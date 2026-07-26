from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from media_catalog_builder.channel import StableChannel, load_component, write_stable_channel_atomic


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assemble the stable catalog channel")
    parser.add_argument("--component", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--published-at")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        channel = StableChannel(
            schema_version=1,
            channel="stable",
            published_at=(
                datetime.now(UTC) if arguments.published_at is None else arguments.published_at
            ),
            components=tuple(load_component(path) for path in arguments.component),
        )
        write_stable_channel_atomic(arguments.output, channel)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
