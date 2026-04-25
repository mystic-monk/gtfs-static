"""
Monitoring Dashboard Page.

Time-series monitoring, alerts, and system health metrics.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta

from src.config import settings
from src.utils.file_io import read_parquet


def main():
    """Monitoring dashboard page."""
    st.title("📈 Monitoring Dashboard")
    st.markdown("System health, quality trends, and alerting")
    
    # Load monitoring data
    monitoring_df = load_monitoring_data()
    
    if monitoring_df.empty:
        st.warning("No monitoring data available.")
        st.info("Run the pipeline to generate monitoring metrics.")
        return
    
    # Current status
    st.header("Current System Status")
    
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
    
    # Active alerts
    st.header("Active Alerts")
    
    alerts = []
    if data_freshness > 48:
        alerts.append("⚠️ Data is stale (>48 hours old)")
    if quality_score < 7:
        alerts.append("⚠️ Quality score below threshold")
    if violation_rate > 5:
        alerts.append("⚠️ High violation rate detected")
    if drift_score > 0.5:
        alerts.append("⚠️ Significant data drift detected")
    
    if alerts:
        for alert in alerts:
            st.warning(alert)
    else:
        st.success("✅ All systems normal")
    
    st.divider()
    
    # Time series charts
    st.header("Quality Trends Over Time")
    
    if "timestamp" in monitoring_df.columns:
        monitoring_df["timestamp"] = pd.to_datetime(monitoring_df["timestamp"])
        
        # Select metrics to plot
        metric_cols = [col for col in monitoring_df.columns if col not in ["timestamp", "operator"]]
        
        if metric_cols:
            # Create subplots for multiple metrics
            fig = go.Figure()
            
            colors = ['#2E8B57', '#8A2BE2', '#87CEEB', '#FFA07A', '#98FB98']
            
            for i, metric in enumerate(metric_cols[:5]):  # Limit to 5 metrics
                fig.add_trace(go.Scatter(
                    x=monitoring_df["timestamp"],
                    y=monitoring_df[metric],
                    mode='lines+markers',
                    name=metric.replace('_', ' ').title(),
                    line=dict(color=colors[i % len(colors)])
                ))
            
            fig.update_layout(
                title="Quality Metrics Time Series",
                xaxis_title="Time",
                yaxis_title="Value",
                hovermode="x unified"
            )
            
            st.plotly_chart(fig, use_container_width=True)
    
    # Quality score breakdown
    st.header("Quality Score Components")
    
    if not monitoring_df.empty:
        # Get latest values for quality components
        components = {
            "Data Completeness": latest_metrics.get("data_completeness_score", 0),
            "Data Accuracy": latest_metrics.get("data_accuracy_score", 0),
            "Timeliness": latest_metrics.get("timeliness_score", 0),
            "Consistency": latest_metrics.get("consistency_score", 0)
        }
        
        # Create radar chart
        fig = go.Figure()
        
        fig.add_trace(go.Scatterpolar(
            r=list(components.values()),
            theta=list(components.keys()),
            fill='toself',
            name='Quality Components',
            line=dict(color='#2E8B57')
        ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 10]
                )
            ),
            showlegend=False,
            title="Quality Score Components"
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    # Historical alerts
    st.header("Alert History")
    
    # Generate sample alert history (in real app, this would come from monitoring logs)
    alert_history = generate_alert_history(monitoring_df)
    
    if not alert_history.empty:
        st.dataframe(alert_history, use_container_width=True)
    
    # Export monitoring data
    st.header("Export Monitoring Data")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📊 Export Metrics"):
            csv_data = monitoring_df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name="monitoring_metrics.csv",
                mime="text/csv"
            )
    
    with col2:
        if st.button("📋 Export Alerts"):
            if not alert_history.empty:
                csv_data = alert_history.to_csv(index=False)
                st.download_button(
                    label="Download CSV",
                    data=csv_data,
                    file_name="alert_history.csv",
                    mime="text/csv"
                )


@st.cache_data(ttl=300)
def load_monitoring_data():
    """Load monitoring data."""
    monitoring_path = settings.MONITORING_OUTPUT
    if monitoring_path.exists():
        metrics_file = monitoring_path / "quality_metrics.parquet"
        if metrics_file.exists():
            return read_parquet(str(metrics_file))
    return pd.DataFrame()


def generate_alert_history(monitoring_df):
    """Generate alert history from monitoring data."""
    if monitoring_df.empty:
        return pd.DataFrame()
    
    alerts = []
    
    for _, row in monitoring_df.iterrows():
        timestamp = row.get("timestamp", datetime.now())
        
        # Check for alerts
        if row.get("data_freshness_hours", 0) > 48:
            alerts.append({
                "timestamp": timestamp,
                "alert_type": "Data Staleness",
                "severity": "WARNING",
                "message": f"Data is {row['data_freshness_hours']:.1f} hours old"
            })
        
        if row.get("overall_quality_score", 10) < 7:
            alerts.append({
                "timestamp": timestamp,
                "alert_type": "Quality Degradation",
                "severity": "WARNING",
                "message": f"Quality score dropped to {row['overall_quality_score']:.2f}"
            })
        
        if row.get("violation_rate_percent", 0) > 5:
            alerts.append({
                "timestamp": timestamp,
                "alert_type": "High Violation Rate",
                "severity": "CRITICAL",
                "message": f"Violation rate is {row['violation_rate_percent']:.1f}%"
            })
    
    return pd.DataFrame(alerts).sort_values("timestamp", ascending=False)


if __name__ == "__main__":
    main()