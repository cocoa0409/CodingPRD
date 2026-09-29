"""Composite setup helpers, arranged in tiers.

Every test starts against an empty database, so the workflow of PRD section 3
has to be replayed from the beginning each time. These helpers do that once,
in the order the PRD declares, and hand back a ``World`` dictionary carrying
the identifiers and versions a test needs.

Tier 1  single-resource seeds
Tier 2  state progression on one entity (qualified, cleared)
Tier 3  full-lifecycle shortcuts (quoted, papered, signed, open)
Tier 4  accumulation and threshold targeting (rooming list, pickup, cutoff)
Tier 5  finalization and terminal states (settlement, cancellation)

Identity is threaded rather than hard-coded: the separation-of-duties gate of
PRD 2.1 means the user who requests a study cannot decide it and the user who
prepares a settlement cannot finalize it, so every helper takes the acting
headers as a parameter.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    ACCOUNTING_CLERK,
    ACCOUNTING_CLERK_ALT,
    CONTRACT_ADMIN,
    RESERVATIONS_AGENT,
    REVENUE_MANAGER,
    REVENUE_MANAGER_ALT,
    SALES_MANAGER,
    SYSTEM_OPERATOR,
    make_group_contact_headers,
)
from .types import World

# --------------------------------------------------------------------------
# Tier 1 - single-resource seeds
# --------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock of PRD 2.4."""
    return get_success_data(api.set_clock(to_iso8601, SYSTEM_OPERATOR))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    """Pin the clock to the mandated startup default of PRD 2.4."""
    return set_clock(api, C.CLOCK_DEFAULT)


def seed_account(
    api: ApiClient, *, actor: Dict[str, str] = SALES_MANAGER, **kwargs: Any
) -> Dict[str, Any]:
    """Register a client organization (PRD 3.1)."""
    return get_success_data(
        api.create_account(F.account_payload(**kwargs), actor), 201
    )


def seed_inventory_days(
    api: ApiClient,
    stay_dates: Optional[Sequence[str]] = None,
    *,
    actor: Dict[str, str] = REVENUE_MANAGER,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Seed one calendar date per stay date (PRD 2.9)."""
    dates = list(stay_dates) if stay_dates is not None else list(C.STAY_DATES)
    return [
        get_success_data(
            api.create_inventory_day(F.inventory_day_payload(day, **kwargs), actor), 201
        )
        for day in dates
    ]


def seed_package(
    api: ApiClient,
    payload: Optional[Dict[str, Any]] = None,
    *,
    actor: Dict[str, str] = REVENUE_MANAGER,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Define a concession package (PRD 3.1)."""
    body = payload if payload is not None else F.package_payload(**kwargs)
    return get_success_data(api.create_package(body, actor), 201)


def seed_lead(
    api: ApiClient,
    account_id: str,
    *,
    actor: Dict[str, str] = SALES_MANAGER,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Capture an inbound lead in NEW (PRD 3.2)."""
    return get_success_data(
        api.create_lead(F.lead_payload(account_id, **kwargs), actor), 201
    )


def seed_function_space_hold(
    api: ApiClient,
    lead_id: str,
    *,
    actor: Dict[str, str] = SALES_MANAGER,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Hold meeting space for a lead's programme (PRD 3.2)."""
    return get_success_data(
        api.create_function_space_hold(
            F.function_space_hold_payload(lead_id, **kwargs), actor
        ),
        201,
    )


def seed_ancillary_charge(
    api: ApiClient,
    contract_id: str,
    *,
    actor: Dict[str, str] = ACCOUNTING_CLERK,
    post: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Quote ancillary revenue against a signed contract (PRD 3.8)."""
    charge = get_success_data(
        api.create_ancillary_charge(
            F.ancillary_charge_payload(contract_id, **kwargs), actor
        ),
        201,
    )
    if post:
        charge = get_success_data(api.post_ancillary_charge(charge["id"], actor))
    return charge


# --------------------------------------------------------------------------
# Read helpers - small typed reads used to capture versions and counters
# --------------------------------------------------------------------------


def read_lead(api: ApiClient, lead_id: str, actor: Dict[str, str] = SALES_MANAGER):
    return get_success_data(api.get_lead(lead_id, actor))


def lead_version(api: ApiClient, lead_id: str, actor: Dict[str, str] = SALES_MANAGER) -> int:
    return read_lead(api, lead_id, actor)["version"]


def read_contract(
    api: ApiClient, contract_id: str, actor: Dict[str, str] = CONTRACT_ADMIN
):
    return get_success_data(api.get_contract(contract_id, actor))


def contract_version(
    api: ApiClient, contract_id: str, actor: Dict[str, str] = CONTRACT_ADMIN
) -> int:
    return read_contract(api, contract_id, actor)["version"]


def read_quote(api: ApiClient, quote_id: str, actor: Dict[str, str] = SALES_MANAGER):
    return get_success_data(api.get_rate_quote(quote_id, actor))


def read_block(api: ApiClient, block_id: str, actor: Dict[str, str] = CONTRACT_ADMIN):
    return get_success_data(api.get_room_block(block_id, actor))


def block_version(
    api: ApiClient, block_id: str, actor: Dict[str, str] = CONTRACT_ADMIN
) -> int:
    return read_block(api, block_id, actor)["version"]


def read_nights(
    api: ApiClient, block_id: str, actor: Dict[str, str] = RESERVATIONS_AGENT
) -> List[Dict[str, Any]]:
    return get_success_data(api.list_block_nights(block_id, actor))


def night_on(
    api: ApiClient,
    block_id: str,
    stay_date: str,
    actor: Dict[str, str] = RESERVATIONS_AGENT,
) -> Dict[str, Any]:
    for night in read_nights(api, block_id, actor):
        if night["stay_date"] == stay_date:
            return night
    raise AssertionError(f"block {block_id} has no night on {stay_date}")


def read_inventory_days(
    api: ApiClient,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    actor: Dict[str, str] = REVENUE_MANAGER,
) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_inventory_days(actor, from_date=from_date, to_date=to_date)
    )


def inventory_day_on(
    api: ApiClient, stay_date: str, actor: Dict[str, str] = REVENUE_MANAGER
) -> Dict[str, Any]:
    for day in read_inventory_days(api, actor=actor):
        if day["stay_date"] == stay_date:
            return day
    raise AssertionError(f"no inventory day seeded for {stay_date}")


def held_rooms(
    api: ApiClient, stay_dates: Sequence[str], actor: Dict[str, str] = REVENUE_MANAGER
) -> List[int]:
    """held_group_rooms per stay date, in the order asked for (PRD 2.9)."""
    calendar = {d["stay_date"]: d for d in read_inventory_days(api, actor=actor)}
    return [calendar[day]["held_group_rooms"] for day in stay_dates]


def committed_rooms(
    api: ApiClient, stay_dates: Sequence[str], actor: Dict[str, str] = REVENUE_MANAGER
) -> List[int]:
    """committed_group_rooms per stay date, in the order asked for (PRD 2.9)."""
    calendar = {d["stay_date"]: d for d in read_inventory_days(api, actor=actor)}
    return [calendar[day]["committed_group_rooms"] for day in stay_dates]


def master_block_of(
    api: ApiClient, contract_id: str, actor: Dict[str, str] = CONTRACT_ADMIN
) -> Dict[str, Any]:
    """The master block minted by the countersignature cascade (PRD 3.5)."""
    rows = get_success_data(
        api.list_room_blocks(actor, contract_id=contract_id, is_master=True)
    )
    assert rows, f"contract {contract_id} has no master room block"
    return rows[0]


# --------------------------------------------------------------------------
# Tier 2 - state progression on the lead
# --------------------------------------------------------------------------


def seed_calendar_and_package(
    api: ApiClient,
    *,
    stay_dates: Optional[Sequence[str]] = None,
    inventory: Optional[Dict[str, Any]] = None,
    package: Optional[Dict[str, Any]] = None,
    account: Optional[Dict[str, Any]] = None,
    reset: bool = True,
) -> World:
    """Clock, client organization, house calendar and concession package.

    This is the common prefix of every workflow in PRD section 3.
    """
    if reset:
        reset_clock(api)
    acct = seed_account(api, **(account or {}))
    days = seed_inventory_days(api, stay_dates, **(inventory or {}))
    pkg = seed_package(api, package)
    return {
        "account_id": acct["id"],
        "account": acct,
        "group_contact": make_group_contact_headers(acct["id"]),
        "inventory_days": days,
        "stay_dates": list(stay_dates) if stay_dates is not None else list(C.STAY_DATES),
        "package_id": pkg["id"],
        "package": pkg,
    }


def seed_qualified_lead(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    lead: Optional[Dict[str, Any]] = None,
    actor: Dict[str, str] = SALES_MANAGER,
    **setup: Any,
) -> World:
    """A lead scored and routed by the qualification fork of PRD 3.2."""
    world = dict(world) if world is not None else seed_calendar_and_package(api, **setup)
    row = seed_lead(api, world["account_id"], actor=actor, **(lead or {}))
    world["lead_id"] = row["id"]
    world["lead"] = get_success_data(api.qualify_lead(row["id"], actor))
    world["lead_version"] = world["lead"]["version"]
    return world


def seed_displacement_analysis(
    api: ApiClient,
    world: World,
    *,
    analysis_variant: str = "FORECAST_BASED",
    requester: Dict[str, str] = REVENUE_MANAGER,
) -> Dict[str, Any]:
    """Request a displacement study against the lead (PRD 3.3)."""
    return get_success_data(
        api.create_displacement_analysis(
            F.displacement_analysis_payload(
                world["lead_id"], analysis_variant=analysis_variant
            ),
            requester,
        ),
        201,
    )


def decide_displacement_analysis(
    api: ApiClient,
    world: World,
    analysis_id: str,
    *,
    decision: str = "APPROVE",
    override_reason: Optional[str] = None,
    decider: Dict[str, str] = REVENUE_MANAGER_ALT,
) -> Dict[str, Any]:
    """Decide a study, reading the lead version immediately beforehand.

    PRD 2.7 makes ``expected_lead_version`` mandatory on this operation, so
    the guard token is always the lead's freshly read current version.
    """
    version = lead_version(api, world["lead_id"])
    decided = get_success_data(
        api.decide_displacement_analysis(
            analysis_id,
            F.decide_payload(
                decision=decision,
                expected_lead_version=version,
                override_reason=override_reason,
            ),
            decider,
        )
    )
    world["lead_version"] = lead_version(api, world["lead_id"])
    return decided


def seed_cleared_lead(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    analysis_variant: str = "FORECAST_BASED",
    requester: Dict[str, str] = REVENUE_MANAGER,
    decider: Dict[str, str] = REVENUE_MANAGER_ALT,
    override_reason: Optional[str] = None,
    **setup: Any,
) -> World:
    """A lead cleared by an approved displacement study (PRD 3.3)."""
    world = world if world is not None else seed_qualified_lead(api, **setup)
    analysis = seed_displacement_analysis(
        api, world, analysis_variant=analysis_variant, requester=requester
    )
    world["analysis_id"] = analysis["id"]
    world["analysis"] = analysis
    world["decided_analysis"] = decide_displacement_analysis(
        api, world, analysis["id"], decider=decider, override_reason=override_reason
    )
    return world


# --------------------------------------------------------------------------
# Tier 3 - full-lifecycle shortcuts
# --------------------------------------------------------------------------


def seed_draft_quote(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    quote: Optional[Dict[str, Any]] = None,
    actor: Dict[str, str] = SALES_MANAGER,
    **setup: Any,
) -> World:
    """A quote drafted against a cleared lead (PRD 3.4)."""
    world = world if world is not None else seed_cleared_lead(api, **setup)
    row = get_success_data(
        api.create_rate_quote(
            F.rate_quote_payload(
                world["lead_id"],
                world["package_id"],
                world["lead_version"],
                **(quote or {}),
            ),
            actor,
        ),
        201,
    )
    world["quote_id"] = row["id"]
    world["quote"] = row
    return world


def seed_proposed_quote(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    actor: Dict[str, str] = SALES_MANAGER,
    **setup: Any,
) -> World:
    """A quote sent to the client, holding rooms (PRD 3.4)."""
    world = world if world is not None else seed_draft_quote(api, **setup)
    world["quote"] = get_success_data(api.propose_rate_quote(world["quote_id"], actor))
    world["lead_version"] = lead_version(api, world["lead_id"])
    return world


def seed_accepted_quote(
    api: ApiClient, world: Optional[World] = None, **setup: Any
) -> World:
    """A quote accepted by the owning GroupContact (PRD 3.4)."""
    world = world if world is not None else seed_proposed_quote(api, **setup)
    world["quote"] = get_success_data(
        api.accept_rate_quote(world["quote_id"], world["group_contact"])
    )
    world["lead_version"] = lead_version(api, world["lead_id"])
    return world


def seed_draft_contract(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    contract: Optional[Dict[str, Any]] = None,
    actor: Dict[str, str] = CONTRACT_ADMIN,
    **setup: Any,
) -> World:
    """An accepted quote papered into a DRAFT contract (PRD 3.5)."""
    world = world if world is not None else seed_accepted_quote(api, **setup)
    row = get_success_data(
        api.create_contract(
            F.contract_payload(world["quote_id"], **(contract or {})), actor
        ),
        201,
    )
    world["contract_id"] = row["id"]
    world["contract"] = row
    return world


def seed_sent_contract(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    actor: Dict[str, str] = CONTRACT_ADMIN,
    **setup: Any,
) -> World:
    """A contract issued to the client for signature (PRD 3.5)."""
    world = world if world is not None else seed_draft_contract(api, **setup)
    world["contract"] = get_success_data(api.send_contract(world["contract_id"], actor))
    return world


def seed_signed_contract(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    signature_name: str = "R. Buyer",
    actor: Dict[str, str] = CONTRACT_ADMIN,
    **setup: Any,
) -> World:
    """A countersigned contract with its master room block (PRD 3.5).

    The countersignature cascade mints the master block, so the world gains
    ``master_block_id`` and ``master_version`` here.
    """
    world = world if world is not None else seed_sent_contract(api, **setup)
    world["contract"] = get_success_data(
        api.sign_contract(
            world["contract_id"], F.sign_payload(signature_name=signature_name), actor
        )
    )
    master = master_block_of(api, world["contract_id"])
    world["master_block_id"] = master["id"]
    world["master_block"] = master
    world["master_version"] = master["version"]
    return world


def seed_open_master_block(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    actor: Dict[str, str] = RESERVATIONS_AGENT,
    **setup: Any,
) -> World:
    """The master block opened for pickup (PRD 3.6)."""
    world = world if world is not None else seed_signed_contract(api, **setup)
    world["master_block"] = get_success_data(
        api.open_room_block(world["master_block_id"], actor)
    )
    world["master_version"] = world["master_block"]["version"]
    return world


def seed_sub_block(
    api: ApiClient,
    world: World,
    *,
    name: str = "SUB-A",
    nightly_allotments: Optional[List[Dict[str, Any]]] = None,
    parent_block_id: Optional[str] = None,
    actor: Dict[str, str] = CONTRACT_ADMIN,
) -> Dict[str, Any]:
    """Carve a sub-block, re-reading the parent version guard first (PRD 2.7)."""
    parent = parent_block_id or world["master_block_id"]
    return get_success_data(
        api.create_room_block(
            F.sub_block_payload(
                parent,
                block_version(api, parent),
                name=name,
                nightly_allotments=nightly_allotments,
            ),
            actor,
        ),
        201,
    )


# --------------------------------------------------------------------------
# Tier 4 - accumulation and threshold targeting
# --------------------------------------------------------------------------


def seed_reservation(
    api: ApiClient,
    block_id: str,
    *,
    actor: Dict[str, str] = RESERVATIONS_AGENT,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Write one rooming-list entry into an OPEN block (PRD 3.6)."""
    return get_success_data(
        api.create_reservation(F.reservation_payload(block_id, **kwargs), actor), 201
    )


def seed_reservations(
    api: ApiClient,
    block_id: str,
    specs: Sequence[Dict[str, Any]],
    *,
    actor: Dict[str, str] = RESERVATIONS_AGENT,
) -> List[Dict[str, Any]]:
    """Write a rooming list in ``created_at`` order (PRD 3.6)."""
    return [seed_reservation(api, block_id, actor=actor, **spec) for spec in specs]


def advance_reservation(
    api: ApiClient,
    reservation_id: str,
    to_status: str,
    *,
    actor: Dict[str, str] = RESERVATIONS_AGENT,
) -> Dict[str, Any]:
    """Move a guest along the stay (PRD 3.6)."""
    return get_success_data(
        api.advance_reservation(reservation_id, F.advance_payload(to_status), actor)
    )


def confirm_reservations(
    api: ApiClient,
    reservation_ids: Sequence[str],
    *,
    actor: Dict[str, str] = RESERVATIONS_AGENT,
) -> List[Dict[str, Any]]:
    """Confirm every named reservation so it enters the actualized set.

    PRD 3.7: "A reservation actualizes when its status is CONFIRMED,
    CHECKED_IN, CHECKED_OUT, or NO_SHOW. PENDING rows never actualize".
    """
    return [
        advance_reservation(api, rid, "CONFIRMED", actor=actor) for rid in reservation_ids
    ]


def pickup_summary(
    api: ApiClient, block_id: str, *, actor: Dict[str, str] = CONTRACT_ADMIN
) -> Dict[str, Any]:
    """The read-only both-bases projection of PRD 3.7."""
    return get_success_data(api.get_pickup_summary(block_id, actor))


def cutoff_block(
    api: ApiClient,
    block_id: str,
    *,
    actor: Dict[str, str] = RESERVATIONS_AGENT,
    at_clock: Optional[str] = C.CUTOFF_CLOCK,
) -> Dict[str, Any]:
    """Cut a block off, moving the clock to its cutoff date first (PRD 3.7)."""
    if at_clock is not None:
        set_clock(api, at_clock)
    return get_success_data(api.cutoff_room_block(block_id, actor))


def seed_cut_off_master(
    api: ApiClient,
    world: World,
    *,
    at_clock: Optional[str] = C.CUTOFF_CLOCK,
    actor: Dict[str, str] = RESERVATIONS_AGENT,
) -> World:
    """The master block cut off, releasing what it never sold (PRD 3.7)."""
    world["master_block"] = cutoff_block(
        api, world["master_block_id"], actor=actor, at_clock=at_clock
    )
    world["master_version"] = world["master_block"]["version"]
    return world


# --------------------------------------------------------------------------
# Tier 5 - finalization and terminal states
# --------------------------------------------------------------------------


def seed_draft_reconciliation(
    api: ApiClient,
    world: World,
    *,
    preparer: Dict[str, str] = ACCOUNTING_CLERK,
    at_clock: Optional[str] = C.POST_DEPARTURE_CLOCK,
) -> World:
    """Open the post-event settlement (PRD 3.9).

    The contract version guard of PRD 2.7 is read immediately before the
    write, and the clock is walked past the contract's departure date so the
    ``ERR_EVENT_NOT_CONCLUDED`` gate of priority 17 is satisfied.
    """
    if at_clock is not None:
        set_clock(api, at_clock)
    row = get_success_data(
        api.create_reconciliation(
            world["contract_id"],
            F.reconciliation_payload(contract_version(api, world["contract_id"])),
            preparer,
        ),
        201,
    )
    world["reconciliation_id"] = row["id"]
    world["reconciliation"] = row
    return world


def seed_finalized_reconciliation(
    api: ApiClient,
    world: World,
    *,
    finalizer: Dict[str, str] = ACCOUNTING_CLERK_ALT,
) -> World:
    """Finalize the settlement with a second clerk (PRD 3.9).

    "the acting X-User-ID must differ from the settlement's
    prepared_by_user_id ... even though both halves are AccountingClerk work."
    """
    world["reconciliation"] = get_success_data(
        api.finalize_reconciliation(world["reconciliation_id"], finalizer)
    )
    return world


def seed_settled_contract(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    reservation_specs: Optional[Sequence[Dict[str, Any]]] = None,
    confirm: bool = True,
    **setup: Any,
) -> World:
    """The whole arc from registration to a finalized settlement.

    Signs the contract, opens the master block, writes and confirms a rooming
    list, cuts the block off after its cutoff date, then opens and finalizes
    the settlement of PRD 3.9 with two different clerks.
    """
    world = world if world is not None else seed_open_master_block(api, **setup)
    if reservation_specs:
        rows = seed_reservations(api, world["master_block_id"], reservation_specs)
        world["reservation_ids"] = [r["id"] for r in rows]
        if confirm:
            confirm_reservations(api, world["reservation_ids"])
    seed_cut_off_master(api, world)
    seed_draft_reconciliation(api, world)
    seed_finalized_reconciliation(api, world)
    return world
