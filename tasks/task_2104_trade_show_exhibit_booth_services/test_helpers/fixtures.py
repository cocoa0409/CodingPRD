"""Composite setup helpers.

Every test starts against an empty database and a logical clock reading its
2026-08-01T00:00:00Z default, so these helpers rebuild whole precondition chains
(venue -> show -> exhibitor -> booth -> order -> invoice, and the freight, labor
and claim chains) out of PRD-declared endpoints only.

Identity threading: the Exhibitor role's X-User-ID is the acting Exhibitor row's
id and the WarehouseAgent role's X-User-ID is the id of the Warehouse the agent
staffs, so every ownership-gated call here uses make_exhibitor_headers(...) or
make_warehouse_agent_headers(...) with the real row id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK, SHOW_CALENDAR, SHOW_FORWARD_CHAIN, TEST_DEFAULTS
from .factories import (
    create_booth_payload,
    create_change_order_payload,
    create_crate_payload,
    create_damage_claim_payload,
    create_drayage_shipment_payload,
    create_exhibit_asset_payload,
    create_exhibit_design_payload,
    create_exhibitor_payload,
    create_invoice_payload,
    create_jurisdiction_payload,
    create_labor_call_payload,
    create_lead_capture_license_payload,
    create_refurb_work_order_payload,
    create_service_order_payload,
    create_show_payload,
    create_venue_payload,
    create_warehouse_payload,
    service_order_line,
)
from .test_users import (
    TEST_USERS,
    make_exhibitor_headers,
    make_warehouse_agent_headers,
)

OPS = TEST_USERS["show_operations_headers"]
OPS_ALT = TEST_USERS["show_operations_alt_headers"]
LABOR = TEST_USERS["labor_supervisor_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ADJUSTER_ALT = TEST_USERS["claims_adjuster_alt_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]
FINANCE_ALT = TEST_USERS["finance_controller_alt_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601, headers=OPS):
    """Reposition the logical show clock. Mutates no entity."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and reads
# ---------------------------------------------------------------------------

def create_venue(**overrides):
    return get_success_data(
        api_client.create_venue(create_venue_payload(**overrides), OPS))


def create_jurisdiction(venue_id, **overrides):
    return get_success_data(
        api_client.create_jurisdiction(venue_id,
                                       create_jurisdiction_payload(**overrides), OPS))


def create_warehouse(**overrides):
    return get_success_data(
        api_client.create_warehouse(create_warehouse_payload(**overrides), OPS))


def create_show(venue_id, **overrides):
    return get_success_data(
        api_client.create_show(create_show_payload(venue_id, **overrides), OPS))


def create_exhibitor(**overrides):
    return get_success_data(
        api_client.create_exhibitor(create_exhibitor_payload(**overrides), OPS))


def create_booth(show_id, exhibitor_id, **overrides):
    return get_success_data(
        api_client.create_booth(
            create_booth_payload(show_id, exhibitor_id, **overrides), OPS))


def get_venue(venue_id):
    return get_success_data(api_client.get_venue(venue_id, OPS))


def get_warehouse(warehouse_id):
    return get_success_data(api_client.get_warehouse(warehouse_id, OPS))


def get_show(show_id):
    return get_success_data(api_client.get_show(show_id, OPS))


def get_exhibitor(exhibitor_id):
    return get_success_data(api_client.get_exhibitor(exhibitor_id, OPS))


def get_booth(booth_id):
    return get_success_data(api_client.get_booth(booth_id, OPS))


def get_asset(asset_id):
    return get_success_data(api_client.get_exhibit_asset(asset_id, OPS))


def get_design(design_id):
    return get_success_data(api_client.get_exhibit_design(design_id, OPS))


def get_order(order_id):
    return get_success_data(api_client.get_service_order(order_id, OPS))


def get_crate(crate_id):
    return get_success_data(api_client.get_crate(crate_id, OPS))


def get_shipment(shipment_id):
    return get_success_data(api_client.get_drayage_shipment(shipment_id, OPS))


def get_labor_call(call_id):
    return get_success_data(api_client.get_labor_call(call_id, OPS))


def get_change_order(change_order_id):
    return get_success_data(api_client.get_change_order(change_order_id, OPS))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, OPS))


def get_claim(claim_id):
    return get_success_data(api_client.get_damage_claim(claim_id, OPS))


def get_refurb(refurb_id):
    return get_success_data(api_client.get_refurb_work_order(refurb_id, OPS))


def booth_version(booth_id):
    """Freshly re-read Booth.version, for pinning expected_booth_version."""
    return get_booth(booth_id)["version"]


def warehouse_version(warehouse_id):
    return get_warehouse(warehouse_id)["version"]


def order_version(order_id):
    return get_order(order_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def advance_show(show_id, to_status):
    """Single show lifecycle edge."""
    return get_success_data(
        api_client.set_show_status(show_id, {"to_status": to_status}, OPS))


def walk_show_to(show_id, target_status):
    """Walk the show forward one declared edge at a time until target_status."""
    if target_status == "DRAFT":
        return get_show(show_id)
    if target_status == "CANCELLED":
        return advance_show(show_id, "CANCELLED")
    show = None
    for status in SHOW_FORWARD_CHAIN[1:]:
        show = advance_show(show_id, status)
        if status == target_status:
            return show
    return show


def suspend_exhibitor(exhibitor_id, reason="Credit review pending"):
    return get_success_data(api_client.set_exhibitor_status(
        exhibitor_id, {"to_status": "SUSPENDED", "reason": reason}, FINANCE))


def reinstate_exhibitor(exhibitor_id):
    return get_success_data(api_client.set_exhibitor_status(
        exhibitor_id, {"to_status": "ACTIVE"}, FINANCE))


# ---------------------------------------------------------------------------
# Tier 2: show ground - venue, show, exhibitor, booth
# ---------------------------------------------------------------------------

def setup_show_ground(show_status="OPEN_FOR_ORDERS",
                      clock=BASE_CLOCK,
                      credit_limit_cents=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
                      booth_number="1024",
                      booth_sqft=400,
                      booth_type="ISLAND",
                      venue_overrides=None,
                      show_overrides=None,
                      exhibitor_overrides=None,
                      with_warehouse=False,
                      warehouse_overrides=None,
                      with_jurisdiction=False,
                      jurisdiction_overrides=None):
    """Venue + show walked to show_status + exhibitor + one booth.

    Returns a dict with keys venue, show, exhibitor, booth, and optionally
    warehouse and jurisdiction. The booth entry is the row as created; call
    get_booth() or booth_version() to re-read it after later mutations.
    """
    if clock is not None:
        set_clock(clock)
    venue = create_venue(**(venue_overrides or {}))
    result = {"venue": venue}
    if with_warehouse:
        result["warehouse"] = create_warehouse(**(warehouse_overrides or {}))
    if with_jurisdiction:
        result["jurisdiction"] = create_jurisdiction(
            venue["id"], **(jurisdiction_overrides or {}))
    show = create_show(venue["id"], **(show_overrides or {}))
    exhibitor = create_exhibitor(credit_limit_cents=credit_limit_cents,
                                 **(exhibitor_overrides or {}))
    booth = create_booth(show["id"], exhibitor["id"], booth_number=booth_number,
                         sqft=booth_sqft, booth_type=booth_type)
    if show_status != "DRAFT":
        show = walk_show_to(show["id"], show_status)
    result["show"] = show
    result["exhibitor"] = exhibitor
    result["booth"] = get_booth(booth["id"])
    return result


def add_booth(ground, booth_number, exhibitor_id=None, sqft=400, booth_type="ISLAND"):
    """Second (or third) booth on the same show for the same or another exhibitor."""
    return create_booth(ground["show"]["id"], exhibitor_id or ground["exhibitor"]["id"],
                        booth_number=booth_number, sqft=sqft, booth_type=booth_type)


# ---------------------------------------------------------------------------
# Tier 3: exhibit designs and assets
# ---------------------------------------------------------------------------

def create_design(exhibitor_id, booth_id, **overrides):
    return get_success_data(api_client.create_exhibit_design(
        create_exhibit_design_payload(exhibitor_id, booth_id, **overrides),
        make_exhibitor_headers(exhibitor_id)))


def quote_design(design_id, exhibitor_id, **payload):
    return get_success_data(api_client.quote_design(
        design_id, dict(payload), make_exhibitor_headers(exhibitor_id)))


def decide_design(design_id, decision, note=None):
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.decide_design(design_id, payload, OPS))


def release_design(design_id):
    return get_success_data(api_client.release_design(design_id, OPS))


def create_quoted_design(exhibitor_id, booth_id, **overrides):
    """DRAFT design walked to QUOTED with both variants stored."""
    design = create_design(exhibitor_id, booth_id, **overrides)
    return quote_design(design["id"], exhibitor_id)


def create_approved_design(exhibitor_id, booth_id, **overrides):
    design = create_quoted_design(exhibitor_id, booth_id, **overrides)
    return decide_design(design["id"], "APPROVE")


def create_design_with_revisions(exhibitor_id, booth_id, revisions, **overrides):
    """Design cycled QUOTED -> DRAFT `revisions` times, left QUOTED."""
    design = create_design(exhibitor_id, booth_id, **overrides)
    design = quote_design(design["id"], exhibitor_id)
    for _ in range(revisions):
        design = decide_design(design["id"], "REQUEST_REVISION")
        design = quote_design(design["id"], exhibitor_id)
    return design


def register_asset(exhibitor_id, **overrides):
    return get_success_data(api_client.create_exhibit_asset(
        create_exhibit_asset_payload(exhibitor_id, **overrides),
        make_exhibitor_headers(exhibitor_id)))


def move_asset(asset_id, to_status, warehouse_id=None, headers=OPS):
    payload = {"to_status": to_status}
    if warehouse_id is not None:
        payload["warehouse_id"] = warehouse_id
    return get_success_data(api_client.asset_lifecycle(asset_id, payload, headers))


def create_stored_asset(exhibitor_id, warehouse_id, **overrides):
    """Registered asset walked IN_DESIGN -> FABRICATED -> IN_STORAGE."""
    asset = register_asset(exhibitor_id, **overrides)
    move_asset(asset["id"], "FABRICATED")
    return move_asset(asset["id"], "IN_STORAGE", warehouse_id=warehouse_id)


# ---------------------------------------------------------------------------
# Tier 3: service orders
# ---------------------------------------------------------------------------

def place_order(booth_id, exhibitor_id, lines=None, expected_booth_version=None,
                actor="exhibitor", **overrides):
    """Create a service order, pinning the booth version freshly unless one is
    supplied. `actor` selects the acting operator: the exhibitor itself or the
    show operations desk."""
    if expected_booth_version is None:
        expected_booth_version = booth_version(booth_id)
    payload = create_service_order_payload(booth_id, expected_booth_version, **overrides)
    if lines is not None:
        payload["lines"] = lines
    headers = make_exhibitor_headers(exhibitor_id) if actor == "exhibitor" else OPS
    return get_success_data(api_client.create_service_order(payload, headers))


def advance_fulfillment(order_id, to_status, note=None, headers=OPS):
    payload = {"to_status": to_status}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.service_order_fulfillment(order_id, payload, headers))


def list_order_lines(order_id, params=None):
    resp = api_client.list_service_order_lines(order_id, OPS, params=params)
    return get_success_data(resp)


TWO_LINE_ORDER = [
    service_order_line(1, "ELEC-20A", 4, 32500, 0),
    service_order_line(2, "ELEC-LBR", 3, 21750, 0.10),
]


def setup_order_ground(show_status="OPEN_FOR_ORDERS", lines=None, **ground_kwargs):
    """Show ground plus one service order on the booth. Returns the ground dict
    with an extra `order` key."""
    ground = setup_show_ground(show_status=show_status, **ground_kwargs)
    ground["order"] = place_order(ground["booth"]["id"], ground["exhibitor"]["id"],
                                  lines=lines if lines is not None else TWO_LINE_ORDER)
    return ground


# ---------------------------------------------------------------------------
# Tier 3: invoices
# ---------------------------------------------------------------------------

def open_invoice(exhibitor_id, show_id, order_ids, headers=FINANCE):
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(exhibitor_id, show_id, order_ids), headers))


def issue_invoice(invoice_id, headers=FINANCE):
    return get_success_data(api_client.issue_invoice(invoice_id, headers))


def pay_invoice(invoice_id, amount_cents, headers=FINANCE):
    return get_success_data(
        api_client.pay_invoice(invoice_id, {"amount_cents": amount_cents}, headers))


def void_invoice(invoice_id, reason="Duplicate billing run", headers=FINANCE_ALT):
    return get_success_data(
        api_client.void_invoice(invoice_id, {"reason": reason}, headers))


def setup_draft_invoice(show_status="OPEN_FOR_ORDERS", lines=None, **ground_kwargs):
    """Show ground + one order + a DRAFT invoice sweeping it."""
    ground = setup_order_ground(show_status=show_status, lines=lines, **ground_kwargs)
    ground["invoice"] = open_invoice(ground["exhibitor"]["id"], ground["show"]["id"],
                                     [ground["order"]["id"]])
    return ground


def setup_issued_invoice(show_status="OPEN_FOR_ORDERS", lines=None, **ground_kwargs):
    """Show ground + one order + an ISSUED invoice, so the exhibitor balance
    carries the order total."""
    ground = setup_draft_invoice(show_status=show_status, lines=lines, **ground_kwargs)
    ground["invoice"] = issue_invoice(ground["invoice"]["id"])
    return ground


# ---------------------------------------------------------------------------
# Tier 3: freight - crates, check-ins, shipments
# ---------------------------------------------------------------------------

def register_crate(exhibitor_id, **overrides):
    return get_success_data(api_client.create_crate(
        create_crate_payload(exhibitor_id, **overrides),
        make_exhibitor_headers(exhibitor_id)))


def check_in_crate(crate_id, warehouse_id, expected_warehouse_version=None):
    if expected_warehouse_version is None:
        expected_warehouse_version = warehouse_version(warehouse_id)
    return get_success_data(api_client.warehouse_check_in(
        crate_id,
        {"warehouse_id": warehouse_id,
         "expected_warehouse_version": expected_warehouse_version},
        make_warehouse_agent_headers(warehouse_id)))


def move_crate(crate_id, to_status, shipment_id=None, note=None, headers=OPS):
    payload = {"to_status": to_status}
    if shipment_id is not None:
        payload["shipment_id"] = shipment_id
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.move_crate(crate_id, payload, headers))


def receive_shipment(show_id, exhibitor_id, crate_ids, warehouse_id=None, **overrides):
    """Create a drayage receipt. The acting warehouse agent is identified by the
    warehouse the receipt targets."""
    payload = create_drayage_shipment_payload(show_id, exhibitor_id, crate_ids,
                                              **overrides)
    if warehouse_id is not None and payload.get("channel") == "ADVANCE_WAREHOUSE":
        payload["warehouse_id"] = warehouse_id
    agent_id = warehouse_id or payload.get("warehouse_id")
    return get_success_data(api_client.create_drayage_shipment(
        payload, make_warehouse_agent_headers(agent_id)))


def set_shipment_hold(shipment_id, hold_flag, reason=None, headers=OPS):
    payload = {"hold_flag": hold_flag}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.set_shipment_hold(shipment_id, payload, headers))


def run_storage_billing(warehouse_id, as_of):
    return get_success_data(api_client.run_storage_billing(
        warehouse_id, {"as_of": as_of}, make_warehouse_agent_headers(warehouse_id)))


def setup_warehouse_with_crate(weight_lbs=1250, capacity_cwt=1000,
                               checked_in_at="2026-10-01T00:00:00Z",
                               warehouse_overrides=None, **ground_kwargs):
    """Show ground with a warehouse holding one checked-in crate. Returns the
    ground dict plus `crate` and `warehouse` keys."""
    ground = setup_show_ground(with_warehouse=True,
                               warehouse_overrides=dict(capacity_cwt=capacity_cwt,
                                                        **(warehouse_overrides or {})),
                               **ground_kwargs)
    crate = register_crate(ground["exhibitor"]["id"], weight_lbs=weight_lbs)
    if checked_in_at is not None:
        set_clock(checked_in_at)
    ground["crate"] = check_in_crate(crate["id"], ground["warehouse"]["id"])
    return ground


# ---------------------------------------------------------------------------
# Tier 3: labor calls
# ---------------------------------------------------------------------------

def request_labor_call(booth_id, jurisdiction_id, actor="ops", exhibitor_id=None,
                       **overrides):
    payload = create_labor_call_payload(booth_id, jurisdiction_id, **overrides)
    headers = OPS if actor == "ops" else make_exhibitor_headers(exhibitor_id)
    return get_success_data(api_client.create_labor_call(payload, headers))


def dispatch_labor_call(call_id):
    return get_success_data(api_client.dispatch_labor_call(call_id, LABOR))


def check_in_labor_call(call_id, actual_start):
    return get_success_data(
        api_client.check_in_labor_call(call_id, {"actual_start": actual_start}, LABOR))


def complete_labor_call(call_id, outcome="COMPLETED", actual_end=None):
    payload = {"outcome": outcome}
    if actual_end is not None:
        payload["actual_end"] = actual_end
    return get_success_data(api_client.complete_labor_call(call_id, payload, LABOR))


def cancel_labor_call(call_id, reason=None, headers=LABOR):
    payload = {}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.cancel_labor_call(call_id, payload, headers))


def setup_labor_ground(show_status="ON_SITE", jurisdiction_overrides=None,
                       **ground_kwargs):
    """Show ground at ON_SITE with a jurisdiction declared at the show's venue."""
    return setup_show_ground(show_status=show_status, with_jurisdiction=True,
                             jurisdiction_overrides=jurisdiction_overrides,
                             **ground_kwargs)


def setup_requested_labor_call(show_status="ON_SITE", call_overrides=None,
                               jurisdiction_overrides=None, **ground_kwargs):
    """Labor ground plus one REQUESTED call on the booth."""
    ground = setup_labor_ground(show_status=show_status,
                                jurisdiction_overrides=jurisdiction_overrides,
                                **ground_kwargs)
    ground["labor_call"] = request_labor_call(
        ground["booth"]["id"], ground["jurisdiction"]["id"],
        **(call_overrides or {}))
    return ground


def setup_worked_labor_call(actual_start, actual_end,
                            call_overrides=None, jurisdiction_overrides=None,
                            **ground_kwargs):
    """Labor ground with one call dispatched, checked in and completed."""
    ground = setup_requested_labor_call(call_overrides=call_overrides,
                                        jurisdiction_overrides=jurisdiction_overrides,
                                        **ground_kwargs)
    dispatch_labor_call(ground["labor_call"]["id"])
    check_in_labor_call(ground["labor_call"]["id"], actual_start)
    ground["labor_call"] = complete_labor_call(ground["labor_call"]["id"],
                                               "COMPLETED", actual_end)
    return ground


# ---------------------------------------------------------------------------
# Tier 3: change orders
# ---------------------------------------------------------------------------

def raise_change_order(booth_id, target_type, target_id, actor_headers=OPS, **overrides):
    return get_success_data(api_client.create_change_order(
        create_change_order_payload(booth_id, target_type, target_id, **overrides),
        actor_headers))


def submit_change_order(change_order_id, headers=OPS):
    return get_success_data(api_client.submit_change_order(change_order_id, headers))


def review_change_order(change_order_id, decision, note=None, headers=OPS_ALT):
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.review_change_order(change_order_id, payload, headers))


def apply_change_order(change_order_id, order_id, expected_service_order_version=None,
                       headers=OPS_ALT):
    if expected_service_order_version is None:
        expected_service_order_version = order_version(order_id)
    return get_success_data(api_client.apply_change_order(
        change_order_id,
        {"expected_service_order_version": expected_service_order_version}, headers))


def create_approved_change_order(booth_id, target_type, target_id,
                                 creator_headers=OPS, reviewer_headers=OPS_ALT,
                                 **overrides):
    """Change order walked DRAFT -> SUBMITTED -> UNDER_REVIEW -> APPROVED, with the
    reviewer a different operator from the creator."""
    change_order = raise_change_order(booth_id, target_type, target_id,
                                      actor_headers=creator_headers, **overrides)
    submit_change_order(change_order["id"], creator_headers)
    review_change_order(change_order["id"], "START_REVIEW", headers=reviewer_headers)
    return review_change_order(change_order["id"], "APPROVE", headers=reviewer_headers)


# ---------------------------------------------------------------------------
# Tier 3: claims
# ---------------------------------------------------------------------------

def file_claim(exhibitor_id, asset_id, actor="exhibitor", **overrides):
    payload = create_damage_claim_payload(exhibitor_id, asset_id, **overrides)
    headers = make_exhibitor_headers(exhibitor_id) if actor == "exhibitor" else ADJUSTER
    return get_success_data(api_client.create_damage_claim(payload, headers))


def open_investigation(claim_id, headers=ADJUSTER):
    return get_success_data(api_client.open_claim_investigation(claim_id, headers))


def adjudicate_claim(claim_id, decision="APPROVE", coverage_basis=None, note=None,
                     headers=ADJUSTER_ALT):
    payload = {"decision": decision}
    if coverage_basis is not None:
        payload["coverage_basis"] = coverage_basis
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.adjudicate_claim(claim_id, payload, headers))


def appeal_claim(claim_id, note="Freight bill and dock photographs attached",
                 headers=None, exhibitor_id=None):
    if headers is None:
        headers = make_exhibitor_headers(exhibitor_id) if exhibitor_id else ADJUSTER
    return get_success_data(api_client.appeal_claim(claim_id, {"note": note}, headers))


def settle_claim(claim_id, headers=ADJUSTER):
    return get_success_data(api_client.settle_claim(claim_id, headers))


def setup_claim_under_investigation(claim_overrides=None, asset_overrides=None,
                                    crate_weight_lbs=1250, with_crate=True,
                                    **ground_kwargs):
    """Show ground + one asset + optionally its crate + a claim moved to
    UNDER_INVESTIGATION. Returns the ground dict plus asset, crate and claim."""
    ground = setup_show_ground(**ground_kwargs)
    exhibitor_id = ground["exhibitor"]["id"]
    ground["asset"] = register_asset(exhibitor_id, **(asset_overrides or {}))
    overrides = dict(claim_overrides or {})
    if with_crate:
        ground["crate"] = register_crate(exhibitor_id, weight_lbs=crate_weight_lbs,
                                         asset_id=ground["asset"]["id"])
        overrides.setdefault("crate_id", ground["crate"]["id"])
    claim = file_claim(exhibitor_id, ground["asset"]["id"], **overrides)
    ground["claim"] = open_investigation(claim["id"])
    return ground


# ---------------------------------------------------------------------------
# Tier 3: refurbishment
# ---------------------------------------------------------------------------

def open_refurb(asset_id, warehouse_id, **overrides):
    return get_success_data(api_client.create_refurb_work_order(
        create_refurb_work_order_payload(asset_id, warehouse_id, **overrides),
        make_warehouse_agent_headers(warehouse_id)))


def refurb_progress(refurb_id, warehouse_id, to_status, actual_cents=None,
                    condition_grade_after=None):
    payload = {"to_status": to_status}
    if actual_cents is not None:
        payload["actual_cents"] = actual_cents
    if condition_grade_after is not None:
        payload["condition_grade_after"] = condition_grade_after
    return get_success_data(api_client.refurb_progress(
        refurb_id, payload, make_warehouse_agent_headers(warehouse_id)))


def setup_refurb_in_progress(estimate_cents=500000, asset_overrides=None,
                             **ground_kwargs):
    """Warehouse + stored asset + work order started, so the asset is IN_REFURB."""
    ground = setup_show_ground(with_warehouse=True, **ground_kwargs)
    warehouse_id = ground["warehouse"]["id"]
    ground["asset"] = create_stored_asset(ground["exhibitor"]["id"], warehouse_id,
                                          **(asset_overrides or {}))
    refurb = open_refurb(ground["asset"]["id"], warehouse_id,
                         estimate_cents=estimate_cents)
    ground["refurb"] = refurb_progress(refurb["id"], warehouse_id, "IN_PROGRESS")
    return ground


# ---------------------------------------------------------------------------
# Tier 3: lead capture
# ---------------------------------------------------------------------------

def provision_license(booth_id, exhibitor_id, **overrides):
    return get_success_data(api_client.create_lead_capture_license(
        create_lead_capture_license_payload(booth_id, **overrides),
        make_exhibitor_headers(exhibitor_id)))


def ingest_leads(license_id, exhibitor_id, badge_ids,
                 captured_at="2026-09-21T12:00:00Z"):
    return get_success_data(api_client.ingest_lead_batch(
        license_id, {"badge_ids": list(badge_ids), "captured_at": captured_at},
        make_exhibitor_headers(exhibitor_id)))


def setup_active_license(badge_ids=("B1", "B2", "B3"), license_overrides=None,
                         **ground_kwargs):
    """Show ground at ON_SITE with one licence moved to ACTIVE by a first batch."""
    ground = setup_show_ground(show_status="ON_SITE", **ground_kwargs)
    license_row = provision_license(ground["booth"]["id"], ground["exhibitor"]["id"],
                                    **(license_overrides or {}))
    ground["license"] = ingest_leads(license_row["id"], ground["exhibitor"]["id"],
                                     badge_ids)
    return ground
