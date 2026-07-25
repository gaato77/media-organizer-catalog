from __future__ import annotations

import argparse
import json
from pathlib import Path

from media_catalog_builder.config import CatalogConfig
from media_catalog_builder.http import RetryingHttpClient
from media_catalog_builder.wikidata import WikidataSource
from media_catalog_builder.year_probe import run_year_probe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a resumable full-year Wikidata probe")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
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
    summary = run_year_probe(
        source,
        arguments.output_dir,
        arguments.year,
        limit=arguments.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
