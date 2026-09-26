"""
tests/test_confirmation_flow_regression.py
-----------------------------------------
Regression test suite for confirmation flow and result rendering:
1. Full flow: ask "show me data of patient james" -> get needs_confirmation: true with suggested_value "Dr. James Wilson"
   -> send "yes" as the next message in the SAME conversation_id
   -> confirm this now returns the actual data for Dr. James Wilson, sql populated, result non-empty (Bug B regression)
2. Direct exact-name query "show details of patient Dr. James Wilson"
   -> confirm API response itself contains populated "result" data (Bug C regression at API level)
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


class TestConfirmationFlowRegression:
    """Regression suite testing confirmation follow-up resolution and direct exact-name queries."""

    def test_1_full_flow_james_confirmation_and_yes_follow_up(self, client, hospital_sid):
        """Case 1 (Bug B):
        - Ask 'show me data of patient james'
        - Expect needs_confirmation: True, suggested_value: 'Dr. James Wilson'
        - Send 'yes' as follow-up in the SAME conversation_id
        - Confirm this returns actual data for Dr. James Wilson, sql populated, result non-empty.
        """
        conv_id = str(uuid.uuid4())

        # Step 1: User asks for 'james'
        r1 = _query(client, hospital_sid, "show me data of patient james", conversation_id=conv_id)
        assert r1.status_code == 200, f"Query 1 failed: {r1.text}"
        d1 = r1.json()

        assert d1.get("needs_confirmation") is True, f"Expected needs_confirmation=True for 'james', got: {d1}"
        assert d1.get("suggested_value") == "Dr. James Wilson", f"Expected suggested_value='Dr. James Wilson', got: {d1.get('suggested_value')}"
        conf_q = (d1.get("confirmation_question") or "").lower()
        assert "dr. james wilson" in conf_q or "james" in conf_q, f"Confirmation question unexpected: {conf_q}"

        # Step 2: User responds 'yes'
        r2 = _query(client, hospital_sid, "yes", conversation_id=conv_id)
        assert r2.status_code == 200, f"Follow-up 'yes' failed: {r2.text}"
        d2 = r2.json()

        # Bug B check: must NOT return needs_confirmation=True again!
        assert d2.get("needs_confirmation") is False, f"Bug B regression: expected needs_confirmation=False after 'yes', got: {d2}"
        sql = (d2.get("sql") or "").lower()
        assert "doctors" in sql or "patients" in sql, f"Expected valid SQL targeting doctor/patient table, got: {sql}"
        assert "james" in sql and "wilson" in sql, f"Expected SQL to target Dr. James Wilson, got: {sql}"

        result = d2.get("result") or []
        assert len(result) > 0, f"Expected populated result data for Dr. James Wilson after 'yes', got empty list: {result}"
        assert any("james wilson" in str(row).lower() for row in result), f"Expected Dr. James Wilson in rows: {result}"

    def test_2_direct_exact_name_query_returns_populated_result(self, client, hospital_sid):
        """Case 2 (Bug C):
        - Direct exact query 'show details of patient Dr. James Wilson'
        - Confirm API response contains populated 'result' data, bypassing frontend rendering.
        """
        resp = _query(client, hospital_sid, "show details of patient Dr. James Wilson")
        assert resp.status_code == 200, f"Direct query failed: {resp.text}"
        data = resp.json()

        assert data.get("needs_confirmation") is False, f"Expected needs_confirmation=False for exact query, got: {data}"
        assert data.get("sql") is not None, f"Expected populated SQL, got: {data.get('sql')}"

        result = data.get("result") or []
        assert len(result) > 0, f"Bug C regression: expected populated result data, got empty list: {result}"
        assert any("james wilson" in str(row).lower() for row in result), f"Expected Dr. James Wilson in result rows: {result}"
