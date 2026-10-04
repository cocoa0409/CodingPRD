"""Caller identities for the eight declared roles (PRD §2.1).

Identity model per the PRD:

- ``DealerRep`` is entity-backed: its ``X-User-ID`` must equal the ``id`` of
  the Account it acts for. Ownership checks on order placement, cancellation,
  and claim filing compare the resource's ``account_id`` to ``X-User-ID``, so
  any ownership-gated call MUST use ``make_dealer_rep_headers(account["id"])``.
  The shared ``TEST_USERS["dealer_rep"]`` entry is a fallback for tests whose
  outcome does not depend on ownership (e.g. a 400-on-bad-payload probe).

- ``RetailDesigner`` is opaque, but the server records the caller's
  ``X-User-ID`` as the design job's ``designer_user_id`` and requires every
  later transition of that job to present the same id. Fixtures therefore keep
  one designer id per job via ``make_retail_designer_headers(user_id)``.

- ``ClaimsAdjuster`` is opaque; segregation of duties requires the decider's
  ``X-User-ID`` to differ from the claim's ``filed_by_user_id``. Two shared
  adjuster identities plus the builder cover that.

- ``PlatformAdmin``, ``ProgramManager``, ``PlantScheduler``,
  ``LogisticsCoordinator`` and ``FieldServiceRep`` are opaque and never
  compared to any entity id; shared constants are canonical for them.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLAIMS_ADJUSTER,
    ROLE_DEALER_REP,
    ROLE_FIELD_SERVICE_REP,
    ROLE_LOGISTICS_COORDINATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_PLANT_SCHEDULER,
    ROLE_PROGRAM_MANAGER,
    ROLE_RETAIL_DESIGNER,
)

# Stable opaque identifiers for the non-entity-backed roles.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"id": "pa-1", "role": ROLE_PLATFORM_ADMIN},
    "program_manager": {"id": "pm-1", "role": ROLE_PROGRAM_MANAGER},
    "retail_designer": {"id": "des-1", "role": ROLE_RETAIL_DESIGNER},
    "retail_designer_alt": {"id": "des-2", "role": ROLE_RETAIL_DESIGNER},
    # Fallback only: this id matches no Account. Never use it for an
    # ownership-gated call (order create/cancel, DealerRep claim filing).
    "dealer_rep": {"id": "dealer-rep-unlinked-1", "role": ROLE_DEALER_REP},
    "plant_scheduler": {"id": "ps-1", "role": ROLE_PLANT_SCHEDULER},
    "logistics_coordinator": {"id": "lc-1", "role": ROLE_LOGISTICS_COORDINATOR},
    "claims_adjuster": {"id": "ca-1", "role": ROLE_CLAIMS_ADJUSTER},
    "claims_adjuster_alt": {"id": "ca-2", "role": ROLE_CLAIMS_ADJUSTER},
    "field_service_rep": {"id": "fsr-1", "role": ROLE_FIELD_SERVICE_REP},
}

# Ready-made header dicts for the opaque roles (and the DealerRep fallback).
PLATFORM_ADMIN_HEADERS = build_user_headers(TEST_USERS["platform_admin"]["id"], ROLE_PLATFORM_ADMIN)
PROGRAM_MANAGER_HEADERS = build_user_headers(TEST_USERS["program_manager"]["id"], ROLE_PROGRAM_MANAGER)
RETAIL_DESIGNER_HEADERS = build_user_headers(TEST_USERS["retail_designer"]["id"], ROLE_RETAIL_DESIGNER)
RETAIL_DESIGNER_ALT_HEADERS = build_user_headers(
    TEST_USERS["retail_designer_alt"]["id"], ROLE_RETAIL_DESIGNER
)
DEALER_REP_HEADERS = build_user_headers(TEST_USERS["dealer_rep"]["id"], ROLE_DEALER_REP)
PLANT_SCHEDULER_HEADERS = build_user_headers(TEST_USERS["plant_scheduler"]["id"], ROLE_PLANT_SCHEDULER)
LOGISTICS_COORDINATOR_HEADERS = build_user_headers(
    TEST_USERS["logistics_coordinator"]["id"], ROLE_LOGISTICS_COORDINATOR
)
CLAIMS_ADJUSTER_HEADERS = build_user_headers(TEST_USERS["claims_adjuster"]["id"], ROLE_CLAIMS_ADJUSTER)
CLAIMS_ADJUSTER_ALT_HEADERS = build_user_headers(
    TEST_USERS["claims_adjuster_alt"]["id"], ROLE_CLAIMS_ADJUSTER
)
FIELD_SERVICE_REP_HEADERS = build_user_headers(
    TEST_USERS["field_service_rep"]["id"], ROLE_FIELD_SERVICE_REP
)


# ── Per-instance builders ───────────────────────────────────────────────────

def make_dealer_rep_headers(account_id: str) -> Dict[str, str]:
    """Headers for a DealerRep acting as the Account with this id.

    Mandatory whenever the call is ownership-gated: the PRD requires the
    DealerRep's X-User-ID to equal the account_id of the order being placed
    or cancelled, or of the order a claim is filed against.
    """
    return build_user_headers(account_id, ROLE_DEALER_REP)


def make_retail_designer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a RetailDesigner. Pass the same id across a design job's
    whole lifecycle: transitions require X-User-ID == designer_user_id."""
    return build_user_headers(user_id, ROLE_RETAIL_DESIGNER)


def make_claims_adjuster_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ClaimsAdjuster. Decide with an id different from the
    claim filer's id to satisfy segregation of duties."""
    return build_user_headers(user_id, ROLE_CLAIMS_ADJUSTER)


def make_logistics_coordinator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LOGISTICS_COORDINATOR)


def make_program_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PROGRAM_MANAGER)


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_plant_scheduler_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLANT_SCHEDULER)


def make_field_service_rep_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FIELD_SERVICE_REP)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Generic builder for any declared role."""
    return build_user_headers(user_id, role)


# ── Malformed credentials, for the authentication tier ─────────────────────

def headers_without_role(user_id: str = "probe-1") -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_PLATFORM_ADMIN) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


UNDECLARED_ROLE = "StoreGreeter"


def headers_with_undeclared_role(user_id: str = "probe-1") -> Dict[str, str]:
    """Headers naming a role the contract does not recognize."""
    return build_user_headers(user_id, UNDECLARED_ROLE)


def empty_headers() -> Dict[str, str]:
    """Neither header present."""
    return {"Content-Type": "application/json"}
