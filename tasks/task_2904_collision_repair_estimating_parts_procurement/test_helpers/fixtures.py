"""State builders, from single rows up to whole repair orders in mid-flight.

The harness restarts the server before every test, so every fixture builds its
world from nothing through the declared endpoints. Setup calls go through the
lenient success reader, so a broken prerequisite surfaces as a setup failure
naming the endpoint that refused rather than as a mysterious assertion.

Five tiers:

1. Single rows: the standing registries, the logical clock, one repair order.
2. Entity hierarchy: findings, procedure records, labor lines, parts lines and
   bookings hung off an order.
3. Lifecycle shortcuts: an order blueprinted, locked, staged, in repair, in
   refinish or waiting for quality control, and a part walked from planned to
   installed.
4. Accumulation and threshold targeting: supplier performance histories, parts
   priced to land in a chosen rebate tier, owner shares sitting on the consent
   threshold.
5. Finalisation: inspection filed, vehicle delivered, vehicle totalled.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .constants import CLOCK_DEFAULT
from .test_users import (
    ESTIMATOR_HEADERS,
    PARTS_MANAGER_HEADERS,
    QC_INSPECTOR_HEADERS,
    SHOP_ADMIN_HEADERS,
    TECHNICIAN_HEADERS,
    make_customer_headers,
    make_insurer_adjuster_headers,
    make_qc_inspector_headers,
)

# ---------------------------------------------------------------------------
# Windows on the default clock day, for bookings and calibration slots
# ---------------------------------------------------------------------------
DAY = "2026-08-01"
T0000 = f"{DAY}T00:00:00Z"
T0600 = f"{DAY}T06:00:00Z"
T0800 = f"{DAY}T08:00:00Z"
T0900 = f"{DAY}T09:00:00Z"
T1000 = f"{DAY}T10:00:00Z"
T1100 = f"{DAY}T11:00:00Z"
T1200 = f"{DAY}T12:00:00Z"
T1230 = f"{DAY}T12:30:00Z"
T1231 = f"{DAY}T12:31:00Z"
T1300 = f"{DAY}T13:00:00Z"
T1400 = f"{DAY}T14:00:00Z"
T1500 = f"{DAY}T15:00:00Z"
T1600 = f"{DAY}T16:00:00Z"
NEXT_DAY = "2026-08-02T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: the logical clock and the standing registries
# ---------------------------------------------------------------------------
def set_clock(api, to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), SHOP_ADMIN_HEADERS))


def create_customer(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_customer(f.customer_payload(**overrides), SHOP_ADMIN_HEADERS)
    )


def create_insurer(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_insurer(f.insurer_payload(**overrides), SHOP_ADMIN_HEADERS)
    )


def create_vendor(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_parts_vendor(f.parts_vendor_payload(**overrides), SHOP_ADMIN_HEADERS)
    )


def create_stall(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_stall(f.stall_payload(**overrides), SHOP_ADMIN_HEADERS)
    )


def create_bay(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_calibration_bay(
            f.calibration_bay_payload(**overrides), SHOP_ADMIN_HEADERS
        )
    )


def create_repair_order(api, customer_id: str, insurer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_repair_order(
            f.repair_order_payload(customer_id, insurer_id, **overrides),
            SHOP_ADMIN_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: reads
# ---------------------------------------------------------------------------
def read_order(api, order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_repair_order(order_id, headers or SHOP_ADMIN_HEADERS))


def order_version(api, order_id: str) -> int:
    return read_order(api, order_id)["version"]


def read_estimate_line(api, line_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_estimate_line(line_id, headers or ESTIMATOR_HEADERS))


def read_parts_line(api, line_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_parts_line(line_id, headers or PARTS_MANAGER_HEADERS))


def read_supplement(api, supplement_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_supplement(supplement_id, headers or ESTIMATOR_HEADERS))


def read_vendor(api, vendor_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_parts_vendor(vendor_id, headers or PARTS_MANAGER_HEADERS))


def read_stall(api, stall_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_stall(stall_id, headers or SHOP_ADMIN_HEADERS))


def read_bay(api, bay_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_calibration_bay(bay_id, headers or SHOP_ADMIN_HEADERS))


def read_procedure_record(api, record_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_procedure_record(record_id, headers or TECHNICIAN_HEADERS)
    )


def read_assignment(api, assignment_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_stage_assignment(assignment_id, headers or TECHNICIAN_HEADERS)
    )


def read_cycle_time(api, order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_cycle_time(order_id, headers or SHOP_ADMIN_HEADERS))


def page(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Unwrap a paginated listing into its rows and its page metadata."""
    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Tier 2: children of an order
# ---------------------------------------------------------------------------
def add_finding(api, order_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_teardown_finding(
            order_id, f.teardown_finding_payload(**overrides), ESTIMATOR_HEADERS
        )
    )


def add_procedure_record(api, order_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_procedure_record(
            order_id, f.procedure_record_payload(**overrides), ESTIMATOR_HEADERS
        )
    )


def document_adherence(api, record_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.document_adherence(record_id, f.adherence_payload(**overrides), TECHNICIAN_HEADERS)
    )


def add_estimate_line(api, order_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_estimate_line(
            order_id, f.estimate_line_payload(**overrides), ESTIMATOR_HEADERS
        )
    )


def publish_blueprint(api, order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.publish_blueprint(order_id, None, headers or ESTIMATOR_HEADERS)
    )


def lock_estimate(api, order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.lock_estimate(order_id, None, headers or ESTIMATOR_HEADERS))


def declare_total_loss(api, order_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.declare_total_loss(order_id, f.total_loss_payload(**overrides), ESTIMATOR_HEADERS)
    )


def add_parts_line(api, estimate_line_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_parts_line(
            estimate_line_id, f.parts_line_payload(**overrides), PARTS_MANAGER_HEADERS
        )
    )


def quote_part(api, parts_line_id: str, vendor_id: str, quoted_unit_price_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.quote_parts_line(
            parts_line_id,
            f.quote_payload(vendor_id, quoted_unit_price_cents),
            PARTS_MANAGER_HEADERS,
        )
    )


def counter_part(api, parts_line_id: str, counter_unit_price_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.counter_offer_parts_line(
            parts_line_id,
            f.counter_offer_payload(counter_unit_price_cents),
            PARTS_MANAGER_HEADERS,
        )
    )


def accept_price(api, parts_line_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.accept_parts_price(parts_line_id, None, PARTS_MANAGER_HEADERS)
    )


def place_parts_order(api, parts_line_id: str, promised_eta: str) -> Dict[str, Any]:
    return get_success_data(
        api.order_parts_line(parts_line_id, f.order_payload(promised_eta), PARTS_MANAGER_HEADERS)
    )


def receive_part(api, parts_line_id: str, received_qty: int, condition: str = "CORRECT") -> Dict[str, Any]:
    return get_success_data(
        api.receive_parts_line(
            parts_line_id, f.receive_payload(received_qty, condition), PARTS_MANAGER_HEADERS
        )
    )


def install_part(api, parts_line_id: str) -> Dict[str, Any]:
    return get_success_data(api.install_parts_line(parts_line_id, None, TECHNICIAN_HEADERS))


def return_units(api, parts_line_id: str, return_qty: int, return_reason: str) -> Dict[str, Any]:
    return get_success_data(
        api.return_parts_line(
            parts_line_id, f.return_payload(return_qty, return_reason), PARTS_MANAGER_HEADERS
        )
    )


def run_delay_sweep(api, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.run_parts_delay_sweep(order_id, None, PARTS_MANAGER_HEADERS)
    )


def book_stall(api, order_id: str, stall_id: str, stage: str, window_start: str, window_end: str) -> Dict[str, Any]:
    return get_success_data(
        api.create_stage_assignment(
            order_id,
            f.stage_assignment_payload(stall_id, stage, window_start, window_end),
            TECHNICIAN_HEADERS,
        )
    )


def cancel_assignment(api, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_stage_assignment(assignment_id, None, TECHNICIAN_HEADERS)
    )


def advance_stage(api, order_id: str, to_stage: str) -> Dict[str, Any]:
    return get_success_data(
        api.advance_stage(order_id, f.stage_advance_payload(to_stage), TECHNICIAN_HEADERS)
    )


def schedule_calibration(api, record_id: str, bay_id: str, window_start: str, window_end: str) -> Dict[str, Any]:
    return get_success_data(
        api.schedule_calibration(
            record_id,
            f.calibration_schedule_payload(bay_id, window_start, window_end),
            TECHNICIAN_HEADERS,
        )
    )


def record_calibration_result(api, record_id: str, result: str, post_scan_dtc_count: int, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.record_calibration_result(
            record_id,
            f.calibration_result_payload(result, post_scan_dtc_count, **overrides),
            TECHNICIAN_HEADERS,
        )
    )


def raise_supplement(api, order_id: str, expected_repair_order_version: Optional[int] = None, **overrides: Any) -> Dict[str, Any]:
    version = (
        expected_repair_order_version
        if expected_repair_order_version is not None
        else order_version(api, order_id)
    )
    return get_success_data(
        api.create_supplement(
            order_id, f.supplement_payload(version, **overrides), ESTIMATOR_HEADERS
        )
    )


def decide_supplement(api, supplement_id: str, insurer_id: str, decision: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.decide_supplement(
            supplement_id,
            f.supplement_decision_payload(decision, **overrides),
            make_insurer_adjuster_headers(insurer_id),
        )
    )


def resubmit_supplement(api, supplement_id: str, requested_amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.resubmit_supplement(
            supplement_id,
            f.supplement_resubmit_payload(requested_amount_cents),
            ESTIMATOR_HEADERS,
        )
    )


def record_consent(api, order_id: str, customer_id: str, decision: str, alternate_parts_ok: bool, expected_repair_order_version: Optional[int] = None) -> Dict[str, Any]:
    version = (
        expected_repair_order_version
        if expected_repair_order_version is not None
        else order_version(api, order_id)
    )
    return get_success_data(
        api.create_consent_decision(
            order_id,
            f.consent_decision_payload(decision, alternate_parts_ok, version),
            make_customer_headers(customer_id),
        )
    )


def file_qc_inspection(api, order_id: str, checklist_passed: bool = True, post_scan_dtc_count: int = 0, inspector_user_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    headers = (
        make_qc_inspector_headers(inspector_user_id)
        if inspector_user_id is not None
        else QC_INSPECTOR_HEADERS
    )
    return get_success_data(
        api.create_qc_inspection(
            order_id,
            f.qc_inspection_payload(checklist_passed, post_scan_dtc_count, **overrides),
            headers,
        )
    )


def deliver_order(api, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.deliver_repair_order(order_id, None, SHOP_ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Tier 3: whole worlds
# ---------------------------------------------------------------------------
def open_order_world(
    api,
    customer_overrides: Optional[Dict[str, Any]] = None,
    insurer_overrides: Optional[Dict[str, Any]] = None,
    order_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An owner, a program and one repair order sitting at intake."""
    customer = create_customer(api, **(customer_overrides or {}))
    insurer = create_insurer(api, **(insurer_overrides or {}))
    order = create_repair_order(api, customer["id"], insurer["id"], **(order_overrides or {}))
    return {
        "customer": customer,
        "insurer": insurer,
        "order": order,
        "customer_id": customer["id"],
        "insurer_id": insurer["id"],
        "order_id": order["id"],
        "claim_number": order["claim_number"],
        "customer_headers": make_customer_headers(customer["id"]),
        "insurer_headers": make_insurer_adjuster_headers(insurer["id"]),
        "findings": [],
        "procedure_records": [],
        "lines": [],
        "parts_lines": [],
        "assignments": [],
    }


def blueprinted_world(
    api,
    findings: Optional[List[Dict[str, Any]]] = None,
    procedures: Optional[List[Dict[str, Any]]] = None,
    **world_overrides: Any,
) -> Dict[str, Any]:
    """An order carried through teardown to a published blueprint."""
    world = open_order_world(api, **world_overrides)
    for spec in findings if findings is not None else [{}]:
        world["findings"].append(add_finding(api, world["order_id"], **spec))
    for spec in procedures or []:
        world["procedure_records"].append(
            add_procedure_record(api, world["order_id"], **spec)
        )
    world["order"] = publish_blueprint(api, world["order_id"])
    return world


def locked_world(
    api,
    lines: Optional[List[Dict[str, Any]]] = None,
    findings: Optional[List[Dict[str, Any]]] = None,
    procedures: Optional[List[Dict[str, Any]]] = None,
    **world_overrides: Any,
) -> Dict[str, Any]:
    """An order whose estimate has been committed, with its labor lines written.

    The default estimate is the single 4.5-hour body operation the requirements
    use in their own worked illustrations.
    """
    world = blueprinted_world(api, findings=findings, procedures=procedures, **world_overrides)
    for spec in lines if lines is not None else [{"labor_type": "BODY", "guide_hours": 4.5}]:
        world["lines"].append(add_estimate_line(api, world["order_id"], **spec))
    world["order"] = lock_estimate(api, world["order_id"])
    world["line_ids"] = [line["id"] for line in world["lines"]]
    return world


def ensure_stall(api, world: Dict[str, Any], key: str, **overrides: Any) -> Dict[str, Any]:
    """Register a stall once per world and remember it under `key`."""
    if key not in world:
        world[key] = create_stall(api, **overrides)
    return world[key]


def walk_forward(
    api,
    world: Dict[str, Any],
    target_stage: str,
    repair_window: Tuple[str, str] = (T0800, T1200),
    refinish_window: Tuple[str, str] = (T1300, T1500),
) -> Dict[str, Any]:
    """Walk a locked order one hop at a time up to `target_stage`.

    Bookings are registered as each hop demands them, procedure adherence is
    documented on every record the world created, and any calibration a record
    demands is booked and passed. Tests that are themselves about one of those
    gates build their own path instead of calling this.
    """
    order_id = world["order_id"]

    if target_stage == "ESTIMATE_LOCKED":
        return read_order(api, order_id)

    world["order"] = advance_stage(api, order_id, "PARTS_STAGED")
    if target_stage == "PARTS_STAGED":
        return world["order"]

    body_stall = ensure_stall(api, world, "body_stall", name="Body 1", stall_type="BODY")
    world["repair_assignment"] = book_stall(
        api, order_id, body_stall["id"], "REPAIR", repair_window[0], repair_window[1]
    )
    world["assignments"].append(world["repair_assignment"])
    world["order"] = advance_stage(api, order_id, "REPAIR")
    if target_stage == "REPAIR":
        return world["order"]

    for record in world["procedure_records"]:
        fresh = read_procedure_record(api, record["id"])
        if not fresh["adherence_documented"]:
            document_adherence(api, record["id"], adherence_doc_ref="DOC-1")

    paint_stall = ensure_stall(api, world, "paint_stall", name="Paint 1", stall_type="PAINT")
    world["refinish_assignment"] = book_stall(
        api,
        order_id,
        paint_stall["id"],
        "REFINISH_CALIBRATION",
        refinish_window[0],
        refinish_window[1],
    )
    world["assignments"].append(world["refinish_assignment"])
    world["order"] = advance_stage(api, order_id, "REFINISH_CALIBRATION")
    if target_stage == "REFINISH_CALIBRATION":
        return world["order"]

    for record in world["procedure_records"]:
        fresh = read_procedure_record(api, record["id"])
        if fresh["requires_calibration"] and fresh["calibration_status"] != "PASSED":
            bay = ensure_bay(api, world, fresh["calibration_type"])
            schedule_calibration(api, record["id"], bay["id"], T0900, T1000)
            record_calibration_result(api, record["id"], "PASS", 0, scan_report_ref="SCAN-1")

    world["order"] = advance_stage(api, order_id, "READY_FOR_QC")
    return world["order"]


def ensure_bay(api, world: Dict[str, Any], calibration_type: str) -> Dict[str, Any]:
    """A bay that supports exactly the modality the record demands."""
    key = f"bay_{calibration_type.lower()}"
    if key not in world:
        world[key] = create_bay(
            api,
            name=f"Calibration Bay {calibration_type}",
            supported_types=[calibration_type],
        )
    return world[key]


def locked_world_at(
    api,
    target_stage: str,
    lines: Optional[List[Dict[str, Any]]] = None,
    findings: Optional[List[Dict[str, Any]]] = None,
    procedures: Optional[List[Dict[str, Any]]] = None,
    repair_window: Tuple[str, str] = (T0800, T1200),
    refinish_window: Tuple[str, str] = (T1300, T1500),
    **world_overrides: Any,
) -> Dict[str, Any]:
    """A locked order walked forward to the requested stage."""
    world = locked_world(
        api, lines=lines, findings=findings, procedures=procedures, **world_overrides
    )
    world["order"] = walk_forward(
        api,
        world,
        target_stage,
        repair_window=repair_window,
        refinish_window=refinish_window,
    )
    return world


# ---------------------------------------------------------------------------
# Tier 3: a part walked along the procurement chain
# ---------------------------------------------------------------------------
def planned_part(api, estimate_line_id: str, **overrides: Any) -> Dict[str, Any]:
    return add_parts_line(api, estimate_line_id, **overrides)


def quoted_part(
    api, estimate_line_id: str, vendor_id: str, quoted_unit_price_cents: int, **overrides: Any
) -> Dict[str, Any]:
    line = add_parts_line(api, estimate_line_id, **overrides)
    return quote_part(api, line["id"], vendor_id, quoted_unit_price_cents)


def price_locked_part(
    api, estimate_line_id: str, vendor_id: str, quoted_unit_price_cents: int, **overrides: Any
) -> Dict[str, Any]:
    line = quoted_part(
        api, estimate_line_id, vendor_id, quoted_unit_price_cents, **overrides
    )
    return accept_price(api, line["id"])


def ordered_part(
    api,
    estimate_line_id: str,
    vendor_id: str,
    quoted_unit_price_cents: int,
    promised_eta: str = NEXT_DAY,
    **overrides: Any,
) -> Dict[str, Any]:
    line = price_locked_part(
        api, estimate_line_id, vendor_id, quoted_unit_price_cents, **overrides
    )
    return place_parts_order(api, line["id"], promised_eta)


def received_part(
    api,
    estimate_line_id: str,
    vendor_id: str,
    quoted_unit_price_cents: int,
    received_qty: int = 1,
    condition: str = "CORRECT",
    promised_eta: str = NEXT_DAY,
    **overrides: Any,
) -> Dict[str, Any]:
    line = ordered_part(
        api,
        estimate_line_id,
        vendor_id,
        quoted_unit_price_cents,
        promised_eta=promised_eta,
        **overrides,
    )
    return receive_part(api, line["id"], received_qty, condition)


def installed_part(
    api,
    estimate_line_id: str,
    vendor_id: str,
    quoted_unit_price_cents: int,
    received_qty: int = 1,
    promised_eta: str = NEXT_DAY,
    **overrides: Any,
) -> Dict[str, Any]:
    line = received_part(
        api,
        estimate_line_id,
        vendor_id,
        quoted_unit_price_cents,
        received_qty=received_qty,
        promised_eta=promised_eta,
        **overrides,
    )
    return install_part(api, line["id"])


# ---------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ---------------------------------------------------------------------------
def close_vendor_outcome(
    api,
    world: Dict[str, Any],
    vendor_id: str,
    unit_price_cents: int,
    on_time: bool = True,
    return_qty: int = 0,
    extra_quote_rounds: int = 0,
    qty: int = 1,
    promised_eta: str = NEXT_DAY,
    late_clock: str = "2026-08-03T00:00:00Z",
) -> Dict[str, Any]:
    """Produce one closed outcome for a supplier's performance window.

    A closed outcome is a parts line that has been received, so it carries an
    `on_time` verdict, a `returned_qty` and a `quote_round`. The line is hung
    off a fresh labor operation on the world's order so that several outcomes
    can be accumulated against the same supplier.
    """
    line = add_estimate_line(api, world["order_id"], labor_type="MECHANICAL", guide_hours=1.0)
    part = add_parts_line(
        api, line["id"], list_price_cents=unit_price_cents * 2, qty=qty
    )
    quote_part(api, part["id"], vendor_id, unit_price_cents + extra_quote_rounds * 1000)
    for step in range(extra_quote_rounds):
        counter_part(api, part["id"], unit_price_cents + (extra_quote_rounds - step - 1) * 1000 - 1)
        quote_part(api, part["id"], vendor_id, unit_price_cents + (extra_quote_rounds - step - 1) * 1000)
    accept_price(api, part["id"])
    place_parts_order(api, part["id"], promised_eta)
    if not on_time:
        set_clock(api, late_clock)
    received = receive_part(api, part["id"], qty)
    if not on_time:
        set_clock(api, CLOCK_DEFAULT)
    if return_qty:
        received = return_units(api, part["id"], return_qty, "UNUSED")
    return received


# ---------------------------------------------------------------------------
# Tier 5: finalisation
# ---------------------------------------------------------------------------
def passed_qc_world(api, world: Dict[str, Any], inspector_user_id: Optional[str] = None) -> Dict[str, Any]:
    """File a passing inspection on an order already waiting for quality control."""
    world["qc_inspection"] = file_qc_inspection(
        api, world["order_id"], True, 0, inspector_user_id=inspector_user_id, scan_report_ref="SCAN-QC"
    )
    world["order"] = read_order(api, world["order_id"])
    return world


def delivered_world(api, world: Dict[str, Any], inspector_user_id: Optional[str] = None) -> Dict[str, Any]:
    """Take an order waiting for quality control all the way to released."""
    passed_qc_world(api, world, inspector_user_id=inspector_user_id)
    world["order"] = deliver_order(api, world["order_id"])
    return world
