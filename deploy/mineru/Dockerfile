FROM python:3.12-slim-bookworm

# OpenCV / ONNX Runtime / llama.cpp runtime libraries. MinerU's default CPU
# install uses ONNX small models and llama.cpp for the VLM, so torch/vLLM are
# intentionally not installed.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      libgl1 \
      libglib2.0-0 \
      libgomp1 \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "mineru==4.0.12"

# Models are persisted on a volume so container rebuilds do not re-download them.
ENV MINERU_HOME=/models \
    MINERU_MODEL_SOURCE=huggingface \
    MINERU_MODEL_SMALL_BACKEND=onnx \
    MINERU_MODEL_VLM_ENGINE=llama-cpp \
    MINERU_TABLE_DEVICE=cpu

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD curl -fsS http://localhost:8000/v1/health || exit 1

ENTRYPOINT ["mineru-kit"]
CMD ["api-server", "--host", "0.0.0.0", "--port", "8000", "--tier", "standard", "--concurrency", "1"]
