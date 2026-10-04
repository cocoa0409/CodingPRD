"""Secondary-source licensing and royalty settlement routes (PRD 3.7)."""

from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, request

from constants import PRACTICE_AREAS, ROYALTY_BASES
from db import stamp_ledger, stamp_new, store, touch
from errors import raise_err
from middleware import require_roles
from response import list_response, ok_object
from serializers import serialize_agreement, serialize_statement
from util import get_body, opt_int, req_bool, req_date, req_enum, req_str

bp = Blueprint("licensing", __name__)

AGREEMENT_READERS = ("LicensingManager", "BillingAdmin")
STATEMENT_READERS = ("BillingAdmin", "LicensingManager")


@bp.post("/legal-research/license-agreements")
@require_roles("LicensingManager")
def create_agreement():
    body = get_body()
    work_title = req_str(body, "work_title")
    author_name = req_str(body, "author_name")
    practice_area = req_enum(body, "practice_area", PRACTICE_AREAS)
    royalty_basis = req_enum(body, "royalty_basis", ROYALTY_BASES)
    exclusive = req_bool(body, "exclusive")
    window_start = req_date(body, "window_start")
    window_end = req_date(body, "window_end")
    if not (window_start < window_end):
        raise_err("ERR_INVALID_REQUEST", "window_start must be earlier than window_end")

    per_view_fee = opt_int(body, "per_view_fee_cents")
    revenue_share_bps = opt_int(body, "revenue_share_bps")
    if royalty_basis == "PER_VIEW" and per_view_fee is None:
        raise_err("ERR_INVALID_REQUEST", "per_view_fee_cents is required for PER_VIEW agreements")
    if royalty_basis == "REVENUE_SHARE" and revenue_share_bps is None:
        raise_err("ERR_INVALID_REQUEST", "revenue_share_bps is required for REVENUE_SHARE agreements")

    # Exclusive windows per practice_area must not overlap (half-open, so
    # adjacency is allowed). Only ACTIVE exclusive agreements are consulted.
    if exclusive:
        for other in store.agreements.values():
            if not other["exclusive"] or other["status"] != "ACTIVE":
                continue
            if other["practice_area"] != practice_area:
                continue
            if window_start < other["_window_end"] and other["_window_start"] < window_end:
                raise_err("ERR_LICENSE_WINDOW_OVERLAP", "exclusive window overlaps an existing agreement")

    agreement = stamp_new({
        "work_title": work_title,
        "author_name": author_name,
        "practice_area": practice_area,
        "royalty_basis": royalty_basis,
        "per_view_fee_cents": per_view_fee,
        "revenue_share_bps": revenue_share_bps,
        "exclusive": exclusive,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "_window_start": window_start,
        "_window_end": window_end,
        "status": "ACTIVE",
    })
    store.agreements[agreement["id"]] = agreement
    return ok_object(serialize_agreement(agreement), 201)


@bp.get("/legal-research/license-agreements/<agreement_id>")
@require_roles(*AGREEMENT_READERS)
def get_agreement(agreement_id):
    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        raise_err("ERR_AGREEMENT_NOT_FOUND", "license agreement %s does not exist" % agreement_id)
    return ok_object(serialize_agreement(agreement))


@bp.post("/legal-research/license-agreements/<agreement_id>/terminate")
@require_roles("LicensingManager")
def terminate_agreement(agreement_id):
    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        raise_err("ERR_AGREEMENT_NOT_FOUND", "license agreement %s does not exist" % agreement_id)
    if agreement["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "license agreement %s is already TERMINATED" % agreement_id)
    agreement["status"] = "TERMINATED"
    touch(agreement)
    return ok_object(serialize_agreement(agreement), 200)


@bp.post("/legal-research/royalty-statements/generate")
@require_roles("BillingAdmin")
def generate_statement():
    body = get_body()
    license_agreement_id = req_str(body, "license_agreement_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if not (period_start < period_end):
        raise_err("ERR_INVALID_REQUEST", "period_start must be earlier than period_end")

    agreement = store.agreements.get(license_agreement_id)
    if agreement is None:
        raise_err("ERR_AGREEMENT_NOT_FOUND", "license agreement %s does not exist" % license_agreement_id)

    # The agreement must be ACTIVE and the settlement window must intersect
    # the agreement's own license window (half-open intersection).
    intersects = period_start < agreement["_window_end"] and agreement["_window_start"] < period_end
    if agreement["status"] != "ACTIVE" or not intersects:
        raise_err("ERR_AGREEMENT_NOT_ACTIVE", "agreement is not active for the requested window")

    # Evaluation order is pinned: view_count first, then the basis-specific amount.
    view_count = sum(
        1
        for event in store.usage_events.values()
        if event["license_agreement_id"] == license_agreement_id
        and event["event_type"] == "DOC_VIEW"
        and period_start <= event["_occurred_dt"].date() < period_end
    )

    if agreement["royalty_basis"] == "PER_VIEW":
        revenue_base = 0
        royalty_amount = view_count * agreement["per_view_fee_cents"]
    else:  # REVENUE_SHARE
        revenue_base = 0
        for inv in store.invoices.values():
            if inv["status"] not in ("ISSUED", "PAID"):
                continue  # voided, overdue, and draft invoices contribute nothing
            if not (inv["_period_start"] < period_end and period_start < inv["_period_end"]):
                continue
            subscription = store.subscriptions.get(inv["subscription_id"])
            if subscription is None:
                continue
            plan = store.plans.get(subscription["plan_id"])
            if plan is None or plan["practice_area"] != agreement["practice_area"]:
                continue
            revenue_base += inv["total_cents"]
        royalty_amount = int(
            (Decimal(revenue_base) * Decimal(agreement["revenue_share_bps"]) / Decimal(10000))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    statement = stamp_ledger({
        "license_agreement_id": license_agreement_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "view_count": view_count,
        "revenue_base_cents": revenue_base,
        "royalty_amount_cents": royalty_amount,
    })
    store.statements[statement["id"]] = statement
    return ok_object(serialize_statement(statement), 201)


@bp.get("/legal-research/royalty-statements")
@require_roles(*STATEMENT_READERS)
def list_statements():
    f_agreement = request.args.get("license_agreement_id")
    rows = list(store.statements.values())
    if f_agreement is not None:
        rows = [s for s in rows if s["license_agreement_id"] == f_agreement]
    return list_response(rows, serialize_statement)


@bp.get("/legal-research/royalty-statements/<statement_id>")
@require_roles(*STATEMENT_READERS)
def get_statement(statement_id):
    statement = store.statements.get(statement_id)
    if statement is None:
        raise_err("ERR_STATEMENT_NOT_FOUND", "royalty statement %s does not exist" % statement_id)
    return ok_object(serialize_statement(statement))
