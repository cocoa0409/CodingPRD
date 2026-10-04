"""Pre-built role headers for every role in the PRD (§2.1).

All six roles carry an OPAQUE ``X-User-ID`` string — never an entity id.
Ownership for ``RegistrantRepresentative`` resolves by comparing the header's
``X-User-ID`` to the owning product's ``registrant_ref`` (stamped from the
same header at product creation), so distinct owners simply use distinct
user-id strings.

Segregation of duties (PRD §1 intro, §3.4, §3.8) compares user-id STRINGS
across role hats:
  * application approver (RegistrationReviewer) vs the latest risk
    assessment's assessor (RiskAssessor) — a violation is staged by having
    the SAME user id act under both hats;
  * proceeding order issuer vs the proceeding's initiator (both
    RegistrationReviewer) — staged with two reviewer ids, violated with one.
Use the ``make_*_headers`` builders to mint fresh ids per test.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical user-id strings (also used by the difficulty fixtures' recipes).
ADMIN_USER_ID = "sys-admin-1"
REGISTRANT_ALICE_ID = "reg-alice"
REGISTRANT_BOB_ID = "reg-bob"
REVIEWER_1_ID = "rr-1"
REVIEWER_2_ID = "rr-2"
ASSESSOR_1_ID = "ra-1"
ASSESSOR_2_ID = "ra-2"
STATE_AGENCY_ID = "sla-1"
CERT_AUTHORITY_ID = "ca-1"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "SystemAdministrator"),
    "registrant_alice_headers": build_user_headers(
        REGISTRANT_ALICE_ID, "RegistrantRepresentative"),
    "registrant_bob_headers": build_user_headers(
        REGISTRANT_BOB_ID, "RegistrantRepresentative"),
    "reviewer_1_headers": build_user_headers(REVIEWER_1_ID, "RegistrationReviewer"),
    "reviewer_2_headers": build_user_headers(REVIEWER_2_ID, "RegistrationReviewer"),
    "assessor_1_headers": build_user_headers(ASSESSOR_1_ID, "RiskAssessor"),
    "assessor_2_headers": build_user_headers(ASSESSOR_2_ID, "RiskAssessor"),
    "state_agency_headers": build_user_headers(STATE_AGENCY_ID, "StateLeadAgency"),
    "certification_authority_headers": build_user_headers(
        CERT_AUTHORITY_ID, "CertificationAuthority"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — use these whenever a test needs a fresh identity
# (ownership isolation, SoD staging, or multi-registrant scenarios).
# ---------------------------------------------------------------------------
def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "SystemAdministrator")


def make_registrant_headers(user_id: str) -> dict:
    """RegistrantRepresentative headers; the product's registrant_ref equals
    this user_id, so ownership-gated calls must reuse the same id."""
    return build_user_headers(user_id, "RegistrantRepresentative")


def make_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegistrationReviewer")


def make_assessor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RiskAssessor")


def make_state_agency_headers(user_id: str = STATE_AGENCY_ID) -> dict:
    return build_user_headers(user_id, "StateLeadAgency")


def make_certification_authority_headers(user_id: str = CERT_AUTHORITY_ID) -> dict:
    return build_user_headers(user_id, "CertificationAuthority")


def user_id_of(headers: dict) -> str:
    """Extract the X-User-ID from a headers dict built here."""
    return headers["X-User-ID"]
