"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment, so each test has to build the
world it needs from scratch. These helpers do that walking through the public
API only - no direct data writes - and return the identifiers, headers and
observed versions the caller then asserts against.

They are organised from the simplest to the most far-reaching:

  Tier 1  advancing the logical clock
  Tier 2  seeding standing reference data: community, buyer, home site, commitment
  Tier 3  building the deal hierarchy: contract, application, rate lock
  Tier 4  lifecycle shortcuts: lock, approve, close, cancel, reinstate
  Tier 5  incentive machinery: disclosures, allocations, buydown records, forfeitures

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import constants as c
from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    BANKER_HEADERS,
    CLOSING_HEADERS,
    COMPLIANCE_HEADERS,
    SALES_HEADERS,
    make_buyer_headers,
)

# Every fixture-minted identity ends with this suffix so that a test which creates a
# second entity inside a shared ``world`` never trips PRD's uniqueness rules:
#   PRD section 2.7 - the commitment_code must be unique among the community's live
#     commitments ("collides with a live commitment of this community").
#   PRD section 3.2 - the lot_number must be "unique within its community".
#   PRD section 3.3 - the buyer email must be "unique across all buyers".
_UNIQUE_SALT = 0


def unique_suffix() -> str:
    """A per-call token that keeps a minted identity unique within one test."""
    global _UNIQUE_SALT
    _UNIQUE_SALT += 1
    return f"{_UNIQUE_SALT:04d}"

# The instant the clock reports on a fresh deployment.
BASE_CLOCK = c.BASE_CLOCK


def set_clock(api: ApiClient, to_iso8601: str) -> None:
    """Move the server's logical clock to the supplied instant."""
    get_success_data(api.set_clock(to_iso8601, ADMIN_HEADERS))


def rows(response) -> Tuple[List[dict], dict]:
    """Unwrap a listing into (rows, meta).

    PRD section 2.3 scopes the pagination fields to the list endpoints that accept
    `limit`/`offset`; the four nested contract/application listings are declared
    without those controls, so their envelope carries only the identity fields in
    `meta`. Both shapes are accepted here.
    """
    if response.status_code != 200:
        raise AssertionError(
            f"Expected 200 for a listing, got {response.status_code}: {response.text}"
        )
    body = response.json()
    assert "data" in body, "Missing 'data'"
    assert "meta" in body, "Missing 'meta'"
    data = body["data"]
    assert isinstance(data, list), f"a listing's data must be an array, got {type(data).__name__}"
    return data, body["meta"]


def read_community(api: ApiClient, community_id: str) -> dict:
    return get_success_data(api.get_community(community_id, COMPLIANCE_HEADERS))


def read_buyer(api: ApiClient, buyer_id: str) -> dict:
    return get_success_data(api.get_buyer(buyer_id, SALES_HEADERS))


def read_home_site(api: ApiClient, home_site_id: str) -> dict:
    return get_success_data(api.get_home_site(home_site_id, SALES_HEADERS))


def read_commitment(api: ApiClient, commitment_id: str) -> dict:
    return get_success_data(api.get_forward_commitment(commitment_id, BANKER_HEADERS))


def read_contract(api: ApiClient, contract_id: str) -> dict:
    return get_success_data(api.get_contract(contract_id, COMPLIANCE_HEADERS))


def read_application(api: ApiClient, application_id: str) -> dict:
    return get_success_data(api.get_loan_application(application_id, BANKER_HEADERS))


def read_rate_lock(api: ApiClient, rate_lock_id: str) -> dict:
    return get_success_data(api.get_rate_lock(rate_lock_id, BANKER_HEADERS))


def read_allocation(api: ApiClient, allocation_id: str) -> dict:
    return get_success_data(api.get_incentive_allocation(allocation_id, SALES_HEADERS))


def read_buydown_record(api: ApiClient, record_id: str) -> dict:
    return get_success_data(api.get_buydown_record(record_id, CLOSING_HEADERS))


def read_disclosure(api: ApiClient, disclosure_id: str) -> dict:
    return get_success_data(api.get_disclosure(disclosure_id, COMPLIANCE_HEADERS))


def read_forfeiture(api: ApiClient, forfeiture_id: str) -> dict:
    return get_success_data(api.get_deposit_forfeiture(forfeiture_id, CLOSING_HEADERS))


# --------------------------------------------------------------------------
# Tier 2 - standing reference data
# --------------------------------------------------------------------------

def create_community(api: ApiClient, **overrides) -> dict:
    """A community under the STANDARD policy unless caps are supplied."""
    return get_success_data(api.create_community(f.community_payload(**overrides), ADMIN_HEADERS))


def create_buyer(api: ApiClient, **overrides) -> dict:
    """A buyer whose default email is unique across the deployment.

    An override of ``email`` wins, so the duplicate-email tests can still plant a
    collision deliberately.
    """
    if not overrides.get("email"):
        overrides["email"] = f"buyer{unique_suffix()}@x.com"
    return get_success_data(api.create_buyer(f.buyer_payload(**overrides), SALES_HEADERS))


def create_home_site(api: ApiClient, community_id: str, **overrides) -> dict:
    """A home site whose default lot_number is unique within its community."""
    if not overrides.get("lot_number"):
        overrides["lot_number"] = f"LOT-{unique_suffix()}"
    return get_success_data(
        api.create_home_site(community_id, f.home_site_payload(**overrides), SALES_HEADERS)
    )


def create_commitment(api: ApiClient, community_id: str, **overrides) -> dict:
    """A commitment whose default code is unique among its community's live pools."""
    if not overrides.get("commitment_code"):
        overrides["commitment_code"] = f"FC-{unique_suffix()}"
    return get_success_data(
        api.create_forward_commitment(
            community_id, f.forward_commitment_payload(**overrides), BANKER_HEADERS
        )
    )


def seed_reference_data(
    api: ApiClient,
    *,
    committed_units: int = 10,
    commitment_start_iso: Optional[str] = None,
    commitment_end_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Clock at the startup default, one community, one buyer, one home site, one commitment.

    ``commitment_start_iso`` / ``commitment_end_iso`` override the reference pool's
    window. Tests that plant a commitment of their own in the same community pass a
    window that cannot collide with it - PRD section 3.6 refuses a purchase whose
    half-open window runs into an existing OPEN commitment of the community.

    Returns a dict of ids and header sets that the deeper builders extend.
    """
    world: Dict[str, Any] = {}
    set_clock(api, BASE_CLOCK)
    world["community"] = create_community(api)
    world["buyer"] = create_buyer(api)
    world["home_site"] = create_home_site(api, world["community"]["id"])
    seed_commitment_overrides: Dict[str, Any] = {"committed_units": committed_units}
    if commitment_start_iso is not None:
        seed_commitment_overrides["commitment_start_iso"] = commitment_start_iso
    if commitment_end_iso is not None:
        seed_commitment_overrides["commitment_end_iso"] = commitment_end_iso
    world["commitment"] = create_commitment(
        api, world["community"]["id"], **seed_commitment_overrides
    )
    world.update(
        {
            "cm1": world["community"]["id"],
            "b1": world["buyer"]["id"],
            "hs1": world["home_site"]["id"],
            "fc1": world["commitment"]["id"],
            "admin_headers": ADMIN_HEADERS,
            "compliance_headers": COMPLIANCE_HEADERS,
            "sales_headers": SALES_HEADERS,
            "banker_headers": BANKER_HEADERS,
            "closing_headers": CLOSING_HEADERS,
            "anonymous_headers": ANONYMOUS_HEADERS,
            "buyer_headers": make_buyer_headers(world["buyer"]["id"]),
        }
    )
    return world


# --------------------------------------------------------------------------
# Tier 3 - the deal hierarchy
# --------------------------------------------------------------------------

def add_home_site(api: ApiClient, world: Dict[str, Any], key: str, **overrides) -> dict:
    """Attach one more inventory home to the world's community."""
    site = create_home_site(api, world["cm1"], **overrides)
    world[key] = site["id"]
    return site


def create_contract(api: ApiClient, home_site_id: str, buyer_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_contract(home_site_id, f.contract_payload(buyer_id, **overrides), SALES_HEADERS)
    )


def create_application(
    api: ApiClient,
    contract_id: str,
    lender_entity_code: str = "AFFILIATED_LENDER",
    **overrides,
) -> dict:
    """File one loan application. Default numbers stay unique across the platform
    (PRD section 3.3), which matters when a test files two.
    """
    if not overrides.get("application_number"):
        overrides["application_number"] = f"APP-{unique_suffix()}"
    return get_success_data(
        api.create_loan_application(
            contract_id,
            f.loan_application_payload(lender_entity_code=lender_entity_code, **overrides),
            BANKER_HEADERS,
        )
    )


def build_deal(
    api: ApiClient,
    *,
    lender_entity_code: str = "AFFILIATED_LENDER",
    construction_stage: str = "DRYWALL",
    committed_units: int = 10,
    application_number: str = "APP-1",
    qualifying_income_cents: Optional[int] = None,
    monthly_debt_cents: Optional[int] = None,
    qualify: bool = True,
    world: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Reference data plus a PENDING contract and (by default) a QUALIFIED application.

    Keys added: ct1, ct1_v, la1, la1_v (when qualified), contract, application.
    """
    world = dict(world) if world else seed_reference_data(api, committed_units=committed_units)
    if construction_stage != "DRYWALL":
        site = create_home_site(
            api, world["cm1"], lot_number="L1", address="1 Elm", construction_stage=construction_stage
        )
        world["home_site"] = site
        world["hs1"] = site["id"]

    contract = create_contract(api, world["hs1"], world["b1"])
    world["contract"] = contract
    world["ct1"] = contract["id"]
    world["ct1_v"] = contract["version"]

    app_overrides: Dict[str, Any] = {"application_number": application_number}
    if qualifying_income_cents is not None:
        app_overrides["qualifying_income_cents"] = qualifying_income_cents
    if monthly_debt_cents is not None:
        app_overrides["monthly_debt_cents"] = monthly_debt_cents
    application = create_application(
        api, world["ct1"], lender_entity_code=lender_entity_code, **app_overrides
    )
    world["application"] = application
    world["la1"] = application["id"]

    if qualify:
        qualified = get_success_data(api.qualify_loan_application(world["la1"], BANKER_HEADERS))
        world["application"] = qualified
        world["la1_v"] = qualified["version"]
    return world


def give_lock(
    api: ApiClient,
    world: Dict[str, Any],
    *,
    lock_days: int = 180,
    lock_rate_bps: Optional[int] = None,
    application_id: Optional[str] = None,
    commitment_id: Optional[str] = None,
) -> dict:
    """Create a rate lock against the world's qualified application. Stores lk1."""
    application_id = application_id or world["la1"]
    commitment_id = commitment_id or world["fc1"]
    application = read_application(api, application_id)
    payload = f.rate_lock_payload(
        commitment_id,
        lock_rate_bps=lock_rate_bps,
        lock_days=lock_days,
        expected_application_version=application["version"],
    )
    lock = get_success_data(api.create_rate_lock(application_id, payload, BANKER_HEADERS))
    world["lock"] = lock
    world["lk1"] = lock["id"]
    return lock


def drive_lock(api: ApiClient, world: Dict[str, Any]) -> dict:
    """Move the world's contract from PENDING to LOCKED."""
    contract = get_success_data(api.lock_contract(world["ct1"], BANKER_HEADERS))
    world["contract"] = contract
    return contract


def drive_approve(api: ApiClient, world: Dict[str, Any]) -> dict:
    contract = get_success_data(api.approve_contract(world["ct1"], COMPLIANCE_HEADERS))
    world["contract"] = contract
    return contract


def drive_close(api: ApiClient, world: Dict[str, Any]) -> dict:
    contract = get_success_data(api.close_contract(world["ct1"], CLOSING_HEADERS))
    world["contract"] = contract
    return contract


def drive_cancel(api: ApiClient, world: Dict[str, Any], reason: str = "RATE_SHOCK") -> dict:
    contract = get_success_data(api.cancel_contract(world["ct1"], reason, SALES_HEADERS))
    world["contract"] = contract
    return contract


def drive_reinstate(api: ApiClient, world: Dict[str, Any]) -> dict:
    contract = get_success_data(api.reinstate_contract(world["ct1"], SALES_HEADERS))
    world["contract"] = contract
    return contract


# --------------------------------------------------------------------------
# Tier 5 - disclosures and the incentive machinery
# --------------------------------------------------------------------------

def deliver_disclosure(
    api: ApiClient,
    contract_id: str,
    disclosure_type: str = "AFFILIATED_BUSINESS_ARRANGEMENT",
) -> dict:
    return get_success_data(api.create_disclosure(contract_id, disclosure_type, COMPLIANCE_HEADERS))


def acknowledge(api: ApiClient, disclosure_id: str, buyer_id: str) -> dict:
    """Acknowledging is buyer-only, and the buyer header carries the real buyer id."""
    return get_success_data(
        api.acknowledge_disclosure(disclosure_id, make_buyer_headers(buyer_id))
    )


def allocate(
    api: ApiClient,
    contract_id: str,
    bucket: str,
    requested_cents: int,
    expected_contract_version: Optional[int] = None,
) -> dict:
    """Allocate against the contract, defaulting the version guard to the live one."""
    if expected_contract_version is None:
        expected_contract_version = read_contract(api, contract_id)["version"]
    return get_success_data(
        api.create_incentive_allocation(
            contract_id,
            f.incentive_allocation_payload(bucket, requested_cents, expected_contract_version),
            SALES_HEADERS,
        )
    )


def add_buydown_record(
    api: ApiClient,
    contract_id: str,
    allocation_id: str,
    gross_buydown_cents: int,
    expected_contract_version: Optional[int] = None,
) -> dict:
    if expected_contract_version is None:
        expected_contract_version = read_contract(api, contract_id)["version"]
    return get_success_data(
        api.create_buydown_record(
            contract_id,
            f.buydown_record_payload(allocation_id, gross_buydown_cents, expected_contract_version),
            CLOSING_HEADERS,
        )
    )


def setup_contract_with_aba(
    api: ApiClient,
    *,
    construction_stage: str = "DRYWALL",
    committed_units: int = 10,
    acknowledge_aba: bool = True,
    lock_days: int = 180,
    target_state: str = "LOCKED",
    world: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Contract driven to LOCKED, with an affiliated qualified application,
    an active lock and (optionally) an acknowledged affiliated-business disclosure."""
    world = build_deal(
        api, construction_stage=construction_stage,
        committed_units=committed_units, world=world,
    )
    give_lock(api, world, lock_days=lock_days)
    drive_lock(api, world)

    disclosure = deliver_disclosure(api, world["ct1"])
    world["disclosure"] = disclosure
    world["d1"] = disclosure["id"]
    if acknowledge_aba:
        acked = acknowledge(api, world["d1"], world["b1"])
        world["disclosure"] = acked

    if target_state == "APPROVED":
        drive_approve(api, world)
    elif target_state == "CLOSED":
        drive_approve(api, world)
        drive_close(api, world)
    return world


def setup_contract_with_rate_buydown(
    api: ApiClient,
    *,
    buydown_cents: int = 6_000_000,
    gross_buydown_cents: Optional[int] = None,
    construction_stage: str = "DRYWALL",
    committed_units: int = 10,
    target_state: str = "LOCKED",
    with_buydown_record: bool = False,
    acknowledge_aba: bool = True,
    lock_days: int = 180,
    world: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Contract carrying a RATE_BUYDOWN allocation, optionally with a booked record.

    Order matters: the affiliated-business disclosure is delivered (and normally
    acknowledged) first, because PRD section 3.7 refuses a RATE_BUYDOWN allocation
    until the contract holds an ACKNOWLEDGED AFFILIATED_BUSINESS_ARRANGEMENT form;
    the allocation is written second, then approval applies it.
    """
    world = build_deal(
        api, construction_stage=construction_stage,
        committed_units=committed_units, world=world,
    )
    give_lock(api, world, lock_days=lock_days)
    drive_lock(api, world)

    # PRD section 3.7: a RATE_BUYDOWN allocation is refused (ERR_ABA_DISCLOSURE_MISSING,
    # priority 6) unless the contract already holds an ACKNOWLEDGED affiliated-business
    # disclosure. Deliver and acknowledge that form first, then allocate.
    disclosure = deliver_disclosure(api, world["ct1"])
    world["disclosure"] = disclosure
    world["d1"] = disclosure["id"]
    if acknowledge_aba:
        acked = acknowledge(api, world["d1"], world["b1"])
        world["disclosure"] = acked

    allocation = allocate(api, world["ct1"], "RATE_BUYDOWN", buydown_cents)
    world["allocation"] = allocation
    world["al1"] = allocation["id"]

    if with_buydown_record:
        record = add_buydown_record(
            api, world["ct1"], world["al1"], gross_buydown_cents or buydown_cents
        )
        world["buydown_record"] = record
        world["bd1"] = record["id"]

    if target_state == "APPROVED":
        drive_approve(api, world)
    elif target_state == "CLOSED":
        drive_approve(api, world)
        drive_close(api, world)
    return world


def close_deal(
    api: ApiClient,
    *,
    lender_entity_code: str = "AFFILIATED_LENDER",
    construction_stage: str = "FINISH",
    committed_units: int = 10,
    home_site_id: Optional[str] = None,
    buyer_id: Optional[str] = None,
    world: Optional[Dict[str, Any]] = None,
    suffix: str = "1",
) -> Dict[str, Any]:
    """Run one whole deal from contract to CLOSED inside the world's community.

    Returns a dict with the contract, home site, application, lock and the world.
    """
    world = world or seed_reference_data(api, committed_units=committed_units)
    if home_site_id is None:
        site = create_home_site(
            api,
            world["cm1"],
            lot_number=f"HOME-{suffix}",
            address=f"{suffix} Elm",
            construction_stage=construction_stage,
        )
        home_site_id = site["id"]
    buyer_id = buyer_id or create_buyer(
        api, full_name=f"Buyer {suffix}", email=f"buyer{suffix}@x.com"
    )["id"]

    contract = create_contract(api, home_site_id, buyer_id)
    application = create_application(
        api, contract["id"], lender_entity_code=lender_entity_code,
        application_number=f"APP-{suffix}",
    )
    application = get_success_data(
        api.qualify_loan_application(application["id"], BANKER_HEADERS)
    )
    lock = get_success_data(
        api.create_rate_lock(
            application["id"],
            f.rate_lock_payload(
                world["fc1"], lock_days=180,
                expected_application_version=application["version"],
            ),
            BANKER_HEADERS,
        )
    )
    get_success_data(api.lock_contract(contract["id"], BANKER_HEADERS))
    get_success_data(api.approve_contract(contract["id"], COMPLIANCE_HEADERS))
    get_success_data(api.close_contract(contract["id"], CLOSING_HEADERS))
    return {
        "world": world,
        "contract_id": contract["id"],
        "application_id": application["id"],
        "rate_lock_id": lock["id"],
        "home_site_id": home_site_id,
        "buyer_id": buyer_id,
    }


def setup_zeroed_derived_fields_expectation(api: ApiClient, **overrides) -> Dict[str, Any]:
    """Convenience wrapper used by the community-creation corner tests."""
    world: Dict[str, Any] = {}
    set_clock(api, BASE_CLOCK)
    community = create_community(api, **overrides)
    world["community"] = community
    world["cm1"] = community["id"]
    return world