from llmbench import llama_cpp_setup as lcs


def test_auto_backend_prefers_cuda_for_nvidia_with_nvcc(monkeypatch):
    monkeypatch.delenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", raising=False)
    monkeypatch.setattr(lcs, "_source_build_enabled", lambda: True)
    monkeypatch.setattr(lcs, "_nvidia_gpu_present", lambda: True)
    monkeypatch.setattr(lcs, "_which_nvcc", lambda: "/usr/local/cuda/bin/nvcc")

    assert lcs._prefer_cuda_source("linux", "x64") is True
    assert lcs._desired_existing_backend("linux", "x64") == "cuda"


def test_auto_backend_does_not_claim_cuda_without_nvidia_gpu(monkeypatch):
    monkeypatch.delenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", raising=False)
    monkeypatch.setattr(lcs, "_source_build_enabled", lambda: True)
    monkeypatch.setattr(lcs, "_nvidia_gpu_present", lambda: False)
    monkeypatch.setattr(lcs, "_which_nvcc", lambda: "/usr/local/cuda/bin/nvcc")

    assert lcs._prefer_cuda_source("linux", "x64") is False
    assert lcs._desired_existing_backend("linux", "x64") is None


def test_forced_backend_overrides_auto_detection(monkeypatch):
    monkeypatch.setenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", "cpu")
    monkeypatch.setattr(lcs, "_source_build_enabled", lambda: True)
    monkeypatch.setattr(lcs, "_nvidia_gpu_present", lambda: True)
    monkeypatch.setattr(lcs, "_which_nvcc", lambda: "/usr/local/cuda/bin/nvcc")

    assert lcs._prefer_cuda_source("linux", "x64") is False
    assert lcs._desired_existing_backend("linux", "x64") == "cpu"
