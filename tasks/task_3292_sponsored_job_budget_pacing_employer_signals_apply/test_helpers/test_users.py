"""Role headers for every role the service recognises.

`PlatformAdmin` and `TrustReviewer` are opaque identities: the server records the
supplied id but never matches it against a persisted entity, so the shared
constants below are safe for every call those roles make.

`Employer` and `JobSeeker` are entity-backed: ownership checks compare the
resource's employer/seeker foreign key to `X-User-ID`. Any ownership-gated call
MUST therefore use `make_employer_headers(<employer.id>)` or
`make_seeker_headers(<seeker.id>)` with the real entity id; the shared constants
exist only for calls that are not ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque role — canonical shared constant.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # Opaque role — canonical shared constant.
    "trust_headers": build_user_headers("test-trust-1", "TrustReviewer"),
    # entity_backed:Employer — fallback for non-ownership-gated calls only.
    "employer_headers": build_user_headers("employer-string-id", "Employer"),
    # entity_backed:JobSeeker — fallback for non-ownership-gated calls only.
    "seeker_headers": build_user_headers("seeker-string-id", "JobSeeker"),
}


def make_employer_headers(user_id: str) -> dict:
    """Headers for an Employer acting as the employer whose id is `user_id`.

    Pass the owning `Employer.id` for any ownership-gated call (campaigns,
    sponsored jobs, postings, assessments, dispositions, resumes, holds).
    """
    return build_user_headers(user_id, "Employer")


def make_seeker_headers(user_id: str) -> dict:
    """Headers for a JobSeeker acting as the seeker whose id is `user_id`.

    Pass the `JobSeeker.id` for any ownership-gated call (applications,
    alert subscriptions, matches).
    """
    return build_user_headers(user_id, "JobSeeker")


# Role name constants for parametrized RBAC tests.
ROLE_ADMIN = "PlatformAdmin"
ROLE_TRUST = "TrustReviewer"
ROLE_EMPLOYER = "Employer"
ROLE_SEEKER = "JobSeeker"