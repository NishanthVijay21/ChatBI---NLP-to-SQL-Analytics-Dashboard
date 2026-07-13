"""
data_engine.py
Multi-table DuckDB engine. Key changes from v1:
  - tables dict: tracks all loaded tables, not just one
  - load_file() no longer clobbers previous tables
  - merge_tables(): runs a user-described join and stores the result as a new table
  - all_schemas_description(): single string covering every loaded table, for the LLM
"""

import re
import duckdb
import pandas as pd


def sanitize_ident(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if re.match(r"^\d", cleaned):
        cleaned = f"_{cleaned}"
    return cleaned or "dataset"


class DataEngine:
    DESTRUCTIVE_SQL = re.compile(
        r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|TRUNCATE|ATTACH|COPY)\b", re.IGNORECASE
    )

    def __init__(self):
        self.con = duckdb.connect(database=":memory:")
        self.tables: dict[str, dict] = {}

    # ------------------------------------------------------------------ loading

    def load_file(self, uploaded_file, filename: str) -> str:
        """Load one file into a new DuckDB table. Returns the table name."""
        table_name = sanitize_ident(filename.rsplit(".", 1)[0])
        base = table_name
        idx = 2
        while table_name in self.tables:
            table_name = f"{base}_{idx}"
            idx += 1

        lower = filename.lower()
        if lower.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        elif lower.endswith((".xlsx", ".xls")):
            df = pd.read_excel(uploaded_file)
        else:
            raise ValueError("Unsupported file type — upload a .csv or .xlsx file.")

        self.con.register("_incoming", df)
        self.con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _incoming")
        self.con.unregister("_incoming")

        self.tables[table_name] = {
            "filename": filename,
            "schema": [],
            "row_count": 0,
        }
        self._refresh_schema(table_name)
        return table_name

    def drop_table(self, table_name: str) -> None:
        """Remove a loaded table."""
        if table_name in self.tables:
            self.con.execute(f"DROP TABLE IF EXISTS {table_name}")
            del self.tables[table_name]

    # ------------------------------------------------------------------ preprocessing i/o

    def get_dataframe(self, table_name: str) -> pd.DataFrame:
        """Pull a full table into pandas for preprocessing."""
        return self.con.execute(f"SELECT * FROM {table_name}").fetchdf()

    def replace_table_data(self, table_name: str, df: pd.DataFrame) -> None:
        """
        Overwrite an existing table's contents with a transformed DataFrame
        (e.g. after cleaning/encoding via the Preprocessor) and refresh its
        cached schema/row-count metadata.
        """
        self.con.register("_incoming", df)
        self.con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _incoming")
        self.con.unregister("_incoming")
        self._refresh_schema(table_name)

    # ------------------------------------------------------------------ merging

    def merge_tables(self, sql: str, result_table: str) -> pd.DataFrame:
        """
        Execute a user-defined join/union SQL and persist the result as a new
        table so subsequent queries can reference it.
        """
        if not self.is_safe(sql):
            raise ValueError("Blocked a potentially destructive SQL statement.")

        result_table = sanitize_ident(result_table)
        self.con.execute(f"CREATE OR REPLACE TABLE {result_table} AS {sql}")
        self.tables[result_table] = {
            "filename": "(merged)",
            "schema": [],
            "row_count": 0,
        }
        self._refresh_schema(result_table)
        return self.con.execute(f"SELECT * FROM {result_table} LIMIT 100").fetchdf()

    # ------------------------------------------------------------------ schema

    def _refresh_schema(self, table_name: str) -> None:
        describe_rows = self.con.execute(f"DESCRIBE {table_name}").fetchall()
        row_count = self.con.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]

        schema = []
        for col_name, col_type, *_ in describe_rows:
            try:
                sample_row = self.con.execute(
                    f'SELECT "{col_name}" FROM {table_name} '
                    f'WHERE "{col_name}" IS NOT NULL LIMIT 1'
                ).fetchone()
                sample = sample_row[0] if sample_row else None

                null_pct = self.con.execute(
                    f'SELECT ROUND(100.0 * SUM(CASE WHEN "{col_name}" IS NULL '
                    f'THEN 1 ELSE 0 END) / COUNT(*), 1) FROM {table_name}'
                ).fetchone()[0]
            except Exception:
                sample, null_pct = None, None

            schema.append({
                "name": col_name,
                "type": col_type,
                "sample": sample,
                "null_pct": null_pct or 0.0,
            })

        self.tables[table_name]["schema"] = schema
        self.tables[table_name]["row_count"] = row_count

    def all_schemas_description(self) -> str:
        """
        Produces a block the LLM can use to understand every loaded table, e.g.:
          TABLE sales: date (DATE), amount (DOUBLE), region (VARCHAR)
          TABLE customers: id (INTEGER), name (VARCHAR), region (VARCHAR)
        """
        parts = []
        for tname, meta in self.tables.items():
            cols = ", ".join(
                f"{c['name']} ({c['type']})" for c in meta["schema"]
            )
            parts.append(f"TABLE {tname}: {cols}")
        return "\n".join(parts)

    def table_names(self) -> list[str]:
        return list(self.tables.keys())

    # ------------------------------------------------------------------ query

    def is_safe(self, sql: str) -> bool:
        return not self.DESTRUCTIVE_SQL.search(sql)

    def run_query(self, sql: str) -> pd.DataFrame:
        if not self.is_safe(sql):
            raise ValueError("Blocked a potentially destructive or unsafe query.")
        return self.con.execute(sql).fetchdf()
