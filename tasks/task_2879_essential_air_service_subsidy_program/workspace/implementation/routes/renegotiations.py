"""Rate renegotiation on fuel and documented-cost grounds (PRD 3.10)."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import errors
import lookups
import response
import serializers
import validation as v
from auth import CARRIER, PROGRAM_ADMIN, SELECTION_OFFICER, endpoint
from db import add_days, base_row, by_seq, dec, now, now_iso, q2, store, touch

bp = Blueprint("renegotiations", __name__)

TRIGGER_TYPES = ("FUEL_INDEX", "COST_INCREASE")
ADMIN_ACTIONS = ("COUNTER", "ACCEPT", "REJECT")
CARRIER_ACTIONS = ("REVISE", "WITHDRAW")
RENEGOTIATION_ACTIONS = ADMIN_ACTIONS + CARRIER_ACTIONS
OPEN_STATUSES = ("REQUESTED", "COUNTERED")
ACCEPTABLE_AGREEMENT_STATUSES = ("ACTIVE", "HOLD_IN")
MAX_REVISIONS = 3


def _facial_cap_guard(agreement, requested):
    if requested is None:
        return
    if dec(requested) > calc.facial_cap(agreement):
        v.bad("The requested annual subsidy exceeds 1.25 times the rate in force.")


@bp.route("/rate-renegotiations", methods=["POST"])
@endpoint(CARRIER)
def create_renegotiation():
    data = v.body()
    agreement_id = v.id_field(data, "agreement_id")
    trigger_type = v.enum_field(data, "trigger_type", TRIGGER_TYPES)
    requested = v.num_field(data, "requested_annual_subsidy_usd", places=2,
                            exclusive_minimum=0)
    justification = v.str_field(data, "justification", min_len=1, max_len=2000)
    fuel_index_month = v.month_field(data, "fuel_index_month", required=False)
    cost_increase_pct = v.num_field(data, "documented_cost_increase_pct",
                                    required=False, places=4, minimum=0)

    agreement = lookups.agreement(agreement_id)
    _facial_cap_guard(agreement, requested)

    auth.require_owner(agreement["carrier_id"])

    if trigger_type == "FUEL_INDEX":
        if fuel_index_month is None or cost_increase_pct is not None:
            errors.fail(errors.ERR_MISSING_FUEL_INDEX,
                        "A FUEL_INDEX request must carry fuel_index_month and omit "
                        "documented_cost_increase_pct.")
        if lookups.fuel_index_for_month(fuel_index_month) is None:
            errors.fail(errors.ERR_MISSING_FUEL_INDEX,
                        "No fuel index has been published for %s." % fuel_index_month)
    else:
        if cost_increase_pct is None or fuel_index_month is not None:
            errors.fail(errors.ERR_MISSING_FUEL_INDEX,
                        "A COST_INCREASE request must carry "
                        "documented_cost_increase_pct and omit fuel_index_month.")

    for row in store.renegotiations.values():
        if row["agreement_id"] == agreement["id"] and row["status"] in OPEN_STATUSES:
            errors.fail(errors.ERR_RENEGOTIATION_ALREADY_OPEN,
                        "This agreement already carries a live renegotiation.")

    cooling_off_ends = add_days(v.parse_stamp(agreement["rate_effective_from"]),
                               calc.RENEGOTIATION_COOLING_OFF_DAYS)
    if now() < cooling_off_ends:
        errors.fail(errors.ERR_RENEGOTIATION_COOLING_OFF,
                    "The rate may not be reopened before its cooling-off period ends.")

    figures = calc.renegotiation_figures(agreement, trigger_type, fuel_index_month,
                                         cost_increase_pct)

    row = base_row(True)
    row.update({
        "agreement_id": agreement["id"],
        "trigger_type": trigger_type,
        "fuel_index_month": fuel_index_month,
        "documented_cost_increase_pct": cost_increase_pct,
        "requested_annual_subsidy_usd": requested,
        "justification": justification,
        "current_fuel_index_usd": figures["current_fuel_index_usd"],
        "fuel_cost_delta_usd": figures["fuel_cost_delta_usd"],
        "justified_delta_usd": figures["justified_delta_usd"],
        "ceiling_annual_subsidy_usd": figures["ceiling_annual_subsidy_usd"],
        "countered_annual_subsidy_usd": None,
        "approved_annual_subsidy_usd": None,
        "revision_count": 0,
        "status": "REQUESTED",
        "effective_at": None,
    })
    store.renegotiations[row["id"]] = row
    return response.created(serializers.renegotiation(row))


@bp.route("/rate-renegotiations/<rid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, CARRIER)
def read_renegotiation(rid):
    return response.ok(serializers.renegotiation(lookups.renegotiation(rid)))


@bp.route("/rate-renegotiations", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, CARRIER)
def list_renegotiations():
    rows = list(store.renegotiations.values())
    for field in ("agreement_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return response.paginate(by_seq(rows), serializers.renegotiation)


@bp.route("/rate-renegotiations/<rid>/actions", methods=["POST"])
@endpoint(PROGRAM_ADMIN, CARRIER)
def renegotiation_actions(rid):
    data = v.body()

    # rung 2: the action-level role split precedes request-shape validation.
    peeked = data.get("action")
    if isinstance(peeked, str):
        if peeked in ADMIN_ACTIONS and auth.role() != PROGRAM_ADMIN:
            errors.fail(errors.ERR_UNAUTHORIZED,
                        "%s is reserved to ProgramAdmin." % peeked)
        if peeked in CARRIER_ACTIONS and auth.role() != CARRIER:
            errors.fail(errors.ERR_UNAUTHORIZED,
                        "%s is reserved to the Carrier." % peeked)

    action = v.enum_field(data, "action", RENEGOTIATION_ACTIONS)
    revised = v.num_field(data, "revised_annual_subsidy_usd", required=False,
                          places=2, exclusive_minimum=0)
    v.str_field(data, "action_note", required=False, min_len=0, max_len=2000)

    renegotiation = lookups.renegotiation(rid)
    agreement = lookups.agreement(renegotiation["agreement_id"])
    if action == "REVISE":
        _facial_cap_guard(agreement, revised)

    if auth.role() == CARRIER:
        auth.require_owner(agreement["carrier_id"])

    status = renegotiation["status"]

    if action == "COUNTER":
        if status != "REQUESTED":
            errors.fail(errors.ERR_RENEGOTIATION_NOT_ACTIONABLE,
                        "A renegotiation in status %s may not be countered." % status)
        renegotiation["status"] = "COUNTERED"
        renegotiation["countered_annual_subsidy_usd"] = \
            renegotiation["ceiling_annual_subsidy_usd"]
        touch(renegotiation)
        return response.ok(serializers.renegotiation(renegotiation))

    if action == "REVISE":
        if status != "COUNTERED":
            errors.fail(errors.ERR_RENEGOTIATION_NOT_ACTIONABLE,
                        "A renegotiation in status %s may not be revised." % status)
        if renegotiation["revision_count"] >= MAX_REVISIONS or revised is None:
            errors.fail(errors.ERR_REVISION_LIMIT_EXCEEDED,
                        "No further revision is permitted on this renegotiation.")
        figures = calc.renegotiation_figures(
            agreement, renegotiation["trigger_type"],
            renegotiation["fuel_index_month"],
            renegotiation["documented_cost_increase_pct"])
        renegotiation["requested_annual_subsidy_usd"] = revised
        renegotiation["current_fuel_index_usd"] = figures["current_fuel_index_usd"]
        renegotiation["fuel_cost_delta_usd"] = figures["fuel_cost_delta_usd"]
        renegotiation["justified_delta_usd"] = figures["justified_delta_usd"]
        renegotiation["ceiling_annual_subsidy_usd"] = \
            figures["ceiling_annual_subsidy_usd"]
        renegotiation["revision_count"] = renegotiation["revision_count"] + 1
        renegotiation["status"] = "REQUESTED"
        touch(renegotiation)
        return response.ok(serializers.renegotiation(renegotiation))

    if status not in OPEN_STATUSES:
        errors.fail(errors.ERR_RENEGOTIATION_NOT_ACTIONABLE,
                    "A renegotiation in status %s does not admit this action."
                    % status)

    if action == "REJECT":
        renegotiation["status"] = "REJECTED"
        touch(renegotiation)
        return response.ok(serializers.renegotiation(renegotiation))

    if action == "WITHDRAW":
        renegotiation["status"] = "WITHDRAWN"
        touch(renegotiation)
        return response.ok(serializers.renegotiation(renegotiation))

    # --- ACCEPT ------------------------------------------------------------
    if agreement["status"] not in ACCEPTABLE_AGREEMENT_STATUSES:
        errors.fail(errors.ERR_AGREEMENT_NOT_ACTIVE,
                    "An agreement in status %s may not be repriced."
                    % agreement["status"])

    ceiling = dec(renegotiation["ceiling_annual_subsidy_usd"])
    requested = dec(renegotiation["requested_annual_subsidy_usd"])
    approved = ceiling if ceiling < requested else requested
    rate_in_force = dec(agreement["annual_subsidy_usd"])

    settled = len([p for p in lookups.periods_of_agreement(agreement["id"])
                   if p["status"] in ("CERTIFIED", "PAID")])
    remaining_months = agreement["term_months"] - settled
    if remaining_months < 0:
        remaining_months = 0

    delta = q2(approved - rate_in_force)
    prorated = q2(delta * dec(remaining_months) / Decimal("12"))
    new_total = q2(dec(agreement["total_committed_usd"]) + prorated)
    new_obligated = q2(new_total - dec(agreement["disbursed_to_date_usd"]))
    if new_obligated < Decimal("0.00"):
        errors.fail(errors.ERR_OBLIGATION_EXCEEDED,
                    "The repriced term commits less than has already been disbursed.")

    renegotiation["status"] = "ACCEPTED"
    renegotiation["approved_annual_subsidy_usd"] = q2(approved)
    renegotiation["effective_at"] = now_iso()
    touch(renegotiation)

    agreement["annual_subsidy_usd"] = q2(approved)
    agreement["rate_effective_from"] = now_iso()
    agreement["total_committed_usd"] = new_total
    agreement["obligated_remaining_usd"] = new_obligated
    touch(agreement)

    return response.ok(serializers.renegotiation(renegotiation))
