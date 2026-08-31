import asyncio
import time
from pathlib import Path

import httpx

from llmbench.backends.llama_cpp import LlamaCppBackend
from llmbench.config import load_config
from llmbench.endpoint import wait_health_async
from llmbench.utils import ensure_dir, print_err, print_msg


async def _probe_context(base_url: str, prompt_length: int, timeout: int = 300) -> bool:
    # Generiere künstlichen, pseudo-zufälligen RAG Prompt
    # 1 "Wort" entspricht ca 1.3 Token
    words_needed = int(prompt_length / 1.3)
    chunk = "The quick brown fox jumps over the lazy dog. "
    prompt = chunk * (words_needed // 9) + "\nBitte fasse diesen Text in einem Satz zusammen."

    payload = {
        "prompt": prompt,
        "n_predict": 50,
        "temperature": 0.0,
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            t_start = time.perf_counter()
            r = await client.post(base_url.rstrip("/") + "/completion", json=payload)
            r.raise_for_status()
            t_dur = time.perf_counter() - t_start
            print_msg(f"[OK] {prompt_length} Token-Klasse (Dauer: {t_dur:.1f}s)")
            return True
    except httpx.ReadTimeout:
        print_err(f"[TIMEOUT] Keine Antwort nach {timeout}s bei ~{prompt_length} Tokens.")
        return False
    except Exception as e:
        print_err(f"[FEHLER] Server-Crash bei ~{prompt_length} Tokens: {e}")
        return False


async def run_oom_stress(config_path: str = "benchmark.yaml") -> int:
    cfg = load_config(config_path)
    if not cfg["models"]:
        print_err("Keine Modelle in Konfiguration.")
        return 1

    model = cfg["models"][0]
    print_msg(f"=== KV-Cache OOM Stresstest ===")
    print_msg(f"Modell: {model['name']}")
    
    out_dir = ensure_dir(Path(cfg.get("project", {}).get("output_dir", "results")) / "stress_oom")
    backend = LlamaCppBackend(cfg["tools"])
    
    ep_cfg = cfg.get("endpoint", {})
    base_url = ep_cfg.get("base_url", "http://127.0.0.1:8080")
    
    # Fuer OOM muessen wir den Server mit maximalem Context (-c 131072) starten!
    bench_cfg = dict(cfg["benchmark"])
    ep_cfg["context_size"] = 131072
    
    prof = (model.get("profiles") or [{}])[0]
    proc = None
    
    try:
        print_msg("Starte Server mit Kontextgroesse 128k...")
        proc, _ = backend.start_server(model["path"], prof, ep_cfg, bench_cfg, out_dir / "server.log")
        
        print_msg("Warte auf Bereitstellung...")
        await wait_health_async(base_url, 300)
        
        # Stufen fuer Kontextlänge
        levels = [4000, 8000, 16000, 32000, 64000, 96000, 128000]
        max_stable = 0
        
        for level in levels:
            print_msg(f"\nTeste mit ca. {level} Tokens Prompt-Laenge...")
            ok = await _probe_context(base_url, level)
            if ok:
                max_stable = level
            else:
                print_msg(f"-> VRAM / KV-Cache Grenze erreicht bei Stufe {level}!")
                break
                
        print_msg(f"\n=== Ergebnis ===")
        print_msg(f"Maximale stabile RAG-Kontextlänge: {max_stable} Tokens")
        
    except Exception as e:
        print_err(f"Fehler: {e}")
        return 1
    finally:
        if proc:
            backend.stop_server(proc)
            
    return 0
