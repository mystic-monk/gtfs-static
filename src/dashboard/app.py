"""
Streamlit dashboard for Irish GTFS Analytics Platform.

Features a clean, pastel color palette and comprehensive analytics views.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import json
from datetime import datetime, timedelta

# Import our modules
from src.config import settings
from src.utils.file_io import read_parquet

# Configure page
st.set_page_config(
    page_title="Irish GTFS Analytics",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for pastel theme
st.markdown("""
<style>
    .main-header {
        color: #2E8B57;
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #F0F8FF;
        padding: 1rem;
        border-radius: 10px;
        border-left: 5px solid #87CEEB;
        margin: 0.5rem 0;
    }
    .sidebar-header {
        color: #8A2BE2;
        font-size: 1.2rem;
        font-weight: bold;
        margin-bottom: 1rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #FFF8DC;
        border-radius: 4px 4px 0 0;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FFE4E1;
    }
</style>
""", unsafe_allow_html=True)

# Color palette
COLORS = {
    'primary': '#2E8B57',      # Sea Green
    'secondary': '#8A2BE2',    # Blue Violet
    'accent': '#87CEEB',       # Sky Blue
    'warning': '#FFA07A',      # Light Salmon
    'success': '#98FB98',      # Pale Green
    'background': '#FFF8DC',   # Cornsilk
    'text': '#2F4F4F'          # Dark Slate Gray
}


def load_gold_tables():
    """Load all gold layer tables."""
    gold_path = settings.GOLD_OUTPUT
    tables = {}
    
    if gold_path.exists():
        for file_path in gold_path.glob("*.parquet"):
            table_name = file_path.stem
            try:
                tables[table_name] = read_parquet(str(file_path))
            except Exception as e:
                st.warning(f"Could not load {table_name}: {e}")
    
    return tables


def load_monitoring_data():
    """Load monitoring data."""
    monitoring_path = settings.MONITORING_OUTPUT
    if monitoring_path.exists():
        metrics_file = monitoring_path / "quality_metrics.parquet"
        if metrics_file.exists():
            return read_parquet(str(metrics_file))
    return pd.DataFrame()


def load_validation_summary():
    """Load validation summary."""
    quarantine_path = settings.QUARANTINE_OUTPUT
    if quarantine_path.exists():
        summary_file = quarantine_path / "validation_summary.parquet"
        if summary_file.exists():
            return read_parquet(str(summary_file))
    return pd.DataFrame()


def main():
    """Main dashboard application."""
    
    # Sidebar
    with st.sidebar:
        st.markdown('<div class="sidebar-header">🚌 Irish GTFS Analytics</div>', unsafe_allow_html=True)
        
        # Navigation
        page = st.radio(
            "Navigation",
            ["Overview", "Quality Dashboard", "Remediation Center", "Monitoring", "Data Explorer"],
            label_visibility="collapsed"
        )
        
        st.divider()
        
        # Quick stats
        gold_tables = load_gold_tables()
        if gold_tables:
            total_records = sum(len(df) for df in gold_tables.values())
            st.metric("Total Records", f"{total_records:,}")
        
        # Last update
        gold_path = settings.GOLD_OUTPUT
        if gold_path.exists():
            latest_file = max(gold_path.glob("*.parquet"), key=lambda x: x.stat().st_mtime, default=None)
            if latest_file:
                last_update = datetime.fromtimestamp(latest_file.stat().st_mtime)
                st.caption(f"Last updated: {last_update.strftime('%Y-%m-%d %H:%M')}")
    
    # Page routing
    if page == "Overview":
        show_overview_page(gold_tables)
    elif page == "Quality Dashboard":
        show_quality_page()
    elif page == "Remediation Center":
        show_remediation_page()
    elif page == "Monitoring":
        show_monitoring_page()
    elif page == "Data Explorer":
        show_explorer_page(gold_tables)


def show_overview_page(gold_tables):
    """Overview dashboard page."""
    st.markdown('<div class="main-header">📊 Overview Dashboard</div>', unsafe_allow_html=True)
    
    if not gold_tables:
        st.warning("No data available. Please run the pipeline first.")
        return
    
    # Key metrics row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if "route_summary" in gold_tables:
            route_count = len(gold_tables["route_summary"])
            st.metric("Active Routes", route_count)
    
    with col2:
        if "stop_activity" in gold_tables:
            stop_count = gold_tables["stop_activity"]["stop_id"].nunique()
            st.metric("Bus Stops", stop_count)
    
    with col3:
        if "operator_performance" in gold_tables:
            avg_rating = gold_tables["operator_performance"]["avg_rating"].mean()
            st.metric("Avg Operator Rating", f"{avg_rating:.1f}/5")
    
    with col4:
        if "headway_analysis" in gold_tables:
            avg_headway = gold_tables["headway_analysis"]["avg_headway_minutes"].mean()
            st.metric("Avg Headway", f"{avg_headway:.0f} min")
    
    st.divider()
    
    # Charts row
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🚇 Routes by Type")
        if "route_summary" in gold_tables:
            route_type_counts = gold_tables["route_summary"]["route_type"].value_counts()
            fig = px.pie(
                values=route_type_counts.values,
                names=route_type_counts.index,
                color_discrete_sequence=[COLORS['primary'], COLORS['secondary'], COLORS['accent']]
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color=COLORS['text']
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("📍 Top 10 Busiest Stops")
        if "stop_activity" in gold_tables:
            top_stops = gold_tables["stop_activity"].nlargest(10, "daily_trips")
            fig = px.bar(
                top_stops,
                x="stop_name",
                y="daily_trips",
                color_discrete_sequence=[COLORS['primary']]
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color=COLORS['text'],
                xaxis_tickangle=-45
            )
            st.plotly_chart(fig, use_container_width=True)
    
    # Additional insights
    st.subheader("🔍 Key Insights")
    
    insights = []
    
    if "temporal_patterns" in gold_tables:
        peak_hour = gold_tables["temporal_patterns"].loc[
            gold_tables["temporal_patterns"]["hourly_trips"].idxmax()
        ]["hour"]
        insights.append(f"Peak travel hour: {peak_hour}:00")
    
    if "operator_performance" in gold_tables:
        best_operator = gold_tables["operator_performance"].loc[
            gold_tables["operator_performance"]["avg_rating"].idxmax()
        ]["operator_name"]
        insights.append(f"Top-rated operator: {best_operator}")
    
    if insights:
        for insight in insights:
            st.markdown(f"• {insight}")
    else:
        st.info("Run the full pipeline to generate insights.")


def show_quality_page():
    """Quality dashboard page."""
    st.markdown('<div class="main-header">🔍 Quality Dashboard</div>', unsafe_allow_html=True)
    
    validation_df = load_validation_summary()
    
    if validation_df.empty:
        st.warning("No validation data available.")
        return
    
    # Quality metrics
    col1, col2, col3 = st.columns(3)
    
    total_violations = validation_df["violation_count"].sum()
    critical_count = validation_df[validation_df["severity"] == "CRITICAL"]["violation_count"].sum()
    warning_count = validation_df[validation_df["severity"] == "WARNING"]["violation_count"].sum()
    
    with col1:
        st.metric("Total Violations", total_violations)
    
    with col2:
        st.metric("Critical Issues", critical_count, delta=f"{critical_count/total_violations*100:.1f}%" if total_violations > 0 else "0%")
    
    with col3:
        st.metric("Warnings", warning_count)
    
    st.divider()
    
    # Validation breakdown
    st.subheader("📋 Validation Results by File")
    
    fig = px.bar(
        validation_df,
        x="source_file",
        y="violation_count",
        color="severity",
        color_discrete_map={"CRITICAL": COLORS['warning'], "WARNING": COLORS['accent']},
        barmode="stack"
    )
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font_color=COLORS['text']
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Detailed table
    st.subheader("📊 Detailed Validation Report")
    st.dataframe(validation_df, use_container_width=True)


def show_remediation_page():
    """Remediation center page."""
    st.markdown('<div class="main-header">🔧 Remediation Center</div>', unsafe_allow_html=True)
    
    quarantine_path = settings.QUARANTINE_OUTPUT
    remediation_file = quarantine_path / "remediation_log.parquet"
    
    if not remediation_file.exists():
        st.info("No remediation data available. Enable auto-remediation in config to generate logs.")
        return
    
    try:
        remediation_df = read_parquet(str(remediation_file))
        
        # Remediation stats
        col1, col2, col3 = st.columns(3)
        
        total_remediated = len(remediation_df)
        success_rate = (remediation_df["success"] == True).sum() / total_remediated * 100 if total_remediated > 0 else 0
        
        with col1:
            st.metric("Records Remediated", total_remediated)
        
        with col2:
            st.metric("Success Rate", f"{success_rate:.1f}%")
        
        with col3:
            failed_count = (remediation_df["success"] == False).sum()
            st.metric("Failed Remediations", failed_count)
        
        st.divider()
        
        # Remediation actions
        st.subheader("🛠️ Remediation Actions Taken")
        
        action_counts = remediation_df["action_taken"].value_counts()
        fig = px.pie(
            values=action_counts.values,
            names=action_counts.index,
            color_discrete_sequence=[COLORS['primary'], COLORS['secondary'], COLORS['accent'], COLORS['warning']]
        )
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color=COLORS['text']
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Detailed log
        st.subheader("📋 Remediation Log")
        st.dataframe(remediation_df, use_container_width=True)
        
    except Exception as e:
        st.error(f"Could not load remediation data: {e}")


def show_monitoring_page():
    """Monitoring dashboard page."""
    st.markdown('<div class="main-header">📈 Monitoring Dashboard</div>', unsafe_allow_html=True)
    
    monitoring_df = load_monitoring_data()
    
    if monitoring_df.empty:
        st.warning("No monitoring data available.")
        return
    
    # Time series of quality metrics
    st.subheader("📊 Quality Metrics Over Time")
    
    if "timestamp" in monitoring_df.columns:
        monitoring_df["timestamp"] = pd.to_datetime(monitoring_df["timestamp"])
        
        # Select metrics to plot
        metric_cols = [col for col in monitoring_df.columns if col not in ["timestamp", "operator"]]
        
        if metric_cols:
            fig = px.line(
                monitoring_df,
                x="timestamp",
                y=metric_cols,
                color_discrete_sequence=[COLORS['primary'], COLORS['secondary'], COLORS['accent'], COLORS['warning']]
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color=COLORS['text']
            )
            st.plotly_chart(fig, use_container_width=True)
    
    # Current status
    st.subheader("📍 Current Status")
    
    latest_metrics = monitoring_df.iloc[-1] if not monitoring_df.empty else {}
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        data_freshness = latest_metrics.get("data_freshness_hours", 0)
        status_color = "🟢" if data_freshness < 24 else "🟡" if data_freshness < 48 else "🔴"
        st.metric("Data Freshness", f"{data_freshness:.1f}h", delta=status_color)
    
    with col2:
        quality_score = latest_metrics.get("overall_quality_score", 0)
        st.metric("Quality Score", f"{quality_score:.2f}/10")
    
    with col3:
        violation_rate = latest_metrics.get("violation_rate_percent", 0)
        st.metric("Violation Rate", f"{violation_rate:.1f}%")
    
    with col4:
        drift_score = latest_metrics.get("drift_score", 0)
        st.metric("Drift Score", f"{drift_score:.2f}")
    
    # Alerts
    st.subheader("🚨 Active Alerts")
    
    alerts = []
    if data_freshness > 48:
        alerts.append("⚠️ Data is stale (>48 hours old)")
    if quality_score < 7:
        alerts.append("⚠️ Quality score below threshold")
    if violation_rate > 5:
        alerts.append("⚠️ High violation rate detected")
    
    if alerts:
        for alert in alerts:
            st.warning(alert)
    else:
        st.success("✅ All systems normal")


def show_explorer_page(gold_tables):
    """Data explorer page."""
    st.markdown('<div class="main-header">🔬 Data Explorer</div>', unsafe_allow_html=True)
    
    if not gold_tables:
        st.warning("No data available for exploration.")
        return
    
    # Table selector
    selected_table = st.selectbox(
        "Select a table to explore:",
        list(gold_tables.keys()),
        help="Choose from the available analytics tables"
    )
    
    if selected_table:
        df = gold_tables[selected_table]
        
        # Table info
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Rows", len(df))
        
        with col2:
            st.metric("Columns", len(df.columns))
        
        with col3:
            memory_usage = df.memory_usage(deep=True).sum() / 1024 / 1024  # MB
            st.metric("Memory Usage", f"{memory_usage:.1f} MB")
        
        # Data preview
        st.subheader("📋 Data Preview")
        st.dataframe(df.head(100), use_container_width=True)
        
        # Column analysis
        st.subheader("📊 Column Analysis")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Data Types:**")
            dtype_counts = df.dtypes.value_counts()
            for dtype, count in dtype_counts.items():
                st.write(f"- {dtype}: {count} columns")
        
        with col2:
            st.write("**Missing Values:**")
            null_counts = df.isnull().sum()
            if null_counts.sum() > 0:
                null_percent = (null_counts / len(df) * 100).round(2)
                null_df = pd.DataFrame({
                    "Column": null_counts.index,
                    "Missing": null_counts.values,
                    "Percent": null_percent.values
                }).sort_values("Missing", ascending=False)
                null_df = null_df[null_df["Missing"] > 0]
                st.dataframe(null_df, use_container_width=True)
            else:
                st.success("No missing values found!")
        
        # Export option
        st.subheader("💾 Export Data")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📊 Export to CSV"):
                csv_data = df.to_csv(index=False)
                st.download_button(
                    label="Download CSV",
                    data=csv_data,
                    file_name=f"{selected_table}.csv",
                    mime="text/csv"
                )
        
        with col2:
            if st.button("📈 Export to Excel"):
                excel_data = df.to_excel(index=False)
                st.download_button(
                    label="Download Excel",
                    data=excel_data,
                    file_name=f"{selected_table}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )


if __name__ == "__main__":
    main()