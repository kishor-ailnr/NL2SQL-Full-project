"""
tests/test_data_value_integrity.py
----------------------------------
Test suite for Data Value Integrity & Zero-Results Reasoning (Bug 1 & Bug 2).

Verifies:
1. Search for a deliberately misspelled name that does not exist ("xyzabc123") -> 0 rows, explanation mentions "xyzabc123".
2. Search for a misspelled name phonetically close to a real existing name ("virthi" vs "Karthik") -> literal "virthi" searched,
   0 rows returned, explanation says no match found for "virthi", Karthik's data is NOT returned.
3. Search for the correct exact existing name ("Karthik Raj") -> returns record normally, high confidence, no clarification.
4. Schema-term typo ("paiens" -> "patients") -> still corrected normally in corrected_terms.
5. Zero-result query with legitimate reason ("patients visited in the last 5 days") -> explanation clearly states no match found for criteria.
"""

import pytest

pytestmark = pytest.mark.integration


def _query(client, session_id: str, text: str):
    return client.post(
        "/api/query",
        json={"session_id": session_id, "text": text, "language": "auto"},
    )


class TestDataValueIntegrityAndZeroResults:
    """Verifies that user data values are never replaced with DB records, and 0-row results are clearly explained."""

    def test_1_deliberately_misspelled_nonexistent_name(self, client, hospital_sid):
        """Case 1: Search for a deliberately misspelled name that does NOT exist and is NOT close to any real name.
        
        Expect: 0 rows, SQL searches for literal 'xyzabc123', and explanation clearly states no match found,
        explicitly mentioning 'xyzabc123' (not a substituted name).
        """
        resp = _query(client, hospital_sid, "search for patient xyzabc123")
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()

        assert data.get("result") == [], f"Expected 0 rows returned, got: {data.get('result')}"
        sql = (data.get("sql") or "").lower()
        assert "xyzabc123" in sql, f"Expected SQL WHERE clause to search for literal 'xyzabc123', got: {sql}"

        explanation = data.get("explanation") or ""
        assert "xyzabc123" in explanation.lower(), f"Expected explanation to mention 'xyzabc123', got: {explanation}"
        assert any(
            phrase in explanation.lower()
            for phrase in ["no patient found", "no patients found", "no patient was found", "no patients were found", "no record", "no match"]
        ), f"Expected explanation to state no match found, got: {explanation}"

    def test_2_misspelled_name_phonetically_close_to_existing_record(self, client, hospital_sid):
        """Case 2: Search for a misspelled name that IS phonetically close to a real existing name ("virthi" vs "Karthik").
        
        Expect: SQL searches for the LITERAL 'virthi' text, returns 0 rows (since no patient is actually named virthi),
        explanation says no match found for 'virthi', and Karthik's data must NOT be returned.
        """
        resp = _query(client, hospital_sid, "show details of patient virthi")
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()

        # 1. SQL must search for literal 'virthi', never 'karthik'
        sql = (data.get("sql") or "").lower()
        assert "virthi" in sql, f"Expected SQL to search for literal 'virthi', got: {sql}"
        assert "karthik" not in sql, f"CRITICAL ACCURACY BUG: SQL substituted 'virthi' with 'karthik': {sql}"

        # 2. corrected_terms must NOT swap 'virthi' -> 'Karthik'
        corrected_terms = data.get("corrected_terms") or []
        for pair in corrected_terms:
            orig = pair.get("original", "").lower()
            corr = pair.get("corrected", "").lower()
            assert not (orig == "virthi" and "karthik" in corr), (
                f"CRITICAL: corrected_terms substituted data value 'virthi' with database record '{corr}'"
            )

        # 3. 0 rows must be returned
        result = data.get("result") or []
        assert len(result) == 0, f"Expected 0 rows returned for nonexistent patient 'virthi', got: {result}"

        # 4. Karthik's data MUST NOT be returned in result rows
        result_str = str(result).lower()
        assert "karthik" not in result_str, f"CRITICAL: Karthik's data was returned for 'virthi' search: {result}"

        # 5. Explanation must clearly state no match found for 'virthi'
        explanation = data.get("explanation") or ""
        assert "virthi" in explanation.lower(), f"Expected explanation to mention 'virthi', got: {explanation}"
        assert any(
            phrase in explanation.lower()
            for phrase in ["no patient found", "no patients found", "no patient was found", "no patients were found", "no match", "no record"]
        ), f"Expected explanation to clearly state no patient found, got: {explanation}"

    def test_3_correct_exact_existing_name(self, client, hospital_sid):
        """Case 3: Search for the CORRECT exact name that does exist ("Karthik Raj").
        
        Expect: That patient's data returned normally, confidence high (>= 0.7), no clarification needed.
        """
        resp = _query(client, hospital_sid, "show details of patient Karthik Raj")
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()

        assert data.get("needs_clarification") is False, "Exact match query should not need clarification"
        assert data.get("confidence", 0) >= 0.7, f"Expected high confidence >= 0.7, got {data.get('confidence')}"

        result = data.get("result") or []
        assert len(result) > 0, f"Expected patient records for 'Karthik Raj', got 0 rows. Result: {result}"

        # Confirm the record belongs to Karthik Raj
        matching_rows = [r for r in result if "karthik" in str(r).lower()]
        assert len(matching_rows) > 0, f"Expected Karthik Raj in result rows, got: {result}"

    def test_4_genuine_schema_term_typo_still_corrected(self, client, hospital_sid):
        """Case 4: A genuine schema-term typo ("paiens" instead of "patients").
        
        Expect: Confirm this STILL gets corrected normally in corrected_terms (regression check that Bug 1/2
        fixes did not break the original typo-correction feature for schema terms).
        """
        resp = _query(client, hospital_sid, "show me paiens older than 40")
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()

        corrected = data.get("corrected_terms") or []
        assert any(
            item.get("original", "").lower() == "paiens" and "patient" in item.get("corrected", "").lower()
            for item in corrected
        ), f"Expected 'paiens' -> 'patients' correction in corrected_terms, got: {corrected}"

        sql = (data.get("sql") or "").lower()
        assert "patients" in sql or "patient" in sql, f"Expected SQL to query patients table, got: {sql}"
        assert "40" in sql, f"Expected age filter > 40 in SQL, got: {sql}"

    def test_5_zero_results_for_legitimate_reason(self, client, hospital_sid):
        """Case 5: A query with zero results for a legitimate reason ("patients visited in the last 5 days" when none were).
        
        Expect: Query executes successfully, returns 0 rows, and explanation clearly states that no patients
        matched the criteria (not just an empty table without explanation).
        """
        resp = _query(client, hospital_sid, "patients visited in the last 5 days")
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()

        assert data.get("result") == [], f"Expected 0 rows for last 5 days query, got: {data.get('result')}"

        explanation = data.get("explanation") or ""
        assert len(explanation.strip()) > 0, "Explanation must not be empty on zero results"
        expl_lower = explanation.lower()

        # Explanation must state that no patients/records were found matching the condition
        assert any(
            p in expl_lower
            for p in ["no patients found", "no patient found", "no patients were found", "no patient was found", "no records found", "no records were found", "no matching", "no data found"]
        ), f"Expected explanation to state no patients/records found, got: {explanation}"

        # Explanation should restate condition or timeframe
        assert any(
            k in expl_lower
            for k in ["5 days", "visited", "last 5", "criteria", "recent"]
        ), f"Expected explanation to mention condition/timeframe ('last 5 days' or 'visited'), got: {explanation}"
