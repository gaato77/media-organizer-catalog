from __future__ import annotations

import argparse
import json
from pathlib import Path

from media_catalog_builder.multi_year_probe import consolidate_year_shards


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Consolidate completed annual catalog shards")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    summary = consolidate_year_shards(
        arguments.output_dir,
        arguments.start_year,
        arguments.end_year,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
