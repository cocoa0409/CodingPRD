"""Claims, validation, disputes, compliance reviews, close-period and the clock."""

from flask import Blueprint

from authz import endpoint, find, require_member_scope, resolve
from envelope import created, ok
from errors import ApiError
from money import VARIANCE_TOLERANCE_BPS, floor_bps, round_half_up_div
from pageutil import paged
from routes_reference import _filtered
from serializers import dump
from shapes import Date, Enum, Instant, Int, Str, parse_body, raw_body
from store import (date_of_instant, days_between, db, new_immutable_record,
                   new_record, touch)
from svc_clock import set_clock
from svc_close import accruals_of_deal_period, close_period
from svc_common import batches_blocking_period, tier_of_member
from svc_compliance import apply_breach, apply_deal_loss, compute_review
from svc_savings import savings_report

bp = Blueprint("rebate", __name__)

CLAIM_ROLES = ("GpoAdmin", "RebateAnalyst", "DisputeArbiter", "ManufacturerRep",
               "MemberOperator")
ACCRUAL_ROLES = ("GpoAdmin", "RebateAnalyst", "DisputeArbiter", "MemberOperator")
REASON_CODES = ("RATE_MISMATCH", "UNITS_MISMATCH", "ITEM_MISMATCH",
                "TIER_MISMATCH")


def _require_no_unaccrued_batches(period_start, period_end):
    """Ladder priority 37 - the underlying purchase data must be processed."""
    if batches_blocking_period(period_start, period_end):
        raise ApiError("ERR_PERIOD_HAS_UNACCRUED_BATCHES")


# --------------------------------------------------------------------------
# manufacturer claims
# --------------------------------------------------------------------------

@bp.post("/manufacturer-claims")
@endpoint("ManufacturerRep", "GpoAdmin")
def create_claim(caller):
    body = parse_body([
        Str("deal_id"),
        Int("expected_deal_version"),
        Date("period_start"),
        Date("period_end"),
        Int("claimed_units", 0, None),
        Int("claimed_amount_cents", 0, None),
    ])
    deal = resolve("deal", body["deal_id"])                    # priority 9
    if body["expected_deal_version"] != deal["version"]:       # priority 10
        raise ApiError("ERR_STALE_PARENT_VERSION")
    if deal["status"] not in ("DRAFT", "ACTIVE"):              # priority 14
        raise ApiError("ERR_DEAL_NOT_OPEN_FOR_CHANGES")
    if body["period_end"] < body["period_start"]:              # priority 22
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")

    same_period = [c for c in db.claims.values()
                   if c["deal_id"] == deal["id"]
                   and c["period_start"] == body["period_start"]
                   and c["period_end"] == body["period_end"]]
    # priority 26 - a settled period cannot be reopened
    for claim in same_period:
        if claim["status"] == "RECONCILED":
            raise ApiError("ERR_CLAIM_PERIOD_ALREADY_RECONCILED")

    # Restatement: the incumbent live filing for the same period is superseded.
    for claim in same_period:
        if claim["status"] in ("SUBMITTED", "VARIANCE_FLAGGED"):
            claim["status"] = "SUPERSEDED"
            touch(claim)

    rec = new_record("ManufacturerClaim", {
        "deal_id": deal["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "claimed_units": body["claimed_units"],
        "claimed_amount_cents": body["claimed_amount_cents"],
        "accrued_amount_cents": 0,
        "variance_bps": 0,
        "status": "SUBMITTED",
        "reconciled_at": None,
    })
    db.claims[rec["id"]] = rec
    touch(deal)   # the owning deal's version advances by exactly 1 for the call
    return created(dump(rec))


@bp.get("/manufacturer-claims/<claim_id>")
@endpoint(*CLAIM_ROLES)
def get_claim(caller, claim_id):
    return ok(dump(resolve("claim", claim_id)))


@bp.get("/manufacturer-claims")
@endpoint(*CLAIM_ROLES)
def list_claims(caller):
    records = _filtered(db.claims.values(),
                        [("deal_id", "deal_id"), ("status", "status")])
    return paged(records)


@bp.post("/manufacturer-claims/<claim_id>/reconcile")
@endpoint("RebateAnalyst")
def reconcile_claim(caller, claim_id):
    claim = resolve("claim", claim_id)
    if claim["status"] != "SUBMITTED":                      # priority 11
        raise ApiError("ERR_INVALID_STATE")
    _require_no_unaccrued_batches(claim["period_start"], claim["period_end"])

    deal = db.deals.get(claim["deal_id"])
    accrued = 0
    for accrual in accruals_of_deal_period(
            deal, claim["period_start"], claim["period_end"],
            ("ACCRUED", "VALIDATED", "FLAGGED", "PAID")):
        accrued += accrual["gross_rebate_cents"]

    claimed = claim["claimed_amount_cents"]
    if accrued == 0 and claimed == 0:
        variance = 0
    elif accrued == 0:
        # The maximum possible disagreement stands in for an undefined ratio.
        variance = 10000
    else:
        variance = floor_bps(abs(claimed - accrued), accrued)

    claim["accrued_amount_cents"] = accrued
    claim["variance_bps"] = variance
    if variance <= VARIANCE_TOLERANCE_BPS:
        claim["status"] = "RECONCILED"
        claim["reconciled_at"] = db.now_iso()
    else:
        claim["status"] = "VARIANCE_FLAGGED"
    touch(claim)
    return ok(dump(claim))


# --------------------------------------------------------------------------
# accruals
# --------------------------------------------------------------------------

@bp.get("/accruals/<accrual_id>")
@endpoint(*ACCRUAL_ROLES)
def get_accrual(caller, accrual_id):
    return ok(dump(resolve("accrual", accrual_id)))


@bp.get("/accruals")
@endpoint(*ACCRUAL_ROLES)
def list_accruals(caller):
    records = _filtered(db.accruals.values(),
                        [("purchase_line_id", "purchase_line_id"),
                         ("member_id", "member_id"),
                         ("rate_card_id", "rate_card_id"),
                         ("status", "status"),
                         ("basis", "basis")])
    return paged(records)


@bp.post("/accruals/<accrual_id>/validate")
@endpoint("RebateAnalyst")
def validate_accrual(caller, accrual_id):
    accrual = resolve("accrual", accrual_id)
    body = parse_body([Str("claim_id")])
    claim = resolve("claim", body["claim_id"])          # priority 9

    if accrual["status"] != "ACCRUED":                  # priority 11
        raise ApiError("ERR_INVALID_STATE")
    if claim["status"] != "RECONCILED":                 # priority 16
        raise ApiError("ERR_CLAIM_NOT_RECONCILED")
    member = db.members.get(accrual["member_id"])
    if member is not None and member["payout_hold"]:    # priority 41
        raise ApiError("ERR_MEMBER_PAYOUT_HELD")

    if claim["claimed_units"] == 0:
        implied = 0
    else:
        implied = round_half_up_div(
            claim["claimed_amount_cents"] * accrual["accrued_cases"],
            claim["claimed_units"])

    gross = accrual["gross_rebate_cents"]
    if gross == 0:
        variance = 10000
    else:
        variance = floor_bps(abs(implied - gross), gross)

    # Validation is an assertion about agreement: no money field changes.
    accrual["status"] = ("VALIDATED" if variance <= VARIANCE_TOLERANCE_BPS
                         else "FLAGGED")
    accrual["validated_by_user_id"] = caller.user_id
    touch(accrual)
    return ok(dump(accrual))


# --------------------------------------------------------------------------
# period close
# --------------------------------------------------------------------------

@bp.post("/manufacturer-deals/<deal_id>/close-period")
@endpoint("GpoAdmin")
def close_deal_period(caller, deal_id):
    deal = resolve("deal", deal_id)
    body = parse_body([Date("period_start"), Date("period_end")])
    _require_no_unaccrued_batches(body["period_start"], body["period_end"])
    close_period(deal, body["period_start"], body["period_end"])
    return ok(dump(deal))


# --------------------------------------------------------------------------
# disputes
# --------------------------------------------------------------------------

def _batch_of_accrual(accrual):
    line = db.lines.get(accrual["purchase_line_id"])
    if line is None:
        return None
    return db.batches.get(line["purchase_batch_id"])


@bp.post("/disputes")
@endpoint("MemberOperator")
def create_dispute(caller):
    # priority 5 - compared against the cited accrual's member_id
    pre_accrual = find("accrual", raw_body().get("accrual_id"))
    if pre_accrual is not None:
        require_member_scope(caller, pre_accrual["member_id"])

    body = parse_body([
        Str("accrual_id"),
        Str("claim_id", required=False),
        Enum("reason_code", REASON_CODES),
        Int("disputed_amount_cents"),
    ])
    accrual = resolve("accrual", body["accrual_id"])     # priority 9
    if body["claim_id"] is not None:
        resolve("claim", body["claim_id"])

    if accrual["status"] in ("REVERSED", "PAID"):                     # priority 11
        raise ApiError("ERR_INVALID_STATE")
    member = db.members.get(accrual["member_id"])
    if member is None or member["enrollment_status"] != "ACTIVE":     # priority 12
        raise ApiError("ERR_MEMBER_NOT_ENROLLED")

    # priority 24 - the boundary day itself is still open
    tier = tier_of_member(member)
    elapsed = days_between(date_of_instant(accrual["created_at"]),
                           date_of_instant(db.now_iso()))
    if elapsed > tier["dispute_window_days"]:
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED")

    # priority 38 - no other live dispute on the same accrual
    for dispute in db.disputes.values():
        if (dispute["accrual_id"] == accrual["id"]
                and dispute["status"] in ("OPEN", "EVIDENCE_REQUESTED")):
            raise ApiError("ERR_DUPLICATE_OPEN_DISPUTE")

    # priority 40 - at least 1 cent and no more than the accrual's member share
    amount = body["disputed_amount_cents"]
    if amount < 1 or amount > accrual["member_share_cents"]:
        raise ApiError("ERR_DISPUTE_AMOUNT_EXCEEDS_SHARE")

    rec = new_record("RebateDispute", {
        "accrual_id": accrual["id"],
        "claim_id": body["claim_id"],
        "reason_code": body["reason_code"],
        "disputed_amount_cents": amount,
        "opened_by_user_id": caller.user_id,
        # Captured so that a rejected dispute is perfectly reversible.
        "accrual_status_before": accrual["status"],
        "evidence_round_count": 0,
        "status": "OPEN",
        "decided_by_user_id": None,
        "decision_note": None,
    })
    db.disputes[rec["id"]] = rec
    accrual["status"] = "DISPUTED"
    touch(accrual)
    return created(dump(rec))


@bp.get("/disputes/<dispute_id>")
@endpoint(*ACCRUAL_ROLES)
def get_dispute(caller, dispute_id):
    return ok(dump(resolve("dispute", dispute_id)))


@bp.get("/disputes")
@endpoint(*ACCRUAL_ROLES)
def list_disputes(caller):
    records = _filtered(db.disputes.values(),
                        [("accrual_id", "accrual_id"),
                         ("claim_id", "claim_id"),
                         ("status", "status"),
                         ("reason_code", "reason_code")])
    return paged(records)


@bp.post("/disputes/<dispute_id>/request-evidence")
@endpoint("DisputeArbiter")
def request_evidence(caller, dispute_id):
    dispute = resolve("dispute", dispute_id)
    if dispute["status"] != "OPEN":                       # priority 11
        raise ApiError("ERR_INVALID_STATE")
    # priority 18 - the bar is on the identifier, not the role name
    if caller.user_id == dispute["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    dispute["status"] = "EVIDENCE_REQUESTED"
    touch(dispute)
    return ok(dump(dispute))


@bp.post("/disputes/<dispute_id>/submit-evidence")
@endpoint("MemberOperator")
def submit_evidence(caller, dispute_id):
    dispute = resolve("dispute", dispute_id)              # priority 4
    accrual = db.accruals.get(dispute["accrual_id"])
    if accrual is not None:                               # priority 5
        require_member_scope(caller, accrual["member_id"])
    parse_body([Str("evidence_note", 1, 500)])
    if dispute["status"] != "EVIDENCE_REQUESTED":          # priority 11
        raise ApiError("ERR_INVALID_STATE")
    dispute["status"] = "OPEN"
    dispute["evidence_round_count"] += 1
    touch(dispute)
    return ok(dump(dispute))


@bp.post("/disputes/<dispute_id>/decide")
@endpoint("DisputeArbiter")
def decide_dispute(caller, dispute_id):
    dispute = resolve("dispute", dispute_id)
    body = parse_body([
        Enum("decision", ("UPHOLD", "REJECT")),
        Str("decision_note", 1, 500),
    ])
    if dispute["status"] != "OPEN":                        # priority 11
        raise ApiError("ERR_INVALID_STATE")

    accrual = db.accruals.get(dispute["accrual_id"])
    batch = _batch_of_accrual(accrual) if accrual else None
    # priority 18 - the full segregation-of-duties bar
    barred = [dispute["opened_by_user_id"]]
    if accrual is not None:
        barred.append(accrual["validated_by_user_id"])
    if batch is not None:
        barred.append(batch["accrued_by_user_id"])
    if caller.user_id in [b for b in barred if b is not None]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    dispute["decided_by_user_id"] = caller.user_id
    dispute["decision_note"] = body["decision_note"]

    if body["decision"] == "REJECT":
        # A pure state restore: not one money field or counter changes.
        dispute["status"] = "REJECTED"
        touch(dispute)
        if accrual is not None:
            accrual["status"] = dispute["accrual_status_before"]
            touch(accrual)
        return ok(dump(dispute))

    # hop 1 - the dispute is upheld
    dispute["status"] = "UPHELD"
    touch(dispute)
    if accrual is None:
        return ok(dump(dispute))

    # hop 2 - the accrual is reversed
    accrual["status"] = "REVERSED"
    accrual["reversal_reason"] = "DISPUTE_UPHELD"
    touch(accrual)

    # hop 3 - the member's ledger is retracted component by exact component
    member = db.members.get(accrual["member_id"])
    if member is None:
        return ok(dump(dispute))
    member["accrued_member_share_cents"] -= accrual["member_share_cents"]
    member["attributed_gpo_retention_cents"] -= accrual["gpo_retention_cents"]
    member["attributed_admin_fee_cents"] -= accrual["admin_fee_cents"]
    member["dispute_reversal_count"] += 1
    touch(member)

    # hop 4 - the posture hardens once, and only from CLEAR
    tier = tier_of_member(member)
    if (member["reconciliation_posture"] == "CLEAR" and tier is not None
            and member["dispute_reversal_count"] >= tier["reversal_posture_limit"]):
        member["reconciliation_posture"] = "RESTRICTED"
        member["payout_hold"] = True
        touch(member)
        member_line_ids = set(l["purchase_batch_id"] for l in db.lines.values()
                              if l["member_id"] == member["id"])
        for batch_id in member_line_ids:
            held = db.batches.get(batch_id)
            if held is not None and held["normalization_status"] == "ACCRUED":
                held["payout_hold"] = True
                touch(held)

    return ok(dump(dispute))


# --------------------------------------------------------------------------
# compliance reviews
# --------------------------------------------------------------------------

@bp.post("/compliance-reviews")
@endpoint("GpoAdmin", "RebateAnalyst")
def create_compliance_review(caller):
    body = parse_body([
        Str("member_id"),
        Str("deal_id"),
        Date("window_start"),
        Date("window_end"),
    ])
    member = resolve("member", body["member_id"])     # priority 9
    deal = resolve("deal", body["deal_id"])
    if body["window_end"] < body["window_start"]:     # priority 22
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")
    # priority 25 - a review of a period that has not finished happening would
    # understate purchasing by construction
    if body["window_end"] > date_of_instant(db.now_iso()):
        raise ApiError("ERR_REVIEW_WINDOW_IN_FUTURE")

    computed = compute_review(member, deal, body["window_start"],
                              body["window_end"])
    fields = {
        "member_id": member["id"],
        "deal_id": deal["id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
    }
    fields.update(computed)
    fields["triggered_deal_loss"] = computed["result"] == "DEAL_LOST"
    rec = new_immutable_record("ComplianceReview", fields)
    db.reviews[rec["id"]] = rec

    if computed["result"] == "BREACH":
        apply_breach(member)
    elif computed["result"] == "DEAL_LOST":
        apply_deal_loss(deal)
    return created(dump(rec))


@bp.get("/compliance-reviews/<review_id>")
@endpoint(*ACCRUAL_ROLES)
def get_compliance_review(caller, review_id):
    return ok(dump(resolve("review", review_id)))


@bp.get("/compliance-reviews")
@endpoint(*ACCRUAL_ROLES)
def list_compliance_reviews(caller):
    records = _filtered(db.reviews.values(),
                        [("member_id", "member_id"),
                         ("deal_id", "deal_id"),
                         ("result", "result")])
    return paged(records)


# --------------------------------------------------------------------------
# member savings report (computed read)
# --------------------------------------------------------------------------

@bp.get("/members/<member_id>/savings-report")
@endpoint("MemberOperator", "GpoAdmin", "RebateAnalyst")
def member_savings_report(caller, member_id):
    from flask import request
    from shapes import DATE_RE

    member = resolve("member", member_id)              # priority 4
    require_member_scope(caller, member["id"])          # priority 5

    period_start = request.args.get("period_start")
    period_end = request.args.get("period_end")
    basis = request.args.get("basis")
    if period_start is None or not DATE_RE.match(period_start):
        raise ApiError("ERR_INVALID_REQUEST")
    if period_end is None or not DATE_RE.match(period_end):
        raise ApiError("ERR_INVALID_REQUEST")
    if basis is None:
        basis = "AS_PURCHASED"                          # the declared default
    elif basis not in ("AS_PURCHASED", "FULL_BASKET"):
        raise ApiError("ERR_INVALID_REQUEST")

    return ok(savings_report(member, period_start, period_end, basis))


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@endpoint("GpoAdmin")
def set_current_utc(caller):
    body = parse_body([Instant("current_utc")])
    return ok(set_clock(body["current_utc"]))
