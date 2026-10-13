from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """Optional features exposed by a benchmark backend.

    Capabilities describe what the llmbench adapter can benchmark reliably,
    not every feature the upstream runtime may support in isolation.
    """

    endpoint: bool = False
    streaming: bool = False
    concurrency: bool = False
    long_context: bool = False
    kv_cache_observation: bool = False
    oom_probe: bool = False
    quantization: bool = False
    multi_model: bool = False

    def supports(self, capability: str) -> bool:
        if capability not in self.__dataclass_fields__:
            raise ValueError(f"Unbekannte Backend-Faehigkeit: {capability!r}")
        return bool(getattr(self, capability))

    def to_dict(self) -> dict[str, bool]:
        return {key: bool(value) for key, value in asdict(self).items()}
