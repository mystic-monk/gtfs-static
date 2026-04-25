"""
File I/O utilities for the Irish GTFS Analytics Platform.
"""
import io
import zipfile
from pathlib import Path
from typing import Optional, Dict, List
import pandas as pd
import pyarrow.parquet as pq
import logging

logger = logging.getLogger(__name__)


def read_parquet(path: Path) -> pd.DataFrame:
    """
    Read a Parquet file into a DataFrame.
    
    Args:
        path: Path to Parquet file
        
    Returns:
        pandas DataFrame
    """
    return pd.read_parquet(path)


def write_parquet(
    df: pd.DataFrame,
    path: Path,
    partition_cols: Optional[List[str]] = None,
    compression: str = "snappy",
) -> None:
    """
    Write a DataFrame to Parquet format.
    
    Args:
        df: pandas DataFrame to write
        path: Output path
        partition_cols: Columns to partition by (for Hive-style partitioning)
        compression: Compression codec ('snappy', 'gzip', 'brotli', 'zstd', 'lz4')
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    if partition_cols:
        df.to_parquet(
            path,
            engine="pyarrow",
            compression=compression,
            partition_cols=partition_cols,
        )
    else:
        df.to_parquet(
            path,
            engine="pyarrow",
            compression=compression,
        )
    
    logger.info(f"Wrote {len(df)} rows to {path}")


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    """
    Read a CSV file into a DataFrame.
    
    Args:
        path: Path to CSV file
        **kwargs: Additional pandas read_csv parameters
        
    Returns:
        pandas DataFrame
    """
    return pd.read_csv(path, **kwargs)


def write_csv(df: pd.DataFrame, path: Path, index: bool = False, **kwargs) -> None:
    """
    Write a DataFrame to CSV format.
    
    Args:
        df: pandas DataFrame to write
        path: Output path
        index: Whether to write index column
        **kwargs: Additional pandas to_csv parameters
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=index, **kwargs)
    logger.info(f"Wrote {len(df)} rows to {path}")


def extract_gtfs_zip(zip_path: Path, extract_to: Path) -> Dict[str, pd.DataFrame]:
    """
    Extract and parse all GTFS text files from a zip archive.
    
    Args:
        zip_path: Path to GTFS zip file
        extract_to: Directory to extract files to
        
    Returns:
        Dictionary mapping filename (without .txt) to DataFrame
    """
    expected_files = {
        "agency.txt",
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
        "calendar.txt",
        "calendar_dates.txt",
        "shapes.txt",
        "fare_attributes.txt",
        "fare_rules.txt",
        "feed_info.txt",
    }
    
    dfs = {}
    extract_to.mkdir(parents=True, exist_ok=True)
    
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # List all files in zip
            available_files = set(zip_ref.namelist())
            
            # Extract and read each file
            for gtfs_file in expected_files:
                if gtfs_file in available_files:
                    with zip_ref.open(gtfs_file) as f:
                        content = f.read().decode("utf-8")
                        df = pd.read_csv(io.StringIO(content), dtype=str, keep_default_na=False)
                        key = gtfs_file.replace(".txt", "")
                        dfs[key] = df
                        logger.info(f"Extracted {gtfs_file}: {len(df)} rows")
                else:
                    logger.warning(f"File {gtfs_file} not found in zip")
    
    except zipfile.BadZipFile:
        logger.error(f"Invalid zip file: {zip_path}")
        raise
    except Exception as e:
        logger.error(f"Error extracting {zip_path}: {e}")
        raise
    
    return dfs


def list_parquet_files(directory: Path) -> List[Path]:
    """
    List all Parquet files in a directory.
    
    Args:
        directory: Directory to search
        
    Returns:
        List of Path objects for Parquet files
    """
    if not directory.exists():
        return []
    
    return list(directory.glob("**/*.parquet")) + list(directory.glob("**/*.parquetformat"))


def get_parquet_row_count(path: Path) -> int:
    """
    Get row count from a Parquet file without loading all data.
    
    Args:
        path: Path to Parquet file
        
    Returns:
        Number of rows in the file
    """
    parquet_file = pq.ParquetFile(path)
    return parquet_file.metadata.num_rows


def cleanup_directory(directory: Path, pattern: str = "*") -> None:
    """
    Delete all files matching pattern in a directory.
    
    Args:
        directory: Directory to clean
        pattern: File pattern to match
    """
    if directory.exists():
        for file in directory.glob(pattern):
            file.unlink()
        logger.info(f"Cleaned up {directory}")
