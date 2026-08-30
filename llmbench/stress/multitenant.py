import asyncio
import sys
import time
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from llmbench.backends.llama_cpp import LlamaCppBackend
from llmbench.config import load_config
from llmbench.endpoint import _run_endpoint_load_async, wait_health_async
from llmbench.utils import ensure_dir, print_err, print_msg


def modify_url_port(base_url: str, new_port: int) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.hostname}:{new_port}{parsed.path}"


async def run_multitenant(config_path: str = "benchmark.yaml") -> int:
    cfg = load_config(config_path)
    if len(cfg["models"]) < 2:
        print_err("Multi-Tenant Stresstest benoetigt mindestens 2 Modelle in der Konfiguration.")
        return 1
    
    # Modelle auswaehlen (nehmen die ersten beiden aus der Config)
    model1 = cfg["models"][0]
    model2 = cfg["models"][1]
    
    print_msg(f"=== Multi-Tenant Stresstest ===")
    print_msg(f"Modell 1: {model1['name']}")
    print_msg(f"Modell 2: {model2['name']}")
    
    out_dir = ensure_dir(Path(cfg.get("project", {}).get("output_dir", "results")) / "stress_multitenant")
    
    backend = LlamaCppBackend(cfg["tools"])
    
    # Endpoint Configs ableiten
    ep_cfg = cfg.get("endpoint", {})
    if not ep_cfg.get("enabled", True):
        print_err("Endpoint-Tests muessen in benchmark.yaml aktiviert sein.")
        return 1
    
    ep_cfg1 = deepcopy(ep_cfg)
    ep_cfg2 = deepcopy(ep_cfg)
    
    # Zweiter Server braucht anderen Port
    ep_cfg1["base_url"] = modify_url_port(ep_cfg.get("base_url", "http://127.0.0.1:8080"), 8080)
    ep_cfg2["base_url"] = modify_url_port(ep_cfg.get("base_url", "http://127.0.0.1:8080"), 8081)
    
    # Profile: Wir nehmen das erste Profil, das verfuegbar ist
    prof1 = (model1.get("profiles") or [{}])[0]
    prof2 = (model2.get("profiles") or [{}])[0]
    
    # VRAM Halbieren? Fuer jetzt lassen wir llama-server das Speicher-OS-Management machen,
    # oder uebergeben feste layers (wenn -1 konfiguriert ist, geht alles ins VRAM).
    
    proc1 = None
    proc2 = None
    
    try:
        print_msg("Starte Server 1...")
        proc1, _ = backend.start_server(model1["path"], prof1, ep_cfg1, cfg["benchmark"], out_dir / "server1.log")
        
        print_msg("Starte Server 2...")
        proc2, _ = backend.start_server(model2["path"], prof2, ep_cfg2, cfg["benchmark"], out_dir / "server2.log")
        
        print_msg("Warte auf Health Checks...")
        t1 = asyncio.create_task(wait_health_async(ep_cfg1["base_url"], 300))
        t2 = asyncio.create_task(wait_health_async(ep_cfg2["base_url"], 300))
        await asyncio.gather(t1, t2)
        print_msg("Beide Server bereit!")
        
        # Concurrency Lauf
        print_msg("Starte Concurrency-Bombardement auf beide Server...")
        t_start = time.perf_counter()
        
        load1 = asyncio.create_task(_run_endpoint_load_async(ep_cfg1["base_url"], ep_cfg1, 0.5, out_dir))
        load2 = asyncio.create_task(_run_endpoint_load_async(ep_cfg2["base_url"], ep_cfg2, 0.5, out_dir))
        
        res1, res2 = await asyncio.gather(load1, load2)
        t_duration = time.perf_counter() - t_start
        
        print_msg(f"\nMulti-Tenant Test abgeschlossen in {t_duration:.1f}s")
        print_msg("=== Auswertung ===")
        print_msg(f"{model1['name']} - Gesamte System-TPS: {sum(lv['system_tps'] for lv in res1['levels'])/len(res1['levels']):.2f}")
        print_msg(f"{model2['name']} - Gesamte System-TPS: {sum(lv['system_tps'] for lv in res2['levels'])/len(res2['levels']):.2f}")
        
    except Exception as e:
        print_err(f"Fehler im Stresstest: {e}")
        return 1
    finally:
        if proc1:
            backend.stop_server(proc1)
        if proc2:
            backend.stop_server(proc2)
            
    return 0
