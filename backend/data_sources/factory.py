import os
from pathlib import Path
from .csv_source import CSVDataSource
from .snowflake_source import SnowflakeDataSource


def get_data_source():
    source_type = os.getenv("DATA_SOURCE_TYPE", "csv").lower()

    if source_type == "csv":
        default_csv_path = Path(__file__).resolve().parent.parent / "cdm_model" / "data" / "invoices.csv"
        return CSVDataSource(str(default_csv_path))

    if source_type == "snowflake":
        return SnowflakeDataSource()

    if source_type == "databricks":
        raise NotImplementedError("Databricks connector not added yet.")

    if source_type == "synapse":
        raise NotImplementedError("Synapse connector not added yet.")

    raise ValueError(f"Unsupported DATA_SOURCE_TYPE: {source_type}")