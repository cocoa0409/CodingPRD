"""Valuation endpoints (PRD §3.3): OCC-guarded submission and adjudication."""

from flask import Blueprint

import calc
import clock
import errors
import store
from constants import VALUATION_METHODS, VALUATION_OUTCOMES, CONDITION_GRADES
from middleware import require_roles, require_business_role
from response import ok_object, ok_list
from routes_assets import load_asset
from serialize import ser_valuation
from util import (
    get_body,
    req_str,
    req_enum,
    req_int,
    opt_int,
    absent_or_none,
    parse_pagination,
    sort_and_page,
)

bp = Blueprint("valuations", __name__)

# Legal states from which a valuation may be submitted.
_SUBMITTABLE_STATES = ("SEIZED", "VALUATION_PENDING", "VALUED", "DISPOSITION_REVIEW")


@bp.route("/custody/valuations", methods=["POST"])
def create_valuation():
    user_id, _ = require_roles("Appraiser")
    # Tier 3: request shape, including method-specific consistency.
    data = get_body()
    asset_id = req_str(data, "asset_id")
    method = req_enum(data, "method", VALUATION_METHODS)
    expected_asset_version = req_int(data, "expected_asset_version")
    raw_value_cents = None
    assessed_condition_grade = None
    annual_net_revenues = None
    if method == "INCOME_APPROACH":
        # Requires exactly 3 integers (oldest fiscal year first); raw forbidden.
        if not absent_or_none(data, "raw_value_cents"):
            raise errors.invalid_request(
                "INCOME_APPROACH forbids raw_value_cents"
            )
        if "annual_net_revenues_cents" not in data or data["annual_net_revenues_cents"] is None:
            raise errors.invalid_request(
                "INCOME_APPROACH requires annual_net_revenues_cents"
            )
        revenues = data["annual_net_revenues_cents"]
        if (
            not isinstance(revenues, list)
            or len(revenues) != 3
            or any(isinstance(r, bool) or not isinstance(r, int) for r in revenues)
        ):
            raise errors.invalid_request(
                "annual_net_revenues_cents must be an array of exactly 3 integers"
            )
        annual_net_revenues = revenues
    else:
        # Requires raw_value_cents + assessed_condition_grade; revenues forbidden.
        raw_value_cents = req_int(data, "raw_value_cents", min_value=0)
        assessed_condition_grade = req_enum(
            data, "assessed_condition_grade", CONDITION_GRADES
        )
        if not absent_or_none(data, "annual_net_revenues_cents"):
            raise errors.invalid_request(
                "Method %s forbids annual_net_revenues_cents" % method
            )
    # Tier 4: asset must exist.
    asset = load_asset(asset_id)
    # Tier 5: optimistic concurrency on the asset.
    if expected_asset_version != asset["version"]:
        raise errors.stale_version(
            "expected_asset_version %s does not match current asset version %s"
            % (expected_asset_version, asset["version"])
        )
    # Tier 6: legal-state gate.
    if asset["legal_state"] not in _SUBMITTABLE_STATES:
        raise errors.invalid_state(
            "Valuations may not be submitted while legal_state == %s"
            % asset["legal_state"]
        )
    adjusted = calc.adjusted_value(
        method, raw_value_cents, assessed_condition_grade, annual_net_revenues
    )
    valuation = store.new_entity(
        {
            "asset_id": asset["id"],
            "method": method,
            "raw_value_cents": raw_value_cents,
            "assessed_condition_grade": assessed_condition_grade,
            "annual_net_revenues_cents": annual_net_revenues,
            "adjusted_value_cents": adjusted,
            "status": "SUBMITTED",
            "submitted_by_user_id": user_id,
        }
    )
    store.VALUATIONS[valuation["id"]] = valuation
    # The very first valuation advances the legal track SEIZED -> VALUATION_PENDING.
    if asset["legal_state"] == "SEIZED":
        asset["legal_state"] = "VALUATION_PENDING"
        store.touch(asset)
    return ok_object(ser_valuation(valuation), status=201)


@bp.route("/custody/valuations/<valuation_id>/adjudicate", methods=["POST"])
def adjudicate_valuation(valuation_id):
    require_roles("CourtOfficial")
    data = get_body()
    outcome = req_enum(data, "outcome", VALUATION_OUTCOMES)
    valuation = store.VALUATIONS.get(valuation_id)
    if valuation is None:
        raise errors.not_found("Valuation not found: %s" % valuation_id)
    # Tier 6: only a SUBMITTED valuation can be adjudicated.
    if valuation["status"] != "SUBMITTED":
        raise errors.invalid_state(
            "Only a SUBMITTED valuation can be adjudicated (status=%s)"
            % valuation["status"]
        )
    if outcome == "REJECT":
        valuation["status"] = "REJECTED"
        store.touch(valuation)
        return ok_object(ser_valuation(valuation))
    # ACCEPT: stamp the asset's appraised figures and advance/revert the
    # legal track per the state machine.
    valuation["status"] = "ACCEPTED"
    store.touch(valuation)
    asset = store.ASSETS.get(valuation["asset_id"])
    if asset is not None:
        asset["appraised_value_cents"] = valuation["adjusted_value_cents"]
        asset["appraised_at"] = clock.now()
        if asset["legal_state"] == "VALUATION_PENDING":
            asset["legal_state"] = "VALUED"
        elif asset["legal_state"] == "DISPOSITION_REVIEW":
            # Revaluation invalidates the pending sell decision.
            asset["legal_state"] = "VALUED"
            asset["retention_decision"] = "PENDING"
        # legal VALUED revaluation: stays VALUED with refreshed figures.
        store.touch(asset)
    return ok_object(ser_valuation(valuation))


@bp.route("/custody/assets/<asset_id>/valuations", methods=["GET"])
def list_asset_valuations(asset_id):
    require_business_role()
    asset = load_asset(asset_id)
    limit, offset = parse_pagination()
    page, total = sort_and_page(store.valuations_of_asset(asset["id"]), limit, offset)
    return ok_list([ser_valuation(v) for v in page], total, limit, offset)
