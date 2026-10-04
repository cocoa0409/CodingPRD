"""PlanogramVersion, PlanogramSlot and the revenue-attribution computed read."""

from flask import Blueprint, request

import calculations as calc
import db
import middleware as mw
import response as resp
import serializers as ser
from errors import ApiError

bp = Blueprint("planograms", __name__)

POG_READ_ROLES = ["PlatformAdmin", "AssortmentPlanner", "BoutiqueManager"]
SLOT_STATUSES = {"PLANNED", "APPLIED", "VERIFIED", "FROZEN", "VACATED"}
TIERS = {"FULL", "REGIONAL_TWEAK", "MINIMAL"}


# ---------------------------------------------------------------------------
# PlanogramVersion
# ---------------------------------------------------------------------------

@bp.post("/retail-ops/planogram-versions")
def create_version():
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner"])
    data = mw.body()

    location_id = mw.required(data, "location_id")
    location_rec = db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")

    tier = mw.required(data, "assortment_tier")
    if tier not in TIERS:
        raise ApiError("ERR_INVALID_REQUEST", "assortment_tier is not a declared tier.")
    effective_date = db.fmt_ts(db.parse_ts(mw.required(data, "effective_date"), "effective_date"))

    rec = db.new_record({
        "location_id": location_rec["id"],
        "assortment_tier": tier,
        "effective_date": effective_date,
        "status": "DRAFT",
        "superseded_by_version_id": None,
        "slot_count": 0,
        "published_at": None,
    })

    clone_from = mw.optional(data, "clone_slots_from_version_id", None)
    if clone_from:
        source = db.get_or_404(db.planogram_versions, clone_from, "ERR_PLANOGRAM_NOT_FOUND")
        db.planogram_versions[rec["id"]] = rec
        for slot in list(db.planogram_slots.values()):
            if slot.get("planogram_version_id") != source["id"]:
                continue
            if slot.get("status") == "VACATED":
                continue
            copy = db.new_record({
                "planogram_version_id": rec["id"],
                "item_id": slot.get("item_id"),
                "slot_position": slot.get("slot_position"),
                "facings": slot.get("facings", 1),
                "min_presentation_units": slot.get("min_presentation_units", 1),
                "status": "PLANNED",
                "applied_at": None,
                "verified_at": None,
            })
            db.planogram_slots[copy["id"]] = copy
        calc.recompute_slot_count(rec)
    else:
        db.planogram_versions[rec["id"]] = rec

    return resp.ok(ser.planogram_version(rec), 201)


@bp.get("/retail-ops/planogram-versions")
def list_versions():
    ctx = mw.context()
    mw.require_role(ctx, POG_READ_ROLES)
    records = resp.order_records([r for r in db.planogram_versions.values() if mw.matches(r, {
        "location_id": mw.query_str("location_id"),
        "status": mw.query_str("status"),
        "assortment_tier": mw.query_str("assortment_tier"),
        "superseded_by_version_id": mw.query_str("superseded_by_version_id"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.planogram_version(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/planogram-versions/<version_id>")
def get_version(version_id):
    ctx = mw.context()
    mw.require_role(ctx, POG_READ_ROLES)
    rec = db.get_or_404(db.planogram_versions, version_id, "ERR_PLANOGRAM_NOT_FOUND")
    return resp.ok(ser.planogram_version(rec))


@bp.put("/retail-ops/planogram-versions/<version_id>")
def update_version(version_id):
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner"])
    rec = db.get_or_404(db.planogram_versions, version_id, "ERR_PLANOGRAM_NOT_FOUND")
    data = mw.body()

    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    if data.get("assortment_tier") is not None:
        tier = mw.coerce(data["assortment_tier"], "assortment_tier", str)
        if tier not in TIERS:
            raise ApiError("ERR_INVALID_REQUEST", "assortment_tier is not a declared tier.")
        rec["assortment_tier"] = tier
    if data.get("effective_date") is not None:
        rec["effective_date"] = db.fmt_ts(db.parse_ts(data["effective_date"], "effective_date"))

    db.touch(rec)
    return resp.ok(ser.planogram_version(rec))


@bp.delete("/retail-ops/planogram-versions/<version_id>")
def delete_version(version_id):
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner"])
    rec = db.get_or_404(db.planogram_versions, version_id, "ERR_PLANOGRAM_NOT_FOUND")

    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    for slot_id, slot in list(db.planogram_slots.items()):
        if slot.get("planogram_version_id") == rec["id"]:
            del db.planogram_slots[slot_id]
    del db.planogram_versions[rec["id"]]

    location_rec = db.locations.get(rec.get("location_id"))
    if location_rec is not None:
        db.touch(location_rec)
    return resp.no_content()


@bp.post("/retail-ops/planogram-versions/<version_id>/publish")
def publish_version(version_id):
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner"])
    rec = db.get_or_404(db.planogram_versions, version_id, "ERR_PLANOGRAM_NOT_FOUND")

    location_rec = db.locations.get(rec.get("location_id"))

    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    # Priority 22 — publish readiness.
    calc.recompute_slot_count(rec)
    if rec.get("slot_count", 0) < 6:
        raise ApiError("ERR_PLANOGRAM_VERSION_CONFLICT")

    effective = db.parse_ts(rec.get("effective_date"), "effective_date")
    for other in db.planogram_versions.values():
        if other["id"] == rec["id"] or other.get("location_id") != rec.get("location_id"):
            continue
        if other.get("status") == "DRAFT":
            if db.parse_ts(other.get("effective_date"), "effective_date") < effective:
                raise ApiError("ERR_PLANOGRAM_VERSION_CONFLICT")

    # The location's previously published version is superseded first.
    previous = None
    for other in db.planogram_versions.values():
        if other["id"] == rec["id"] or other.get("location_id") != rec.get("location_id"):
            continue
        if other.get("status") != "PUBLISHED":
            continue
        if db.parse_ts(other.get("effective_date"), "effective_date") < effective:
            if previous is None or db.parse_ts(previous.get("effective_date"), "effective_date") < \
                    db.parse_ts(other.get("effective_date"), "effective_date"):
                previous = other

    if previous is not None:
        previous["status"] = "SUPERSEDED"
        previous["superseded_by_version_id"] = rec["id"]
        for slot in db.planogram_slots.values():
            if slot.get("planogram_version_id") == previous["id"] and slot.get("status") == "APPLIED":
                slot["status"] = "FROZEN"
                db.touch(slot)
        db.touch(previous)

    rec["status"] = "PUBLISHED"
    rec["published_at"] = db.fmt_ts(db.now())
    for slot in db.planogram_slots.values():
        if slot.get("planogram_version_id") == rec["id"] and slot.get("status") == "PLANNED":
            slot["status"] = "APPLIED"
            slot["applied_at"] = db.fmt_ts(db.now())
            db.touch(slot)
    db.touch(rec)

    if location_rec is not None:
        location_rec["active_planogram_version_id"] = rec["id"]
        db.touch(location_rec)
    return resp.ok(ser.planogram_version(rec))


@bp.post("/retail-ops/planogram-versions/<version_id>/retire")
def retire_version(version_id):
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner"])
    rec = db.get_or_404(db.planogram_versions, version_id, "ERR_PLANOGRAM_NOT_FOUND")

    if rec.get("status") != "SUPERSEDED":
        raise ApiError("ERR_INVALID_STATE")

    published_at = rec.get("published_at")
    if published_at is None:
        raise ApiError("ERR_INVALID_STATE")
    if db.now() < db.plus_days(db.parse_ts(published_at, "published_at"), 30):
        raise ApiError("ERR_INVALID_STATE")

    rec["status"] = "RETIRED"
    for slot in db.planogram_slots.values():
        if slot.get("planogram_version_id") == rec["id"] and slot.get("status") == "FROZEN":
            slot["status"] = "VACATED"
            db.touch(slot)
    db.touch(rec)
    return resp.ok(ser.planogram_version(rec))


@bp.get("/retail-ops/planogram-versions/<version_id>/region-fit")
def version_region_fit(version_id):
    ctx = mw.context()
    mw.require_role(ctx, POG_READ_ROLES)
    rec = db.get_or_404(db.planogram_versions, version_id, "ERR_PLANOGRAM_NOT_FOUND")
    return resp.ok(ser.region_fit(rec))


# ---------------------------------------------------------------------------
# PlanogramSlot
# ---------------------------------------------------------------------------

def _validate_slot_target(version_rec, item_rec):
    location_rec = db.locations.get(version_rec.get("location_id"))
    if not calc.theme_carried(location_rec, item_rec.get("theme_code")):
        raise ApiError("ERR_PLANOGRAM_SLOT_CONFLICT")
    return True


@bp.post("/retail-ops/planogram-slots")
def create_slot():
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner"])
    data = mw.body()

    version_id = mw.required(data, "planogram_version_id")
    version_rec = db.get_or_404(db.planogram_versions, version_id, "ERR_PLANOGRAM_NOT_FOUND")
    item_id = mw.required(data, "item_id")
    item_rec = db.get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")

    if version_rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    position = mw.required(data, "slot_position", int)
    facings = mw.optional(data, "facings", 1, int)
    if facings < 1:
        raise ApiError("ERR_INVALID_REQUEST", "facings must be at least 1.")
    min_units = mw.optional(data, "min_presentation_units", 1, int)
    if min_units < 1:
        raise ApiError("ERR_INVALID_REQUEST", "min_presentation_units must be at least 1.")

    # Priority 21 — slot-position uniqueness and the theme-carry rule.
    for slot in db.planogram_slots.values():
        if slot.get("planogram_version_id") == version_rec["id"] and \
                slot.get("slot_position") == position and slot.get("status") != "VACATED":
            raise ApiError("ERR_PLANOGRAM_SLOT_CONFLICT")

    # Priority 23 — the first-class regional-assortment refusal.
    location_rec = db.locations.get(version_rec.get("location_id"))
    if not calc.theme_carried(location_rec, item_rec.get("theme_code")):
        raise ApiError("ERR_NO_REGIONAL_ASSORTMENT")

    rec = db.new_record({
        "planogram_version_id": version_rec["id"],
        "item_id": item_rec["id"],
        "slot_position": position,
        "facings": facings,
        "min_presentation_units": min_units,
        "status": "PLANNED",
        "applied_at": None,
        "verified_at": None,
    })
    db.planogram_slots[rec["id"]] = rec
    calc.recompute_slot_count(version_rec)
    return resp.ok(ser.planogram_slot(rec), 201)


@bp.get("/retail-ops/planogram-slots")
def list_slots():
    ctx = mw.context()
    mw.require_role(ctx, POG_READ_ROLES)
    records = resp.order_records([r for r in db.planogram_slots.values() if mw.matches(r, {
        "planogram_version_id": mw.query_str("planogram_version_id"),
        "item_id": mw.query_str("item_id"),
        "status": mw.query_str("status"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.planogram_slot(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/planogram-slots/<slot_id>")
def get_slot(slot_id):
    ctx = mw.context()
    mw.require_role(ctx, POG_READ_ROLES)
    rec = db.get_or_404(db.planogram_slots, slot_id, "ERR_PLANOGRAM_NOT_FOUND")
    return resp.ok(ser.planogram_slot(rec))


@bp.put("/retail-ops/planogram-slots/<slot_id>")
def reshape_slot(slot_id):
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner"])
    rec = db.get_or_404(db.planogram_slots, slot_id, "ERR_PLANOGRAM_NOT_FOUND")
    data = mw.body()

    version_rec = db.get_or_404(db.planogram_versions, rec.get("planogram_version_id"),
                                "ERR_PLANOGRAM_NOT_FOUND")

    if rec.get("status") != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")

    # OCC on the parent version — non-optional on this endpoint (PRD 2.6).
    expected = mw.required(data, "expected_planogram_version_version", int)
    if expected != version_rec.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    if data.get("facings") is not None:
        facings = mw.coerce(data["facings"], "facings", int)
        if facings < 1:
            raise ApiError("ERR_INVALID_REQUEST", "facings must be at least 1.")
        rec["facings"] = facings
    if data.get("slot_position") is not None:
        position = mw.coerce(data["slot_position"], "slot_position", int)
        # Priority 21 — uniqueness within the version.
        for slot in db.planogram_slots.values():
            if slot["id"] == rec["id"]:
                continue
            if slot.get("planogram_version_id") == version_rec["id"] and \
                    slot.get("slot_position") == position and slot.get("status") != "VACATED":
                raise ApiError("ERR_PLANOGRAM_SLOT_CONFLICT")
        rec["slot_position"] = position

    db.touch(rec)
    calc.recompute_slot_count(version_rec)
    db.touch(version_rec)
    return resp.ok(ser.planogram_slot(rec))


@bp.post("/retail-ops/planogram-slots/<slot_id>/apply")
def apply_slot(slot_id):
    ctx = mw.context()
    mw.require_role(ctx, ["RetailLead", "BoutiqueManager"])
    rec = db.get_or_404(db.planogram_slots, slot_id, "ERR_PLANOGRAM_NOT_FOUND")

    if rec.get("status") != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")

    rec["status"] = "APPLIED"
    rec["applied_at"] = db.fmt_ts(db.now())
    db.touch(rec)
    return resp.ok(ser.planogram_slot(rec))


@bp.post("/retail-ops/planogram-slots/<slot_id>/verify")
def verify_slot(slot_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.planogram_slots, slot_id, "ERR_PLANOGRAM_NOT_FOUND")

    if rec.get("status") != "APPLIED":
        raise ApiError("ERR_INVALID_STATE")

    rec["status"] = "VERIFIED"
    rec["verified_at"] = db.fmt_ts(db.now())
    db.touch(rec)
    return resp.ok(ser.planogram_slot(rec))


# ---------------------------------------------------------------------------
# Revenue attribution
# ---------------------------------------------------------------------------

@bp.get("/retail-ops/revenue-attribution")
def revenue_attribution():
    ctx = mw.context()
    mw.require_role(ctx, ["PlatformAdmin", "AssortmentPlanner", "BoutiqueManager", "RetailLead"])
    store_day_id = mw.query_str("store_day_id")
    if not store_day_id:
        raise ApiError("ERR_INVALID_REQUEST", "store_day_id is required.")
    db.get_or_404(db.store_days, store_day_id, "ERR_STORE_DAY_NOT_FOUND")
    return resp.ok(ser.revenue_attribution(store_day_id, mw.query_str("variant")))