import os
from pathlib import Path
from .csv_source import CSVDataSource
from .snowflake_source import SnowflakeDataSource


def get_data_source():
    source_type = os.getenv("DATA_SOURCE_TYPE", "csv").lower()

    if source_type == "csv":
        default_csv_path = os.getenv("DEFAULT_INVOICE_CSV_PATH")

        # Railway fallback
        railway_path = "/app/neuraflow_invoices.csv"

        # Local fallback
        local_path = str(
            Path(__file__).resolve().parent.parent / "neuraflow_invoices.csv"
        )

        # If env var is missing OR points to a Mac path that does not exist in Railway
        if not default_csv_path:
            default_csv_path = railway_path if os.path.exists(railway_path) else local_path

        if default_csv_path.startswith("/Users/") and not os.path.exists(default_csv_path):
            default_csv_path = railway_path if os.path.exists(railway_path) else local_path

        return CSVDataSource(default_csv_path)

    if source_type == "snowflake":
        return SnowflakeDataSource()

    if source_type == "databricks":
        raise NotImplementedError("Databricks connector not added yet.")

    if source_type == "synapse":
        raise NotImplementedError("Synapse connector not added yet.")

    raise ValueError(f"Unsupported DATA_SOURCE_TYPE: {source_type}")