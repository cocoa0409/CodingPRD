"""Pre-built role headers for every role in the PRD (section 2.1).

Opaque roles (ClearinghouseOps, Servicer, ResearchAnalyst) have canonical
shared headers. Entity-backed roles (RegistrarSubmitter, RegistrarCertifier,
Requester, Learner) MUST be built per-instance with the backing entity's id
via the make_*_headers builders whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "ops_headers": build_user_headers("ops-1", "ClearinghouseOps"),
    "servicer_headers": build_user_headers("SVC-100", "Servicer"),
    "analyst_headers": build_user_headers("analyst-a", "ResearchAnalyst"),
    # Entity-backed roles: fallback only for non-ownership probes
    # (e.g. 400/404 tests where identity resolution is what matters).
    "submitter_headers": build_user_headers("test-submitter-1", "RegistrarSubmitter"),
    "certifier_headers": build_user_headers("test-certifier-1", "RegistrarCertifier"),
    "requester_headers": build_user_headers("test-requester-1", "Requester"),
    "learner_headers": build_user_headers("test-learner-1", "Learner"),
}


def make_submitter_headers(user_id: str) -> dict:
    """RegistrarSubmitter is entity-backed by InstitutionUser: pass the
    provisioned user's id for any tenancy- or ownership-gated call."""
    return build_user_headers(user_id, "RegistrarSubmitter")


def make_certifier_headers(user_id: str) -> dict:
    """RegistrarCertifier is entity-backed by InstitutionUser: pass the
    provisioned user's id for any tenancy- or ownership-gated call."""
    return build_user_headers(user_id, "RegistrarCertifier")


def make_requester_headers(requester_id: str) -> dict:
    """Requester is entity-backed by Requester: pass the account id."""
    return build_user_headers(requester_id, "Requester")


def make_learner_headers(student_id: str) -> dict:
    """Learner is entity-backed by StudentRecord: pass the student's id."""
    return build_user_headers(student_id, "Learner")


def make_servicer_headers(servicer_ref: str) -> dict:
    """Servicer is opaque, but X-User-ID is compared against servicer_ref."""
    return build_user_headers(servicer_ref, "Servicer")


def make_analyst_headers(analyst_id: str) -> dict:
    """ResearchAnalyst is opaque; listings scope to created_by_analyst_id."""
    return build_user_headers(analyst_id, "ResearchAnalyst")


def make_ops_headers(op_id: str = "ops-1") -> dict:
    """ClearinghouseOps is opaque and never compared against an entity id."""
    return build_user_headers(op_id, "ClearinghouseOps")
