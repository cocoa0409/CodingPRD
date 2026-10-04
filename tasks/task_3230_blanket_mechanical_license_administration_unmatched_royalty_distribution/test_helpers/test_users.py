"""Pre-built role headers for every role in the PRD.

ServiceProviderUser and MemberUser are entity-backed roles: for any
ownership-gated call, callers MUST build headers with the actual entity id
via the make_* builders below. The shared constants are safe only for
opaque roles or for tests that never exercise ownership (400/404 paths).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles: shared constant is canonical
    "admin_headers": build_user_headers("admin-op-1", "MLCAdministrator"),
    "admin2_headers": build_user_headers("admin-op-2", "MLCAdministrator"),
    "public_headers": build_user_headers("public-searcher-1", "PublicSearcher"),
    # entity-backed roles: fallback for non-ownership tests only
    "dsp_user_headers": build_user_headers("test-dsp-user-1", "ServiceProviderUser"),
    "member_user_headers": build_user_headers("test-member-user-1", "MemberUser"),
}


def make_admin_headers(user_id: str = "admin-op-1") -> dict:
    """MLCAdministrator is opaque; any distinct id is a distinct operator."""
    return build_user_headers(user_id, "MLCAdministrator")


def make_dsp_headers(service_provider_id: str) -> dict:
    """ServiceProviderUser (entity_backed:ServiceProvider). Pass the actual
    ServiceProvider.id whenever the call is ownership-gated (report
    create/line-add/submit/reopen, report and audit reads under the DSP)."""
    return build_user_headers(service_provider_id, "ServiceProviderUser")


def make_member_headers(member_id: str) -> dict:
    """MemberUser (entity_backed:Member). Pass the actual Member.id whenever
    the call is ownership-gated (claim create/withdraw, audit open/findings/
    withdraw, member-scoped statement/payee reads)."""
    return build_user_headers(member_id, "MemberUser")


def make_public_headers(user_id: str = "public-searcher-1") -> dict:
    """PublicSearcher is opaque; read-only on the public search surface."""
    return build_user_headers(user_id, "PublicSearcher")
