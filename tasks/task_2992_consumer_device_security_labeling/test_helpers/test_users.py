"""Pre-built role headers for every role the PRD declares (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.  ProgramAdministrator, ConformityReviewer and
# Consumer principals are never compared against a persisted row's id, so a
# shared constant is the canonical form for them.
ADMIN_USER_ID = "admin-1"
ADMIN_2_USER_ID = "admin-2"
ADMIN_3_USER_ID = "admin-3"
ADMIN_INTAKE_USER_ID = "admin-intake-1"
ADMIN_NOTICE_USER_ID = "admin-notice-1"
ADMIN_ADJUDICATE_USER_ID = "admin-adjudicate-1"
ADMIN_VACATE_USER_ID = "admin-vacate-1"
REVIEWER_USER_ID = "reviewer-1"
REVIEWER_2_USER_ID = "reviewer-2"
REVIEWER_3_USER_ID = "reviewer-3"
CONSUMER_USER_ID = "consumer-1"

TEST_USERS = {
    # opaque roles - shared constants are the canonical form
    "admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdministrator"),
    "admin_2_headers": build_user_headers(ADMIN_2_USER_ID, "ProgramAdministrator"),
    "admin_3_headers": build_user_headers(ADMIN_3_USER_ID, "ProgramAdministrator"),
    "admin_intake_headers": build_user_headers(
        ADMIN_INTAKE_USER_ID, "ProgramAdministrator"
    ),
    "admin_notice_headers": build_user_headers(
        ADMIN_NOTICE_USER_ID, "ProgramAdministrator"
    ),
    "admin_adjudicate_headers": build_user_headers(
        ADMIN_ADJUDICATE_USER_ID, "ProgramAdministrator"
    ),
    "admin_vacate_headers": build_user_headers(
        ADMIN_VACATE_USER_ID, "ProgramAdministrator"
    ),
    "reviewer_headers": build_user_headers(REVIEWER_USER_ID, "ConformityReviewer"),
    "reviewer_2_headers": build_user_headers(REVIEWER_2_USER_ID, "ConformityReviewer"),
    "reviewer_3_headers": build_user_headers(REVIEWER_3_USER_ID, "ConformityReviewer"),
    "consumer_headers": build_user_headers(CONSUMER_USER_ID, "Consumer"),
    # entity-backed roles - these shared constants are ONLY safe for tests that
    # do not exercise ownership (bad payload, missing resource, role denial).
    "manufacturer_headers": build_user_headers("test-manufacturer-1", "Manufacturer"),
    "test_lab_operator_headers": build_user_headers("test-lab-1", "TestLabOperator"),
    "retailer_headers": build_user_headers("test-retailer-1", "Retailer"),
}


# --- per-instance builders (mandatory for the three entity-backed roles) ---
def make_manufacturer_headers(manufacturer_id: str) -> dict:
    """Headers for a Manufacturer principal.  X-User-ID must be the acting
    Manufacturer's own id whenever the call is ownership-gated."""
    return build_user_headers(manufacturer_id, "Manufacturer")


def make_lab_operator_headers(test_lab_id: str) -> dict:
    """Headers for a TestLabOperator principal.  X-User-ID must be the acting
    TestLab's own id whenever the call is ownership-gated."""
    return build_user_headers(test_lab_id, "TestLabOperator")


def make_retailer_headers(retailer_id: str) -> dict:
    """Headers for a Retailer principal.  X-User-ID must be the acting
    Retailer's own id whenever the call is ownership-gated."""
    return build_user_headers(retailer_id, "Retailer")


def make_admin_headers(user_id: str) -> dict:
    """Headers for a named ProgramAdministrator operator identity."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_reviewer_headers(user_id: str) -> dict:
    """Headers for a named ConformityReviewer operator identity."""
    return build_user_headers(user_id, "ConformityReviewer")


def make_consumer_headers(user_id: str = CONSUMER_USER_ID) -> dict:
    return build_user_headers(user_id, "Consumer")


def make_headers(user_id: str, role: str) -> dict:
    """Free-form header builder for authentication-shape tests.

    Blank values are sent as empty strings (never whitespace) so the HTTP
    library transmits the header rather than rejecting it locally.
    """
    return build_user_headers(user_id, role)


ADMIN_HEADERS = TEST_USERS["admin_headers"]
REVIEWER_HEADERS = TEST_USERS["reviewer_headers"]
CONSUMER_HEADERS = TEST_USERS["consumer_headers"]
