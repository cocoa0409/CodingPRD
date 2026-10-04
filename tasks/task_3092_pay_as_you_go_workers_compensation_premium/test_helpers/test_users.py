"""Pre-built role headers for every role in the API.

``EmployerAdmin`` is entity-backed: its ``X-User-ID`` is the ``id`` of an actual
``Employer``, and ownership checks compare that identifier to a resource's
``employer_id``. The shared constant below is therefore only safe for requests
that do not exercise ownership; every ownership-gated call must use
``make_employer_admin_headers`` with the real employer's ``id``.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # Named to differ from the filer identities used by dispute/audit fixtures
    # (helpers file with explicit ids like "uw-pat"/"tf-nina"); segregation of
    # duties compares the decider's X-User-ID to the recorded filer.
    "underwriter_headers": build_user_headers("test-underwriter-2", "Underwriter"),
    "payroll_provider_headers": build_user_headers("test-payroll-provider-1", "PayrollProvider"),
    "tax_filer_headers": build_user_headers("test-tax-filer-1", "TaxFiler"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # entity_backed role — the shared constant is a fallback for non-ownership
    # requests only; prefer make_employer_admin_headers(employer["id"]).
    "employer_admin_headers": build_user_headers("test-employer-admin-1", "EmployerAdmin"),
}

# No user context at all — used to exercise the authentication check.
NO_USER_HEADERS: dict = {"Content-Type": "application/json"}


def make_employer_admin_headers(employer_id: str) -> dict:
    """Headers for an EmployerAdmin acting as itself. Pass the real Employer.id
    whenever the call is ownership-gated (paying invoices, filing disputes)."""
    return build_user_headers(employer_id, "EmployerAdmin")


def make_role_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary identity/role pair (e.g., a specific underwriter
    whose X-User-ID must differ from — or equal — a recorded filer)."""
    return build_user_headers(user_id, role)
