"""
tests/test_multi_entity_and_or.py
---------------------------------
Comprehensive unit and integration test suite for multi-entity AND / OR condition handling,
partial result matching, fuzzy candidate clarification, and normal filter regression protection.
"""

import sys
import sqlite3
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.sql_generator import (
    extract_entity_conjunctions,
    fix_mutually_exclusive_and,
    evaluate_multi_entity_results,
    clean_entity_term,
)

HOSPITAL_DB = Path(__file__).resolve().parent.parent / "data" / "demo_hospital.db"


# ===========================================================================
# 1. ENTITY CONJUNCTION EXTRACTION TESTS
# ===========================================================================

class TestEntityConjunctionExtraction:
    """Verify that natural-language entity-level AND/OR expressions are accurately recognized."""

    def test_and_standard_phrase(self):
        res = extract_entity_conjunctions("Give me the details of patient 1 and patient 2")
        assert res is not None
        assert res["operator"] == "AND"
        assert res["entity_type"] == "patient"
        assert "patient 1" in res["entities"]
        assert "patient 2" in res["entities"]

    def test_and_ampersand(self):
        res = extract_entity_conjunctions("patient A & patient B")
        assert res is not None
        assert res["operator"] == "AND"
        assert "patient A" in res["entities"]
        assert "patient B" in res["entities"]

    def test_and_as_well_as(self):
        res = extract_entity_conjunctions("show patient A as well as patient B")
        assert res is not None
        assert res["operator"] == "AND"
        assert len(res["entities"]) == 2

    def test_and_along_with(self):
        res = extract_entity_conjunctions("details of patient A along with patient B")
        assert res is not None
        assert res["operator"] == "AND"
        assert len(res["entities"]) == 2

    def test_and_comma_separated(self):
        res = extract_entity_conjunctions("patient A, patient B")
        assert res is not None
        assert res["operator"] == "AND"
        assert len(res["entities"]) == 2

    def test_and_three_entities(self):
        res = extract_entity_conjunctions("Give me patient A, patient B and patient C")
        assert res is not None
        assert res["operator"] == "AND"
        assert len(res["entities"]) == 3

    def test_compare_syntax(self):
        res = extract_entity_conjunctions("compare patient A and patient B")
        assert res is not None
        assert res["operator"] == "AND"
        assert len(res["entities"]) == 2

    def test_or_standard_phrase(self):
        res = extract_entity_conjunctions("Give me patient 1 or patient 2")
        assert res is not None
        assert res["operator"] == "OR"
        assert "patient 1" in res["entities"]
        assert "patient 2" in res["entities"]


# ===========================================================================
# 2. FILTER CONJUNCTION REGRESSION TESTS (Must NOT be flagged as multi-entity)
# ===========================================================================

class TestFilterConjunctionPreservation:
    """Ensure attribute/filter-level conjunctions are NEVER misidentified as multi-entity lookups."""

    def test_diabetic_and_above_60(self):
        res = extract_entity_conjunctions("Find patients who are diabetic and above 60")
        assert res is None, "Attribute filter must not be flagged as entity conjunction"

    def test_age_comparison_operator(self):
        res = extract_entity_conjunctions("Find patients where age > 50 and gender = female")
        assert res is None, "Comparison operators must not be treated as entity conjunction"

    def test_diabetic_or_hypertensive(self):
        res = extract_entity_conjunctions("Show patients who are diabetic or hypertensive")
        assert res is None, "Boolean disease filter must not be treated as entity conjunction"

    def test_count_aggregation_conjunction(self):
        res = extract_entity_conjunctions("Count of patients and count of doctors")
        assert res is None, "Aggregation queries must not be treated as entity conjunction"


# ===========================================================================
# 3. SQL MUTUALLY EXCLUSIVE AND FIXER TESTS
# ===========================================================================

class TestSQLMutuallyExclusiveFixer:
    """Verify that mutually exclusive AND on the same column is converted to OR."""

    def test_fix_name_and(self):
        sql = "SELECT * FROM patients WHERE name = 'Alice' AND name = 'Bob';"
        fixed = fix_mutually_exclusive_and(sql)
        assert "WHERE name = 'Alice' OR name = 'Bob'" in fixed

    def test_fix_lower_name_and(self):
        sql = "SELECT * FROM patients WHERE LOWER(name) = 'alice' AND LOWER(name) = 'bob';"
        fixed = fix_mutually_exclusive_and(sql)
        assert "OR LOWER(name) = 'bob'" in fixed

    def test_fix_id_and(self):
        sql = "SELECT * FROM patients WHERE id = 1 AND id = 2;"
        fixed = fix_mutually_exclusive_and(sql)
        assert "WHERE id = 1 OR id = 2" in fixed

    def test_preserve_normal_attribute_and(self):
        sql = "SELECT * FROM patients WHERE diagnosis = 'diabetes' AND age > 60;"
        fixed = fix_mutually_exclusive_and(sql)
        assert fixed == sql, "Cross-column filters must remain AND"

    def test_preserve_range_filter_and(self):
        sql = "SELECT * FROM patients WHERE age > 20 AND age < 50;"
        fixed = fix_mutually_exclusive_and(sql)
        assert fixed == sql, "Range filters must remain AND"


# ===========================================================================
# 4. MULTI-ENTITY RESULT EVALUATION & PARTIAL SUCCESS TESTS
# ===========================================================================

class TestMultiEntityResultEvaluation:
    """Verify independent entity tracking, partial success, and near-miss clarification."""

    SAMPLE_PATIENTS = [
        "Alice Jenkins", "Karthik Raj", "Harini Krishnan", "Robert Martinez",
        "Clara Oswald", "David Kim", "Elena Rostova", "Frank Gallagher",
        "Grace Hopper", "Henry Cavill", "Irene Adler", "James Wilson", "Pavai", "Arjun Kumar"
    ]

    def test_both_exist(self):
        conjunction = {"operator": "AND", "entity_type": "patient", "entities": ["Alice Jenkins", "Karthik Raj"]}
        exec_rows = [
            {"id": 1, "name": "Alice Jenkins", "age": 42},
            {"id": 2, "name": "Karthik Raj", "age": 30},
        ]
        res = evaluate_multi_entity_results(conjunction, exec_rows, self.SAMPLE_PATIENTS)
        assert res["found_count"] == 2
        assert res["missing_count"] == 0
        assert res["has_clarification"] is False
        assert "Alice Jenkins" in res["explanation"]
        assert "Karthik Raj" in res["explanation"]

    def test_partial_success_with_candidate_clarification(self):
        """First exists, second misspelled (Arjun Kumer -> Arjun Kumar)."""
        conjunction = {"operator": "AND", "entity_type": "patient", "entities": ["Alice Jenkins", "Arjun Kumer"]}
        exec_rows = [{"id": 1, "name": "Alice Jenkins", "age": 42}]
        res = evaluate_multi_entity_results(conjunction, exec_rows, self.SAMPLE_PATIENTS)
        assert res["found_count"] == 1
        assert res["missing_count"] == 1
        assert res["has_clarification"] is True
        assert res["clarification_question"] is not None
        assert "Arjun Kumar" in res["clarification_question"]
        assert "I found data for Alice Jenkins" in res["explanation"]

    def test_partial_success_without_candidate(self):
        """First exists, second not in database at all."""
        conjunction = {"operator": "AND", "entity_type": "patient", "entities": ["Alice Jenkins", "Patient 999"]}
        exec_rows = [{"id": 1, "name": "Alice Jenkins", "age": 42}]
        res = evaluate_multi_entity_results(conjunction, exec_rows, self.SAMPLE_PATIENTS)
        assert res["found_count"] == 1
        assert res["missing_count"] == 1
        assert res["has_clarification"] is False
        assert "I found data for Alice Jenkins" in res["explanation"]
        assert "No matching data was found for Patient 999" in res["explanation"]

    def test_neither_exists_no_candidate(self):
        conjunction = {"operator": "AND", "entity_type": "patient", "entities": ["Nonexistent A", "Nonexistent B"]}
        exec_rows = []
        res = evaluate_multi_entity_results(conjunction, exec_rows, self.SAMPLE_PATIENTS)
        assert res["found_count"] == 0
        assert res["missing_count"] == 2
        assert "No matching data was found" in res["explanation"]

    def test_three_entities_independent_evaluation(self):
        """A found, B missing, C found."""
        conjunction = {"operator": "AND", "entity_type": "patient", "entities": ["Alice Jenkins", "Nonexistent B", "Karthik Raj"]}
        exec_rows = [
            {"id": 1, "name": "Alice Jenkins", "age": 42},
            {"id": 2, "name": "Karthik Raj", "age": 30},
        ]
        res = evaluate_multi_entity_results(conjunction, exec_rows, self.SAMPLE_PATIENTS)
        assert res["found_count"] == 2
        assert res["missing_count"] == 1
        assert "Alice Jenkins" in res["explanation"]
        assert "Karthik Raj" in res["explanation"]
    def test_first_missing_second_exists(self):
        """First does not exist, second exists."""
        conjunction = {"operator": "AND", "entity_type": "patient", "entities": ["Nonexistent A", "Karthik Raj"]}
        exec_rows = [{"id": 2, "name": "Karthik Raj", "age": 30}]
        res = evaluate_multi_entity_results(conjunction, exec_rows, self.SAMPLE_PATIENTS)
        assert res["found_count"] == 1
        assert res["missing_count"] == 1
        assert "Karthik Raj" in res["explanation"]
        assert "No matching data was found for Nonexistent A" in res["explanation"]

    def test_or_operator_partial_success(self):
        """OR query: patient 1 or patient 2, only 1 exists."""
        conjunction = {"operator": "OR", "entity_type": "patient", "entities": ["Alice Jenkins", "Nonexistent B"]}
        exec_rows = [{"id": 1, "name": "Alice Jenkins", "age": 42}]
        res = evaluate_multi_entity_results(conjunction, exec_rows, self.SAMPLE_PATIENTS)
        assert res["found_count"] == 1
        assert res["missing_count"] == 1
        assert "Alice Jenkins" in res["explanation"]
        assert "No matching data was found for Nonexistent B" in res["explanation"]

    def test_case_insensitivity_and_whitespace(self):
        """Case insensitivity: '  aLiCe JeNkInS  '."""
        conjunction = {"operator": "AND", "entity_type": "patient", "entities": ["  aLiCe JeNkInS  ", "karthik raj"]}
        exec_rows = [
            {"id": 1, "name": "Alice Jenkins", "age": 42},
            {"id": 2, "name": "Karthik Raj", "age": 30},
        ]
        res = evaluate_multi_entity_results(conjunction, exec_rows, self.SAMPLE_PATIENTS)
        assert res["found_count"] == 2
        assert res["missing_count"] == 0


# ===========================================================================
# 5. EDGE CASES CONJUNCTION PARSER TESTS
# ===========================================================================

class TestEdgeCasesConjunctionParser:
    """Verify edge-case inputs: repeated keywords, punctuation, various phrasings."""

    def test_repeated_and(self):
        res = extract_entity_conjunctions("patient A and patient B and patient C")
        assert res is not None
        assert len(res["entities"]) == 3

    def test_repeated_or(self):
        res = extract_entity_conjunctions("patient A or patient B or patient C")
        assert res is not None
        assert res["operator"] == "OR"
        assert len(res["entities"]) == 3

    def test_and_and_or_compound(self):
        res = extract_entity_conjunctions("patient A and patient B or patient C")
        assert res is not None
        assert len(res["entities"]) >= 2

    def test_misspelled_entity_in_conjunction(self):
        res = extract_entity_conjunctions("Alice Jenkins and Arjun Kumer")
        assert res is not None
        assert "Alice Jenkins" in res["entities"]
        assert "Arjun Kumer" in res["entities"]

    def test_empty_and_null(self):
        assert extract_entity_conjunctions("") is None
        assert extract_entity_conjunctions("   ") is None
        assert extract_entity_conjunctions(None) is None


# ===========================================================================
# 6. DATABASE EXECUTION TESTS (Using demo_hospital.db)
# ===========================================================================

class TestDatabaseExecutionMultiEntity:
    """Test actual SQLite execution using demo_hospital.db."""

    def setup_method(self, method=None):
        assert HOSPITAL_DB.exists(), f"Hospital DB not found at {HOSPITAL_DB}"
        self.conn = sqlite3.connect(str(HOSPITAL_DB))
        self.conn.row_factory = sqlite3.Row

    def teardown_method(self, method=None):
        if hasattr(self, "conn") and self.conn:
            self.conn.close()

    def test_real_db_multi_patient_lookup(self):
        """Query real database for Alice Jenkins and Karthik Raj."""
        sql = "SELECT id, name, age, diagnosis FROM patients WHERE LOWER(name) IN ('alice jenkins', 'karthik raj');"
        cursor = self.conn.cursor()
        cursor.execute(sql)
        rows = [dict(r) for r in cursor.fetchall()]
        assert len(rows) == 2
        names = {r["name"] for r in rows}
        assert "Alice Jenkins" in names
        assert "Karthik Raj" in names

    def test_real_db_partial_lookup(self):
        """Query real database for Alice Jenkins and Nonexistent Person."""
        sql = "SELECT id, name, age, diagnosis FROM patients WHERE LOWER(name) IN ('alice jenkins', 'nonexistent person');"
        cursor = self.conn.cursor()
        cursor.execute(sql)
        rows = [dict(r) for r in cursor.fetchall()]
        assert len(rows) == 1
        assert rows[0]["name"] == "Alice Jenkins"

    def test_real_db_attribute_filter_still_works(self):
        """Verify normal SQL filtering: patients older than 40 and female."""
        sql = "SELECT id, name, age, gender FROM patients WHERE age > 40 AND gender = 'Female';"
        cursor = self.conn.cursor()
        cursor.execute(sql)
        rows = [dict(r) for r in cursor.fetchall()]
        assert len(rows) > 0
        for r in rows:
            assert r["age"] > 40
            assert r["gender"] == "Female"


if __name__ == "__main__":
    import sys
    test_classes = [
        TestEntityConjunctionExtraction,
        TestFilterConjunctionPreservation,
        TestSQLMutuallyExclusiveFixer,
        TestMultiEntityResultEvaluation,
        TestEdgeCasesConjunctionParser,
        TestDatabaseExecutionMultiEntity,
    ]
    passed = 0
    failed = 0
    print("=" * 70)
    print("RUNNING MULTI-ENTITY AND/OR TEST SUITE")
    print("=" * 70)

    for cls in test_classes:
        instance = cls()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                if hasattr(instance, "setup_method"):
                    instance.setup_method()
                try:
                    getattr(instance, method_name)()
                    print(f"  [PASS] {cls.__name__}.{method_name}")
                    passed += 1
                except Exception as e:
                    print(f"  [FAIL] {cls.__name__}.{method_name}: {e}")
                    failed += 1
                finally:
                    if hasattr(instance, "teardown_method"):
                        instance.teardown_method()

    print("=" * 70)
    print(f"TEST RESULTS: {passed} PASSED, {failed} FAILED")
    print("=" * 70)
    if failed > 0:
        sys.exit(1)
