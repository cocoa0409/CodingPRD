"""Pre-built role headers for every role in the PRD.

`Investor` is entity-backed: `X-User-ID` is the `id` of the acting Investor row
itself, so ownership checks compare it against the resource's `investor_id`,
`seller_id` or `buyer_id`. Every other role is opaque -- `X-User-ID` is an
operator identifier that is never compared to any entity's `id`.

Use `make_investor_headers(investor["id"])` for any call that is ownership
gated; the shared `investor_headers` constant is only safe for calls that do
not exercise ownership (e.g. reading an offering's public sub-resources).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-caller-1", "Anonymous"),
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
    "issuer_ops_headers": build_user_headers("ops-desk-11", "IssuerOps"),
    "compliance_officer_headers": build_user_headers("officer-reyes", "ComplianceOfficer"),
    "transfer_agent_headers": build_user_headers("agent-sable", "TransferAgent"),
    "platform_admin_headers": build_user_headers("admin-root", "PlatformAdmin"),
    "system_headers": build_user_headers("system", "System"),
}


def make_investor_headers(user_id: str) -> dict:
    """For the entity-backed Investor role. Pass the actual Investor.id."""
    return build_user_headers(user_id, "Investor")


def make_issuer_ops_headers(user_id: str = "ops-desk-11") -> dict:
    return build_user_headers(user_id, "IssuerOps")


def make_compliance_officer_headers(user_id: str = "officer-reyes") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_transfer_agent_headers(user_id: str = "agent-sable") -> dict:
    return build_user_headers(user_id, "TransferAgent")


# Header sets used to probe the credential-presence rule.
NO_HEADERS: dict = {}
BLANK_ROLE_HEADERS = {"X-User-ID": "someone", "X-User-Role": ""}
BLANK_ID_HEADERS = {"X-User-ID": "", "X-User-Role": "IssuerOps"}