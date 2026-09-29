"""Quote header, line and pricing-preview endpoints (PRD 3.2, 3.3)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import common
import db
import response
import validation
import workflow
from auth import require_roles
from errors import fail
from validation import validate, json_body

bp = Blueprint("quotes", __name__)

ALL = auth.ALL_ROLES

BILLING_FREQUENCIES = ("ANNUAL", "SEMI_ANNUAL", "QUARTERLY", "MONTHLY")

QUOTE_CREATE_SPEC = {
    "account_id": {"type": "string", "required": True},
    "title": {"type": "string", "required": True},
    "term_months": {"type": "integer", "required": True, "ge": 1, "le": 60},
    "payment_terms_days": {"type": "integer", "ge": 1, "le": 180},
    "billing_frequency": {"type": "enum", "values": BILLING_FREQUENCIES},
}

QUOTE_PATCH_SPEC = {
    "title": {"type": "string"},
    "term_months": {"type": "integer", "ge": 1, "le": 60},
    "payment_terms_days": {"type": "integer", "ge": 1, "le": 180},
    "billing_frequency": {"type": "enum", "values": BILLING_FREQUENCIES},
}


def new_quote_record(account_id, title, term_months, payment_terms_days,
                     billing_frequency, policy, owner_rep_user_id,
                     renegotiated_from_quote_id=None):
    record = {
        "account_id": account_id,
        "desk_policy_id": policy["id"],
        "renegotiated_from_quote_id": renegotiated_from_quote_id,
        "owner_rep_user_id": owner_rep_user_id,
        "title": title,
        "term_months": term_months,
        "payment_terms_days": payment_terms_days,
        "billing_frequency": billing_frequency,
        "status": "DRAFT",
        "revision_count": 0,
        "renegotiation_count": 0,
        "list_total_cents": 0,
        "cost_total_cents": 0,
        "provisional_net_total_cents": 0,
        "final_net_total_cents": 0,
        "provisional_blended_discount_pct": calc.rhu(0, 6),
        "final_blended_discount_pct": calc.rhu(0, 6),
        "provisional_margin_pct": calc.rhu(0, 6),
        "final_margin_pct": calc.rhu(0, 6),
        "volume_rebate_cents": 0,
        "payment_terms_uplift_cents": 0,
        "required_approval_level": 0,
        "terms_risk_score_aggregate": calc.rhu(0, 2),
        "terms_risk_score_dominant": calc.rhu(0, 2),
        "arrangement_type": "SINGLE_ELEMENT",
        "booked_arr_cents": 0,
        "booked_tcv_cents": 0,
        "submitted_at": None,
        "approved_at": None,
        "expires_at": None,
        "booked_at": None,
        "policy_revalidation_required": False,
        "pinned_policy_version": None,
    }
    db.insert("quotes", record)
    db.mark_fresh(record)
    record["expires_at"] = calc.creation_expiry(policy, record["created_at"])
    return record


@bp.post("/quotes")
@require_roles("SalesRep")
def create_quote():
    body = validate(json_body(), QUOTE_CREATE_SPEC)
    if db.account(body["account_id"]) is None:
        fail("ERR_ACCOUNT_NOT_FOUND")
    policy = db.active_policy()
    if policy is None:
        fail("ERR_NO_ACTIVE_DESK_POLICY", "No desk policy revision is ACTIVE.")
    quote = new_quote_record(
        body["account_id"],
        body["title"],
        body["term_months"],
        body.get("payment_terms_days", 30),
        body.get("billing_frequency", "ANNUAL"),
        policy,
        auth.current_user_id(),
    )
    return response.created(quote)


@bp.get("/quotes/<quote_id>")
@require_roles(ALL)
def read_quote(quote_id):
    return response.ok(common.must_get("quotes", quote_id))


@bp.get("/quotes")
@require_roles(ALL)
def list_quotes():
    rows = db.sorted_records(db.all_records("quotes"))
    from flask import request
    for field in ("account_id", "desk_policy_id", "renegotiated_from_quote_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    window, total, limit, offset = validation.paginate(rows)
    return response.listing(window, total, limit, offset)


@bp.patch("/quotes/<quote_id>")
@require_roles("SalesRep")
def patch_quote(quote_id):
    quote = common.must_get("quotes", quote_id)
    body = validate(json_body(), QUOTE_PATCH_SPEC)
    common.require_owner(quote)
    if quote["status"] != "DRAFT":
        fail("ERR_QUOTE_NOT_DRAFT")
    for field in ("title", "term_months", "payment_terms_days", "billing_frequency"):
        if field in body:
            quote[field] = body[field]
    workflow.reprice(quote)
    db.touch(quote)
    workflow.stale_assessments(quote)
    return response.ok(quote)


@bp.get("/quotes/<quote_id>/lines")
@require_roles(ALL)
def list_quote_lines(quote_id):
    common.must_get("quotes", quote_id)
    window, total, limit, offset = validation.paginate(db.lines_of_quote(quote_id))
    return response.listing(window, total, limit, offset)


LINE_CREATE_SPEC = {
    "quote_id": {"type": "string", "required": True},
    "product_id": {"type": "string", "required": True},
    "quantity": {"type": "integer", "required": True, "ge": 1, "le": 1000000},
    "requested_discount_pct": {"type": "number", "ge": Decimal(0), "lt": Decimal(1)},
}

LINE_PATCH_SPEC = {
    "quantity": {"type": "integer", "ge": 1, "le": 1000000},
    "requested_discount_pct": {"type": "number", "ge": Decimal(0), "lt": Decimal(1)},
}


def _after_line_write(quote):
    workflow.reprice(quote)
    db.touch(quote)
    workflow.stale_assessments(quote)


@bp.post("/quote-lines")
@require_roles("SalesRep")
def create_quote_line():
    body = validate(json_body(), LINE_CREATE_SPEC)
    quote = db.quote(body["quote_id"])
    if quote is None:
        fail("ERR_QUOTE_NOT_FOUND")
    product = db.product(body["product_id"])
    if product is None:
        fail("ERR_PRODUCT_NOT_FOUND")
    common.require_owner(quote)
    if quote["status"] != "DRAFT":
        fail("ERR_QUOTE_NOT_DRAFT")
    policy = common.policy_of(quote)
    requested = body.get("requested_discount_pct", calc.rhu(0, 6))
    if calc.dec(requested) > calc.dec(policy["max_stack_discount_pct"]):
        fail(
            "ERR_DISCOUNT_STACK_EXCEEDED",
            "requested_discount_pct exceeds the policy's max_stack_discount_pct.",
        )
    line = {
        "quote_id": quote["id"],
        "product_id": product["id"],
        "quantity": body["quantity"],
        "requested_discount_pct": calc.dec(requested),
        "unit_list_price_cents": product["list_unit_price_cents"],
        "unit_cost_cents": product["unit_cost_cents"],
        "rev_rec_category": product["rev_rec_category"],
        "extended_list_cents": 0,
        "extended_cost_cents": 0,
        "provisional_net_cents": 0,
        "final_net_cents": 0,
        "volume_tier_level_applied": 0,
        "bundle_discount_applied_pct": calc.rhu(0, 6),
        "effective_stack_discount_pct": calc.rhu(0, 6),
    }
    db.insert("quote_lines", line)
    db.mark_fresh(line)
    _after_line_write(quote)
    return response.created(line)


@bp.patch("/quote-lines/<line_id>")
@require_roles("SalesRep")
def patch_quote_line(line_id):
    line = common.must_get("quote_lines", line_id)
    body = validate(json_body(), LINE_PATCH_SPEC)
    quote = db.quote(line["quote_id"])
    common.require_owner(quote)
    if quote["status"] != "DRAFT":
        fail("ERR_QUOTE_NOT_DRAFT")
    policy = common.policy_of(quote)
    if "requested_discount_pct" in body:
        if calc.dec(body["requested_discount_pct"]) > calc.dec(policy["max_stack_discount_pct"]):
            fail(
                "ERR_DISCOUNT_STACK_EXCEEDED",
                "requested_discount_pct exceeds the policy's max_stack_discount_pct.",
            )
    for field in ("quantity", "requested_discount_pct"):
        if field in body:
            line[field] = body[field]
    db.touch(line)
    _after_line_write(quote)
    return response.ok(line)


@bp.delete("/quote-lines/<line_id>")
@require_roles("SalesRep")
def delete_quote_line(line_id):
    line = common.must_get("quote_lines", line_id)
    validate(json_body(), {})
    quote = db.quote(line["quote_id"])
    common.require_owner(quote)
    if quote["status"] != "DRAFT":
        fail("ERR_QUOTE_NOT_DRAFT")
    del db.store["quote_lines"][line_id]
    _after_line_write(quote)
    return response.no_content()


PREVIEW_LINE_FIELDS = (
    "product_id",
    "quantity",
    "requested_discount_pct",
    "unit_list_price_cents",
    "unit_cost_cents",
    "rev_rec_category",
    "extended_list_cents",
    "extended_cost_cents",
    "volume_tier_level_applied",
    "bundle_discount_applied_pct",
    "effective_stack_discount_pct",
    "provisional_net_cents",
    "final_net_cents",
)


@bp.get("/quotes/<quote_id>/pricing-preview")
@require_roles(ALL)
def pricing_preview(quote_id):
    quote = common.must_get("quotes", quote_id)
    priced = workflow.compute_pricing(quote)
    scored = calc.score_terms(quote_id)

    merged = []
    by_id = {p["id"]: p for p in priced["priced"]}
    for line in priced["lines"]:
        row = dict(line)
        row.update(by_id[line["id"]])
        merged.append(row)
    allocation = calc.allocate(
        {"final_net_total_cents": priced["final_net_total_cents"]}, merged
    )

    lines = []
    for row in merged:
        item = {"id": row["id"], "quote_line_id": row["id"]}
        for field in PREVIEW_LINE_FIELDS:
            item[field] = row.get(field)
        lines.append(item)

    data = {
        "list_total_cents": priced["list_total_cents"],
        "cost_total_cents": priced["cost_total_cents"],
        "provisional_net_total_cents": priced["provisional_net_total_cents"],
        "final_net_total_cents": priced["final_net_total_cents"],
        "provisional_blended_discount_pct": priced["provisional_blended_discount_pct"],
        "final_blended_discount_pct": priced["final_blended_discount_pct"],
        "provisional_margin_pct": priced["provisional_margin_pct"],
        "final_margin_pct": priced["final_margin_pct"],
        "volume_rebate_cents": priced["volume_rebate_cents"],
        "payment_terms_uplift_cents": priced["payment_terms_uplift_cents"],
        "required_approval_level": priced["required_approval_level"],
        "terms_risk_score_aggregate": scored["aggregate"],
        "terms_risk_score_dominant": scored["dominant"],
        "arrangement_type": priced["arrangement_type"],
        "usage_excluded_cents": allocation["usage_excluded_cents"],
        "allocable_amount_cents": allocation["allocable_amount_cents"],
        "allocation_residual_cents": allocation["allocation_residual_cents"],
        "margin_give_up_cents": priced["margin_give_up_cents"],
        "lines": lines,
    }
    return response.ok(data)
