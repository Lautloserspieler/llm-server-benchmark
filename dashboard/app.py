import streamlit as st
import json
import pandas as pd
import plotly.express as px
from pathlib import Path
from llmbench.i18n import _

st.set_page_config(page_title=_("LLM Server Benchmark Dashboard"), layout="wide")

def load_summary(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_endpoint_data(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

st.title(f"📊 {_('LLM Server Benchmark Dashboard')}")

# Sidebar: Result Directory Selection
res_dir = st.sidebar.text_input(_("Ergebnisordner"), value="results")
res_path = Path(res_dir)

if not res_path.exists() or not res_path.is_dir():
    st.warning(f"{_('Ordner')} {res_dir} {_('nicht gefunden. Bitte gueltigen Pfad eingeben.')}")
    st.stop()

# Find all run directories
run_dirs = sorted([d for d in res_path.iterdir() if d.is_dir()], reverse=True)
if not run_dirs:
    st.warning(_("Keine Laeufe im Ergebnisordner gefunden."))
    st.stop()

selected_run_name = st.sidebar.selectbox(_("Lauf auswaehlen"), [d.name for d in run_dirs])
selected_run_path = next(d for d in run_dirs if d.name == selected_run_name)

try:
    summary = load_summary(selected_run_path / "summary.json")
except Exception as e:
    st.error(f"{_('Konnte summary.json nicht laden:')} {e}")
    st.stop()

st.header(f"{_('Lauf:')} {selected_run_name}")
st.markdown(f"**{_('Server:')}** {summary.get('server_name')} | **{_('Datum:')}** {summary.get('started_at')}")

# Hardware Info
with st.expander(f"💻 {_('Hardware-Informationen')}"):
    hw = summary.get("hardware", {})
    col1, col2, col3 = st.columns(3)
    with col1:
        st.write(f"**{_('CPU:')}**")
        st.write(hw.get("cpu", {}).get("name", _("Unbekannt")))
    with col2:
        st.write(f"**{_('OS:')}**")
        st.write(hw.get("os", _("Unbekannt")))
    with col3:
        st.write(f"**{_('RAM:')}**")
        ram_gb = hw.get("memory", {}).get("total_bytes", 0) / (1024**3)
        st.write(f"{ram_gb:.2f} GB")

    if hw.get("gpus"):
        st.write(f"**{_('GPUs:')}**")
        gpu_data = []
        for g in hw["gpus"]:
            gpu_data.append({
                _("Index"): g.get("index"),
                _("Name"): g.get("name"),
                _("Vendor"): g.get("vendor"),
                _("VRAM (MB)"): g.get("memory.total", _("Unbekannt"))
            })
        st.table(pd.DataFrame(gpu_data))

# Main Results Table
st.header(f"🚀 {_('Leistungsergebnisse')}")

all_results = []
for model in summary.get("models", []):
    model_name = model.get("model", {}).get("name", _("Unbekannt"))
    for profile in model.get("profiles", []):
        profile_name = profile.get("name", _("Unbekannt"))
        for kind, result in profile.get("benchmarks", {}).items():
            if result.get("status") == "ok":
                # We use the first row's average tokens/s as a representative value
                # Import here to avoid potential circular imports or setup issues
                from llmbench.llama_bench import flatten_bench_rows
                rows = flatten_bench_rows(result)
                if rows:
                    avg_tps = rows[0].get("avg_ts", 0)
                    all_results.append({
                        _("Modell"): model_name,
                        _("Profil"): profile_name,
                        _("Bereich"): kind,
                        _("TPS"): float(avg_tps)
                    })

if all_results:
    df = pd.DataFrame(all_results)
    st.dataframe(df, use_container_width=True)

    # Comparison Plot
    fig = px.bar(df, x=_("Modell"), y=_("TPS"), color=_("Profil"), barmode="group", facet_col=_("Bereich"),
                 title=_("Vergleich der Tokens pro Sekunde"))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info(_("Keine erfolgreichen Benchmark-Ergebnisse in diesem Lauf gefunden."))

# Endpoint Detail
st.header(f"🔌 {_('Endpoint-Lasttest')}")
for model in summary.get("models", []):
    model_name = model.get("model", {}).get("name", _("Unbekannt"))
    ep = model.get("endpoint")
    if ep and ep.get("status") == "ok":
        st.subheader(f"{_('Modell:')} {model_name}")

        col1, col2 = st.columns(2)
        with col1:
            st.metric(_("Kaltstart"), f"{ep.get('cold_start_seconds', 0):.2f} s")
            st.metric("Sanity Check", "✅ " + _("Bestanden") if ep.get("sanity_check", {}).get("passed") else "❌ " + _("Fehlgeschlagen"))

        # TPS vs Concurrency
        levels = ep.get("levels", [])
        if levels:
            concurrency = [level["concurrency"] for level in levels]
            system_tps = [level["system_tps"] for level in levels]

            fig_tps = px.line(x=concurrency, y=system_tps, markers=True,
                             labels={"x": _("Concurrency"), "y": _("System TPS")},
                             title=f"{_('Durchsatz vs. Concurrency')} - {model_name}")
            st.plotly_chart(fig_tps, use_container_width=True)

            # VRAM Usage
            vram_usage = [level.get("telemetry", {}).get("max_memory_used_bytes", 0) / (1024**2) for level in levels]
            fig_vram = px.line(x=concurrency, y=vram_usage, markers=True,
                              labels={"x": _("Concurrency"), "y": _("Max VRAM (MB)")},
                              title=f"{_('VRAM-Nutzung vs. Concurrency')} - {model_name}")
            st.plotly_chart(fig_vram, use_container_width=True)
else:
    st.info(_("Keine Ergebnisse fuer Endpoint-Lasttest verfuegbar."))
