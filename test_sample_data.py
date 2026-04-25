"""
Quick test to generate and load sample GTFS data.
"""
from src.ingestion.sample_data import create_sample_gtfs_zip
from pathlib import Path

# Create sample data ZIP
output_zip = Path("outputs/sample_dublin_bus.zip")
create_sample_gtfs_zip(output_zip)

print(f"\n✅ Sample GTFS ZIP created at: {output_zip}")
print(f"File size: {output_zip.stat().st_size / 1024:.1f} KB")

# Test loading it
from src.utils.file_io import extract_gtfs_zip
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    tmppath = Path(tmpdir)
    gtfs_dfs = extract_gtfs_zip(output_zip, tmppath)
    
    print(f"\n📊 Loaded GTFS files:")
    for file_name, df in gtfs_dfs.items():
        print(f"  - {file_name}: {len(df)} rows")
    
    total_records = sum(len(df) for df in gtfs_dfs.values())
    print(f"\n✅ Total records: {total_records}")