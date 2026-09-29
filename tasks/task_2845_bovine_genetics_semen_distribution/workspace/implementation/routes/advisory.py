"""Breeding advisory: customer herds and the mating selector engine (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import config
import envelope
import resolve
import serializers
import store
import validate
from errors import fail
from validate import F, COUNTRY_CODE_RE

bp = Blueprint("advisory", __name__)


# ------------------------------------------------------------ customer herds ----
@bp.post("/customer-herds")
def create_herd():
    values = validate.parse([
        F("herd_name", "string", required=True, min_len=1),
        F("distributor_id", "id", required=True),
        F("country_code", "string", required=True, pattern=COUNTRY_CODE_RE),
        F("target_product_line", "enum", required=True, enum=config.PRODUCT_LINES),
        F("max_inbreeding_pct", "number", default=None, gt=0, max=25),
        F("base_sire_id", "id", default=None),
    ])
    auth.require_role(config.ROLE_BREEDING_ADVISOR, config.ROLE_DISTRIBUTOR)
    auth.require_distributor_scope(values["distributor_id"])
    distributor = resolve.need("distributors", values["distributor_id"])
    base_sire = resolve.optional("sires", values["base_sire_id"])
    ceiling = values["max_inbreeding_pct"]
    rec = store.new_record("customer_herds", {
        "herd_name": values["herd_name"],
        "distributor_id": distributor["id"],
        "base_sire_id": base_sire["id"] if base_sire is not None else None,
        "country_code": values["country_code"],
        "target_product_line": values["target_product_line"],
        "max_inbreeding_pct": (float(config.DEFAULT_MAX_INBREEDING_PCT)
                               if ceiling is None else ceiling),
    })
    return envelope.created(serializers.customer_herd(rec))


@bp.get("/customer-herds/<herd_id>")
def read_herd(herd_id):
    auth.require_role(config.ROLE_BREEDING_ADVISOR, config.ROLE_DISTRIBUTOR,
                      config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("customer_herds", herd_id)
    auth.require_distributor_scope(rec["distributor_id"])
    return envelope.ok(serializers.customer_herd(rec))


@bp.get("/customer-herds")
def list_herds():
    auth.require_role(config.ROLE_BREEDING_ADVISOR, config.ROLE_DISTRIBUTOR,
                      config.ROLE_PROGRAM_DIRECTOR)
    limit, offset = validate.pagination()
    distributor_id = validate.qstr("distributor_id")
    base_sire_id = validate.qstr("base_sire_id")
    items = []
    for rec in store.rows("customer_herds"):
        if distributor_id is not None and rec["distributor_id"] != distributor_id:
            continue
        if base_sire_id is not None and rec["base_sire_id"] != base_sire_id:
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.customer_herd)


# ----------------------------------------------------- mating recommendations ----
def _eligible_lots(sire_id, product_line, doses_requested):
    out = []
    for lot in store.rows("straw_lots"):
        if lot["sire_id"] != sire_id:
            continue
        if lot["distribution_status"] != "RELEASED":
            continue
        if lot["product_line"] != product_line:
            continue
        if int(lot["doses_available"]) < int(doses_requested):
            continue
        out.append(lot)
    return out


@bp.post("/customer-herds/<herd_id>/mating-recommendations")
def request_recommendation(herd_id):
    values = validate.parse([
        F("dam_ref", "string", required=True, min_len=1),
        F("dam_sire_id", "id", default=None),
        F("requested_product_line", "enum", required=True, enum=config.PRODUCT_LINES),
        F("doses_requested", "integer", required=True, min=1),
        F("excluded_sire_ids", "array", default=None, item_kind="id"),
    ])
    auth.require_role(config.ROLE_BREEDING_ADVISOR)
    herd = resolve.need("customer_herds", herd_id)
    dam_sire = resolve.optional("sires", values["dam_sire_id"])
    excluded = list(values["excluded_sire_ids"] or [])
    for sire_id in excluded:
        resolve.need("sires", sire_id)
    product_line = values["requested_product_line"]
    doses_requested = int(values["doses_requested"])
    ceiling = calc.D(herd["max_inbreeding_pct"])

    candidates = []
    for sire in store.rows("sires"):
        if sire["acquisition_status"] != "RESIDENT":
            continue
        if sire["collection_status"] != "ELIGIBLE":
            continue
        if sire["published_evaluation_effective_at"] is None:
            continue
        if herd["base_sire_id"] is not None and sire["id"] == herd["base_sire_id"]:
            continue
        if sire["id"] in excluded:
            continue
        inbreeding = calc.inbreeding_pct(
            sire["id"], dam_sire["id"] if dam_sire is not None else None)
        if inbreeding > ceiling:
            continue
        lots = _eligible_lots(sire["id"], product_line, doses_requested)
        if not lots:
            continue
        candidates.append((sire, inbreeding, lots))

    if not candidates:
        fail("ERR_NO_ELIGIBLE_SIRE",
             "No resident, eligible, proven bull with releasable %s stock qualifies for this herd."
             % product_line)

    candidates.sort(key=lambda entry: (
        -calc.D(entry[0]["published_composite_index"]),
        entry[1],
        entry[0]["created_at"],
        entry[0]["_seq"],
    ))
    sire, inbreeding, lots = candidates[0]
    lots.sort(key=lambda lot: (-int(lot["doses_available"]), lot["created_at"], lot["_seq"]))
    lot = lots[0]
    ejaculate = store.get("ejaculates", lot["ejaculate_id"])
    rate = calc.conception_rate(product_line, sire["published_composite_index"],
                               ejaculate["post_thaw_motility_pct"], inbreeding)
    rec = store.new_record("mating_recommendations", {
        "customer_herd_id": herd["id"],
        "dam_ref": values["dam_ref"],
        "dam_sire_id": dam_sire["id"] if dam_sire is not None else None,
        "requested_product_line": product_line,
        "doses_requested": doses_requested,
        "excluded_sire_ids": excluded,
        "recommended_sire_id": sire["id"],
        "straw_lot_id": lot["id"],
        "inbreeding_pct": calc.num(inbreeding),
        "expected_conception_rate": calc.num(rate),
        "candidate_pool_size": len(candidates),
        "status": "PROPOSED",
        "doses_committed": 0,
        "decided_at": None,
    })
    return envelope.created(serializers.mating_recommendation(rec))


@bp.get("/mating-recommendations/<recommendation_id>")
def read_recommendation(recommendation_id):
    auth.require_role(config.ROLE_BREEDING_ADVISOR, config.ROLE_DISTRIBUTOR,
                      config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("mating_recommendations", recommendation_id)
    herd = store.get("customer_herds", rec["customer_herd_id"])
    auth.require_distributor_scope(herd["distributor_id"])
    return envelope.ok(serializers.mating_recommendation(rec))


@bp.get("/mating-recommendations")
def list_recommendations():
    auth.require_role(config.ROLE_BREEDING_ADVISOR, config.ROLE_DISTRIBUTOR,
                      config.ROLE_PROGRAM_DIRECTOR)
    limit, offset = validate.pagination()
    filters = {
        "customer_herd_id": validate.qstr("customer_herd_id"),
        "recommended_sire_id": validate.qstr("recommended_sire_id"),
        "straw_lot_id": validate.qstr("straw_lot_id"),
        "dam_sire_id": validate.qstr("dam_sire_id"),
        "status": validate.qenum("status", config.RECOMMENDATION_STATUSES),
    }
    items = []
    for rec in store.rows("mating_recommendations"):
        if any(want is not None and rec[key] != want for key, want in filters.items()):
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.mating_recommendation)


@bp.post("/mating-recommendations/<recommendation_id>/decision")
def decide_recommendation(recommendation_id):
    values = validate.parse([
        F("decision", "enum", required=True, enum=config.RECOMMENDATION_DECISIONS),
    ])
    auth.require_role(config.ROLE_BREEDING_ADVISOR, config.ROLE_DISTRIBUTOR)
    rec = resolve.need("mating_recommendations", recommendation_id)
    herd = store.get("customer_herds", rec["customer_herd_id"])
    auth.require_distributor_scope(herd["distributor_id"])
    if rec["status"] != "PROPOSED":
        fail("ERR_RECOMMENDATION_STATE", "A decision requires status PROPOSED.")
    if values["decision"] == "ACCEPTED":
        lot = store.get("straw_lots", rec["straw_lot_id"])
        if lot["distribution_status"] != "RELEASED":
            fail("ERR_LOT_NOT_RELEASED", "The selected lot is no longer RELEASED.")
        if int(lot["doses_available"]) < int(rec["doses_requested"]):
            fail("ERR_INSUFFICIENT_DOSES",
                 "The selected lot no longer holds that many available doses.")
        lot["doses_available"] = int(lot["doses_available"]) - int(rec["doses_requested"])
        lot["doses_reserved"] = int(lot["doses_reserved"]) + int(rec["doses_requested"])
        store.touch(lot)
        rec["doses_committed"] = int(rec["doses_requested"])
    rec["status"] = values["decision"]
    rec["decided_at"] = store.clock_iso()
    store.touch(rec)
    return envelope.ok(serializers.mating_recommendation(rec))
