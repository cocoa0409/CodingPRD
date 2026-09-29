"""Pre-built identity headers for the five roles named in the PRD.

Only one role is entity-backed: when `X-User-Role` is `CDESponsor`, `X-User-ID`
is the `id` of the acting community development entity, and ownership checks
compare a resource's foreign key to it.  Tests that act as a CDE sponsor MUST
therefore build headers with `make_cde_sponsor_headers(cde["id"])`.

The other four roles carry opaque operator identifiers that the server records
but never compares to any entity's `id`.  Those identifiers still have to be
threaded consistently, because they are stamped onto records
(`investor_user_id`, `sponsor_user_id`, `performed_by_user_id`,
`filed_by_user_id`) and later compared against each other.
"""
from prd_bench_local_runner.testing import build_user_headers

# --- Role names -------------------------------------------------------------

ROLE_CERTIFYING_AGENCY = "CertifyingAgency"
ROLE_CDE_SPONSOR = "CDESponsor"
ROLE_COMPLIANCE_REVIEWER = "ComplianceReviewer"
ROLE_TAX_CREDIT_INVESTOR = "TaxCreditInvestor"
ROLE_QALICB_SPONSOR = "QALICBSponsor"

ALL_ROLES = [
    ROLE_CERTIFYING_AGENCY,
    ROLE_CDE_SPONSOR,
    ROLE_COMPLIANCE_REVIEWER,
    ROLE_TAX_CREDIT_INVESTOR,
    ROLE_QALICB_SPONSOR,
]

# --- Stable opaque operator identifiers ------------------------------------

AGENCY_USER_ID = "agency-nmtc"

INVESTOR_DELTA_USER_ID = "investor-delta"
INVESTOR_ECHO_USER_ID = "investor-echo"

SPONSOR_DELTA_USER_ID = "sponsor-delta"
SPONSOR_ECHO_USER_ID = "sponsor-echo"
SPONSOR_BAYOU_USER_ID = "sponsor-bayou"

REVIEWER_ELIGIBILITY_USER_ID = "reviewer-eligibility"
REVIEWER_ANNUAL_USER_ID = "reviewer-annual"
REVIEWER_CBA_USER_ID = "reviewer-cba"

#: Placeholder for a CDE sponsor identity in tests that never reach an
#: ownership check (bad payloads, unresolvable path ids, role refusals).
UNOWNED_CDE_SPONSOR_USER_ID = "cde-sponsor-unowned"


TEST_USERS = {
    "agency_headers": build_user_headers(AGENCY_USER_ID, ROLE_CERTIFYING_AGENCY),
    # Entity-backed role: this shared constant is only safe where no ownership
    # check is reached.  Use make_cde_sponsor_headers(cde_id) otherwise.
    "cde_sponsor_headers": build_user_headers(
        UNOWNED_CDE_SPONSOR_USER_ID, ROLE_CDE_SPONSOR
    ),
    "investor_headers": build_user_headers(
        INVESTOR_DELTA_USER_ID, ROLE_TAX_CREDIT_INVESTOR
    ),
    "qalicb_sponsor_headers": build_user_headers(
        SPONSOR_DELTA_USER_ID, ROLE_QALICB_SPONSOR
    ),
    "eligibility_reviewer_headers": build_user_headers(
        REVIEWER_ELIGIBILITY_USER_ID, ROLE_COMPLIANCE_REVIEWER
    ),
    "annual_reviewer_headers": build_user_headers(
        REVIEWER_ANNUAL_USER_ID, ROLE_COMPLIANCE_REVIEWER
    ),
    "cba_reviewer_headers": build_user_headers(
        REVIEWER_CBA_USER_ID, ROLE_COMPLIANCE_REVIEWER
    ),
}


# --- Per-instance builders -------------------------------------------------

def make_cde_sponsor_headers(cde_id: str) -> dict:
    """Headers for the allocatee community development entity itself.

    `CDESponsor` is the one entity-backed role: pass the acting CDE's `id`
    so that ownership checks reaching through an award's `cde_id` succeed.
    """
    return build_user_headers(cde_id, ROLE_CDE_SPONSOR)


def make_agency_headers(user_id: str = AGENCY_USER_ID) -> dict:
    """Headers for the federal certifying and allocating authority."""
    return build_user_headers(user_id, ROLE_CERTIFYING_AGENCY)


def make_investor_headers(user_id: str = INVESTOR_DELTA_USER_ID) -> dict:
    """Headers for the tax-credit investor; recorded as `investor_user_id`."""
    return build_user_headers(user_id, ROLE_TAX_CREDIT_INVESTOR)


def make_qalicb_sponsor_headers(user_id: str = SPONSOR_DELTA_USER_ID) -> dict:
    """Headers for a project-company sponsor; recorded as `sponsor_user_id`."""
    return build_user_headers(user_id, ROLE_QALICB_SPONSOR)


def make_reviewer_headers(user_id: str) -> dict:
    """Headers for the independent compliance function.

    Two distinct reviewer identifiers are mandatory: the reviewer recorded on a
    project company's most recent eligibility test may not run the annual test
    of an investment that funds that company.
    """
    return build_user_headers(user_id, ROLE_COMPLIANCE_REVIEWER)


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identity pair, for identity-header tests."""
    return build_user_headers(user_id, role)
