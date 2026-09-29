"""Master data: terminals, grades, segments, shippers, history, tariffs, clock."""
from decimal import Decimal

from flask import Blueprint

import serializers as ser
from calc import ZERO
from cascades import recompute_segment_derate
from core import (bad_request, db, fail, field_bool, field_decimal, field_enum,
                  field_instant, field_int, field_string, get_body, lookup_path,
                  new_row, paginate, present, resolve_ref, respond_object, touch,
                  authenticate, acting_user, r2, r3)

bp = Blueprint("master", __name__)

ALL_ROLES = ("PipelineScheduler", "TariffAdministrator", "TerminalOperator", "Shipper")
STAFF = ("PipelineScheduler", "TariffAdministrator", "TerminalOperator")


def unique_or_fail(collection, field, value):
    for row in collection.values():
        if row.get(field) == value:
            bad_request("{} '{}' is already in use.".format(field, value))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(ALL_ROLES)
    body = get_body()
    instant = field_instant(body, "current_utc")
    db.clock = instant
    return respond_object({})


# ---------------------------------------------------------------------------
# Terminals
# ---------------------------------------------------------------------------
@bp.route("/pipeline/terminals", methods=["POST"])
def create_terminal():
    authenticate(("TariffAdministrator",))
    body = get_body()
    code = field_string(body, "terminal_code")
    name = field_string(body, "name")
    role_kind = field_enum(body, "role_kind", ("ORIGIN", "DESTINATION", "BOTH"))
    shell = field_decimal(body, "shell_capacity_bbl", positive=True)
    floor = field_decimal(body, "min_operating_inventory_bbl", non_negative=True)
    bays = 1
    if present(body, "injection_bays"):
        bays = field_int(body, "injection_bays", minimum=1)
    unique_or_fail(db.terminals, "terminal_code", code)
    row = new_row({
        "terminal_code": code,
        "name": name,
        "role_kind": role_kind,
        "shell_capacity_bbl": shell,
        "min_operating_inventory_bbl": floor,
        "injection_bays": bays,
        "inventory_bbl": r2(0),
    })
    db.terminals[row["id"]] = row
    return respond_object(ser.terminal_json(row), 201)


@bp.route("/pipeline/terminals/<row_id>/inventory-adjustments", methods=["POST"])
def adjust_inventory(row_id):
    authenticate(("TerminalOperator",))
    terminal = lookup_path(db.terminals, row_id, "ERR_REFERENCE_NOT_FOUND")
    body = get_body()
    segment = resolve_ref(body, "segment_id", db.segments)
    kind = field_enum(body, "adjustment_kind", ("INVENTORY", "LINEFILL"))
    delta = field_decimal(body, "adjustment_bbl")
    field_string(body, "reason")
    expected = field_int(body, "expected_terminal_version")
    if kind == "LINEFILL" and segment is None:
        bad_request("adjustment_kind LINEFILL requires 'segment_id'.")
    if expected != terminal["version"]:
        fail("ERR_STALE_TERMINAL_VERSION",
             "Terminal version {} does not match the expected {}.".format(
                 terminal["version"], expected))
    if kind == "LINEFILL":
        segment["linefill_bbl"] = r2(segment["linefill_bbl"] + delta)
        touch(segment)
    else:
        terminal["inventory_bbl"] = r2(terminal["inventory_bbl"] + delta)
    touch(terminal)
    return respond_object(ser.terminal_json(terminal))


@bp.route("/pipeline/terminals/<row_id>", methods=["GET"])
def read_terminal(row_id):
    authenticate(STAFF)
    row = lookup_path(db.terminals, row_id, "ERR_REFERENCE_NOT_FOUND")
    return respond_object(ser.terminal_json(row))


@bp.route("/pipeline/terminals", methods=["GET"])
def list_terminals():
    authenticate(STAFF)
    rows = list(db.terminals.values())
    rows = _filtered(rows, [("role_kind", "role_kind", "str")])
    rows.sort(key=lambda r: (r["terminal_code"], r["created_at"], r["_seq"]))
    return paginate(rows, ser.terminal_json)


def _filtered(rows, specs):
    from core import apply_filters
    return apply_filters(rows, specs)


# ---------------------------------------------------------------------------
# Product grades
# ---------------------------------------------------------------------------
@bp.route("/pipeline/product-grades", methods=["POST"])
def create_grade():
    authenticate(("TariffAdministrator",))
    body = get_body()
    code = field_string(body, "grade_code")
    name = field_string(body, "name")
    rank = field_int(body, "sequence_rank", minimum=1, maximum=9)
    sulfur = field_decimal(body, "max_sulfur_ppm", positive=True)
    rvp = field_decimal(body, "max_rvp_psi", positive=True)
    transmix = field_bool(body, "is_transmix_grade", default=False)
    unique_or_fail(db.product_grades, "grade_code", code)
    row = new_row({
        "grade_code": code,
        "name": name,
        "sequence_rank": rank,
        "max_sulfur_ppm": sulfur,
        "max_rvp_psi": rvp,
        "is_transmix_grade": bool(transmix),
    })
    db.product_grades[row["id"]] = row
    return respond_object(ser.grade_json(row), 201)


@bp.route("/pipeline/product-grades/<row_id>", methods=["GET"])
def read_grade(row_id):
    authenticate(ALL_ROLES)
    row = lookup_path(db.product_grades, row_id, "ERR_REFERENCE_NOT_FOUND")
    return respond_object(ser.grade_json(row))


@bp.route("/pipeline/product-grades", methods=["GET"])
def list_grades():
    authenticate(ALL_ROLES)
    rows = _filtered(list(db.product_grades.values()),
                     [("is_transmix_grade", "is_transmix_grade", "bool")])
    rows.sort(key=lambda r: (r["sequence_rank"], r["created_at"], r["_seq"]))
    return paginate(rows, ser.grade_json)


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------
@bp.route("/pipeline/segments", methods=["POST"])
def create_segment():
    authenticate(("TariffAdministrator",))
    body = get_body()
    origin = resolve_ref(body, "origin_terminal_id", db.terminals)
    destination = resolve_ref(body, "destination_terminal_id", db.terminals)
    grade = resolve_ref(body, "linefill_grade_id", db.product_grades)
    code = field_string(body, "segment_code")
    if origin is None:
        bad_request("Required field 'origin_terminal_id' is missing.")
    if destination is None:
        bad_request("Required field 'destination_terminal_id' is missing.")
    if grade is None:
        bad_request("Required field 'linefill_grade_id' is missing.")
    capacity = field_decimal(body, "capacity_bbl_per_cycle", positive=True)
    reserve = field_decimal(body, "transmix_reserve_bbl", non_negative=True)
    cut = field_decimal(body, "transmix_cut_bbl", non_negative=True)
    min_tender = field_decimal(body, "min_tender_bbl", positive=True)
    requirement = field_decimal(body, "linefill_requirement_bbl", non_negative=True)
    policy = field_enum(body, "proration_policy", ("HISTORY_WEIGHTED", "VOLUME_WEIGHTED"))
    if origin["role_kind"] not in ("ORIGIN", "BOTH"):
        bad_request("origin_terminal_id must name a terminal whose role_kind is ORIGIN or BOTH.")
    if destination["role_kind"] not in ("DESTINATION", "BOTH"):
        bad_request("destination_terminal_id must name a terminal whose role_kind is "
                    "DESTINATION or BOTH.")
    unique_or_fail(db.segments, "segment_code", code)
    row = new_row({
        "segment_code": code,
        "origin_terminal_id": origin["id"],
        "destination_terminal_id": destination["id"],
        "linefill_grade_id": grade["id"],
        "capacity_bbl_per_cycle": capacity,
        "transmix_reserve_bbl": reserve,
        "transmix_cut_bbl": cut,
        "min_tender_bbl": min_tender,
        "linefill_requirement_bbl": requirement,
        "linefill_bbl": r2(0),
        "proration_policy": policy,
        "operational_status": "OPERATIONAL",
        "derate_pct": r2(0),
        "in_transit_bbl": r2(0),
        "transmix_inventory_bbl": r2(0),
        "system_loss_bbl": r2(0),
    })
    db.segments[row["id"]] = row
    return respond_object(ser.segment_json(row), 201)


@bp.route("/pipeline/segments/<row_id>/proration-policy", methods=["POST"])
def change_policy(row_id):
    authenticate(("TariffAdministrator",))
    segment = lookup_path(db.segments, row_id, "ERR_REFERENCE_NOT_FOUND")
    body = get_body()
    policy = field_enum(body, "proration_policy", ("HISTORY_WEIGHTED", "VOLUME_WEIGHTED"))
    segment["proration_policy"] = policy
    touch(segment)
    return respond_object(ser.segment_json(segment))


@bp.route("/pipeline/segments/<row_id>", methods=["GET"])
def read_segment(row_id):
    authenticate(ALL_ROLES)
    row = lookup_path(db.segments, row_id, "ERR_REFERENCE_NOT_FOUND")
    return respond_object(ser.segment_json(row))


@bp.route("/pipeline/segments", methods=["GET"])
def list_segments():
    authenticate(ALL_ROLES)
    rows = _filtered(list(db.segments.values()), [
        ("origin_terminal_id", "origin_terminal_id", "str"),
        ("destination_terminal_id", "destination_terminal_id", "str"),
        ("linefill_grade_id", "linefill_grade_id", "str"),
        ("operational_status", "operational_status", "str"),
    ])
    rows.sort(key=lambda r: (r["segment_code"], r["created_at"], r["_seq"]))
    return paginate(rows, ser.segment_json)


# ---------------------------------------------------------------------------
# Shippers
# ---------------------------------------------------------------------------
@bp.route("/pipeline/shippers", methods=["POST"])
def create_shipper():
    authenticate(("TariffAdministrator",))
    body = get_body()
    code = field_string(body, "shipper_code", min_len=3, max_len=12)
    name = field_string(body, "name")
    limit = field_decimal(body, "credit_limit_usd", non_negative=True)
    unique_or_fail(db.shippers, "shipper_code", code)
    row = new_row({
        "shipper_code": code,
        "name": name,
        "status": "ACTIVE",
        "suspended_reason": None,
        "credit_limit_usd": r2(limit),
        "exposure_usd": r2(0),
    })
    db.shippers[row["id"]] = row
    return respond_object(ser.shipper_json(row), 201)


@bp.route("/pipeline/shippers/<row_id>/suspend", methods=["POST"])
def suspend_shipper(row_id):
    authenticate(("TariffAdministrator",))
    shipper = lookup_path(db.shippers, row_id, "ERR_REFERENCE_NOT_FOUND")
    body = get_body()
    reason = field_string(body, "suspended_reason")
    shipper["status"] = "SUSPENDED"
    shipper["suspended_reason"] = reason
    touch(shipper)
    return respond_object(ser.shipper_json(shipper))


@bp.route("/pipeline/shippers/<row_id>", methods=["GET"])
def read_shipper(row_id):
    authenticate(STAFF)
    row = lookup_path(db.shippers, row_id, "ERR_REFERENCE_NOT_FOUND")
    return respond_object(ser.shipper_json(row))


@bp.route("/pipeline/shippers", methods=["GET"])
def list_shippers():
    authenticate(STAFF)
    rows = _filtered(list(db.shippers.values()), [("status", "status", "str")])
    rows.sort(key=lambda r: (r["shipper_code"], r["created_at"], r["_seq"]))
    return paginate(rows, ser.shipper_json)


# ---------------------------------------------------------------------------
# Historical movement records (immutable)
# ---------------------------------------------------------------------------
HISTORY_READERS = ("PipelineScheduler", "TariffAdministrator")


@bp.route("/pipeline/shipping-history", methods=["POST"])
def create_history():
    authenticate(("TariffAdministrator",))
    body = get_body()
    shipper = resolve_ref(body, "shipper_id", db.shippers)
    segment = resolve_ref(body, "segment_id", db.segments)
    if shipper is None:
        bad_request("Required field 'shipper_id' is missing.")
    if segment is None:
        bad_request("Required field 'segment_id' is missing.")
    cycle_code = field_string(body, "cycle_code")
    volume = field_decimal(body, "actual_shipped_bbl", non_negative=True)
    ends_at = field_instant(body, "cycle_end_at")
    status = field_enum(body, "record_status", ("FINAL", "PROVISIONAL"))
    row = new_row({
        "shipper_id": shipper["id"],
        "segment_id": segment["id"],
        "cycle_code": cycle_code,
        "actual_shipped_bbl": r2(volume),
        "cycle_end_at": ends_at,
        "record_status": status,
    }, versioned=False)
    db.shipping_history[row["id"]] = row
    return respond_object(ser.history_json(row), 201)


@bp.route("/pipeline/shipping-history/<row_id>", methods=["GET"])
def read_history(row_id):
    authenticate(HISTORY_READERS)
    row = lookup_path(db.shipping_history, row_id, "ERR_REFERENCE_NOT_FOUND")
    return respond_object(ser.history_json(row))


@bp.route("/pipeline/shipping-history", methods=["GET"])
def list_history():
    authenticate(HISTORY_READERS)
    rows = _filtered(list(db.shipping_history.values()), [
        ("shipper_id", "shipper_id", "str"),
        ("segment_id", "segment_id", "str"),
        ("record_status", "record_status", "str"),
    ])
    rows.sort(key=lambda r: (r["cycle_end_at"], r["created_at"], r["_seq"]))
    return paginate(rows, ser.history_json)


# ---------------------------------------------------------------------------
# Tariffs
# ---------------------------------------------------------------------------
TARIFF_READERS = ("PipelineScheduler", "TariffAdministrator", "Shipper")


@bp.route("/pipeline/tariffs", methods=["POST"])
def create_tariff():
    authenticate(("TariffAdministrator",))
    body = get_body()
    segment = resolve_ref(body, "segment_id", db.segments)
    grade = resolve_ref(body, "grade_id", db.product_grades)
    if segment is None:
        bad_request("Required field 'segment_id' is missing.")
    if grade is None:
        bad_request("Required field 'grade_id' is missing.")
    base = field_decimal(body, "base_rate_usd_per_bbl", positive=True)
    tier1_min = field_decimal(body, "tier1_min_bbl", positive=True)
    tier1_rate = field_decimal(body, "tier1_rate_usd_per_bbl", positive=True)
    tier2_min = field_decimal(body, "tier2_min_bbl", positive=True)
    tier2_rate = field_decimal(body, "tier2_rate_usd_per_bbl", positive=True)
    tender = field_decimal(body, "tender_minimum_bbl", positive=True)
    penalty = field_decimal(body, "imbalance_penalty_rate_usd_per_bbl", non_negative=True)
    effective_from = field_instant(body, "effective_from")
    effective_to = field_instant(body, "effective_to", required=False)
    if tier2_min <= tier1_min:
        bad_request("'tier2_min_bbl' must be strictly greater than 'tier1_min_bbl'.")
    if effective_to is not None and effective_to <= effective_from:
        bad_request("'effective_to' must be strictly later than 'effective_from'.")
    row = new_row({
        "segment_id": segment["id"],
        "grade_id": grade["id"],
        "base_rate_usd_per_bbl": r3(base),
        "tier1_min_bbl": tier1_min,
        "tier1_rate_usd_per_bbl": r3(tier1_rate),
        "tier2_min_bbl": tier2_min,
        "tier2_rate_usd_per_bbl": r3(tier2_rate),
        "tender_minimum_bbl": tender,
        "imbalance_penalty_rate_usd_per_bbl": penalty,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
    })
    db.tariffs[row["id"]] = row
    return respond_object(ser.tariff_json(row), 201)


def _overlaps(a, b):
    a_end = a["effective_to"]
    b_end = b["effective_to"]
    if a_end is not None and b["effective_from"] >= a_end:
        return False
    if b_end is not None and a["effective_from"] >= b_end:
        return False
    return True


@bp.route("/pipeline/tariffs/<row_id>/activate", methods=["POST"])
def activate_tariff(row_id):
    authenticate(("TariffAdministrator",))
    tariff = lookup_path(db.tariffs, row_id, "ERR_REFERENCE_NOT_FOUND")
    if tariff["status"] != "DRAFT":
        fail("ERR_TARIFF_INVALID_STATE",
             "A tariff in {} cannot be activated.".format(tariff["status"]))
    tariff["status"] = "EFFECTIVE"
    touch(tariff)
    peers = [t for t in db.tariffs.values()
             if t["id"] != tariff["id"]
             and t["segment_id"] == tariff["segment_id"]
             and t["grade_id"] == tariff["grade_id"]
             and t["status"] == "EFFECTIVE"]
    peers.sort(key=lambda t: (t["created_at"], t["_seq"]))
    for peer in peers:
        if _overlaps(tariff, peer):
            peer["status"] = "SUPERSEDED"
            touch(peer)
    return respond_object(ser.tariff_json(tariff))


@bp.route("/pipeline/tariffs/<row_id>", methods=["GET"])
def read_tariff(row_id):
    authenticate(TARIFF_READERS)
    row = lookup_path(db.tariffs, row_id, "ERR_REFERENCE_NOT_FOUND")
    return respond_object(ser.tariff_json(row))


@bp.route("/pipeline/tariffs", methods=["GET"])
def list_tariffs():
    authenticate(TARIFF_READERS)
    rows = _filtered(list(db.tariffs.values()), [
        ("segment_id", "segment_id", "str"),
        ("grade_id", "grade_id", "str"),
        ("status", "status", "str"),
    ])
    rows.sort(key=lambda r: (r["effective_from"], r["created_at"], r["_seq"]), reverse=True)
    return paginate(rows, ser.tariff_json)
