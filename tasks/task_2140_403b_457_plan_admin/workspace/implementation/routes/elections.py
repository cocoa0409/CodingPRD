"""Contribution elections."""
import datetime

from flask import Blueprint, g, request

import auth
import calc
import derive
import envelope
import serialize
import store
import validate as V
from auth import endpoint
from errors import ApiError

bp = Blueprint("elections", __name__)


def _catchup_structurally_ok(catchup, plan_type):
    if catchup == "NONE":
        return True
    if catchup == "FINAL_3_YEAR":
        return plan_type == "PLAN_457B"
    if catchup in ("SERVICE_15_YEAR", "AGE_50_AND_SERVICE_15_YEAR"):
        return plan_type == "PLAN_403B"
    return True   # AGE_50 is admissible on either plan type


def _catchup_capacity_ok(catchup, plan, participant, employer):
    age = calc.attained_age_at_year_end(participant)
    if catchup in ("AGE_50", "AGE_50_AND_SERVICE_15_YEAR"):
        if age < 50:
            return False
        if plan["plan_type"] == "PLAN_457B" and not plan["is_governmental_457"]:
            return False
    if catchup in ("SERVICE_15_YEAR", "AGE_50_AND_SERVICE_15_YEAR"):
        if not employer["is_qualified_organization"]:
            return False
        if participant["years_of_service"] < calc.SERVICE_15YR_MIN_YEARS:
            return False
    if catchup == "FINAL_3_YEAR":
        if age not in (62, 63, 64):
            return False
    return True


@bp.post("/plan-admin/contribution-elections")
@endpoint(["PlanSponsorAdmin", "Participant"])
def create_election():
    body = V.body_of(request)
    participant_id = V.req_str(body, "participant_id")
    plan_id = V.req_str(body, "plan_id")
    vendor_account_id = V.req_str(body, "vendor_account_id")
    amount = V.req_int(body, "annual_deferral_amount_cents", minimum=1)
    effective_from = V.req_date(body, "effective_from")
    effective_through = V.req_date(body, "effective_through")
    if effective_through < effective_from:
        raise V.bad("effective_through must fall on or after effective_from.")
    expected_version = V.req_int(body, "expected_participant_version")
    catchup = V.opt_enum(body, "catchup_election", calc.CATCHUP_ELECTIONS, "NONE")
    supersedes_id = V.opt_str(body, "supersedes_election_id")

    participant = auth.participant(participant_id)      # rung 5
    plan = auth.plan(plan_id)                           # rung 5
    auth.vendor_account(vendor_account_id)              # rung 5
    superseded_row = auth.election(supersedes_id) if supersedes_id else None   # rung 5

    if g.role == "Participant":                         # rung 6
        auth.require(participant_id == g.user_id)
    else:
        auth.own_plan(plan)

    if expected_version != participant["version"]:      # rung 8
        raise ApiError("ERR_STALE_VERSION",
                       "expected_participant_version does not match the participant's version.")
    if plan["status"] not in ("ACTIVE", "FROZEN"):      # rung 10
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "The governing plan is %s." % plan["status"])
    if plan["status"] == "FROZEN":                      # rung 11
        raise ApiError("ERR_PLAN_FROZEN",
                       "No election may be created against a frozen plan.")
    if (plan["nondiscrimination_regime"] == "TOP_HAT_457"
            and not participant["is_select_management_or_hce"]):   # rung 18
        raise ApiError("ERR_NOT_TOP_HAT_ELIGIBLE",
                       "A top-hat 457(b) plan admits only select management or highly "
                       "compensated employees.")

    for other in store.elections_of(participant_id):    # rung 31
        if other["plan_id"] != plan_id:
            continue
        if other["state"] not in ("SUBMITTED", "EFFECTIVE"):
            continue
        if superseded_row is not None and other["id"] == superseded_row["id"]:
            continue
        other_from = calc.parse_iso_date(other["effective_from"])
        other_through = calc.parse_iso_date(other["effective_through"])
        if effective_from <= other_through and other_from <= effective_through:
            raise ApiError("ERR_ELECTION_WINDOW_OVERLAP",
                           "The election window overlaps an existing election.")

    if not _catchup_structurally_ok(catchup, plan["plan_type"]):    # rung 35
        raise ApiError("ERR_CATCHUP_COMBINATION_NOT_PERMITTED",
                       "The elected catch-up combination is impossible for this plan type.")
    employer = store.employers.get(plan["employer_id"])
    if not _catchup_capacity_ok(catchup, plan, participant, employer):   # rung 36
        raise ApiError("ERR_CATCHUP_NOT_AVAILABLE",
                       "An elected catch-up bucket has zero capacity for this participant.")

    row = store.common_fields()
    row.update({
        "participant_id": participant_id,
        "plan_id": plan_id,
        "vendor_account_id": vendor_account_id,
        "supersedes_election_id": supersedes_id,
        "annual_deferral_amount_cents": amount,
        "effective_from": effective_from.isoformat(),
        "effective_through": effective_through.isoformat(),
        "catchup_election": catchup,
        "state": "SUBMITTED",
        "basic_deferral_attributed_cents": 0,
        "service_catchup_attributed_cents": 0,
        "age50_catchup_attributed_cents": 0,
        "final3yr_catchup_attributed_cents": 0,
        "submitted_by_user_id": g.user_id,
        "approved_by_user_id": None,
    })
    store.contribution_elections[row["id"]] = row
    store.touch(participant)
    return envelope.created(serialize.election(row))


@bp.get("/plan-admin/contribution-elections/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_election(row_id):
    return envelope.ok(serialize.election(auth.election(row_id)))


@bp.get("/plan-admin/contribution-elections")
@endpoint(auth.ALL_ROLES)
def list_elections():
    args = request.args
    limit, offset = V.pagination(args)
    participant_id = args.get("participant_id")
    plan_id = args.get("plan_id")
    vendor_account_id = args.get("vendor_account_id")
    supersedes_election_id = args.get("supersedes_election_id")
    state = V.query_enum(args, "state", calc.ELECTION_STATES)
    items = store.rows(store.contribution_elections)
    if participant_id:
        items = [e for e in items if e["participant_id"] == participant_id]
    if plan_id:
        items = [e for e in items if e["plan_id"] == plan_id]
    if vendor_account_id:
        items = [e for e in items if e["vendor_account_id"] == vendor_account_id]
    if supersedes_election_id:
        items = [e for e in items if e["supersedes_election_id"] == supersedes_election_id]
    if state:
        items = [e for e in items if e["state"] == state]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.election(e) for e in page], limit, offset, total)


@bp.post("/plan-admin/contribution-elections/<row_id>/decision")
@endpoint(["ComplianceOfficer"])
def decide_election(row_id):
    body = V.body_of(request)
    decision = V.req_enum(body, "decision", {"APPROVE", "REJECT"})
    V.opt_str(body, "note")

    election = auth.election(row_id)                    # rung 4
    determination = store.latest_determination(election["plan_id"], election["participant_id"])
    if determination is not None and determination["determined_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",     # rung 7
                       "The officer who ran the eligibility determination may not decide "
                       "the election it governs.")
    if election["state"] != "SUBMITTED":                # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED election may be decided.")
    plan = store.plans.get(election["plan_id"])
    participant = store.participants.get(election["participant_id"])
    employer = store.employers.get(plan["employer_id"])
    if plan["status"] not in ("ACTIVE", "FROZEN"):      # rung 10
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "The governing plan is %s." % plan["status"])
    if plan["status"] == "FROZEN":                      # rung 11
        raise ApiError("ERR_PLAN_FROZEN",
                       "No election of a frozen plan may be decided.")

    if decision == "REJECT":
        election["state"] = "REJECTED"
        election["approved_by_user_id"] = g.user_id
        store.touch(election)
        return envelope.ok(serialize.election(election))

    if (determination is not None
            and determination["universal_availability_applies"]
            and determination["notice_status"] != "CURRENT"):        # rung 16
        raise ApiError("ERR_UA_NOTICE_MISSING",
                       "No valid universal availability notice covers this plan year.")
    if determination is None or determination["status"] != "ELIGIBLE":   # rung 19
        raise ApiError("ERR_PARTICIPANT_NOT_ELIGIBLE",
                       "The governing eligibility determination is absent or not ELIGIBLE.")

    attribution, remainder = calc.deferral_attribution_order(election, plan, participant,
                                                             employer)
    if remainder > 0:                                    # rung 37
        raise ApiError("ERR_402G_LIMIT_EXCEEDED",
                       "The attribution waterfall leaves an unattributed remainder.")
    annual_additions, annual_limit = calc.annual_additions_415c(plan, participant)
    if annual_additions is not None:                     # rung 38
        if annual_additions + election["annual_deferral_amount_cents"] > annual_limit:
            raise ApiError("ERR_415C_LIMIT_EXCEEDED",
                           "Annual additions would exceed the section 415(c) limit.")

    snapshot_used = attribution.pop("snapshot_used")
    election.update(attribution)
    election["state"] = "EFFECTIVE"
    election["approved_by_user_id"] = g.user_id
    store.touch(election)

    participant["cumulative_special_catchup_used_cents"] = (
        snapshot_used + attribution["service_catchup_attributed_cents"])

    if election["supersedes_election_id"]:
        prior = store.contribution_elections.get(election["supersedes_election_id"])
        if prior is not None and prior["state"] == "EFFECTIVE":
            prior["state"] = "SUPERSEDED"
            new_from = calc.parse_iso_date(election["effective_from"])
            prior["effective_through"] = (new_from - datetime.timedelta(days=1)).isoformat()
            store.touch(prior)

    derive.recompute_participant(participant, bump=True)
    derive.recompute_plan_excess(plan)
    return envelope.ok(serialize.election(election))


@bp.post("/plan-admin/contribution-elections/<row_id>/revoke")
@endpoint(["PlanSponsorAdmin", "Participant"])
def revoke_election(row_id):
    body = V.body_of(request)
    V.opt_str(body, "reason")
    election = auth.election(row_id)                    # rung 4
    plan = store.plans.get(election["plan_id"])
    participant = store.participants.get(election["participant_id"])
    if g.role == "Participant":                         # rung 6
        auth.require(election["participant_id"] == g.user_id)
    else:
        auth.own_plan(plan)
    if election["state"] not in ("SUBMITTED", "EFFECTIVE"):   # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED or EFFECTIVE election may be revoked.")

    was_effective = election["state"] == "EFFECTIVE"
    election["state"] = "REVOKED"
    store.touch(election)
    if was_effective:
        participant["cumulative_special_catchup_used_cents"] -= (
            election["service_catchup_attributed_cents"])
        derive.recompute_participant(participant, bump=True)
        derive.recompute_plan_excess(plan)
    return envelope.ok(serialize.election(election))
