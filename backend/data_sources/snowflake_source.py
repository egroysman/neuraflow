import os
from typing import Optional, Dict, Any
from .base import BaseDataSource


class SnowflakeDataSource(BaseDataSource):
    def __init__(self):
        self.account = os.getenv("SNOWFLAKE_ACCOUNT")
        self.user = os.getenv("SNOWFLAKE_USER")
        self.password = os.getenv("SNOWFLAKE_PASSWORD")
        self.warehouse = os.getenv("SNOWFLAKE_WAREHOUSE")
        self.database = os.getenv("SNOWFLAKE_DATABASE")
        self.schema = os.getenv("SNOWFLAKE_SCHEMA")

    def _connect(self):
        try:
            import snowflake.connector
        except ImportError:
            raise Exception("snowflake-connector-python not installed")

        return snowflake.connector.connect(
            user=self.user,
            password=self.password,
            account=self.account,
            warehouse=self.warehouse,
            database=self.database,
            schema=self.schema,
        )

    def get_customer_summaries(self, uploaded_file_bytes: Optional[bytes] = None) -> Dict[str, Any]:
        conn = self._connect()
        cursor = conn.cursor()

        try:
            query = """
                SELECT
                    CustomerID,
                    COUNT(*) AS invoice_count,
                    SUM(InvoiceAmount) AS total_amount,
                    SUM(CASE WHEN DueDate < CURRENT_DATE THEN InvoiceAmount ELSE 0 END) AS overdue_amount,
                    MAX(DueDate) AS latest_due_date,
                    MIN(InvoiceDate) AS oldest_invoice_date
                FROM invoices
                GROUP BY CustomerID
            """

            cursor.execute(query)
            rows = cursor.fetchall()

            columns = [col[0] for col in cursor.description]

            customer_summaries = []
            for row in rows:
                record = dict(zip(columns, row))
                customer_summaries.append({
                    "customer_id": str(record.get("CUSTOMERID")),
                    "invoice_count": int(record.get("INVOICE_COUNT", 0)),
                    "total_amount": float(record.get("TOTAL_AMOUNT", 0)),
                    "overdue_amount": float(record.get("OVERDUE_AMOUNT", 0)),
                    "latest_due_date": str(record.get("LATEST_DUE_DATE")),
                    "oldest_invoice_date": str(record.get("OLDEST_INVOICE_DATE")),
                })

            return {
                "customer_count": len(customer_summaries),
                "customer_summaries": customer_summaries,
                "source_type": "snowflake"
            }

        finally:
            cursor.close()
            conn.close()

    def get_customer_detail(self, customer_id: str, uploaded_file_bytes: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()

        try:
            query = f"""
                SELECT *
                FROM invoices
                WHERE CustomerID = '{customer_id}'
            """

            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [col[0] for col in cursor.description]

            invoices = [dict(zip(columns, row)) for row in rows]

            return {
                "customer_id": customer_id,
                "invoices": invoices
            }

        finally:
            cursor.close()
            conn.close()