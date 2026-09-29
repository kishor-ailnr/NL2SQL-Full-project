"""
app/services/chart_advisor.py
-----------------------------
Intelligent chart advisor that analyzes query results and SQL structure
to suggest the most effective visualization type ('bar', 'pie', 'line', or 'none').
"""

import re
from typing import Any, Dict, List, Optional


CHART_INTENT_PATTERN = re.compile(
    r"\b(?:chart|charts|chartu|chartil|chartla|graph|graphs|graphla|plot|plots|plotu|"
    r"visualize|visualise|visualization|visualisation|trend|diagram|histogram|"
    r"pie\s*chart|bar\s*chart|line\s*chart|varaipadam)\b",
    re.IGNORECASE,
)


def advise_chart_type(
    result_rows: List[Dict[str, Any]],
    sql: Optional[str] = None,
    user_query: Optional[str] = None,
) -> str:
    """Analyze query rows and SQL statement to suggest an appropriate chart type.

    Rule: Charts are ONLY suggested when the user explicitly asks for a chart/graph/plot
    in their natural language request (or if user_query is omitted in legacy tests).
    Otherwise, returns 'none' so clean tabular data is displayed.
    """
    if not result_rows or not isinstance(result_rows, list) or len(result_rows) == 0:
        return "none"

    # If user_query is provided, only return a chart type if chart was explicitly requested
    if user_query is not None:
        if not CHART_INTENT_PATTERN.search(user_query):
            return "none"

    first_row = result_rows[0]
    if not isinstance(first_row, dict):
        return "none"

    cols = list(first_row.keys())
    num_cols = len(cols)
    num_rows = len(result_rows)

    # 1. Single scalar value (e.g. COUNT(*), AVG(age)) -> no chart
    if num_rows == 1 and num_cols == 1:
        return "none"

    # 2. Single entity detail lookup (e.g. SELECT * FROM patients WHERE name = '...') -> no chart
    if num_rows == 1 and num_cols > 2:
        return "none"

    # 3. Categorize column types across rows
    numeric_cols = []
    text_cols = []
    date_cols = []

    date_keywords = {"date", "day", "month", "year", "time", "week", "period"}

    for col in cols:
        col_lower = col.lower()
        # Check if column name suggests date/time
        is_date_name = any(dk in col_lower for dk in date_keywords)

        # Check sample value types
        val = first_row[col]
        if isinstance(val, (int, float)) and not (isinstance(val, bool)):
            numeric_cols.append(col)
        elif is_date_name:
            date_cols.append(col)
        elif isinstance(val, str):
            # Check if string matches date format YYYY-MM-DD
            if re.match(r"^\d{4}-\d{2}-\d{2}", val.strip()):
                date_cols.append(col)
            else:
                text_cols.append(col)
        else:
            text_cols.append(col)

    # 4. Check for temporal trend -> 'line' or 'bar'
    if date_cols and numeric_cols:
        return "line"

    # 5. Check for categorical distribution (e.g. gender, status, category with count/sum)
    if text_cols and numeric_cols:
        # If very few categories (e.g. gender with Male/Female, status with 2-4 values), prefer bar or pie
        if num_rows <= 5:
            # Check if gender or status
            first_text_col = text_cols[0].lower()
            if "gender" in first_text_col or "status" in first_text_col:
                return "bar"
            return "bar"
        return "bar"

    # If query grouped by a category and counted
    if sql:
        sql_lower = sql.lower()
        if "group by" in sql_lower:
            if any(dk in sql_lower for dk in ("strftime", "date", "year", "month")):
                return "line"
            return "bar"

    return "none"
