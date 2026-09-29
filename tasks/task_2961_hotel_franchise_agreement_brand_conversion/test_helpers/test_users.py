"""Pre-built request headers for the four recognised roles (PRD §2.1).

The three franchisor roles are opaque: any non-empty ``X-User-ID`` is
accepted and the value only matters where segregation of duties compares two
actors, so those roles get several distinct identities.

``Owner`` is entity-backed: ``X-User-ID`` must be the id of an Owner row, and
an owner may only reach resources whose agreement resolves — through its
application's ``owner_id`` — back to that same row.  Owner headers therefore
have to be built per owner with :func:`make_owner_headers`; there is no
usable shared owner identity.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Opaque franchisor identities ────────────────────────────────────
# Distinct ids so a segregation-of-duties pair can be assembled from two
# actors holding the same role.
FDM_REVIEWER_USER_ID = "fdm-review-01"
FDM_DECIDER_USER_ID = "fdm-decision-02"
FDM_THIRD_USER_ID = "fdm-portfolio-03"
BSD_USER_ID = "bsd-standards-01"
BSD_SECOND_USER_ID = "bsd-standards-02"
QA_INSPECTOR_USER_ID = "qai-first-01"
QA_SECOND_INSPECTOR_USER_ID = "qai-second-02"


def make_franchise_development_manager_headers(user_id: str) -> dict:
    """Headers for a FranchiseDevelopmentManager acting under ``user_id``."""
    return build_user_headers(user_id, UserRole.FRANCHISE_DEVELOPMENT_MANAGER.value)


def make_brand_standards_director_headers(user_id: str) -> dict:
    """Headers for a BrandStandardsDirector acting under ``user_id``."""
    return build_user_headers(user_id, UserRole.BRAND_STANDARDS_DIRECTOR.value)


def make_qa_inspector_headers(user_id: str) -> dict:
    """Headers for a QaInspector acting under ``user_id``."""
    return build_user_headers(user_id, UserRole.QA_INSPECTOR.value)


def make_owner_headers(user_id: str) -> dict:
    """Headers for the Owner whose row id is ``user_id``.

    Always thread the real Owner id here.  Reusing one placeholder id across
    two owners would make every ownership check pass by accident.
    """
    return build_user_headers(user_id, UserRole.OWNER.value)


# Convenience singletons for the franchisor roles, whose identity is opaque.
FDM_HEADERS = make_franchise_development_manager_headers(FDM_REVIEWER_USER_ID)
FDM_DECIDER_HEADERS = make_franchise_development_manager_headers(FDM_DECIDER_USER_ID)
FDM_THIRD_HEADERS = make_franchise_development_manager_headers(FDM_THIRD_USER_ID)
BSD_HEADERS = make_brand_standards_director_headers(BSD_USER_ID)
BSD_SECOND_HEADERS = make_brand_standards_director_headers(BSD_SECOND_USER_ID)
QA_HEADERS = make_qa_inspector_headers(QA_INSPECTOR_USER_ID)
QA_SECOND_HEADERS = make_qa_inspector_headers(QA_SECOND_INSPECTOR_USER_ID)

TEST_USERS = {
    "franchise_development_manager": FDM_HEADERS,
    "franchise_development_manager_decider": FDM_DECIDER_HEADERS,
    "brand_standards_director": BSD_HEADERS,
    "qa_inspector": QA_HEADERS,
}


# ─── Malformed credential builders ───────────────────────────────────

def headers_without_user_id() -> dict:
    """Only the role header is present, so X-User-ID is genuinely absent."""
    return {
        "X-User-Role": UserRole.FRANCHISE_DEVELOPMENT_MANAGER.value,
        "Content-Type": "application/json",
    }


def headers_without_role() -> dict:
    """Only the id header is present, so X-User-Role is genuinely absent."""
    return {
        "X-User-ID": FDM_REVIEWER_USER_ID,
        "Content-Type": "application/json",
    }


def headers_with_empty_user_id() -> dict:
    """X-User-ID present but the empty string - not a space, the empty string."""
    return {
        "X-User-ID": "",
        "X-User-Role": UserRole.FRANCHISE_DEVELOPMENT_MANAGER.value,
        "Content-Type": "application/json",
    }


def headers_with_empty_role() -> dict:
    """X-User-Role present but the empty string."""
    return {
        "X-User-ID": FDM_REVIEWER_USER_ID,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_unrecognised_role(role: str = "RegionalVicePresident") -> dict:
    """Both headers present; the role is simply not one of the four."""
    return {
        "X-User-ID": FDM_REVIEWER_USER_ID,
        "X-User-Role": role,
        "Content-Type": "application/json",
    }
