"""Over-the-air rekey campaigns."""
from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import KEY_CUSTODIAN

bp = Blueprint("campaigns", __name__, url_prefix=common.PREFIX)


@bp.post("/otar-campaigns")
def create_campaign():
    validate.authenticate([KEY_CUSTODIAN])
    body = validate.get_body()
    keyset = validate.req_fk(body, "keyset_id", "keysets")
    agency = validate.req_fk(body, "agency_id", "agencies")
    start = validate.req_dt(body, "window_start")
    end = validate.req_dt(body, "window_end")
    validate.window_order(start, end)
    if keyset["status"] != "ACTIVE":
        raise ApiError("ERR_KEYSET_NOT_ACTIVE")
    for other in db.store.campaigns.values():
        if other["status"] != "SCHEDULED":
            continue
        if other["keyset_id"] != keyset["id"] or other["agency_id"] != agency["id"]:
            continue
        if start < other["window_end"] and other["window_start"] < end:
            raise ApiError("ERR_OTAR_WINDOW_OVERLAP")
    if start < keyset["crypto_period_start"] or end > keyset["crypto_period_end"]:
        raise ApiError("ERR_OTAR_WINDOW_OUTSIDE_CRYPTO_PERIOD")
    row = db.base_row({
        "keyset_id": keyset["id"],
        "agency_id": agency["id"],
        "window_start": start,
        "window_end": end,
        "status": "SCHEDULED",
        "target_unit_count": 0,
        "rekeyed_unit_count": 0,
        "failed_unit_count": 0,
        "executed_at": None,
    })
    db.store.campaigns[row["id"]] = row
    return response.ok(serialize.campaign(row), 201)


@bp.get("/otar-campaigns")
def list_campaigns():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("keyset_id", validate.filter_str("keyset_id")),
        ("agency_id", validate.filter_str("agency_id")),
        ("status", validate.filter_enum("status", enums.CAMPAIGN_STATUSES)),
    )
    return common.list_endpoint("campaigns", serialize.campaign, filters)


@bp.get("/otar-campaigns/<campaign_id>")
def read_campaign(campaign_id):
    validate.authenticate(common.ANY_ROLE)
    campaign = validate.lookup("campaigns", campaign_id)
    return response.ok(serialize.campaign(campaign))


@bp.post("/otar-campaigns/<campaign_id>/execute")
def execute_campaign(campaign_id):
    validate.authenticate([KEY_CUSTODIAN])
    campaign = validate.lookup("campaigns", campaign_id)
    if campaign["status"] in ("COMPLETED", "ABORTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if campaign["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    keyset = db.store.keysets.get(campaign["keyset_id"])
    if keyset is None or keyset["status"] != "ACTIVE":
        raise ApiError("ERR_KEYSET_NOT_ACTIVE")
    now = db.now()
    if now < campaign["window_start"] or now >= campaign["window_end"]:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The logical clock is outside the campaign window.",
        )
    targets = db.sort_rows([
        u for u in compute.agency_units(campaign["agency_id"])
        if u["provision_status"] in compute.BILLABLE_STATUSES and u["key_status"] != "ZEROIZED"
    ])
    rekeyed = 0
    failed = 0
    for unit in targets:
        if unit["provision_status"] == "ASSIGNED":
            unit["key_status"] = "KEYED"
            unit["active_keyset_id"] = campaign["keyset_id"]
            unit["last_otar_at"] = now
            db.touch(unit)
            rekeyed += 1
        else:
            failed += 1
    campaign["target_unit_count"] = len(targets)
    campaign["rekeyed_unit_count"] = rekeyed
    campaign["failed_unit_count"] = failed
    campaign["executed_at"] = now
    campaign["status"] = "COMPLETED"
    db.touch(campaign)
    compute.recompute_keyset_loaded_count(keyset)
    return response.ok(serialize.campaign(campaign))
