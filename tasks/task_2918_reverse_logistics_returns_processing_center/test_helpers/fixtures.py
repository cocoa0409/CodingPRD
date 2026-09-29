"""Composite setup builders.

The harness restarts the server before every individual test, so every fixture
below builds its world from an empty database using nothing but documented
endpoints. Setup calls go through `get_success_data`, which raises a readable
AssertionError naming the error_id when a preamble step fails.

All builders return the response's `data` payload directly — never the whole
envelope — so no call site ever needs to reach into `["data"]` itself.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from . import test_users as users
from .api_client import ApiClient
from .constants import (
    BAY_TYPE_GENERAL,
    BAY_TYPE_HAZMAT,
    CHANNEL_TYPE_CERTIFIED_DESTRUCTION,
    CHANNEL_TYPE_DONATION_PARTNER,
    CHANNEL_WINDOW_A_END,
    CHANNEL_WINDOW_A_START,
    GRADE_C,
    GRADE_D,
    GRADE_SCRAP,
    PACKAGING_TARE_GRAMS,
    REASON_DEFECTIVE,
    RECALL_MANDATORY,
    TEST_RESULT_FAIL,
    TEST_RESULT_PASS,
)

# ─── Configuration surface ──────────────────────────────────────────────


def make_client(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one client and return it."""
    return get_success_data(
        api.create_client(f.client_payload(**overrides), users.ADMIN)
    )


def make_catalog_item(
    api: ApiClient, client_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Register one catalogue item against a client and return it."""
    return get_success_data(
        api.create_catalog_item(
            f.catalog_item_payload(client_id, **overrides), users.ADMIN
        )
    )


def make_bay(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one processing bay and return it."""
    return get_success_data(
        api.create_processing_bay(f.processing_bay_payload(**overrides), users.ADMIN)
    )


def make_general_bay(
    api: ApiClient, bay_code: str = "BAY-G1", buffer_minutes: int = 30
) -> Dict[str, Any]:
    """A GENERAL bay for refurbishment test windows."""
    return make_bay(
        api,
        bay_code=bay_code,
        bay_type=BAY_TYPE_GENERAL,
        buffer_minutes=buffer_minutes,
    )


def make_hazmat_bay(
    api: ApiClient, bay_code: str = "HZ1", buffer_minutes: int = 0
) -> Dict[str, Any]:
    """A HAZMAT bay for quarantine occupations."""
    return make_bay(
        api,
        bay_code=bay_code,
        bay_type=BAY_TYPE_HAZMAT,
        buffer_minutes=buffer_minutes,
    )


def make_channel(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one secondary-market channel and return it."""
    return get_success_data(
        api.create_channel(f.channel_payload(**overrides), users.ADMIN)
    )


def make_donation_channel(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A donation partner accepting every non-scrap grade."""
    defaults: Dict[str, Any] = {
        "name": "Helping Hands",
        "channel_code": "DON1",
        "channel_type": CHANNEL_TYPE_DONATION_PARTNER,
        "fee_pct": 0.00,
        "min_lot_value_cents": 0,
    }
    defaults.update(overrides)
    return make_channel(api, **defaults)


def make_destruction_channel(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A certified-destruction outlet accepting D and SCRAP."""
    defaults: Dict[str, Any] = {
        "name": "SafeBurn",
        "channel_code": "DEST1",
        "channel_type": CHANNEL_TYPE_CERTIFIED_DESTRUCTION,
        "accepted_grades": [GRADE_D, GRADE_SCRAP],
        "fee_pct": 0.00,
        "min_lot_value_cents": 0,
    }
    defaults.update(overrides)
    return make_channel(api, **defaults)


# ─── Authorizations ─────────────────────────────────────────────────────


def make_draft_rma(api: ApiClient, client_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open a DRAFT authorization for a client."""
    return get_success_data(
        api.create_rma(f.rma_payload(client_id, **overrides), users.ADMIN)
    )


def add_rma_line(
    api: ApiClient, rma_id: str, catalog_item_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Declare one authorized line on a DRAFT authorization."""
    return get_success_data(
        api.create_rma_line(
            rma_id, f.rma_line_payload(catalog_item_id, **overrides), users.ADMIN
        )
    )


def issue_rma(api: ApiClient, rma_id: str) -> Dict[str, Any]:
    """Issue an authorization so goods may be received against it."""
    return get_success_data(api.issue_rma(rma_id, users.ADMIN))


def make_issued_rma(
    api: ApiClient,
    client_id: str,
    line_specs: List[Dict[str, Any]],
    **rma_overrides: Any,
) -> Dict[str, Any]:
    """A DRAFT authorization carrying the given lines, then issued.

    Each entry of `line_specs` is the keyword payload for one authorization
    line and must carry at least `catalog_item_id`.
    """
    rma = make_draft_rma(api, client_id, **rma_overrides)
    lines = [add_rma_line(api, rma["id"], **spec) for spec in line_specs]
    issued = issue_rma(api, rma["id"])
    return {"rma": issued, "lines": lines}


def expected_weight_grams(*unit_weight_and_quantity) -> int:
    """The scan-time weight expectation: the tare plus every authorized line.

    Each positional argument is a (unit_weight_grams, authorized_quantity)
    pair covering one authorization line of the receipt's authorization.
    """
    total = PACKAGING_TARE_GRAMS
    for unit_weight, quantity in unit_weight_and_quantity:
        total += unit_weight * quantity
    return total


# ─── Dock ───────────────────────────────────────────────────────────────


def make_receipt(
    api: ApiClient,
    rma_id: str,
    gross_weight_grams: int,
    tracking_reference: str = "TRK-1",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Scan an inbound carton against an issued authorization."""
    return get_success_data(
        api.create_receipt(
            f.receipt_payload(
                rma_id,
                tracking_reference=tracking_reference,
                gross_weight_grams=gross_weight_grams,
            ),
            headers or users.CLERK,
        )
    )


def scan_line(
    api: ApiClient,
    receipt_id: str,
    rma_line_id: str,
    quantity: int = 1,
    reason_code: str = REASON_DEFECTIVE,
    scanned_serial: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Register one scanned unit line inside a carton."""
    return get_success_data(
        api.create_receipt_line(
            receipt_id,
            f.receipt_line_payload(
                rma_line_id,
                quantity=quantity,
                reason_code=reason_code,
                scanned_serial=scanned_serial,
            ),
            headers or users.CLERK,
        )
    )


# ─── Return-line progression ────────────────────────────────────────────


def quarantine_line(
    api: ApiClient,
    return_line_id: str,
    bay_id: str,
    start_at: str,
    end_at: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Occupy a hazmat or quarantine bay for a bounded window."""
    return get_success_data(
        api.quarantine_line(
            return_line_id,
            f.quarantine_payload(bay_id, start_at, end_at),
            headers or users.CLERK,
        )
    )


def grade_line(
    api: ApiClient,
    return_line_id: str,
    condition_grade: str = GRADE_C,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Assign a condition grade, running the whole grading side-effect chain."""
    return get_success_data(
        api.grade_line(
            return_line_id,
            f.grade_payload(condition_grade),
            headers or users.GRADER,
        )
    )


def read_return_line(api: ApiClient, return_line_id: str) -> Dict[str, Any]:
    """Read one return line as CenterAdmin."""
    return get_success_data(api.get_return_line(return_line_id, users.ADMIN))


def read_client(api: ApiClient, client_id: str) -> Dict[str, Any]:
    """Read one client as CenterAdmin."""
    return get_success_data(api.get_client(client_id, users.ADMIN))


def read_audit(api: ApiClient, client_id: str) -> Dict[str, Any]:
    """Read one client's disposition-audit report as CenterAdmin."""
    return get_success_data(api.get_disposition_audit(client_id, users.ADMIN))


def read_rma(api: ApiClient, rma_id: str) -> Dict[str, Any]:
    """Read one authorization as CenterAdmin."""
    return get_success_data(api.get_rma(rma_id, users.ADMIN))


def read_work_order(api: ApiClient, work_order_id: str) -> Dict[str, Any]:
    """Read one work order as CenterAdmin."""
    return get_success_data(api.get_work_order(work_order_id, users.ADMIN))


def read_order(api: ApiClient, disposition_order_id: str) -> Dict[str, Any]:
    """Read one disposition order as CenterAdmin."""
    return get_success_data(
        api.get_disposition_order(disposition_order_id, users.ADMIN)
    )


def list_ledger(api: ApiClient, client_id: str) -> List[Dict[str, Any]]:
    """Every shrink-ledger entry for a client, in sequence order."""
    body = api.list_shrink_ledger_entries(
        users.ADMIN, {"client_id": client_id, "limit": 100}
    )
    return get_success_data(body)


def refund_release_for_line(api: ApiClient, return_line_id: str) -> Dict[str, Any]:
    """The single refund release grading created for a line."""
    rows = get_success_data(
        api.list_refund_releases(users.ADMIN, {"return_line_id": return_line_id})
    )
    assert len(rows) == 1, (
        f"expected exactly one refund release for the line, got {len(rows)}"
    )
    return rows[0]


def fraud_checks_for_line(api: ApiClient, return_line_id: str) -> List[Dict[str, Any]]:
    """Every fraud check recorded against a line."""
    return get_success_data(
        api.list_line_fraud_checks(return_line_id, users.ADMIN, {"limit": 100})
    )


def orders_for_line(api: ApiClient, return_line_id: str) -> List[Dict[str, Any]]:
    """Every disposition order recorded against a line."""
    return get_success_data(
        api.list_disposition_orders(
            users.ADMIN, {"return_line_id": return_line_id, "limit": 100}
        )
    )


def file_recall(
    api: ApiClient, catalog_item_id: str, recall_status: str = RECALL_MANDATORY
) -> Dict[str, Any]:
    """File a recall notice against a catalogue item as a CenterAdmin."""
    return get_success_data(
        api.recall_catalog_item(
            catalog_item_id, {"recall_status": recall_status}, users.ADMIN
        )
    )


def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    """Move the logical clock, which also runs the authorization expiry sweep."""
    return get_success_data(api.set_clock(instant, users.ADMIN))


# ─── Refurbishment ──────────────────────────────────────────────────────


def open_work_order(
    api: ApiClient, return_line_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Open a refurbishment work order; the caller becomes the technician."""
    return get_success_data(
        api.create_work_order(
            f.work_order_payload(return_line_id), headers or users.TECHNICIAN
        )
    )


def start_test(
    api: ApiClient,
    work_order_id: str,
    bay_id: str,
    start_at: str,
    end_at: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Reserve a GENERAL bay window and put the unit on test."""
    return get_success_data(
        api.start_test(
            work_order_id,
            f.start_test_payload(bay_id, start_at, end_at),
            headers or users.TECHNICIAN,
        )
    )


def record_test_result(
    api: ApiClient,
    work_order_id: str,
    result: str,
    labor_minutes: int = 10,
    parts_cost_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record a test outcome; the caller is stamped as qa_user_id."""
    return get_success_data(
        api.record_test_result(
            work_order_id,
            f.test_result_payload(
                result, labor_minutes=labor_minutes, parts_cost_cents=parts_cost_cents
            ),
            headers or users.QA_INSPECTOR,
        )
    )


def run_failed_test_cycle(
    api: ApiClient,
    work_order_id: str,
    bay_id: str,
    start_at: str,
    end_at: str,
    labor_minutes: int = 10,
) -> Dict[str, Any]:
    """One complete start-then-FAIL cycle on a work order."""
    start_test(api, work_order_id, bay_id, start_at, end_at)
    return record_test_result(
        api, work_order_id, TEST_RESULT_FAIL, labor_minutes=labor_minutes
    )


def run_passed_test_cycle(
    api: ApiClient,
    work_order_id: str,
    bay_id: str,
    start_at: str,
    end_at: str,
    labor_minutes: int = 10,
    parts_cost_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """One complete start-then-PASS cycle on a work order."""
    start_test(api, work_order_id, bay_id, start_at, end_at)
    return record_test_result(
        api,
        work_order_id,
        TEST_RESULT_PASS,
        labor_minutes=labor_minutes,
        parts_cost_cents=parts_cost_cents,
    )


def abandon_work_order(
    api: ApiClient, work_order_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Abandon a work order, sinking its cost so far to the shrink ledger."""
    return get_success_data(
        api.abandon_work_order(
            work_order_id, f.abandon_payload(), headers or users.TECHNICIAN
        )
    )


# ─── Disposition orders ─────────────────────────────────────────────────


def propose_order(
    api: ApiClient,
    return_line_id: str,
    channel_id: Optional[str] = None,
    window_start_at: Optional[str] = CHANNEL_WINDOW_A_START,
    window_end_at: Optional[str] = CHANNEL_WINDOW_A_END,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Propose a disposition order, reading the line's current version first."""
    line = read_return_line(api, return_line_id)
    return get_success_data(
        api.create_disposition_order(
            f.disposition_order_payload(
                return_line_id,
                line["version"],
                channel_id=channel_id,
                channel_window_start_at=window_start_at,
                channel_window_end_at=window_end_at,
                **overrides,
            ),
            headers or users.SUPERVISOR,
        )
    )


def approve_order(
    api: ApiClient, order_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Approve a proposed disposition order."""
    return get_success_data(
        api.approve_disposition_order(order_id, headers or users.SUPERVISOR)
    )


def execute_order(
    api: ApiClient,
    order_id: str,
    realized_unit_price_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute an approved disposition order, firing the five-link cascade."""
    return get_success_data(
        api.execute_disposition_order(
            order_id,
            headers or users.SUPERVISOR,
            f.execute_payload(realized_unit_price_cents),
        )
    )


def propose_and_approve(
    api: ApiClient,
    return_line_id: str,
    channel_id: Optional[str] = None,
    window_start_at: Optional[str] = CHANNEL_WINDOW_A_START,
    window_end_at: Optional[str] = CHANNEL_WINDOW_A_END,
    approver: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Propose an order and approve it, returning the approved order."""
    order = propose_order(
        api,
        return_line_id,
        channel_id=channel_id,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
    )
    return approve_order(api, order["id"], headers=approver)


# ─── Whole-world composites ─────────────────────────────────────────────


def received_scenario(
    api: ApiClient,
    client_kwargs: Optional[Dict[str, Any]] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
    gross_weight_grams: Optional[int] = None,
    tracking_reference: str = "TRK-1",
    rma_kwargs: Optional[Dict[str, Any]] = None,
    scan: bool = True,
) -> Dict[str, Any]:
    """A client, its catalogue, an issued authorization and one scanned carton.

    `items` is a list of catalogue-item keyword payloads. `lines` is a list of
    line specs; each may carry `item_index`, `authorized_quantity`,
    `reason_code`, `declared_serial`, plus the dock-side `scan_quantity`,
    `scan_reason_code` and `scanned_serial`. When `gross_weight_grams` is
    omitted the carton weighs exactly what the authorization expects.
    """
    client = make_client(api, **(client_kwargs or {}))
    item_specs = items if items is not None else [{}]
    item_rows = [make_catalog_item(api, client["id"], **spec) for spec in item_specs]

    line_specs = lines if lines is not None else [{}]
    rma_line_payloads = []
    for spec in line_specs:
        item = item_rows[spec.get("item_index", 0)]
        rma_line_payloads.append(
            {
                "catalog_item_id": item["id"],
                "authorized_quantity": spec.get("authorized_quantity", 1),
                "reason_code": spec.get("reason_code", REASON_DEFECTIVE),
                "declared_serial": spec.get("declared_serial"),
            }
        )
    issued = make_issued_rma(
        api,
        client["id"],
        [{k: v for k, v in p.items() if v is not None} for p in rma_line_payloads],
        **(rma_kwargs or {}),
    )

    weight_pairs = [
        (
            item_rows[spec.get("item_index", 0)]["unit_weight_grams"],
            spec.get("authorized_quantity", 1),
        )
        for spec in line_specs
    ]
    expected_weight = expected_weight_grams(*weight_pairs)
    carton_weight = (
        gross_weight_grams if gross_weight_grams is not None else expected_weight
    )

    result: Dict[str, Any] = {
        "client": client,
        "items": item_rows,
        "item": item_rows[0],
        "rma": issued["rma"],
        "rma_lines": issued["lines"],
        "rma_line": issued["lines"][0],
        "expected_weight_grams": expected_weight,
    }
    if not scan:
        return result

    receipt = make_receipt(
        api, issued["rma"]["id"], carton_weight, tracking_reference=tracking_reference
    )
    scanned = []
    for spec, rma_line in zip(line_specs, issued["lines"]):
        scanned.append(
            scan_line(
                api,
                receipt["id"],
                rma_line["id"],
                quantity=spec.get("scan_quantity", spec.get("authorized_quantity", 1)),
                reason_code=spec.get(
                    "scan_reason_code", spec.get("reason_code", REASON_DEFECTIVE)
                ),
                scanned_serial=spec.get("scanned_serial", spec.get("declared_serial")),
            )
        )
    result["receipt"] = receipt
    result["lines"] = scanned
    result["line"] = scanned[0]
    return result


def graded_scenario(
    api: ApiClient,
    client_kwargs: Optional[Dict[str, Any]] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
    grades: Optional[List[str]] = None,
    condition_grade: str = GRADE_C,
    grader: Optional[Dict[str, str]] = None,
    **received_kwargs: Any,
) -> Dict[str, Any]:
    """`received_scenario` with every scanned line graded.

    `grades` gives a per-line grade; when omitted every line takes
    `condition_grade`.
    """
    world = received_scenario(
        api,
        client_kwargs=client_kwargs,
        items=items,
        lines=lines,
        **received_kwargs,
    )
    graded = []
    for index, line in enumerate(world["lines"]):
        grade = grades[index] if grades is not None else condition_grade
        graded.append(grade_line(api, line["id"], grade, headers=grader))
    world["lines"] = graded
    world["line"] = graded[0]
    world["refund_release"] = refund_release_for_line(api, graded[0]["id"])
    return world


# ─── Named client rule-set presets ──────────────────────────────────────


def liquidation_client_kwargs(
    client_code: str, name: str = "Liquidation Client", **overrides: Any
) -> Dict[str, Any]:
    """A client whose rule set routes grade-C goods to liquidation.

    `restock_grade_floor` A keeps grade C out of restocking, the liquidation
    floor is the documented default of 0.30, and the fraud tolerance and
    exposure cap are set high enough that no fraud check and no exposure cap
    can interfere with the figure under test.
    """
    defaults: Dict[str, Any] = {
        "name": name,
        "client_code": client_code,
        "restock_grade_floor": "A",
        "refund_hold_hours": 48,
        "liquidation_floor_pct": 0.30,
        "fraud_tolerance_cents": 100000000,
        "donation_allowed": False,
        "destroy_requires_dual_signoff": False,
        "max_refund_exposure_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def auction_channel_kwargs(
    channel_code: str = "AUC1", **overrides: Any
) -> Dict[str, Any]:
    """An auction channel accepting A through D at a 12 percent commission."""
    defaults: Dict[str, Any] = {
        "name": "Alpha Auction",
        "channel_code": channel_code,
        "fee_pct": 0.12,
        "min_lot_value_cents": 0,
        "concurrent_lot_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def widget_item_kwargs(**overrides: Any) -> Dict[str, Any]:
    """The standard 20000-cent, 1200-gram, non-serialized widget."""
    defaults: Dict[str, Any] = {
        "sku": "WIDGET-1",
        "description": "Standard widget",
        "declared_value_cents": 20000,
        "unit_weight_grams": 1200,
        "serialized": False,
        "refurb_eligible": False,
        "secondary_market_floor_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
