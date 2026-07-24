from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from media_catalog_builder.config import CatalogConfig
from media_catalog_builder.http import RetryingHttpClient
from media_catalog_builder.probe import run_probe
from media_catalog_builder.wikidata import WikidataSource


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded Wikidata catalog probe")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=_parse_utc, required=True)
    parser.add_argument("--end", type=_parse_utc, required=True)
    parser.add_argument("--limit", type=int, default=25)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    config = CatalogConfig.load(arguments.config)
    http = RetryingHttpClient(
        user_agent=config.user_agent,
        timeout_seconds=min(float(config.request_timeout_seconds), 70.0),
        request_interval_seconds=max(config.request_interval_seconds, 1.0),
        request_retries=min(config.request_retries, 2),
    )
    source = WikidataSource(config.sparql_endpoint, http)
    summary = run_probe(
        source,
        arguments.output_dir,
        arguments.start,
        arguments.end,
        limit=arguments.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
