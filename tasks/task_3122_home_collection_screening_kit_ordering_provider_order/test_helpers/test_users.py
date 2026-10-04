"""Pre-built role headers for every role in the PRD.

The Provider role is entity_backed by the Provider entity: X-User-ID must be
the acting Provider's id for any ownership-aware call. Use
make_provider_headers(provider_id) after creating the Provider. The shared
constant below is a fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import USER_IDS

TEST_USERS = {
    "program_admin_headers": build_user_headers(USER_IDS["PROGRAM_ADMIN"], "ProgramAdmin"),
    # entity_backed:Provider — fallback only for tests that do not exercise ownership.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "fulfillment_agent_headers": build_user_headers(USER_IDS["FULFILLMENT_AGENT"], "FulfillmentAgent"),
    "lab_technician_headers": build_user_headers(USER_IDS["LAB_TECHNICIAN"], "LabTechnician"),
    "navigator_headers": build_user_headers(USER_IDS["NAVIGATOR"], "Navigator"),
}


def make_provider_headers(provider_id: str) -> dict:
    """Provider is entity_backed:Provider — pass the acting Provider's id."""
    return build_user_headers(provider_id, "Provider")
