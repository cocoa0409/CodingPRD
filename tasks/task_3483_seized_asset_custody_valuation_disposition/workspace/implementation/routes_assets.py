"""Asset endpoints (PRD §3.2 intake, §3.3 disposition decision, §3.8 returns).

The asset carries two independent state dimensions (custody_state x
legal_state) plus the retention_decision field (PRD §2.8).
"""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import errors
import store
from constants import (
    ASSET_TYPES,
    CONDITION_GRADES,
    DECISIONS,
    DISPUTE_WINDOW_DAYS,
    RETENTION_VALUE_FLOOR_CENTS,
)
from middleware import require_roles, require_business_role
from response import ok_object
from serialize import ser_asset
from util import get_body, req_str, req_enum, req_int, req_dt

bp = Blueprint("assets", __name__)


def load_asset(asset_id):
    asset = store.ASSETS.get(asset_id)
    if asset is None:
        raise errors.not_found("Asset not found: %s" % asset_id)
    return asset


def cancel_scheduled_transfers(asset):
    """Cascade: every SCHEDULED CustodyTransfer of this asset -> CANCELLED."""
    for transfer in store.transfers_of_asset(asset["id"]):
        if transfer["status"] == "SCHEDULED":
            transfer["status"] = "CANCELLED"
            store.touch(transfer)


@bp.route("/custody/assets", methods=["POST"])
def create_asset():
    require_roles("AssetCustodian")
    # Tier 3: request shape.
    data = get_body()
    seizure_case_id = req_str(data, "seizure_case_id")
    asset_type = req_enum(data, "asset_type", ASSET_TYPES)
    description = req_str(data, "description")
    seized_on = req_dt(data, "seized_on")
    seizure_condition_grade = req_enum(
        data, "seizure_condition_grade", CONDITION_GRADES
    )
    # Tier 4: owning case must exist.
    case = store.CASES.get(seizure_case_id)
    if case is None:
        raise errors.not_found("SeizureCase not found: %s" % seizure_case_id)
    # Tier 6: intake blocked only for DISMISSED cases (substitute assets may
    # be seized into OPEN, FORFEITURE_PENDING, or FORFEITED cases).
    if case["status"] == "DISMISSED":
        raise errors.invalid_state(
            "Cannot intake an asset into a DISMISSED case"
        )
    asset = store.new_entity(
        {
            "seizure_case_id": case["id"],
            "asset_type": asset_type,
            "description": description,
            "seized_on": seized_on,
            "seizure_condition_grade": seizure_condition_grade,
            "current_condition_grade": seizure_condition_grade,
            "appraised_value_cents": None,
            "appraised_at": None,
            "accumulated_net_holding_cost_cents": 0,
            "custody_state": "INTAKE",
            "legal_state": "SEIZED",
            "retention_decision": "PENDING",
            "returned_at": None,
            "computed_depreciation_cents": None,
            "dispute_claimed_depreciation_cents": None,
            "final_depreciation_cents": None,
        }
    )
    store.ASSETS[asset["id"]] = asset
    return ok_object(ser_asset(asset), status=201)


@bp.route("/custody/assets/<asset_id>", methods=["GET"])
def get_asset(asset_id):
    require_business_role()
    asset = load_asset(asset_id)
    return ok_object(ser_asset(asset))


@bp.route("/custody/assets/<asset_id>/decide-retention", methods=["POST"])
def decide_retention(asset_id):
    require_roles("AssetManager")
    data = get_body()
    decision = req_enum(data, "decision", DECISIONS)
    asset = load_asset(asset_id)
    # Tier 6: legal_state must be VALUED.
    if asset["legal_state"] != "VALUED":
        raise errors.invalid_state(
            "decide-retention requires legal_state == VALUED (legal_state=%s)"
            % asset["legal_state"]
        )
    if decision == "RETAIN":
        # Tier 9, floor first: final net retention value >= 500000 cents.
        _, final_value = calc.retention_values(
            asset, store.valuations_of_asset(asset["id"])
        )
        if final_value is None or final_value < RETENTION_VALUE_FLOOR_CENTS:
            raise errors.ApiError(
                errors.ERR_RETENTION_VALUE_TOO_LOW,
                422,
                "final_net_retention_value_cents is below the retention floor",
            )
        # Tier 9, ratio second: interlocutory eligibility must be FALSE.
        if calc.interlocutory_eligible(asset):
            raise errors.ApiError(
                errors.ERR_RETENTION_BLOCKED_HOLDING_COST,
                422,
                "Holding costs have reached the interlocutory threshold; "
                "retention is blocked",
            )
        asset["retention_decision"] = "RETAIN"
        asset["legal_state"] = "RETAINED"
    else:  # SELL
        asset["retention_decision"] = "SELL"
        asset["legal_state"] = "DISPOSITION_REVIEW"
    store.touch(asset)
    return ok_object(ser_asset(asset))


@bp.route("/custody/assets/<asset_id>/authorize-sale", methods=["POST"])
def authorize_sale(asset_id):
    require_roles("AssetManager")
    get_body()
    asset = load_asset(asset_id)
    case = store.CASES.get(asset["seizure_case_id"])
    # Tier 6 (scaffold precondition order): the case must be FORFEITED...
    if case is None or case["status"] != "FORFEITED":
        raise errors.case_not_forfeited(
            "authorize-sale requires the owning case to be FORFEITED"
        )
    # ...and the asset must stand at DISPOSITION_REVIEW with decision SELL.
    if asset["legal_state"] != "DISPOSITION_REVIEW" or (
        asset["retention_decision"] != "SELL"
    ):
        raise errors.invalid_state(
            "authorize-sale requires legal_state == DISPOSITION_REVIEW with "
            "retention_decision == SELL"
        )
    asset["legal_state"] = "SALE_AUTHORIZED"
    asset["custody_state"] = "RELEASED_FOR_SALE"
    cancel_scheduled_transfers(asset)
    store.touch(asset)
    return ok_object(ser_asset(asset))


@bp.route("/custody/assets/<asset_id>/initiate-return", methods=["POST"])
def initiate_return(asset_id):
    require_roles("AssetManager")
    get_body()
    asset = load_asset(asset_id)
    # Tier 6: legal RETURN_PENDING, custody anything except TRANSFERRED_OUT.
    if asset["legal_state"] != "RETURN_PENDING":
        raise errors.invalid_state(
            "initiate-return requires legal_state == RETURN_PENDING "
            "(legal_state=%s)" % asset["legal_state"]
        )
    if asset["custody_state"] == "TRANSFERRED_OUT":
        raise errors.invalid_state(
            "initiate-return is invalid once custody_state == TRANSFERRED_OUT"
        )
    asset["custody_state"] = "RELEASED_FOR_RETURN"
    store.touch(asset)
    return ok_object(ser_asset(asset))


@bp.route("/custody/assets/<asset_id>/complete-return", methods=["POST"])
def complete_return(asset_id):
    require_roles("AssetManager")
    data = get_body()
    return_condition_grade = req_enum(data, "return_condition_grade", CONDITION_GRADES)
    asset = load_asset(asset_id)
    # Tier 6: legal RETURN_PENDING and physical handover completed first.
    if asset["legal_state"] != "RETURN_PENDING":
        raise errors.invalid_state(
            "complete-return requires legal_state == RETURN_PENDING "
            "(legal_state=%s)" % asset["legal_state"]
        )
    if asset["custody_state"] != "TRANSFERRED_OUT":
        raise errors.invalid_state(
            "complete-return requires custody_state == TRANSFERRED_OUT "
            "(custody_state=%s)" % asset["custody_state"]
        )
    now = clock.now()
    asset["returned_at"] = now
    asset["computed_depreciation_cents"] = calc.depreciation_cents(
        asset, return_condition_grade, now
    )
    asset["legal_state"] = "RETURNED"
    store.touch(asset)
    return ok_object(ser_asset(asset))


@bp.route("/custody/assets/<asset_id>/dispute-return", methods=["POST"])
def dispute_return(asset_id):
    require_roles("Claimant")
    data = get_body()
    claimed = req_int(data, "claimed_depreciation_cents", min_value=0)
    asset = load_asset(asset_id)
    # Tier 6: legal RETURNED.
    if asset["legal_state"] != "RETURNED":
        raise errors.invalid_state(
            "dispute-return requires legal_state == RETURNED (legal_state=%s)"
            % asset["legal_state"]
        )
    # Tier 10: within returned_at + DISPUTE_WINDOW_DAYS (boundary inclusive).
    deadline = asset["returned_at"] + timedelta(days=DISPUTE_WINDOW_DAYS)
    if clock.now() > deadline:
        raise errors.ApiError(
            errors.ERR_DISPUTE_WINDOW_EXPIRED,
            409,
            "The 30-day dispute window after returned_at has expired",
        )
    asset["dispute_claimed_depreciation_cents"] = claimed
    asset["legal_state"] = "DISPUTED"
    store.touch(asset)
    return ok_object(ser_asset(asset))


@bp.route("/custody/assets/<asset_id>/resolve-return-dispute", methods=["POST"])
def resolve_return_dispute(asset_id):
    require_roles("CourtOfficial")
    data = get_body()
    final_depreciation = req_int(data, "final_depreciation_cents", min_value=0)
    asset = load_asset(asset_id)
    # Tier 6: legal DISPUTED.
    if asset["legal_state"] != "DISPUTED":
        raise errors.invalid_state(
            "resolve-return-dispute requires legal_state == DISPUTED "
            "(legal_state=%s)" % asset["legal_state"]
        )
    # Tier 9: final_depreciation_cents <= appraised_value_cents; a null
    # appraised value admits only exactly 0.
    appraised = asset["appraised_value_cents"]
    limit = appraised if appraised is not None else 0
    if final_depreciation > limit:
        raise errors.ApiError(
            errors.ERR_DEPRECIATION_EXCEEDS_VALUE,
            422,
            "final_depreciation_cents exceeds the asset's appraised value",
        )
    asset["final_depreciation_cents"] = final_depreciation
    asset["legal_state"] = "RESOLVED"
    store.touch(asset)
    return ok_object(ser_asset(asset))
