"""Pastures, capacity assessments and drought readings."""
from flask import Blueprint, request

from common import (authenticate, body_of, dec, opt_int, parse_dt, req_dt_str,
                    req_enum, req_int, req_num, req_str)
from derive import (DROUGHT_CONSECUTIVE_REQUIRED, DROUGHT_FORAGE_FLOOR_PCT,
                    DROUGHT_RECOVERY_INDEX, LIVE_LIFECYCLES,
                    apply_drought_cascade, apply_effective_assessment,
                    capacity_rating, contracts_of_pasture, drought_run_length,
                    recompute_pasture, sorted_records)
from envelope import created, listing, ok, pagination, public, public_list
from errors import ApiError
from store import db, new_record, touch

bp = Blueprint("pastures", __name__)

ALL_ROLES = ("Grazier", "CattleOwner", "RangeConsultant", "PlatformAdmin")

FORAGE_TYPES = ("NATIVE_RANGE", "IMPROVED_PASTURE", "COOL_SEASON_MIX", "WARM_SEASON_MIX")
WATER_SOURCES = ("WELL", "CREEK", "PIPELINE", "POND")
FENCE_CLASSES = ("CLASS_A", "CLASS_B", "CLASS_C")
OPERATIONAL_STATUSES = ("DRAFT", "AVAILABLE", "CLOSED")
ASSESSMENT_METHODS = ("DRY_MATTER", "STOCKING_HISTORY")


def get_pasture(pasture_id):
    pasture = db.pastures.get(pasture_id)
    if pasture is None:
        raise ApiError("ERR_PASTURE_NOT_FOUND", "Pasture does not exist.")
    return pasture


@bp.post("/grazing/pastures")
def create_pasture():
    actor = authenticate(("Grazier",))
    body = body_of()
    name = req_str(body, "name")
    acres = req_num(body, "acres", gt=0)
    forage_type = req_enum(body, "forage_type", FORAGE_TYPES)
    water_source_type = req_enum(body, "water_source_type", WATER_SOURCES)
    fence_class = req_enum(body, "fence_class", FENCE_CLASSES)
    prior_season_head_days = opt_int(body, "prior_season_head_days", 0, minv=0)

    rec = new_record()
    rec.update({
        "grazier_id": actor.user_id,
        "name": name,
        "acres": acres,
        "forage_type": forage_type,
        "water_source_type": water_source_type,
        "fence_class": fence_class,
        "prior_season_head_days": prior_season_head_days,
        "operational_status": "DRAFT",
        "effective_assessment_id": None,
        "rated_aum": 0,
        "rated_head_days": 0,
        "committed_head_days": 0,
        "capacity_utilization_pct": 0,
        "stocked_head_count": 0,
        "drought_destock_flag": False,
        "open_critical_ticket_count": 0,
        "grazing_posture": "OPEN",
    })
    db.pastures[rec["id"]] = rec
    return created(public(rec))


@bp.get("/grazing/pastures/<pasture_id>")
def read_pasture(pasture_id):
    authenticate(ALL_ROLES)
    return ok(public(get_pasture(pasture_id)))


@bp.get("/grazing/pastures")
def list_pastures():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = sorted_records(db.pastures.values())
    for field in ("grazier_id", "operational_status", "grazing_posture", "effective_assessment_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(public_list(rows), limit, offset)


@bp.post("/grazing/pastures/<pasture_id>/status")
def pasture_status(pasture_id):
    actor = authenticate(("Grazier",))
    pasture = get_pasture(pasture_id)
    body = body_of()
    to_status = req_enum(body, "to_status", OPERATIONAL_STATUSES)

    if pasture["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the owning grazier may drive this pasture.")

    current = pasture["operational_status"]
    allowed = {("DRAFT", "AVAILABLE"), ("DRAFT", "CLOSED"), ("AVAILABLE", "CLOSED")}
    if (current, to_status) not in allowed:
        raise ApiError("ERR_PASTURE_INVALID_STATE",
                       "Pasture cannot move from %s to %s." % (current, to_status))

    if to_status == "AVAILABLE":
        has_assessment = any(a["pasture_id"] == pasture["id"] for a in db.assessments.values())
        if not has_assessment:
            raise ApiError("ERR_NO_CAPACITY_ASSESSMENT",
                           "The pasture has no capacity assessment.")
    else:  # CLOSED
        if current == "AVAILABLE":
            for contract in contracts_of_pasture(pasture["id"]):
                if contract["lifecycle_status"] in LIVE_LIFECYCLES:
                    raise ApiError("ERR_PASTURE_HAS_ACTIVE_CONTRACTS",
                                   "The pasture still carries live contracts.")

    pasture["operational_status"] = to_status
    if to_status == "AVAILABLE":
        apply_effective_assessment(pasture)
    touch(pasture)
    recompute_pasture(pasture)
    return ok(public(pasture))


@bp.post("/grazing/pastures/<pasture_id>/capacity-assessments")
def file_assessment(pasture_id):
    actor = authenticate(("RangeConsultant",))
    pasture = get_pasture(pasture_id)
    body = body_of()
    expected_version = req_int(body, "expected_pasture_version")
    method = req_enum(body, "method", ASSESSMENT_METHODS)
    utilization_pct = req_num(body, "utilization_pct", gt=0, maxv=60)
    assessment_date = req_dt_str(body, "assessment_date")
    if method == "DRY_MATTER":
        forage_dm = req_num(body, "forage_dry_matter_lbs_per_acre", minv=0)
    else:
        forage_dm = body.get("forage_dry_matter_lbs_per_acre")
        if forage_dm is None:
            forage_dm = 0
        elif not isinstance(forage_dm, (int, float)) or isinstance(forage_dm, bool) or forage_dm < 0:
            raise ApiError("ERR_VALIDATION", "forage_dry_matter_lbs_per_acre must be a number >= 0.")

    if expected_version != pasture["version"]:
        raise ApiError("ERR_STALE_PASTURE_VERSION",
                       "expected_pasture_version does not match the pasture's current version.")

    if pasture["operational_status"] not in ("DRAFT", "AVAILABLE"):
        raise ApiError("ERR_PASTURE_INVALID_STATE",
                       "A closed pasture cannot be assessed.")

    rated_aum, rated_head_days = capacity_rating(pasture, method, forage_dm, utilization_pct)

    rec = new_record(common_fields=False)
    rec.update({
        "pasture_id": pasture["id"],
        "assessor_id": actor.user_id,
        "method": method,
        "forage_dry_matter_lbs_per_acre": forage_dm,
        "utilization_pct": utilization_pct,
        "assessment_date": assessment_date,
        "rated_aum": rated_aum,
        "rated_head_days": rated_head_days,
    })
    db.assessments[rec["id"]] = rec

    apply_effective_assessment(pasture)
    touch(pasture)
    recompute_pasture(pasture)
    return created(public(rec))


@bp.get("/grazing/capacity-assessments/<assessment_id>")
def read_assessment(assessment_id):
    authenticate(ALL_ROLES)
    row = db.assessments.get(assessment_id)
    if row is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND", "Capacity assessment does not exist.")
    return ok(public(row))


@bp.get("/grazing/capacity-assessments")
def list_assessments():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = sorted_records(db.assessments.values())
    for field in ("pasture_id", "assessor_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(public_list(rows), limit, offset)


@bp.post("/grazing/pastures/<pasture_id>/drought-readings")
def file_drought_reading(pasture_id):
    authenticate(("RangeConsultant",))
    pasture = get_pasture(pasture_id)
    body = body_of()
    reading_date = req_dt_str(body, "reading_date")
    drought_index = req_int(body, "drought_index", minv=0, maxv=5)
    forage_remaining_pct = req_num(body, "forage_remaining_pct", minv=0, maxv=100)

    rec = new_record(common_fields=False)
    rec.update({
        "pasture_id": pasture["id"],
        "reading_date": reading_date,
        "drought_index": drought_index,
        "forage_remaining_pct": forage_remaining_pct,
        "consecutive_severe_count": 0,
        "triggered_destock": False,
    })
    db.drought_readings[rec["id"]] = rec

    rec["consecutive_severe_count"] = drought_run_length(pasture["id"], rec)

    forage = dec(forage_remaining_pct)
    orders_destock = (rec["consecutive_severe_count"] >= DROUGHT_CONSECUTIVE_REQUIRED
                      or forage <= DROUGHT_FORAGE_FLOOR_PCT)
    if not pasture["drought_destock_flag"] and orders_destock:
        rec["triggered_destock"] = True
        apply_drought_cascade(pasture, rec)
    elif (pasture["drought_destock_flag"]
          and drought_index <= DROUGHT_RECOVERY_INDEX
          and forage > DROUGHT_FORAGE_FLOOR_PCT):
        pasture["drought_destock_flag"] = False
        touch(pasture)
        recompute_pasture(pasture)

    return created(public(rec))


@bp.get("/grazing/pastures/<pasture_id>/drought-readings")
def list_drought_readings(pasture_id):
    authenticate(ALL_ROLES)
    pasture = get_pasture(pasture_id)
    limit, offset = pagination()
    rows = [r for r in db.drought_readings.values() if r["pasture_id"] == pasture["id"]]
    rows.sort(key=lambda r: (parse_dt(r["reading_date"]), r["_seq"]), reverse=True)
    return listing(public_list(rows), limit, offset)
