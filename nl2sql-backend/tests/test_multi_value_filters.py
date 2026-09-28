"""
tests/test_multi_value_filters.py
---------------------------------
Comprehensive test suite verifying multi-value questions on the SAME column:
1. Deterministic AST Guard unit tests using sqlglot (rewrites col = a AND col = b into IN).
2. Zero-row & partial-match explanation unit tests built from actual WHERE clause.
3. End-to-end LLM queries across IDs, text IDs, names, dates, amounts, categories,
   mixed columns, NOT/exclusions, row intersections, joins, Tamil/Thanglish,
   uploaded CSV with spaced column headers, and cross-domain hospital demo.
Asserts on SQL AST structure (parsed via sqlglot) and returned rows/explanations.
"""

import io
import time
import pytest
import sqlglot
from sqlglot import exp
from starlette.testclient import TestClient

from app.services.sql_generator import (
    sanitize_mutually_exclusive_and,
    evaluate_where_clause_results,
    generate_zero_result_explanation,
    clear_query_cache,
)


# ===========================================================================
# STEP 3: DETERMINISTIC GUARD UNIT TESTS (AST parsing and rewriting via sqlglot)
# ===========================================================================

class TestGuardUnitTests:
    """Verifies that sanitize_mutually_exclusive_and correctly rewrites unsatisfiable
    same-column equality predicates inside AND conjuncts across all scopes, while
    leaving satisfiable conditions untouched.
    """

    def test_guard_two_literals_rewritten_to_in(self):
        sql = "SELECT * FROM transactions WHERE transaction_id = 'TXN_1001' AND transaction_id = 'TXN_1002'"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        in_expr = tree.find(exp.In)
        assert in_expr is not None, f"Expected exp.In in rewritten SQL: {rewritten}"
        in_col = in_expr.this.sql(dialect="sqlite")
        assert in_col == "transaction_id"
        vals = [e.this for e in in_expr.expressions if isinstance(e, exp.Literal)]
        assert "TXN_1001" in vals and "TXN_1002" in vals
        assert note is not None
        assert "Treated 'TXN_1001 and TXN_1002' as either value" in note

    def test_guard_three_literals_numeric_rewritten(self):
        sql = "SELECT * FROM orders WHERE id = 3 AND id = 5 AND id = 7"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        in_expr = tree.find(exp.In)
        assert in_expr is not None
        vals = [int(e.this) for e in in_expr.expressions if isinstance(e, exp.Literal)]
        assert vals == [3, 5, 7]
        assert "Treated '3 and 5 and 7' as either value" in note

    def test_guard_table_qualified_column(self):
        sql = "SELECT * FROM customers AS c WHERE c.id = 1 AND c.id = 2"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        in_expr = tree.find(exp.In)
        assert in_expr is not None
        assert "c.id" in in_expr.this.sql(dialect="sqlite").lower()

    def test_guard_lower_function_column(self):
        sql = "SELECT * FROM products WHERE LOWER(name) = 'keyboard' AND LOWER(name) = 'mouse'"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        in_expr = tree.find(exp.In)
        assert in_expr is not None
        assert "lower(name)" in in_expr.this.sql(dialect="sqlite").lower()

    def test_guard_nested_inside_or_groups(self):
        sql = "SELECT * FROM items WHERE (status = 'pending' AND status = 'shipped') OR (category = 'A' AND category = 'B')"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        in_exprs = list(tree.find_all(exp.In))
        assert len(in_exprs) == 2, f"Expected 2 IN expressions, got {len(in_exprs)}"

    def test_guard_in_join_on_clause(self):
        sql = "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id AND c.id = 10 AND c.id = 20"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        join_expr = tree.find(exp.Join)
        assert join_expr is not None
        in_expr = join_expr.find(exp.In)
        assert in_expr is not None
        assert "c.id" in in_expr.this.sql(dialect="sqlite").lower()

    def test_guard_in_subquery(self):
        sql = "SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers WHERE status = 'gold' AND status = 'platinum')"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        selects = list(tree.find_all(exp.Select))
        assert len(selects) >= 2
        sub_in = selects[1].find(exp.In)
        assert sub_in is not None
        assert "status" in sub_in.this.sql(dialect="sqlite").lower()

    def test_guard_preserves_satisfiable_range(self):
        sql = "SELECT * FROM products WHERE price > 50 AND price < 100"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        assert tree.find(exp.In) is None
        assert len(list(tree.find_all(exp.GT))) == 1
        assert len(list(tree.find_all(exp.LT))) == 1

    def test_guard_preserves_satisfiable_like(self):
        sql = "SELECT * FROM descriptions WHERE text LIKE '%red%' AND text LIKE '%leather%'"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        assert tree.find(exp.In) is None
        assert len(list(tree.find_all(exp.Like))) == 2

    def test_guard_preserves_different_columns(self):
        sql = "SELECT * FROM customers WHERE id = 1 AND city = 'Chennai'"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        assert tree.find(exp.In) is None
        assert len(list(tree.find_all(exp.EQ))) == 2

    def test_guard_preserves_group_by_having_intersection(self):
        sql = "SELECT customer_id FROM orders WHERE product_id IN (1, 2) GROUP BY customer_id HAVING COUNT(DISTINCT product_id) = 2"
        rewritten, note = sanitize_mutually_exclusive_and(sql)
        tree = sqlglot.parse_one(rewritten, read="sqlite")
        assert tree.find(exp.Having) is not None
        assert "HAVING" in rewritten.upper()


# ===========================================================================
# STEP 4: BETTER ZERO-ROW & PARTIAL EXPLANATION UNIT TESTS
# ===========================================================================

class TestExplanationUnitTests:
    """Verifies that explanations are dynamically built from the actual WHERE clause
    for partial matches and zero-row matches.
    """

    def test_partial_match_reporting(self):
        sql = "SELECT * FROM transactions WHERE transaction_id IN ('TXN_1001', 'TXN_1002')"
        rows = [{"transaction_id": "TXN_1001", "amount": 150.0}]
        explanation = evaluate_where_clause_results(sql, rows, "show transaction TXN_1001 and TXN_1002")
        assert explanation is not None
        assert "Found transaction TXN_1001; no transaction TXN_1002 found." in explanation

    def test_all_missing_zero_rows_explanation(self):
        sql = "SELECT * FROM transactions WHERE transaction_id IN ('TXN_999', 'TXN_888')"
        explanation = generate_zero_result_explanation("show transaction TXN_999 and TXN_888", sql)
        assert "TXN_999" in explanation or "TXN_888" in explanation
        assert "no transactions found" in explanation.lower() or "no transaction found" in explanation.lower()

    def test_date_without_year_zero_rows_explanation(self):
        sql = "SELECT * FROM appointments WHERE strftime('%m', appointment_date) BETWEEN '01' AND '02'"
        explanation = generate_zero_result_explanation("appointments between January and February", sql)
        assert "no year given, so all years were included" in explanation.lower()


# ===========================================================================
# STEP 5: END-TO-END LLM SCENARIOS (Testing SQL AST structure & Row Results)
# ===========================================================================

@pytest.mark.integration
class TestMultiValueLLMScenarios:
    """End-to-end integration tests using FastAPI TestClient against real databases.
    Respects rate limits using sleep throttling and tests scenarios twice with cache cleared.
    """

    @pytest.fixture(autouse=True)
    def throttle(self):
        time.sleep(1.2)
        yield
        time.sleep(1.2)

    def _query(self, client: TestClient, session_id: str, question: str):
        clear_query_cache()
        resp = client.post("/api/query", json={"session_id": session_id, "text": question, "language": "auto"})
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        return resp.json()

    # --- Scenario 1: Numeric IDs ---
    def test_numeric_ids_and_or_list(self, client: TestClient, ecommerce_sid: str):
        # 1 and 2
        for _ in range(2):
            clear_query_cache()
            data = self._query(client, ecommerce_sid, "show customer 1 and customer 2")
            assert data["sql"] is not None
            tree = sqlglot.parse_one(data["sql"], read="sqlite")
            assert tree.find(exp.In) is not None or tree.find(exp.Or) is not None
            assert len(data["result"]) == 2
            ids = {r["id"] for r in data["result"] if "id" in r}
            assert {1, 2}.issubset(ids)
            time.sleep(1.2)

        # 1, 2 and 3
        data = self._query(client, ecommerce_sid, "orders 1, 2 and 3")
        assert len(data["result"]) == 3

        # 1 or 2
        data = self._query(client, ecommerce_sid, "customer 1 or 2")
        assert len(data["result"]) >= 2

        # 10 ids in a list
        data = self._query(client, ecommerce_sid, "orders 1, 2, 3, 4, 5, 6, 7, 8, 9, 10")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.In) is not None or tree.find(exp.Or) is not None
        assert len(data["result"]) == 10

    # --- Scenario 2: Text IDs on Uploaded CSV ---
    def test_text_ids_uploaded_csv(self, client: TestClient):
        csv_bytes = b"transaction_id,amount,status\nTXN_1001,150.0,completed\nTXN_1002,250.0,pending\nTXN_1003,500.0,completed\n"
        upload_resp = client.post("/api/upload-db", files={"file": ("transactions.csv", io.BytesIO(csv_bytes), "text/csv")})
        assert upload_resp.status_code == 200
        sid = upload_resp.json()["session_id"]

        for _ in range(2):
            clear_query_cache()
            data = self._query(client, sid, "show transaction TXN_1001 and transaction TXN_1002")
            assert data["sql"] is not None
            tree = sqlglot.parse_one(data["sql"], read="sqlite")
            assert tree.find(exp.In) is not None or tree.find(exp.Or) is not None
            assert len(data["result"]) == 2
            txns = {r["transaction_id"] for r in data["result"]}
            assert txns == {"TXN_1001", "TXN_1002"}
            time.sleep(1.2)

    # --- Scenario 3: Names (both exist, one exists/one missing, both missing) ---
    def test_names_scenarios(self, client: TestClient, hospital_sid: str):
        # Both exist
        data = self._query(client, hospital_sid, "show patient Alice Jenkins and patient Bob Smith")
        assert len(data["result"]) >= 2

        # One exists, one missing
        data = self._query(client, hospital_sid, "show patient Alice Jenkins and patient NonExistentPerson999")
        assert len(data["result"]) >= 1
        assert "Alice Jenkins" in [r.get("name") for r in data["result"]]
        assert "NonExistentPerson999" in (data.get("explanation") or "")

        # Both missing
        data = self._query(client, hospital_sid, "show patient FakePersonOne and patient FakePersonTwo")
        assert len(data["result"]) == 0
        assert "FakePersonOne" in (data.get("explanation") or "") or "FakePersonTwo" in (data.get("explanation") or "")

    # --- Scenario 4: Dates (specific dates, between range, no year) ---
    def test_date_scenarios(self, client: TestClient, ecommerce_sid: str):
        # Specific dates
        data = self._query(client, ecommerce_sid, "orders on 2024-02-01 and 2024-02-03")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.In) is not None or tree.find(exp.Or) is not None or tree.find(exp.Between) is not None

        # Range between
        data = self._query(client, ecommerce_sid, "orders between February 1 2024 and February 5 2024")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.Between) is not None or (tree.find(exp.GTE) is not None and tree.find(exp.LTE) is not None)

        # No year given
        data = self._query(client, ecommerce_sid, "orders in January and February")
        assert data["sql"] is not None
        assert "strftime" in data["sql"].lower()
        assert "no year given, so all years were included" in (data.get("explanation") or "").lower()

    # --- Scenario 5: Amounts (values, range, comparisons) ---
    def test_amount_scenarios(self, client: TestClient, ecommerce_sid: str):
        # Discrete values
        data = self._query(client, ecommerce_sid, "orders with total_amount 100 and 250")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.In) is not None or tree.find(exp.Or) is not None

        # Range
        data = self._query(client, ecommerce_sid, "orders with amount between 100 and 250")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.Between) is not None or (tree.find(exp.GTE) is not None and tree.find(exp.LTE) is not None)

        # Comparisons
        data = self._query(client, ecommerce_sid, "orders with amount above 100 and below 250")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.GT) is not None or tree.find(exp.GTE) is not None

    # --- Scenario 6: Categories ---
    def test_category_scenarios(self, client: TestClient, ecommerce_sid: str):
        data = self._query(client, ecommerce_sid, "products in category Electronics and Clothing")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.In) is not None or tree.find(exp.Or) is not None

    # --- Scenario 7: Mixed Columns ---
    def test_mixed_columns_scenarios(self, client: TestClient, ecommerce_sid: str):
        # AND across different columns
        data = self._query(client, ecommerce_sid, "customer 1 and city San Jose")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.And) is not None

        # Same column OR combined with different column AND
        data = self._query(client, ecommerce_sid, "customer 1 or 2 and city San Jose")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.In) is not None or tree.find(exp.Or) is not None

    # --- Scenario 8: NOT / Exclusions ---
    def test_not_exclusions_scenarios(self, client: TestClient, ecommerce_sid: str):
        data = self._query(client, ecommerce_sid, "everyone except customer 1 and 2")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.Not) is not None or tree.find(exp.NEQ) is not None
        ids = {r["id"] for r in data["result"] if "id" in r}
        assert 1 not in ids and 2 not in ids

    # --- Scenario 9: Row Intersection ---
    def test_intersection_scenarios(self, client: TestClient, ecommerce_sid: str):
        data = self._query(client, ecommerce_sid, "customers who bought product 1 and product 2")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert (
            tree.find(exp.Having) is not None
            or tree.find(exp.Intersect) is not None
            or len(list(tree.find_all(exp.Select))) >= 2
        )

    # --- Scenario 10: Joins with Multi-Value ---
    def test_joins_with_multivalue(self, client: TestClient, ecommerce_sid: str):
        data = self._query(client, ecommerce_sid, "orders of customer 1 and 2 with product names")
        assert data["sql"] is not None
        tree = sqlglot.parse_one(data["sql"], read="sqlite")
        assert tree.find(exp.Join) is not None
        assert tree.find(exp.In) is not None or tree.find(exp.Or) is not None

    # --- Scenario 11: Tamil / Thanglish ---
    def test_tamil_thanglish_scenarios(self, client: TestClient, ecommerce_sid: str):
        # matrum
        data = self._query(client, ecommerce_sid, "customer 1 matrum customer 2")
        assert data["sql"] is not None
        assert len(data["result"]) == 2

        # mattum
        data = self._query(client, ecommerce_sid, "customer 1 mattum 2")
        assert data["sql"] is not None
        assert len(data["result"]) >= 2

    # --- Scenario 12: CSV with Spaced Column Names ---
    def test_csv_with_spaces_in_headers(self, client: TestClient):
        csv_bytes = b"Account Number,Client Name,Current Balance\nACC-101,John Doe,500\nACC-102,Jane Smith,750\nACC-103,Bob Brown,900\n"
        upload_resp = client.post("/api/upload-db", files={"file": ("accounts.csv", io.BytesIO(csv_bytes), "text/csv")})
        assert upload_resp.status_code == 200
        sid = upload_resp.json()["session_id"]

        data = self._query(client, sid, "show Account Number ACC-101 and ACC-102")
        assert data["sql"] is not None
        assert len(data["result"]) == 2
        accs = {r.get("Account Number") for r in data["result"]}
        assert accs == {"ACC-101", "ACC-102"}

    # --- Scenario 13: Cross-domain Hospital Demo ---
    def test_cross_domain_hospital(self, client: TestClient, hospital_sid: str):
        # patient 1 and 2
        data = self._query(client, hospital_sid, "patient 1 and 2")
        assert data["sql"] is not None
        assert len(data["result"]) == 2

        # doctor Ravi and Priya
        data = self._query(client, hospital_sid, "doctor Ravi and Priya")
        assert data["sql"] is not None
        assert data["query_type"] == "select"
