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


class TestMultiTableDisambiguation:
    """Tests for person names existing in both doctors and patients tables (James Wilson)."""

    def test_patient_explicit_mention(self, client, hospital_sid):
        """When user mentions 'patient James Wilson', query MUST return patient record, NOT doctor."""
        conv_id = str(uuid.uuid4())
        resp = _query(client, hospital_sid, "show details of patient James Wilson", conversation_id=conv_id)
        assert resp.status_code == 200
        data = resp.json()

        assert data["needs_clarification"] is False
        assert data["sql"] is not None
        assert "patients" in data["sql"].lower()
        assert "doctors" not in data["sql"].lower()
        assert len(data["result"]) > 0
        # Patient 12 diagnosis is Chronic Kidney Disease
        res_str = str(data["result"])
        assert "Chronic Kidney Disease" in res_str or "James Wilson" in res_str
        # Doctor specialty Oncology should NOT be in result
        assert "Oncology" not in res_str

    def test_doctor_explicit_mention(self, client, hospital_sid):
        """When user mentions 'doctor James Wilson', query MUST return doctor record."""
        conv_id = str(uuid.uuid4())
        resp = _query(client, hospital_sid, "show details of doctor James Wilson", conversation_id=conv_id)
        assert resp.status_code == 200
        data = resp.json()

        assert data["needs_clarification"] is False
        assert data["sql"] is not None
        assert "doctors" in data["sql"].lower()
        assert len(data["result"]) > 0
        res_str = str(data["result"])
        assert "Oncology" in res_str

    def test_ambiguous_name_asks_clarification(self, client, hospital_sid):
        """When user asks for 'James Wilson' without specifying role, system MUST ask for clarification."""
        conv_id = str(uuid.uuid4())
        resp = _query(client, hospital_sid, "show details of James Wilson", conversation_id=conv_id)
        assert resp.status_code == 200
        data = resp.json()

        assert data["needs_clarification"] is True
        assert data["sql"] is None
        assert "clarification_question" in data
        cq = data["clarification_question"].lower()
        assert "doctor" in cq and "patient" in cq

    def test_clarification_followup_patient(self, client, hospital_sid):
        """User asks for 'James Wilson', gets clarification, then replies 'patient' -> returns patient data."""
        conv_id = str(uuid.uuid4())

        # Step 1: Initial query
        resp1 = _query(client, hospital_sid, "show details of James Wilson", conversation_id=conv_id)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["needs_clarification"] is True

        # Step 2: Follow-up clarifying 'patient'
        resp2 = _query(client, hospital_sid, "patient", conversation_id=conv_id)
        assert resp2.status_code == 200
        data2 = resp2.json()

        assert data2["needs_clarification"] is False
        assert data2["sql"] is not None
        assert "patients" in data2["sql"].lower()
        assert len(data2["result"]) > 0
        res_str = str(data2["result"])
        assert "Chronic Kidney Disease" in res_str

    def test_clarification_followup_doctor(self, client, hospital_sid):
        """User asks for 'James Wilson', gets clarification, then replies 'doctor' -> returns doctor data."""
        conv_id = str(uuid.uuid4())

        # Step 1: Initial query
        resp1 = _query(client, hospital_sid, "show details of James Wilson", conversation_id=conv_id)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["needs_clarification"] is True

        # Step 2: Follow-up clarifying 'doctor'
        resp2 = _query(client, hospital_sid, "doctor", conversation_id=conv_id)
        assert resp2.status_code == 200
        data2 = resp2.json()

        assert data2["needs_clarification"] is False
        assert data2["sql"] is not None
        assert "doctors" in data2["sql"].lower()
        assert len(data2["result"]) > 0
        res_str = str(data2["result"])
        assert "Oncology" in res_str
