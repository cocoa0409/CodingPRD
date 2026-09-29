"""Shipper disputes, evidence review and service-guarantee recovery (PRD 3.9)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import domain
import pricing
import routes_billing as billing
import serializers as ser
import validators as v
from auth import (ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER,
                  authorize, caller_id, enforce_named_shipper,
                  enforce_shipper_scope, is_shipper_user)
from errors import ApiError
from response import pagination_params, paginate, success
from store import (db, iso, new_record, now, parse_instant, sorted_records,
                   touch)

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("WEIGHT", "ACCESSORIAL")
EVIDENCE_TYPES = ("SCAN_IMAGE", "DELIVERY_PHOTO", "ADDRESS_PROOF", "SCALE_CERT")
DISPUTE_OUTCOMES = ("UPHELD", "DENIED")
CLAIM_OUTCOMES = ("APPROVED", "DENIED")
DISPUTABLE_INVOICE_STATES = ("ISSUED", "ADJUSTED")
BLOCKING_DISPUTE_STATES = ("SUBMITTED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "UPHELD")
BLOCKING_CLAIM_STATES = ("FILED", "APPROVED", "REFUNDED")


def dispute_line(dispute):
    return db.invoice_lines.get(dispute["invoice_line_id"])


def shipper_of_dispute(dispute):
    line = dispute_line(dispute)
    return billing.shipper_of_line(line) if line else None


# --------------------------------------------------------------------------
# filing a dispute
# --------------------------------------------------------------------------

@bp.route("/disputes", methods=["POST"])
@authorize(ROLE_SHIPPER_USER)
def create_dispute():
    body = v.get_body()
    line = domain.line_or_404(v.peek_str(body, "invoice_line_id"))
    enforce_shipper_scope(billing.shipper_of_line(line))

    claim_type = v.req_enum(body, "claim_type", CLAIM_TYPES)
    claimed_reason = v.req_string(body, "claimed_reason")
    disputed_codes = v.opt_str_list(body, "disputed_codes", [],
                                   members=calc.ACCESSORIAL_CODES)

    invoice = billing.invoice_of_line(line)
    if invoice["status"] not in DISPUTABLE_INVOICE_STATES:
        raise ApiError("ERR_INVOICE_NOT_DISPUTABLE",
                       "Only an ISSUED or ADJUSTED invoice may be disputed.")

    deadline = parse_instant(invoice["dispute_deadline_utc"])
    if deadline is None or now() > deadline:
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED",
                       "The ninety-day dispute window has closed.")

    for other in db.disputes.values():
        if (other["invoice_line_id"] == line["id"]
                and other["status"] in BLOCKING_DISPUTE_STATES):
            raise ApiError("ERR_DUPLICATE_DISPUTE",
                           "A live dispute already contests this invoice line.")

    assessed_codes = set(c["code"] for c in domain.assessed_charges(line["shipment_id"]))
    if claim_type == "ACCESSORIAL":
        if not disputed_codes or any(c not in assessed_codes for c in disputed_codes):
            raise ApiError("ERR_DISPUTED_CODE_NOT_ASSESSED",
                           "Every disputed code must carry an ASSESSED charge on "
                           "the disputed line's shipment.")
    elif disputed_codes:
        raise ApiError("ERR_DISPUTED_CODE_NOT_ASSESSED",
                       "A WEIGHT dispute must not name any disputed code.")

    record = new_record()
    record.update({
        "invoice_line_id": line["id"],
        "shipper_user_id": caller_id(),
        "claim_type": claim_type,
        "disputed_codes": disputed_codes,
        "claimed_reason": claimed_reason,
        "status": "SUBMITTED",
        "round_count": 0,
        "required_item_type": None,
        "granted_credit_cents": 0,
        "resolved_at": None,
    })
    db.disputes[record["id"]] = record
    return success(ser.dispute(record), 201)


# --------------------------------------------------------------------------
# evidence and review rounds
# --------------------------------------------------------------------------

@bp.route("/disputes/<dispute_id>/evidence", methods=["POST"])
@authorize(ROLE_SHIPPER_USER)
def create_evidence(dispute_id):
    dispute = domain.dispute_or_404(dispute_id)
    enforce_shipper_scope(shipper_of_dispute(dispute))

    body = v.get_body()
    item_type = v.req_enum(body, "item_type", EVIDENCE_TYPES)
    reference = v.req_string(body, "reference")

    if dispute["status"] not in ("SUBMITTED", "EVIDENCE_REQUESTED"):
        raise ApiError("ERR_DISPUTE_NOT_IN_STATE",
                       "Evidence may only be filed on a SUBMITTED or "
                       "EVIDENCE_REQUESTED dispute.")

    required = dispute["required_item_type"]
    accepted = required is None or item_type == required

    item = new_record(versioned=False)
    item.update({
        "dispute_id": dispute["id"],
        "item_type": item_type,
        "reference": reference,
        "submitted_by_user_id": caller_id(),
        "accepted": accepted,
    })
    db.evidence_items[item["id"]] = item

    if accepted:
        dispute["required_item_type"] = None
    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)

    return success(ser.evidence_item(item), 201)


@bp.route("/disputes/<dispute_id>/request-evidence", methods=["POST"])
@authorize(ROLE_REVENUE_AUDITOR)
def request_evidence(dispute_id):
    dispute = domain.dispute_or_404(dispute_id)
    body = v.get_body()
    required_item_type = v.req_enum(body, "required_item_type", EVIDENCE_TYPES)

    if dispute["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError("ERR_DISPUTE_NOT_IN_STATE",
                       "Evidence may only be requested on a SUBMITTED or "
                       "UNDER_REVIEW dispute.")
    if dispute["round_count"] >= calc.MAX_EVIDENCE_ROUNDS:
        raise ApiError("ERR_EVIDENCE_ROUNDS_EXHAUSTED",
                       "The review loop is bounded at two evidence rounds.")

    dispute["required_item_type"] = required_item_type
    dispute["round_count"] += 1
    dispute["status"] = "EVIDENCE_REQUESTED"
    touch(dispute)
    return success(ser.dispute(dispute))


# --------------------------------------------------------------------------
# resolving a dispute
# --------------------------------------------------------------------------

def dispute_credit(dispute, line):
    """PRD 3.9 valuation: FULL_REPRICE or ACCESSORIAL_ONLY."""
    line_total = domain.line_total_cents(line)
    if dispute["claim_type"] == "WEIGHT":
        shipment = db.shipments.get(line["shipment_id"])
        repriced = pricing.price_shipment(shipment)["line_total_cents"]
        credit = max(0, line_total - repriced)
    else:
        codes = set(dispute["disputed_codes"] or [])
        credit = sum(c["amount_cents"]
                     for c in domain.assessed_charges(line["shipment_id"])
                     if c["code"] in codes)
    return min(credit, line_total)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
@authorize(ROLE_REVENUE_AUDITOR)
def resolve_dispute(dispute_id):
    dispute = domain.dispute_or_404(dispute_id)
    body = v.get_body()
    outcome = v.req_enum(body, "outcome", DISPUTE_OUTCOMES)

    line = dispute_line(dispute)
    invoice = billing.invoice_of_line(line) if line else None
    if invoice is None or invoice["status"] not in DISPUTABLE_INVOICE_STATES:
        raise ApiError("ERR_INVOICE_NOT_DISPUTABLE",
                       "The invoice behind the disputed line must still be "
                       "ISSUED or ADJUSTED.")
    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_DISPUTE_NOT_IN_STATE",
                       "Only an UNDER_REVIEW dispute may be resolved.")
    if outcome == "UPHELD" and domain.accepted_evidence_count(dispute["id"]) < 1:
        raise ApiError("ERR_EVIDENCE_REQUIRED",
                       "Upholding a dispute requires at least one accepted "
                       "evidence item.")

    if outcome == "DENIED":
        dispute["status"] = "DENIED"
        dispute["granted_credit_cents"] = 0
        dispute["resolved_at"] = iso(now())
        touch(dispute)
        return success(ser.dispute(dispute))

    granted = dispute_credit(dispute, line)
    dispute["status"] = "UPHELD"
    dispute["granted_credit_cents"] = granted
    dispute["resolved_at"] = iso(now())
    touch(dispute)

    if granted > 0:
        adjustment = billing.create_adjustment(
            line, "DISPUTE_CREDIT", -granted, "system",
            status="APPLIED", dispute_id=dispute["id"],
            applied_at=iso(now()), applied_by_user_id="system")

        if dispute["claim_type"] == "ACCESSORIAL":
            codes = set(dispute["disputed_codes"] or [])
            for charge in domain.assessed_charges(line["shipment_id"]):
                if charge["code"] in codes:
                    charge["status"] = "WAIVED"
                    touch(charge)

        touch(line)
        invoice["status"] = "ADJUSTED"
        touch(invoice)
        shipment = db.shipments.get(line["shipment_id"])
        if shipment is not None:
            if shipment["billing_status"] == "BILLED":
                shipment["billing_status"] = "ADJUSTED"
            touch(shipment)

    return success(ser.dispute(dispute))


@bp.route("/disputes/<dispute_id>", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def read_dispute(dispute_id):
    dispute = domain.dispute_or_404(dispute_id)
    enforce_shipper_scope(shipper_of_dispute(dispute))
    return success(ser.dispute(dispute))


@bp.route("/disputes", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def list_disputes():
    limit, offset = pagination_params()
    rows = sorted_records(list(db.disputes.values()))
    if is_shipper_user():
        rows = [r for r in rows if shipper_of_dispute(r) == caller_id()]
    for key in ("invoice_line_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, ser.dispute, limit, offset)


@bp.route("/disputes/<dispute_id>/evidence", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def list_evidence(dispute_id):
    dispute = domain.dispute_or_404(dispute_id)
    enforce_shipper_scope(shipper_of_dispute(dispute))
    limit, offset = pagination_params()
    rows = domain.evidence_of_dispute(dispute["id"])
    return paginate(rows, ser.evidence_item, limit, offset)


# --------------------------------------------------------------------------
# guarantee claims
# --------------------------------------------------------------------------

def peak_season_suspension(shipment):
    for window in db.surcharge_windows.values():
        if window["status"] != "ACTIVE" or window["kind"] != "PEAK_SEASON":
            continue
        if not (window["start_date"] <= shipment["pickup_date"] < window["end_date"]):
            continue
        scope = window["service_level_id"]
        if scope is None or scope == shipment["service_level_id"]:
            return True
    return False


def live_invoiced_line(shipment):
    line = domain.live_line_for_shipment(shipment["id"])
    if line is None:
        return None
    invoice = billing.invoice_of_line(line)
    if invoice is None or invoice["status"] not in DISPUTABLE_INVOICE_STATES:
        return None
    return line


def claim_eligibility(shipment, strict):
    """Shared by the single filing (strict) and the audit sweep (silent).

    Returns (line, late_by_seconds, candidate_refund_cents) or None when the
    package is ineligible and strict is False.
    """
    def reject(error_id, message):
        if strict:
            raise ApiError(error_id, message)
        return None

    if shipment["movement_status"] != "DELIVERED":
        return reject("ERR_SHIPMENT_NOT_DELIVERED",
                      "Only a DELIVERED package may carry a guarantee claim.")

    delivered_at = parse_instant(shipment["delivered_at"])
    if delivered_at is None:
        return reject("ERR_SHIPMENT_NOT_DELIVERED",
                      "Only a DELIVERED package may carry a guarantee claim.")
    if now() > delivered_at + timedelta(days=calc.CLAIM_WINDOW_DAYS):
        return reject("ERR_CLAIM_WINDOW_CLOSED",
                      "The fifteen-day claim window has closed.")

    for other in db.guarantee_claims.values():
        if (other["shipment_id"] == shipment["id"]
                and other["status"] in BLOCKING_CLAIM_STATES):
            return reject("ERR_DUPLICATE_CLAIM",
                          "A live guarantee claim already exists for this package.")

    service_level = db.service_levels.get(shipment["service_level_id"])
    if service_level is None or not service_level["guaranteed"]:
        return reject("ERR_SERVICE_NOT_GUARANTEED",
                      "The purchased service carries no money-back commitment.")

    line = live_invoiced_line(shipment)
    if line is None:
        return reject("ERR_SHIPMENT_NOT_INVOICED",
                      "The package must sit on a live line of an ISSUED or "
                      "ADJUSTED invoice.")

    if peak_season_suspension(shipment):
        return reject("ERR_GUARANTEE_SUSPENDED",
                      "The money-back commitment is suspended inside a peak "
                      "season window.")

    deadline = parse_instant(shipment["guarantee_deadline_utc"])
    if deadline is None or delivered_at <= deadline:
        return reject("ERR_SHIPMENT_NOT_LATE",
                      "The delivery landed on or before the commitment instant.")

    late_by_seconds = int((delivered_at - deadline).total_seconds())
    return line, late_by_seconds, line["transportation_base_cents"]


def file_claim(shipment, filed_by_user_id, claimed_reason, eligibility):
    line, late_by_seconds, candidate_refund_cents = eligibility
    record = new_record()
    record.update({
        "shipment_id": shipment["id"],
        "invoice_line_id": line["id"],
        "claimed_reason": claimed_reason,
        "guarantee_deadline_utc": shipment["guarantee_deadline_utc"],
        "delivered_at": shipment["delivered_at"],
        "late_by_seconds": late_by_seconds,
        "candidate_refund_cents": candidate_refund_cents,
        "refund_cents": 0,
        "status": "FILED",
        "filed_by_user_id": filed_by_user_id,
        "adjudicated_at": None,
    })
    db.guarantee_claims[record["id"]] = record
    return record


@bp.route("/guarantee-claims", methods=["POST"])
@authorize(ROLE_SHIPPER_USER, ROLE_REVENUE_AUDITOR)
def create_guarantee_claim():
    body = v.get_body()
    shipment = domain.shipment_or_404(v.peek_str(body, "shipment_id"))
    enforce_shipper_scope(shipment["shipper_id"])

    claimed_reason = v.opt_string(body, "claimed_reason")

    eligibility = claim_eligibility(shipment, True)
    claim = file_claim(shipment, caller_id(), claimed_reason, eligibility)
    return success(ser.guarantee_claim(claim), 201)


@bp.route("/guarantee-claims/scan", methods=["POST"])
@authorize(ROLE_REVENUE_AUDITOR)
def scan_guarantee_claims():
    body = v.get_body()
    shipper = domain.shipper_or_404(v.peek_str(body, "shipper_id"))
    period_start = v.req_date(body, "period_start")
    period_end = v.req_date(body, "period_end")

    if period_end < period_start:
        raise ApiError("ERR_INVALID_PERIOD",
                       "period_end must be on or after period_start.")

    candidates = [s for s in domain.shipments_of_shipper(shipper["id"])
                  if period_start <= s["pickup_date"] <= period_end]
    candidates.sort(key=lambda s: (s["pickup_date"], s["created_at"], s["_seq"]))

    filed_ids = []
    skipped = 0
    for shipment in candidates:
        eligibility = claim_eligibility(shipment, False)
        if eligibility is None:
            skipped += 1
            continue
        claim = file_claim(shipment, "system", None, eligibility)
        filed_ids.append(claim["id"])

    return success({
        "filed_count": len(filed_ids),
        "skipped_count": skipped,
        "claim_ids": filed_ids,
    })


@bp.route("/guarantee-claims/<claim_id>/adjudicate", methods=["POST"])
@authorize(ROLE_REVENUE_AUDITOR)
def adjudicate_guarantee_claim(claim_id):
    claim = domain.claim_or_404(claim_id)
    body = v.get_body()
    outcome = v.req_enum(body, "outcome", CLAIM_OUTCOMES)

    if claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_NOT_ADJUDICABLE",
                       "Only a FILED claim may be adjudicated.")

    if outcome == "DENIED":
        claim["status"] = "DENIED"
        claim["refund_cents"] = 0
        claim["adjudicated_at"] = iso(now())
        touch(claim)
        return success(ser.guarantee_claim(claim))

    line = db.invoice_lines.get(claim["invoice_line_id"])
    invoice = billing.invoice_of_line(line) if line else None
    if invoice is None or invoice["status"] not in DISPUTABLE_INVOICE_STATES:
        raise ApiError("ERR_INVOICE_NOT_ADJUSTABLE",
                       "The invoice behind the claim's line must be ISSUED or "
                       "ADJUSTED.")
    if claim["candidate_refund_cents"] <= 0:
        raise ApiError("ERR_CLAIM_NOT_ADJUDICABLE",
                       "There is no candidate refund to approve.")

    billing.create_adjustment(line, "GUARANTEE_REFUND",
                              -claim["candidate_refund_cents"], caller_id(),
                              guarantee_claim_id=claim["id"])
    touch(invoice)

    claim["status"] = "APPROVED"
    claim["adjudicated_at"] = iso(now())
    touch(claim)
    return success(ser.guarantee_claim(claim))


@bp.route("/guarantee-claims/<claim_id>", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def read_guarantee_claim(claim_id):
    claim = domain.claim_or_404(claim_id)
    shipment = db.shipments.get(claim["shipment_id"])
    if shipment is not None:
        enforce_shipper_scope(shipment["shipper_id"])
    return success(ser.guarantee_claim(claim))


@bp.route("/guarantee-claims", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def list_guarantee_claims():
    limit, offset = pagination_params()
    rows = sorted_records(list(db.guarantee_claims.values()))
    if is_shipper_user():
        rows = [r for r in rows
                if (db.shipments.get(r["shipment_id"]) or {}).get("shipper_id")
                == caller_id()]
    for key in ("shipment_id", "invoice_line_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, ser.guarantee_claim, limit, offset)
