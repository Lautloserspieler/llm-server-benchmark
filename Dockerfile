# syntax=docker/dockerfile:1.7

ARG CUDA_DEVEL_IMAGE=nvidia/cuda:13.2.1-devel-ubuntu24.04
ARG CUDA_RUNTIME_IMAGE=nvidia/cuda:13.2.1-runtime-ubuntu24.04
ARG LLAMA_CPP_COMMIT=64a155d242cb427766055ea9caea6f34df1ca94b

FROM ${CUDA_DEVEL_IMAGE} AS llama-build
ARG LLAMA_CPP_COMMIT
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates cmake git ninja-build pkg-config \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/ggml-org/llama.cpp.git /src/llama.cpp \
    && cd /src/llama.cpp \
    && git checkout --detach "${LLAMA_CPP_COMMIT}" \
    && test "$(git rev-parse HEAD)" = "${LLAMA_CPP_COMMIT}"
RUN cmake -S /src/llama.cpp -B /src/llama.cpp/build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DGGML_CUDA=ON \
      -DLLAMA_CURL=OFF \
      -DBUILD_SHARED_LIBS=OFF \
    && cmake --build /src/llama.cpp/build --target llama-bench llama-server -j"$(nproc)" \
    && /src/llama.cpp/build/bin/llama-bench --version

FROM ${CUDA_RUNTIME_IMAGE} AS runtime
ARG CUDA_DEVEL_IMAGE
ARG CUDA_RUNTIME_IMAGE
ARG LLAMA_CPP_COMMIT
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:/opt/llama.cpp:${PATH} \
    HF_HOME=/workspace/.cache/huggingface \
    LLMBENCH_EXECUTION_ENV=docker \
    LLMBENCH_CONTAINER_RUNTIME=docker \
    LLMBENCH_CUDA_DEVEL_IMAGE=${CUDA_DEVEL_IMAGE} \
    LLMBENCH_CUDA_RUNTIME_IMAGE=${CUDA_RUNTIME_IMAGE} \
    LLMBENCH_LLAMA_CPP_COMMIT=${LLAMA_CPP_COMMIT} \
    LLMBENCH_LLAMA_DIR=/opt/llama.cpp
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates libgomp1 python3 python3-pip python3-venv \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/llmbench
COPY pyproject.toml README.md LICENSE VERSION ./
COPY llmbench ./llmbench
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir .

RUN mkdir -p /opt/llama.cpp /workspace/models /workspace/results /workspace/.cache/huggingface
COPY --from=llama-build /src/llama.cpp/build/bin/llama-bench /opt/llama.cpp/llama-bench
COPY --from=llama-build /src/llama.cpp/build/bin/llama-server /opt/llama.cpp/llama-server
COPY docker/entrypoint.sh /usr/local/bin/llmbench-entrypoint
RUN chmod 0755 /opt/llama.cpp/llama-bench /opt/llama.cpp/llama-server /usr/local/bin/llmbench-entrypoint

LABEL org.opencontainers.image.title="llm-server-benchmark" \
      org.opencontainers.image.description="Reproducible CUDA llama.cpp benchmark runtime" \
      io.llmbench.llama-cpp-commit="${LLAMA_CPP_COMMIT}" \
      io.llmbench.cuda-devel-image="${CUDA_DEVEL_IMAGE}" \
      io.llmbench.cuda-runtime-image="${CUDA_RUNTIME_IMAGE}"

WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/llmbench-entrypoint"]
CMD ["python", "-m", "llmbench", "--help"]
