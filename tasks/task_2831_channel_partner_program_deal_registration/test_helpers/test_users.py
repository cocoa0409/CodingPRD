"""Pre-built role headers for every role the PRD recognises.

Partner is the one role whose ``X-User-ID`` must be a real Partner id: the PRD scopes a
Partner's writes to its own rows, so ownership-gated calls MUST use make_partner_headers()
with the actual Partner id.  The other three roles are opaque staff identities.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.  Safe for the three opaque staff roles, and for Partner-role tests that
# do not depend on the caller owning the subject row (401/403/404 shape checks).
TEST_USERS = {
    "partner_headers": build_user_headers("test-partner-1", "Partner"),
    "channel_ops_analyst_headers": build_user_headers("u_ops_1", "ChannelOpsAnalyst"),
    "channel_ops_analyst_2_headers": build_user_headers("u_ops_2", "ChannelOpsAnalyst"),
    "channel_director_headers": build_user_headers("u_dir_1", "ChannelDirector"),
    "channel_director_2_headers": build_user_headers("u_dir_2", "ChannelDirector"),
    "direct_sales_rep_headers": build_user_headers("u_dsr_1", "DirectSalesRep"),
    "direct_sales_rep_2_headers": build_user_headers("u_dsr_2", "DirectSalesRep"),
}

# Stable opaque staff user ids, so SoD assertions can name the actor that acted.
OPS_ANALYST_USER_ID = "u_ops_1"
OPS_ANALYST_2_USER_ID = "u_ops_2"
DIRECTOR_USER_ID = "u_dir_1"
DIRECTOR_2_USER_ID = "u_dir_2"
DIRECT_SALES_REP_USER_ID = "u_dsr_1"
DIRECT_SALES_REP_2_USER_ID = "u_dsr_2"


def make_partner_headers(user_id: str) -> dict:
    """Headers for the Partner role.  ``user_id`` must be the acting Partner's own id,
    because the PRD resolves the Partner identity from X-User-ID and refuses any write
    aimed at another partner's rows."""
    return build_user_headers(user_id, "Partner")


def make_channel_ops_analyst_headers(user_id: str = OPS_ANALYST_USER_ID) -> dict:
    """Headers for the ChannelOpsAnalyst role (opaque identity)."""
    return build_user_headers(user_id, "ChannelOpsAnalyst")


def make_channel_director_headers(user_id: str = DIRECTOR_USER_ID) -> dict:
    """Headers for the ChannelDirector role (opaque identity)."""
    return build_user_headers(user_id, "ChannelDirector")


def make_direct_sales_rep_headers(user_id: str = DIRECT_SALES_REP_USER_ID) -> dict:
    """Headers for the DirectSalesRep role (opaque identity)."""
    return build_user_headers(user_id, "DirectSalesRep")


ANALYST = TEST_USERS["channel_ops_analyst_headers"]
ANALYST_2 = TEST_USERS["channel_ops_analyst_2_headers"]
DIRECTOR = TEST_USERS["channel_director_headers"]
DIRECTOR_2 = TEST_USERS["channel_director_2_headers"]
DIRECT_REP = TEST_USERS["direct_sales_rep_headers"]
DIRECT_REP_2 = TEST_USERS["direct_sales_rep_2_headers"]
