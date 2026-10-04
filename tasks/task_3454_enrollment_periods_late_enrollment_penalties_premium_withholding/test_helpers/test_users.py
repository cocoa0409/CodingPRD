"""Caller identities.

PRD section 2.1 splits identity in two.  For ``FieldOfficer``,
``AppealsOfficer``, ``IrsDataAgent`` and ``BenefitAdministrator`` the
``X-User-ID`` is an opaque operator identifier that the server records in
audit fields but never compares against an entity ``id``; for ``Beneficiary``
the ``X-User-ID`` *is* the ``id`` of the acting Beneficiary record, which is
what every ownership check compares against.  Operator headers are therefore
constants, while a beneficiary's headers can only be built once the
beneficiary row exists - call ``make_beneficiary_headers(beneficiary["id"])``
for any ownership-gated call.

Segregation of duties (PRD section 3.6) needs the determination author's id
and the adjudicator's id to be distinct operator ids, and needs to be able to
cross-wire them: the same human id behind both roles must be rejected with
ERR_SOD_SAME_ACTOR.  Hence the fixed ``fo-100`` / ``ao-200`` pair and the
per-instance builders.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_APPEALS_OFFICER,
    ROLE_BENEFICIARY,
    ROLE_BENEFIT_ADMINISTRATOR,
    ROLE_FIELD_OFFICER,
    ROLE_IRS_DATA_AGENT,
)

# --- Opaque operator identifiers ------------------------------------------------

FIELD_OFFICER_USER_ID = "fo-100"
FIELD_OFFICER_2_USER_ID = "fo-101"
APPEALS_OFFICER_USER_ID = "ao-200"
APPEALS_OFFICER_2_USER_ID = "ao-201"
IRS_DATA_AGENT_USER_ID = "irs-300"
BENEFIT_ADMINISTRATOR_USER_ID = "ba-400"

# --- Ready-made operator header sets ----------------------------------------------

FIELD_OFFICER_HEADERS = build_user_headers(FIELD_OFFICER_USER_ID, ROLE_FIELD_OFFICER)
FIELD_OFFICER_2_HEADERS = build_user_headers(FIELD_OFFICER_2_USER_ID, ROLE_FIELD_OFFICER)
APPEALS_OFFICER_HEADERS = build_user_headers(APPEALS_OFFICER_USER_ID, ROLE_APPEALS_OFFICER)
APPEALS_OFFICER_2_HEADERS = build_user_headers(
    APPEALS_OFFICER_2_USER_ID, ROLE_APPEALS_OFFICER
)
IRS_DATA_AGENT_HEADERS = build_user_headers(IRS_DATA_AGENT_USER_ID, ROLE_IRS_DATA_AGENT)
BENEFIT_ADMINISTRATOR_HEADERS = build_user_headers(
    BENEFIT_ADMINISTRATOR_USER_ID, ROLE_BENEFIT_ADMINISTRATOR
)

# Shared-constant map.  The Beneficiary entry is a FALLBACK for calls whose
# outcome does not depend on owning the subject resource (malformed-payload
# 400s, missing-resource 404s); any ownership-gated call must use
# make_beneficiary_headers with the real Beneficiary id instead.
TEST_USERS = {
    "beneficiary_headers": build_user_headers("test-beneficiary-1", ROLE_BENEFICIARY),
    "field_officer_headers": FIELD_OFFICER_HEADERS,
    "appeals_officer_headers": APPEALS_OFFICER_HEADERS,
    "irs_data_agent_headers": IRS_DATA_AGENT_HEADERS,
    "benefit_administrator_headers": BENEFIT_ADMINISTRATOR_HEADERS,
}


# --- Per-instance builders ----------------------------------------------------------


def make_beneficiary_headers(beneficiary_id):
    """Headers for the Beneficiary caller who IS this Beneficiary row.

    Mandatory for every ownership-gated call: the server compares the
    resource's beneficiary_id to X-User-ID.
    """
    return build_user_headers(beneficiary_id, ROLE_BENEFICIARY)


def make_field_officer_headers(user_id):
    return build_user_headers(user_id, ROLE_FIELD_OFFICER)


def make_appeals_officer_headers(user_id):
    """AppealsOfficer headers for an arbitrary operator id.

    Pass a determination author's id here to exercise the segregation-of-
    duties rejection (the same human behind both roles).
    """
    return build_user_headers(user_id, ROLE_APPEALS_OFFICER)


def make_irs_data_agent_headers(user_id):
    return build_user_headers(user_id, ROLE_IRS_DATA_AGENT)


def make_benefit_administrator_headers(user_id):
    return build_user_headers(user_id, ROLE_BENEFIT_ADMINISTRATOR)


# --- Malformed authentication header sets ----------------------------------------------
#
# PRD section 2.1: a request missing either header, or presenting a role the
# system does not declare, is rejected with ERR_UNAUTHENTICATED (HTTP 401).

NO_AUTH_HEADERS = {
    "Content-Type": "application/json",
}

MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_FIELD_OFFICER,
    "Content-Type": "application/json",
}

MISSING_USER_ROLE_HEADERS = {
    "X-User-ID": FIELD_OFFICER_USER_ID,
    "Content-Type": "application/json",
}

UNDECLARED_ROLE_HEADERS = {
    "X-User-ID": FIELD_OFFICER_USER_ID,
    "X-User-Role": "EnrollmentClerk",
    "Content-Type": "application/json",
}
