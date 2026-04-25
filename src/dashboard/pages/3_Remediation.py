"""
Remediation Center Page.

Automated remediation actions and manual intervention tools.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

from src.config import settings
from src.utils.file_io import read_parquet
from src.remediation.engine import apply_remediation


def main():
    """Remediation center page."""
    st.title("🔧 Remediation Center")
    st.markdown("Automated fixes and manual intervention tools")
    
    # Load remediation data
    remediation_df = load_remediation_log()
    quarantine_df = load_quarantine_data()
    
    # Remediation stats
    st.header("Remediation Statistics")
    
    if not remediation_df.empty:
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
    if not remediation_df.empty:
        st.header("Remediation Actions Taken")
        
        action_counts = remediation_df["action_taken"].value_counts()
        fig = px.pie(
            values=action_counts.values,
            names=action_counts.index,
            title="Remediation Actions Distribution",
            color_discrete_sequence=['#2E8B57', '#8A2BE2', '#87CEEB', '#FFA07A']
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # Manual remediation tools
    st.header("Manual Remediation Tools")
    
    tab1, tab2 = st.tabs(["Quarantine Review", "Bulk Actions"])
    
    with tab1:
        show_quarantine_review(quarantine_df)
    
    with tab2:
        show_bulk_actions(quarantine_df)
    
    # Remediation log
    if not remediation_df.empty:
        st.header("Remediation Log")
        
        # Filters
        col1, col2 = st.columns(2)
        
        with col1:
            success_filter = st.selectbox(
                "Filter by Success",
                options=["All", "Successful", "Failed"],
                index=0
            )
        
        with col2:
            action_filter = st.multiselect(
                "Filter by Action",
                options=remediation_df["action_taken"].unique(),
                default=remediation_df["action_taken"].unique()
            )
        
        # Apply filters
        filtered_log = remediation_df.copy()
        
        if success_filter == "Successful":
            filtered_log = filtered_log[filtered_log["success"] == True]
        elif success_filter == "Failed":
            filtered_log = filtered_log[filtered_log["success"] == False]
        
        filtered_log = filtered_log[filtered_log["action_taken"].isin(action_filter)]
        
        st.dataframe(filtered_log, use_container_width=True)
        
        # Export
        if st.button("📊 Export Remediation Log"):
            csv_data = filtered_log.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name="remediation_log.csv",
                mime="text/csv"
            )


def show_quarantine_review(quarantine_df):
    """Show quarantine data for manual review."""
    if quarantine_df.empty:
        st.info("No quarantined records to review.")
        return
    
    st.subheader("Quarantined Records Review")
    
    # Show sample of quarantined records
    st.dataframe(quarantine_df.head(50), use_container_width=True)
    
    # Manual remediation form
    st.subheader("Manual Remediation")
    
    with st.form("manual_remediation"):
        record_id = st.selectbox(
            "Select Record ID",
            options=quarantine_df["record_id"].unique()
        )
        
        action = st.selectbox(
            "Remediation Action",
            options=[
                "fix_missing_stop_name",
                "fix_invalid_coordinates",
                "fix_route_agency_mismatch",
                "fix_time_sequence",
                "remove_duplicate",
                "custom_fix"
            ]
        )
        
        custom_value = st.text_input("Custom Value (if needed)") if action == "custom_fix" else ""
        
        submitted = st.form_submit_button("Apply Remediation")
        
        if submitted:
            # Apply manual remediation
            selected_record = quarantine_df[quarantine_df["record_id"] == record_id]
            if not selected_record.empty:
                try:
                    # Call remediation engine
                    result_df, log_df = apply_remediation(selected_record, auto_remediate=True)
                    
                    if not log_df.empty and log_df.iloc[0]["success"]:
                        st.success("✅ Manual remediation applied successfully!")
                    else:
                        st.error("❌ Manual remediation failed.")
                        
                except Exception as e:
                    st.error(f"Error applying remediation: {e}")
            else:
                st.error("Record not found.")


def show_bulk_actions(quarantine_df):
    """Show bulk remediation actions."""
    if quarantine_df.empty:
        st.info("No quarantined records for bulk actions.")
        return
    
    st.subheader("Bulk Remediation Actions")
    
    # Action selection
    action = st.selectbox(
        "Select Bulk Action",
        options=[
            "fix_all_missing_stop_names",
            "fix_all_invalid_coordinates",
            "remove_all_duplicates",
            "approve_all_warnings"
        ]
    )
    
    # Preview affected records
    affected_count = len(quarantine_df)  # Simplified - in real app, filter by action type
    
    st.info(f"This action will affect {affected_count} records.")
    
    if st.button("Execute Bulk Remediation", type="primary"):
        try:
            # Apply bulk remediation
            result_df, log_df = apply_remediation(quarantine_df, auto_remediate=True)
            
            success_count = (log_df["success"] == True).sum() if not log_df.empty else 0
            st.success(f"✅ Bulk remediation completed! {success_count}/{len(quarantine_df)} records successfully remediated.")
            
        except Exception as e:
            st.error(f"Error in bulk remediation: {e}")


@st.cache_data(ttl=300)
def load_remediation_log():
    """Load remediation log."""
    quarantine_path = settings.QUARANTINE_OUTPUT
    if quarantine_path.exists():
        log_file = quarantine_path / "remediation_log.parquet"
        if log_file.exists():
            return read_parquet(str(log_file))
    return pd.DataFrame()


@st.cache_data(ttl=300)
def load_quarantine_data():
    """Load quarantine data."""
    quarantine_path = settings.QUARANTINE_OUTPUT
    if quarantine_path.exists():
        quarantine_file = quarantine_path / "quarantine.parquet"
        if quarantine_file.exists():
            return read_parquet(str(quarantine_file))
    return pd.DataFrame()


if __name__ == "__main__":
    main()