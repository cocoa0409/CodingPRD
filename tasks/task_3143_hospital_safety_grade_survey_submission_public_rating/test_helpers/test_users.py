"""Pre-built role headers for every role in the PRD.

Two things are emitted per role:

- a shared-constant entry in ``TEST_USERS``, safe for opaque roles and for
  ownership-independent calls; and
- a per-instance builder for the roles whose identity is an entity, so the
  ``X-User-ID`` used on an ownership-gated call is the real entity's ``id``.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
TEST_USERS = {
    # RatingAdmin — opaque operator identifier.
    "rating_admin_headers": build_user_headers("test-rating-admin-1", "RatingAdmin"),
    # VerificationAnalyst — opaque operator identifier.
    "analyst_headers": build_user_headers("va-owen", "VerificationAnalyst"),
    # RatingEngine — opaque operator identifier.
    "engine_headers": build_user_headers("re-cara", "RatingEngine"),
    # AnyAuthenticated readership — opaque identifier.
    "reader_headers": build_user_headers("pa-lin", "AnyAuthenticated"),
    # HospitalRespondent — entity-backed; the shared constant is a fallback for
    # calls that do not exercise ownership.
    "respondent_headers": build_user_headers("test-respondent-1", "HospitalRespondent"),
    # PurchaserAdmin — entity-backed; the shared constant is a fallback for
    # calls that do not exercise ownership.
    "purchaser_headers": build_user_headers("test-purchaser-1", "PurchaserAdmin"),
}


def make_respondent_headers(hospital_id: str) -> dict:
    """Headers for HospitalRespondent acting as the given Hospital.

    Pass the real ``Hospital.id`` whenever the call is ownership-gated.
    """
    return build_user_headers(hospital_id, "HospitalRespondent")


def make_purchaser_headers(employer_id: str) -> dict:
    """Headers for PurchaserAdmin acting as the given Employer.

    Pass the real ``Employer.id`` whenever the call is ownership-gated.
    """
    return build_user_headers(employer_id, "PurchaserAdmin")


def anonymous_headers() -> dict:
    """Headers with no identity, for the missing-context tier."""
    return {"Content-Type": "application/json"}


def headers_for(role: str, user_id: str = "test-operator-1") -> dict:
    """Headers for an arbitrary role name and operator id."""
    return build_user_headers(user_id, role)