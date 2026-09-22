from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
from typing import Optional, Sequence

from federalgraph import __version__
from federalgraph.config import Settings
from federalgraph.logging_config import configure_logging
from federalgraph.paths import ProjectPaths
from federalgraph.pipeline import Pipeline


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


def main(argv: Optional[Sequence[str]] = None) -> int:
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
    if args.command == "organizations":
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

    parser.error(f"Unsupported command: {args.command}")
    return 2
