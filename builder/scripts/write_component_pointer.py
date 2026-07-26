from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from media_catalog_builder.channel import ComponentType, write_component_atomic
from media_catalog_builder.component_pointer import build_component_pointer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a verified stable catalog component pointer"
    )
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--installed-database", type=Path, required=True)
    parser.add_argument("--component-id", required=True)
    parser.add_argument(
        "--component-type", choices=[item.value for item in ComponentType], required=True
    )
    parser.add_argument("--from-year", type=int, required=True)
    parser.add_argument("--to-year", type=int, required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--priority", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        component = build_component_pointer(
            arguments.release_dir,
            arguments.installed_database,
            component_id=arguments.component_id,
            component_type=ComponentType(arguments.component_type),
            from_year=arguments.from_year,
            to_year=arguments.to_year,
            release_tag=arguments.release_tag,
            priority=arguments.priority,
        )
        write_component_atomic(arguments.output, component)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
