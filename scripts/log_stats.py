#!/usr/bin/env python3
"""Summarize a local log file and optionally save the statistics as JSON."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from mho import logstats  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("log", help="a local server log file")
    p.add_argument("--json", help="also write the numbers to this file")
    args = p.parse_args(argv)
    if not os.path.isfile(args.log):
        print(f"no such log: {args.log}", file=sys.stderr)
        return 2
    stats = logstats.analyse(logstats.read_lines(args.log))
    print("\n".join(logstats.render(stats, os.path.basename(args.log))))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
