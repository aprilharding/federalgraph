"""Discover report evidence on websites asserted by the USA.gov agency index.

A report link is a candidate, not a program assertion. Bounded searches always
emit coverage rows; no candidate found does not mean that an agency has no report.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

LOGGER = logging.getLogger(__name__)
UA = "FederalGraph/0.8 (+public-interest report discovery)"
REPORT_FIELDS = [
    "organization_id",
    "organization_source_name",
    "agency_website",
    "report_type",
    "report_title",
    "fiscal_year_candidates",
    "report_url",
    "discovered_on",
    "discovery_status",
    "download_status",
    "snapshot_path",
    "sha256",
]
COVERAGE_FIELDS = [
    "organization_id",
    "organization_source_name",
    "agency_website",
    "status",
    "pages_checked",
    "report_candidates",
    "search_limit_reached",
    "errors",
    "checked_at",
]
TYPES = (
    (
        "performance_plan_and_report",
        r"performance\s+(?:plans?\s+(?:and|&)?\s*reports?|"
        r"reports?\s+(?:and|&)\s+plans?)",
    ),
    (
        "performance_and_accountability_report",
        r"performance\s+(?:and|&)\s+accountability\s+reports?",
    ),
    ("annual_performance_report", r"annual\s+performance\s+reports?"),
    ("agency_financial_report", r"agency\s+financial\s+reports?"),
    ("annual_performance_plan", r"annual\s+performance\s+plans?"),
    ("strategic_plan", r"strategic\s+plans?"),
    ("congressional_budget_justification", r"congressional\s+budget\s+justifications?"),
    ("performance_report", r"performance\s+reports?"),
    ("annual_report", r"annual\s+reports?"),
)
NAVIGATION = re.compile(
    r"about|budget|performance|accountability|strategic|reports?|financial|plans?|"
    r"publications|transparency|resources",
    re.I,
)


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.href = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join(" ".join(self.label).split())))
            self.href = None


def report_type(label: str, url: str) -> str:
    # URL filenames provide useful evidence when anchor text is just "FY 2024".
    text = re.sub(r"[-_+/]+", " ", f"{label} {unquote(urlsplit(url).path)}")
    for kind, pattern in TYPES:
        if re.search(pattern, text, re.I):
            return kind
    return ""


def normalized_url(url: str) -> str:
    return urldefrag(url)[0].strip()


def same_site(url: str, seed: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    root = (urlsplit(seed).hostname or "").lower().removeprefix("www.")
    return bool(host and root and (host == root or host.endswith("." + root)))


def official_document(url: str, seed: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return same_site(url, seed) or host.endswith((".gov", ".mil"))


def read_url(url: str, max_bytes: int = 4_000_000):
    request = Request(url, headers={"User-Agent": UA})
    with urlopen(request, timeout=25) as response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError("response exceeds configured byte limit")
        return body, response.headers.get("Content-Type", ""), response.geturl()


def year_candidates(text: str) -> list[str]:
    years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text))
    years.update("20" + y for y in re.findall(r"\bFY[ _-]?(\d{2})(?!\d)", text, re.I))
    return sorted(years)


def robots_policy(url: str, fetch):
    policy = RobotFileParser()
    try:
        body, _, _ = fetch(urljoin(url, "/robots.txt"))
        policy.parse(body.decode("utf-8", errors="replace").splitlines())
    except HTTPError as exc:
        policy.parse(["User-agent: *", "Disallow: /"] if exc.code in {401, 403} else [])
    except Exception:
        # Missing policy does not imply that the site's pages are accessible.
        policy.parse([])
    return policy


def source_seeds(source_csv: Path):
    seen = set()
    with source_csv.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not str(row.get("source", "")).startswith("USA.gov"):
                continue
            website = normalized_url(row.get("website", ""))
            if website and not urlsplit(website).scheme:
                website = "https://" + website
            oid = row.get("canonical_external_id", "")
            key = (oid or row.get("source_name", ""), website)
            if key in seen:
                continue
            seen.add(key)
            yield {
                "organization_id": oid,
                "organization_source_name": row.get("source_name", ""),
                "agency_website": website,
            }


def crawl(
    seed: dict,
    raw_dir: Path,
    *,
    max_pages: int = 40,
    max_depth: int = 3,
    download_reports: bool = False,
    fetch=read_url,
):
    website = seed["agency_website"]
    errors, reports, seen, visited = [], {}, set(), 0
    checked_at = datetime.now(timezone.utc).isoformat()
    if urlsplit(website).scheme not in {"https", "http"} or not urlsplit(website).hostname:
        return [], {
            **seed,
            "status": "missing_or_invalid_website",
            "pages_checked": 0,
            "report_candidates": 0,
            "search_limit_reached": False,
            "errors": "",
            "checked_at": checked_at,
        }
    queue = deque([(website, 0)])
    scheduled = {website}
    depth_limited = False
    robots = robots_policy(website, fetch)
    document_policies = {urlsplit(website).netloc: robots}
    while queue and visited < max_pages:
        url, depth = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if not robots.can_fetch(UA, url):
            errors.append(f"robots_disallowed:{url}")
            continue
        visited += 1
        try:
            body, content_type, final_url = fetch(url)
            if not same_site(final_url, website):
                errors.append(f"off_site_redirect:{url} -> {final_url}")
                continue
            if "html" not in content_type.lower():
                continue
            digest = hashlib.sha256(body).hexdigest()
            snapshot = raw_dir / (digest + ".html")
            snapshot.write_bytes(body)
            parser = Links()
            parser.feed(body.decode("utf-8", errors="replace"))
            follow = []
            for href, label in parser.links:
                target = normalized_url(urljoin(final_url, href))
                if urlsplit(target).scheme not in {"http", "https"}:
                    continue
                kind = report_type(label, target)
                if kind and official_document(target, website):
                    years = year_candidates(f"{label} {unquote(target)}")
                    reports.setdefault(
                        target,
                        {
                            **seed,
                            "report_type": kind,
                            "report_title": label,
                            "fiscal_year_candidates": "|".join(years),
                            "report_url": target,
                            "discovered_on": final_url,
                            "discovery_status": "unverified_report_link",
                            "download_status": "not_requested",
                            "snapshot_path": "",
                            "sha256": "",
                        },
                    )
                if same_site(target, website) and NAVIGATION.search(label + " " + target):
                    if not re.search(r"\.(?:pdf|xlsx?|docx?|zip|jpg|png)(?:\?|$)", target, re.I):
                        if depth >= max_depth:
                            depth_limited = depth_limited or target not in scheduled
                            continue
                        # FY2024 first, then newest named years, then navigation.
                        years = year_candidates(target + " " + label)
                        newest = max(map(int, years), default=0)
                        priority = (0 if "2024" in years else 1, 0 if kind else 1, -newest, target)
                        follow.append((priority, target))
            for _, target in sorted(follow):
                if target not in scheduled:
                    scheduled.add(target)
                    queue.append((target, depth + 1))
        except Exception as exc:
            errors.append(f"fetch_failed:{url}:{type(exc).__name__}:{exc}")
        time.sleep(0.1)
    if download_reports:
        for report in reports.values():
            try:
                url = report["report_url"]
                host = urlsplit(url).netloc
                if host not in document_policies:
                    document_policies[host] = robots_policy(url, fetch)
                if not document_policies[host].can_fetch(UA, url):
                    raise ValueError("robots_disallowed")
                body, content_type, final_url = fetch(url, max_bytes=25_000_000)
                if not official_document(final_url, website):
                    raise ValueError("off_site_redirect")
                pdf = body.startswith(b"%PDF-")
                html = "html" in content_type.lower()
                if not pdf and not html:
                    raise ValueError("unsupported_document_type")
                digest = hashlib.sha256(body).hexdigest()
                snapshot = raw_dir / (digest + (".pdf" if pdf else ".html"))
                snapshot.write_bytes(body)
                report.update(
                    download_status="downloaded", snapshot_path=str(snapshot), sha256=digest
                )
            except Exception as exc:
                report["download_status"] = f"failed:{type(exc).__name__}:{exc}"
    status = "report_candidates_found" if reports else "no_candidate_in_bounded_search"
    if visited == 0 or visited == 1 and errors and not reports:
        status = "website_unavailable_or_blocked"
    coverage = {
        **seed,
        "status": status,
        "pages_checked": visited,
        "report_candidates": len(reports),
        "search_limit_reached": bool(queue) or depth_limited,
        "errors": json.dumps(errors),
        "checked_at": checked_at,
    }
    return list(reports.values()), coverage


def discover(
    source_csv: Path,
    raw_dir: Path,
    out_dir: Path,
    *,
    max_pages: int = 40,
    max_depth: int = 3,
    workers: int = 4,
    max_agencies=None,
    download_reports=False,
):
    if min(max_pages, workers) < 1 or max_depth < 0:
        raise ValueError("Page/worker limits must be positive and depth must be nonnegative")
    if max_agencies is not None and max_agencies < 1:
        raise ValueError("max_agencies must be positive")
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = list(source_seeds(source_csv))
    if not seeds:
        raise ValueError("No USA.gov source assertions found in organization source CSV")
    targets_available = len(seeds)
    if max_agencies is not None:
        seeds = seeds[:max_agencies]
    reports, coverage = [], []

    def task(seed):
        return crawl(
            seed,
            raw_dir,
            max_pages=max_pages,
            max_depth=max_depth,
            download_reports=download_reports,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for found, result in pool.map(task, seeds):
            reports.extend(found)
            coverage.append(result)
            LOGGER.info(
                "Report discovery %s: %s (%s candidates)",
                result["organization_source_name"],
                result["status"],
                len(found),
            )
    for filename, rows, fields in (
        ("agency_report_sources.csv", reports, REPORT_FIELDS),
        ("agency_report_coverage.csv", coverage, COVERAGE_FIELDS),
    ):
        with (out_dir / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    summary = {
        "agency_website_targets_available": targets_available,
        "limited_run": len(seeds) < targets_available,
        "agency_website_targets": len(seeds),
        "report_candidates": len(reports),
        "targets_with_candidates": sum(bool(r["report_candidates"]) for r in coverage),
        "reports_downloaded": sum(r["download_status"] == "downloaded" for r in reports),
        "max_pages_per_target": max_pages,
        "max_depth": max_depth,
    }
    (out_dir / "agency_report_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary
