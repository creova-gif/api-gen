"""
Datapi Vectorized Analytics Module.
Provides turnkey DuckDB analytics endpoint code generation and SQL synthesis
with high-speed aggregation (COUNT, AVG, MIN, MAX, SUM for numeric fields,
grouped by categorical/enum fields) and automatic fallback to SQLite window functions.
"""

import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union
from datapi.infer import FieldDef, SchemaDef

try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    duckdb = None
    DUCKDB_AVAILABLE = False

_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VALID_INTERVALS = ("day", "month", "year")


def _validate_identifier(name: str, context: str = "identifier") -> str:
    if not isinstance(name, str) or not _SAFE_IDENT_RE.fullmatch(name):
        raise ValueError(f"Unsafe SQL {context}: {name!r}")
    return name


def _sanitize_col_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", str(name).strip())
    if cleaned and cleaned[0].isdigit():
        cleaned = f"f_{cleaned}"
    return cleaned.lower() or "field"


def _validate_table_name(schema: SchemaDef, table_name: str) -> str:
    _validate_identifier(table_name, "table_name")
    allowed_tables = {
        "records",
        _validate_identifier(schema.plural_name, "plural_name"),
        _validate_identifier(schema.resource_name, "resource_name"),
    }
    if table_name not in allowed_tables:
        raise ValueError(f"Invalid table_name '{table_name}'. Allowed tables: {sorted(allowed_tables)}")
    return table_name


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
    _validate_table_name(schema, table_name)
    allowed_fields = {f.name for f in schema.fields}
    if group_by is not None:
        _validate_identifier(group_by, "group_by")
        if group_by not in allowed_fields:
            raise ValueError(
                f"Invalid group_by field '{group_by}'. Allowed schema fields: {sorted(allowed_fields)}"
            )

    numeric_fields = _get_numeric_fields(schema)
    aggs = ["COUNT(*) AS total_count"]
    for f in numeric_fields:
        col = _validate_identifier(f.name, "numeric_field")
        aggs.append(f'AVG("{col}") AS avg_{col}')
        aggs.append(f'MIN("{col}") AS min_{col}')
        aggs.append(f'MAX("{col}") AS max_{col}')
        aggs.append(f'SUM("{col}") AS sum_{col}')

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
    _validate_table_name(schema, table_name)
    if interval not in _VALID_INTERVALS:
        raise ValueError(f"Invalid interval '{interval}'. Allowed: {_VALID_INTERVALS}")

    allowed_fields = {f.name for f in schema.fields}
    if date_field is not None:
        _validate_identifier(date_field, "date_field")
        if date_field not in allowed_fields:
            raise ValueError(f"Invalid date_field '{date_field}'. Allowed schema fields: {sorted(allowed_fields)}")
    if metric_field is not None:
        _validate_identifier(metric_field, "metric_field")
        if metric_field not in allowed_fields:
            raise ValueError(f"Invalid metric_field '{metric_field}'. Allowed schema fields: {sorted(allowed_fields)}")

    date_cols = _get_date_fields(schema)
    date_col = _validate_identifier(
        date_field or (date_cols[0].name if date_cols else (schema.primary_key or "id")),
        "date_col",
    )

    numeric_cols = _get_numeric_fields(schema)
    raw_metric = metric_field or (numeric_cols[0].name if numeric_cols else None)
    metric_col = _validate_identifier(raw_metric, "metric_col") if raw_metric else None

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
            ',\n    sum_metric,\n    avg_metric,\n'
            '    ROUND(AVG(avg_metric) OVER (ORDER BY period ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS moving_avg_7d'
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

        normalized_records = [
            {_sanitize_col_name(k): v for k, v in r.items()}
            for r in self.records
        ]
        if self.schema is not None:
            schema_cols = [_validate_identifier(f.name, "column") for f in self.schema.fields]
            keys = schema_cols
            normalized_records = [
                {col: nr.get(col) for col in keys}
                for nr in normalized_records
            ]
        else:
            seen: List[str] = []
            for nr in normalized_records:
                for k in nr.keys():
                    valid_k = _validate_identifier(k, "column")
                    if valid_k not in seen:
                        seen.append(valid_k)
            keys = seen

        if DUCKDB_AVAILABLE:
            try:
                con = duckdb.connect(":memory:")
                rows = normalized_records  # noqa: F841 - read by DuckDB replacement scan in the SQL below
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
        cols = ", ".join(f'"{k}"' for k in keys)
        placeholders = ", ".join("?" for _ in keys)
        cur.execute(f"CREATE TABLE records ({cols})")
        cur.executemany(
            f"INSERT INTO records VALUES ({placeholders})",
            [[nr.get(k) for k in keys] for nr in normalized_records],
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


def generate_duckdb_analytics_code(schema: Union[SchemaDef, List[SchemaDef], Any], app_variable: str = "app") -> str:
    """
    Emits turnkey FastAPI route code for:
      - GET /{plural}/analytics/summary
      - GET /{plural}/analytics/timeseries
    Executes vectorized aggregation (COUNT, AVG, MIN, MAX, SUM) grouped by categorical/enum fields.
    Uses DuckDB in-memory engine when installed, with fallback to SQLite window functions.
    Supports a single SchemaDef, a list of SchemaDef objects, or an APIPlan.
    """
    auth_enabled = bool(getattr(schema, "auth_enabled", False))
    endpoint_security = ",\n    dependencies=[Depends(verify_api_key)]," if auth_enabled else ","

    if hasattr(schema, "all_schemas"):
        schemas = schema.all_schemas
    elif isinstance(schema, list):
        schemas = schema
    else:
        schemas = [schema]

    endpoints_code = []

    for s in schemas:
        plural = s.plural_name
        numeric_fields = [f.name for f in _get_numeric_fields(s)]
        cat_fields = [f.name for f in _get_categorical_fields(s)]
        date_fields = [f.name for f in _get_date_fields(s)]
        default_date_field = date_fields[0] if date_fields else (s.primary_key or "id")
        default_metric_field = numeric_fields[0] if numeric_fields else ""

        numeric_cols_repr = repr(numeric_fields)
        cat_fields_repr = repr(cat_fields)
        all_fields_repr = repr([f.name for f in s.fields])

        endpoint_block = f'''
@{app_variable}.get(
    "/{plural}/analytics/summary",
    tags=["Analytics"],
    summary="Vectorized summary analytics for {plural}"{endpoint_security}
)
def get_{plural}_analytics_summary(
    group_by: Optional[str] = Query(None, description="Categorical or enum field to group by"),
):
    valid_group_fields = {cat_fields_repr}
    all_fields = {all_fields_repr}
    if group_by and group_by not in valid_group_fields and group_by not in all_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid group_by field: {{group_by}}. Allowed fields: {{valid_group_fields}}",
        )

    target_db = globals().get("db_{plural}", globals().get("db", {{}}))
    rows = list(target_db.values())
    if not rows:
        return {{"resource": "{plural}", "total": 0, "metrics": [], "engine": "none"}}

    numeric_cols = {numeric_cols_repr}
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

    results, engine = _execute_analytics_query(sql, sql, rows, allowed_columns=all_fields)
    return {{
        "resource": "{plural}",
        "group_by": group_by,
        "metrics": results,
        "engine": engine,
    }}


@{app_variable}.get(
    "/{plural}/analytics/timeseries",
    tags=["Analytics"],
    summary="Vectorized timeseries analytics for {plural}"{endpoint_security}
)
def get_{plural}_analytics_timeseries(
    date_field: Optional[str] = Query(None, description="Date or datetime column to bucket by"),
    interval: str = Query("day", description="Time bucket interval (day, month, year)"),
    metric: Optional[str] = Query(None, description="Numeric metric column to aggregate"),
):
    all_fields = {all_fields_repr}
    numeric_cols = {numeric_cols_repr}
    if interval not in ("day", "month", "year"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid interval: {{interval}}. Allowed: day, month, year",
        )
    if date_field and date_field not in all_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date_field: {{date_field}}. Allowed fields: {{all_fields}}",
        )
    if metric and metric not in numeric_cols and metric not in all_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid metric: {{metric}}. Allowed fields: {{numeric_cols}}",
        )

    target_db = globals().get("db_{plural}", globals().get("db", {{}}))
    rows = list(target_db.values())
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

    results, engine = _execute_analytics_query(duckdb_sql, sqlite_sql, rows, allowed_columns=all_fields)
    return {{
        "resource": "{plural}",
        "date_field": date_col,
        "interval": interval,
        "metric": metric_col,
        "timeseries": results,
        "engine": engine,
    }}
'''
        endpoints_code.append(endpoint_block)

    header = '''# --- Turnkey DuckDB Vectorized Analytics Endpoints ---

try:
    import duckdb as _duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    _duckdb = None
    _DUCKDB_AVAILABLE = False

import re as _re
import sqlite3 as _sqlite3
from typing import Any, Dict, List, Optional, Tuple
from fastapi import Query, HTTPException, status

_ANALYTICS_IDENT_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _sanitize_analytics_col(name: str) -> str:
    cleaned = _re.sub(r"[^0-9a-zA-Z_]", "_", str(name).strip())
    if cleaned and cleaned[0].isdigit():
        cleaned = f"f_{cleaned}"
    return cleaned.lower() or "field"


def _execute_analytics_query(
    sql_duckdb: str,
    sql_sqlite: str,
    records: List[Dict[str, Any]],
    allowed_columns: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    if not records:
        return [], "none"

    normalized_records = [
        {_sanitize_analytics_col(k): v for k, v in r.items()}
        for r in records
    ]
    if allowed_columns:
        keys = [c for c in allowed_columns if _ANALYTICS_IDENT_RE.fullmatch(c)]
        normalized_records = [
            {col: nr.get(col) for col in keys}
            for nr in normalized_records
        ]
    else:
        keys = []
        for nr in normalized_records:
            for k in nr.keys():
                if not _ANALYTICS_IDENT_RE.fullmatch(k):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid column identifier: {k}")
                if k not in keys:
                    keys.append(k)

    if _DUCKDB_AVAILABLE:
        try:
            con = _duckdb.connect(":memory:")
            rows = normalized_records
            con.execute("CREATE TABLE records AS SELECT * FROM rows")
            res = con.execute(sql_duckdb).fetchall()
            cols = [d[0] for d in con.description]
            return [dict(zip(cols, row)) for row in res], "duckdb"
        except Exception:
            pass

    conn = _sqlite3.connect(":memory:")
    conn.row_factory = _sqlite3.Row
    cur = conn.cursor()
    cols = ", ".join(f\'"{k}"\' for k in keys)
    placeholders = ", ".join("?" for _ in keys)
    cur.execute(f"CREATE TABLE records ({cols})")
    cur.executemany(
        f"INSERT INTO records VALUES ({placeholders})",
        [[nr.get(k) for k in keys] for nr in normalized_records],
    )
    cur.execute(sql_sqlite)
    results = [dict(r) for r in cur.fetchall()]
    conn.close()
    return results, "sqlite"
'''
    return (header + "\n".join(endpoints_code)).strip()


# Aliases for convenience
generate_analytics_routes = generate_duckdb_analytics_code
generate_analytics_endpoints = generate_duckdb_analytics_code
