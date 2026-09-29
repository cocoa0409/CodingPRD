"""
Identity headers.

PRD section 2.1 splits callers in two. Five roles present an "opaque operator
identifier not tied to any persisted entity"; those get stable string ids below.
Two roles — ``Sitter`` and ``RemoteObserver`` — present "the ``id`` of the acting
``Staff`` row", so their headers can only be built *after* the Staff row exists.
``make_sitter_headers`` / ``make_remote_observer_headers`` take that id, which is
why no shared constant exists for either role: two entities the PRD requires to
have distinct owners must never share one ``X-User-ID``.

Distinct opaque identities are structurally required in three places, all of
which the PRD enforces with ``ERR_SEGREGATION_OF_DUTIES``:

* a discontinuation decision must come from a provider other than the order's
  ``ordering_provider_user_id`` -> ``PROVIDER_ONE`` vs ``PROVIDER_TWO``;
* an incident review must be closed by an officer other than its
  ``review_opened_by_user_id`` -> ``OFFICER_ONE`` vs ``OFFICER_TWO``;
* a handoff countersigner must be a different ``Staff`` from the outgoing
  assignment's ``staff_id`` -> two separate Staff rows.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ATTENDING_PROVIDER,
    ROLE_NURSE_MANAGER,
    ROLE_REMOTE_OBSERVER,
    ROLE_SAFETY_OFFICER,
    ROLE_SITTER,
    ROLE_STAFFING_COORDINATOR,
    ROLE_SYSTEM_ADMIN,
)

# ─── Opaque operator identifiers ──────────────────────

PROVIDER_ONE = "prov-1"
PROVIDER_TWO = "prov-2"
PROVIDER_THREE = "prov-3"

MANAGER_ONE = "mgr-1"
MANAGER_TWO = "mgr-2"

COORDINATOR_ONE = "coord-1"
COORDINATOR_TWO = "coord-2"

OFFICER_ONE = "safety-1"
OFFICER_TWO = "safety-2"

ADMIN_ONE = "admin-1"

# An identifier used only for reads, where the PRD grants access to all roles.
READER_ONE = "reader-1"


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Build ``X-User-ID`` / ``X-User-Role`` headers for an arbitrary pair."""
    return build_user_headers(user_id, role)


# ─── Pre-built opaque-role headers ────────────────────

PROVIDER_1 = headers_for(ROLE_ATTENDING_PROVIDER, PROVIDER_ONE)
PROVIDER_2 = headers_for(ROLE_ATTENDING_PROVIDER, PROVIDER_TWO)
PROVIDER_3 = headers_for(ROLE_ATTENDING_PROVIDER, PROVIDER_THREE)

MANAGER = headers_for(ROLE_NURSE_MANAGER, MANAGER_ONE)
MANAGER_2 = headers_for(ROLE_NURSE_MANAGER, MANAGER_TWO)

COORDINATOR = headers_for(ROLE_STAFFING_COORDINATOR, COORDINATOR_ONE)
COORDINATOR_2 = headers_for(ROLE_STAFFING_COORDINATOR, COORDINATOR_TWO)

OFFICER_1 = headers_for(ROLE_SAFETY_OFFICER, OFFICER_ONE)
OFFICER_2 = headers_for(ROLE_SAFETY_OFFICER, OFFICER_TWO)

ADMIN = headers_for(ROLE_SYSTEM_ADMIN, ADMIN_ONE)

# A ``Sitter`` / ``RemoteObserver`` identity used for reads only, where PRD 2.1
# says "Every read endpoint in the API is readable by all seven roles".
READER_AS_SITTER = headers_for(ROLE_SITTER, READER_ONE)


# ─── Entity-backed identity builders ──────────────────

def make_sitter_headers(staff_id: str) -> Dict[str, str]:
    """A ``Sitter`` whose ``X-User-ID`` is the id of their own ``Staff`` row."""
    return headers_for(ROLE_SITTER, staff_id)


def make_remote_observer_headers(staff_id: str) -> Dict[str, str]:
    """A ``RemoteObserver`` whose ``X-User-ID`` is the id of their own ``Staff`` row."""
    return headers_for(ROLE_REMOTE_OBSERVER, staff_id)


# ─── Negative-path identity builders ──────────────────

def blank_user_id_headers(role: str) -> Dict[str, str]:
    """
    Headers whose ``X-User-ID`` is a genuine empty string.

    PRD 2.1: "a header supplied as an empty string counts as absent". The value
    must be ``""`` and not a whitespace string — whitespace would be a
    well-formed header value and would not exercise the same rung.
    """
    return headers_for(role, "")


def blank_role_headers(user_id: str) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is a genuine empty string."""
    return headers_for("", user_id)


def unknown_role_headers(user_id: str = ADMIN_ONE) -> Dict[str, str]:
    """A syntactically valid header carrying a role outside the declared seven."""
    return headers_for("ObservationAuditor", user_id)
