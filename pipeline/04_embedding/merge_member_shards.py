"""Merge gpu0/gpu1 shard outputs from all members into one Qdrant-ready directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from member_shards_utils import format_verify_report, merge_member_shards


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--search-root",
        type=Path,
        action="append",
        required=True,
        help="Directory to search for shards_member_* and embed_payload_v0.1.parquet.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Merged output directory (vectors, payload shards, manifest.json).",
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
        report = merge_member_shards(
            args.search_root,
            args.output_dir,
            num_members=args.num_members,
            spot_check_vectors=not args.no_spot_check,
        )
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        print(f"MERGE FAILED\n{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(format_verify_report(report))
    print(f"\nMerged shards written to: {args.output_dir.resolve()}")
    print("Next step:")
    print(
        f"  python build_qdrant.py --shards-dir {args.output_dir} "
        "--storage-dir <qdrant_storage> --recreate"
    )


if __name__ == "__main__":
    main()
