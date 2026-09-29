"""Mill certificates and loadout orders (PRD 3.8, 3.9)."""

from flask import Blueprint

from core import (
    API_PREFIX, INTERNAL_ROLES, READ_ROLES_PLUS_CUSTOMER,
    D, ZERO, r2, rnd, guard, body, fail, actor, actor_role, now,
    want_str, want_num, want_int, want_dt,
    fk_ref, path_row, put_row, new_row, touch, get_row, rows,
    respond_object, filtered_list, field_eq, hours_between, _bad,
)
import calc
import cascades
import serial
from routes_kiln import _half_open_overlap, _window_ordering

bp = Blueprint("commercial", __name__, url_prefix=API_PREFIX)

READ = INTERNAL_ROLES
READ_SCOPED = READ_ROLES_PLUS_CUSTOMER


# ---------------------------------------------------------------------------
# Rung 45 — the Customer visibility scope
# ---------------------------------------------------------------------------
def _customer_scope():
    """Returns the acting customer's id, or None for the internal roles."""
    return actor() if actor_role() == "Customer" else None


def _scope_guard(row):
    scope = _customer_scope()
    if scope is not None and row["customer_id"] != scope:
        fail("ERR_CUSTOMER_SCOPE_VIOLATION")


def _scope_prefilter():
    scope = _customer_scope()
    if scope is None:
        return None
    return lambda row: row["customer_id"] == scope


# ===========================================================================
# Mill certificates
# ===========================================================================
@bp.post("/mill-certificates")
@guard(["QualityManager"])
def create_certificate():
    payload = body()
    batch = fk_ref(payload, "cement_batch_id", "batches")
    customer = fk_ref(payload, "customer_id", "customers")
    want_str(payload, "cement_batch_id")
    want_str(payload, "customer_id")
    certified = want_num(payload, "certified_tonnes")
    blaine_test = calc.newest_in_spec_lab_test(batch["id"], "BLAINE")
    strength_test = calc.newest_in_spec_lab_test(batch["id"], "COMPRESSIVE_STRENGTH_28D")
    row = new_row("certificates")
    row.update({
        "cement_batch_id": batch["id"],
        "customer_id": customer["id"],
        "certified_tonnes": certified,
        "status": "DRAFT",
        "certified_blaine_m2_per_kg": None if blaine_test is None else blaine_test["value"],
        "certified_strength_mpa": None if strength_test is None else strength_test["value"],
        "certified_so3_pct": None,
        "issued_by_user_id": None,
        "issued_at": None,
        "revoke_reason": None,
        "revoked_at": None,
    })
    put_row("certificates", row)
    return respond_object(serial.certificate_out(row), 201)


@bp.post("/mill-certificates/<mill_certificate_id>/issue")
@guard(["QualityManager"])
def issue_certificate(mill_certificate_id):
    cert = path_row("certificates", mill_certificate_id)
    batch = get_row("batches", cert["cement_batch_id"])
    # Rung 55 — two-person control against whoever recorded the strength test.
    strength = calc.newest_lab_test("cement_batch_id", cert["cement_batch_id"],
                                    "COMPRESSIVE_STRENGTH_28D")
    if strength is not None and actor() == strength["recorded_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if cert["status"] != "DRAFT":
        fail("ERR_INVALID_CERTIFICATE_STATE")
    if batch is None or batch["status"] not in ("QUALIFIED", "CERTIFIED"):
        fail("ERR_BATCH_NOT_QUALIFIED")
    customer = get_row("customers", cert["customer_id"])
    if (customer is None
            or batch["cement_type"] != customer["required_cement_type"]
            or D(batch["so3_pct"]) > D(customer["max_so3_pct"])):
        fail("ERR_CUSTOMER_SPEC_NOT_MET")
    # Rung 106 — the batch's other live certificates plus this one must fit.
    others = ZERO
    for other in rows("certificates"):
        if (other["id"] != cert["id"]
                and other["cement_batch_id"] == batch["id"]
                and other["status"] in ("DRAFT", "ISSUED")):
            others += D(other["certified_tonnes"])
    if rnd(others + D(cert["certified_tonnes"]), 2) > D(batch["cement_tonnes"]):
        fail("ERR_CERTIFIED_TONNES_EXCEED_BATCH")
    cert["status"] = "ISSUED"
    cert["issued_by_user_id"] = actor()
    cert["issued_at"] = now()
    cert["certified_so3_pct"] = batch["so3_pct"]
    touch(cert)
    if batch["status"] == "QUALIFIED":
        batch["status"] = "CERTIFIED"
        touch(batch)
    return respond_object(serial.certificate_out(cert))


@bp.post("/mill-certificates/<mill_certificate_id>/revoke")
@guard(["QualityManager"])
def revoke_certificate(mill_certificate_id):
    cert = path_row("certificates", mill_certificate_id)
    payload = body()
    reason = want_str(payload, "revoke_reason")
    if cert["status"] != "ISSUED":
        fail("ERR_INVALID_CERTIFICATE_STATE")
    cert["status"] = "REVOKED"
    cert["revoke_reason"] = reason
    cert["revoked_at"] = now()
    touch(cert)
    cascades.revoke_cascade(cert)
    return respond_object(serial.certificate_out(cert))


@bp.get("/mill-certificates/<mill_certificate_id>")
@guard(READ_SCOPED)
def get_certificate(mill_certificate_id):
    cert = path_row("certificates", mill_certificate_id)
    _scope_guard(cert)
    return respond_object(serial.certificate_out(cert))


@bp.get("/mill-certificates")
@guard(READ_SCOPED)
def list_certificates():
    return filtered_list("certificates", serial.certificate_out, {
        "cement_batch_id": field_eq("cement_batch_id"),
        "customer_id": field_eq("customer_id"),
        "status": field_eq("status"),
    }, prefilter=_scope_prefilter())


# ===========================================================================
# Loadout orders
# ===========================================================================
def _spout_conflicts(silo, window_start, window_end, statuses, skip_order_id=None):
    """Rung 107 — concurrent draws on one silo, half-open windows."""
    count = 0
    for order in rows("orders"):
        if order["cement_silo_id"] != silo["id"] or order["id"] == skip_order_id:
            continue
        if order["status"] not in statuses:
            continue
        if _half_open_overlap(window_start, window_end,
                              order["window_start"], order["window_end"]):
            count += 1
    return count


@bp.post("/loadout-orders")
@guard(["LogisticsPlanner"])
def create_order():
    payload = body()
    customer = fk_ref(payload, "customer_id", "customers")
    silo = fk_ref(payload, "cement_silo_id", "silos")
    cert = fk_ref(payload, "mill_certificate_id", "certificates")
    want_str(payload, "customer_id")
    want_str(payload, "cement_silo_id")
    want_str(payload, "mill_certificate_id")
    window_start = want_dt(payload, "window_start")
    window_end = want_dt(payload, "window_end")
    tonnes = want_num(payload, "tonnes")
    expected = want_int(payload, "expected_mill_certificate_version")
    if expected != cert["version"]:
        fail("ERR_STALE_CERTIFICATE_VERSION")
    if silo["status"] != "OPEN":
        fail("ERR_SILO_BLOCKED")
    _window_ordering(window_start, window_end)
    if silo["material_kind"] != "CEMENT":
        fail("ERR_SILO_KIND_MISMATCH")
    if D(tonnes) > D(calc.silo_available(silo)):
        fail("ERR_INSUFFICIENT_CEMENT")
    if cert["status"] != "ISSUED":
        fail("ERR_CERTIFICATE_NOT_ISSUED")
    if cert["customer_id"] != customer["id"]:
        fail("ERR_CERTIFICATE_CUSTOMER_MISMATCH")
    allocated = D(calc.certificate_allocated(cert["id"]))
    if rnd(allocated + D(tonnes), 2) > D(cert["certified_tonnes"]):
        fail("ERR_CERTIFICATE_ALLOCATION_EXCEEDED")
    if _spout_conflicts(silo, window_start, window_end,
                        ("RESERVED", "LOADING")) >= silo["loadout_spouts"]:
        fail("ERR_SILO_SPOUT_CAPACITY")
    scheduled_hours = hours_between(window_start, window_end)
    drawable = r2(D(silo["draw_rate_tonnes_per_hour"]) * D(scheduled_hours))
    if D(tonnes) > drawable:
        fail("ERR_DRAW_RATE_EXCEEDED")
    row = new_row("orders")
    row.update({
        "customer_id": customer["id"],
        "cement_silo_id": silo["id"],
        "mill_certificate_id": cert["id"],
        "window_start": window_start,
        "window_end": window_end,
        "scheduled_hours": scheduled_hours,
        "tonnes": tonnes,
        "loaded_tonnes": 0.00,
        "status": "RESERVED",
        "void_reason": None,
        "loading_started_at": None,
        "completed_at": None,
    })
    put_row("orders", row)
    silo["reserved_tonnes"] = r2(D(silo["reserved_tonnes"]) + D(tonnes))
    touch(silo)
    touch(cert)
    return respond_object(serial.order_out(row), 201)


@bp.post("/loadout-orders/<loadout_order_id>/start-loading")
@guard(["LogisticsPlanner"])
def start_loading(loadout_order_id):
    order = path_row("orders", loadout_order_id)
    if order["status"] != "RESERVED":
        fail("ERR_INVALID_ORDER_STATE")
    cert = get_row("certificates", order["mill_certificate_id"])
    if cert is None or cert["status"] != "ISSUED":
        fail("ERR_CERTIFICATE_NOT_ISSUED")
    silo = get_row("silos", order["cement_silo_id"])
    if silo is None or silo["status"] != "OPEN":
        fail("ERR_SILO_BLOCKED")
    if not (order["window_start"] <= now() < order["window_end"]):
        fail("ERR_LOADOUT_WINDOW_NOT_ACTIVE")
    loading = 0
    for other in rows("orders"):
        if (other["id"] != order["id"]
                and other["cement_silo_id"] == silo["id"]
                and other["status"] == "LOADING"):
            loading += 1
    if loading >= silo["loadout_spouts"]:
        fail("ERR_SILO_SPOUT_CAPACITY")
    order["status"] = "LOADING"
    order["loading_started_at"] = now()
    touch(order)
    return respond_object(serial.order_out(order))


@bp.post("/loadout-orders/<loadout_order_id>/complete")
@guard(["LogisticsPlanner"])
def complete_order(loadout_order_id):
    order = path_row("orders", loadout_order_id)
    payload = body()
    loaded = want_num(payload, "loaded_tonnes")
    if order["status"] != "LOADING":
        fail("ERR_INVALID_ORDER_STATE")
    if D(loaded) <= ZERO or D(loaded) > D(order["tonnes"]):
        _bad("loaded_tonnes", "must be positive and no greater than the reserved tonnage")
    order["status"] = "COMPLETED"
    order["loaded_tonnes"] = loaded
    order["completed_at"] = now()
    touch(order)
    silo = get_row("silos", order["cement_silo_id"])
    if silo is not None:
        silo["tonnes_on_hand"] = r2(D(silo["tonnes_on_hand"]) - D(loaded))
        silo["reserved_tonnes"] = r2(D(silo["reserved_tonnes"]) - D(order["tonnes"]))
        touch(silo)
    customer = get_row("customers", order["customer_id"])
    if customer is not None:
        touch(customer)
    return respond_object(serial.order_out(order))


@bp.post("/loadout-orders/<loadout_order_id>/void")
@guard(["LogisticsPlanner"])
def void_order(loadout_order_id):
    order = path_row("orders", loadout_order_id)
    payload = body()
    reason = want_str(payload, "void_reason")
    if order["status"] not in ("RESERVED", "LOADING", "COMPLETED"):
        fail("ERR_INVALID_ORDER_STATE")
    silo = get_row("silos", order["cement_silo_id"])
    if order["status"] == "COMPLETED":
        # The compensating void: the cement comes back on hand before the
        # order's loaded tonnage is cleared, so the arithmetic stays exact.
        loaded = D(order["loaded_tonnes"])
        if silo is None:
            fail("ERR_SILO_NOT_FOUND")
        if D(silo["tonnes_on_hand"]) + loaded > D(silo["capacity_tonnes"]):
            fail("ERR_SILO_CAPACITY_EXCEEDED")
        order["status"] = "VOIDED"
        order["void_reason"] = reason
        touch(order)
        silo["tonnes_on_hand"] = r2(D(silo["tonnes_on_hand"]) + loaded)
        touch(silo)
        order["loaded_tonnes"] = 0.00
    else:
        order["status"] = "VOIDED"
        order["void_reason"] = reason
        touch(order)
        if silo is not None:
            silo["reserved_tonnes"] = r2(
                D(silo["reserved_tonnes"]) - D(order["tonnes"])
            )
            touch(silo)
    customer = get_row("customers", order["customer_id"])
    if customer is not None:
        touch(customer)
    return respond_object(serial.order_out(order))


@bp.get("/loadout-orders/<loadout_order_id>")
@guard(READ_SCOPED)
def get_order(loadout_order_id):
    order = path_row("orders", loadout_order_id)
    _scope_guard(order)
    return respond_object(serial.order_out(order))


@bp.get("/loadout-orders")
@guard(READ_SCOPED)
def list_orders():
    return filtered_list("orders", serial.order_out, {
        "customer_id": field_eq("customer_id"),
        "cement_silo_id": field_eq("cement_silo_id"),
        "mill_certificate_id": field_eq("mill_certificate_id"),
        "status": field_eq("status"),
    }, prefilter=_scope_prefilter())
