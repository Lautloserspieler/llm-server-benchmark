import json
import subprocess

from llmbench.memory_bandwidth_observer import MactopObserver


def _hardware():
    return {"memory_domains": [{"id": "apple:unified:0", "name": "Apple M4 Max"}]}


def test_observer_requires_opt_in(tmp_path):
    observer = MactopObserver(tmp_path, enabled=False, hardware=_hardware())
    observer.start()
    assert observer.stop() is None


def test_observer_rejects_invalid_mactop_trace(tmp_path):
    observer = MactopObserver(tmp_path, enabled=True, hardware=_hardware())
    observer.output_path.write_text("not json", encoding="utf-8")
    result = observer._parse()
    assert result["observed_during_benchmark"]["reason"] == "mactop_invalid_or_incomplete_output"


def test_observer_parses_counter_backed_samples_and_keeps_artifact(tmp_path, monkeypatch):
    observer = MactopObserver(tmp_path, enabled=True, hardware=_hardware())
    observer.output_path.write_text(json.dumps([
        {"soc_metrics": {"DRAMBWCombined": 100.0}},
        {"soc_metrics": {"DRAMBWCombined": 140.0}},
    ]), encoding="utf-8")
    monkeypatch.setattr(observer, "_version", lambda: "mactop v2")
    result = observer._parse()
    assert result["observed_during_benchmark"]["value"] == 120.0
    assert result["statistics"]["max_gb_s"] == 140.0
    assert result["artifact"]["sha256"]
    assert result["observed_during_benchmark"]["evidence"]["field"] == "soc_metrics.DRAMBWCombined"


def test_observer_does_not_measure_unknown_json_field(tmp_path):
    observer = MactopObserver(tmp_path, enabled=True, hardware=_hardware())
    observer.output_path.write_text(json.dumps([{"soc_metrics": {"dram_bw_combined": 123.0}}]), encoding="utf-8")
    result = observer._parse()
    assert result["observed_during_benchmark"]["reason"] == "mactop_counter_bandwidth_not_reported"


def test_observer_stop_terminates_then_kills_after_timeout(tmp_path):
    class Process:
        def __init__(self):
            self.terminated = self.killed = False
        def terminate(self): self.terminated = True
        def wait(self, timeout):
            if not self.killed:
                raise subprocess.TimeoutExpired("mactop", timeout)
        def kill(self): self.killed = True

    observer = MactopObserver(tmp_path, enabled=True, hardware=_hardware())
    observer.process = Process()  # type: ignore[assignment]
    observer.output_path.write_text("[]", encoding="utf-8")
    result = observer.stop()
    assert observer.process.terminated is True
    assert observer.process.killed is True
    assert result["observed_during_benchmark"]["reason"] == "mactop_counter_bandwidth_not_reported"


def test_m5_is_not_reported_as_measured(tmp_path, monkeypatch):
    observer = MactopObserver(tmp_path, enabled=True, hardware={"memory_domains": [{"id": "apple:unified:0", "name": "Apple M5"}]})
    monkeypatch.setattr("llmbench.memory_bandwidth_observer.sys.platform", "darwin")
    observer.start()
    assert observer.result["observed_during_benchmark"]["reason"] == "mactop_power_estimate_not_measured"
