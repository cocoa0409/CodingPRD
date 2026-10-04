"""Pre-built role headers for every role the API recognises.

`Candidate` and `Employer` are entity-backed roles: their X-User-ID must be the
id of an existing Nurse / Employer row, so any ownership-gated call MUST use
`make_candidate_headers(nurse_id)` / `make_employer_headers(employer_id)` with
that row's id.  `PlatformAdmin` is an opaque role; its shared constant is the
canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is canonical.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # Entity-backed roles: fallback only for calls that are not ownership-gated
    # (e.g. Candidate self-registration via POST /marketplace/nurses).
    "candidate_headers": build_user_headers("test-candidate-unbound", "Candidate"),
    "employer_headers": build_user_headers("test-employer-unbound", "Employer"),
}

ADMIN = TEST_USERS["platform_admin_headers"]


def make_candidate_headers(nurse_id: str) -> dict:
    """Headers for the `Candidate` role acting as the nurse whose id is `nurse_id`.

    A Candidate's X-User-ID is matched against the Nurse row's `id`, so any
    ownership-gated call (submit, deactivate, review, accept, ...) must pass
    the actual nurse id here.
    """
    return build_user_headers(nurse_id, "Candidate")


def make_employer_headers(employer_id: str) -> dict:
    """Headers for the `Employer` role acting as the employer whose id is
    `employer_id`.

    An Employer's X-User-ID is matched against the Employer row's `id`, so any
    ownership-gated call (requisition writes, applications, offers, ...) must
    pass the actual employer id here.
    """
    return build_user_headers(employer_id, "Employer")
