"""Identity headers for every role.

The five operator roles carry an opaque ``X-User-ID`` that the server never
compares to an entity id, so they are pre-built module constants.  A
``SupplierUser`` header, by contrast, must carry the acting supplier's own id,
so it is produced by a builder that takes the supplier id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_PACKAGING_DESIGNER,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_QUALITY_AUDITOR,
    ROLE_REGULATORY_REVIEWER,
    ROLE_SOURCING_MANAGER,
    ROLE_SUPPLIER_USER,
)

# --- Operator user identifiers ----------------------------------------------
DIRECTOR_1 = "u-director-1"
DIRECTOR_2 = "u-director-2"
DIRECTOR_3 = "u-director-3"
SOURCING_3 = "u-sourcing-3"
SOURCING_4 = "u-sourcing-4"
QUALITY_5 = "u-quality-5"
REGULATORY_7 = "u-reg-7"
REGULATORY_9 = "u-reg-9"
DESIGNER_1 = "u-designer-1"
DESIGNER_2 = "u-designer-2"

# --- Pre-built operator headers ---------------------------------------------
DIRECTOR_HEADERS = build_user_headers(DIRECTOR_1, ROLE_PROGRAM_DIRECTOR)
DIRECTOR_2_HEADERS = build_user_headers(DIRECTOR_2, ROLE_PROGRAM_DIRECTOR)
DIRECTOR_3_HEADERS = build_user_headers(DIRECTOR_3, ROLE_PROGRAM_DIRECTOR)
SOURCING_HEADERS = build_user_headers(SOURCING_3, ROLE_SOURCING_MANAGER)
SOURCING_4_HEADERS = build_user_headers(SOURCING_4, ROLE_SOURCING_MANAGER)
QUALITY_HEADERS = build_user_headers(QUALITY_5, ROLE_QUALITY_AUDITOR)
REGULATORY_HEADERS = build_user_headers(REGULATORY_7, ROLE_REGULATORY_REVIEWER)
REGULATORY_9_HEADERS = build_user_headers(REGULATORY_9, ROLE_REGULATORY_REVIEWER)
DESIGNER_HEADERS = build_user_headers(DESIGNER_1, ROLE_PACKAGING_DESIGNER)
DESIGNER_2_HEADERS = build_user_headers(DESIGNER_2, ROLE_PACKAGING_DESIGNER)


def make_supplier_headers(supplier_id: str) -> dict:
    """Headers for a SupplierUser acting as the supplier whose id is given."""
    return build_user_headers(supplier_id, ROLE_SUPPLIER_USER)


def make_director_headers(user_id: str) -> dict:
    """Headers for an arbitrary ProgramDirector operator identifier."""
    return build_user_headers(user_id, ROLE_PROGRAM_DIRECTOR)


def make_regulatory_headers(user_id: str) -> dict:
    """Headers for an arbitrary RegulatoryReviewer operator identifier."""
    return build_user_headers(user_id, ROLE_REGULATORY_REVIEWER)


def make_designer_headers(user_id: str) -> dict:
    """Headers for an arbitrary PackagingDesigner operator identifier."""
    return build_user_headers(user_id, ROLE_PACKAGING_DESIGNER)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user identifier and role string."""
    return build_user_headers(user_id, role)


HEADERS_BY_ROLE = {
    ROLE_PROGRAM_DIRECTOR: DIRECTOR_HEADERS,
    ROLE_SOURCING_MANAGER: SOURCING_HEADERS,
    ROLE_QUALITY_AUDITOR: QUALITY_HEADERS,
    ROLE_REGULATORY_REVIEWER: REGULATORY_HEADERS,
    ROLE_PACKAGING_DESIGNER: DESIGNER_HEADERS,
}

# Headers that omit an identity entirely, and headers that carry an empty
# identity, for the two 401 pathways.
NO_AUTH_HEADERS: dict = {"Content-Type": "application/json"}
EMPTY_USER_ID_HEADERS = build_user_headers("", ROLE_PROGRAM_DIRECTOR)
UNKNOWN_ROLE_HEADERS = build_user_headers("u-buyer-9", "CategoryBuyer")
