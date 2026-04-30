"""Script to download the Vietnamese Legal Documents dataset from HuggingFace."""

import os
from huggingface_hub import snapshot_download

def download():
    # Define destination path
    raw_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "raw", "vietnamese-legal-documents"
    )
    os.makedirs(raw_dir, exist_ok=True)
    
    print(f"Downloading dataset from HuggingFace to {raw_dir}...")
    snapshot_download(
        repo_id="th1nhng0/vietnamese-legal-documents",
        repo_type="dataset",
        local_dir=raw_dir,
        local_dir_use_symlinks=False
    )
    print("Download completed successfully!")

if __name__ == "__main__":
    download()

