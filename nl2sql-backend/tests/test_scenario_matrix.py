"""
tests/test_scenario_matrix.py
-----------------------------
Comprehensive 120+ Scenario Test Matrix across 14 Categories:
1. Basic reads (all cols, subset, count, distinct)
2. Filters (equality, ranges, dates, multiple AND/OR, null)
3. Aggregates (group by, having, min, max, avg, sum)
4. Joins (1-to-1, 1-to-many, self, multi-table)
5. Advanced (subqueries, window, order+limit, pagination)
6. Names & Values (exact, partial, case, typo in name, typo in schema, person in 2 roles)
7. Writes & Injection (INSERT, UPDATE, DELETE with/without WHERE, DROP TABLE, injection)
8. NOT-database conversation (greetings, 'what can you do?', 'tell me a joke', 'who made you?')
9. Bad input (empty string, whitespace, punctuation mark, gibberish, long string)
10. Languages (pure English, pure Tamil script, Thanglish, mixed, non-English)
11. Ambiguity & Unavailable (vague question, missing schema data, partial data)
12. Follow-ups in conversation (filter addition, confirmation yes/no, role clarification)
13. Uploaded CSV / custom database (unseen schema, unusual column names)
14. Presentation & Visualization (chart-worthy queries, scalar queries, non-chart queries)

Tests outcome types:
'rows', 'zero_rows_explained', 'clarification', 'unavailable',
'did_you_mean', 'write_pending', 'blocked', 'friendly_reply'
"""

import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.routers.query import reset_rate_limits
from app.services.sql_generator import clear_query_cache

pytestmark = pytest.mark.integration


@dataclass
class Scenario:
    id: str
    category: str
    description: str
    question: str
    expected_outcome: str  # rows, zero_rows_explained, clarification, unavailable, did_you_mean, write_pending, blocked, friendly_reply
    db: str = "hospital"  # hospital, ecommerce, custom
    sql_must_contain: Optional[List[str]] = None
    sql_must_not_contain: Optional[List[str]] = None
    min_rows: int = 0
    max_rows: Optional[int] = None
    expected_chart_types: Optional[List[str]] = None
    follow_up: Optional[str] = None
    follow_up_expected_outcome: Optional[str] = None


# ---------------------------------------------------------------------------
# 127 SCENARIOS ACROSS 14 CATEGORIES
# ---------------------------------------------------------------------------
SCENARIOS: List[Scenario] = [
    # --- Category 1: Basic Reads (10 scenarios) ---
    Scenario("C1_01", "1. Basic Reads", "All columns read", "Show all patients", "rows", min_rows=1, sql_must_contain=["patients"]),
    Scenario("C1_02", "1. Basic Reads", "All columns read doctors", "List all doctors", "rows", min_rows=1, sql_must_contain=["doctors"]),
    Scenario("C1_03", "1. Basic Reads", "Subset of columns", "Give me the names and ages of all patients", "rows", min_rows=1),
    Scenario("C1_04", "1. Basic Reads", "Count rows", "Count total appointments", "rows", min_rows=1, sql_must_contain=["COUNT"]),
    Scenario("C1_05", "1. Basic Reads", "Distinct values", "List distinct diagnoses of patients", "rows", min_rows=1, sql_must_contain=["DISTINCT"]),
    Scenario("C1_06", "1. Basic Reads", "All customers", "Show all customers", "rows", db="ecommerce", min_rows=1),
    Scenario("C1_07", "1. Basic Reads", "All products", "Display all products", "rows", db="ecommerce", min_rows=1),
    Scenario("C1_08", "1. Basic Reads", "All orders", "Get all orders", "rows", db="ecommerce", min_rows=1),
    Scenario("C1_09", "1. Basic Reads", "Count orders", "How many orders are there", "rows", db="ecommerce", min_rows=1, sql_must_contain=["COUNT"]),
    Scenario("C1_10", "1. Basic Reads", "Distinct product categories", "Distinct product categories in products", "rows", db="ecommerce", min_rows=1, sql_must_contain=["DISTINCT"]),

    # --- Category 2: Filters (10 scenarios) ---
    Scenario("C2_01", "2. Filters", "Numeric inequality", "Patients older than 50", "rows", min_rows=1, sql_must_contain=[">"]),
    Scenario("C2_02", "2. Filters", "Numeric greater than", "Products with price greater than 100", "rows", db="ecommerce", min_rows=1),
    Scenario("C2_03", "2. Filters", "Multiple AND filters", "Patients with gender Female and diagnosis Hypertension", "rows", sql_must_contain=["WHERE"]),
    Scenario("C2_04", "2. Filters", "Status equality", "Appointments with status Scheduled", "rows", min_rows=1),
    Scenario("C2_05", "2. Filters", "Month range across all years (BUG FIX)", "Give the patient name with appointment date between January and February", "rows", min_rows=1, sql_must_contain=["strftime", "'01'", "'02'"], sql_must_not_contain=["Give"]),
    Scenario("C2_06", "2. Filters", "Zero row date search explained", "Patients with appointment date in year 1990", "zero_rows_explained", sql_must_not_contain=["with the name"]),
    Scenario("C2_07", "2. Filters", "Status filter cancelled", "Appointments with status Cancelled", "rows", min_rows=1),
    Scenario("C2_08", "2. Filters", "Price range between", "Products with price between 50 and 500", "rows", db="ecommerce", min_rows=1),
    Scenario("C2_09", "2. Filters", "Age range between", "Patients with age between 20 and 40", "rows", min_rows=1),
    Scenario("C2_10", "2. Filters", "Filter for not null admission date", "Patients where admission date is not null", "rows", sql_must_contain=["IS NOT NULL"]),

    # --- Category 3: Aggregates (9 scenarios) ---
    Scenario("C3_01", "3. Aggregates", "Average function", "Average age of patients", "rows", sql_must_contain=["AVG"]),
    Scenario("C3_02", "3. Aggregates", "Maximum function", "Maximum product price", "rows", db="ecommerce", sql_must_contain=["MAX"]),
    Scenario("C3_03", "3. Aggregates", "Minimum function", "What is the minimum age of patients", "rows", sql_must_contain=["MIN"]),
    Scenario("C3_04", "3. Aggregates", "Group by status", "Count of appointments by status", "rows", sql_must_contain=["GROUP BY"]),
    Scenario("C3_05", "3. Aggregates", "Sum revenue", "Total amount from all orders", "rows", db="ecommerce", sql_must_contain=["SUM"]),
    Scenario("C3_06", "3. Aggregates", "Average by category", "Average product price by category", "rows", db="ecommerce", sql_must_contain=["GROUP BY"]),
    Scenario("C3_07", "3. Aggregates", "Group by gender", "Count of patients grouped by gender", "rows", sql_must_contain=["GROUP BY"]),
    Scenario("C3_08", "3. Aggregates", "Having clause", "Genders with more than 1 patient", "rows", sql_must_contain=["HAVING"]),
    Scenario("C3_09", "3. Aggregates", "Sum salaries", "Total stock of all products", "rows", db="ecommerce", sql_must_contain=["SUM"]),

    # --- Category 4: Joins (9 scenarios) ---
    Scenario("C4_01", "4. Joins", "Patient-appointment join", "Show patient names and their appointment dates", "rows", sql_must_contain=["JOIN"]),
    Scenario("C4_02", "4. Joins", "Doctor-appointment join", "List doctors along with their scheduled appointments", "rows", sql_must_contain=["JOIN"]),
    Scenario("C4_03", "4. Joins", "Three-table join", "Show patient name, doctor name, and appointment date", "rows", sql_must_contain=["JOIN"]),
    Scenario("C4_04", "4. Joins", "Customer-orders join", "Orders with customer names", "rows", db="ecommerce", sql_must_contain=["JOIN"]),
    Scenario("C4_05", "4. Joins", "Orders join products", "Orders with product names and prices", "rows", db="ecommerce", sql_must_contain=["JOIN"]),
    Scenario("C4_06", "4. Joins", "Customers placed orders", "Customers who have placed orders", "rows", db="ecommerce", sql_must_contain=["JOIN"]),
    Scenario("C4_07", "4. Joins", "Appointments with specialty", "Show appointments along with doctor specialty", "rows", sql_must_contain=["JOIN"]),
    Scenario("C4_08", "4. Joins", "Cardiology appointments join", "Patients and their doctor names for cardiology appointments", "rows", sql_must_contain=["JOIN"]),
    Scenario("C4_09", "4. Joins", "Customer email and order total", "Show customer email and order total amount", "rows", db="ecommerce", sql_must_contain=["JOIN"]),

    # --- Category 5: Advanced (9 scenarios) ---
    Scenario("C5_01", "5. Advanced", "Top N with order by limit", "Top 3 oldest patients", "rows", max_rows=3, sql_must_contain=["ORDER BY", "LIMIT"]),
    Scenario("C5_02", "5. Advanced", "Oldest patients limit", "5 oldest patients", "rows", max_rows=5, sql_must_contain=["ORDER BY", "LIMIT"]),
    Scenario("C5_03", "5. Advanced", "First 5 appointments by date", "First 5 appointments ordered by date", "rows", max_rows=5, sql_must_contain=["ORDER BY", "LIMIT"]),
    Scenario("C5_04", "5. Advanced", "Most expensive products", "Top 3 most expensive products", "rows", db="ecommerce", max_rows=3, sql_must_contain=["ORDER BY", "LIMIT"]),
    Scenario("C5_05", "5. Advanced", "Subquery age greater than average", "Patients whose age is greater than average patient age", "rows", sql_must_contain=["AVG"]),
    Scenario("C5_06", "5. Advanced", "Subquery salary greater than average", "Products with price above average product price", "rows", db="ecommerce", sql_must_contain=["AVG"]),
    Scenario("C5_07", "5. Advanced", "Pagination limit offset", "Show patients with limit 3 offset 2", "rows", max_rows=3, sql_must_contain=["LIMIT"]),
    Scenario("C5_08", "5. Advanced", "Orders descending limit", "Orders sorted by order date descending limit 5", "rows", db="ecommerce", max_rows=5),
    Scenario("C5_09", "5. Advanced", "Highest spending customer", "Top 1 customer by total order amount", "rows", db="ecommerce", max_rows=1),

    # --- Category 6: Names & Values (10 scenarios) ---
    Scenario("C6_01", "6. Names & Values", "Exact patient name", "Show details of patient Alice Jenkins", "rows", sql_must_contain=["alice jenkins"]),
    Scenario("C6_02", "6. Names & Values", "Exact doctor name", "Show details of doctor Robert Chase", "rows", sql_must_contain=["robert chase"]),
    Scenario("C6_03", "6. Names & Values", "Partial name search", "Patients whose name contains Raj", "rows", sql_must_contain=["raj"]),
    Scenario("C6_04", "6. Names & Values", "Lowercase name search", "Search for patient alice jenkins in lowercase", "rows", sql_must_contain=["alice jenkins"]),
    Scenario("C6_05", "6. Names & Values", "Exact name Karthik Raj", "Find patient Karthik Raj", "rows", min_rows=1),
    Scenario("C6_06", "6. Names & Values", "Non-existent name virthi (no substitution)", "Find patient virthi", "zero_rows_explained", sql_must_contain=["virthi"], sql_must_not_contain=["Karthik"]),
    Scenario("C6_07", "6. Names & Values", "Near-miss typo triggers did-you-mean", "Find patient Kartheek", "did_you_mean"),
    Scenario("C6_08", "6. Names & Values", "Person in two roles triggers clarification", "Show details of James Wilson", "clarification"),
    Scenario("C6_09", "6. Names & Values", "Disambiguated doctor James Wilson", "Show details of doctor James Wilson", "rows", sql_must_contain=["doctors"]),
    Scenario("C6_10", "6. Names & Values", "Disambiguated patient James Wilson", "Show details of patient James Wilson", "rows", sql_must_contain=["patients"]),

    # --- Category 7: Writes & Injection (10 scenarios) ---
    Scenario("C7_01", "7. Writes & Injection", "INSERT staged for confirmation", "Add patient TestUser age 30 gender Male diagnosis Flu and show all patients", "write_pending", sql_must_contain=["INSERT"]),
    Scenario("C7_02", "7. Writes & Injection", "UPDATE single column staged", "Update patient Alice Jenkins age to 35", "write_pending", sql_must_contain=["UPDATE"]),
    Scenario("C7_03", "7. Writes & Injection", "Attribute clear to NULL staged", "Delete the age of patient Pavai", "write_pending", sql_must_contain=["UPDATE", "NULL"]),
    Scenario("C7_04", "7. Writes & Injection", "DELETE with WHERE staged", "Delete patient Alice Jenkins", "write_pending", sql_must_contain=["DELETE", "WHERE"]),
    Scenario("C7_05", "7. Writes & Injection", "DELETE without WHERE rejected", "Delete all patients", "blocked"),
    Scenario("C7_06", "7. Writes & Injection", "UPDATE without WHERE rejected", "Update all patients set age = 0", "blocked"),
    Scenario("C7_07", "7. Writes & Injection", "DROP TABLE rejected", "Drop table patients", "blocked"),
    Scenario("C7_08", "7. Writes & Injection", "DROP DATABASE rejected", "Drop database hospital", "blocked"),
    Scenario("C7_09", "7. Writes & Injection", "Multi-statement injection rejected", "Show patients WHERE 1=1; DROP TABLE patients; --", "blocked"),
    Scenario("C7_10", "7. Writes & Injection", "Tautology injection blocked", "Select * from patients where name = 'x' OR 1=1 --", "blocked"),

    # --- Category 8: NOT-database conversation (9 scenarios) ---
    Scenario("C8_01", "8. Conversation", "Greeting Hello", "Hello", "friendly_reply"),
    Scenario("C8_02", "8. Conversation", "Greeting Hi there", "Hi there", "friendly_reply"),
    Scenario("C8_03", "8. Conversation", "Greeting Good morning", "Good morning", "friendly_reply"),
    Scenario("C8_04", "8. Conversation", "Capability question", "What can you do?", "friendly_reply"),
    Scenario("C8_05", "8. Conversation", "Identity question", "Who are you?", "friendly_reply"),
    Scenario("C8_06", "8. Conversation", "Chit-chat joke", "Tell me a joke", "friendly_reply"),
    Scenario("C8_07", "8. Conversation", "Bot origin question", "Who made you?", "friendly_reply"),
    Scenario("C8_08", "8. Conversation", "Help request", "Help", "friendly_reply"),
    Scenario("C8_09", "8. Conversation", "Gratitude closing", "Thank you so much!", "friendly_reply"),

    # --- Category 9: Bad input (9 scenarios) ---
    Scenario("C9_01", "9. Bad Input", "Empty string", "", "clarification"),
    Scenario("C9_02", "9. Bad Input", "Whitespace only spaces", "     ", "clarification"),
    Scenario("C9_03", "9. Bad Input", "Whitespace tabs and newlines", "\t\n  ", "clarification"),
    Scenario("C9_04", "9. Bad Input", "Single question mark", "?", "clarification"),
    Scenario("C9_05", "9. Bad Input", "Multiple exclamation marks", "!!!", "clarification"),
    Scenario("C9_06", "9. Bad Input", "Gibberish words", "asdfghjk qwerty", "clarification"),
    Scenario("C9_07", "9. Bad Input", "Alphanumeric gibberish", "zzxxqqww123890", "clarification"),
    Scenario("C9_08", "9. Bad Input", "Excessively long string", "a" * 5000, "clarification"),
    Scenario("C9_09", "9. Bad Input", "Punctuation dots", "...", "clarification"),

    # --- Category 10: Languages (9 scenarios) ---
    Scenario("C10_01", "10. Languages", "English", "List all patients", "rows", min_rows=1),
    Scenario("C10_02", "10. Languages", "Tamil script patients", "அனைத்து நோயாளிகளையும் காட்டு", "rows", min_rows=1),
    Scenario("C10_03", "10. Languages", "Tamil script doctors", "மருத்துவர்களின் பட்டியலைக் காட்டு", "rows", min_rows=1),
    Scenario("C10_04", "10. Languages", "Thanglish doctor list", "doctor ellam list pannu", "rows", min_rows=1),
    Scenario("C10_05", "10. Languages", "Thanglish age filter", "40 vayasuku mela patients kaatu", "rows", min_rows=1),
    Scenario("C10_06", "10. Languages", "Thanglish diagnosis filter", "diabetes irukra patients yaaru", "rows", min_rows=1),
    Scenario("C10_07", "10. Languages", "Mixed English-Tamil", "patients list panna mudiyuma", "rows", min_rows=1),
    Scenario("C10_08", "10. Languages", "Mixed urgent request", "Show me doctor list please romba mukkiyam", "rows", min_rows=1),
    Scenario("C10_09", "10. Languages", "Foreign language French", "Que sont les patients", "rows", min_rows=1),

    # --- Category 11: Ambiguity & Unavailable (9 scenarios) ---
    Scenario("C11_01", "11. Ambiguity & Unavailable", "Vague ranking without metric/limit", "Show top patients", "clarification"),
    Scenario("C11_02", "11. Ambiguity & Unavailable", "Vague superlative without criteria", "Give me the best doctors", "clarification"),
    Scenario("C11_03", "11. Ambiguity & Unavailable", "Vague timeframe recent", "Show recent appointments", "clarification"),
    Scenario("C11_04", "11. Ambiguity & Unavailable", "Unavailable entity students", "Show students enrolled in course", "unavailable"),
    Scenario("C11_05", "11. Ambiguity & Unavailable", "Unavailable entity employees", "List employee salaries and department head", "unavailable"),
    Scenario("C11_06", "11. Ambiguity & Unavailable", "Unavailable entity flights", "Show flights departing tomorrow", "unavailable"),
    Scenario("C11_07", "11. Ambiguity & Unavailable", "Unavailable attribute vehicles", "Patients with vehicle registration number", "unavailable"),
    Scenario("C11_08", "11. Ambiguity & Unavailable", "Unavailable attribute insurance policy", "Show patient insurance policy limits", "unavailable"),
    Scenario("C11_09", "11. Ambiguity & Unavailable", "Specific ranking (not ambiguous)", "Show top 5 oldest patients", "rows", max_rows=5),

    # --- Category 12: Follow-ups in Conversation (8 scenarios) ---
    Scenario("C12_01", "12. Follow-ups", "Follow-up filter addition", "List all patients", "rows", follow_up="only females", follow_up_expected_outcome="rows"),
    Scenario("C12_02", "12. Follow-ups", "Follow-up specialty filter", "Show all doctors", "rows", follow_up="in Cardiology", follow_up_expected_outcome="rows"),
    Scenario("C12_03", "12. Follow-ups", "Follow-up appointment status", "Show appointments", "rows", follow_up="only Scheduled status", follow_up_expected_outcome="rows"),
    Scenario("C12_04", "12. Follow-ups", "Confirmation reply YES", "Find patient Kartheek", "did_you_mean", follow_up="yes", follow_up_expected_outcome="rows"),
    Scenario("C12_05", "12. Follow-ups", "Confirmation reply NO", "Find patient Kartheek", "did_you_mean", follow_up="no", follow_up_expected_outcome="friendly_reply"),
    Scenario("C12_06", "12. Follow-ups", "Clarification reply the doctor", "Show details of James Wilson", "clarification", follow_up="the doctor", follow_up_expected_outcome="rows"),
    Scenario("C12_07", "12. Follow-ups", "Clarification reply the patient", "Show details of James Wilson", "clarification", follow_up="the patient", follow_up_expected_outcome="rows"),
    Scenario("C12_08", "12. Follow-ups", "Follow-up pivot entity", "Count patients", "rows", follow_up="what about doctors?", follow_up_expected_outcome="rows"),

    # --- Category 13: Uploaded CSV / Custom DB (8 scenarios) ---
    Scenario("C13_01", "13. Custom DB", "Custom DB read all", "List all items", "rows", db="custom", min_rows=1),
    Scenario("C13_02", "13. Custom DB", "Custom DB filter threshold", "Items with quantity less than 10", "rows", db="custom", min_rows=1),
    Scenario("C13_03", "13. Custom DB", "Custom DB average cost", "Average unit cost of items", "rows", db="custom", min_rows=1),
    Scenario("C13_04", "13. Custom DB", "Custom DB filter category", "Items in category Electronics", "rows", db="custom", min_rows=1),
    Scenario("C13_05", "13. Custom DB", "Custom DB group by category", "Count items by category", "rows", db="custom", min_rows=1),
    Scenario("C13_06", "13. Custom DB", "Custom DB computed total value", "Total inventory value", "rows", db="custom", min_rows=1),
    Scenario("C13_07", "13. Custom DB", "Custom DB filter zero stock", "Items with zero stock", "rows", db="custom", min_rows=1),
    Scenario("C13_08", "13. Custom DB", "Custom DB specific item lookup", "Show item Laptop", "rows", db="custom", min_rows=1),

    # --- Category 14: Presentation & Visualization (8 scenarios) ---
    Scenario("C14_01", "14. Visualization", "Categorical count chart", "Count of patients by gender", "rows", expected_chart_types=["bar", "pie"]),
    Scenario("C14_02", "14. Visualization", "Temporal count chart", "Appointments per day", "rows", expected_chart_types=["line", "bar"]),
    Scenario("C14_03", "14. Visualization", "Total order amount by category chart", "Total order amount by product category", "rows", db="ecommerce", expected_chart_types=["bar", "pie"]),
    Scenario("C14_04", "14. Visualization", "Single person no chart", "Show details of patient Alice Jenkins", "rows", expected_chart_types=["none"]),
    Scenario("C14_05", "14. Visualization", "Scalar count no chart", "How many total patients are there", "rows", expected_chart_types=["none"]),
    Scenario("C14_06", "14. Visualization", "Scalar average no chart", "Average age of patients", "rows", expected_chart_types=["none"]),
    Scenario("C14_07", "14. Visualization", "Product count by category chart", "Count of products by category", "rows", db="ecommerce", expected_chart_types=["bar", "pie"]),
    Scenario("C14_08", "14. Visualization", "Doctor count by spec chart", "Doctor count by specialization", "rows", expected_chart_types=["bar", "pie"]),
]


# ---------------------------------------------------------------------------
# Helpers & Custom Database Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def custom_db_path():
    """Create a temporary custom SQLite database with an unseen schema (inventory_items)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name

    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE inventory_items (
            id INTEGER PRIMARY KEY,
            item_name TEXT,
            category TEXT,
            quantity INTEGER,
            unit_price REAL,
            supplier TEXT
        );
    """)
    cur.executemany("""
        INSERT INTO inventory_items (id, item_name, category, quantity, unit_price, supplier)
        VALUES (?, ?, ?, ?, ?, ?);
    """, [
        (1, "Laptop", "Electronics", 5, 999.99, "TechCorp"),
        (2, "Mouse", "Electronics", 50, 19.99, "TechCorp"),
        (3, "Desk Chair", "Furniture", 8, 149.50, "OfficeSupply"),
        (4, "Notebook", "Stationery", 120, 2.50, "PaperCo"),
        (5, "Monitor", "Electronics", 0, 199.99, "TechCorp"),
    ])
    conn.commit()
    conn.close()

    yield path

    try:
        os.remove(path)
    except OSError:
        pass


def classify_outcome(resp_status: int, data: dict) -> str:
    """Map API response to one of the 8 canonical outcomes."""
    if resp_status in (400, 403):
        return "blocked"
    if resp_status == 422:
        return "clarification"
    if resp_status != 200:
        return "blocked"

    # Friendly conversational reply
    if data.get("intent") == "conversation" or data.get("query_type") == "conversation":
        return "friendly_reply"

    # Near-miss did-you-mean confirmation
    if data.get("needs_confirmation") and data.get("suggested_value"):
        return "did_you_mean"

    # Clarification needed
    if data.get("needs_clarification"):
        return "clarification"

    # Data unavailable in schema
    if data.get("data_available") is False:
        return "unavailable"

    # Explicit blocked indicators in SQL, explanation, or zero confidence
    sql_text = data.get("sql") or ""
    exp_text = (data.get("explanation") or "").lower()
    if (
        "-- Dangerous" in sql_text
        or "-- Blocked" in sql_text
        or "prohibited" in exp_text
        or "not allowed" in exp_text
        or "blocked" in exp_text
        or "security" in exp_text
        or "safety" in exp_text
        or data.get("confidence") == 0.0
    ):
        return "blocked"

    # Write staged for confirmation (needs_confirmation must be True or query_type == "write")
    if (data.get("needs_confirmation") and not data.get("suggested_value")) or data.get("query_type") == "write":
        return "write_pending"

    # If no SQL produced and not conversation, blocked or clarification
    if not sql_text and not data.get("result"):
        if (
            "prohibited" in exp_text
            or "not allowed" in exp_text
            or "blocked" in exp_text
            or "security" in exp_text
            or data.get("confidence") == 0.0
        ):
            return "blocked"
        return "clarification"

    # Check rows returned
    result = data.get("result", [])
    if len(result) == 0:
        return "zero_rows_explained"
    return "rows"


def execute_scenario(client: TestClient, scenario: Scenario, session_id: str, bypass_cache: bool = True) -> Dict[str, Any]:
    """Execute a single scenario against the backend and assert criteria."""
    if bypass_cache:
        clear_query_cache()
    reset_rate_limits()

    conv_id = f"test-conv-{scenario.id}-{int(time.time()*1000)}"

    # 1. Primary Query
    resp = client.post(
        "/api/query",
        json={
            "session_id": session_id,
            "conversation_id": conv_id,
            "text": scenario.question,
            "language": "auto",
        }
    )

    data = resp.json() if resp.status_code == 200 else {}
    actual_outcome = classify_outcome(resp.status_code, data)

    # 2. Follow-up Query if scenario specifies one
    if scenario.follow_up and resp.status_code == 200:
        time.sleep(0.1)
        if bypass_cache:
            clear_query_cache()
        reset_rate_limits()

        resp2 = client.post(
            "/api/query",
            json={
                "session_id": session_id,
                "conversation_id": conv_id,
                "text": scenario.follow_up,
                "language": "auto",
            }
        )
        data2 = resp2.json() if resp2.status_code == 200 else {}
        actual_outcome = classify_outcome(resp2.status_code, data2)
        data = data2

    return {
        "status_code": resp.status_code,
        "data": data,
        "outcome": actual_outcome,
    }


# ---------------------------------------------------------------------------
# Test Matrix Suite
# ---------------------------------------------------------------------------

class TestScenarioMatrix:
    """Comprehensive test matrix executing all 127 scenarios across 14 categories."""

    @pytest.fixture(autouse=True)
    def setup_sessions(self, client, custom_db_path):
        """Prepare active sessions for each DB type."""
        # Hospital session
        r_h = client.post("/api/connect-db", json={"db_type": "demo", "demo_name": "hospital"})
        self.hosp_sid = r_h.json()["session_id"]

        # Ecommerce session
        r_e = client.post("/api/connect-db", json={"db_type": "demo", "demo_name": "ecommerce"})
        self.ecom_sid = r_e.json()["session_id"]

        # Custom DB session
        cust_uri = f"sqlite:///{Path(custom_db_path).as_posix()}"
        r_c = client.post("/api/connect-db", json={"db_type": "sqlite", "connection_string": cust_uri})
        self.cust_sid = r_c.json()["session_id"]

    def _get_sid(self, db_type: str) -> str:
        if db_type == "ecommerce":
            return self.ecom_sid
        if db_type == "custom":
            return self.cust_sid
        return self.hosp_sid

    @pytest.mark.parametrize("sc", SCENARIOS, ids=[s.id for s in SCENARIOS])
    def test_single_scenario(self, client, sc: Scenario):
        """Run an individual scenario from the 127-scenario matrix."""
        sid = self._get_sid(sc.db)
        res = execute_scenario(client, sc, sid, bypass_cache=True)
        data = res["data"]
        actual_outcome = res["outcome"]
        expected = sc.follow_up_expected_outcome if sc.follow_up else sc.expected_outcome

        # Assert outcome type matches
        assert actual_outcome == expected, (
            f"[{sc.id}] {sc.description}: Expected outcome '{expected}', but got '{actual_outcome}'. "
            f"Explanation: {data.get('explanation')}, SQL: {data.get('sql')}"
        )

        # Assert SQL constraints
        sql = data.get("sql") or ""
        if sc.sql_must_contain:
            for s in sc.sql_must_contain:
                assert s.lower() in sql.lower(), (
                    f"[{sc.id}] SQL missing required substring '{s}': {sql}"
                )

        if sc.sql_must_not_contain:
            for s in sc.sql_must_not_contain:
                assert s.lower() not in sql.lower(), (
                    f"[{sc.id}] SQL contains forbidden substring '{s}': {sql}"
                )

        # Assert row count bounds
        if actual_outcome == "rows":
            rows = data.get("result", [])
            if sc.min_rows:
                assert len(rows) >= sc.min_rows, (
                    f"[{sc.id}] Expected at least {sc.min_rows} rows, got {len(rows)}"
                )
            if sc.max_rows is not None:
                assert len(rows) <= sc.max_rows, (
                    f"[{sc.id}] Expected at most {sc.max_rows} rows, got {len(rows)}"
                )

        # Assert chart types
        if sc.expected_chart_types:
            chart = data.get("chart_type", "none")
            assert chart in sc.expected_chart_types, (
                f"[{sc.id}] Expected chart_type in {sc.expected_chart_types}, got '{chart}'"
            )
