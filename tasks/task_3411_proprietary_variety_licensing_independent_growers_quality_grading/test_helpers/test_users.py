"""Pre-built role headers for every role in the PRD (8 roles).

GrowerPrincipal is entity-backed: its X-User-ID must equal the acting Grower's id
on every ownership-gated call. Use make_grower_principal_headers(grower["id"]) —
never the shared constant — for any call that touches a grower-owned resource.

Grading is four-eyes: the certifier's X-User-ID must differ from both the lot's
submitted_by_user_id and received_by_user_id. The canonical ids below
(GRADER_SUBMITTER / GRADER_CERTIFIER / GRADER_THIRD / COOLING_OP_1) are mutually
distinct so the segregation rule passes on the happy path and is easy to violate
on purpose in negative tests.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator ids (segregation-of-duties participants)
COOLING_OP_1 = "co-1"
GRADER_SUBMITTER = "qg-1"
GRADER_CERTIFIER = "qg-2"
GRADER_THIRD = "qg-3"

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400/404 probes, role denials). The grower_principal entry is a
# fallback for non-ownership tests ONLY.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "breeding_manager_headers": build_user_headers("test-breeder-1", "BreedingManager"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "nursery_manager_headers": build_user_headers("test-nursery-1", "NurseryManager"),
    "grower_principal_headers": build_user_headers("test-grower-1", "GrowerPrincipal"),
    "cooling_operator_headers": build_user_headers(COOLING_OP_1, "CoolingOperator"),
    "quality_grader_headers": build_user_headers(GRADER_SUBMITTER, "QualityGrader"),
    "settlement_officer_headers": build_user_headers("test-settlement-1", "SettlementOfficer"),
}


def make_grower_principal_headers(user_id: str) -> dict:
    """GrowerPrincipal is entity_backed:Grower. Pass the actual Grower.id as
    user_id whenever the call is ownership-gated (agreement apply, planting
    create/confirm/complete, harvest-lot create, grade dispute, statement
    dispute)."""
    return build_user_headers(user_id, "GrowerPrincipal")


def make_quality_grader_headers(user_id: str) -> dict:
    """QualityGrader with a specific operator id — required to control the
    segregation-of-duties axis (certifier != submitter != receiver)."""
    return build_user_headers(user_id, "QualityGrader")


def make_cooling_operator_headers(user_id: str) -> dict:
    """CoolingOperator with a specific operator id; the receiver's id is recorded
    on the lot and participates in segregation of duties at certify time."""
    return build_user_headers(user_id, "CoolingOperator")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_breeding_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BreedingManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_nursery_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NurseryManager")


def make_settlement_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SettlementOfficer")
