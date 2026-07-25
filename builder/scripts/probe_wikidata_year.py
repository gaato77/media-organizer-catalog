from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from media_catalog_builder.config import CatalogConfig
from media_catalog_builder.http import RetryingHttpClient
from media_catalog_builder.wikidata import WikidataSource
from media_catalog_builder.year_probe import run_year_probe


def _utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("through must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("through must include a timezone")
    return parsed.astimezone(UTC)


def _month_number(value: str) -> int:
    try:
        month = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("refresh month must be an integer") from exc
    if not 1 <= month <= 12:
        raise argparse.ArgumentTypeError("refresh month must be between 1 and 12")
    return month


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a resumable full or partial-year probe")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--through", type=_utc_datetime)
    parser.add_argument(
        "--refresh-month",
        action="append",
        type=_month_number,
        default=[],
        help="Month number to rebuild; repeat for more than one month",
    )
    parser.add_argument("--limit", type=int, default=5000)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    config = CatalogConfig.load(arguments.config)
    http = RetryingHttpClient(
        user_agent=config.user_agent,
        timeout_seconds=min(float(config.request_timeout_seconds), 70.0),
        request_interval_seconds=max(config.request_interval_seconds, 1.0),
        request_retries=config.request_retries,
    )
    source = WikidataSource(config.sparql_endpoint, http)
    refresh_months = frozenset(arguments.refresh_month) or None
    summary = run_year_probe(
        source,
        arguments.output_dir,
        arguments.year,
        limit=arguments.limit,
        through=arguments.through,
        refresh_months=refresh_months,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
