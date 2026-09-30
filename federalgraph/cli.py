from __future__ import annotations

import argparse
import json
import platform
from collections.abc import Sequence
from pathlib import Path

from federalgraph import __version__
from federalgraph.config import Settings
from federalgraph.extract import agency_reports
from federalgraph.logging_config import configure_logging
from federalgraph.paths import ProjectPaths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="federalgraph",
        description="Compile authoritative federal data into a canonical knowledge graph.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--verbose", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Check the local development environment.")
    subparsers.add_parser("sources", help="List configured data sources.")

    organizations = subparsers.add_parser(
        "organizations", help="Build the canonical organization registry."
    )
    organizations.add_argument(
        "--fpi-csv", type=Path, help="Optional CSV with Department and Agency columns."
    )
    organizations.add_argument(
        "--source-csv",
        type=Path,
        help="Reuse an existing organization_sources.csv instead of downloading sources.",
    )
    organizations.add_argument("--skip-usagov", action="store_true")
    organizations.add_argument("--skip-federal-register", action="store_true")
    organizations.add_argument("--skip-govinfo", action="store_true")
    organizations.add_argument("--skip-opm", action="store_true")

    programs = subparsers.add_parser(
        "programs",
        help="Build canonical program identities, authorities, purposes, and org mappings.",
    )
    programs.add_argument(
        "--source-csv",
        type=Path,
        help="Reuse an existing program source-record CSV instead of downloading primary sources.",
    )
    programs.add_argument(
        "--performance-csv",
        type=Path,
        help="Optional archived Performance.gov FPI reference-table CSV.",
    )
    programs.add_argument(
        "--supplemental-csv",
        type=Path,
        action="append",
        default=[],
        help=(
            "Additional official program candidate CSV (repeatable), "
            "e.g. curated CBJ/Budget extracts."
        ),
    )
    programs.add_argument("--skip-sam", action="store_true")
    programs.add_argument("--skip-treasury", action="store_true")
    programs.add_argument("--skip-performance", action="store_true")
    programs.add_argument("--skip-uscode", action="store_true")
    programs.add_argument(
        "--max-sam-pages",
        type=int,
        help="Limit SAM pages for a smoke test. Omit for the full inventory.",
    )
    reports = subparsers.add_parser(
        "reports", help="Discover agency performance report candidates from saved USA.gov websites."
    )
    reports.add_argument(
        "--source-csv",
        type=Path,
        help="Organization sources CSV; defaults to data/processed/organization_sources.csv.",
    )
    reports.add_argument("--max-pages", type=int, default=40)
    reports.add_argument("--max-depth", type=int, default=3)
    reports.add_argument("--workers", type=int, default=4)
    reports.add_argument("--max-agencies", type=int, help="Limit website targets for a smoke test.")
    reports.add_argument(
        "--download-reports",
        action="store_true",
        help="Save candidate PDF/HTML documents as raw evidence.",
    )
    return parser


def command_doctor(paths: ProjectPaths) -> int:
    paths.ensure_data_dirs()
    checks = {
        "python": platform.python_version(),
        "project_root": str(paths.root),
        "config_exists": (paths.config / "sources.json").exists(),
        "raw_directory": paths.raw.exists(),
        "cache_directory": paths.cache.exists(),
        "processed_directory": paths.processed.exists(),
    }
    print(json.dumps(checks, indent=2))
    return 0 if all(value is not False for value in checks.values()) else 1


def command_sources(paths: ProjectPaths) -> int:
    settings = Settings.load(paths.config / "sources.json")
    sources = settings.values.get("sources", {})
    for name, details in sorted(sources.items()):
        state = "enabled" if details.get("enabled", False) else "disabled"
        print(f"{name}: {state} ({details.get('kind', 'unknown')})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    try:
        paths = ProjectPaths.discover(Path.cwd())
    except RuntimeError as exc:
        parser.error(str(exc))

    if args.command == "doctor":
        return command_doctor(paths)
    if args.command == "sources":
        return command_sources(paths)
    if args.command == "reports":
        paths.ensure_data_dirs()
        summary = agency_reports.discover(
            source_csv=(
                args.source_csv.resolve()
                if args.source_csv
                else paths.processed / "organization_sources.csv"
            ),
            raw_dir=paths.raw / "agency_reports",
            out_dir=paths.processed,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            workers=args.workers,
            max_agencies=args.max_agencies,
            download_reports=args.download_reports,
        )
        print(json.dumps(summary, indent=2))
        print(f"\nOutputs: {paths.processed}")
        return 0
    if args.command == "organizations":
        from federalgraph.pipeline import Pipeline

        summary = Pipeline(paths).run_organizations(
            fpi_csv=args.fpi_csv.resolve() if args.fpi_csv else None,
            source_csv=args.source_csv.resolve() if args.source_csv else None,
            skip_usagov=args.skip_usagov,
            skip_federal_register=args.skip_federal_register,
            skip_govinfo=args.skip_govinfo,
            skip_opm=args.skip_opm,
        )
        print(json.dumps(summary, indent=2))
        print(f"\nOutputs: {paths.processed}")
        return 0
    if args.command == "programs":
        from federalgraph.pipeline import Pipeline

        summary = Pipeline(paths).run_programs(
            source_csv=args.source_csv.resolve() if args.source_csv else None,
            performance_csv=args.performance_csv.resolve() if args.performance_csv else None,
            supplemental_csvs=[path.resolve() for path in args.supplemental_csv],
            skip_sam=args.skip_sam,
            skip_treasury=args.skip_treasury,
            skip_performance=args.skip_performance,
            skip_uscode=args.skip_uscode,
            max_sam_pages=args.max_sam_pages,
        )
        print(json.dumps(summary, indent=2))
        print(f"\nOutputs: {paths.processed}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2
