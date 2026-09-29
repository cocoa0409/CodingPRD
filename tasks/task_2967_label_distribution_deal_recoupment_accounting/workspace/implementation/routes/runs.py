"""Physical manufacturing, shipping, returns and reserves (PRD section 3.7)."""

from decimal import Decimal

from flask import Blueprint, request

import db
import response
import serializers
import validation as v
from errors import ApiError
from middleware import authenticate, pagination, paginate, parse_body
from routes.common import (BUSINESS_AFFAIRS, DISTRIBUTION_PARTNER, LABEL_ADMIN,
                           ROYALTY_ANALYST, check_run_version, find_distributor,
                           find_release, find_run, require_owner)
from services import calculations, lookups

bp = Blueprint("runs", __name__)

PHYSICAL_FORMATS = ("VINYL", "CD", "CASSETTE")
READERS = [LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS, DISTRIBUTION_PARTNER]


@bp.route("/physical-runs", methods=["POST"])
def create_run():
    authenticate([LABEL_ADMIN])
    body = parse_body()
    release_id = v.identifier(body, "release_id", required=True)
    distributor_id = v.identifier(body, "distributor_id", required=True)
    units_planned = v.integer(body, "units_planned", required=True, minimum=1)
    unit_cost = v.integer(body, "unit_manufacturing_cost_cents", required=True,
                          minimum=1)
    window_start = v.date_field(body, "window_start", required=True)
    window_end = v.date_field(body, "window_end", required=True)
    if window_end < window_start:
        v.bad("window_end", "may not fall before window_start.")
    returns_reserve_pct = v.percentage(
        body, "returns_reserve_pct", required=False,
        minimum=Decimal("0.0000"), maximum=Decimal("0.5000"))

    release = find_release(release_id)
    distributor = find_distributor(distributor_id)

    if not any(f in PHYSICAL_FORMATS for f in (release["formats"] or [])):
        raise ApiError("ERR_INVALID_RELEASE_STATE",
                       "The release carries no physical format.")
    if release["status"] not in ("PLANNED", "RELEASED"):
        raise ApiError("ERR_INVALID_RELEASE_STATE",
                       "The release is no longer physically distributable.")

    if returns_reserve_pct is None:
        returns_reserve_pct = distributor["default_returns_reserve_pct"]

    record = db.base_record()
    record.update({
        "release_id": release_id,
        "distributor_id": distributor_id,
        "units_planned": units_planned,
        "unit_manufacturing_cost_cents": unit_cost,
        "window_start": db.date_str(window_start),
        "window_end": db.date_str(window_end),
        "returns_reserve_pct": returns_reserve_pct,
        "status": "PLANNED",
        "reserve_status": "HELD",
        "units_manufactured": 0,
        "units_shipped": 0,
        "units_returned": 0,
        "wholesale_unit_price_cents": 0,
        "returns_rate": Decimal("0.0000"),
        "effective_reserve_pct": None,
        "reserve_initial_cents": 0,
        "reserve_held_cents": 0,
        "reserve_liquidated_cents": 0,
        "manufacturing_cost_cents": 0,
        "physical_net_receipts_cents": 0,
    })
    db.store.runs[record["id"]] = record
    return response.created(serializers.run(record))


@bp.route("/physical-runs/<record_id>", methods=["GET"])
def get_run(record_id):
    authenticate(READERS)
    return response.ok(serializers.run(find_run(record_id)))


@bp.route("/physical-runs", methods=["GET"])
def list_runs():
    authenticate(READERS)
    limit, offset = pagination()
    records = db.ordered(list(db.store.runs.values()))
    for key in ("release_id", "distributor_id", "status", "reserve_status"):
        wanted = request.args.get(key)
        if wanted is not None:
            records = [r for r in records if r[key] == wanted]
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.run(r) for r in page], limit, offset, total)


def _adjust_net_receipts(run, delta):
    if delta == 0:
        return []
    touched = []
    release = db.store.releases.get(run["release_id"])
    if release is not None:
        release["net_receipts_to_date_cents"] = \
            (release.get("net_receipts_to_date_cents") or 0) + delta
        db.touch(release)
        touched.append(release)
        deal = lookups.deal_of_release(release)
        if deal is not None:
            deal["net_receipts_to_date_cents"] = \
                (deal.get("net_receipts_to_date_cents") or 0) + delta
            db.touch(deal)
            touched.append(deal)
    return touched


@bp.route("/physical-runs/<record_id>/manufacture", methods=["POST"])
def manufacture_run(record_id):
    authenticate([LABEL_ADMIN])
    run = find_run(record_id)
    body = parse_body()
    units_manufactured = v.integer(body, "units_manufactured", required=True,
                                   minimum=1)
    if run["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_RUN_STATE")
    release = db.store.releases.get(run["release_id"])
    if release is None or release["status"] not in ("PLANNED", "RELEASED"):
        raise ApiError("ERR_INVALID_RELEASE_STATE")
    run["status"] = "MANUFACTURED"
    run["units_manufactured"] = units_manufactured
    run["manufacturing_cost_cents"] = \
        units_manufactured * run["unit_manufacturing_cost_cents"]
    db.touch(run)
    return response.ok(serializers.run(run))


@bp.route("/physical-runs/<record_id>/ship", methods=["POST"])
def ship_run(record_id):
    caller = authenticate([DISTRIBUTION_PARTNER])
    run = find_run(record_id)
    require_owner(caller, run["distributor_id"])
    body = parse_body()
    units_shipped = v.integer(body, "units_shipped", required=True, minimum=0)
    price = v.integer(body, "wholesale_unit_price_cents", required=True, minimum=0)
    if run["status"] != "MANUFACTURED":
        raise ApiError("ERR_INVALID_RUN_STATE")
    if units_shipped > (run["units_manufactured"] or 0):
        v.bad("units_shipped", "may not exceed units_manufactured.")
    retained = (run["units_manufactured"] or 0) - units_shipped
    if retained < calculations.minimum_retained_inventory(units_shipped):
        raise ApiError("ERR_INVENTORY_OBLIGATION_BREACH")
    run["status"] = "SHIPPED"
    run["units_shipped"] = units_shipped
    run["wholesale_unit_price_cents"] = price
    run["units_returned"] = 0
    before = run.get("physical_net_receipts_cents") or 0
    calculations.recompute_reserve(run)
    db.touch(run)
    _adjust_net_receipts(run, run["physical_net_receipts_cents"] - before)
    return response.ok(serializers.run(run))


@bp.route("/physical-runs/<record_id>/record-returns", methods=["POST"])
def record_returns(record_id):
    caller = authenticate([DISTRIBUTION_PARTNER])
    run = find_run(record_id)
    require_owner(caller, run["distributor_id"])
    body = parse_body()
    returned_units = v.integer(body, "returned_units", required=True, minimum=0)
    if run["status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_RUN_STATE")
    if run["reserve_status"] != "HELD":
        raise ApiError("ERR_INVALID_RUN_STATE",
                       "The reserve has already been partly released.")
    cumulative = (run.get("units_returned") or 0) + returned_units
    if cumulative > (run.get("units_shipped") or 0):
        raise ApiError("ERR_RETURNS_EXCEED_SHIPPED")
    before = run.get("physical_net_receipts_cents") or 0
    run["units_returned"] = cumulative
    calculations.recompute_reserve(run)
    db.touch(run)
    _adjust_net_receipts(run, run["physical_net_receipts_cents"] - before)
    return response.ok(serializers.run(run))


@bp.route("/physical-runs/<record_id>/liquidate-reserve", methods=["POST"])
def liquidate_reserve(record_id):
    authenticate([ROYALTY_ANALYST])
    run = find_run(record_id)
    body = parse_body()
    expected = v.integer(body, "expected_run_version", required=True)
    liquidation_pct = v.percentage(body, "liquidation_pct", required=True,
                                  maximum=Decimal("1.0000"))
    if liquidation_pct <= Decimal("0.0000"):
        v.bad("liquidation_pct", "must be strictly above 0.0000.")
    check_run_version(run, expected)
    if run["status"] not in ("SHIPPED", "RECONCILED"):
        raise ApiError("ERR_INVALID_RUN_STATE")
    amount = db.round_half_up(
        Decimal(run.get("reserve_initial_cents") or 0) * liquidation_pct)
    if amount > (run.get("reserve_held_cents") or 0):
        raise ApiError("ERR_LIQUIDATION_EXCEEDS_RESERVE")
    run["reserve_held_cents"] = (run.get("reserve_held_cents") or 0) - amount
    run["reserve_liquidated_cents"] = \
        (run.get("reserve_liquidated_cents") or 0) + amount
    if run["reserve_liquidated_cents"] >= (run.get("reserve_initial_cents") or 0):
        run["reserve_status"] = "LIQUIDATED"
        run["reserve_held_cents"] = 0
        run["reserve_liquidated_cents"] = run.get("reserve_initial_cents") or 0
        if run["status"] == "SHIPPED":
            run["status"] = "RECONCILED"
    else:
        run["reserve_status"] = "PARTIALLY_LIQUIDATED"
    db.touch(run)
    return response.ok(serializers.run(run))


def _finalized_statement_reads_reserve(run):
    for statement in db.store.statements.values():
        if statement["status"] != "FINALIZED":
            continue
        if statement["basis_variant"] != "FINAL":
            continue
        agreement = db.store.agreements.get(statement["artist_agreement_id"])
        if agreement is None:
            continue
        if agreement["release_id"] == run["release_id"]:
            return True
    return False


@bp.route("/physical-runs/<record_id>/void-liquidation", methods=["POST"])
def void_liquidation(record_id):
    authenticate([ROYALTY_ANALYST])
    run = find_run(record_id)
    body = parse_body()
    expected = v.integer(body, "expected_run_version", required=True)
    check_run_version(run, expected)
    if run["reserve_status"] not in ("PARTIALLY_LIQUIDATED", "LIQUIDATED"):
        raise ApiError("ERR_INVALID_RUN_STATE")
    if _finalized_statement_reads_reserve(run):
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    was_liquidated = run["reserve_status"] == "LIQUIDATED"
    run["reserve_held_cents"] = (run.get("reserve_held_cents") or 0) + \
        (run.get("reserve_liquidated_cents") or 0)
    run["reserve_liquidated_cents"] = 0
    run["reserve_status"] = "HELD"
    if was_liquidated and run["status"] == "RECONCILED":
        run["status"] = "SHIPPED"
    db.touch(run)
    return response.ok(serializers.run(run))
