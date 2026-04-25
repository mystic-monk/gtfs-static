"""
Quality Dashboard Page.

Data quality metrics, validation results, and compliance monitoring.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

from src.config import settings
from src.utils.file_io import read_parquet


def main():
    """Quality dashboard page."""
    st.title("🔍 Quality Dashboard")
    st.markdown("Monitor data quality and validation results")
    
    # Load validation data
    validation_df = load_validation_summary()
    
    if validation_df.empty:
        st.warning("No validation data available.")
        st.info("Run the pipeline to generate validation reports.")
        return
    
    # Quality metrics
    st.header("Quality Metrics")
    
    col1, col2, col3 = st.columns(3)
    
    total_violations = validation_df["violation_count"].sum()
    critical_count = validation_df[validation_df["severity"] == "CRITICAL"]["violation_count"].sum()
    warning_count = validation_df[validation_df["severity"] == "WARNING"]["violation_count"].sum()
    
    with col1:
        st.metric("Total Violations", total_violations)
    
    with col2:
        critical_pct = critical_count/total_violations*100 if total_violations > 0 else 0
        st.metric("Critical Issues", critical_count, delta=f"{critical_pct:.1f}%")
    
    with col3:
        st.metric("Warnings", warning_count)
    
    st.divider()
    
    # Validation breakdown
    st.header("Validation Results by File")
    
    fig = px.bar(
        validation_df,
        x="source_file",
        y="violation_count",
        color="severity",
        color_discrete_map={"CRITICAL": "#FFA07A", "WARNING": "#87CEEB"},
        barmode="stack",
        title="Validation Violations by Severity"
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Rule performance
    st.header("Rule Performance")
    
    rule_summary = validation_df.groupby("rule_name").agg({
        "violation_count": "sum",
        "severity": "first"
    }).reset_index()
    
    fig = px.bar(
        rule_summary,
        x="rule_name",
        y="violation_count",
        color="severity",
        color_discrete_map={"CRITICAL": "#FFA07A", "WARNING": "#87CEEB"},
        title="Violations by Validation Rule"
    )
    fig.update_xaxes(tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)
    
    # Detailed table
    st.header("Detailed Validation Report")
    
    # Add filters
    col1, col2 = st.columns(2)
    
    with col1:
        severity_filter = st.multiselect(
            "Filter by Severity",
            options=validation_df["severity"].unique(),
            default=validation_df["severity"].unique()
        )
    
    with col2:
        file_filter = st.multiselect(
            "Filter by File",
            options=validation_df["source_file"].unique(),
            default=validation_df["source_file"].unique()
        )
    
    # Apply filters
    filtered_df = validation_df[
        (validation_df["severity"].isin(severity_filter)) &
        (validation_df["source_file"].isin(file_filter))
    ]
    
    st.dataframe(filtered_df, use_container_width=True)
    
    # Export option
    if st.button("📊 Export Validation Report"):
        csv_data = filtered_df.to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv_data,
            file_name="validation_report.csv",
            mime="text/csv"
        )


@st.cache_data(ttl=300)
def load_validation_summary():
    """Load validation summary."""
    quarantine_path = settings.QUARANTINE_OUTPUT
    if quarantine_path.exists():
        summary_file = quarantine_path / "validation_summary.parquet"
        if summary_file.exists():
            return read_parquet(str(summary_file))
    return pd.DataFrame()


if __name__ == "__main__":
    main()