"""Pre-built role headers for every role in the PRD.

Shared constants in TEST_USERS are safe for opaque roles (PlatformAdmin,
ProgramManager, System, Anonymous) and for any test whose outcome does not
depend on the caller owning a persisted entity.

Entity-backed roles (Inspector, MedicalDirector, Responder) bind X-User-ID to
a persisted Responder record's id, so per-instance builders are mandatory for
ownership-gated calls: always build headers with the actual responder id.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "program_manager_headers": build_user_headers("test-pm-1", "ProgramManager"),
    "system_headers": build_user_headers("test-system-1", "System"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "medical_director_headers": build_user_headers("test-md-1", "MedicalDirector"),
    "responder_headers": build_user_headers("test-responder-1", "Responder"),
}


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity-backed by Responder). Pass the actual Responder.id
    whenever the call is identity- or ownership-gated (e.g. submitting an
    inspection whose inspector_id must match the caller)."""
    return build_user_headers(user_id, "Inspector")


def make_medical_director_headers(user_id: str) -> dict:
    """For MedicalDirector (entity-backed by Responder). Pass the actual
    Responder.id whenever the call is identity-gated (case-review create,
    submit, accept, reopen all compare reviewer identity to the caller)."""
    return build_user_headers(user_id, "MedicalDirector")


def make_responder_headers(user_id: str) -> dict:
    """For Responder (entity-backed by Responder). Pass the actual Responder.id
    whenever the call is identity-gated (acknowledge/resolve/close_no_patient
    verify the caller is a specific certified responder)."""
    return build_user_headers(user_id, "Responder")
