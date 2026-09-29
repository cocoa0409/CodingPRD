"""Pre-built request headers for every acting identity in the suite.

PRD 2.1 requires two headers on every request: ``X-User-ID``, an opaque
identifier, and ``X-User-Role``, one of the six declared roles. The builders
below are the only place either header is constructed, so a distinct actor
always gets a distinct identifier -- which matters wherever the PRD compares two
acting identifiers with each other.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ALLERGY_NURSE,
    ROLE_AUDIOLOGIST,
    ROLE_OTOLARYNGOLOGIST,
    ROLE_PAYER_LIAISON,
    ROLE_PRACTICE_ADMIN,
    ROLE_STERILE_PROCESSING_TECH,
    USER_ADMIN_1,
    USER_ADMIN_2,
    USER_AUD_1,
    USER_AUD_2,
    USER_ENT_1,
    USER_ENT_2,
    USER_LIAISON_1,
    USER_LIAISON_2,
    USER_NURSE_1,
    USER_NURSE_2,
    USER_PL_1,
    USER_PL_2,
    USER_TECH_1,
    USER_TECH_2,
)


def headers_for(user_id: str, role: str) -> Dict[str, str]:
    """Build the two identity headers for an arbitrary actor."""
    return build_user_headers(user_id, role)


# -- practice administration -------------------------------------------------
ADMIN_1 = headers_for(USER_ADMIN_1, ROLE_PRACTICE_ADMIN)
ADMIN_2 = headers_for(USER_ADMIN_2, ROLE_PRACTICE_ADMIN)

# -- otolaryngology ----------------------------------------------------------
ENT_1 = headers_for(USER_ENT_1, ROLE_OTOLARYNGOLOGIST)
ENT_2 = headers_for(USER_ENT_2, ROLE_OTOLARYNGOLOGIST)

# -- allergy nursing ---------------------------------------------------------
NURSE_1 = headers_for(USER_NURSE_1, ROLE_ALLERGY_NURSE)
NURSE_2 = headers_for(USER_NURSE_2, ROLE_ALLERGY_NURSE)

# -- audiology ---------------------------------------------------------------
AUD_1 = headers_for(USER_AUD_1, ROLE_AUDIOLOGIST)
AUD_2 = headers_for(USER_AUD_2, ROLE_AUDIOLOGIST)

# -- sterile processing ------------------------------------------------------
TECH_1 = headers_for(USER_TECH_1, ROLE_STERILE_PROCESSING_TECH)
TECH_2 = headers_for(USER_TECH_2, ROLE_STERILE_PROCESSING_TECH)

# -- payer liaison -----------------------------------------------------------
LIAISON_1 = headers_for(USER_LIAISON_1, ROLE_PAYER_LIAISON)
LIAISON_2 = headers_for(USER_LIAISON_2, ROLE_PAYER_LIAISON)
# Two further payer-liaison identities, used where a test needs a submitter and
# a decider drawn from a different pair of opaque identifiers.
PL_1 = headers_for(USER_PL_1, ROLE_PAYER_LIAISON)
PL_2 = headers_for(USER_PL_2, ROLE_PAYER_LIAISON)


# -- deliberately malformed identity headers ---------------------------------
#
# PRD 2.1 treats a missing or empty ``X-User-ID`` and a missing or empty
# ``X-User-Role`` alike: the request is unauthenticated. The builders below emit
# the empty string, never a run of spaces -- a whitespace-only header value is
# rejected by the HTTP layer itself and would never reach the service.


def headers_with_blank_user_id(role: str) -> Dict[str, str]:
    """Identity headers whose ``X-User-ID`` is the empty string."""
    headers = build_user_headers("placeholder", role)
    headers["X-User-ID"] = ""
    return headers


def headers_with_blank_role(user_id: str) -> Dict[str, str]:
    """Identity headers whose ``X-User-Role`` is the empty string."""
    headers = build_user_headers(user_id, "placeholder")
    headers["X-User-Role"] = ""
    return headers


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Identity headers from which ``X-User-ID`` is absent altogether."""
    headers = build_user_headers("placeholder", role)
    del headers["X-User-ID"]
    return headers


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """Identity headers from which ``X-User-Role`` is absent altogether."""
    headers = build_user_headers(user_id, "placeholder")
    del headers["X-User-Role"]
    return headers


def headers_with_blank_identity() -> Dict[str, str]:
    """Identity headers in which both values are the empty string."""
    headers = build_user_headers("placeholder", "placeholder")
    headers["X-User-ID"] = ""
    headers["X-User-Role"] = ""
    return headers
