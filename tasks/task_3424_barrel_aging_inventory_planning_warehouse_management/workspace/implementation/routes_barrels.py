"""Routes: barrels, occupancies, assessments, rotations, dump, withdraw."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import envelope
import serializers
import store
import validation as v

bp = Blueprint("barrels", __name__)

WOOD_ORIGINS = {"AMERICAN_WHITE_OAK", "FRENCH_OAK", "MIZUNARA"}
SPIRIT_TYPES = {"BOURBON", "RYE", "TENNESSEE", "SINGLE_MALT"}
ASSESSMENT_KINDS = {"EVAPORATION_READING", "QUALITY_SAMPLE"}


def _get_barrel_or_404(bid):
    barrel = store.barrels.get(bid)
    if barrel is None:
        raise envelope.err_not_found("Barrel not found")
    calc.refresh_barrel(barrel)
    return barrel


@bp.route("/barrel-aging/barrels", methods=["POST"])
def create_barrel():
    _, role = v.authenticate()
    v.require_role(role, ["WarehouseManager"])
    body = v.get_body()
    v.check_allowed_fields(body, {
        "slot_id", "wood_origin", "seasoning_months", "char_level",
        "spirit_type", "fill_proof", "fill_volume_liters", "min_maturation_months",
    })
    slot_id = v.req_str(body, "slot_id")
    wood_origin = v.req_enum(body, "wood_origin", WOOD_ORIGINS)
    seasoning = v.req_int(body, "seasoning_months", min_v=0)
    char_level = v.req_int(body, "char_level", min_v=1, max_v=4)
    spirit_type = v.req_enum(body, "spirit_type", SPIRIT_TYPES)
    fill_proof = v.req_number(body, "fill_proof", min_v=0, exclusive_min=True)
    fill_volume = v.req_number(body, "fill_volume_liters", min_v=0, exclusive_min=True)
    min_maturation = v.req_int(body, "min_maturation_months", min_v=0)

    # Gate 4: existence of the body-supplied slot id.
    slot = store.slots.get(slot_id)
    if slot is None:
        raise envelope.err_not_found("Warehouse slot not found")

    # Gate 6: destination rickhouse posture must be OPERATING.
    rickhouse = calc.rickhouse_for_slot(slot)
    if rickhouse is None or calc.posture(rickhouse) != "OPERATING":
        raise envelope.err_rickhouse_not_operating()

    # Gate 8: slot must be free of an overlapping OPEN occupancy.
    if calc.open_occupancy_on_slot(slot["id"]) is not None:
        raise envelope.err_slot_overlap()

    now = store.now()
    barrel = {
        "id": store.new_id(),
        "wood_origin": wood_origin,
        "seasoning_months": seasoning,
        "char_level": char_level,
        "spirit_type": spirit_type,
        "fill_proof": fill_proof,
        "fill_volume_liters": calc.to_dec(fill_volume),
        "min_maturation_months": min_maturation,
        "fill_date": now,
        # FILLED -> AGING happens within the creation request.
        "maturation_status": "AGING",
        "custody_status": "BONDED",
        "withdrawn_at": None,
        "withdrawn_volume_liters": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.barrels[barrel["id"]] = barrel

    occupancy = {
        "id": store.new_id(),
        "barrel_id": barrel["id"],
        "slot_id": slot["id"],
        "move_reason": "INITIAL_FILL",
        "start_at": now,
        "end_at": None,
        "created_at": now,
        "_seq": store.next_seq(),
    }
    store.occupancies[occupancy["id"]] = occupancy
    return envelope.ok_object(serializers.serialize_barrel(barrel), status=201)


@bp.route("/barrel-aging/barrels/<bid>", methods=["GET"])
def get_barrel(bid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    barrel = _get_barrel_or_404(bid)
    return envelope.ok_object(serializers.serialize_barrel(barrel))


@bp.route("/barrel-aging/barrels", methods=["GET"])
def list_barrels():
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    limit, offset = v.parse_pagination()
    maturation_filter = request.args.get("maturation_status")
    custody_filter = request.args.get("custody_status")
    spirit_filter = request.args.get("spirit_type")
    items = []
    for b in sorted(store.barrels.values(), key=lambda b: (b["created_at"], b["_seq"])):
        calc.refresh_barrel(b)
        if maturation_filter is not None and b["maturation_status"] != maturation_filter:
            continue
        if custody_filter is not None and b["custody_status"] != custody_filter:
            continue
        if spirit_filter is not None and b["spirit_type"] != spirit_filter:
            continue
        items.append(serializers.serialize_barrel(b))
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/barrels/<bid>/occupancies", methods=["GET"])
def list_barrel_occupancies(bid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    _get_barrel_or_404(bid)
    limit, offset = v.parse_pagination()
    status_filter = request.args.get("status")
    occs = calc.barrel_occupancies(bid)
    occs.sort(key=lambda o: (o["start_at"], o["_seq"]))
    items = []
    for o in occs:
        ser = serializers.serialize_occupancy(o)
        if status_filter is not None and ser["status"] != status_filter:
            continue
        items.append(ser)
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/barrels/<bid>/blend-components", methods=["GET"])
def list_barrel_components(bid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    _get_barrel_or_404(bid)
    limit, offset = v.parse_pagination()
    comps = calc.barrel_components(bid)
    comps.sort(key=lambda c: (c["created_at"], c["_seq"]))
    items = [serializers.serialize_component(c) for c in comps]
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/barrels/<bid>/reservations", methods=["GET"])
def list_barrel_reservations(bid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    _get_barrel_or_404(bid)
    limit, offset = v.parse_pagination()
    state_filter = request.args.get("state")
    res = [r for r in store.reservations.values() if r["barrel_id"] == bid]
    res.sort(key=lambda r: (r["created_at"], r["_seq"]))
    items = []
    for r in res:
        ser = serializers.serialize_reservation(r)
        if state_filter is not None and ser["state"] != state_filter:
            continue
        items.append(ser)
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/barrels/<bid>/assessments", methods=["GET"])
def list_assessments(bid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    _get_barrel_or_404(bid)
    limit, offset = v.parse_pagination()
    kind_filter = request.args.get("kind")
    assessments = calc.barrel_assessments(bid)
    assessments.sort(key=lambda a: (a["assessed_at"], a["_seq"]))
    items = []
    for a in assessments:
        if kind_filter is not None and a["kind"] != kind_filter:
            continue
        items.append(serializers.serialize_assessment(a))
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/barrels/<bid>/assessments", methods=["POST"])
def create_assessment(bid):
    _, role = v.authenticate()
    v.require_role(role, ["WarehouseManager"])
    body = v.get_body()
    v.check_allowed_fields(body, {
        "kind", "measured_volume_liters", "sample_draw_liters", "quality_score",
    })
    kind = v.req_enum(body, "kind", ASSESSMENT_KINDS)
    measured = None
    draw = None
    score = None
    if kind == "EVAPORATION_READING":
        if body.get("measured_volume_liters") is None:
            raise envelope.err_validation(
                "measured_volume_liters is required for EVAPORATION_READING"
            )
        measured = v.req_number(body, "measured_volume_liters")
        if body.get("sample_draw_liters") is not None:
            raise envelope.err_validation(
                "sample_draw_liters applies only to QUALITY_SAMPLE"
            )
        if body.get("quality_score") is not None:
            raise envelope.err_validation(
                "quality_score applies only to QUALITY_SAMPLE"
            )
    else:  # QUALITY_SAMPLE
        if body.get("sample_draw_liters") is None:
            raise envelope.err_validation(
                "sample_draw_liters is required for QUALITY_SAMPLE"
            )
        draw = v.req_number(body, "sample_draw_liters", min_v=0, exclusive_min=True)
        if body.get("measured_volume_liters") is not None:
            raise envelope.err_validation(
                "measured_volume_liters applies only to EVAPORATION_READING"
            )
        if body.get("quality_score") is not None:
            score = v.req_int(body, "quality_score", min_v=0, max_v=100)

    barrel = _get_barrel_or_404(bid)
    now = store.now()

    if kind == "QUALITY_SAMPLE":
        # Gate 8: 30-day buffer since the barrel's previous QUALITY_SAMPLE;
        # exactly 30 days is allowed.
        previous = [
            a for a in calc.barrel_assessments(bid) if a["kind"] == "QUALITY_SAMPLE"
        ]
        if previous:
            last = max(previous, key=lambda a: (a["assessed_at"], a["_seq"]))
            if now < last["assessed_at"] + timedelta(days=calc.SAMPLE_BUFFER_DAYS):
                raise envelope.err_sample_buffer()
    else:
        # Gate 10: reading may not exceed the current ledger volume.
        if calc.to_dec(measured) > calc.ledger_at(barrel):
            raise envelope.err_assessment_inconsistent()

    assessment = {
        "id": store.new_id(),
        "barrel_id": bid,
        "kind": kind,
        "measured_volume_liters": calc.to_dec(measured) if measured is not None else None,
        "sample_draw_liters": calc.to_dec(draw) if draw is not None else None,
        "quality_score": score,
        "assessed_at": now,
        "created_at": now,
        "_seq": store.next_seq(),
    }
    store.assessments[assessment["id"]] = assessment
    barrel["version"] += 1
    barrel["updated_at"] = now
    return envelope.ok_object(serializers.serialize_assessment(assessment), status=201)


@bp.route("/barrel-aging/barrels/<bid>/rotations", methods=["POST"])
def rotate_barrel(bid):
    _, role = v.authenticate()
    v.require_role(role, ["WarehouseManager"])
    body = v.get_body()
    v.check_allowed_fields(body, {"to_slot_id", "expected_barrel_version"})
    to_slot_id = v.req_str(body, "to_slot_id")
    expected = v.req_int(body, "expected_barrel_version")

    barrel = _get_barrel_or_404(bid)
    slot = store.slots.get(to_slot_id)
    if slot is None:
        raise envelope.err_not_found("Warehouse slot not found")

    # Gate 5: OCC on the barrel version.
    if expected != barrel["version"]:
        raise envelope.err_stale_barrel()

    # Gate 6: the barrel must be in a rotatable state (an OPEN occupancy).
    if barrel["maturation_status"] == "DUMPED" or barrel["custody_status"] == "WITHDRAWN":
        raise envelope.err_invalid_state("Barrel is not in a rotatable state")
    current = calc.open_occupancy_of_barrel(bid)
    if current is None:
        raise envelope.err_invalid_state("Barrel has no OPEN occupancy")

    # Gate 6 cross-entity: destination rickhouse must be OPERATING.
    rickhouse = calc.rickhouse_for_slot(slot)
    if rickhouse is None or calc.posture(rickhouse) != "OPERATING":
        raise envelope.err_rickhouse_not_operating()

    # Gate 8: destination slot free of an overlapping OPEN occupancy.
    if calc.open_occupancy_on_slot(slot["id"]) is not None:
        raise envelope.err_slot_overlap()

    now = store.now()
    current["end_at"] = now
    occupancy = {
        "id": store.new_id(),
        "barrel_id": bid,
        "slot_id": slot["id"],
        "move_reason": "ROTATION",
        "start_at": now,
        "end_at": None,
        "created_at": now,
        "_seq": store.next_seq(),
    }
    store.occupancies[occupancy["id"]] = occupancy
    barrel["version"] += 1
    barrel["updated_at"] = now
    return envelope.ok_object(serializers.serialize_barrel(barrel))


@bp.route("/barrel-aging/barrels/<bid>/dump", methods=["POST"])
def dump_barrel(bid):
    _, role = v.authenticate()
    v.require_role(role, ["WarehouseManager"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    barrel = _get_barrel_or_404(bid)

    if barrel["maturation_status"] not in ("AGING", "MATURE_ELIGIBLE"):
        raise envelope.err_invalid_state("Barrel is not in AGING or MATURE_ELIGIBLE")

    # Gate 9: no COMMITTED blend component may reference the barrel.
    if calc.has_committed_component(bid):
        raise envelope.err_barrel_in_committed_blend()

    now = store.now()
    barrel["maturation_status"] = "DUMPED"
    current = calc.open_occupancy_of_barrel(bid)
    if current is not None:
        current["end_at"] = now
    barrel["version"] += 1
    barrel["updated_at"] = now
    return envelope.ok_object(serializers.serialize_barrel(barrel))


@bp.route("/barrel-aging/barrels/<bid>/withdraw", methods=["POST"])
def withdraw_barrel(bid):
    _, role = v.authenticate()
    v.require_role(role, ["WarehouseManager"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    barrel = _get_barrel_or_404(bid)

    # Join gate: withdrawal demands DUMPED maturation, BONDED custody.
    if barrel["maturation_status"] != "DUMPED" or barrel["custody_status"] != "BONDED":
        raise envelope.err_invalid_state("Withdrawal requires DUMPED and BONDED")

    # Gate 7 compliance: a FILED or ACCEPTED report must cover now.
    now = store.now()
    covered = any(
        rep["state"] in ("FILED", "ACCEPTED")
        and rep["period_start"] <= now <= rep["period_end"]
        for rep in store.reports.values()
    )
    if not covered:
        raise envelope.err_covering_report()

    # Gate 9: no ACTIVE reservation on the barrel.
    for r in store.reservations.values():
        if r["barrel_id"] == bid:
            calc.refresh_reservation(r)
            if r["state"] == "ACTIVE":
                raise envelope.err_barrel_reserved()

    barrel["custody_status"] = "WITHDRAWN"
    barrel["withdrawn_at"] = now
    barrel["withdrawn_volume_liters"] = calc.ledger_at(barrel)
    barrel["version"] += 1
    barrel["updated_at"] = now
    return envelope.ok_object(serializers.serialize_barrel(barrel))
