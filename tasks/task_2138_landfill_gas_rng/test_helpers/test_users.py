"""Pre-built role headers for every role in the PRD.

Five roles carry an opaque identity (ProjectAdmin, WellfieldTechnician,
PlantOperator, CommercialScheduler, ComplianceOfficer) — the shared constant is
the canonical form for those.

Two roles are entity-backed and their identity is load-bearing:
`HostRepresentative` carries the acting LandfillSite's own `id`, and `Offtaker`
carries the acting OfftakeContract's own `id`. Ownership-gated calls MUST use
the per-instance builders below with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Two distinct compliance officers: segregation of duties is enforced against
# prepared_by_user_id and reviewed_by_user_id, so an officer who prepared a
# filing can never be the one who reviews it.
OFFICER_ALICE = "officer-alice"
OFFICER_BOB = "officer-bob"
OFFICER_CAROL = "officer-carol"


TEST_USERS = {
    # Opaque identities — the shared constant is the canonical form.
    "project_admin_headers": build_user_headers("admin-1", "ProjectAdmin"),
    "wellfield_technician_headers": build_user_headers("tech-1", "WellfieldTechnician"),
    "plant_operator_headers": build_user_headers("operator-1", "PlantOperator"),
    "commercial_scheduler_headers": build_user_headers(
        "scheduler-1", "CommercialScheduler"
    ),
    "compliance_officer_headers": build_user_headers(OFFICER_ALICE, "ComplianceOfficer"),
    # Entity-backed identities — these shared constants are only safe for tests
    # that never reach an ownership check (for example a 403 role check or a
    # 404 on a missing resource).
    "host_representative_headers": build_user_headers(
        "host-not-a-site", "HostRepresentative"
    ),
    "offtaker_headers": build_user_headers("offtaker-not-a-contract", "Offtaker"),
}


# ─── Per-instance builders ────────────────────────────

def make_project_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "ProjectAdmin")


def make_wellfield_technician_headers(user_id: str = "tech-1") -> dict:
    return build_user_headers(user_id, "WellfieldTechnician")


def make_plant_operator_headers(user_id: str = "operator-1") -> dict:
    return build_user_headers(user_id, "PlantOperator")


def make_commercial_scheduler_headers(user_id: str = "scheduler-1") -> dict:
    return build_user_headers(user_id, "CommercialScheduler")


def make_compliance_officer_headers(user_id: str = OFFICER_ALICE) -> dict:
    """The identifier is recorded as prepared_by_user_id / reviewed_by_user_id,
    so pass a distinct value for the preparer and the reviewer."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_host_representative_headers(site_id: str) -> dict:
    """For HostRepresentative: X-User-ID is the id of the acting LandfillSite.
    Pass the real site id whenever the call is ownership-gated."""
    return build_user_headers(site_id, "HostRepresentative")


def make_offtaker_headers(contract_id: str) -> dict:
    """For Offtaker: X-User-ID is the id of the acting OfftakeContract.
    Pass the real contract id whenever the call is ownership-gated."""
    return build_user_headers(contract_id, "Offtaker")


def no_auth_headers() -> dict:
    """A request carrying neither X-User-ID nor X-User-Role."""
    return {"Content-Type": "application/json"}
