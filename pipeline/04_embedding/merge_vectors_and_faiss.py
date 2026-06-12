"""Script to merge the 6 legal embedding shard folders and the FAISS indexes/payloads."""

import os
import sys
import json
import shutil
import logging
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

def link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)

def merge_vector_shards(data_dir: Path, output_dir: Path):
    logging.info("=== STEP 1: Merging Vector Embedding Shards ===")
    
    # Define exact paths to include in sequence
    shard_dirs = [
        data_dir / "legal_embedding_1" / "data" / "shards_member_1" / "gpu0",
        data_dir / "legal_embedding_1" / "data" / "shards_member_1" / "gpu1",
        data_dir / "legal_embedding_3" / "data" / "shards_member_2" / "gpu0",
        data_dir / "legal_embedding_3" / "data" / "shards_member_2" / "gpu1",
        data_dir / "legal_embedding_2" / "data" / "shards_member_3" / "gpu0",
        data_dir / "legal_embedding_2" / "data" / "shards_member_3" / "gpu1",
        data_dir / "legal_embedding_4" / "data" / "shards_member_4" / "gpu0",
        data_dir / "legal_embedding_4" / "data" / "shards_member_4" / "gpu1",
        data_dir / "legal_embedding_5" / "data" / "shards_member_5" / "gpu0",
        data_dir / "legal_embedding_5" / "data" / "shards_member_5" / "gpu1",
        data_dir / "legal_embedding_6" / "data" / "repair_shards",
    ]
    
    # Check if all directories exist
    missing_dirs = [d for d in shard_dirs if not d.exists()]
    if missing_dirs:
        logging.error(f"Missing source directories: {missing_dirs}")
        sys.exit(1)
        
    output_shards_dir = output_dir / "data" / "merged_shards"
    output_shards_dir.mkdir(parents=True, exist_ok=True)
    
    merged_shards = {}
    global_index = 0
    total_rows = 0
    base_metadata = {}
    
    for shard_dir in shard_dirs:
        manifest_path = shard_dir / "manifest.json"
        logging.info(f"Processing manifest: {manifest_path}")
        
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
            
        if not base_metadata:
            for k, v in manifest_data.items():
                if k != "shards" and k != "completed_rows":
                    base_metadata[k] = v
                    
        shards = manifest_data.get("shards", {})
        # Sort keys to preserve order
        sorted_keys = sorted(shards.keys(), key=lambda x: int(x) if x.isdigit() else x)
        
        for shard_key in sorted_keys:
            shard_info = shards[shard_key]
            if shard_info.get("status") != "done":
                logging.warning(f"Skipping incomplete shard {shard_key} in {shard_dir}")
                continue
                
            orig_vectors_name = shard_info.get("vectors")
            orig_payload_name = shard_info.get("payload")
            
            orig_vectors_path = shard_dir / orig_vectors_name
            orig_payload_path = shard_dir / orig_payload_name
            
            new_vectors_name = f"vectors_shard_{global_index:05d}.npy"
            new_payload_name = f"payload_shard_{global_index:05d}.parquet"
            
            dest_vectors_path = output_shards_dir / new_vectors_name
            dest_payload_path = output_shards_dir / new_payload_name
            
            # Link or copy
            link_or_copy(orig_vectors_path, dest_vectors_path)
            link_or_copy(orig_payload_path, dest_payload_path)
            
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
            
    # Write merged manifest
    merged_manifest = base_metadata.copy()
    merged_manifest["shards"] = merged_shards
    merged_manifest["completed_rows"] = total_rows
    
    output_manifest_path = output_shards_dir / "manifest.json"
    with open(output_manifest_path, "w", encoding="utf-8") as f:
        json.dump(merged_manifest, f, ensure_ascii=False, indent=2)
        
    logging.info(f"Vector shards merge complete! Total shards: {global_index}, Total rows: {total_rows}")
    logging.info(f"Manifest written to: {output_manifest_path}")


def merge_faiss_indexes(data_dir: Path, output_dir: Path):
    logging.info("=== STEP 2: Merging FAISS Indexes and Payloads ===")
    
    import faiss
    
    faiss_dir = data_dir / "legal_embedding_6" / "faiss_members"
    manifest_path = faiss_dir / "manifest.json"
    
    if not manifest_path.exists():
        logging.error(f"Missing FAISS manifest: {manifest_path}")
        sys.exit(1)
        
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
        
    indexes = manifest_data.get("indexes", {})
    # Determine the order: member_1 to member_5, then repair
    ordered_names = ["member_1", "member_2", "member_3", "member_4", "member_5", "repair"]
    
    # Verify that all indexes exist in manifest and are done
    for name in ordered_names:
        if name not in indexes:
            logging.error(f"Index {name} not found in FAISS manifest")
            sys.exit(1)
        if indexes[name].get("status") != "done":
            logging.error(f"Index {name} status is not done")
            sys.exit(1)
            
    output_faiss_dir = output_dir / "faiss_members"
    output_faiss_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Copy trained.faiss to the output directory
    trained_src = faiss_dir / "trained.faiss"
    trained_dst = output_faiss_dir / "trained.faiss"
    if trained_src.exists():
        logging.info(f"Copying trained.faiss to {trained_dst}")
        link_or_copy(trained_src, trained_dst)
        
    # 2. Merge FAISS indexes and Arrow payloads
    merged_index = None
    merged_tables = []
    current_shift = 0
    
    for name in ordered_names:
        idx_info = indexes[name]
        idx_file = faiss_dir / idx_info["index"]
        payload_file = faiss_dir / idx_info["payload"]
        
        logging.info(f"Loading {name} FAISS index: {idx_file}")
        idx = faiss.read_index(str(idx_file))
        
        logging.info(f"Loading {name} Arrow payload: {payload_file}")
        handle = pa.memory_map(str(payload_file), "r")
        table = ipc.open_file(handle).read_all()
        handle.close()
        
        if idx.ntotal != table.num_rows:
            logging.error(f"Row count mismatch in {name}: index={idx.ntotal}, payload={table.num_rows}")
            sys.exit(1)
            
        logging.info(f"Merging index {name} with shift {current_shift}")
        if merged_index is None:
            # First one: clone or start with it
            merged_index = idx
        else:
            merged_index.merge_from(idx, current_shift)
            
        merged_tables.append(table)
        current_shift += table.num_rows
        
    # 3. Concatenate and save the Arrow table
    logging.info("Concatenating Arrow payload tables...")
    merged_table = pa.concat_tables(merged_tables)
    
    if merged_index.ntotal != merged_table.num_rows:
        logging.error(f"Merged row count mismatch: index={merged_index.ntotal}, table={merged_table.num_rows}")
        sys.exit(1)
        
    dest_index_path = output_faiss_dir / "merged.faiss"
    dest_payload_path = output_faiss_dir / "merged.payload.arrow"
    
    logging.info(f"Writing merged FAISS index to {dest_index_path}...")
    faiss.write_index(merged_index, str(dest_index_path))
    
    logging.info(f"Writing merged Arrow payload to {dest_payload_path}...")
    payload_sink = pa.OSFile(str(dest_payload_path), "wb")
    payload_writer = ipc.new_file(
        payload_sink,
        merged_table.schema,
        options=ipc.IpcWriteOptions(compression="zstd"),
    )
    payload_writer.write_table(merged_table)
    payload_writer.close()
    payload_sink.close()
    
    # 4. Generate the new manifest.json
    new_manifest = {
        "format": "faiss_members_v2_deduplicated",
        "indexes": {
            "merged": {
                "status": "done",
                "rows": merged_index.ntotal,
                "input_rows": manifest_data.get("completed_rows", merged_index.ntotal),
                "duplicates_removed": manifest_data.get("duplicates_removed", 0),
                "index": "merged.faiss",
                "payload": "merged.payload.arrow"
            }
        },
        "factory": manifest_data.get("factory", "IVF4096,PQ64x8"),
        "completed_rows": merged_index.ntotal,
        "unique_rows": merged_index.ntotal,
        "duplicates_removed": manifest_data.get("duplicates_removed", 0)
    }
    
    dest_manifest_path = output_faiss_dir / "manifest.json"
    with open(dest_manifest_path, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, ensure_ascii=False, indent=2)
        
    logging.info(f"FAISS indexes merge complete! Total rows: {merged_index.ntotal}")
    logging.info(f"Manifest written to: {dest_manifest_path}")

def main():
    # Workspace paths relative to the script location or run directory
    workspace_dir = Path(__file__).resolve().parents[2]
    data_dir = workspace_dir / "data"
    output_dir = data_dir / "legal_embedding"
    
    logging.info(f"Workspace directory: {workspace_dir}")
    logging.info(f"Data directory: {data_dir}")
    logging.info(f"Output directory: {output_dir}")
    
    merge_vector_shards(data_dir, output_dir)
    merge_faiss_indexes(data_dir, output_dir)
    logging.info("ALL MERGING OPERATIONS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
