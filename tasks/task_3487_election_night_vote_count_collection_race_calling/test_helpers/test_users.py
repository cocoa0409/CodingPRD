"""Pre-built role headers for every role in the PRD (§2.1).

Two kinds of entries:

- Shared constants in TEST_USERS — safe for opaque roles, and for calls whose
  success does not depend on the caller owning the subject resource.
- Per-instance builders make_<role>_headers(user_id) — MANDATORY for the two
  entity-backed roles: for Stringer, X-User-ID must equal the acting
  Stringer's id; for MediaCustomer, the acting MediaCustomer's id. Fixtures
  MUST call these builders with the real entity id on ownership-gated calls
  (check-in, stringer-authored reports and resubmits, customer self-reads).

The opaque builders also matter for segregation of duties: publishing a call
with the SAME operator id that proposed it (e.g. make_chief_headers
("analyst-nina")) is the canonical ERR_SEGREGATION_OF_DUTIES setup.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids referenced across the suite (opaque identities the
# server records as proposed_by / published_by).
ADMIN_ID = "admin-olivia"
PLANNER_ID = "planner-pat"
COORDINATOR_ID = "coordinator-cory"
FEED_OPERATOR_ID = "feed-op-fiona"
CLERK_ID = "clerk-carol"
ANALYST_NINA_ID = "analyst-nina"
ANALYST_KIM_ID = "analyst-kim"
CHIEF_RAY_ID = "chief-ray"
RECOUNT_OFFICER_ID = "officer-renee"


TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers(ADMIN_ID, "ElectionOpsAdmin"),
    "planner_headers": build_user_headers(PLANNER_ID, "CoveragePlanner"),
    "coordinator_headers": build_user_headers(COORDINATOR_ID, "StringerCoordinator"),
    "feed_operator_headers": build_user_headers(FEED_OPERATOR_ID, "FeedOperator"),
    "clerk_headers": build_user_headers(CLERK_ID, "TabulationClerk"),
    "analyst_headers": build_user_headers(ANALYST_NINA_ID, "DecisionAnalyst"),
    "analyst_kim_headers": build_user_headers(ANALYST_KIM_ID, "DecisionAnalyst"),
    "chief_headers": build_user_headers(CHIEF_RAY_ID, "DecisionDeskChief"),
    "recount_officer_headers": build_user_headers(RECOUNT_OFFICER_ID, "RecountOfficer"),
    # Entity-backed roles: shared constants are a FALLBACK for non-ownership
    # calls only (role-denial probes, payload-shape probes). Never use them
    # where X-User-ID must equal a real entity id.
    "stringer_headers": build_user_headers("test-stringer-1", "Stringer"),
    "customer_headers": build_user_headers("test-customer-1", "MediaCustomer"),
}


def make_admin_headers(user_id: str = ADMIN_ID) -> dict:
    return build_user_headers(user_id, "ElectionOpsAdmin")


def make_planner_headers(user_id: str = PLANNER_ID) -> dict:
    return build_user_headers(user_id, "CoveragePlanner")


def make_coordinator_headers(user_id: str = COORDINATOR_ID) -> dict:
    return build_user_headers(user_id, "StringerCoordinator")


def make_stringer_headers(user_id: str) -> dict:
    """Stringer is entity-backed: pass the acting Stringer's id whenever the
    call is ownership-gated (check-in, STRINGER reports, own-report resubmit)."""
    return build_user_headers(user_id, "Stringer")


def make_feed_operator_headers(user_id: str = FEED_OPERATOR_ID) -> dict:
    return build_user_headers(user_id, "FeedOperator")


def make_clerk_headers(user_id: str = CLERK_ID) -> dict:
    return build_user_headers(user_id, "TabulationClerk")


def make_analyst_headers(user_id: str = ANALYST_NINA_ID) -> dict:
    return build_user_headers(user_id, "DecisionAnalyst")


def make_chief_headers(user_id: str = CHIEF_RAY_ID) -> dict:
    """DecisionDeskChief. Pass the proposer's operator id here to exercise the
    segregation-of-duties rejection."""
    return build_user_headers(user_id, "DecisionDeskChief")


def make_recount_officer_headers(user_id: str = RECOUNT_OFFICER_ID) -> dict:
    return build_user_headers(user_id, "RecountOfficer")


def make_customer_headers(user_id: str) -> dict:
    """MediaCustomer is entity-backed: pass the acting MediaCustomer's id for
    self-reads, delivery feeds, and invoice operations."""
    return build_user_headers(user_id, "MediaCustomer")
