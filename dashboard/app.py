import streamlit as st
import json
import pandas as pd
import plotly.express as px
from pathlib import Path

st.set_page_config(page_title="LLM Server Benchmark Dashboard", layout="wide")

def load_summary(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_endpoint_data(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

st.title("📊 LLM Server Benchmark Dashboard")

# Sidebar: Result Directory Selection
res_dir = st.sidebar.text_input("Results Directory", value="results")
res_path = Path(res_dir)

if not res_path.exists() or not res_path.is_dir():
    st.warning(f"Directory {res_dir} not found. Please enter a valid results path.")
    st.stop()

# Find all run directories
run_dirs = sorted([d for d in res_path.iterdir() if d.is_dir()], reverse=True)
if not run_dirs:
    st.warning("No run directories found in the results folder.")
    st.stop()

selected_run_name = st.sidebar.selectbox("Select Run", [d.name for d in run_dirs])
selected_run_path = next(d for d in run_dirs if d.name == selected_run_name)

try:
    summary = load_summary(selected_run_path / "summary.json")
except Exception as e:
    st.error(f"Could not load summary.json: {e}")
    st.stop()

st.header(f"Run: {selected_run_name}")
st.markdown(f"**Server:** {summary.get('server_name')} | **Date:** {summary.get('started_at')}")

# Hardware Info
with st.expander("💻 Hardware Information"):
    hw = summary.get("hardware", {})
    col1, col2, col3 = st.columns(3)
    with col1:
        st.write("**CPU:**")
        st.write(hw.get("cpu", {}).get("name", "Unknown"))
    with col2:
        st.write("**OS:**")
        st.write(hw.get("os", "Unknown"))
    with col3:
        st.write("**RAM:**")
        ram_gb = hw.get("memory", {}).get("total_bytes", 0) / (1024**3)
        st.write(f"{ram_gb:.2f} GB")

    if hw.get("gpus"):
        st.write("**GPUs:**")
        gpu_data = []
        for g in hw["gpus"]:
            gpu_data.append({
                "Index": g.get("index"),
                "Name": g.get("name"),
                "Vendor": g.get("vendor"),
                "VRAM (MB)": g.get("memory.total", "Unknown")
            })
        st.table(pd.DataFrame(gpu_data))

# Main Results Table
st.header("🚀 Performance Results")

all_results = []
for model in summary.get("models", []):
    model_name = model.get("model", {}).get("name", "Unknown")
    for profile in model.get("profiles", []):
        profile_name = profile.get("name", "Unknown")
        for kind, result in profile.get("benchmarks", {}).items():
            if result.get("status") == "ok":
                # We use the first row's average tokens/s as a representative value
                # Import here to avoid potential circular imports or setup issues
                from llmbench.llama_bench import flatten_bench_rows
                rows = flatten_bench_rows(result)
                if rows:
                    avg_tps = rows[0].get("avg_ts", 0)
                    all_results.append({
                        "Model": model_name,
                        "Profile": profile_name,
                        "Kind": kind,
                        "TPS": float(avg_tps)
                    })

if all_results:
    df = pd.DataFrame(all_results)
    st.dataframe(df, use_container_width=True)

    # Comparison Plot
    fig = px.bar(df, x="Model", y="TPS", color="Profile", barmode="group", facet_col="Kind",
                 title="Tokens per Second Comparison")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No successful benchmark results found in this run.")

# Endpoint Detail
st.header("🔌 Endpoint Load Test")
for model in summary.get("models", []):
    model_name = model.get("model", {}).get("name", "Unknown")
    ep = model.get("endpoint")
    if ep and ep.get("status") == "ok":
        st.subheader(f"Model: {model_name}")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Cold Start", f"{ep.get('cold_start_seconds', 0):.2f} s")
            st.metric("Sanity Check", "✅ Passed" if ep.get("sanity_check", {}).get("passed") else "❌ Failed")

        # TPS vs Concurrency
        levels = ep.get("levels", [])
        if levels:
            concurrency = [level["concurrency"] for level in levels]
            system_tps = [level["system_tps"] for level in levels]

            fig_tps = px.line(x=concurrency, y=system_tps, markers=True,
                             labels={"x": "Concurrency", "y": "System TPS"},
                             title=f"Throughput vs Concurrency - {model_name}")
            st.plotly_chart(fig_tps, use_container_width=True)

            # VRAM Usage
            vram_usage = [level.get("telemetry", {}).get("max_memory_used_bytes", 0) / (1024**2) for level in levels]
            fig_vram = px.line(x=concurrency, y=vram_usage, markers=True,
                              labels={"x": "Concurrency", "y": "Max VRAM (MB)"},
                              title=f"VRAM Usage vs Concurrency - {model_name}")
            st.plotly_chart(fig_vram, use_container_width=True)
else:
    st.info("No endpoint load test results available.")
