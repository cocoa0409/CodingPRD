"""Caller identities for the seven declared roles (PRD §2.1).

The meaning of ``X-User-ID`` depends on the role:

* ``EstablishmentManager`` — ``X-User-ID`` is the ``id`` of the acting
  Establishment; ownership checks compare it to the resource's establishment
  foreign key. Use ``make_establishment_manager_headers(establishment["id"])``.
* ``Inspector`` — ``X-User-ID`` is the ``id`` of the acting Inspector.
  Use ``make_inspector_headers(inspector["id"])``.
* ``SupervisoryReviewer`` — ``X-User-ID`` is likewise the ``id`` of an
  Inspector entity (a senior inspector acting in a supervisory capacity);
  segregation-of-duties checks compare it against the issuing/reporting
  inspector. Use ``make_supervisory_reviewer_headers(other_inspector["id"])``
  with a DIFFERENT inspector than the issuer/reporter.
* ``DistrictManager``, ``LabelOfficer``, ``RecallCoordinator``,
  ``ProgramAdministrator`` — opaque operator identifiers not tied to any
  persisted entity; the shared constant headers below are canonical.

``TEST_USERS`` values are ready-made header dicts. The entries for the three
entity-backed roles (``establishment_manager_headers``,
``inspector_headers``, ``supervisory_reviewer_headers``) are fallbacks ONLY
for tests whose outcome cannot depend on ownership or segregation
(missing-field 400s, not-found 404s, wrong-role 403s). Any ownership-gated or
segregation-gated call MUST use the per-instance builder with the real
entity's id — a constant id never equals a real entity id, so every such
check would reject the request.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DISTRICT_MANAGER,
    ROLE_ESTABLISHMENT_MANAGER,
    ROLE_INSPECTOR,
    ROLE_LABEL_OFFICER,
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_RECALL_COORDINATOR,
    ROLE_SUPERVISORY_REVIEWER,
)


# ── TEST_USERS: ready-made header dicts ──────────────────────────────────────
# Opaque roles get stable operator identifiers (never matched to an entity).
# Entity-backed entries are fallbacks for non-ownership tests only.

TEST_USERS: Dict[str, Dict[str, str]] = {
    "district_manager_headers": build_user_headers(
        "11111111-1111-4111-8111-111111111111", ROLE_DISTRICT_MANAGER
    ),
    "label_officer_headers": build_user_headers(
        "22222222-2222-4222-8222-222222222222", ROLE_LABEL_OFFICER
    ),
    "recall_coordinator_headers": build_user_headers(
        "33333333-3333-4333-8333-333333333333", ROLE_RECALL_COORDINATOR
    ),
    "program_administrator_headers": build_user_headers(
        "44444444-4444-4444-8444-444444444444", ROLE_PROGRAM_ADMINISTRATOR
    ),
    # Fallbacks for the entity-backed roles — non-ownership tests only.
    "establishment_manager_headers": build_user_headers(
        "55555555-5555-4555-8555-555555555555", ROLE_ESTABLISHMENT_MANAGER
    ),
    "inspector_headers": build_user_headers(
        "66666666-6666-4666-8666-666666666666", ROLE_INSPECTOR
    ),
    "supervisory_reviewer_headers": build_user_headers(
        "77777777-7777-4777-8777-777777777777", ROLE_SUPERVISORY_REVIEWER
    ),
}


# ── Named constants for the opaque roles ─────────────────────────────────────

DISTRICT_MANAGER_HEADERS = TEST_USERS["district_manager_headers"]
LABEL_OFFICER_HEADERS = TEST_USERS["label_officer_headers"]
RECALL_COORDINATOR_HEADERS = TEST_USERS["recall_coordinator_headers"]
PROGRAM_ADMINISTRATOR_HEADERS = TEST_USERS["program_administrator_headers"]


# ── Per-instance builders for the entity-backed roles ───────────────────────

def make_establishment_manager_headers(establishment_id: str) -> Dict[str, str]:
    """EstablishmentManager acting FOR this establishment. Pass the real
    Establishment.id — ownership checks compare it to the resource's
    establishment foreign key."""
    return build_user_headers(establishment_id, ROLE_ESTABLISHMENT_MANAGER)


def make_inspector_headers(inspector_id: str) -> Dict[str, str]:
    """Inspector acting as this inspector. Pass the real Inspector.id —
    issuance/reporting/collection calls pin X-User-ID to their inspector
    foreign key, and assignment confirmation pins it to the assignment's
    inspector_id."""
    return build_user_headers(inspector_id, ROLE_INSPECTOR)


def make_supervisory_reviewer_headers(inspector_id: str) -> Dict[str, str]:
    """SupervisoryReviewer acting as this (senior) inspector. Pass a real
    Inspector.id DIFFERENT from the issuing/reporting inspector — segregation
    of duties rejects a reviewer whose X-User-ID equals the issuer."""
    return build_user_headers(inspector_id, ROLE_SUPERVISORY_REVIEWER)


# ── Malformed credentials (validation tier 1 probes) ────────────────────────

def headers_without_role(user_id: str) -> Dict[str, str]:
    """Only X-User-ID present; X-User-Role omitted."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_PROGRAM_ADMINISTRATOR) -> Dict[str, str]:
    """Only X-User-Role present; X-User-ID omitted."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(
    user_id: str = "99999999-9999-4999-8999-999999999999",
    role: str = "PlantOwner",
) -> Dict[str, str]:
    """A role string the system does not declare."""
    return build_user_headers(user_id, role)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Generic builder for ad-hoc combinations (e.g. wrong-role probes)."""
    return build_user_headers(user_id, role)
