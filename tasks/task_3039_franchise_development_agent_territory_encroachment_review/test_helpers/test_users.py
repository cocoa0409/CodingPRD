"""Pre-built role headers for every role in the PRD (PRD §2.1).

DevelopmentAgent and Franchisee are entity-backed roles: X-User-ID must equal
the acting DevelopmentAgent/Franchisee record's id. Use make_*_headers(id)
whenever the call is ownership-gated; the shared constants are only safe for
tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "franchisor_ops_headers": build_user_headers("franchisor-ops-1", "FranchisorOps"),
    # Entity-backed role: fallback constant for non-ownership tests only.
    "development_agent_headers": build_user_headers("test-agent-1", "DevelopmentAgent"),
    # Entity-backed role: fallback constant for non-ownership tests only.
    "franchisee_headers": build_user_headers("test-franchisee-1", "Franchisee"),
    "mediator_headers": build_user_headers("mediator-1", "Mediator"),
    "inspector_headers": build_user_headers("inspector-1", "Inspector"),
}


def make_development_agent_headers(agent_id: str) -> dict:
    """DevelopmentAgent is entity-backed: pass the actual DevelopmentAgent.id
    whenever the call checks territory assignment."""
    return build_user_headers(agent_id, "DevelopmentAgent")


def make_franchisee_headers(franchisee_id: str) -> dict:
    """Franchisee is entity-backed: pass the actual Franchisee.id whenever the
    call checks store/protest/dispute ownership."""
    return build_user_headers(franchisee_id, "Franchisee")


def make_mediator_headers(mediator_ref: str) -> dict:
    """Mediator is opaque, but segregation of duties compares X-User-ID to the
    protest's mediator_ref; pass the recorded mediator_ref."""
    return build_user_headers(mediator_ref, "Mediator")


def make_inspector_headers(inspector_ref: str) -> dict:
    """Inspector is opaque, but segregation of duties compares X-User-ID to the
    inspection's inspector_ref; pass the recorded inspector_ref."""
    return build_user_headers(inspector_ref, "Inspector")
