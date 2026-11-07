"""
Datapi Vectorized Analytics Module.
Provides turnkey DuckDB analytics endpoint code generation and SQL synthesis
with high-speed aggregation (COUNT, AVG, MIN, MAX, SUM for numeric fields,
grouped by categorical/enum fields) and automatic fallback to SQLite window functions.
"""

import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union
from datapi.infer import FieldDef, SchemaDef

try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    duckdb = None
    DUCKDB_AVAILABLE = False


def _get_numeric_fields(schema: SchemaDef) -> List[FieldDef]:
    """Finds numeric columns suitable for vectorized aggregation."""
    candidates = [
        f for f in schema.fields
        if f.python_type in ("int", "float") and not f.is_primary_key
    ]
    pure_metrics = [
        f for f in candidates
        if not f.name.lower().endswith("_id")
        and not f.name.lower().endswith("id")
        and not any(fk.field_name == f.name for fk in schema.foreign_keys)
    ]
    if pure_metrics:
        return pure_metrics
    if candidates:
        return candidates
    return [f for f in schema.fields if f.python_type in ("int", "float")]


def _get_categorical_fields(schema: SchemaDef) -> List[FieldDef]:
    """Finds categorical and enum columns suitable for GROUP BY."""
    return [
        f for f in schema.fields
        if f.enum_values is not None
        or (f.python_type == "str" and not f.openapi_format in ("uuid", "email"))
        or f.is_filter_candidate
    ]


def _get_date_fields(schema: SchemaDef) -> List[FieldDef]:
    """Finds date/datetime columns suitable for timeseries bucketing."""
    return [
        f for f in schema.fields
        if f.python_type in ("date", "datetime")
        or f.openapi_format in ("date", "date-time")
        or any(k in f.name.lower() for k in ("date", "time", "created", "updated", "timestamp"))
    ]


def synthesize_summary_sql(
    schema: SchemaDef,
    group_by: Optional[str] = None,
    table_name: str = "records",
) -> str:
    """
    Synthesizes vectorized summary SQL query (COUNT, AVG, MIN, MAX, SUM).
    Works interchangeably in DuckDB and SQLite.
    """
    numeric_fields = _get_numeric_fields(schema)
    aggs = ["COUNT(*) AS total_count"]
    for f in numeric_fields:
        aggs.append(f'AVG("{f.name}") AS avg_{f.name}')
        aggs.append(f'MIN("{f.name}") AS min_{f.name}')
        aggs.append(f'MAX("{f.name}") AS max_{f.name}')
        aggs.append(f'SUM("{f.name}") AS sum_{f.name}')

    agg_clause = ",\n    ".join(aggs)

    if group_by:
        return (
            f'SELECT\n    "{group_by}",\n    {agg_clause}\n'
            f'FROM {table_name}\n'
            f'GROUP BY "{group_by}"\n'
            f'ORDER BY total_count DESC'
        )
    return f'SELECT\n    {agg_clause}\nFROM {table_name}'


def synthesize_timeseries_sql(
    schema: SchemaDef,
    date_field: Optional[str] = None,
    metric_field: Optional[str] = None,
    interval: str = "day",
    engine: str = "duckdb",
    table_name: str = "records",
) -> str:
    """
    Synthesizes vectorized timeseries SQL with time bucketing and window functions.
    Supports 'duckdb' and 'sqlite' engines.
    """
    date_cols = _get_date_fields(schema)
    date_col = date_field or (date_cols[0].name if date_cols else (schema.primary_key or "id"))

    numeric_cols = _get_numeric_fields(schema)
    metric_col = metric_field or (numeric_cols[0].name if numeric_cols else None)

    # Time bucket expression per engine
    if engine == "duckdb":
        if interval == "month":
            time_expr = f'strftime(TRY_CAST("{date_col}" AS TIMESTAMP), \'%Y-%m\')'
        elif interval == "year":
            time_expr = f'strftime(TRY_CAST("{date_col}" AS TIMESTAMP), \'%Y\')'
        else:
            time_expr = f'strftime(TRY_CAST("{date_col}" AS TIMESTAMP), \'%Y-%m-%d\')'
    else:  # sqlite fallback
        if interval == "month":
            time_expr = f'strftime(\'%Y-%m\', "{date_col}")'
        elif interval == "year":
            time_expr = f'strftime(\'%Y\', "{date_col}")'
        else:
            time_expr = f'strftime(\'%Y-%m-%d\', "{date_col}")'

    metric_cte = ""
    window_select = "SUM(count) OVER (ORDER BY period) AS cumulative_count"
    if metric_col:
        metric_cte = f',\n        SUM("{metric_col}") AS sum_metric,\n        AVG("{metric_col}") AS avg_metric'
        window_select += (
            f',\n    sum_metric,\n    avg_metric,\n'
            f'    ROUND(AVG(avg_metric) OVER (ORDER BY period ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS moving_avg_7d'
        )

    sql = f"""WITH aggregated AS (
    SELECT
        {time_expr} AS period,
        COUNT(*) AS count{metric_cte}
    FROM {table_name}
    WHERE "{date_col}" IS NOT NULL
    GROUP BY period
)
SELECT
    period,
    count,
    {window_select}
FROM aggregated
ORDER BY period ASC"""
    return sql.strip()


class DuckDBAnalyticsEngine:
    """
    Turnkey vectorized analytics execution engine over in-memory datasets.
    Uses DuckDB when available, otherwise falls back to SQLite window functions.
    """

    def __init__(self, records: List[Dict[str, Any]], schema: Optional[SchemaDef] = None):
        self.records = records
        self.schema = schema

    def execute_query(
        self,
        sql_duckdb: str,
        sql_sqlite: str,
    ) -> Tuple[List[Dict[str, Any]], str]:
        if not self.records:
            return [], "none"

        if DUCKDB_AVAILABLE:
            try:
                con = duckdb.connect(":memory:")
                rows = self.records
                con.execute("CREATE TABLE records AS SELECT * FROM rows")
                res = con.execute(sql_duckdb).fetchall()
                cols = [d[0] for d in con.description]
                return [dict(zip(cols, row)) for row in res], "duckdb"
            except Exception:
                pass

        # Fallback to SQLite with window function support
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        keys = list(self.records[0].keys())
        cols = ", ".join(f'"{k}"' for k in keys)
        placeholders = ", ".join("?" for _ in keys)
        cur.execute(f"CREATE TABLE records ({cols})")
        cur.executemany(
            f"INSERT INTO records VALUES ({placeholders})",
            [[r.get(k) for k in keys] for r in self.records],
        )
        cur.execute(sql_sqlite)
        results = [dict(r) for r in cur.fetchall()]
        conn.close()
        return results, "sqlite"

    def summary(self, group_by: Optional[str] = None) -> Dict[str, Any]:
        if not self.schema:
            raise ValueError("Schema is required for summary aggregation")
        sql = synthesize_summary_sql(self.schema, group_by=group_by, table_name="records")
        results, engine = self.execute_query(sql, sql)
        return {
            "resource": self.schema.plural_name,
            "group_by": group_by,
            "metrics": results,
            "engine": engine,
        }

    def timeseries(
        self,
        date_field: Optional[str] = None,
        metric_field: Optional[str] = None,
        interval: str = "day",
    ) -> Dict[str, Any]:
        if not self.schema:
            raise ValueError("Schema is required for timeseries aggregation")
        duckdb_sql = synthesize_timeseries_sql(
            self.schema, date_field=date_field, metric_field=metric_field, interval=interval, engine="duckdb"
        )
        sqlite_sql = synthesize_timeseries_sql(
            self.schema, date_field=date_field, metric_field=metric_field, interval=interval, engine="sqlite"
        )
        results, engine = self.execute_query(duckdb_sql, sqlite_sql)
        return {
            "resource": self.schema.plural_name,
            "date_field": date_field,
            "interval": interval,
            "metric": metric_field,
            "timeseries": results,
            "engine": engine,
        }


def generate_duckdb_analytics_code(schema: SchemaDef, app_variable: str = "app") -> str:
    """
    Emits turnkey FastAPI route code for:
      - GET /{plural}/analytics/summary
      - GET /{plural}/analytics/timeseries
    Executes vectorized aggregation (COUNT, AVG, MIN, MAX, SUM) grouped by categorical/enum fields.
    Uses DuckDB in-memory engine when installed, with fallback to SQLite window functions.
    """
    plural = schema.plural_name
    numeric_fields = [f.name for f in _get_numeric_fields(schema)]
    cat_fields = [f.name for f in _get_categorical_fields(schema)]
    date_fields = [f.name for f in _get_date_fields(schema)]
    default_date_field = date_fields[0] if date_fields else (schema.primary_key or "id")
    default_metric_field = numeric_fields[0] if numeric_fields else ""

    code = f'''# --- Turnkey DuckDB Vectorized Analytics Endpoints for {plural} ---

try:
    import duckdb as _duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    _duckdb = None
    _DUCKDB_AVAILABLE = False

import sqlite3 as _sqlite3
from typing import Any, Dict, List, Optional, Tuple
from fastapi import Query, HTTPException, status


def _execute_analytics_query(
    sql_duckdb: str,
    sql_sqlite: str,
    records: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], str]:
    if not records:
        return [], "none"

    if _DUCKDB_AVAILABLE:
        try:
            con = _duckdb.connect(":memory:")
            rows = records
            con.execute("CREATE TABLE records AS SELECT * FROM rows")
            res = con.execute(sql_duckdb).fetchall()
            cols = [d[0] for d in con.description]
            return [dict(zip(cols, row)) for row in res], "duckdb"
        except Exception:
            pass

    conn = _sqlite3.connect(":memory:")
    conn.row_factory = _sqlite3.Row
    cur = conn.cursor()
    keys = list(records[0].keys())
    cols = ", ".join(f\'"{{k}}"\' for k in keys)
    placeholders = ", ".join("?" for _ in keys)
    cur.execute(f"CREATE TABLE records ({{cols}})")
    cur.executemany(
        f"INSERT INTO records VALUES ({{placeholders}})",
        [[r.get(k) for k in keys] for r in records],
    )
    cur.execute(sql_sqlite)
    results = [dict(r) for r in cur.fetchall()]
    conn.close()
    return results, "sqlite"


@{app_variable}.get(
    "/{plural}/analytics/summary",
    tags=["Analytics"],
    summary="Vectorized summary analytics for {plural}",
)
def get_{plural}_analytics_summary(
    group_by: Optional[str] = Query(None, description="Categorical or enum field to group by"),
):
    rows = list(db.values()) if "db" in globals() else []
    if not rows:
        return {{"resource": "{plural}", "total": 0, "metrics": [], "engine": "none"}}

    valid_group_fields = {repr(cat_fields)}
    all_fields = {repr([f.name for f in schema.fields])}
    if group_by and group_by not in valid_group_fields and group_by not in all_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid group_by field: {{group_by}}. Allowed fields: {{valid_group_fields}}",
        )

    numeric_cols = {repr(numeric_fields)}
    aggs = ["COUNT(*) AS total_count"]
    for num_col in numeric_cols:
        aggs.append(f\'AVG("{{num_col}}") AS avg_{{num_col}}\')
        aggs.append(f\'MIN("{{num_col}}") AS min_{{num_col}}\')
        aggs.append(f\'MAX("{{num_col}}") AS max_{{num_col}}\')
        aggs.append(f\'SUM("{{num_col}}") AS sum_{{num_col}}\')

    agg_clause = ",\\n    ".join(aggs)
    if group_by:
        sql = (
            f\'SELECT\\n    "{{group_by}}",\\n    {{agg_clause}}\\n\'
            f\'FROM records\\n\'
            f\'GROUP BY "{{group_by}}"\\n\'
            f\'ORDER BY total_count DESC\'
        )
    else:
        sql = f\'SELECT\\n    {{agg_clause}}\\nFROM records\'

    results, engine = _execute_analytics_query(sql, sql, rows)
    return {{
        "resource": "{plural}",
        "group_by": group_by,
        "metrics": results,
        "engine": engine,
    }}


@{app_variable}.get(
    "/{plural}/analytics/timeseries",
    tags=["Analytics"],
    summary="Vectorized timeseries analytics for {plural}",
)
def get_{plural}_analytics_timeseries(
    date_field: Optional[str] = Query(None, description="Date or datetime column to bucket by"),
    interval: str = Query("day", description="Time bucket interval (day, month, year)"),
    metric: Optional[str] = Query(None, description="Numeric metric column to aggregate"),
):
    rows = list(db.values()) if "db" in globals() else []
    if not rows:
        return {{"resource": "{plural}", "total": 0, "timeseries": [], "engine": "none"}}

    date_col = date_field or "{default_date_field}"
    metric_col = metric or ("{default_metric_field}" if "{default_metric_field}" else None)

    if interval == "month":
        duck_time = f\'strftime(TRY_CAST("{{date_col}}" AS TIMESTAMP), "%Y-%m")\'
        sqlite_time = f\'strftime("%Y-%m", "{{date_col}}")\'
    elif interval == "year":
        duck_time = f\'strftime(TRY_CAST("{{date_col}}" AS TIMESTAMP), "%Y")\'
        sqlite_time = f\'strftime("%Y", "{{date_col}}")\'
    else:
        duck_time = f\'strftime(TRY_CAST("{{date_col}}" AS TIMESTAMP), "%Y-%m-%d")\'
        sqlite_time = f\'strftime("%Y-%m-%d", "{{date_col}}")\'

    metric_cte = ""
    window_select = "SUM(count) OVER (ORDER BY period) AS cumulative_count"
    if metric_col:
        metric_cte = f\',\\n        SUM("{{metric_col}}") AS sum_metric,\\n        AVG("{{metric_col}}") AS avg_metric\'
        window_select += (
            f\',\\n    sum_metric,\\n    avg_metric,\\n\'
            f\'    ROUND(AVG(avg_metric) OVER (ORDER BY period ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS moving_avg_7d\'
        )

    duckdb_sql = f"""WITH aggregated AS (
    SELECT
        {{duck_time}} AS period,
        COUNT(*) AS count{{metric_cte}}
    FROM records
    WHERE "{{date_col}}" IS NOT NULL
    GROUP BY period
)
SELECT
    period,
    count,
    {{window_select}}
FROM aggregated
ORDER BY period ASC"""

    sqlite_sql = f"""WITH aggregated AS (
    SELECT
        {{sqlite_time}} AS period,
        COUNT(*) AS count{{metric_cte}}
    FROM records
    WHERE "{{date_col}}" IS NOT NULL
    GROUP BY period
)
SELECT
    period,
    count,
    {{window_select}}
FROM aggregated
ORDER BY period ASC"""

    results, engine = _execute_analytics_query(duckdb_sql, sqlite_sql, rows)
    return {{
        "resource": "{plural}",
        "date_field": date_col,
        "interval": interval,
        "metric": metric_col,
        "timeseries": results,
        "engine": engine,
    }}
'''
    return code.strip()


# Aliases for convenience
generate_analytics_routes = generate_duckdb_analytics_code
generate_analytics_endpoints = generate_duckdb_analytics_code
