"""
Overview Dashboard Page.

Main landing page with key metrics and high-level insights.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

from src.config import settings
from src.utils.file_io import read_parquet


def main():
    """Overview dashboard page."""
    st.title("📊 Overview Dashboard")
    st.markdown("Welcome to the Irish GTFS Analytics Platform")
    
    # Load data
    gold_tables = load_gold_tables()
    
    if not gold_tables:
        st.warning("No data available. Please run the pipeline first.")
        st.info("Use `python -m src.ingestion.pipeline` to run the full pipeline.")
        return
    
    # Key metrics
    st.header("Key Metrics")
    
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
    
    # Visualizations
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🚇 Routes by Type")
        if "route_summary" in gold_tables:
            route_type_counts = gold_tables["route_summary"]["route_type"].value_counts()
            fig = px.pie(
                values=route_type_counts.values,
                names=route_type_counts.index,
                color_discrete_sequence=['#2E8B57', '#8A2BE2', '#87CEEB']
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
                color_discrete_sequence=['#2E8B57']
            )
            fig.update_xaxes(tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
    
    # Insights
    st.header("🔍 Key Insights")
    
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


@st.cache_data(ttl=300)
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


if __name__ == "__main__":
    main()