"""Pre-built role headers for the six declared roles.

Two of the six roles are entity-backed: a MemberOperator's X-User-ID is the
Member row's own id and a DistributorFeed's X-User-ID is the Distributor row's
own id, so calls for those roles must always be built per instance with
make_member_operator_headers(member["id"]) / make_distributor_feed_headers(
distributor["id"]). The other four are opaque user identities.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Distinct opaque user ids per role so that segregation-of-duties tests can
# pick a second actor of the same role who did not originate the record.
GPO_ADMIN_1 = "admin-01"
GPO_ADMIN_2 = "admin-02"
ANALYST_1 = "analyst-01"
ANALYST_2 = "analyst-02"
ARBITER_1 = "arbiter-01"
ARBITER_2 = "arbiter-02"
REP_1 = "rep-01"
REP_2 = "rep-02"


def make_gpo_admin_headers(user_id: str = GPO_ADMIN_1) -> dict:
    return build_user_headers(user_id, Role.GPO_ADMIN.value)


def make_analyst_headers(user_id: str = ANALYST_1) -> dict:
    return build_user_headers(user_id, Role.REBATE_ANALYST.value)


def make_arbiter_headers(user_id: str = ARBITER_1) -> dict:
    return build_user_headers(user_id, Role.DISPUTE_ARBITER.value)


def make_rep_headers(user_id: str = REP_1) -> dict:
    return build_user_headers(user_id, Role.MANUFACTURER_REP.value)


def make_member_operator_headers(member_id: str) -> dict:
    """A MemberOperator caller's X-User-ID is the Member's own id."""
    return build_user_headers(member_id, Role.MEMBER_OPERATOR.value)


def make_distributor_feed_headers(distributor_id: str) -> dict:
    """A DistributorFeed caller's X-User-ID is the Distributor's own id."""
    return build_user_headers(distributor_id, Role.DISTRIBUTOR_FEED.value)


def make_headers(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary role/user pair (role-grid tests)."""
    return build_user_headers(user_id, role)


TEST_USERS = {
    "gpo_admin_headers": make_gpo_admin_headers(),
    "gpo_admin_2_headers": make_gpo_admin_headers(GPO_ADMIN_2),
    "analyst_headers": make_analyst_headers(),
    "analyst_2_headers": make_analyst_headers(ANALYST_2),
    "arbiter_headers": make_arbiter_headers(),
    "arbiter_2_headers": make_arbiter_headers(ARBITER_2),
    "rep_headers": make_rep_headers(),
    "rep_2_headers": make_rep_headers(REP_2),
    # Fallbacks only: never use these for an ownership-scoped call.
    "member_operator_headers": make_member_operator_headers("member-unbound"),
    "distributor_feed_headers": make_distributor_feed_headers("distributor-unbound"),
}

ALL_ROLES = [r.value for r in Role]

OPAQUE_ROLE_USERS = {
    Role.GPO_ADMIN.value: GPO_ADMIN_1,
    Role.REBATE_ANALYST.value: ANALYST_1,
    Role.DISPUTE_ARBITER.value: ARBITER_1,
    Role.MANUFACTURER_REP.value: REP_1,
}
