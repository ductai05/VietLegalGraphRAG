"""Verify embedding shards produced by parallel KAGGLE_MEMBER runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from member_shards_utils import format_verify_report, verify_member_shards


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--search-root",
        type=Path,
        action="append",
        required=True,
        help="Directory to search for shards_member_* and embed_payload_v0.1.parquet.",
    )
    parser.add_argument("--num-members", type=int, default=5)
    parser.add_argument(
        "--no-spot-check",
        action="store_true",
        help="Skip loading vector files for shape/normalization checks.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        report = verify_member_shards(
            args.search_root,
            num_members=args.num_members,
            spot_check_vectors=not args.no_spot_check,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"VERIFICATION FAILED\n{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(format_verify_report(report))


if __name__ == "__main__":
    main()
