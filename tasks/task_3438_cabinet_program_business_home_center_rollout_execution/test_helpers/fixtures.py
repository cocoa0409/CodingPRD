"""Composite fixtures that walk the Cabinet Program Rollout API to a wanted state.

Every test starts against an empty deployment (the harness restarts the server
per test), so each test builds the world it needs through the public API only.
These helpers capture the multi-step preambles the domain demands:

  Tier 1  clock control, primitive creates, reads
  Tier 2  program onboarding: account -> program -> first line -> ACTIVE
  Tier 3  order pipeline: submit -> acknowledge -> schedule -> production ->
          manufacturing -> shipment -> delivery
  Tier 4  claims and replacement logistics
  Tier 5  program transition (supersede / display resets / disposition) and
          the retail design-service chain

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure, not a confusing assertion error. Fixtures never
advance the logical clock past the default reading: they build at the default
and let the test move the clock afterwards (slots must be opened for a week
not before the current one, so week defaults assume the default clock).
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_DEFAULT
from .test_users import (
    CLAIMS_ADJUSTER_HEADERS,
    FIELD_SERVICE_REP_HEADERS,
    LOGISTICS_COORDINATOR_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    PLANT_SCHEDULER_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    make_dealer_rep_headers,
    make_retail_designer_headers,
)


# ═══ Tier 1: clock, primitive creates, reads ═══════════════════════════════

def reset_clock(api: ApiClient, to_iso8601: str = CLOCK_DEFAULT) -> Dict[str, Any]:
    """Set the logical clock (PlatformAdmin; unprefixed endpoint)."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), PLATFORM_ADMIN_HEADERS))


def create_account(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_account(f.account_payload(**overrides), PLATFORM_ADMIN_HEADERS))


def create_retail_account(api: ApiClient, store_codes: Optional[List[str]] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_account(f.retail_account_payload(store_codes, **overrides), PLATFORM_ADMIN_HEADERS)
    )


def set_account_status(api: ApiClient, account_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_account_status(account_id, f.account_status_payload(to_status), PLATFORM_ADMIN_HEADERS)
    )


def create_program(api: ApiClient, account_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_program(f.program_payload(account_id, **overrides), PROGRAM_MANAGER_HEADERS)
    )


def create_finish_batch(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_finish_batch(f.finish_batch_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def create_production_slot(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_production_slot(f.production_slot_payload(**overrides), PLANT_SCHEDULER_HEADERS)
    )


def get_account(api: ApiClient, account_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_account(account_id, headers or PROGRAM_MANAGER_HEADERS))


def get_program(api: ApiClient, program_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_program(program_id, headers or PROGRAM_MANAGER_HEADERS))


def get_line(api: ApiClient, line_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_line(line_id, headers or PROGRAM_MANAGER_HEADERS))


def get_order(api: ApiClient, order_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_order(order_id, headers or PROGRAM_MANAGER_HEADERS))


def get_design_job(api: ApiClient, job_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_design_job(job_id, headers or PROGRAM_MANAGER_HEADERS))


def get_shipment(api: ApiClient, shipment_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_shipment(shipment_id, headers or LOGISTICS_COORDINATOR_HEADERS))


def get_claim(api: ApiClient, claim_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_claim(claim_id, headers or CLAIMS_ADJUSTER_HEADERS))


def get_replacement_order(api: ApiClient, replacement_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_replacement_order(replacement_id, headers or PLANT_SCHEDULER_HEADERS))


def get_display_reset(api: ApiClient, reset_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_display_reset(reset_id, headers or PROGRAM_MANAGER_HEADERS))


def list_orders(api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api.list_orders(headers or PROGRAM_MANAGER_HEADERS, params=params))


def list_lines(api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api.list_lines(headers or PROGRAM_MANAGER_HEADERS, params=params))


def list_production_slots(api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api.list_production_slots(headers or PLANT_SCHEDULER_HEADERS, params=params))


def list_shipments(api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api.list_shipments(headers or LOGISTICS_COORDINATOR_HEADERS, params=params))


def list_claims(api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api.list_claims(headers or CLAIMS_ADJUSTER_HEADERS, params=params))


def list_replacement_orders(api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api.list_replacement_orders(headers or PLANT_SCHEDULER_HEADERS, params=params))


def list_display_resets(api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api.list_display_resets(headers or PROGRAM_MANAGER_HEADERS, params=params))


# ═══ Tier 2: program onboarding ════════════════════════════════════════════

def create_first_line(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create the program's first line on a DRAFT program. The program's
    version is read fresh so the OCC field is always current."""
    program = get_program(api, program_id)
    return get_success_data(
        api.create_program_line(
            program_id,
            f.program_line_payload(program["version"], **overrides),
            PROGRAM_MANAGER_HEADERS,
        )
    )


def activate_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_program(program_id, PROGRAM_MANAGER_HEADERS))


def supersede_program_line(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a superseding line on an ACTIVE program. The OCC field is read
    fresh; the cascade (old line SUNSETTING, program TRANSITIONING, display
    resets, repricing) fires server-side. Returns the new ACTIVE line."""
    program = get_program(api, program_id)
    return get_success_data(
        api.create_program_line(
            program_id,
            f.program_line_payload(program["version"], **overrides),
            PROGRAM_MANAGER_HEADERS,
        )
    )


def setup_active_program(
    api: ApiClient,
    account_overrides: Optional[Dict] = None,
    program_overrides: Optional[Dict] = None,
    families: Optional[List[Dict[str, Any]]] = None,
    line_overrides: Optional[Dict] = None,
    retail: bool = False,
    store_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Account + program + first line, activated. The most common preamble.

    Returns {"account", "program", "line"}. ``program`` is re-read after
    activation so its version reflects the activation increment.
    """
    reset_clock(api)
    if retail:
        account = create_retail_account(api, store_codes, **(account_overrides or {}))
    else:
        account = create_account(api, **(account_overrides or {}))
    program = create_program(api, account["id"], **(program_overrides or {}))
    line_kwargs = dict(line_overrides or {})
    if families is not None:
        line_kwargs["families"] = families
    line = create_first_line(api, program["id"], **line_kwargs)
    activate_program(api, program["id"])
    return {
        "account": account,
        "program": get_program(api, program["id"]),
        "line": line,
    }


# ═══ Tier 3: order pipeline ════════════════════════════════════════════════

def place_order(api: ApiClient, account: Dict, program: Dict, **overrides: Any) -> Dict[str, Any]:
    """Direct dealer/builder order placement. The DealerRep identity is the
    account's id, exactly as the ownership rule requires."""
    return get_success_data(
        api.create_order(
            f.order_payload(account["id"], program["id"], **overrides),
            make_dealer_rep_headers(account["id"]),
        )
    )


def place_store_order(api: ApiClient, account: Dict, program: Dict, store_code: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_order(
            f.store_order_payload(account["id"], program["id"], store_code, **overrides),
            make_dealer_rep_headers(account["id"]),
        )
    )


def acknowledge_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_order(order_id, f.order_transition_payload("ACKNOWLEDGED"), PROGRAM_MANAGER_HEADERS)
    )


def schedule_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_order(order_id, f.order_transition_payload("SCHEDULED"), PLANT_SCHEDULER_HEADERS)
    )


def start_production(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_order(order_id, f.order_transition_payload("IN_PRODUCTION"), PLANT_SCHEDULER_HEADERS)
    )


def complete_manufacturing(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_order(order_id, f.order_transition_payload("MFG_COMPLETE"), PLANT_SCHEDULER_HEADERS)
    )


def invoice_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_order_financial(order_id, f.order_financial_payload("INVOICED"), PROGRAM_MANAGER_HEADERS)
    )


def pay_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_order_financial(order_id, f.order_financial_payload("PAID"), PROGRAM_MANAGER_HEADERS)
    )


def cancel_order(api: ApiClient, order_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.cancel_order(order_id, headers or PROGRAM_MANAGER_HEADERS))


def get_shipment_for_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    """An order's shipment is auto-created at MFG_COMPLETE and is discoverable
    only through the reverse filter."""
    shipments = list_shipments(api, params={"order_id": order_id})
    assert len(shipments) == 1, f"expected exactly one shipment for order {order_id}, got {len(shipments)}"
    return shipments[0]


def transition_shipment(api: ApiClient, shipment_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_shipment(
            shipment_id, f.shipment_transition_payload(to_status), LOGISTICS_COORDINATOR_HEADERS
        )
    )


def deliver_shipment(api: ApiClient, shipment_id: str) -> Dict[str, Any]:
    """PLANNED -> LOADED -> IN_TRANSIT -> DELIVERED; the linked order follows
    to SHIPPED then DELIVERED."""
    transition_shipment(api, shipment_id, "LOADED")
    transition_shipment(api, shipment_id, "IN_TRANSIT")
    return transition_shipment(api, shipment_id, "DELIVERED")


def setup_submitted_order(
    api: ApiClient,
    order_overrides: Optional[Dict] = None,
    **program_kwargs: Any,
) -> Dict[str, Any]:
    """Active program plus one SUBMITTED order. Returns the setup_active_program
    keys plus "order"."""
    world = setup_active_program(api, **program_kwargs)
    world["order"] = place_order(api, world["account"], world["program"], **(order_overrides or {}))
    return world


def setup_acknowledged_order(
    api: ApiClient,
    order_overrides: Optional[Dict] = None,
    slot_overrides: Optional[Dict] = None,
    batch_overrides: Optional[Dict] = None,
    with_slot: bool = True,
    with_batch: bool = True,
    **program_kwargs: Any,
) -> Dict[str, Any]:
    """Submitted order plus the standing capacity/finish data, acknowledged.
    Returns keys of setup_submitted_order plus "slot" and "batch"."""
    world = setup_submitted_order(api, order_overrides, **program_kwargs)
    if with_slot:
        world["slot"] = create_production_slot(api, **(slot_overrides or {}))
    if with_batch:
        world["batch"] = create_finish_batch(api, **(batch_overrides or {}))
    world["order"] = acknowledge_order(api, world["order"]["id"])
    return world


def setup_scheduled_order(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Acknowledged order scheduled into a slot."""
    world = setup_acknowledged_order(api, **kwargs)
    world["order"] = schedule_order(api, world["order"]["id"])
    return world


def setup_delivered_order(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The full fulfillment chain: order driven SUBMITTED -> DELIVERED with
    its auto-created shipment LOADED/IN_TRANSIT/DELIVERED. Returns keys of
    setup_acknowledged_order plus "shipment". The clock stays at the default
    reading, so the shipment's delivered_at is the default instant."""
    world = setup_scheduled_order(api, **kwargs)
    world["order"] = start_production(api, world["order"]["id"])
    world["order"] = complete_manufacturing(api, world["order"]["id"])
    world["shipment"] = get_shipment_for_order(api, world["order"]["id"])
    world["shipment"] = deliver_shipment(api, world["shipment"]["id"])
    world["order"] = get_order(api, world["order"]["id"])
    return world


# ═══ Tier 4: claims and replacement logistics ══════════════════════════════

def file_claim(
    api: ApiClient,
    shipment: Dict,
    order: Dict,
    filer_headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File a damage claim. Default filer is the shared LogisticsCoordinator
    identity (not ownership-gated); DealerRep filers must pass
    make_dealer_rep_headers(order["account_id"])."""
    return get_success_data(
        api.create_claim(
            f.claim_payload(shipment["id"], order["id"], **overrides),
            filer_headers or LOGISTICS_COORDINATOR_HEADERS,
        )
    )


def transition_claim(
    api: ApiClient,
    claim_id: str,
    to_status: str,
    adjuster_headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_claim(
            claim_id,
            f.claim_transition_payload(to_status, **overrides),
            adjuster_headers or CLAIMS_ADJUSTER_HEADERS,
        )
    )


def review_claim(api: ApiClient, claim_id: str, adjuster_headers: Optional[Dict] = None) -> Dict[str, Any]:
    return transition_claim(api, claim_id, "UNDER_REVIEW", adjuster_headers)


def approve_claim(
    api: ApiClient,
    claim_id: str,
    resolution: str,
    adjuster_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """FILED -> UNDER_REVIEW -> APPROVED with the given resolution. The default
    decider (shared ClaimsAdjuster identity) differs from the default filer,
    satisfying segregation of duties."""
    review_claim(api, claim_id, adjuster_headers)
    return transition_claim(api, claim_id, "APPROVED", adjuster_headers, resolution=resolution)


def deny_claim(api: ApiClient, claim_id: str, adjuster_headers: Optional[Dict] = None) -> Dict[str, Any]:
    """FILED -> UNDER_REVIEW -> DENIED."""
    review_claim(api, claim_id, adjuster_headers)
    return transition_claim(api, claim_id, "DENIED", adjuster_headers)


def get_replacement_for_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    replacements = list_replacement_orders(api, params={"damage_claim_id": claim_id})
    assert len(replacements) == 1, (
        f"expected exactly one replacement for claim {claim_id}, got {len(replacements)}"
    )
    return replacements[0]


def setup_approved_replacement(
    api: ApiClient,
    claimed_qty: int = 1,
    order_quantity: int = 2,
    filer_headers: Optional[Dict] = None,
    adjuster_headers: Optional[Dict] = None,
    **order_kwargs: Any,
) -> Dict[str, Any]:
    """Delivered order + claim approved with resolution REPLACEMENT, returning
    the delivered world plus "claim" and "replacement" (status CREATED)."""
    order_overrides = dict(order_kwargs.pop("order_overrides", {}) or {})
    order_overrides.setdefault("lines", [f.order_line(quantity=order_quantity)])
    world = setup_delivered_order(api, order_overrides=order_overrides, **order_kwargs)
    world["claim"] = file_claim(
        api, world["shipment"], world["order"], filer_headers, claimed_qty=claimed_qty
    )
    world["claim"] = approve_claim(api, world["claim"]["id"], "REPLACEMENT", adjuster_headers)
    world["replacement"] = get_replacement_for_claim(api, world["claim"]["id"])
    return world


def transition_replacement(api: ApiClient, replacement_id: str, to_status: str) -> Dict[str, Any]:
    """Drive the replacement machine. Role pins per the PRD: scheduling,
    production and cancellation belong to PlantScheduler; shipping, receiving
    and remake to LogisticsCoordinator."""
    if to_status in ("SHIPPED", "RECEIVED", "REMAKE"):
        headers = LOGISTICS_COORDINATOR_HEADERS
    else:
        headers = PLANT_SCHEDULER_HEADERS
    return get_success_data(
        api.transition_replacement_order(
            replacement_id, f.replacement_transition_payload(to_status), headers
        )
    )


# ═══ Tier 5: program transition and the retail design service ══════════════

def setup_transitioning_program(
    api: ApiClient,
    store_codes: Optional[List[str]] = None,
    disposition_qty: int = 0,
    new_line_overrides: Optional[Dict] = None,
    **program_kwargs: Any,
) -> Dict[str, Any]:
    """RETAIL program superseded once: old line SUNSETTING with the given
    disposition quantity, program TRANSITIONING, one PLANNED display reset per
    store code. Returns {"account", "program", "line1", "line2", "resets"}."""
    codes = list(store_codes) if store_codes is not None else ["ST-1"]
    program_kwargs.setdefault("retail", True)
    program_kwargs.setdefault("store_codes", codes)
    world = setup_active_program(api, **program_kwargs)
    line2_kwargs = {"line_code": "L2", "effective_start_week": f.WEEK_PLUS_2}
    if disposition_qty is not None:
        line2_kwargs["include_disposition_qty"] = True
        line2_kwargs["old_line_disposition_qty"] = disposition_qty
    line2_kwargs.update(new_line_overrides or {})
    line2 = supersede_program_line(api, world["program"]["id"], **line2_kwargs)
    resets = list_display_resets(api, params={"program_id": world["program"]["id"]})
    return {
        "account": world["account"],
        "program": get_program(api, world["program"]["id"]),
        "line1": get_line(api, world["line"]["id"]),
        "line2": line2,
        "resets": resets,
    }


def append_disposition_action(api: ApiClient, line_id: str, action_type: str, qty: int) -> Dict[str, Any]:
    return get_success_data(
        api.append_disposition_action(
            line_id, f.disposition_action_payload(action_type, qty), PROGRAM_MANAGER_HEADERS
        )
    )


def transition_display_reset(
    api: ApiClient, reset_id: str, to_status: str, **fields: Any
) -> Dict[str, Any]:
    """Drive the reset machine. SCHEDULED/COMPLETE belong to FieldServiceRep;
    WAIVED to ProgramManager."""
    headers = PROGRAM_MANAGER_HEADERS if to_status == "WAIVED" else FIELD_SERVICE_REP_HEADERS
    return get_success_data(
        api.transition_display_reset(
            reset_id, f.display_reset_transition_payload(to_status, **fields), headers
        )
    )


def create_design_job(
    api: ApiClient,
    account: Dict,
    program: Dict,
    designer_id: str = "des-1",
    **overrides: Any,
) -> Dict[str, Any]:
    """Book a design job; the caller's id becomes designer_user_id and must be
    reused for every later transition of the job."""
    return get_success_data(
        api.create_design_job(
            f.design_job_payload(account["id"], program["id"], **overrides),
            make_retail_designer_headers(designer_id),
        )
    )


def transition_design_job(
    api: ApiClient, job_id: str, to_status: str, designer_id: str = "des-1", **fields: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_design_job(
            job_id,
            f.design_job_transition_payload(to_status, **fields),
            make_retail_designer_headers(designer_id),
        )
    )


def quote_design_job(
    api: ApiClient,
    job_id: str,
    designer_id: str = "des-1",
    layout_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Walk a job REQUESTED -> MEASURED -> LAYOUT_READY -> QUOTED."""
    lines = layout_lines if layout_lines is not None else [f.order_line(quantity=1)]
    transition_design_job(api, job_id, "MEASURED", designer_id)
    transition_design_job(api, job_id, "LAYOUT_READY", designer_id, layout_lines=lines)
    return transition_design_job(api, job_id, "QUOTED", designer_id)


def setup_quoted_design_job(
    api: ApiClient,
    designer_id: str = "des-1",
    layout_lines: Optional[List[Dict[str, Any]]] = None,
    **program_kwargs: Any,
) -> Dict[str, Any]:
    """RETAIL account with stores + ACTIVE program + a design job in QUOTED.
    Returns the program world plus "job" and "designer_id"."""
    program_kwargs.setdefault("retail", True)
    program_kwargs.setdefault("store_codes", ["ST-1", "ST-2"])
    world = setup_active_program(api, **program_kwargs)
    job = create_design_job(api, world["account"], world["program"], designer_id)
    job = quote_design_job(api, job["id"], designer_id, layout_lines)
    world["job"] = job
    world["designer_id"] = designer_id
    return world


def convert_design_job(
    api: ApiClient, job_id: str, designer_id: str = "des-1", **overrides: Any
) -> Dict[str, Any]:
    """QUOTED -> CONVERTED; returns the created SUBMITTED order."""
    return get_success_data(
        api.convert_design_job(
            job_id,
            f.design_job_convert_payload(**overrides),
            make_retail_designer_headers(designer_id),
        )
    )
