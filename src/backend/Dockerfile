# =============================================================================
# VietLegalGraphRAG — ONNX Runtime Embedding Backend
# =============================================================================
#
# Uses ONNX Runtime for dense retrieval — no PyTorch or Transformers needed.
#
# Before the first build, export the embedding model once from a machine with
# torch+transformers installed:
#
#   python src/infra/scripts/export_vnlegal_onnx.py \
#       --output-dir ./onnx_model \
#       --model darklethelong/vnlegal-lal
#
# Then copy onnx_model/ into the build context and set:
#   EMBEDDING_PROVIDER=onnx
#   EMBEDDING_ONNX_MODEL_PATH=/app/onnx_model/model.onnx
#   EMBEDDING_ONNX_TOKENIZER_PATH=/app/onnx_model/tokenizer.json
#
# See src/infra/scripts/export_vnlegal_onnx.py for full instructions.
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

COPY src/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY src/backend/app /app/src/backend/app
COPY src/backend/services /app/src/backend/services



ENV PYTHONPATH=/app/src/backend/services:/app/src/backend/app
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/src/backend/app"]
