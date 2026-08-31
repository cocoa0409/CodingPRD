"""Pre-built role headers for every role in the PRD (§2.1).

Four roles carry an opaque operator identifier that the server never resolves
against any entity table — PlatformAdmin, CaseManager, UtilizationReviewNurse and
DischargeCoordinator — so a shared constant is the canonical form for them, and
the `make_*` builders exist only so that the four-eyes controls of §2.10 can be
driven with two distinguishable operators.

Two roles are entity-backed and MUST use their per-instance builder:
  * PayerRepresentative — X-User-ID is the id of the acting Payer.
  * PostAcuteLiaison    — X-User-ID is the id of the acting PostAcuteProvider.
Falling back to the shared constant for those two makes every ownership check
reject every request.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers used throughout the fixtures.
CM_ALPHA_ID = "cm-alpha"
CM_GAMMA_ID = "cm-gamma"
UR_BETA_ID = "ur-beta"
UR_DELTA_ID = "ur-delta"
DC_ALPHA_ID = "dc-alpha"
DC_BETA_ID = "dc-beta"
ADMIN_ID = "admin-root"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(ADMIN_ID, "PlatformAdmin"),
    "case_manager_headers": build_user_headers(CM_ALPHA_ID, "CaseManager"),
    "second_case_manager_headers": build_user_headers(CM_GAMMA_ID, "CaseManager"),
    "utilization_review_nurse_headers": build_user_headers(
        UR_BETA_ID, "UtilizationReviewNurse"
    ),
    "second_utilization_review_nurse_headers": build_user_headers(
        UR_DELTA_ID, "UtilizationReviewNurse"
    ),
    "discharge_coordinator_headers": build_user_headers(
        DC_ALPHA_ID, "DischargeCoordinator"
    ),
    "second_discharge_coordinator_headers": build_user_headers(
        DC_BETA_ID, "DischargeCoordinator"
    ),
    # Entity-backed roles: these shared constants are safe ONLY for tests that
    # never reach an ownership check (role-level 403s, unknown-id 404s).
    "payer_representative_headers": build_user_headers(
        "test-payer-rep-1", "PayerRepresentative"
    ),
    "post_acute_liaison_headers": build_user_headers(
        "test-liaison-1", "PostAcuteLiaison"
    ),
}

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]
SECOND_CASE_MANAGER = TEST_USERS["second_case_manager_headers"]
UR_NURSE = TEST_USERS["utilization_review_nurse_headers"]
SECOND_UR_NURSE = TEST_USERS["second_utilization_review_nurse_headers"]
DISCHARGE_COORDINATOR = TEST_USERS["discharge_coordinator_headers"]
SECOND_DISCHARGE_COORDINATOR = TEST_USERS["second_discharge_coordinator_headers"]


def make_payer_rep_headers(payer_id: str) -> dict:
    """PayerRepresentative headers. X-User-ID is the id of the acting Payer, so
    every authorization decision must pass the real payer id."""
    return build_user_headers(payer_id, "PayerRepresentative")


def make_liaison_headers(provider_id: str) -> dict:
    """PostAcuteLiaison headers. X-User-ID is the id of the acting
    PostAcuteProvider, so bed-offer creation and offer withdrawal must pass the
    real provider id."""
    return build_user_headers(provider_id, "PostAcuteLiaison")


def make_case_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CaseManager")


def make_ur_nurse_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UtilizationReviewNurse")


def make_discharge_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DischargeCoordinator")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
