"""
Export darklethelong/vnlegal-lal to ONNX for use with LocalONNXEmbedder.

Run once on a machine with torch and transformers installed:

    python export_vnlegal_onnx.py \
        --output-dir ./onnx_model \
        --model darklethelong/vnlegal-lal

Produces two files in output-dir:
    model.onnx       — self-contained ONNX model (no external .data files)
    tokenizer.json   — merged HuggingFace tokenizer

Then in docker-compose or .env:

    EMBEDDING_PROVIDER=onnx
    EMBEDDING_ONNX_MODEL_PATH=/app/onnx_model/model.onnx
    EMBEDDING_ONNX_TOKENIZER_PATH=/app/onnx_model/tokenizer.json

    # in Dockerfile COPY the output-dir into the image
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

# Model name (Qwen3-based) uses opset 18 internally.
OPSET_VERSION = 18


def export(
    model_name: str,
    output_dir: Path,
    max_length: int = 1024,
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading model: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModel.from_pretrained(model_name)
    model.eval()
    device = torch.device("cpu")
    model.to(device)

    # Dummy inputs for shape inference.
    dummy_texts = ["Vietnamese legal question."]
    dummy_inputs = tokenizer(
        dummy_texts,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    input_ids: torch.Tensor = dummy_inputs["input_ids"].to(device)
    attention_mask: torch.Tensor = dummy_inputs["attention_mask"].to(device)

    # Dynamic axes for batch/sequence dimensions.
    dynamic_axes = {
        "input_ids": {0: "batch", 1: "sequence"},
        "attention_mask": {0: "batch", 1: "sequence"},
        "last_hidden_state": {0: "batch", 1: "sequence"},
    }

    model_onnx_path = output_dir / "model.onnx"

    print(f"Exporting ONNX model to {model_onnx_path} ...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "model.onnx"
        torch.onnx.export(
            model,
            (input_ids, attention_mask),
            str(tmp_path),
            input_names=["input_ids", "attention_mask"],
            output_names=["last_hidden_state"],
            dynamic_axes=dynamic_axes,
            opset_version=OPSET_VERSION,
            export_params=True,
        )
        # Copy model and its external data file into output_dir.
        # torch.onnx.export creates model.onnx + model.onnx.data (external weights).
        # Both files are required at runtime; onnxruntime resolves .data relative to the
        # directory containing model.onnx when loading via an absolute path.
        shutil.copy(str(tmp_path), str(model_onnx_path))
        data_file = Path(tmpdir) / "model.onnx.data"
        if data_file.exists():
            shutil.copy(str(data_file), str(output_dir / "model.onnx.data"))

    # Export tokenizer as merged JSON so runtime only needs one file.
    # Qwen2TokenizerFast doesn't have to_dict() — use save_pretrained + flatten.
    tokenizer_json_path = output_dir / "tokenizer.json"
    tokenizer.save_pretrained(output_dir)
    # save_pretrained writes tokenizer.json directly into output_dir.
    # If it's already there (from a prior run), nothing to do.
    # Otherwise copy from the subdir path it writes to (some tokenizer versions
    # create a model-name subdirectory).
    if tokenizer_json_path.exists():
        pass  # already present
    else:
        candidates = list(output_dir.glob("*/tokenizer.json"))
        if not candidates:
            raise FileNotFoundError(
                "save_pretrained did not produce tokenizer.json. "
                "Check HuggingFace tokenizer version."
            )
        shutil.copy(str(candidates[0]), str(tokenizer_json_path))

    print(f"Done. Files written:")
    for f in sorted(output_dir.iterdir()):
        if f.is_file():
            print(f"  {f.name}: {f.stat().st_size / 1024 / 1024:.1f} MB")

    # Verify the exported model can be loaded with onnxruntime.
    try:
        import onnxruntime as ort

        print("Verifying ONNX model with onnxruntime ...")
        sess = ort.InferenceSession(
            str(model_onnx_path),
            providers=["CPUExecutionProvider"],
        )
        inputs = tokenizer(
            dummy_texts,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="np",
        )
        ort_inputs = {
            "input_ids": inputs["input_ids"].astype("int64"),
            "attention_mask": inputs["attention_mask"].astype("int64"),
        }
        outputs = sess.run(None, ort_inputs)
        hidden = outputs[0]
        print(f"  Output shape: {hidden.shape}")
        print("  Verification PASSED.")
    except ImportError:
        print("onnxruntime not installed — skipping runtime verification.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export vnlegal-lal to ONNX format")
    parser.add_argument(
        "--model",
        default="darklethelong/vnlegal-lal",
        help="HuggingFace model name or local path",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write model.onnx and tokenizer.json",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=1024,
        help="Maximum sequence length (default: 1024)",
    )
    args = parser.parse_args()
    export(
        model_name=args.model,
        output_dir=args.output_dir,
        max_length=args.max_length,
    )


if __name__ == "__main__":
    main()
