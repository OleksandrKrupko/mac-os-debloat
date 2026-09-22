#!/usr/bin/env python3
"""Fill README.md and package.json catalog counts from EMBEDDED_LABELS.

The numbers in the README are real, but they are not maintained by hand.
The script finds each count from surrounding prose (including inside
backticks and fenced code) and rewrites the digits. package.json's
description uses `disable N non-essential`.

After adding or removing a catalog label:

    python3 extras/sync-readme.py

CI / a test can refuse a stale README:

    python3 extras/sync-readme.py --check
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_debloat():
    path = ROOT / "debloat"
    loader = importlib.machinery.SourceFileLoader("debloat", str(path))
    spec = importlib.util.spec_from_loader("debloat", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["debloat"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="exit 1 if README.md or package.json are stale, write nothing",
    )
    args = parser.parse_args()
    stale = load_debloat().sync_docs(ROOT, check=args.check)
    if not stale:
        print("README.md and package.json match the catalog")
        return 0
    joined = ", ".join(stale)
    if args.check:
        print(f"stale catalog counts in {joined} — run python3 extras/sync-readme.py",
              file=sys.stderr)
        return 1
    print(f"updated {joined}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
