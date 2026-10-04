"""Treatment plans and pre-authorizations (PRD 3.4, 3.5)."""

from datetime import timedelta
from body import body, opt, require, require_enum, require_int
from bp import api
from clock import AUTHORIZATION_WINDOW_DAYS, parse_dt
from db import db
from errors import APIError
from helpers import (
    active_contract_rate,
    bundle_of_plan,
    bundle_of_preauth,
    employer_of_bundle,
    member_of_plan,
    plan_of_preauth,
    recompute_bundle,
    recompute_bundle_of_plan,
)
from calculations import clinical_criteria_gate, clinic_bundle_price, remaining_cycles
from listing import apply_filters, ordered, paginate
from lookups import (
    check_occ,
    clinic as clinic_lookup,
    preauthorization as preauth_lookup,
    resolve_member_version,
    treatment_plan as plan_lookup,
)
from middleware import resolve_actor
from response import ok, created
from serializers import serialize

PLAN_LIVE_STATES = ("CLINIC_SELECTED", "AUTHORIZATION_PENDING", "IN_PROGRESS")


# --------------------------------------------------------------------------
# TreatmentPlan
# --------------------------------------------------------------------------

@api.route("/treatment-plans", methods=["POST"])
def create_treatment_plan():
    resolve_actor()
    data = body()
    member_id = require(data, "member_id")
    bundle_id = require(data, "bundle_entitlement_id")
    pathway_type = require_enum(data, "pathway_type", "plan_pathway_type")
    planned_cycles = require_int(data, "planned_cycles")
    min_inter_cycle_days = opt(data, "min_inter_cycle_days")
    if min_inter_cycle_days is None:
        min_inter_cycle_days = 0

    member = db.find("members", member_id)
    if member is None:
        raise APIError("ERR_NOT_FOUND", "The member_id does not resolve.")
    bundle = db.find("bundle_entitlements", bundle_id)
    if bundle is None:
        raise APIError("ERR_NOT_FOUND", "The bundle_entitlement_id does not resolve.")

    row = db.common()
    row.update({
        "_collection": "treatment_plans",
        "member_id": member_id,
        "care_advocate_id": member.get("care_advocate_id"),
        "bundle_entitlement_id": bundle_id,
        "clinic_id": None,
        "pathway_type": pathway_type,
        "plan_status": "PLAN_DRAFT",
        "planned_cycles": planned_cycles,
        "min_inter_cycle_days": min_inter_cycle_days,
        "selected_bundle_price_cents": 0,
        "cycles_completed": 0,
        "plan_blocked_reason": None,
    })
    db.add(row)
    return created(serialize("treatment_plans", row))


@api.route("/treatment-plans/<plan_id>", methods=["GET"])
def get_treatment_plan(plan_id):
    resolve_actor()
    row = plan_lookup(plan_id)
    return ok(serialize("treatment_plans", row))


@api.route("/treatment-plans", methods=["GET"])
def list_treatment_plans():
    resolve_actor()
    rows = ordered(db.all("treatment_plans"))
    rows = apply_filters(rows, {
        "member_id": "member_id",
        "clinic_id": "clinic_id",
        "bundle_entitlement_id": "bundle_entitlement_id",
        "care_advocate_id": "care_advocate_id",
        "plan_status": "plan_status",
        "pathway_type": "pathway_type",
    })
    return paginate(rows, "treatment_plans")


@api.route("/treatment-plans/<plan_id>/select-clinic", methods=["POST"])
def select_clinic(plan_id):
    resolve_actor()
    plan = plan_lookup(plan_id)
    data = body()
    clinic_id = require(data, "clinic_id")
    expected_member_version = data.get("expected_member_version")

    clinic = clinic_lookup(clinic_id)
    member = member_of_plan(db, plan)
    bundle = bundle_of_plan(db, plan)

    if plan["plan_status"] != "PLAN_DRAFT":
        raise APIError("ERR_INVALID_STATE", "The plan is not PLAN_DRAFT.")

    if clinic["clinic_status"] != "CONTRACTED":
        raise APIError("ERR_CLINIC_NOT_CONTRACTED", "The clinic is not CONTRACTED.")

    rate = active_contract_rate(db, clinic_id, bundle["bundle_type"])
    if rate is None:
        raise APIError("ERR_CLINIC_NOT_CONTRACTED", "No negotiated rate applies for this bundle type.")

    resolve_member_version(expected_member_version, member["version"])

    plan["clinic_id"] = clinic_id
    plan["plan_status"] = "CLINIC_SELECTED"
    plan["selected_bundle_price_cents"] = clinic_bundle_price(rate, bundle.get("copay_max"))
    member["clinic_id"] = clinic_id
    db.touch(member)
    return ok(serialize("treatment_plans", plan))


@api.route("/treatment-plans/<plan_id>/preauthorizations", methods=["POST"])
def create_preauthorization(plan_id):
    resolve_actor()
    plan = plan_lookup(plan_id)

    # Priority 5: the declared-state rule for the requested transition.
    if plan["plan_status"] not in PLAN_LIVE_STATES:
        raise APIError("ERR_INVALID_STATE", "The plan is not in a state that admits an authorization.")

    data = body()
    cycle_sequence_index = require_int(data, "cycle_sequence_index")
    criteria_inputs = data.get("criteria_inputs") or {}
    member_cost_share_pct = require_int(data, "member_cost_share_pct")
    if member_cost_share_pct < 0 or member_cost_share_pct > 100:
        raise APIError("ERR_INVALID_REQUEST", "member_cost_share_pct must be between 0 and 100.")

    # Priority 5: the sequencing guard.
    highest = 0
    for existing in db.all("preauthorizations"):
        if existing["treatment_plan_id"] == plan["id"]:
            highest = max(highest, existing["cycle_sequence_index"])
    if cycle_sequence_index <= highest:
        raise APIError("ERR_SEQUENCE_OUT_OF_ORDER", "The sequence index is not the plan's next position.")

    # Priority 13: the carried allowance.
    bundle = bundle_of_plan(db, plan)
    employer = employer_of_bundle(db, bundle)
    if remaining_cycles(db, bundle, employer) < 1:
        if bundle["cycles_remaining"] == 0 and bundle["pharmacy_remaining_cents"] == 0:
            raise APIError("ERR_BUNDLE_EXHAUSTED", "The bundle's allowance and pharmacy pool are empty.")
        raise APIError("ERR_NO_REMAINING_ALLOWANCE", "The bundle carries no remaining cycle.")

    row = db.common()
    row.update({
        "_collection": "preauthorizations",
        "treatment_plan_id": plan["id"],
        "cycle_sequence_index": cycle_sequence_index,
        "criteria_inputs": criteria_inputs,
        "member_cost_share_pct": member_cost_share_pct,
        "review_status": "SUBMITTED",
        "consumption_status": "UNCONSUMED",
        "clinical_criteria_score": clinical_criteria_gate(criteria_inputs),
        "approved_cycles": 0,
        "consumed_cycles": 0,
        "bundle_price_snapshot_cents": 0,
        "effective_from": None,
        "effective_to": None,
        "denial_reason_code": None,
        "decision_actor": None,
    })
    db.add(row)

    plan["plan_status"] = "AUTHORIZATION_PENDING"
    recompute_bundle(db, bundle)
    return created(serialize("preauthorizations", row))


@api.route("/treatment-plans/<plan_id>/resubmit-plan", methods=["POST"])
def resubmit_plan(plan_id):
    resolve_actor()
    plan = plan_lookup(plan_id)
    data = body()
    expected = data.get("expected_treatment_plan_version")
    check_occ(expected, plan["version"], "ERR_PLAN_VERSION_STALE",
              "The plan's version has advanced since it was observed.")

    if plan["plan_status"] != "PLANNING_REVISION":
        raise APIError("ERR_INVALID_STATE", "The plan is not in PLANNING_REVISION.")

    clinic = db.find("clinics", plan["clinic_id"]) if plan.get("clinic_id") else None
    if clinic is None or clinic["clinic_status"] != "CONTRACTED":
        raise APIError("ERR_CLINIC_NOT_CONTRACTED", "The plan's clinic is not CONTRACTED.")

    plan["plan_status"] = "AUTHORIZATION_PENDING"
    plan["plan_blocked_reason"] = None
    for pa in db.all("preauthorizations"):
        if pa["treatment_plan_id"] == plan["id"] and pa["review_status"] == "DENIED" \
                and pa.get("denial_reason_code") == "CLINIC_NOT_CONTRACTED":
            pa["review_status"] = "CLINICAL_REVIEW"
            pa["denial_reason_code"] = None
            db.touch(pa)
    db.touch(plan)
    return ok(serialize("treatment_plans", plan))


@api.route("/treatment-plans/<plan_id>/abandon", methods=["POST"])
def abandon_plan(plan_id):
    resolve_actor()
    plan = plan_lookup(plan_id)
    if plan["plan_status"] not in ("PLAN_DRAFT", "CLINIC_SELECTED", "PLANNING_REVISION"):
        raise APIError("ERR_INVALID_STATE", "The plan may not be abandoned from its current state.")

    plan["plan_status"] = "ABANDONED"

    for pa in db.all("preauthorizations"):
        if pa["treatment_plan_id"] != plan["id"]:
            continue
        if pa["review_status"] in ("SUBMITTED", "CLINICAL_REVIEW", "APPROVED"):
            pa["review_status"] = "EXPIRED"
            pa["approved_cycles"] = 0
            db.touch(pa)

    for cycle in db.all("treatment_cycles"):
        if cycle["treatment_plan_id"] == plan["id"] and cycle["cycle_status"] != "OUTCOME_RECORDED":
            cycle["cycle_status"] = "CANCELLED"
            cycle["consumption_marker"] = "UNCONSUMED"
            db.touch(cycle)

    db.touch(plan)
    recompute_bundle_of_plan(db, plan)
    return ok(serialize("treatment_plans", plan))


# --------------------------------------------------------------------------
# Preauthorization
# --------------------------------------------------------------------------

@api.route("/preauthorizations/<preauth_id>", methods=["GET"])
def get_preauthorization(preauth_id):
    resolve_actor()
    row = preauth_lookup(preauth_id)
    return ok(serialize("preauthorizations", row))


@api.route("/preauthorizations", methods=["GET"])
def list_preauthorizations():
    resolve_actor()
    rows = ordered(db.all("preauthorizations"))
    rows = apply_filters(rows, {
        "treatment_plan_id": "treatment_plan_id",
        "review_status": "review_status",
        "consumption_status": "consumption_status",
    })
    return paginate(rows, "preauthorizations")


@api.route("/preauthorizations/<preauth_id>/begin-clinical-review", methods=["POST"])
def begin_clinical_review(preauth_id):
    actor = resolve_actor()
    pa = preauth_lookup(preauth_id)

    if pa["review_status"] not in ("SUBMITTED", "DENIED"):
        raise APIError("ERR_INVALID_STATE", "The authorization is not SUBMITTED or DENIED.")

    if pa.get("decision_actor") and actor.user_id == pa["decision_actor"]:
        raise APIError("ERR_SOD_CONFLICT", "The reviewer already recorded a decision on this resource.")

    pa["review_status"] = "CLINICAL_REVIEW"
    pa["clinical_criteria_score"] = clinical_criteria_gate(pa.get("criteria_inputs") or {})
    db.touch(pa)
    return ok(serialize("preauthorizations", pa))


@api.route("/preauthorizations/<preauth_id>/decide", methods=["POST"])
def decide_preauthorization(preauth_id):
    actor = resolve_actor()
    pa = preauth_lookup(preauth_id)

    # Priority 4: segregation of duties, evaluated before the state gate.
    if pa.get("decision_actor") and actor.user_id == pa["decision_actor"]:
        raise APIError("ERR_SOD_CONFLICT", "The reviewer already recorded a decision on this resource.")

    # Priority 5: the declared-state rule.  A decision is rendered from either
    # SUBMITTED or CLINICAL_REVIEW; anything already decided is refused.
    if pa["review_status"] not in ("SUBMITTED", "CLINICAL_REVIEW"):
        raise APIError("ERR_INVALID_STATE", "The authorization is already decided.")

    data = body()
    if "decision" not in data or data["decision"] is None:
        raise APIError("ERR_INVALID_REQUEST", "The required input 'decision' is missing.")
    decision = data["decision"]
    if decision not in ("APPROVE", "DENY"):
        raise APIError("ERR_INVALID_REQUEST", "The decision is outside its declared enumeration.")
    if "expected_treatment_plan_version" not in data or data["expected_treatment_plan_version"] is None:
        raise APIError("ERR_INVALID_REQUEST",
                       "The required input 'expected_treatment_plan_version' is missing.")

    plan = plan_of_preauth(db, pa)
    bundle = bundle_of_preauth(db, pa)

    # The mandatory concurrency token, refused before any business rule.
    check_occ(data["expected_treatment_plan_version"], plan["version"], "ERR_PLAN_VERSION_STALE",
              "The plan's version has advanced since it was observed.")

    # A decision rendered straight from SUBMITTED passes through review first.
    pa["review_status"] = "CLINICAL_REVIEW"

    if decision == "DENY":
        pa["review_status"] = "DENIED"
        pa["denial_reason_code"] = data.get("denial_reason_code") or "CLINICAL_CRITERIA_NOT_MET"
        pa["decision_actor"] = actor.user_id
        db.touch(pa)
        return ok(serialize("preauthorizations", pa))

    # --- Approval gates, in the order the coverage family states them -------
    score = pa.get("clinical_criteria_score")
    if score is None:
        score = clinical_criteria_gate(pa.get("criteria_inputs") or {})
        pa["clinical_criteria_score"] = score

    clinic = db.find("clinics", plan["clinic_id"]) if plan.get("clinic_id") else None
    if clinic is None or clinic["clinic_status"] != "CONTRACTED":
        raise APIError("ERR_CLINIC_NOT_CONTRACTED", "The plan's clinic is not CONTRACTED.")
    bundle_type = bundle["bundle_type"]
    rate = active_contract_rate(db, clinic["id"], bundle_type)
    if rate is None:
        raise APIError("ERR_CLINIC_NOT_CONTRACTED", "No negotiated rate applies for this bundle type.")

    window_end = db.now() + timedelta(days=AUTHORIZATION_WINDOW_DAYS)
    contract = _covering_contract(clinic["id"])
    if contract is None or not (parse_dt(contract["effective_from"]) <= db.now()
                                and window_end <= parse_dt(contract["effective_to"])):
        raise APIError("ERR_PREAUTH_WINDOW_OUTSIDE_COVERAGE",
                       "The derived authorization window runs past the contract's coverage.")

    if contract["contracting_status"] == "FROZEN":
        raise APIError("ERR_CLINIC_CONTRACT_FROZEN", "The clinic's active contract is FROZEN.")

    employer = employer_of_bundle(db, bundle)
    if employer is None or employer["account_status"] != "ACTIVE":
        raise APIError("ERR_BENEFIT_INACTIVE", "The sponsoring account is not ACTIVE.")

    if remaining_cycles(db, bundle, employer) < 1:
        if bundle["cycles_remaining"] == 0 and bundle["pharmacy_remaining_cents"] == 0:
            raise APIError("ERR_BUNDLE_EXHAUSTED", "The bundle's allowance and pharmacy pool are empty.")
        raise APIError("ERR_NO_REMAINING_ALLOWANCE", "The bundle carries no remaining cycle.")

    if score < 70:
        # The score below the floor denies the authorization and reports the
        # refusal; the row reads DENIED for the clinical reason afterwards.
        pa["review_status"] = "DENIED"
        pa["denial_reason_code"] = "CLINICAL_CRITERIA_NOT_MET"
        pa["decision_actor"] = actor.user_id
        db.touch(pa)
        bundle = bundle_of_preauth(db, pa)
        recompute_bundle(db, bundle)
        raise APIError("ERR_CLINICAL_CRITERIA_NOT_MET",
                       "The clinical appropriateness score is below the floor.")

    if plan["plan_status"] != "AUTHORIZATION_PENDING":
        raise APIError("ERR_INVALID_STATE", "The plan is not AUTHORIZATION_PENDING.")

    for cycle in db.all("treatment_cycles"):
        if cycle["treatment_plan_id"] == plan["id"] and cycle["cycle_index"] > pa["cycle_sequence_index"]:
            raise APIError("ERR_SEQUENCE_OUT_OF_ORDER",
                           "A cycle of the plan already occupies a later sequence position.")

    if not plan.get("selected_bundle_price_cents"):
        raise APIError("ERR_BUNDLE_PRICE_UNPINNED", "No bundle price has been pinned for this plan.")

    pa["review_status"] = "APPROVED"
    pa["bundle_price_snapshot_cents"] = plan["selected_bundle_price_cents"]
    pa["approved_cycles"] = 1
    pa["effective_from"] = db.now()
    pa["effective_to"] = window_end
    pa["decision_actor"] = actor.user_id
    pa["denial_reason_code"] = None

    plan["plan_status"] = "IN_PROGRESS"
    db.touch(pa)
    recompute_bundle(db, bundle)
    return ok(serialize("preauthorizations", pa))


def _covering_contract(clinic_id):
    from helpers import contracts_of_clinic
    now = db.now()
    for contract in contracts_of_clinic(db, clinic_id, ("ACTIVE", "FROZEN")):
        start = parse_dt(contract["effective_from"])
        end = parse_dt(contract["effective_to"])
        if start <= now < end:
            return contract
    return None


@api.route("/preauthorizations/<preauth_id>/revise-request", methods=["POST"])
def revise_request(preauth_id):
    resolve_actor()
    pa = preauth_lookup(preauth_id)
    data = body()
    criteria_inputs = require(data, "criteria_inputs")

    if pa["review_status"] != "DENIED":
        raise APIError("ERR_INVALID_STATE", "The authorization is not DENIED.")
    if pa.get("denial_reason_code") not in ("CLINICAL_CRITERIA_NOT_MET", "BUNDLE_EXHAUSTED"):
        raise APIError("ERR_INVALID_STATE", "The denial does not arise from the clinical criteria or exhaustion.")

    pa["review_status"] = "CLINICAL_REVIEW"
    pa["denial_reason_code"] = None
    pa["criteria_inputs"] = criteria_inputs
    pa["clinical_criteria_score"] = clinical_criteria_gate(criteria_inputs)
    db.touch(pa)
    bundle = bundle_of_preauth(db, pa)
    recompute_bundle(db, bundle)
    return ok(serialize("preauthorizations", pa))