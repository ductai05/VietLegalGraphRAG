import argparse
import json
import logging
import os
import shutil
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description="Merge distributed member embedding shards into a single unified directory")
    parser.add_argument("--input-dir", type=Path, default=Path("/home/ml/VietLegalGraphRAG/data/member_embeddings"),
                        help="Input directory containing member subfolders (member-1, member-2, etc.)")
    parser.add_argument("--output-dir", type=Path, default=Path("/home/ml/VietLegalGraphRAG/data/legal_embedding/data/merged_shards"),
                        help="Output directory to write the merged shards and unified manifest")
    parser.add_argument("--use-link", action="store_true", default=True,
                        help="Use hard links instead of copying to save disk space and run instantly (falls back to copying if cross-device)")
    parser.add_argument("--no-link", action="store_false", dest="use_link",
                        help="Force copy instead of hard link")
    return parser.parse_args()

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

def main():
    args = parse_args()
    setup_logging()

    if not args.input_dir.exists():
        logging.error("Input directory %s does not exist.", args.input_dir)
        return

    # Find all manifest.json files recursively
    manifest_paths = sorted(list(args.input_dir.glob("**/manifest.json")))
    if not manifest_paths:
        logging.error("No manifest.json files found recursively in %s", args.input_dir)
        return

    logging.info("Found %d manifest file(s) to merge.", len(manifest_paths))

    args.output_dir.mkdir(parents=True, exist_ok=True)

    merged_shards = {}
    global_index = 0
    total_rows = 0
    base_metadata = {}

    for manifest_path in manifest_paths:
        logging.info("Processing manifest: %s", manifest_path.relative_to(args.input_dir))
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception as e:
            logging.error("Failed to read %s: %s", manifest_path, e)
            continue

        # Extract base metadata from the first valid manifest to carry over
        if not base_metadata:
            for k, v in manifest_data.items():
                if k != "shards" and k != "completed_rows":
                    base_metadata[k] = v

        shards = manifest_data.get("shards", {})
        # Sort keys to preserve original shard sequence from each member
        sorted_keys = sorted(shards.keys(), key=lambda x: int(x) if x.isdigit() else x)

        for shard_key in sorted_keys:
            shard_info = shards[shard_key]
            if shard_info.get("status") != "done":
                logging.warning("Skipping incomplete shard %s in %s", shard_key, manifest_path)
                continue

            orig_vectors_name = shard_info.get("vectors")
            orig_payload_name = shard_info.get("payload")

            if not orig_vectors_name or not orig_payload_name:
                logging.warning("Missing filenames for shard %s, skipping", shard_key)
                continue

            orig_vectors_path = manifest_path.parent / orig_vectors_name
            orig_payload_path = manifest_path.parent / orig_payload_name

            if not orig_vectors_path.exists() or not orig_payload_path.exists():
                logging.warning("Shard files not found: %s or %s, skipping", orig_vectors_path, orig_payload_path)
                continue

            # Generate unique sequential filenames
            new_vectors_name = f"vectors_shard_{global_index:05d}.npy"
            new_payload_name = f"payload_shard_{global_index:05d}.parquet"

            dest_vectors_path = args.output_dir / new_vectors_name
            dest_payload_path = args.output_dir / new_payload_name

            # Perform link/copy
            for src, dest in [(orig_vectors_path, dest_vectors_path), (orig_payload_path, dest_payload_path)]:
                if dest.exists():
                    dest.unlink()
                
                success = False
                if args.use_link:
                    try:
                        os.link(src, dest)
                        success = True
                    except OSError:
                        # Fallback to copy if hard link fails (e.g., cross-device)
                        pass
                
                if not success:
                    shutil.copy2(src, dest)

            # Record in merged manifest
            rows = shard_info.get("rows", 0)
            merged_shards[f"{global_index:05d}"] = {
                "status": "done",
                "rows": rows,
                "first_chunk_id": shard_info.get("first_chunk_id"),
                "last_chunk_id": shard_info.get("last_chunk_id"),
                "vectors": new_vectors_name,
                "payload": new_payload_name
            }

            total_rows += rows
            global_index += 1

    # Build final manifest
    merged_manifest = base_metadata.copy()
    merged_manifest["shards"] = merged_shards
    merged_manifest["completed_rows"] = total_rows

    output_manifest_path = args.output_dir / "manifest.json"
    with open(output_manifest_path, "w", encoding="utf-8") as f:
        json.dump(merged_manifest, f, ensure_ascii=False, indent=2)

    logging.info("Merging complete!")
    logging.info("Total shards merged: %d", global_index)
    logging.info("Total rows merged: %d", total_rows)
    logging.info("Unified manifest written to: %s", output_manifest_path)

if __name__ == "__main__":
    main()
