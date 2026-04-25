"""
Data Explorer Page.

Interactive data exploration and analysis tools.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import numpy as np

from src.config import settings
from src.utils.file_io import read_parquet


def main():
    """Data explorer page."""
    st.title("🔬 Data Explorer")
    st.markdown("Interactive exploration of analytics tables")
    
    # Load data
    gold_tables = load_gold_tables()
    
    if not gold_tables:
        st.warning("No data available for exploration.")
        st.info("Run the pipeline to generate analytics tables.")
        return
    
    # Table selector
    selected_table = st.selectbox(
        "Select a table to explore:",
        list(gold_tables.keys()),
        help="Choose from the available analytics tables"
    )
    
    if selected_table:
        df = gold_tables[selected_table]
        
        # Table overview
        st.header("Table Overview")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Rows", len(df))
        
        with col2:
            st.metric("Columns", len(df.columns))
        
        with col3:
            memory_usage = df.memory_usage(deep=True).sum() / 1024 / 1024  # MB
            st.metric("Memory Usage", f"{memory_usage:.1f} MB")
        
        with col4:
            duplicate_count = df.duplicated().sum()
            st.metric("Duplicates", duplicate_count)
        
        # Data preview
        st.header("Data Preview")
        
        # Add pagination for large tables
        page_size = st.selectbox("Rows per page", [10, 25, 50, 100], index=1)
        page_number = st.number_input("Page", min_value=1, max_value=(len(df) // page_size) + 1, value=1)
        
        start_idx = (page_number - 1) * page_size
        end_idx = start_idx + page_size
        
        st.dataframe(df.iloc[start_idx:end_idx], use_container_width=True)
        
        # Column analysis
        st.header("Column Analysis")
        
        tab1, tab2, tab3 = st.tabs(["Data Types", "Missing Values", "Statistics"])
        
        with tab1:
            show_data_types(df)
        
        with tab2:
            show_missing_values(df)
        
        with tab3:
            show_statistics(df)
        
        # Visualization
        st.header("Quick Visualizations")
        
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
        
        if numeric_cols:
            # Distribution plots
            selected_numeric = st.selectbox(
                "Select numeric column for distribution:",
                numeric_cols,
                key="numeric_dist"
            )
            
            if selected_numeric:
                fig = px.histogram(
                    df,
                    x=selected_numeric,
                    title=f"Distribution of {selected_numeric}",
                    color_discrete_sequence=['#2E8B57']
                )
                st.plotly_chart(fig, use_container_width=True)
        
        if len(numeric_cols) >= 2:
            # Scatter plot
            col1, col2 = st.columns(2)
            
            with col1:
                x_col = st.selectbox("X-axis:", numeric_cols, key="scatter_x")
            
            with col2:
                y_col = st.selectbox("Y-axis:", numeric_cols, key="scatter_y")
            
            if x_col and y_col and x_col != y_col:
                fig = px.scatter(
                    df,
                    x=x_col,
                    y=y_col,
                    title=f"{y_col} vs {x_col}",
                    color_discrete_sequence=['#2E8B57']
                )
                st.plotly_chart(fig, use_container_width=True)
        
        if categorical_cols:
            # Bar chart for categorical data
            selected_cat = st.selectbox(
                "Select categorical column for bar chart:",
                categorical_cols,
                key="cat_bar"
            )
            
            if selected_cat:
                value_counts = df[selected_cat].value_counts().head(20)  # Top 20
                fig = px.bar(
                    x=value_counts.index,
                    y=value_counts.values,
                    title=f"Top values in {selected_cat}",
                    color_discrete_sequence=['#8A2BE2']
                )
                fig.update_xaxes(tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)
        
        # Advanced filtering
        st.header("Advanced Filtering")
        
        with st.expander("Filter Data"):
            filtered_df = df.copy()
            
            # Add filters for each column
            filter_cols = st.multiselect(
                "Select columns to filter:",
                df.columns.tolist()
            )
            
            for col in filter_cols:
                if df[col].dtype in ['object', 'category']:
                    # Categorical filter
                    unique_vals = df[col].unique()
                    if len(unique_vals) <= 20:  # Only show if not too many unique values
                        selected_vals = st.multiselect(
                            f"Filter {col}:",
                            unique_vals,
                            default=unique_vals.tolist()
                        )
                        filtered_df = filtered_df[filtered_df[col].isin(selected_vals)]
                    else:
                        # Text search for large categorical columns
                        search_term = st.text_input(f"Search in {col}:")
                        if search_term:
                            filtered_df = filtered_df[filtered_df[col].str.contains(search_term, case=False, na=False)]
                
                elif df[col].dtype in ['int64', 'float64']:
                    # Numeric filter
                    min_val, max_val = st.slider(
                        f"Filter {col}:",
                        float(df[col].min()),
                        float(df[col].max()),
                        (float(df[col].min()), float(df[col].max()))
                    )
                    filtered_df = filtered_df[(filtered_df[col] >= min_val) & (filtered_df[col] <= max_val)]
            
            st.write(f"Filtered to {len(filtered_df)} rows")
            st.dataframe(filtered_df.head(50), use_container_width=True)
        
        # Export options
        st.header("Export Data")
        
        col1, col2, col3 = st.columns(3)
        
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
                # Note: In real implementation, would use openpyxl or similar
                st.info("Excel export would be implemented with openpyxl library")
        
        with col3:
            if st.button("📋 Export Filtered Data"):
                if 'filtered_df' in locals():
                    csv_data = filtered_df.to_csv(index=False)
                    st.download_button(
                        label="Download Filtered CSV",
                        data=csv_data,
                        file_name=f"{selected_table}_filtered.csv",
                        mime="text/csv"
                    )


def show_data_types(df):
    """Show data types analysis."""
    st.subheader("Data Types")
    
    dtype_df = pd.DataFrame({
        'Column': df.columns,
        'Data Type': df.dtypes,
        'Non-Null Count': df.count(),
        'Null Count': df.isnull().sum()
    })
    
    st.dataframe(dtype_df, use_container_width=True)
    
    # Data type distribution
    dtype_counts = df.dtypes.value_counts()
    fig = px.pie(
        values=dtype_counts.values,
        names=dtype_counts.index,
        title="Data Type Distribution",
        color_discrete_sequence=['#2E8B57', '#8A2BE2', '#87CEEB', '#FFA07A']
    )
    st.plotly_chart(fig, use_container_width=True)


def show_missing_values(df):
    """Show missing values analysis."""
    st.subheader("Missing Values")
    
    null_counts = df.isnull().sum()
    null_percent = (null_counts / len(df) * 100).round(2)
    
    missing_df = pd.DataFrame({
        'Column': null_counts.index,
        'Missing Count': null_counts.values,
        'Missing Percentage': null_percent.values
    }).sort_values('Missing Count', ascending=False)
    
    # Only show columns with missing values
    missing_df = missing_df[missing_df['Missing Count'] > 0]
    
    if not missing_df.empty:
        st.dataframe(missing_df, use_container_width=True)
        
        # Missing values heatmap
        fig = go.Figure(data=go.Heatmap(
            z=df.isnull().values,
            x=df.columns,
            y=df.index,
            colorscale=['#98FB98', '#FFA07A'],
            showscale=False
        ))
        fig.update_layout(
            title="Missing Values Heatmap (sample)",
            xaxis_title="Columns",
            yaxis_title="Rows",
            height=400
        )
        # Only show first 100 rows for performance
        fig.update_yaxes(range=[0, min(100, len(df))])
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.success("No missing values found in this table!")


def show_statistics(df):
    """Show statistical analysis."""
    st.subheader("Statistical Summary")
    
    # Numeric columns statistics
    numeric_df = df.select_dtypes(include=[np.number])
    if not numeric_df.empty:
        st.write("**Numeric Columns:**")
        st.dataframe(numeric_df.describe(), use_container_width=True)
    
    # Categorical columns statistics
    categorical_df = df.select_dtypes(include=['object', 'category'])
    if not categorical_df.empty:
        st.write("**Categorical Columns:**")
        cat_stats = []
        for col in categorical_df.columns:
            unique_count = df[col].nunique()
            most_common = df[col].mode().iloc[0] if not df[col].mode().empty else "N/A"
            cat_stats.append({
                'Column': col,
                'Unique Values': unique_count,
                'Most Common': most_common
            })
        st.dataframe(pd.DataFrame(cat_stats), use_container_width=True)


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