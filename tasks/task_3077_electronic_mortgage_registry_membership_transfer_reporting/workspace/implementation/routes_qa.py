"""QA reviews, findings, and sanctions (PRD §3.5)."""
from decimal import Decimal
from flask import Blueprint, request

from db import store, iso
from domain import (
    FIELD_NAMES, SEVERITIES, base_record, compute_discrepancy, err,
    find_finding, find_finding_under, find_loan, find_review, find_sanction,
    get_body, member_sample_loans, opt_number, paginate, req_enum, req_iso,
    req_str, sanction_totals, sorted_items, touch, APPEAL_WINDOW_DAYS,
)
from middleware import require_role
from response import success
from views import finding_view, review_view, sanction_view

bp = Blueprint("qa", __name__)


@bp.post("/qa-reviews")
def create_review():
    body = get_body()
    user_id, _role = require_role("QAAuditor")
    member_id = req_str(body, "member_id")
    period_start = req_iso(body, "period_start")
    period_end = req_iso(body, "period_end")
    if store.members.get(member_id) is None:
        raise err("ERR_MEMBER_NOT_FOUND", f"Member {member_id} not found")
    if period_end < period_start:
        raise err("ERR_INVALID_PERIOD", "period_end must not precede period_start")
    rec = base_record()
    rec.update({
        "member_id": member_id,
        "period_start": iso(period_start),
        "period_end": iso(period_end),
        "sample_size": 0,
        "discrepancy_score": 0.0,
        "status": "DRAFT",
        "created_by": user_id,
        "settled_by": None,
        "settled_at": None,
    })
    store.reviews[rec["id"]] = rec
    return success(review_view(rec), status=201)


@bp.get("/qa-reviews")
def list_reviews():
    require_role("RegistryAdmin", "QAAuditor")
    items = sorted_items(store.reviews)
    for field in ("member_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [r for r in items if r[field] == value]
    page, meta = paginate(items)
    return success([review_view(r) for r in page], is_list=True, pagination=meta)


@bp.get("/qa-reviews/<reviewId>")
def get_review(reviewId):
    require_role("RegistryAdmin", "QAAuditor")
    return success(review_view(find_review(reviewId)))


@bp.post("/qa-reviews/<reviewId>/findings")
def create_finding(reviewId):
    body = get_body()
    require_role("QAAuditor")
    review = find_review(reviewId)
    loan_id = req_str(body, "loan_id")
    field_name = req_enum(body, "field_name", FIELD_NAMES)
    expected_value = req_str(body, "expected_value")
    actual_value = req_str(body, "actual_value")
    severity = req_enum(body, "severity", SEVERITIES)

    find_loan(loan_id)
    if review["status"] != "DRAFT":
        raise err("ERR_REVIEW_NOT_DRAFT", "Findings can only be added to a DRAFT review")
    sample_ids = {l["id"] for l in member_sample_loans(review["member_id"])}
    if loan_id not in sample_ids:
        raise err("ERR_LOAN_NOT_IN_SAMPLE",
                  "The finding's loan is not in the review's sample")

    rec = base_record()
    rec.update({
        "review_id": reviewId,
        "loan_id": loan_id,
        "field_name": field_name,
        "expected_value": expected_value,
        "actual_value": actual_value,
        "severity": severity,
    })
    store.findings[rec["id"]] = rec
    return success(finding_view(rec), status=201)


@bp.get("/qa-reviews/<reviewId>/findings")
def list_findings(reviewId):
    require_role("RegistryAdmin", "QAAuditor")
    find_review(reviewId)
    items = [f for f in sorted_items(store.findings) if f["review_id"] == reviewId]
    for field in ("loan_id", "severity"):
        value = request.args.get(field)
        if value is not None:
            items = [f for f in items if f[field] == value]
    page, meta = paginate(items)
    return success([finding_view(f) for f in page], is_list=True, pagination=meta)


@bp.get("/qa-reviews/<reviewId>/findings/<findingId>")
def get_finding_nested(reviewId, findingId):
    require_role("RegistryAdmin", "QAAuditor")
    find_review(reviewId)
    return success(finding_view(find_finding_under(reviewId, findingId)))


@bp.get("/qa-findings/<findingId>")
def get_finding_flat(findingId):
    require_role("RegistryAdmin", "QAAuditor")
    return success(finding_view(find_finding(findingId)))


@bp.get("/qa-findings")
def list_findings_flat():
    require_role("RegistryAdmin", "QAAuditor")
    items = sorted_items(store.findings)
    for field in ("review_id", "loan_id", "severity"):
        value = request.args.get(field)
        if value is not None:
            items = [f for f in items if f[field] == value]
    page, meta = paginate(items)
    return success([finding_view(f) for f in page], is_list=True, pagination=meta)


@bp.post("/qa-reviews/<reviewId>/issue")
def issue_review(reviewId):
    get_body()
    require_role("QAAuditor")
    review = find_review(reviewId)
    if review["status"] != "DRAFT":
        raise err("ERR_REVIEW_NOT_DRAFT", "Only a DRAFT review can be issued")
    findings = [f for f in store.findings.values() if f["review_id"] == reviewId]
    if not findings:
        raise err("ERR_NO_FINDINGS", "Issuing a review requires at least one finding")
    sample_size, score = compute_discrepancy(review)
    review["sample_size"] = sample_size
    review["discrepancy_score"] = score
    review["status"] = "FINDINGS_ISSUED"
    touch(review)
    return success(review_view(review))


@bp.post("/qa-reviews/<reviewId>/reopen")
def reopen_review(reviewId):
    get_body()
    require_role("QAAuditor")
    review = find_review(reviewId)
    if review["status"] != "FINDINGS_ISSUED":
        raise err("ERR_REVIEW_NOT_ISSUED",
                  "Only a FINDINGS_ISSUED review can be reopened")
    review["status"] = "DRAFT"
    touch(review)
    return success(review_view(review))


@bp.post("/qa-reviews/<reviewId>/settle")
def settle_review(reviewId):
    body = get_body()
    user_id, _role = require_role("QAAuditor")
    review = find_review(reviewId)
    abatement = opt_number(body, "abatement_factor")
    if abatement is None:
        abatement = Decimal("1.0")

    if review["status"] != "FINDINGS_ISSUED":
        raise err("ERR_REVIEW_NOT_ISSUED",
                  "Only a FINDINGS_ISSUED review can be settled")
    if user_id == review["created_by"]:
        raise err("ERR_SOD_SAME_ACTOR",
                  "The auditor who created a review may not settle it")
    if abatement < 0 or abatement > 1:
        raise err("ERR_INVALID_ABATEMENT_FACTOR",
                  "abatement_factor must lie within [0, 1]")

    total, line_count = sanction_totals(review["member_id"], reviewId, abatement)
    review["status"] = "SETTLED"
    review["settled_by"] = user_id
    review["settled_at"] = iso(store.clock)
    touch(review)

    sanction = base_record()
    sanction.update({
        "member_id": review["member_id"],
        "review_id": reviewId,
        "total_amount_cents": total,
        "line_count": line_count,
        "status": "ASSESSED",
    })
    store.sanctions[sanction["id"]] = sanction
    return success(review_view(review))


# ---------------- sanctions ----------------

@bp.get("/sanctions")
def list_sanctions():
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    items = sorted_items(store.sanctions)
    for field in ("member_id", "review_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [s for s in items if s[field] == value]
    page, meta = paginate(items)
    return success([sanction_view(s) for s in page], is_list=True, pagination=meta)


@bp.get("/sanctions/<sanctionId>")
def get_sanction(sanctionId):
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    return success(sanction_view(find_sanction(sanctionId)))


@bp.post("/sanctions/<sanctionId>/appeal")
def appeal_sanction(sanctionId):
    get_body()
    user_id, _role = require_role("MemberRep")
    sanction = find_sanction(sanctionId)
    if sanction["member_id"] != user_id:
        raise err("ERR_NOT_SANCTION_PARTY",
                  "Only the sanctioned member may appeal the sanction")
    if sanction["status"] != "ASSESSED":
        raise err("ERR_SANCTION_NOT_APPEALABLE",
                  "Only an ASSESSED sanction can be appealed")
    from domain import parse_iso
    created = parse_iso(sanction["created_at"], "created_at")
    if (store.clock.date() - created.date()).days > APPEAL_WINDOW_DAYS:
        raise err("ERR_APPEAL_WINDOW_EXPIRED",
                  "Appeal filed beyond the appeal window")
    sanction["status"] = "APPEALED"
    touch(sanction)
    return success(sanction_view(sanction))


@bp.post("/sanctions/<sanctionId>/adjudicate")
def adjudicate_sanction(sanctionId):
    body = get_body()
    user_id, _role = require_role("QAAuditor")
    sanction = find_sanction(sanctionId)
    decision = req_enum(body, "decision", {"UPHELD", "REDUCED", "VACATED"})
    reduced_total_cents = body.get("reduced_total_cents")

    if sanction["status"] != "APPEALED":
        raise err("ERR_SANCTION_NOT_APPEALED",
                  "Only an APPEALED sanction can be adjudicated")
    review = store.reviews.get(sanction["review_id"])
    if review is not None and user_id == review["settled_by"]:
        raise err("ERR_SOD_SAME_ACTOR",
                  "The auditor who settled the review may not adjudicate its sanction")

    if decision == "UPHELD":
        sanction["status"] = "UPHELD"
    elif decision == "REDUCED":
        if not isinstance(reduced_total_cents, int) or isinstance(reduced_total_cents, bool):
            raise err("ERR_INVALID_REQUEST",
                      "reduced_total_cents must be an integer for a REDUCED decision")
        if reduced_total_cents >= sanction["total_amount_cents"]:
            raise err("ERR_REDUCTION_NOT_LOWER",
                      "reduced_total_cents must be strictly below the current total")
        sanction["total_amount_cents"] = reduced_total_cents
        sanction["status"] = "REDUCED"
    else:  # VACATED
        sanction["total_amount_cents"] = 0
        sanction["status"] = "VACATED"
    touch(sanction)
    return success(sanction_view(sanction))


@bp.post("/sanctions/<sanctionId>/pay")
def pay_sanction(sanctionId):
    get_body()
    user_id, _role = require_role("MemberRep")
    sanction = find_sanction(sanctionId)
    if sanction["member_id"] != user_id:
        raise err("ERR_NOT_SANCTION_PARTY",
                  "Only the sanctioned member may pay the sanction")
    if sanction["status"] != "ASSESSED":
        raise err("ERR_SANCTION_NOT_APPEALABLE",
                  "Only an ASSESSED sanction can be paid")
    sanction["status"] = "PAID"
    touch(sanction)
    return success(sanction_view(sanction))
