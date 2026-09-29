from flask import Blueprint, g, request

import cascades
import rating
import store
import views
from common import (API_PREFIX, body, clock_now, envelope_list, envelope_object,
                    fail, get_date, get_enum, get_int, own_policy, paginate,
                    parse_pagination, require)

bp = Blueprint("claims", __name__)

CLAIM = "/claims/<claim_id>"

SUBJECT_FIELDS = ("equipment_item_id", "transit_shipment_id",
                  "installation_floater_id")


def _claim(claim_id):
    return store.find(store.claims, claim_id, "ERR_CLAIM_NOT_FOUND")


def _derive(claim, part):
    """Every claim figure re-derived from the pinned inputs, in the pinned order."""
    valuation = rating.claim_valuation_at_loss(claim)
    threshold = rating.constructive_total_loss_threshold(valuation)
    factor_bp = rating.underreporting_penalty_factor(claim, part)
    limit = rating.claim_limit(claim, part)
    lou_paid = rating.loss_of_use_paid(claim, part)
    repair, total = rating.claim_settlement_variants(claim, part, valuation,
                                                    factor_bp, limit, lou_paid)
    return {
        "valuation_at_loss_cents": valuation,
        "constructive_total_loss_threshold_cents": threshold,
        "underreporting_factor_bp": factor_bp,
        "claim_limit_cents": limit,
        "loss_of_use_paid_cents": lou_paid,
        "repair_basis_settlement_cents": repair,
        "total_loss_basis_settlement_cents": total,
    }


def _store_derived(claim, derived):
    for key in ("valuation_at_loss_cents", "constructive_total_loss_threshold_cents",
                "underreporting_factor_bp", "loss_of_use_paid_cents",
                "repair_basis_settlement_cents", "total_loss_basis_settlement_cents"):
        claim[key] = derived[key]


def _repair_selectable(claim, derived):
    if not claim.get("equipment_item_id"):
        return True
    estimate = claim.get("repair_estimate_cents")
    threshold = derived["constructive_total_loss_threshold_cents"]
    if estimate is None or threshold is None:
        return True
    return estimate < threshold


@bp.post(API_PREFIX + "/policies/<policy_id>/claims")
def report_claim(policy_id):
    require("Underwriter", "Policyholder")
    own_policy(policy_id)
    policy = store.find(store.policies, policy_id, "ERR_POLICY_NOT_FOUND")
    b = body()
    raw_part = b.get("coverage_part_id")
    part = None
    if raw_part is not None:
        part = (store.coverage_parts.get(raw_part) if isinstance(raw_part, str)
                else None)
        if part is None:
            fail("ERR_LOSS_SUBJECT_NOT_FOUND",
                 "Coverage part %s does not exist" % (raw_part,))
    subjects = {}
    for field in SUBJECT_FIELDS:
        raw = b.get(field)
        if raw is None:
            continue
        table = {"equipment_item_id": store.equipment_items,
                 "transit_shipment_id": store.transit_shipments,
                 "installation_floater_id": store.installation_floaters}[field]
        row = table.get(raw) if isinstance(raw, str) else None
        if row is None:
            fail("ERR_LOSS_SUBJECT_NOT_FOUND", "%s %s does not exist" % (field, raw))
        subjects[field] = row
    if part is None:
        fail("ERR_INVALID_REQUEST", "coverage_part_id is required")
    loss_date = get_date(b, "loss_date")
    loss_type = get_enum(b, "loss_type",
                         ("THEFT", "COLLISION", "FIRE", "WINDSTORM", "VANDALISM"))
    if len(subjects) > 1:
        fail("ERR_INVALID_REQUEST",
             "A claim names exactly one of %s" % ", ".join(SUBJECT_FIELDS))
    if not subjects and part["part_type"] != "REPORTING_FORM":
        fail("ERR_INVALID_REQUEST",
             "A claim on a %s part must name a loss subject" % part["part_type"])
    if (loss_date < policy["effective_date"]
            or loss_date >= policy["expiration_date"]):
        fail("ERR_LOSS_DATE_OUTSIDE_TERM",
             "loss_date must fall inside the policy term")
    if (policy["status"] == "CANCELLED" and policy["cancel_effective_date"]
            and loss_date > policy["cancel_effective_date"]):
        fail("ERR_LOSS_DATE_OUTSIDE_TERM",
             "loss_date must fall on or before cancel_effective_date")
    if part["policy_id"] != policy_id:
        fail("ERR_LOSS_SUBJECT_NOT_ON_PART",
             "Coverage part %s does not belong to policy %s" % (part["id"], policy_id))
    for field, row in subjects.items():
        if row["coverage_part_id"] != part["id"]:
            fail("ERR_LOSS_SUBJECT_NOT_ON_PART",
                 "%s does not belong to coverage part %s" % (field, part["id"]))
    row = store.make({
        "policy_id": policy_id,
        "coverage_part_id": part["id"],
        "equipment_item_id": b.get("equipment_item_id"),
        "transit_shipment_id": b.get("transit_shipment_id"),
        "installation_floater_id": b.get("installation_floater_id"),
        "loss_date": loss_date,
        "loss_type": loss_type,
        "repair_estimate_cents": None,
        "actual_value_at_loss_cents": None,
        "valuation_at_loss_cents": None,
        "constructive_total_loss_threshold_cents": None,
        "underreporting_factor_bp": 10000,
        "loss_of_use_days_claimed": 0,
        "loss_of_use_paid_cents": 0,
        "repair_basis_settlement_cents": None,
        "total_loss_basis_settlement_cents": None,
        "adjustment_basis": None,
        "settlement_amount_cents": None,
        "settlement_paid_cents": None,
        "salvage_proceeds_cents": None,
        "salvage_credit_cents": 0,
        "adjustment_status": "OPEN",
        "salvage_status": "NOT_APPLICABLE",
        "inspected_by_user_id": None,
        "declared_by_user_id": None,
        "settled_by_user_id": None,
    })
    store.claims[row["id"]] = row
    return envelope_object(views.claim_view(row), 201)


@bp.get(API_PREFIX + CLAIM)
def get_claim(claim_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    pending = store.maybe(store.claims, claim_id)
    own_policy(pending["policy_id"] if pending else None)
    claim = _claim(claim_id)
    return envelope_object(views.claim_view(claim), 200)


@bp.get(API_PREFIX + "/claims")
def list_claims():
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster")
    limit, offset = parse_pagination()
    rows = store.all_of(
        store.claims,
        policy_id=request.args.get("policy_id"),
        coverage_part_id=request.args.get("coverage_part_id"),
        equipment_item_id=request.args.get("equipment_item_id"),
        transit_shipment_id=request.args.get("transit_shipment_id"),
        installation_floater_id=request.args.get("installation_floater_id"),
        adjustment_status=request.args.get("adjustment_status"),
    )
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.claim_view(r) for r in page], limit, offset, total)


@bp.get(API_PREFIX + CLAIM + "/ledger-entries")
def list_claim_entries(claim_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster")
    claim = _claim(claim_id)
    limit, offset = parse_pagination()
    entry_type = request.args.get("entry_type")
    rows = [e for e in store.entries_of_policy(claim["policy_id"])
            if e.get("claim_id") == claim_id]
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.entry_view(r) for r in page], limit, offset, total)


@bp.get(API_PREFIX + CLAIM + "/settlement-worksheet")
def settlement_worksheet(claim_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster")
    claim = _claim(claim_id)
    part = store.coverage_parts[claim["coverage_part_id"]]
    derived = _derive(claim, part)
    estimate = claim.get("repair_estimate_cents")
    threshold = derived["constructive_total_loss_threshold_cents"]
    reached = (estimate is not None and threshold is not None
               and estimate >= threshold)
    return envelope_object({
        "valuation_at_loss_cents": derived["valuation_at_loss_cents"],
        "constructive_total_loss_threshold_cents": threshold,
        "constructive_total_loss_reached": reached,
        "underreporting_factor_bp": derived["underreporting_factor_bp"],
        "claim_limit_cents": derived["claim_limit_cents"],
        "deductible_cents": part.get("deductible_cents") or 0,
        "loss_of_use_paid_cents": derived["loss_of_use_paid_cents"],
        "repair_basis_settlement_cents": derived["repair_basis_settlement_cents"],
        "total_loss_basis_settlement_cents": derived["total_loss_basis_settlement_cents"],
        "repair_basis_selectable": _repair_selectable(claim, derived),
        "aggregate_available_cents": views.aggregate_available(part),
    }, 200)


@bp.post(API_PREFIX + CLAIM + "/inspect")
def inspect_claim(claim_id):
    require("ClaimsAdjuster")
    claim = _claim(claim_id)
    b = body()
    repair_estimate_cents = get_int(b, "repair_estimate_cents", minimum=0)
    actual_value_at_loss_cents = get_int(b, "actual_value_at_loss_cents", minimum=0)
    if claim["adjustment_status"] != "OPEN":
        fail("ERR_CLAIM_NOT_IN_REQUIRED_STATE",
             "Claim adjustment_status is %s" % claim["adjustment_status"])
    part = store.coverage_parts[claim["coverage_part_id"]]
    claim["repair_estimate_cents"] = repair_estimate_cents
    claim["actual_value_at_loss_cents"] = actual_value_at_loss_cents
    claim["inspected_by_user_id"] = g.user_id
    claim["adjustment_status"] = "INSPECTED"
    # Four derivations, in the pinned order: valuation, CTL threshold, the
    # underreporting factor, then both settlement variants.
    _store_derived(claim, _derive(claim, part))
    store.touch(claim)
    return envelope_object(views.claim_view(claim), 200)


@bp.post(API_PREFIX + CLAIM + "/adjust")
def adjust_claim(claim_id):
    require("ClaimsAdjuster")
    claim = _claim(claim_id)
    b = body()
    basis = get_enum(b, "adjustment_basis", ("REPAIR", "TOTAL_LOSS"))
    days = get_int(b, "loss_of_use_days_claimed", required=False, minimum=0, default=0)
    if claim["adjustment_status"] != "INSPECTED":
        fail("ERR_CLAIM_NOT_IN_REQUIRED_STATE",
             "Claim adjustment_status is %s" % claim["adjustment_status"])
    part = store.coverage_parts[claim["coverage_part_id"]]
    if days > 0 and not rating.loss_of_use_eligible(claim, part):
        fail("ERR_LOSS_OF_USE_NOT_COVERED",
             "Loss of use is only payable on a rented or leased unit of a "
             "RENTED_LEASED part")
    derived = _derive(claim, part)
    if basis == "REPAIR" and not _repair_selectable(claim, derived):
        fail("ERR_CONSTRUCTIVE_TOTAL_LOSS",
             "The repair estimate has reached the constructive-total-loss threshold")
    claim["adjustment_basis"] = basis
    claim["declared_by_user_id"] = g.user_id
    if basis == "REPAIR":
        claim["loss_of_use_days_claimed"] = days
        _store_derived(claim, _derive(claim, part))
        claim["settlement_amount_cents"] = claim["repair_basis_settlement_cents"]
        claim["adjustment_status"] = "REPAIR_APPROVED"
    else:
        _store_derived(claim, _derive(claim, part))
        # A total loss never pays a loss-of-use extension.
        claim["loss_of_use_paid_cents"] = 0
        claim["settlement_amount_cents"] = claim["total_loss_basis_settlement_cents"]
        claim["adjustment_status"] = "TOTAL_LOSS_DECLARED"
        claim["salvage_status"] = "PENDING"
    store.touch(claim)
    return envelope_object(views.claim_view(claim), 200)


@bp.post(API_PREFIX + CLAIM + "/settle")
def settle_claim(claim_id):
    require("UnderwritingManager")
    pending = store.maybe(store.claims, claim_id)
    if pending is not None and pending["declared_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The settling manager must not be the adjuster who declared the basis")
    claim = _claim(claim_id)
    if claim["adjustment_status"] not in ("REPAIR_APPROVED", "TOTAL_LOSS_DECLARED"):
        fail("ERR_CLAIM_NOT_IN_REQUIRED_STATE",
             "Claim adjustment_status is %s" % claim["adjustment_status"])
    part = store.coverage_parts[claim["coverage_part_id"]]
    policy = store.policies[claim["policy_id"]]
    for report in store.reports_of_part(part["id"]):
        if report["status"] == "DELINQUENT":
            fail("ERR_REPORTING_DELINQUENT",
                 "Coverage part %s carries a delinquent value report" % part["id"])
    amount = claim["settlement_amount_cents"] or 0
    available = views.aggregate_available(part)
    if amount > available:
        fail("ERR_AGGREGATE_LIMIT_EXHAUSTED",
             "settlement_amount_cents %s exceeds the remaining aggregate %s"
             % (amount, available))
    # Hop one: the settlement bookkeeping.
    claim["settlement_paid_cents"] = amount
    claim["settled_by_user_id"] = g.user_id
    basis = claim["adjustment_basis"]
    claim["adjustment_status"] = "SETTLED"
    store.append_entry(policy["id"], "CLAIM_SETTLEMENT", amount,
                       "Settlement of claim %s" % claim_id, claim_id=claim_id)
    store.touch(part)
    store.touch(claim)
    if basis == "REPAIR":
        # The salvage axis is dormant, so the join closes inside this call.
        claim["adjustment_status"] = "CLOSED"
        store.touch(claim)
        return envelope_object(views.claim_view(claim), 200)
    kind, subject = rating.claim_subject(claim)
    # Hop two: the loss subject leaves the risk.
    if kind == "equipment_item" and subject is not None:
        subject["status"] = "TOTALED"
        subject["removed_at"] = clock_now()
        store.touch(subject)
    elif kind == "transit_shipment" and subject is not None:
        if subject["status"] == "IN_TRANSIT":
            subject["status"] = "LOST"
            store.touch(subject)
            vehicle = store.vehicles.get(subject["vehicle_id"])
            if vehicle is not None:
                store.touch(vehicle)
    # Hop three: for equipment only, the part re-develops over what is left.
    if kind == "equipment_item" and subject is not None:
        rating.recompute_part(part)
        cascades.prorated_entry(
            policy, -(subject["rated_premium_cents"] or 0),
            "Endorsement: total loss of equipment item %s" % subject["id"],
            unconditional=True)
    # Hop four: the policy roll-up.
    rating.reroll_policy(policy)
    return envelope_object(views.claim_view(claim), 200)


@bp.post(API_PREFIX + CLAIM + "/salvage-recovery")
def record_salvage(claim_id):
    require("ClaimsAdjuster")
    claim = _claim(claim_id)
    b = body()
    proceeds = get_int(b, "salvage_proceeds_cents", minimum=0)
    if (claim["adjustment_status"] != "SETTLED"
            or claim["salvage_status"] != "PENDING"):
        fail("ERR_CLAIM_NOT_SETTLED",
             "Claim is %s with salvage_status %s"
             % (claim["adjustment_status"], claim["salvage_status"]))
    part = store.coverage_parts[claim["coverage_part_id"]]
    claim["salvage_proceeds_cents"] = proceeds
    if proceeds > 0:
        credit = min(proceeds, claim["settlement_paid_cents"] or 0)
        claim["salvage_credit_cents"] = credit
        claim["salvage_status"] = "RECOVERED"
        if credit:
            store.append_entry(claim["policy_id"], "SALVAGE_RECOVERY", -credit,
                               "Salvage recovery on claim %s" % claim_id,
                               claim_id=claim_id)
        store.touch(part)
    else:
        # A waived recovery leaves the consumed capacity consumed.
        claim["salvage_credit_cents"] = 0
        claim["salvage_status"] = "WAIVED"
    claim["adjustment_status"] = "CLOSED"
    store.touch(claim)
    return envelope_object(views.claim_view(claim), 200)
