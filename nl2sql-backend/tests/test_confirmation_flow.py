"""
tests/test_confirmation_flow.py
--------------------------------
Tests for the "Did you mean" confirmation flow for near-miss name/value searches.

Verifies:
1. Search "harini" (near-miss for "Harini Krishnan") -> needs_confirmation: True, confirmation_question mentions "Harini Krishnan", sql: None
2. Follow-up "yes" in the same conversation -> returns Harini Krishnan's actual data, sql populated, result non-empty
3. Regression: search "xyzabc123" (no close match) -> existing zero-results reasoning, needs_confirmation: False
4. Regression: search exact name "Karthik Raj" -> normal direct result, needs_confirmation: False
5. Search "harini" then follow up with "Karthik Raj" instead of "yes" -> searches fresh for "Karthik Raj", not stuck on Harini
"""

import uuid
import pytest

pytestmark = pytest.mark.integration


def _query(client, session_id: str, text: str, conversation_id: str = None):
    payload = {
        "session_id": session_id,
        "text": text,
        "language": "auto",
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return client.post("/api/query", json=payload)


class TestConfirmationFlow:
    """Suite testing the 'did you mean' confirmation flow for near-miss search values."""

    def test_1_near_miss_triggers_confirmation_not_silent_substitution(self, client, hospital_sid):
        """Case 1: Search 'harini' (no exact match, but 'Harini Krishnan' exists in sample data).
        
        Expect:
        - needs_confirmation: True
        - confirmation_question mentions 'Harini Krishnan' and 'harini'
        - suggested_value: 'Harini Krishnan'
        - sql: None
        - result: []
        """
        resp = _query(client, hospital_sid, "search for patient harini")
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()

        assert data.get("needs_confirmation") is True, f"Expected needs_confirmation=True, got: {data}"
        assert data.get("suggested_value") == "Harini Krishnan", f"Expected suggested_value='Harini Krishnan', got: {data.get('suggested_value')}"

        conf_q = data.get("confirmation_question") or ""
        assert "harini krishnan" in conf_q.lower(), f"Expected confirmation_question to mention 'Harini Krishnan', got: {conf_q}"
        assert "harini" in conf_q.lower(), f"Expected confirmation_question to mention literal 'harini', got: {conf_q}"

        assert data.get("sql") is None, f"Expected sql=None during confirmation state, got: {data.get('sql')}"
        assert data.get("result") == [], f"Expected result=[] during confirmation state, got: {data.get('result')}"

    def test_2_follow_up_yes_returns_confirmed_record(self, client, hospital_sid):
        """Case 2: Follow-up 'yes' in the same conversation returns Harini Krishnan's data.
        
        Expect:
        - Message 1: needs_confirmation=True
        - Message 2 ('yes'): needs_confirmation=False, sql populated targeting Harini Krishnan,
          result contains Harini Krishnan's row.
        """
        conv_id = str(uuid.uuid4())

        # Step 1: User asks for 'harini'
        r1 = _query(client, hospital_sid, "search for patient harini", conversation_id=conv_id)
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1.get("needs_confirmation") is True

        # Step 2: User responds 'yes'
        r2 = _query(client, hospital_sid, "yes", conversation_id=conv_id)
        assert r2.status_code == 200, f"Follow-up failed: {r2.text}"
        d2 = r2.json()

        assert d2.get("needs_confirmation") is False, f"Expected needs_confirmation=False after 'yes', got: {d2}"
        sql = (d2.get("sql") or "").lower()
        assert "harini" in sql or "krishnan" in sql, f"Expected SQL to search for Harini Krishnan, got: {sql}"

        result = d2.get("result") or []
        assert len(result) > 0, f"Expected non-empty result for confirmed Harini Krishnan, got: {result}"
        assert any("harini" in str(row).lower() for row in result), f"Expected Harini Krishnan in results, got: {result}"

    def test_3_regression_nonexistent_unrelated_name_no_confirmation(self, client, hospital_sid):
        """Case 3: Regression: search 'xyzabc123' (no close match at all).
        
        Expect:
        - Existing 'no results found' behavior (Bug 1 fix)
        - NOT the confirmation flow (needs_confirmation stays False)
        - Explanation states no match found mentioning 'xyzabc123'
        """
        resp = _query(client, hospital_sid, "search for patient xyzabc123")
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()

        assert data.get("needs_confirmation") is False, f"Expected needs_confirmation=False for unrelated query, got: {data}"
        assert data.get("confirmation_question") is None
        assert data.get("suggested_value") is None

        assert data.get("result") == [], f"Expected 0 rows for xyzabc123, got: {data.get('result')}"
        sql = (data.get("sql") or "").lower()
        assert "xyzabc123" in sql, f"Expected SQL to search literal 'xyzabc123', got: {sql}"

        explanation = (data.get("explanation") or "").lower()
        assert "xyzabc123" in explanation, f"Expected explanation to mention 'xyzabc123', got: {explanation}"

    def test_4_regression_exact_match_no_confirmation(self, client, hospital_sid):
        """Case 4: Regression: search exact correct full name 'Karthik Raj'.
        
        Expect:
        - Direct execution without confirmation (needs_confirmation: False)
        - Data returned normally
        """
        resp = _query(client, hospital_sid, "show details of patient Karthik Raj")
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()

        assert data.get("needs_confirmation") is False, f"Expected needs_confirmation=False for exact match, got: {data}"
        assert data.get("confirmation_question") is None
        assert data.get("suggested_value") is None

        result = data.get("result") or []
        assert len(result) > 0, f"Expected records for exact match 'Karthik Raj', got: {result}"
        assert any("karthik" in str(row).lower() for row in result)

    def test_5_different_name_after_confirmation_runs_fresh(self, client, hospital_sid):
        """Case 5: Search 'harini', then follow up with a different name instead of 'yes' ('Karthik Raj').
        
        Expect:
        - Step 1: needs_confirmation=True for Harini
        - Step 2: System searches for 'Karthik Raj' fresh, NOT stuck on Harini suggestion
        - Returns Karthik Raj's data
        """
        conv_id = str(uuid.uuid4())

        # Step 1: User asks for 'harini'
        r1 = _query(client, hospital_sid, "search for patient harini", conversation_id=conv_id)
        assert r1.status_code == 200
        assert r1.json().get("needs_confirmation") is True

        # Step 2: User provides different name instead of 'yes'
        r2 = _query(client, hospital_sid, "show details of patient Karthik Raj", conversation_id=conv_id)
        assert r2.status_code == 200, f"Query failed: {r2.text}"
        d2 = r2.json()

        assert d2.get("needs_confirmation") is False, f"Expected needs_confirmation=False, got: {d2}"
        sql = (d2.get("sql") or "").lower()
        assert "karthik" in sql, f"Expected SQL to search for Karthik Raj, got: {sql}"
        assert "harini" not in sql, f"SQL should not search for harini after fresh query: {sql}"

        result = d2.get("result") or []
        assert len(result) > 0, f"Expected records for Karthik Raj, got: {result}"
        assert any("karthik" in str(row).lower() for row in result)
