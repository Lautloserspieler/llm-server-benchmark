"""llmbench export: packt einen Benchmark-Lauf in eine portable ZIP-Datei.

Erzeugt ein Paket mit summary.json, Berichten und Rohdaten, das sich
einfach zwischen Servern, Teams und Standorten austauschen laesst.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


def export_run(run_dir: str | Path, output: str | Path | None = None) -> Path:
    """Packt einen Benchmark-Lauf in eine ZIP-Datei.

    Args:
        run_dir: Pfad zum Ergebnisordner eines Laufs.
        output: Pfad fuer die ZIP-Datei. Standard: <run_dir>.zip.

    Returns:
        Pfad zur erzeugten ZIP-Datei.
    """
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Ergebnisordner nicht gefunden: {run_dir}")

    output_path = Path(output) if output else run_dir.with_suffix(".zip")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Dateien die ins Paket gehoeren (wichtigste zuerst)
    include_patterns = [
        "summary.json",
        "report.html",
        "report.pdf",
        "benchmarks.csv",
        "comparison.json",
        "comparison.html",
        "comparison.pdf",
        "comparison.csv",
        "comparison_endpoint.csv",
    ]
    # Auch alle Unterordner mit raw_*.json und Server-Logs einschliessen
    include_globs = ["**/raw_*.json", "**/*.log"]

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # Benannte Dateien
        for pattern in include_patterns:
            p = run_dir / pattern
            if p.is_file():
                zf.write(p, arcname=f"{run_dir.name}/{pattern}")

        # Glob-Muster
        for glob_pattern in include_globs:
            for p in run_dir.glob(glob_pattern):
                if p.is_file():
                    arcname = f"{run_dir.name}/{p.relative_to(run_dir)}"
                    # Vermeide doppelte Eintraege
                    if arcname not in {info.filename for info in zf.infolist()}:
                        zf.write(p, arcname=arcname)

    return output_path
