"""PackConfiguration resource: propose, publish, supersede."""

from flask import jsonify, request

import db
import requtil
import response
from core import app
from common import serialize
from errors import (
    ApiError,
    ERR_CONFIG_LADDER_VIOLATION,
    ERR_CONFIG_SERIAL_OUT_OF_RANGE,
    ERR_INVALID_STATE,
    ERR_PACK_CONFIG_TOTAL_MISMATCH,
    ERR_PACK_CONFIGURATION_NOT_FOUND,
    ERR_PACK_ODDS_NOT_PUBLISHABLE,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SET_NOT_APPROVED,
)
from middleware import authenticate, require_role

READ_ROLES = ["ProductManager", "ProductionPlanner", "PlatformAdmin"]
CONFIG_SERIAL_MIN = 1
CONFIG_SERIAL_MAX = 30


def _get(config_id):
    rec = db.STORE.get("pack_configurations", config_id)
    if rec is None:
        raise ApiError(
            ERR_PACK_CONFIGURATION_NOT_FOUND,
            "No PackConfiguration exists with id %s" % config_id,
        )
    return rec


def _serialize(rec):
    return serialize("pack_configurations", rec)


@app.route("/api/pack-configurations", methods=["POST"])
def create_pack_config():
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    data = requtil.body()
    card_set_id = requtil.required_str(data, "card_set_id")
    config_serial = requtil.required_int(data, "config_serial")
    base_packs = requtil.required_int(data, "base_packs")
    insert_packs = requtil.required_int(data, "insert_packs")
    premium_packs = requtil.required_int(data, "premium_packs")

    store = db.STORE
    if not store.exists("card_sets", card_set_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "card_set_id %s does not resolve" % card_set_id
        )

    now = store.now()
    rec = db.record("pack_configurations", {
        "card_set_id": card_set_id,
        "config_serial": config_serial,
        "odd_value": 0,
        "base_packs": base_packs,
        "insert_packs": insert_packs,
        "premium_packs": premium_packs,
        "total_cards": base_packs + insert_packs + premium_packs,
        "status": "PROPOSED",
    }, now)
    store.insert("pack_configurations", rec)
    return jsonify(response.ok_object(_serialize(rec))), 201


@app.route("/api/pack-configurations", methods=["GET"])
def list_pack_configs():
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)

    store = db.STORE
    items = list(store.all("pack_configurations"))
    card_set_id = requtil.filter_value("card_set_id")
    status = requtil.filter_value("status")
    if card_set_id is not None:
        items = [p for p in items if p["card_set_id"] == card_set_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(response.paginate([_serialize(p) for p in items], request.args)), 200


@app.route("/api/pack-configurations/<config_id>", methods=["GET"])
def get_pack_config(config_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    return jsonify(response.ok_object(_serialize(_get(config_id)))), 200


@app.route("/api/pack-configurations/<config_id>/publish", methods=["POST"])
def publish_pack_config(config_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    store = db.STORE
    now = store.now()
    rec = _get(config_id)

    card_set = store.get("card_sets", rec["card_set_id"])
    if card_set is None:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "The parent card set does not resolve"
        )
    if card_set["status"] not in ("APPROVED", "IN_PRODUCTION"):
        raise ApiError(ERR_SET_NOT_APPROVED, "The parent card set is not APPROVED")
    if rec["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "Pack configuration is not PROPOSED")

    # Ordered ladder checks (PRD 3.2 / validation priorities 15-16).
    if rec["config_serial"] < CONFIG_SERIAL_MIN or rec["config_serial"] > CONFIG_SERIAL_MAX:
        raise ApiError(
            ERR_CONFIG_SERIAL_OUT_OF_RANGE, "config_serial must lie within 1..30"
        )
    published_count = sum(
        1
        for p in store.all("pack_configurations")
        if p["card_set_id"] == rec["card_set_id"] and p["status"] == "PUBLISHED"
    )
    if rec["config_serial"] != published_count + 1:
        raise ApiError(
            ERR_CONFIG_LADDER_VIOLATION,
            "config_serial must equal current_published_count + 1",
        )

    line = store.get("product_lines", card_set["product_line_id"])
    if line is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "The parent product line does not resolve")
    if rec["total_cards"] != line["cards_per_pack"]:
        raise ApiError(
            ERR_PACK_CONFIG_TOTAL_MISMATCH,
            "base_packs + insert_packs + premium_packs must equal cards_per_pack",
        )
    if not card_set["announced"] and rec["insert_packs"] != 0:
        raise ApiError(
            ERR_PACK_ODDS_NOT_PUBLISHABLE,
            "Insert odds cannot be published for an unannounced set",
        )

    rec["status"] = "PUBLISHED"
    rec["odd_value"] = card_set["print_run_quantity"]
    db.bump(rec, now)
    db.bump(card_set, now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/pack-configurations/<config_id>/supersede", methods=["POST"])
def supersede_pack_config(config_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    store = db.STORE
    now = store.now()
    rec = _get(config_id)
    if rec["status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE, "Pack configuration is not PUBLISHED")

    rec["status"] = "SUPERSEDED"
    db.bump(rec, now)

    # Every OTHER PUBLISHED configuration for the same card set returns to
    # PROPOSED.
    for other in store.all("pack_configurations"):
        if other["id"] == rec["id"]:
            continue
        if other["card_set_id"] == rec["card_set_id"] and other["status"] == "PUBLISHED":
            other["status"] = "PROPOSED"
            db.touch(other, now)

    card_set = store.get("card_sets", rec["card_set_id"])
    if card_set is not None:
        db.bump(card_set, now)
    return jsonify(response.ok_object(_serialize(rec))), 200