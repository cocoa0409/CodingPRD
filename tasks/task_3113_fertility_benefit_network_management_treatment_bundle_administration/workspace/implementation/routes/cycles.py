"""Treatment cycles: creation and the explicit clinical pipeline (PRD 3.6)."""

from datetime import timedelta
from flask import request

from body import body, opt, require, require_int
from bp import api
from clock import PREGNANCY_TEST_DAYS, parse_dt
from db import db
from errors import APIError
from helpers import (
    bundle_of_cycle,
    bundle_of_plan,
    active_contract_rate,
    contracts_of_clinic,
    employer_of_bundle,
    member_of_plan,
    preauth_of_cycle,
    plan_of_cycle,
    recompute_bundle,
    recompute_member,
    recompute_plan,
    recompute_preauth_consumption,
)
from listing import apply_filters, ordered, paginate
from lookups import (
    treatment_cycle as cycle_lookup,
    treatment_plan as plan_lookup,
)
from middleware import resolve_actor
from response import ok, created
from serializers import serialize

CYCLE_CREATABLE_PLAN_STATES = ("CLINIC_SELECTED", "AUTHORIZATION_PENDING", "IN_PROGRESS")
CANCELLABLE_STATES = ("SCHEDULED", "STIMULATION", "RETRIEVAL", "FERTILIZATION", "TRANSFER")


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------

@api.route("/treatment-plans/<plan_id>/treatment-cycles", methods=["POST"])
def create_treatment_cycle(plan_id):
    resolve_actor()
    plan = plan_lookup(plan_id)

    # Priority 5: the declared-state rule on the plan.
    if plan["plan_status"] not in CYCLE_CREATABLE_PLAN_STATES:
        raise APIError("ERR_INVALID_STATE", "The plan does not admit a new cycle.")

    data = body()
    preauth_id = require(data, "preauthorization_id")
    retrieval_date = require(data, "retrieval_date")
    transfer_date = require(data, "transfer_date")
    embryos_transferred = require_int(data, "embryos_transferred")

    # Priority 6: every foreign key supplied in the body must resolve.
    pa = db.find("preauthorizations", preauth_id)
    if pa is None or pa["treatment_plan_id"] != plan["id"]:
        raise APIError("ERR_NOT_FOUND", "The preauthorization_id does not resolve on this plan.")

    member = member_of_plan(db, plan)
    bundle = bundle_of_plan(db, plan)

    # The authorization must be approved to admit a cycle.
    if pa["review_status"] != "APPROVED":
        raise APIError("ERR_INVALID_STATE", "The named authorization is not APPROVED.")

    # Priority 8: the authorization's validity window must cover the service instant.
    start = parse_dt(pa["effective_from"])
    end = parse_dt(pa["effective_to"])
    service = parse_dt(retrieval_date)
    if start is None or end is None:
        raise APIError("ERR_PREAUTH_WINDOW_OUTSIDE_COVERAGE", "The authorization carries no validity window.")
    # The window must cover the requested service instant; a cycle is frequently
    # scheduled for a date still ahead of the logical clock, so the clock itself is
    # not part of the test.
    if service < start or service >= end:
        raise APIError("ERR_PREAUTH_WINDOW_OUTSIDE_COVERAGE",
                       "The authorization's validity window does not cover the requested service instant.")

    # Priority 9: the clinic's active contract must not be frozen.
    contract = _covering_contract(plan.get("clinic_id"))
    if contract is not None and contract["contracting_status"] == "FROZEN":
        raise APIError("ERR_CLINIC_CONTRACT_FROZEN", "The clinic's active contract is FROZEN.")

    # Priority 10: the sponsoring account must be ACTIVE and the bundle live.
    employer = employer_of_bundle(db, bundle)
    if employer is None or employer["account_status"] != "ACTIVE":
        raise APIError("ERR_BENEFIT_INACTIVE", "The sponsoring account is not ACTIVE.")

    # Priority 12: the plan's spacing rule and any reserved retention window.
    _check_spacing_and_slots(plan, member, retrieval_date)

    row = db.common()
    row.update({
        "_collection": "treatment_cycles",
        "_creator_user_id": request.headers.get("X-User-ID") or "",
        "treatment_plan_id": plan["id"],
        "preauthorization_id": pa["id"],
        "member_id": member["id"],
        "cycle_index": 0,
        "cycle_status": "SCHEDULED",
        "retrieval_date": parse_dt(retrieval_date),
        "transfer_date": parse_dt(transfer_date),
        "embryos_transferred": embryos_transferred,
        "consumption_marker": "UNCONSUMED",
    })
    db.add(row)
    _renumber_cycles(db, plan)
    db.touch(plan)
    return created(serialize("treatment_cycles", row))


def _renumber_cycles(store, plan):
    """One-based dense ordinal by created_at ASC, creator ASC, retrieval_date ASC."""
    rows = [c for c in store.all("treatment_cycles") if c["treatment_plan_id"] == plan["id"]]
    rows.sort(key=lambda c: (
        store.created_key(c),
        c.get("_creator_user_id") or "",
        parse_dt(c.get("retrieval_date")) or store.created_key(c),
    ))
    for index, cycle in enumerate(rows, start=1):
        cycle["cycle_index"] = index
    return rows


def _check_spacing_and_slots(plan, member, retrieval_instant):
    """The plan's minimum inter-cycle spacing and the member's reserved routes."""
    now = db.now()
    min_days = plan.get("min_inter_cycle_days") or 0
    prior_transfers = []
    for cycle in db.all("treatment_cycles"):
        if cycle["treatment_plan_id"] != plan["id"]:
            continue
        # Only a transfer that actually happened anchors the spacing buffer.
        if cycle["cycle_status"] not in ("TRANSFER", "OUTCOME_PENDING", "OUTCOME_RECORDED"):
            continue
        if cycle.get("transfer_date"):
            prior_transfers.append(parse_dt(cycle["transfer_date"]))
    if prior_transfers:
        latest = max(prior_transfers)
        if now < latest + timedelta(days=min_days):
            raise APIError("ERR_CYCLE_SLOT_OVERLAP",
                           "The plan's minimum inter-cycle spacing has not elapsed.")

    from clock import STORAGE_RETENTION_DAYS
    for route in db.all("surrender_routes"):
        if route["member_id"] != member["id"] or route["route_status"] != "ROUTED":
            continue
        start = parse_dt(route["route_from"])
        end = parse_dt(route["route_to"]) + timedelta(days=STORAGE_RETENTION_DAYS)
        if start <= now < end:
            raise APIError("ERR_CYCLE_SLOT_OVERLAP",
                           "The cycle would fall inside a reserved retention window.")


def _covering_contract(clinic_id):
    if not clinic_id:
        return None
    now = db.now()
    for contract in contracts_of_clinic(db, clinic_id, ("ACTIVE", "FROZEN")):
        start = parse_dt(contract["effective_from"])
        end = parse_dt(contract["effective_to"])
        if start <= now < end:
            return contract
    return None


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

@api.route("/treatment-cycles/<cycle_id>", methods=["GET"])
def get_treatment_cycle(cycle_id):
    resolve_actor()
    row = cycle_lookup(cycle_id)
    return ok(serialize("treatment_cycles", row))


@api.route("/treatment-cycles", methods=["GET"])
def list_treatment_cycles():
    resolve_actor()
    rows = ordered(db.all("treatment_cycles"))
    rows = apply_filters(rows, {
        "treatment_plan_id": "treatment_plan_id",
        "preauthorization_id": "preauthorization_id",
        "member_id": "member_id",
        "cycle_status": "cycle_status",
    })
    rows.sort(key=lambda c: (c.get("cycle_index") or 0, db.created_key(c)))
    return paginate(rows, "treatment_cycles")


# --------------------------------------------------------------------------
# The explicit pipeline
# --------------------------------------------------------------------------

def _start_stimulation(cycle):
    if cycle["cycle_status"] != "SCHEDULED":
        raise APIError("ERR_INVALID_STATE", "The cycle is not SCHEDULED.")
    pa = preauth_of_cycle(db, cycle)
    if pa is None or pa["review_status"] != "APPROVED":
        raise APIError("ERR_INVALID_STATE", "The cycle's authorization is not APPROVED.")
    start = parse_dt(pa["effective_from"])
    end = parse_dt(pa["effective_to"])
    if not (start <= db.now() < end):
        raise APIError("ERR_PREAUTH_WINDOW_OUTSIDE_COVERAGE",
                       "The logical clock is outside the authorization's validity window.")
    for other in db.all("treatment_cycles"):
        if other["treatment_plan_id"] == cycle["treatment_plan_id"] and other["id"] != cycle["id"]:
            if other["cycle_status"] == "STIMULATION":
                raise APIError("ERR_INVALID_STATE", "Another cycle of the plan is already in STIMULATION.")
    cycle["cycle_status"] = "STIMULATION"
    db.touch(cycle)
    return cycle


def _record_retrieval(cycle):
    if cycle["cycle_status"] != "STIMULATION":
        raise APIError("ERR_INVALID_STATE", "The cycle is not STIMULATION.")
    for other in db.all("treatment_cycles"):
        if other["treatment_plan_id"] != cycle["treatment_plan_id"] or other["id"] == cycle["id"]:
            continue
        if (other.get("cycle_index") or 0) < (cycle.get("cycle_index") or 0):
            if other["cycle_status"] not in ("OUTCOME_RECORDED", "CANCELLED"):
                raise APIError("ERR_SEQUENCE_OUT_OF_ORDER",
                               "An earlier cycle of the plan has not reached a terminal state.")
    cycle["cycle_status"] = "RETRIEVAL"
    db.touch(cycle)
    return cycle


def _record_fertilization(cycle):
    if cycle["cycle_status"] != "RETRIEVAL":
        raise APIError("ERR_INVALID_STATE", "The cycle is not RETRIEVAL.")
    cycle["cycle_status"] = "FERTILIZATION"
    db.touch(cycle)
    return cycle


def _record_transfer(cycle, transfer_date, embryos_transferred):
    if cycle["cycle_status"] != "FERTILIZATION":
        raise APIError("ERR_INVALID_STATE", "The cycle is not FERTILIZATION.")
    bundle = bundle_of_cycle(db, cycle)
    limit = bundle.get("max_transfers_per_cycle") if bundle else None
    if embryos_transferred is None or embryos_transferred < 1:
        raise APIError("ERR_INVALID_REQUEST", "embryos_transferred must be at least 1.")
    if limit is not None and embryos_transferred > limit:
        raise APIError("ERR_INVALID_REQUEST", "embryos_transferred exceeds max_transfers_per_cycle.")
    if transfer_date is not None:
        cycle["transfer_date"] = parse_dt(transfer_date)
    cycle["embryos_transferred"] = embryos_transferred
    cycle["cycle_status"] = "TRANSFER"
    db.touch(cycle)
    return cycle


def _promote_outcome_pending(cycle):
    """A TRANSFER cycle whose pregnancy-test instant has arrived moves on."""
    if cycle["cycle_status"] != "TRANSFER" or not cycle.get("transfer_date"):
        return
    if db.now() >= parse_dt(cycle["transfer_date"]) + timedelta(days=PREGNANCY_TEST_DAYS):
        cycle["cycle_status"] = "OUTCOME_PENDING"
        db.touch(cycle)


def _record_outcome(cycle, payload):
    _promote_outcome_pending(cycle)
    if cycle["cycle_status"] != "OUTCOME_PENDING":
        raise APIError("ERR_INVALID_STATE", "The cycle is not OUTCOME_PENDING.")

    cycle["cycle_status"] = "OUTCOME_RECORDED"
    cycle["consumption_marker"] = "CONSUMED"
    db.touch(cycle)

    pa = preauth_of_cycle(db, cycle)
    recompute_preauth_consumption(db, pa)
    db.touch(pa)

    plan = plan_of_cycle(db, cycle)
    recompute_plan(db, plan)
    db.touch(plan)

    member = db.find("members", cycle["member_id"])
    recompute_member(db, member)

    bundle = bundle_of_cycle(db, cycle)
    recompute_bundle(db, bundle)
    _exhaustion_cascade(db, bundle)
    recompute_bundle(db, bundle)
    return cycle


def _exhaustion_cascade(store, bundle):
    """When a bundle reads EXHAUSTED, deny its pending authorizations."""
    if bundle is None or bundle["bundle_status"] != "EXHAUSTED":
        return
    plan_ids = {p["id"] for p in store.all("treatment_plans")
                if p["bundle_entitlement_id"] == bundle["id"]}
    for pa in store.all("preauthorizations"):
        if pa["treatment_plan_id"] in plan_ids and pa["review_status"] in ("SUBMITTED", "CLINICAL_REVIEW"):
            pa["review_status"] = "DENIED"
            pa["denial_reason_code"] = "BUNDLE_EXHAUSTED"
            store.touch(pa)
    for plan in store.all("treatment_plans"):
        if plan["id"] in plan_ids and plan.get("clinic_id"):
            rate = active_contract_rate(store, plan["clinic_id"], bundle["bundle_type"])
            if rate is not None:
                from calculations import clinic_bundle_price
                new_price = clinic_bundle_price(rate, bundle.get("copay_max"))
                if new_price != plan.get("selected_bundle_price_cents"):
                    plan["selected_bundle_price_cents"] = new_price
                    store.touch(plan)


@api.route("/treatment-cycles/<cycle_id>/start-stimulation", methods=["POST"])
def start_stimulation(cycle_id):
    resolve_actor()
    cycle = cycle_lookup(cycle_id)
    _start_stimulation(cycle)
    return ok(serialize("treatment_cycles", cycle))


@api.route("/treatment-cycles/<cycle_id>/record-retrieval", methods=["POST"])
def record_retrieval(cycle_id):
    resolve_actor()
    cycle = cycle_lookup(cycle_id)
    _record_retrieval(cycle)
    return ok(serialize("treatment_cycles", cycle))


@api.route("/treatment-cycles/<cycle_id>/record-fertilization", methods=["POST"])
def record_fertilization(cycle_id):
    resolve_actor()
    cycle = cycle_lookup(cycle_id)
    _record_fertilization(cycle)
    return ok(serialize("treatment_cycles", cycle))


@api.route("/treatment-cycles/<cycle_id>/record-transfer", methods=["POST"])
def record_transfer(cycle_id):
    resolve_actor()
    cycle = cycle_lookup(cycle_id)
    data = body()
    transfer_date = data.get("transfer_date")
    embryos_transferred = data.get("embryos_transferred")
    if embryos_transferred is None:
        raise APIError("ERR_INVALID_REQUEST", "The required input 'embryos_transferred' is missing.")
    _record_transfer(cycle, transfer_date, embryos_transferred)
    return ok(serialize("treatment_cycles", cycle))


@api.route("/treatment-cycles/<cycle_id>/record-outcome", methods=["POST"])
def record_outcome(cycle_id):
    resolve_actor()
    cycle = cycle_lookup(cycle_id)
    data = body()
    payload = {
        "live_birth": bool(opt(data, "live_birth", False)),
        "births_count": opt(data, "births_count", 0),
        "multiple_birth": bool(opt(data, "multiple_birth", False)),
        "gestational_weeks": opt(data, "gestational_weeks", 0),
    }
    _record_outcome(cycle, payload)
    return ok(serialize("treatment_cycles", cycle))


@api.route("/treatment-cycles/<cycle_id>/cancel", methods=["POST"])
def cancel_cycle(cycle_id):
    resolve_actor()
    cycle = cycle_lookup(cycle_id)
    if cycle["cycle_status"] not in CANCELLABLE_STATES:
        raise APIError("ERR_INVALID_STATE", "The cycle may not be cancelled from its current state.")

    cycle["cycle_status"] = "CANCELLED"
    cycle["consumption_marker"] = "UNCONSUMED"
    db.touch(cycle)

    bundle = bundle_of_cycle(db, cycle)
    if bundle is not None:
        recompute_bundle(db, bundle)
    pa = preauth_of_cycle(db, cycle)
    if pa is not None:
        recompute_preauth_consumption(db, pa)
    return ok(serialize("treatment_cycles", cycle))