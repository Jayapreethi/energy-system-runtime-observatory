"""
Energy Systems Runtime Observatory (ESRO)
Live monitoring of containers, frameworks, HPC operations, and cloud integration.

Usage:
    pip install streamlit pandas plotly psutil paramiko streamlit-autorefresh
    streamlit run esro_dashboard.py
"""

import json
import os
import subprocess
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psutil
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False


# ──────────────────────────────────────────────
# Metrics Collector
# ──────────────────────────────────────────────
class MetricsCollector:
    """Collects system, container, and HPC metrics."""

    @staticmethod
    def get_system_metrics() -> dict:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/" if os.name != "nt" else "C:\\")
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "cpu_count": psutil.cpu_count(logical=True),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "memory_percent": vm.percent,
            "memory_used_gb": vm.used / (1024 ** 3),
            "memory_total_gb": vm.total / (1024 ** 3),
            "disk_percent": disk.percent,
            "disk_used_gb": disk.used / (1024 ** 3),
            "disk_total_gb": disk.total / (1024 ** 3),
            "timestamp": datetime.now(),
        }

    @staticmethod
    def get_container_stats() -> list[dict]:
        fmt = (
            '{"name":"{{.Name}}",'
            '"cpu":"{{.CPUPerc}}",'
            '"mem":"{{.MemUsage}}",'
            '"mem_pct":"{{.MemPerc}}",'
            '"net":"{{.NetIO}}",'
            '"pids":"{{.PIDs}}"}'
        )
        try:
            result = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", fmt],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        containers = []
        now = datetime.now()
        for line in result.stdout.strip().splitlines():
            try:
                raw = json.loads(line)
                containers.append({
                    "name": raw["name"],
                    "cpu": float(raw["cpu"].strip("%")),
                    "mem_pct": float(raw["mem_pct"].strip("%")),
                    "memory": raw["mem"],
                    "network": raw["net"],
                    "pids": raw.get("pids", "N/A"),
                    "timestamp": now,
                })
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        return containers

    @staticmethod
    def get_hpc_jobs(ssh_config: dict) -> list[dict]:
        try:
            import paramiko

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                ssh_config["host"],
                username=ssh_config["username"],
                password=ssh_config.get("password"),
                timeout=10,
            )
            squeue_fmt = "%i|%j|%t|%M|%l|%D|%C|%m"
            _, stdout, _ = ssh.exec_command(f"squeue -u $USER -o \"{squeue_fmt}\"")
            output = stdout.read().decode().strip()
            ssh.close()

            jobs = []
            for line in output.splitlines()[1:]:
                parts = line.split("|")
                if len(parts) >= 8:
                    jobs.append({
                        "Job ID": parts[0].strip(),
                        "Name": parts[1].strip(),
                        "State": parts[2].strip(),
                        "Time Used": parts[3].strip(),
                        "Time Limit": parts[4].strip(),
                        "Nodes": parts[5].strip(),
                        "CPUs": parts[6].strip(),
                        "Memory": parts[7].strip(),
                    })
            return jobs
        except Exception:
            return []


# ──────────────────────────────────────────────
# Styling
# ──────────────────────────────────────────────

SERIF = "Roboto Slab, Merriweather, Georgia, serif"

PLOT_COLORS = {
    "primary": "#3776ab",
    "secondary": "#c44e52",
    "grid": "#e5e5e5",
    "bg": "#fafbfc",
}

PLOTLY_LAYOUT = dict(
    font_family=SERIF,
    font_color="#333",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#fafbfc",
    title_font_size=14,
    title_font_color="#222",
    margin=dict(l=10, r=10, t=40, b=10),
)

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@300;400;500;600;700&family=Merriweather:wght@300;400;700&display=swap');

    html, body, [class^='css'], .stMarkdown, .stCaption,
    .stDataFrame, .stTable, th, td, p, span, label, input, button {
        font-family: 'Roboto Slab', 'Merriweather', Georgia, serif !important;
    }

    .esro-title {
        font-family: 'Roboto Slab', serif !important;
        font-size: 2.4rem;
        font-weight: 700;
        color: #3776ab;
        letter-spacing: 1.5px;
        margin: 0;
        padding-top: 0.25rem;
    }
    .esro-subtitle {
        font-family: 'Merriweather', serif !important;
        font-size: 1.05rem;
        font-weight: 300;
        color: #555;
        margin: 0.3rem 0 1.5rem 0;
    }
    .section-label {
        font-family: 'Roboto Slab', serif !important;
        font-size: 1.15rem;
        font-weight: 600;
        color: #333;
        border-bottom: 2px solid #3776ab;
        padding-bottom: 0.4rem;
        margin: 1.5rem 0 1rem 0;
    }
    .stDataFrame, .stTable { border: 1px solid #dde1e5; border-radius: 4px; }
    .stExpander { border: 1px solid #dde1e5; border-radius: 4px; }
    section[data-testid="stSidebar"] { background: #f5f6f8; border-right: 1px solid #dde1e5; }
    hr { border: none; border-top: 1px solid #dde1e5; margin: 1.5rem 0; }
</style>
"""


# ──────────────────────────────────────────────
# Gauge builder
# ──────────────────────────────────────────────
def make_gauge(value: float, title: str, suffix: str = "%",
               detail: str = "", max_val: float = 100) -> go.Figure:
    """Builds a semicircular gauge indicator."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": suffix, "font": {"size": 28, "family": SERIF, "color": "#222"}},
        title={"text": f"<b>{title}</b><br><span style='font-size:0.7rem;color:#777;'>{detail}</span>",
               "font": {"size": 13, "family": SERIF, "color": "#333"}},
        gauge={
            "axis": {"range": [0, max_val], "tickwidth": 1, "tickcolor": "#999",
                     "tickfont": {"size": 9, "color": "#999", "family": SERIF}},
            "bar": {"color": "#3776ab", "thickness": 0.6},
            "bgcolor": "#eef1f5",
            "borderwidth": 0,
            "steps": [
                {"range": [0, max_val * 0.6], "color": "#e8eef5"},
                {"range": [max_val * 0.6, max_val * 0.85], "color": "#fdf0e2"},
                {"range": [max_val * 0.85, max_val], "color": "#fce4e4"},
            ],
            "threshold": {
                "line": {"color": "#c44e52", "width": 2},
                "thickness": 0.8,
                "value": max_val * 0.85,
            },
        },
    ))
    fig.update_layout(
        height=180,
        margin=dict(l=20, r=20, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=SERIF),
    )
    return fig


def make_uptime_indicator(uptime_str: str) -> go.Figure:
    """Plain text indicator for uptime (no gauge)."""
    fig = go.Figure(go.Indicator(
        mode="number",
        value=0,
        number={"font": {"size": 1, "color": "rgba(0,0,0,0)"}},  # hidden
        title={"text": (
            f"<b>Uptime</b><br>"
            f"<span style='font-size:1.8rem;color:#222;font-weight:600;'>{uptime_str}</span>"
        ), "font": {"size": 13, "family": SERIF, "color": "#333"}},
    ))
    fig.update_layout(
        height=180,
        margin=dict(l=20, r=20, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=SERIF),
    )
    return fig


# ──────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Energy Systems Runtime Observatory",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # ── Sidebar ──
    with st.sidebar:
        st.markdown(
            f'<p style="font-family:{SERIF};font-size:1.3rem;font-weight:700;color:#3776ab;margin:0;">ESRO</p>'
            f'<p style="font-family:{SERIF};font-size:0.8rem;color:#666;margin:0 0 1rem 0;">'
            f'Energy Systems Runtime Observatory</p>',
            unsafe_allow_html=True,
        )
        st.divider()

        st.subheader("Monitoring")
        monitor_local = st.toggle("Local System", value=True)
        monitor_containers = st.toggle("Docker Containers", value=True)
        monitor_hpc = st.toggle("HPC Cluster", value=False)

        ssh_config = {}
        if monitor_hpc:
            st.divider()
            st.subheader("HPC Connection")
            hpc_host = st.text_input("Host", value="talon.und.edu")
            hpc_user = st.text_input("Username")
            hpc_password = st.text_input("Password", type="password")
            if hpc_host and hpc_user and hpc_password:
                ssh_config = {"host": hpc_host, "username": hpc_user, "password": hpc_password}

        st.divider()
        st.subheader("Refresh")
        refresh_sec = st.slider("Interval (seconds)", 3, 60, 10)

        if HAS_AUTOREFRESH:
            st_autorefresh(interval=refresh_sec * 1000, key="esro_refresh")
        else:
            st.button("Refresh Now", use_container_width=True)
            st.caption("Install `streamlit-autorefresh` for auto-refresh.")

    # ── Session state: seed history on first load ──
    if "metrics_history" not in st.session_state:
        st.session_state.metrics_history = []
        for _ in range(10):
            vm = psutil.virtual_memory()
            st.session_state.metrics_history.append({
                "timestamp": datetime.now(),
                "cpu": psutil.cpu_percent(interval=0.3),
                "memory": vm.percent,
            })

    collector = MetricsCollector()

    # ── Header ──
    st.markdown(
        '<div class="esro-title">Energy Systems Runtime Observatory</div>'
        '<div class="esro-subtitle">'
        'Live monitoring of containers, frameworks, HPC operations, and cloud integration'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Local System ──
    if monitor_local:
        system = collector.get_system_metrics()

        st.markdown('<div class="section-label">System Resources</div>', unsafe_allow_html=True)

        g1, g2, g3, g4 = st.columns(4)
        with g1:
            st.plotly_chart(make_gauge(
                system["cpu_percent"], "CPU",
                detail=f"{system['cpu_count_physical']}C / {system['cpu_count']}T",
            ), use_container_width=True, key="gauge_cpu")
        with g2:
            st.plotly_chart(make_gauge(
                system["memory_percent"], "Memory",
                detail=f"{system['memory_used_gb']:.1f} / {system['memory_total_gb']:.1f} GB",
            ), use_container_width=True, key="gauge_mem")
        with g3:
            st.plotly_chart(make_gauge(
                system["disk_percent"], "Disk",
                detail=f"{system['disk_used_gb']:.0f} / {system['disk_total_gb']:.0f} GB",
            ), use_container_width=True, key="gauge_disk")
        with g4:
            st.markdown(
                f"""
                <div style="height:180px;display:flex;flex-direction:column;
                            align-items:center;justify-content:center;
                            font-family:'Roboto Slab',Georgia,serif;">
                    <div style="font-size:0.8rem;font-weight:600;color:#333;
                                letter-spacing:0.3px;margin-bottom:0.5rem;">Uptime</div>
                    <div style="font-size:2rem;font-weight:600;color:#222;
                                line-height:1.1;">{_format_uptime()}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.session_state.metrics_history.append({
            "timestamp": system["timestamp"],
            "cpu": system["cpu_percent"],
            "memory": system["memory_percent"],
        })
        if len(st.session_state.metrics_history) > 100:
            st.session_state.metrics_history = st.session_state.metrics_history[-100:]
    else:
        system = {"cpu_count": "N/A", "memory_total_gb": 0}

    # ── Containers ──
    if monitor_containers:
        st.markdown('<div class="section-label">Container Performance</div>', unsafe_allow_html=True)

        containers = collector.get_container_stats()
        if containers:
            df_c = pd.DataFrame(containers)

            fig_col1, fig_col2 = st.columns(2)
            with fig_col1:
                fig_cpu = px.bar(
                    df_c.sort_values("cpu", ascending=True),
                    x="cpu", y="name", orientation="h",
                    title="CPU Usage by Container",
                    labels={"cpu": "CPU %", "name": ""},
                    color_discrete_sequence=[PLOT_COLORS["primary"]],
                )
                fig_cpu.update_layout(
                    **PLOTLY_LAYOUT, showlegend=False,
                    height=max(240, len(df_c) * 40 + 80),
                    xaxis=dict(gridcolor=PLOT_COLORS["grid"]),
                    yaxis=dict(gridcolor=PLOT_COLORS["grid"]),
                )
                st.plotly_chart(fig_cpu, use_container_width=True)

            with fig_col2:
                fig_mem = px.bar(
                    df_c.sort_values("mem_pct", ascending=True),
                    x="mem_pct", y="name", orientation="h",
                    title="Memory Usage by Container",
                    labels={"mem_pct": "Memory %", "name": ""},
                    color_discrete_sequence=[PLOT_COLORS["secondary"]],
                )
                fig_mem.update_layout(
                    **PLOTLY_LAYOUT, showlegend=False,
                    height=max(240, len(df_c) * 40 + 80),
                    xaxis=dict(gridcolor=PLOT_COLORS["grid"]),
                    yaxis=dict(gridcolor=PLOT_COLORS["grid"]),
                )
                st.plotly_chart(fig_mem, use_container_width=True)

            with st.expander("Container Details"):
                display_df = df_c[["name", "cpu", "mem_pct", "memory", "network", "pids"]].copy()
                display_df.columns = ["Container", "CPU %", "Mem %", "Memory", "Network I/O", "PIDs"]
                st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.info("No running containers detected. Start with: `docker compose up -d`")

    # ── HPC ──
    if monitor_hpc:
        st.markdown('<div class="section-label">HPC Cluster (Talon)</div>', unsafe_allow_html=True)

        if ssh_config:
            with st.spinner("Querying SLURM..."):
                jobs = collector.get_hpc_jobs(ssh_config)
            if jobs:
                df_jobs = pd.DataFrame(jobs)
                state_map = {"R": "Running", "PD": "Pending", "CG": "Completing", "CD": "Completed"}
                df_jobs["State"] = df_jobs["State"].map(lambda s: state_map.get(s, s))
                st.dataframe(df_jobs, use_container_width=True, hide_index=True)
                st.caption(f"{len(df_jobs)} active job(s) in queue")
            else:
                st.success("No active jobs in the SLURM queue.")
        else:
            st.warning("Enter HPC credentials in the sidebar to connect.")

    # ── Comparison ──
    st.markdown('<div class="section-label">Performance Comparison</div>', unsafe_allow_html=True)

    comp_col1, comp_col2 = st.columns(2)

    with comp_col1:
        st.markdown("**Local vs HPC**")
        local_status = "Active" if monitor_local else "Disconnected"
        hpc_status = "Connected" if (monitor_hpc and ssh_config) else "Disconnected"
        comparison = pd.DataFrame({
            "System": ["Local", "HPC (Talon)"],
            "CPUs": [str(system.get("cpu_count", "N/A")), "8 (per job)"],
            "Memory (GB)": [
                f"{system['memory_total_gb']:.0f}"
                if isinstance(system.get("memory_total_gb"), (int, float)) else "N/A",
                "16",
            ],
            "Status": [local_status, hpc_status],
        })
        st.dataframe(comparison, use_container_width=True, hide_index=True)

    with comp_col2:
        st.markdown("**Framework Tests**")
        tests = pd.DataFrame({
            "Test": ["Workload Scheduler", "Multi-Cloud Failover", "Privacy FL", "Fast OPF"],
            "Local": ["Ready", "Ready", "Ready", "Ready"],
            "HPC": ["Pending", "Pending", "Pending", "Pending"],
        })
        st.dataframe(tests, use_container_width=True, hide_index=True)

    # ── Timeline ──
    st.markdown('<div class="section-label">Metrics Timeline</div>', unsafe_allow_html=True)

    history = st.session_state.get("metrics_history", [])
    if history:
        df_h = pd.DataFrame(history)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_h["timestamp"], y=df_h["cpu"],
            name="Local CPU %", mode="lines+markers",
            line=dict(color=PLOT_COLORS["primary"], width=2),
            marker=dict(size=4),
        ))
        fig.add_trace(go.Scatter(
            x=df_h["timestamp"], y=df_h["memory"],
            name="Local Memory %", mode="lines+markers",
            line=dict(color=PLOT_COLORS["secondary"], width=2),
            marker=dict(size=4),
        ))
        fig.update_layout(
            **PLOTLY_LAYOUT,
            title="System Metrics Over Time",
            height=300,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02,
                xanchor="right", x=1, font=dict(size=11),
            ),
            xaxis=dict(title="Time", gridcolor=PLOT_COLORS["grid"]),
            yaxis=dict(title="Usage %", range=[0, 100], gridcolor=PLOT_COLORS["grid"]),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"{len(history)} data point(s) collected")
    else:
        st.info("Enable Local System monitoring to begin collecting metrics.")

    # ── Footer ──
    st.divider()
    st.caption(
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  ESRO v2.0"
    )


def _format_uptime() -> str:
    try:
        boot = datetime.fromtimestamp(psutil.boot_time())
        delta = datetime.now() - boot
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        if hours >= 24:
            days = hours // 24
            hours = hours % 24
            return f"{days}d {hours}h"
        return f"{hours}h {minutes}m"
    except Exception:
        return "N/A"


if __name__ == "__main__":
    main()