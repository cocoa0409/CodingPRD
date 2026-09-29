from flask import Blueprint, g

import cascades
import rating
import store
import views
from common import (API_PREFIX, body, clock_date, clock_now, envelope_list,
                    envelope_object, fail, get_date, get_enum, get_int, get_str,
                    own_policy, paginate, parse_pagination, require)

bp = Blueprint("policies", __name__)


@bp.post(API_PREFIX + "/policies")
def create_policy():
    require("Underwriter")
    b = body()
    policyholder_name = get_str(b, "policyholder_name", max_len=120)
    territory_code = get_enum(b, "territory_code", rating.TERRITORIES)
    effective_date = get_date(b, "effective_date")
    expiration_date = get_date(b, "expiration_date")
    if expiration_date <= effective_date:
        fail("ERR_INVALID_REQUEST", "expiration_date must be after effective_date")
    minimum_premium_cents = get_int(b, "minimum_premium_cents", required=False,
                                    minimum=0, default=250000)
    row = store.make({
        "policyholder_name": policyholder_name,
        "territory_code": territory_code,
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "term_days": (expiration_date - effective_date).days,
        "minimum_premium_cents": minimum_premium_cents,
        "status": "DRAFT",
        "referral_required": False,
        "referral_status": "NOT_REQUIRED",
        "referred_by_user_id": None,
        "referral_decided_by_user_id": None,
        "sum_of_part_premiums_cents": 0,
        "scheduled_basis_premium_cents": 0,
        "blanket_basis_premium_cents": 0,
        "written_premium_cents": 0,
        "premium_balance_cents": 0,
        "incurred_loss_cents": 0,
        "total_insured_value_cents": 0,
        "occupancy_termination_count": 0,
        "cancellation_reason": None,
        "cancel_effective_date": None,
        "quoted_at": None,
        "bound_at": None,
        "in_force_at": None,
    })
    store.policies[row["id"]] = row
    return envelope_object(views.policy_view(row), 201)


@bp.get(API_PREFIX + "/policies/<policy_id>")
def get_policy(policy_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    own_policy(policy_id)
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    return envelope_object(views.policy_view(policy), 200)


@bp.get(API_PREFIX + "/policies/<policy_id>/premium-summary")
def policy_premium_summary(policy_id):
    require("Underwriter", "UnderwritingManager", "Policyholder")
    own_policy(policy_id)
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    roll = rating.policy_rollup(policy)
    data = {
        "sum_of_part_premiums_cents": roll["sum_of_part_premiums_cents"],
        "expense_load_bp": roll["expense_load_bp"],
        "written_premium_cents": roll["written_premium_cents"],
        "scheduled_basis_premium_cents": roll["scheduled_basis_premium_cents"],
        "blanket_basis_premium_cents": roll["blanket_basis_premium_cents"],
        "minimum_premium_applied": roll["minimum_premium_applied"],
        "total_insured_value_cents": roll["total_insured_value_cents"],
        "premium_balance_cents": views.premium_balance(policy),
        "incurred_loss_cents": views.incurred_loss(policy),
        "referral_required": roll["referral_required"],
    }
    return envelope_object(data, 200)


@bp.get(API_PREFIX + "/policies/<policy_id>/coverage-parts")
def list_policy_parts(policy_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    own_policy(policy_id)
    store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    limit, offset = parse_pagination()
    from flask import request
    part_type = request.args.get("part_type")
    rows = store.parts_of_policy(policy_id)
    if part_type is not None:
        rows = [r for r in rows if r["part_type"] == part_type]
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.part_view(r) for r in page], limit, offset, total)


@bp.get(API_PREFIX + "/policies/<policy_id>/ledger-entries")
def list_policy_entries(policy_id):
    require("Underwriter", "UnderwritingManager", "Policyholder")
    own_policy(policy_id)
    store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    limit, offset = parse_pagination()
    from flask import request
    ledger = request.args.get("ledger")
    entry_type = request.args.get("entry_type")
    rows = store.entries_of_policy(policy_id)
    if ledger is not None:
        rows = [r for r in rows if r["ledger"] == ledger]
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.entry_view(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + "/policies/<policy_id>/coverage-parts")
def create_coverage_part(policy_id):
    require("Underwriter")
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    b = body()
    part_type = get_enum(b, "part_type", rating.PART_TYPES)
    valuation_basis = get_enum(b, "valuation_basis", rating.VALUATION_BASES)
    rating_basis = get_enum(b, "rating_basis", ("SCHEDULED", "BLANKET"),
                            required=False, default="SCHEDULED")
    deductible_cents = get_int(b, "deductible_cents", required=False, minimum=0,
                               default=100000)
    aggregate_limit_cents = get_int(b, "aggregate_limit_cents", minimum=1)
    blanket_required = rating_basis == "BLANKET"
    blanket_limit_cents = get_int(b, "blanket_limit_cents", required=blanket_required,
                                 minimum=0)
    coinsurance_pct_bp = get_int(b, "coinsurance_pct_bp", required=False,
                                 minimum=5000, maximum=10000)
    rented = part_type == "RENTED_LEASED"
    per_item_limit_cents = get_int(b, "per_item_limit_cents", required=rented, minimum=0)
    loss_of_use_daily_limit_cents = get_int(b, "loss_of_use_daily_limit_cents",
                                           required=rented, minimum=0)
    loss_of_use_max_days = get_int(b, "loss_of_use_max_days", required=rented, minimum=1)
    transit = part_type == "TRANSIT"
    transit_owned_limit_cents = get_int(b, "transit_owned_limit_cents",
                                       required=transit, minimum=0)
    transit_hired_limit_cents = get_int(b, "transit_hired_limit_cents",
                                       required=transit, minimum=0)
    catastrophe_limit_cents = get_int(b, "catastrophe_limit_cents",
                                      required=transit, minimum=0)
    reporting = part_type == "REPORTING_FORM"
    reporting_frequency = get_enum(b, "reporting_frequency", ("MONTHLY", "QUARTERLY"),
                                   required=reporting)
    reporting_annual_rate_bp = get_int(b, "reporting_annual_rate_bp",
                                       required=reporting, minimum=0)
    reporting_limit_cents = get_int(b, "reporting_limit_cents", required=reporting,
                                    minimum=0)
    if policy["status"] not in rating.MUTABLE_POLICY_STATUSES:
        fail("ERR_POLICY_NOT_MUTABLE", "Policy is %s" % policy["status"])
    row = store.make({
        "policy_id": policy_id,
        "part_type": part_type,
        "valuation_basis": valuation_basis,
        "rating_basis": rating_basis,
        "deductible_cents": deductible_cents,
        "blanket_limit_cents": blanket_limit_cents,
        "coinsurance_pct_bp": coinsurance_pct_bp,
        "per_item_limit_cents": per_item_limit_cents,
        "aggregate_limit_cents": aggregate_limit_cents,
        "aggregate_available_cents": aggregate_limit_cents,
        "aggregate_paid_net_cents": 0,
        "loss_of_use_daily_limit_cents": loss_of_use_daily_limit_cents,
        "loss_of_use_max_days": loss_of_use_max_days,
        "transit_owned_limit_cents": transit_owned_limit_cents,
        "transit_hired_limit_cents": transit_hired_limit_cents,
        "catastrophe_limit_cents": catastrophe_limit_cents,
        "reporting_frequency": reporting_frequency,
        "reporting_annual_rate_bp": reporting_annual_rate_bp,
        "reporting_limit_cents": reporting_limit_cents,
        "deposit_premium_cents": None,
        "earned_reported_premium_cents": 0,
        "latest_report_period_end_date": None,
        "rated_premium_cents": 0,
        "status": "ACTIVE",
    })
    row["_scheduled_variant_cents"] = 0
    row["_blanket_variant_cents"] = 0
    store.coverage_parts[row["id"]] = row
    # Adding a part is the one exposure-adding write that leaves the policy
    # version alone.
    return envelope_object(views.part_view(row), 201)


@bp.post(API_PREFIX + "/policies/<policy_id>/quote")
def quote_policy(policy_id):
    require("Underwriter")
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    if policy["status"] not in ("DRAFT", "QUOTED"):
        fail("ERR_POLICY_NOT_QUOTABLE", "Policy is %s" % policy["status"])
    parts = store.parts_of_policy(policy_id)
    if not any(p["status"] == "ACTIVE" for p in parts):
        fail("ERR_NO_RATABLE_COVERAGE",
             "Policy has no ACTIVE coverage part to rate")
    for part in parts:
        for item in store.items_of_part(part["id"]):
            if item["status"] in rating.ON_SCHEDULE_STATUSES:
                rating.apply_rating(item, rating.rate_equipment_item(item, policy))
    for part in parts:
        rating.recompute_part(part)
        if part["part_type"] == "REPORTING_FORM":
            part["deposit_premium_cents"] = part["rated_premium_cents"]
            store.touch(part)
    rating.reroll_policy(policy)
    policy["status"] = "QUOTED"
    policy["quoted_at"] = clock_now()
    store.touch(policy)
    return envelope_object(views.policy_view(policy), 200)


@bp.post(API_PREFIX + "/policies/<policy_id>/refer")
def refer_policy(policy_id):
    require("Underwriter")
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    b = body()
    get_str(b, "referral_note", required=False, max_len=500)
    if (policy["status"] != "QUOTED" or not policy["referral_required"]
            or policy["referral_status"] not in ("NOT_REQUIRED", "DECLINED")):
        fail("ERR_POLICY_NOT_REFERRABLE",
             "Policy is %s with referral_status %s and referral_required %s"
             % (policy["status"], policy["referral_status"],
                policy["referral_required"]))
    policy["status"] = "REFERRED"
    policy["referral_status"] = "PENDING"
    policy["referred_by_user_id"] = g.user_id
    store.touch(policy)
    return envelope_object(views.policy_view(policy), 200)


@bp.post(API_PREFIX + "/policies/<policy_id>/referral-decision")
def decide_referral(policy_id):
    require("UnderwritingManager")
    pending = store.maybe(store.policies, policy_id)
    if pending is not None and pending["referred_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The deciding manager must not be the referring underwriter")
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    b = body()
    decision = get_enum(b, "decision", ("APPROVE", "DECLINE"))
    if policy["status"] != "REFERRED" or policy["referral_status"] != "PENDING":
        fail("ERR_REFERRAL_NOT_PENDING",
             "Policy is %s with referral_status %s"
             % (policy["status"], policy["referral_status"]))
    policy["referral_decided_by_user_id"] = g.user_id
    if decision == "APPROVE":
        policy["referral_status"] = "APPROVED"
        policy["status"] = "QUOTED"
        store.touch(policy)
    else:
        policy["referral_status"] = "DECLINED"
        policy["status"] = "DECLINED"
        store.touch(policy)
        cascades.void_parts_and_floaters(policy, "CANCELLATION")
    return envelope_object(views.policy_view(policy), 200)


@bp.post(API_PREFIX + "/policies/<policy_id>/bind")
def bind_policy(policy_id):
    require("Underwriter")
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    if policy["status"] != "QUOTED" or policy["written_premium_cents"] <= 0:
        fail("ERR_POLICY_NOT_BINDABLE",
             "Policy is %s with written_premium_cents %s"
             % (policy["status"], policy["written_premium_cents"]))
    if policy["referral_required"] and policy["referral_status"] != "APPROVED":
        fail("ERR_REFERRAL_REQUIRED",
             "Referral clearance is required before binding")
    policy["status"] = "BOUND"
    policy["bound_at"] = clock_now()
    store.touch(policy)
    store.append_entry(policy_id, "INITIAL_PREMIUM", policy["written_premium_cents"],
                       "Initial written premium at bind",
                       effective_date=policy["effective_date"])
    return envelope_object(views.policy_view(policy), 200)


@bp.post(API_PREFIX + "/policies/<policy_id>/activate")
def activate_policy(policy_id):
    require("Underwriter")
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    today = clock_date()
    if (policy["status"] != "BOUND" or today < policy["effective_date"]
            or today >= policy["expiration_date"]):
        fail("ERR_POLICY_NOT_ACTIVATABLE",
             "Policy is %s and the clock reads %s" % (policy["status"], today))
    policy["status"] = "IN_FORCE"
    policy["in_force_at"] = clock_now()
    store.touch(policy)
    return envelope_object(views.policy_view(policy), 200)


@bp.post(API_PREFIX + "/policies/<policy_id>/cancel")
def cancel_policy(policy_id):
    require("UnderwritingManager")
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    b = body()
    reason = get_enum(b, "cancellation_reason",
                      ("INSURED_REQUEST", "NON_REPORTING", "UNDERWRITING"))
    cancel_date = get_date(b, "cancel_effective_date")
    if policy["status"] not in ("BOUND", "IN_FORCE", "SUSPENDED"):
        fail("ERR_POLICY_ALREADY_TERMINAL", "Policy is %s" % policy["status"])
    if (cancel_date < policy["effective_date"]
            or cancel_date >= policy["expiration_date"]):
        fail("ERR_CANCEL_DATE_OUTSIDE_TERM",
             "cancel_effective_date must be within the policy term")
    returned = rating.policy_cancellation_return(policy, cancel_date, reason)
    policy["cancellation_reason"] = reason
    policy["cancel_effective_date"] = cancel_date
    if returned != 0:
        store.append_entry(policy_id, "CANCELLATION_RETURN", -returned,
                           "Return of unearned premium on cancellation",
                           effective_date=cancel_date)
    for part in store.parts_of_policy(policy_id):
        for item in store.items_of_part(part["id"]):
            if item["status"] in rating.ON_SCHEDULE_STATUSES:
                item["status"] = "REMOVED"
                item["removed_at"] = clock_now()
                store.touch(item)
        for shipment in store.shipments_of_part(part["id"]):
            if shipment["status"] == "PLANNED":
                shipment["status"] = "CANCELLED"
                store.touch(shipment)
    cascades.void_parts_and_floaters(policy, "CANCELLATION")
    policy["status"] = "CANCELLED"
    store.touch(policy)
    return envelope_object(views.policy_view(policy), 200)
