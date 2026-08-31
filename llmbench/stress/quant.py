import asyncio
import subprocess
from pathlib import Path

from llmbench.config import load_config
from llmbench.utils import ensure_dir, print_err, print_msg, resolve_executable


async def run_quant_stress(config_path: str = "benchmark.yaml") -> int:
    cfg = load_config(config_path)
    
    print_msg(f"=== Quantisierungs-Test (Speicherbandbreite) ===")
    out_dir = ensure_dir(Path(cfg.get("project", {}).get("output_dir", "results")) / "stress_quant")
    
    # Finde llama-bench
    exe = resolve_executable(cfg["tools"].get("llama_bench", "llama-bench"))
    
    models_dir = Path("models")
    if not models_dir.exists():
        print_err("Der Ordner 'models' existiert nicht.")
        return 1
        
    # Suche alle GGUF Dateien, gruppiere nach Basis-Modellnamen
    # z.B. Llama-3-8B-Instruct.Q4_K_M.gguf -> Llama-3-8B-Instruct
    quants = list(models_dir.glob("*.gguf"))
    if not quants:
        print_err("Keine GGUF-Modelle im Ordner 'models' gefunden.")
        return 1
        
    print_msg(f"Gefundene Modelle fuer Quantisierungs-Vergleich:")
    for q in quants:
        print_msg(f" - {q.name}")
        
    print_msg("\nStarte llama-bench fuer alle Modelle (pp512, tg128)...")
    
    results = {}
    for q in quants:
        cmd = [exe, "-m", str(q), "-p", "512", "-n", "128"]
        print_msg(f"\nTeste {q.name}...")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            print(res.stdout)
            if res.returncode != 0:
                print_err(f"Fehler: {res.stderr}")
            else:
                results[q.name] = "Abgeschlossen"
        except Exception as e:
            print_err(f"Fehler beim Ausfuehren von llama-bench: {e}")
            
    print_msg("\n=== Quantisierungs-Ergebnisse ===")
    print_msg("Vergleiche die 't/s' (Tokens per Second) in der Konsolenausgabe oben.")
    print_msg("Wenn Q8_0 deutlich langsamer ist als Q4_K_M, ist deine Speicherbandbreite der Flaschenhals!")
    
    return 0
