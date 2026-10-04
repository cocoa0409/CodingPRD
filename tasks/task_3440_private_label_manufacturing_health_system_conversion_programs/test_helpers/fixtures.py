"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the server restarts before each test). Setup calls use the lenient
get_success_data() so a setup failure surfaces as a clear error naming the
step, not a confusing assertion deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_conversion_program_payload,
    create_disruption_payload,
    create_facility_payload,
    create_inventory_program_payload,
    create_lot_payload,
    create_order_payload,
    create_product_payload,
    create_rebate_claim_payload,
    create_sterilization_batch_payload,
    create_tray_template_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_clinician_headers,
    make_conversion_manager_headers,
    make_facility_director_headers,
    make_planner_headers,
    make_quality_headers,
)

ADMIN = TEST_USERS["admin_headers"]
REGULATORY = TEST_USERS["regulatory_headers"]
GPO = TEST_USERS["gpo_analyst_headers"]


def _ok(resp, step: str) -> dict:
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed at {step}: {resp.status_code} {resp.text}"
    return data


# --- Logical clock (PRD §2.4) ---


def set_clock(to_iso8601: str) -> dict:
    return _ok(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), "set_clock")


# --- Tier 1/2: base entities ---


def create_facility(**overrides) -> dict:
    return _ok(
        api_client.create_facility(create_facility_payload(**overrides), ADMIN),
        "create_facility",
    )


def create_product(**overrides) -> dict:
    return _ok(
        api_client.create_product(create_product_payload(**overrides), ADMIN),
        "create_product",
    )


def create_registered_product(**overrides) -> dict:
    """Product driven UNREGISTERED -> SUBMITTED -> REGISTERED (PRD §3.1)."""
    product = create_product(**overrides)
    _ok(
        api_client.record_registration_event(product["id"], {"event": "SUBMIT"}, REGULATORY),
        "registration SUBMIT",
    )
    return _ok(
        api_client.record_registration_event(product["id"], {"event": "APPROVE"}, REGULATORY),
        "registration APPROVE",
    )


def create_lot(product_id: str, planner_id: str = "planner-1", **overrides) -> dict:
    return _ok(
        api_client.create_manufacturing_lot(
            create_lot_payload(product_id, **overrides), make_planner_headers(planner_id)
        ),
        "create_lot",
    )


def create_batch(lot_ids: list, planner_id: str = "planner-1", **overrides) -> dict:
    return _ok(
        api_client.create_sterilization_batch(
            create_sterilization_batch_payload(lot_ids, **overrides),
            make_planner_headers(planner_id),
        ),
        "create_batch",
    )


def record_sterility_result(batch_id: str, result: str, qm_id: str = "qm-1") -> dict:
    return _ok(
        api_client.record_sterility_result(
            batch_id, {"result": result}, make_quality_headers(qm_id)
        ),
        "record_sterility_result",
    )


def record_qa_disposition(lot_id: str, disposition: str, qm_id: str = "qm-1") -> dict:
    return _ok(
        api_client.record_qa_disposition(
            lot_id, {"disposition": disposition}, make_quality_headers(qm_id)
        ),
        "record_qa_disposition",
    )


# --- Agreements / orders (PRD §3.5-§3.6) ---


def create_agreement(facility_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_prime_vendor_agreement(
            create_agreement_payload(facility_id, **overrides), ADMIN
        ),
        "create_agreement",
    )


def place_order(agreement_id: str, facility_id: str, lines: list, **overrides) -> dict:
    """Facility-director call: X-User-ID must equal the agreement's facility."""
    return _ok(
        api_client.create_distribution_order(
            create_order_payload(agreement_id, lines, **overrides),
            make_facility_director_headers(facility_id),
        ),
        "place_order",
    )


def ship_order(order_id: str, shipped_lines: list) -> dict:
    return _ok(
        api_client.record_fulfillment_event(
            order_id, {"event": "SHIPPED", "shipped_lines": shipped_lines}, ADMIN
        ),
        "ship_order",
    )


def receive_order(order_id: str) -> dict:
    return _ok(
        api_client.record_fulfillment_event(
            order_id, {"event": "RECEIVED", "shipped_lines": []}, ADMIN
        ),
        "receive_order",
    )


def get_agreement(agreement_id: str) -> dict:
    return _ok(api_client.get_prime_vendor_agreement(agreement_id, ADMIN), "get_agreement")


# --- Inventory programs (PRD §3.9) ---


def create_inventory_program(facility_id: str, positions: list, **overrides) -> dict:
    return _ok(
        api_client.create_inventory_program(
            create_inventory_program_payload(facility_id, positions, **overrides), ADMIN
        ),
        "create_inventory_program",
    )


def record_stock_event(program_id: str, product_id: str, quantity_delta: int, event_type: str) -> dict:
    return _ok(
        api_client.record_stock_event(
            program_id,
            {
                "product_id": product_id,
                "quantity_delta": quantity_delta,
                "event_type": event_type,
            },
            ADMIN,
        ),
        "record_stock_event",
    )


def get_inventory_program(program_id: str) -> dict:
    return _ok(api_client.get_inventory_program(program_id, ADMIN), "get_inventory_program")


# --- Rebate claims (PRD §3.7) ---


def create_rebate_claim(facility_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_rebate_claim(
            create_rebate_claim_payload(facility_id, **overrides), GPO
        ),
        "create_rebate_claim",
    )


def record_claim_event(claim_id: str, event: str, dispute_reason: str = None) -> dict:
    payload = {"event": event}
    if dispute_reason is not None:
        payload["dispute_reason"] = dispute_reason
    return _ok(api_client.record_lifecycle_event(claim_id, payload, GPO), f"claim {event}")


# --- Supply disruptions (PRD §3.8) ---


def create_disruption(product_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_supply_disruption(
            create_disruption_payload(product_id, **overrides), ADMIN
        ),
        "create_disruption",
    )


def post_allocation(
    disruption_id: str, facility_id: str, quantity: int, expected_version: int
) -> dict:
    return _ok(
        api_client.post_allocation(
            disruption_id,
            {
                "facility_id": facility_id,
                "quantity": quantity,
                "expected_disruption_version": expected_version,
            },
            ADMIN,
        ),
        "post_allocation",
    )


def request_substitution(
    disruption_id: str, facility_id: str, proposed_product_id: str, covered_quantity: int
) -> dict:
    """Substitution REQUEST: FacilitySupplyDirector whose X-User-ID is the facility."""
    return _ok(
        api_client.post_substitution_request(
            disruption_id,
            {
                "action": "REQUEST",
                "facility_id": facility_id,
                "proposed_product_id": proposed_product_id,
                "covered_quantity": covered_quantity,
            },
            make_facility_director_headers(facility_id),
        ),
        "request_substitution",
    )


def decide_substitution(
    disruption_id: str,
    request_id: str,
    decision: str,
    clinician_id: str = "clin-1",
    rationale: str = None,
) -> dict:
    payload = {"action": "DECIDE", "request_id": request_id, "decision": decision}
    if rationale is not None:
        payload["rationale"] = rationale
    return _ok(
        api_client.post_substitution_request(
            disruption_id, payload, make_clinician_headers(clinician_id)
        ),
        "decide_substitution",
    )


def get_disruption(disruption_id: str) -> dict:
    return _ok(api_client.get_supply_disruption(disruption_id, ADMIN), "get_disruption")


# --- Tray templates (PRD §3.4) ---


def create_tray_template(
    facility_id: str, components: list, creator_id: str = "admin-1", **overrides
) -> dict:
    return _ok(
        api_client.create_tray_template(
            create_tray_template_payload(facility_id, components, **overrides),
            make_admin_headers(creator_id),
        ),
        "create_tray_template",
    )


def propose_tray_change(
    tray_id: str, components: list, expected_version: int, user_id: str = "admin-1"
) -> dict:
    return _ok(
        api_client.propose_tray_change(
            tray_id,
            {"components": components, "expected_template_version": expected_version},
            make_admin_headers(user_id),
        ),
        "propose_tray_change",
    )


def decide_tray_approval(tray_id: str, decision: str, admin_id: str = "admin-2") -> dict:
    return _ok(
        api_client.record_approval_decision(
            tray_id, {"decision": decision}, make_admin_headers(admin_id)
        ),
        "decide_tray_approval",
    )


# --- Conversion programs (PRD §3.3) ---


def create_conversion_program(facility_id: str, line_items: list, **overrides) -> dict:
    return _ok(
        api_client.create_conversion_program(
            create_conversion_program_payload(facility_id, line_items, **overrides),
            make_conversion_manager_headers("cm-1"),
        ),
        "create_conversion_program",
    )


def evaluate_line_item(
    program_id: str,
    line_id: str,
    outcome: str,
    training_completed: bool,
    clinician_id: str = "clin-1",
    notes: str = None,
) -> dict:
    payload = {
        "line_id": line_id,
        "outcome": outcome,
        "training_completed": training_completed,
    }
    if notes is not None:
        payload["notes"] = notes
    return _ok(
        api_client.record_line_item_evaluation(
            program_id, payload, make_clinician_headers(clinician_id)
        ),
        "evaluate_line_item",
    )


def review_program(program_id: str, decision: str) -> dict:
    return _ok(
        api_client.record_review_decision(
            program_id, {"decision": decision}, make_conversion_manager_headers("cm-1")
        ),
        "review_program",
    )


def get_conversion_program(program_id: str) -> dict:
    return _ok(
        api_client.get_conversion_program(
            program_id, make_conversion_manager_headers("cm-1")
        ),
        "get_conversion_program",
    )


# --- Tier 3/4: composite scenarios ---


def setup_facility_with_agreement(
    committed_fill_rate_pct: float = 95.0,
    each_price_cents: int = 100,
    annual_commitment_cents: int = 100000000,
    lum_commitment: bool = False,
    product_overrides: dict = None,
    agreement_overrides: dict = None,
) -> dict:
    """Facility + one catalog product + ACTIVE agreement (default window
    2026-08-01..2027-08-31, which contains the default logical clock).
    Returns {"facility", "product", "agreement"}."""
    facility = create_facility()
    product = create_product(each_price_cents=each_price_cents, **(product_overrides or {}))
    agreement = create_agreement(
        facility["id"],
        committed_fill_rate_pct=committed_fill_rate_pct,
        lum_commitment=lum_commitment,
        annual_commitment_cents=annual_commitment_cents,
        **(agreement_overrides or {}),
    )
    return {"facility": facility, "product": product, "agreement": agreement}


def suspend_agreement_via_breach(
    facility_id: str, agreement_id: str, product_id: str
) -> dict:
    """Drive an ACTIVE agreement (committed 95.0) into SUSPENDED:
    order x200, ship 170 with NO backorder cancellation, then receive from
    PARTIALLY_SHIPPED so the open 30-unit shortfall stays in the final rate's
    denominator (PRD 3.6) -> final 170/200 = 85.00, rolling 85.00 < 95.0.
    (A cancelled single-line order always finals at 100.00, since cancelled
    units leave the denominator.) Returns the received order."""
    order = place_order(
        agreement_id,
        facility_id,
        [{"product_id": product_id, "ordered_qty": 200}],
        requested_delivery_date="2026-09-10",
    )
    ship_order(
        order["id"],
        [{"product_id": product_id, "shipped_qty": 170, "backorder_cancelled": False}],
    )
    return receive_order(order["id"])


def setup_suspended_agreement_scenario(
    annual_commitment_cents: int = 100000000, committed_fill_rate_pct: float = 95.0
) -> dict:
    """Facility + product + agreement driven SUSPENDED via the standard
    170-of-200 breach. Returns {"facility", "product", "agreement", "order"}."""
    ctx = setup_facility_with_agreement(
        committed_fill_rate_pct=committed_fill_rate_pct,
        annual_commitment_cents=annual_commitment_cents,
    )
    order = suspend_agreement_via_breach(
        ctx["facility"]["id"], ctx["agreement"]["id"], ctx["product"]["id"]
    )
    ctx["order"] = order
    return ctx


def setup_program_in_review(
    outcome: str = "PASSED",
    training_completed: bool = True,
    with_agreement: bool = False,
) -> dict:
    """Facility (+ optional ACTIVE agreement) + incumbent/replacement products
    + a one-line conversion program whose single line item has been evaluated,
    auto-advancing the program to IN_REVIEW. Returns
    {"facility", "incumbent", "replacement", "program", "line_id", "agreement"?}."""
    facility = create_facility()
    incumbent = create_product()
    replacement = create_product(brand_type="PRIVATE_LABEL")
    agreement = create_agreement(facility["id"]) if with_agreement else None
    program = create_conversion_program(
        facility["id"],
        [
            {
                "incumbent_product_id": incumbent["id"],
                "replacement_product_id": replacement["id"],
            }
        ],
    )
    line_id = program["line_items"][0]["line_id"]
    program = evaluate_line_item(
        program["id"], line_id, outcome, training_completed, notes="evaluated"
    )
    return {
        "facility": facility,
        "incumbent": incumbent,
        "replacement": replacement,
        "program": program,
        "line_id": line_id,
        "agreement": agreement,
    }
