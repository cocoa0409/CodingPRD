"""Plan development: commitments, funding assurances, submission, decision."""
from flask import Blueprint

import auth
import calc
import envelope
import resolve
import serialize
import shape
import store
import util
from errors import ApiError

bp = Blueprint("plans", __name__)

PROPONENT = ("Proponent",)
AGENCY = ("WildlifeAgency",)


@bp.route("/habitat-conservation-plans/<hid>/mitigation-commitments",
          methods=["POST"])
def add_commitment(hid):
    caller = auth.authenticate(PROPONENT)
    plan = resolve.plan(hid)
    auth.require_owner(caller, auth.owner_of_plan(plan))

    # Rung 6.
    bank_id = shape.peek_str("conservation_bank_id")
    bank = resolve.bank(bank_id) if bank_id is not None else None

    body = shape.Body()
    mechanism = body.enum("mechanism", calc.MECHANISMS)
    units = body.quantity("units", positive=True)
    expected_version = body.integer("expected_hcp_version")
    body.ident("conservation_bank_id", required=False)
    body.close()

    # Rung 8 -- nothing at all is written when the guard fails.
    if expected_version != plan["version"]:
        raise ApiError("ERR_STALE_HCP_VERSION")

    # Rung 9.
    if plan["plan_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Rung 24 -- the pairing rule and bank eligibility, before availability.
    action = store.get("actions", plan["project_action_id"])
    if mechanism == "CONSERVATION_BANK_CREDIT":
        if bank is None:
            raise ApiError("ERR_BANK_NOT_ELIGIBLE")
        primary = calc.primary_species(action) if action is not None else None
        if primary is None or bank["covered_species_id"] != primary["id"]:
            raise ApiError("ERR_BANK_NOT_ELIGIBLE")
        if action["county_code"] not in bank["service_area_county_codes"]:
            raise ApiError("ERR_BANK_NOT_ELIGIBLE")
        # Rung 25.
        if util.to_dec(bank["credits_available"]) < units:
            raise ApiError("ERR_INSUFFICIENT_BANK_CREDITS")
    else:
        if bank is not None:
            raise ApiError("ERR_BANK_NOT_ELIGIBLE")

    base, pct, admin, total = calc.commitment_cost(mechanism, units, bank)
    row = store.new_row(
        hcp_id=plan["id"],
        conservation_bank_id=bank["id"] if bank is not None else None,
        mechanism=mechanism,
        units=units,
        status="RESERVED",
        base_fee_cents=base,
        admin_fee_pct_applied=pct,
        admin_fee_cents=admin,
        total_cost_cents=total,
        endowment_contribution_cents=0,
    )
    store.insert("commitments", row)

    if bank is not None:
        bank["credits_available"] = util.q2(
            util.to_dec(bank["credits_available"]) - units
        )
        bank["credits_reserved"] = util.q2(
            util.to_dec(bank["credits_reserved"]) + units
        )
        store.touch(bank)

    calc.recompute_endowment(plan)
    calc.recompute_secured_units(plan)
    calc.recompute_funding(plan)
    store.touch(plan)

    return envelope.created(serialize.commitment(row))


@bp.route("/habitat-conservation-plans/<hid>/funding-assurances",
          methods=["POST"])
def record_funding(hid):
    caller = auth.authenticate(PROPONENT)
    plan = resolve.plan(hid)
    auth.require_owner(caller, auth.owner_of_plan(plan))

    body = shape.Body()
    contribution = body.money("contribution_cents")
    body.enum("instrument_type", calc.INSTRUMENT_TYPES)
    body.close()

    if plan["plan_status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    plan["endowment_secured_cents"] = plan["endowment_secured_cents"] + contribution
    calc.recompute_funding(plan)
    store.touch(plan)
    return envelope.obj(serialize.plan(plan))


@bp.route("/habitat-conservation-plans/<hid>/submit", methods=["POST"])
def submit_plan(hid):
    caller = auth.authenticate(PROPONENT)
    plan = resolve.plan(hid)
    auth.require_owner(caller, auth.owner_of_plan(plan))
    shape.Body().close()

    if plan["plan_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # Rung 23.
    if not calc.plan_commitments(plan, ("RESERVED",)):
        raise ApiError("ERR_NO_MITIGATION_COMMITMENTS")

    action = store.get("actions", plan["project_action_id"])
    final_units = calc.final_mitigation_units(action)
    plan["plan_status"] = "SUBMITTED"
    plan["final_mitigation_units"] = final_units
    plan["mitigation_delta_units"] = util.q2(
        final_units - util.to_dec(plan["preliminary_mitigation_units"])
    )
    calc.recompute_secured_units(plan)
    store.touch(plan)
    return envelope.obj(serialize.plan(plan))


@bp.route("/habitat-conservation-plans/<hid>/decision", methods=["POST"])
def decide_plan(hid):
    caller = auth.authenticate(AGENCY)
    plan = resolve.plan(hid)

    body = shape.Body()
    decision = body.enum("decision", calc.PLAN_DECISIONS)
    body.string("decision_note", 1, required=False)
    body.close()

    if plan["plan_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if decision == "APPROVE":
        _check_approval_gates(plan)
        _approve(plan, caller.user_id)
    else:
        _return_for_revision(plan)

    store.touch(plan)
    return envelope.obj(serialize.plan(plan))


def _check_approval_gates(plan):
    action = store.get("actions", plan["project_action_id"])
    consultation_id = action.get("active_consultation_id") if action else None
    if consultation_id is not None:
        for opinion in store.where("opinions", consultation_id=consultation_id):
            # JEOPARDY_WITH_RPA and NO_JEOPARDY both pass the gate.
            if opinion["conclusion"] == "JEOPARDY":
                raise ApiError("ERR_JEOPARDY_UNRESOLVED")

    if plan["funding_status"] != "FULLY_ASSURED":
        raise ApiError("ERR_FUNDING_NOT_ASSURED")

    if util.to_dec(plan["secured_mitigation_units"]) < util.to_dec(
        plan["final_mitigation_units"]
    ):
        raise ApiError("ERR_MITIGATION_SHORTFALL")


def _approve(plan, user_id):
    plan["plan_status"] = "APPROVED"
    plan["approved_by_user_id"] = user_id
    for commitment in calc.plan_commitments(plan, ("RESERVED",)):
        commitment["status"] = "SECURED"
        store.touch(commitment)
        if commitment["mechanism"] != "CONSERVATION_BANK_CREDIT":
            continue
        bank = store.get("banks", commitment["conservation_bank_id"])
        if bank is None:
            continue
        units = util.to_dec(commitment["units"])
        bank["credits_reserved"] = util.q2(
            util.to_dec(bank["credits_reserved"]) - units
        )
        bank["credits_transferred"] = util.q2(
            util.to_dec(bank["credits_transferred"]) + units
        )
        store.touch(bank)
    calc.refresh_reserve_remaining(plan)


def _return_for_revision(plan):
    plan["plan_status"] = "DRAFT"
    for commitment in calc.plan_commitments(plan, ("RESERVED",)):
        commitment["status"] = "RELEASED"
        store.touch(commitment)
        if commitment["mechanism"] != "CONSERVATION_BANK_CREDIT":
            continue
        bank = store.get("banks", commitment["conservation_bank_id"])
        if bank is None:
            continue
        units = util.to_dec(commitment["units"])
        # The bank returns to its exact pre-commitment split.
        bank["credits_reserved"] = util.q2(
            util.to_dec(bank["credits_reserved"]) - units
        )
        bank["credits_available"] = util.q2(
            util.to_dec(bank["credits_available"]) + units
        )
        store.touch(bank)
    calc.recompute_endowment(plan)
    calc.recompute_funding(plan)
