import csv
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from federalgraph.extract import agency_reports as reports


class ReportDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = {
            "organization_id": "ORG-1",
            "organization_source_name": "Example Agency",
            "agency_website": "https://example.gov/",
        }
        self.calls = []
        self.pages = {"https://example.gov/robots.txt": (b"User-agent: *\nAllow: /", "text/plain")}

    def fetch(self, url, max_bytes=4_000_000):
        self.calls.append(url)
        body, kind = self.pages[url]
        return body, kind, url

    def crawl(self, **kwargs):
        with patch.object(reports.time, "sleep"):
            return reports.crawl(self.seed, self.root, fetch=self.fetch, **kwargs)

    def html(self, url, text):
        self.pages[url] = (text.encode(), "text/html; charset=utf-8")

    def test_navigation_candidates_years_and_snapshot(self):
        self.html(self.seed["agency_website"], '<a href="/about">About</a>')
        self.html(
            "https://example.gov/about",
            """
            <a href="/apr_2024_final.pdf"><span>FY2024 Annual</span> Performance Report</a>
            <a href="/apr_2024_final.pdf#page=2">Annual Performance Report</a>
            <a href="https://parent.gov/par.pdf">Performance and Accountability Report</a>
            <a href="https://ads.example.com/report.pdf">Annual Report</a>
            <a href="mailto:x@example.gov">Annual Report</a>
        """,
        )
        found, coverage = self.crawl()
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0]["organization_id"], "ORG-1")
        self.assertEqual(found[0]["fiscal_year_candidates"], "2024")
        self.assertEqual(found[0]["discovered_on"], "https://example.gov/about")
        self.assertEqual(found[0]["discovery_status"], "unverified_report_link")
        self.assertEqual(coverage["pages_checked"], 2)
        self.assertEqual(len(list(self.root.glob("*.html"))), 2)
        self.assertNotIn("https://parent.gov/par.pdf", self.calls)

    def test_download_integrity_and_failure_evidence(self):
        self.html(
            self.seed["agency_website"],
            """
            <a href="/strategic-plan.pdf">Strategic Plan 2022–2026</a>
            <a href="/annual-report.pdf">Annual Report</a>""",
        )
        self.pages["https://example.gov/strategic-plan.pdf"] = (
            b"%PDF-1.7 fixture",
            "application/pdf",
        )
        self.pages["https://example.gov/annual-report.pdf"] = (b"not a report", "text/plain")
        found, _ = self.crawl(download_reports=True)
        good, bad = found
        self.assertEqual(good["fiscal_year_candidates"], "2022|2026")
        self.assertEqual(good["download_status"], "downloaded")
        self.assertEqual(good["sha256"], hashlib.sha256(b"%PDF-1.7 fixture").hexdigest())
        self.assertEqual(Path(good["snapshot_path"]).read_bytes(), b"%PDF-1.7 fixture")
        self.assertIn("unsupported_document_type", bad["download_status"])

    def test_robots_exclusion_is_visible(self):
        self.pages["https://example.gov/robots.txt"] = (b"User-agent: *\nDisallow: /", "text/plain")
        found, coverage = self.crawl()
        self.assertEqual(found, [])
        self.assertEqual(coverage["status"], "website_unavailable_or_blocked")
        self.assertEqual(coverage["pages_checked"], 0)
        self.assertIn("robots_disallowed", coverage["errors"])

    def test_missing_or_failed_site_has_coverage(self):
        _, failed = self.crawl()
        self.assertEqual(failed["status"], "website_unavailable_or_blocked")
        self.assertIn("fetch_failed", failed["errors"])
        self.seed["agency_website"] = ""
        _, missing = self.crawl()
        self.assertEqual(missing["status"], "missing_or_invalid_website")

    def test_no_candidate_does_not_claim_no_report(self):
        self.html(self.seed["agency_website"], "<p>Welcome</p>")
        _, coverage = self.crawl()
        self.assertEqual(coverage["status"], "no_candidate_in_bounded_search")
        self.assertFalse(coverage["search_limit_reached"])

    def test_page_bound_prioritizes_2024(self):
        self.html(
            self.seed["agency_website"],
            """
            <a href="/performance-2023">Performance 2023</a>
            <a href="/performance-2025">Performance 2025</a>
            <a href="/performance-2024">Performance 2024</a>""",
        )
        self.html("https://example.gov/performance-2024", "<p>Landing</p>")
        _, coverage = self.crawl(max_pages=2)
        self.assertEqual(self.calls[-1], "https://example.gov/performance-2024")
        self.assertTrue(coverage["search_limit_reached"])
        self.assertEqual(coverage["pages_checked"], 2)

    def test_depth_bound_and_cycle(self):
        self.html(self.seed["agency_website"], '<a href="/about">About</a><a href="/">Reports</a>')
        _, coverage = self.crawl(max_depth=0)
        self.assertTrue(coverage["search_limit_reached"])
        self.assertEqual(coverage["pages_checked"], 1)

    def test_redirect_offsite_is_not_crawled(self):
        def redirect(url, max_bytes=4_000_000):
            return (
                b'<a href="/annual-report.pdf">Annual Report</a>',
                "text/html",
                "https://evil.test/",
            )

        with patch.object(reports.time, "sleep"):
            found, coverage = reports.crawl(self.seed, self.root, fetch=redirect)
        self.assertEqual(found, [])
        self.assertIn("off_site_redirect", coverage["errors"])

    def source_csv(self):
        source = self.root / "sources.csv"
        with source.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["source", "canonical_external_id", "source_name", "website"]
            )
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "source": "USA.gov Agency Index",
                        "canonical_external_id": "ORG-1",
                        "source_name": "Example",
                        "website": "example.gov/",
                    },
                    {
                        "source": "USA.gov Agency Index",
                        "canonical_external_id": "ORG-1",
                        "source_name": "Alias",
                        "website": "https://example.gov/",
                    },
                    {
                        "source": "OPM",
                        "canonical_external_id": "ORG-2",
                        "source_name": "Other",
                        "website": "other.gov",
                    },
                    {
                        "source": "USA.gov Agency Index",
                        "canonical_external_id": "ORG-3",
                        "source_name": "Missing",
                        "website": "",
                    },
                ]
            )
        return source

    def test_sources_dedupe_and_retain_missing_website(self):
        seeds = list(reports.source_seeds(self.source_csv()))
        self.assertEqual(len(seeds), 2)
        self.assertEqual(seeds[0]["agency_website"], "https://example.gov/")
        self.assertEqual(seeds[1]["agency_website"], "")

    def test_exports_and_smoke_run_summary(self):
        self.html(self.seed["agency_website"], "<p>Welcome</p>")
        real_crawl = reports.crawl

        def fake_crawl(seed, raw_dir, **kwargs):
            return real_crawl(seed, raw_dir, fetch=self.fetch, **kwargs)

        with (
            patch.object(reports, "crawl", side_effect=fake_crawl),
            patch.object(reports.time, "sleep"),
        ):
            summary = reports.discover(
                self.source_csv(), self.root / "raw", self.root / "out", max_agencies=1
            )
        self.assertTrue(summary["limited_run"])
        self.assertEqual(summary["agency_website_targets_available"], 2)
        with (self.root / "out/agency_report_sources.csv").open() as handle:
            self.assertEqual(next(csv.reader(handle)), reports.REPORT_FIELDS)
        with (self.root / "out/agency_report_coverage.csv").open() as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 1)

    def test_invalid_limits_fail_before_crawling(self):
        with self.assertRaises(ValueError):
            reports.discover(self.source_csv(), self.root, self.root, max_pages=0)

    def test_external_report_respects_its_robots_policy(self):
        self.html(
            self.seed["agency_website"],
            '<a href="https://parent.gov/par.pdf">Performance and Accountability Report</a>',
        )
        self.pages["https://parent.gov/robots.txt"] = (b"User-agent: *\nDisallow: /", "text/plain")
        found, _ = self.crawl(download_reports=True)
        self.assertIn("robots_disallowed", found[0]["download_status"])
        self.assertNotIn("https://parent.gov/par.pdf", self.calls)

    def test_robots_forbidden_response_blocks_site(self):
        def forbidden(url, max_bytes=4_000_000):
            raise HTTPError(url, 403, "Forbidden", {}, None)

        policy = reports.robots_policy(self.seed["agency_website"], forbidden)
        self.assertFalse(policy.can_fetch(reports.UA, self.seed["agency_website"]))

    def test_combined_report_and_short_year_labels(self):
        self.assertEqual(
            reports.report_type("FY24 Performance Plan and Report", "https://example.gov/x"),
            "performance_plan_and_report",
        )
        self.assertEqual(
            reports.year_candidates("FY24 APR / FY26 APP 2025"), ["2024", "2025", "2026"]
        )

    def test_reports_cli_default_sources_and_output_paths(self):
        from federalgraph.cli import main
        from federalgraph.paths import ProjectPaths

        paths = ProjectPaths(
            self.root,
            self.root / "config",
            self.root / "raw",
            self.root / "cache",
            self.root / "processed",
        )
        with (
            patch.object(ProjectPaths, "discover", return_value=paths),
            patch.object(reports, "discover", return_value={}) as discover,
        ):
            self.assertEqual(main(["reports", "--max-agencies", "5", "--download-reports"]), 0)
        args = discover.call_args.kwargs
        self.assertEqual(args["source_csv"], paths.processed / "organization_sources.csv")
        self.assertEqual(args["max_agencies"], 5)
        self.assertTrue(args["download_reports"])
        self.assertEqual(args["raw_dir"], paths.raw / "agency_reports")

    def test_type_detection_and_domain_boundary(self):
        self.assertEqual(
            reports.report_type("FY2024", "https://example.gov/annual_performance_report.pdf"),
            "annual_performance_report",
        )
        self.assertEqual(
            reports.report_type("Performance & Accountability Report", "https://example.gov/x"),
            "performance_and_accountability_report",
        )
        self.assertTrue(
            reports.same_site("https://reports.example.gov/x", self.seed["agency_website"])
        )
        self.assertFalse(
            reports.same_site("https://example.gov.evil.test/x", self.seed["agency_website"])
        )


if __name__ == "__main__":
    unittest.main()
