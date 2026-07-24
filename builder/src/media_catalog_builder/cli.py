from __future__ import annotations

import argparse
from collections.abc import Sequence

COMMANDS = ("build-full", "build-update", "validate", "lookup", "apply-delta")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="media-catalog-builder")
    parser.add_argument("command", choices=COMMANDS)
    return parser


def _coerce_exit_code(code: str | int | None) -> int:
    if isinstance(code, int):
        return code
    if code is None:
        return 0
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        return _coerce_exit_code(exc.code)
    return 0


def console_main() -> int:
    return main()
