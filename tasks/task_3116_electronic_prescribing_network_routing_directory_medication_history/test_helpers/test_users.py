"""Pre-built role headers for every role in PRD §2.1.

Three roles are entity-backed (`ParticipantAdmin`, `Prescriber`, `Pharmacy`): whenever the
call under test is ownership-gated, the fixture must build headers from the actual entity's
`id` via `make_<role>_headers(entity_id)`. The three opaque roles (`NetworkOperator`,
`HubOperator`, `PatientService`) carry an identifier that is never compared to an entity id,
so the shared constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for opaque roles, and for entity-backed roles only on calls whose
# success does not depend on the caller owning the subject resource.
TEST_USERS = {
    "network_operator_headers": build_user_headers("test-network-operator-1", "NetworkOperator"),
    "participant_admin_headers": build_user_headers("test-participant-admin-1", "ParticipantAdmin"),
    "prescriber_headers": build_user_headers("test-prescriber-1", "Prescriber"),
    "pharmacy_headers": build_user_headers("test-pharmacy-1", "Pharmacy"),
    "hub_operator_headers": build_user_headers("test-hub-operator-1", "HubOperator"),
    "patient_service_headers": build_user_headers("test-patient-service-1", "PatientService"),
}


# ─── Per-instance builders for every entity_backed role ───

def make_participant_admin_headers(participant_id: str) -> dict:
    """For ParticipantAdmin (entity_backed:NetworkParticipant). Pass the administered
    participant's id whenever the call is ownership-gated."""
    return build_user_headers(participant_id, "ParticipantAdmin")


def make_prescriber_headers(participant_id: str) -> dict:
    """For Prescriber (entity_backed:NetworkParticipant). Pass the prescriber clinic
    participant's id whenever the call is ownership-gated."""
    return build_user_headers(participant_id, "Prescriber")


def make_pharmacy_headers(participant_id: str) -> dict:
    """For Pharmacy (entity_backed:NetworkParticipant). Pass the pharmacy participant's id
    whenever the call is ownership-gated."""
    return build_user_headers(participant_id, "Pharmacy")