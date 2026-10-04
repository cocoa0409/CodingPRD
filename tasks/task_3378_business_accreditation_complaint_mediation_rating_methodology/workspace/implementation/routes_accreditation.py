"""Accreditation applications and dues invoices (PRD 3.2, 3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import domain
import web
from constants import (
    ACCREDITATION_MIN_AGE_DAYS,
    BILLING_PLANS,
    CHECKLIST_RESULTS,
    DECISIONS,
    INVOICE_DUE_DAYS,
    LEDGER_KINDS,
    REAPPLICATION_COOLING_DAYS,
    ROLE_BUSINESS_REP,
    ROLE_BUREAU_ADMIN,
    ROLE_STANDARDS_REVIEWER,
    VOID_RECENCY_DAYS,
)
from errors import ApiError
from routes_core import get_business_or_404, serialize_business  # noqa: F401

bp = Blueprint("accreditation", __name__)

APP_LIST_ROLES = {ROLE_BUREAU_ADMIN, ROLE_STANDARDS_REVIEWER, ROLE_BUSINESS_REP}
LIVE_APPLICATION_STATES = ("DRAFT", "SUBMITTED", "APPROVED_PENDING_DUES")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_application_or_404(application_id):
    application = db.STORE.applications.get(application_id)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND")
    return application


def get_invoice_or_404(invoice_id):
    invoice = db.STORE.invoices.get(invoice_id)
    if invoice is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND")
    return invoice


def serialize_application(application):
    return db.serialize(application)


def serialize_invoice(invoice):
    domain.refresh_derived("invoice", invoice)
    return db.serialize(invoice)


# ---------------------------------------------------------------------------
# POST /businesses/{id}/accreditation-applications  (create or reapply-reset)
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/accreditation-applications", methods=["POST"])
def create_application(business_id):
    user_id, role = web.authz({ROLE_BUSINESS_REP})
    # priority 3: ownership on the path business id
    if user_id != business_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    # priority 4: path existence, then body-id existence
    business = get_business_or_404(business_id)
    data = web.body()
    application_id = data.get("application_id")
    existing = None
    if application_id is not None:
        candidate = db.STORE.applications.get(application_id)
        if candidate is None or candidate["business_id"] != business_id:
            raise ApiError("ERR_APPLICATION_NOT_FOUND")
        existing = candidate
    # priority 5: schema
    billing_plan = web.require_enum(data, "billing_plan", BILLING_PLANS)
    license_number = web.require_string(data, "license_number")

    if existing is not None:
        # reapplication: reset the DENIED application back to DRAFT
        # priority 7: from-state
        if existing["status"] != "DENIED":
            raise ApiError("ERR_APPLICATION_INVALID_STATE")
        # priority 10: cooling window
        decided_at = existing["decided_at"]
        if decided_at is None or db.now() < decided_at + timedelta(
            days=REAPPLICATION_COOLING_DAYS
        ):
            raise ApiError("ERR_REAPPLICATION_COOLING")
        existing["reapplication_count"] += 1
        existing["billing_plan"] = billing_plan
        existing["license_number"] = license_number
        existing["status"] = "DRAFT"
        existing["submitted_at"] = None
        existing["decided_at"] = None
        existing["denial_reason"] = None
        existing["advertising_practices_result"] = None
        existing["complaint_history_result"] = None
        existing["licensing_result"] = None
        db.touch(existing)
        return web.success_object(serialize_application(existing), status=201)

    # priority 9: at most one live application per business
    for application in db.STORE.applications.values():
        if (
            application["business_id"] == business_id
            and application["status"] in LIVE_APPLICATION_STATES
        ):
            raise ApiError("ERR_APPLICATION_ALREADY_ACTIVE")
    application = db.new_entity(
        "applications",
        {
            "business_id": business["id"],
            "billing_plan": billing_plan,
            "license_number": license_number,
            "status": "DRAFT",
            "reapplication_count": 0,
            "submitted_at": None,
            "decided_at": None,
            "denial_reason": None,
            "advertising_practices_result": None,
            "complaint_history_result": None,
            "licensing_result": None,
            "dues_invoice_id": None,
        },
    )
    return web.success_object(serialize_application(application), status=201)


# ---------------------------------------------------------------------------
# GET /businesses/{id}/accreditation-applications
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/accreditation-applications", methods=["GET"])
def list_applications(business_id):
    web.authz(APP_LIST_ROLES)
    get_business_or_404(business_id)
    status = request.args.get("status")
    items = [
        a for a in db.STORE.applications.values() if a["business_id"] == business_id
    ]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return web.paginated_entities(items, serialize_application)


# ---------------------------------------------------------------------------
# POST /accreditation-applications/{id}/submit
# ---------------------------------------------------------------------------
@bp.route("/accreditation-applications/<application_id>/submit", methods=["POST"])
def submit_application(application_id):
    user_id, role = web.authz({ROLE_BUSINESS_REP})
    application = get_application_or_404(application_id)
    # priority 3: ownership
    if user_id != application["business_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    # priority 7: from-state
    if application["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_INVALID_STATE")
    # priority 8: business age >= 183 days at the submit instant
    business = get_business_or_404(application["business_id"])
    founded_on = business["founded_on"]
    if (db.now() - founded_on).total_seconds() < ACCREDITATION_MIN_AGE_DAYS * 86400:
        raise ApiError("ERR_BUSINESS_TOO_YOUNG")
    application["status"] = "SUBMITTED"
    application["submitted_at"] = db.now()
    db.touch(application)
    return web.success_object(serialize_application(application), status=200)


# ---------------------------------------------------------------------------
# POST /accreditation-applications/{id}/decision
# ---------------------------------------------------------------------------
@bp.route("/accreditation-applications/<application_id>/decision", methods=["POST"])
def decide_application(application_id):
    web.authz({ROLE_STANDARDS_REVIEWER})
    application = get_application_or_404(application_id)
    data = web.body()
    # priority 5: schema — decision enum, checklist enums, and the pinned
    # APPROVE-needs-all-PASS / DENY-needs-denial_reason shape rules
    decision = web.require_enum(data, "decision", DECISIONS)
    ad_result = web.require_enum(
        data, "advertising_practices_result", CHECKLIST_RESULTS
    )
    complaint_result = web.require_enum(
        data, "complaint_history_result", CHECKLIST_RESULTS
    )
    licensing_result = web.require_enum(data, "licensing_result", CHECKLIST_RESULTS)
    denial_reason = web.optional_string(data, "denial_reason")
    if decision == "APPROVE" and (
        ad_result != "PASS" or complaint_result != "PASS" or licensing_result != "PASS"
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "APPROVE requires all three checklist results to be PASS",
        )
    if decision == "DENY" and not denial_reason:
        raise ApiError("ERR_INVALID_REQUEST", "DENY requires denial_reason")
    # priority 7: from-state
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_INVALID_STATE")

    business = get_business_or_404(application["business_id"])
    now = db.now()

    if decision == "APPROVE":
        # priority 8: compliance gates
        for review in db.STORE.advertising_reviews.values():
            if review["business_id"] == business["id"] and review["status"] in (
                "UNDER_REVIEW",
                "REFERRED_TO_REGULATOR",
            ):
                raise ApiError("ERR_ADVERTISING_REVIEW_ADVERSE")
        counters = domain.complaint_counters(business["id"], now)
        if (
            counters["complaints_unanswered_36m"] != 0
            or counters["complaints_unresolved_36m"] != 0
        ):
            raise ApiError("ERR_ADVERSE_COMPLAINT_HISTORY")
        # priority 11: fiscal gate
        for invoice in db.STORE.invoices.values():
            if invoice["business_id"] != business["id"]:
                continue
            if (
                invoice["status"] == "OVERDUE"
                and domain.invoice_balance_cents(invoice) > 0
            ):
                raise ApiError("ERR_OUTSTANDING_DUES_BALANCE")
            if (
                invoice["status"] == "VOID"
                and invoice["voided_at"] is not None
                and now - invoice["voided_at"] <= timedelta(days=VOID_RECENCY_DAYS)
            ):
                raise ApiError("ERR_OUTSTANDING_DUES_BALANCE")

    application["advertising_practices_result"] = ad_result
    application["complaint_history_result"] = complaint_result
    application["licensing_result"] = licensing_result
    application["decided_at"] = now

    if decision == "DENY":
        application["denial_reason"] = denial_reason
        application["status"] = "DENIED"
        db.touch(application)
        return web.success_object(serialize_application(application), status=200)

    # APPROVE: freeze every pricing input at issue time and mint the invoice
    bureau = db.STORE.bureaus.get(business["bureau_id"])
    local_fee = bureau["local_dues_fee_cents"] if bureau is not None else 0
    base, amount_due, installments = domain.compute_dues(
        business["size_tier"], local_fee, application["billing_plan"]
    )
    invoice = db.new_entity(
        "invoices",
        {
            "business_id": business["id"],
            "application_id": application["id"],
            "billing_plan": application["billing_plan"],
            "size_tier_at_issue": business["size_tier"],
            "base_amount_cents": base,
            "local_fee_cents": local_fee,
            "amount_due_cents": amount_due,
            "installments": installments,
            "paid_cents": 0,
            "refunded_cents": 0,
            "balance_cents": amount_due,
            "status": "ISSUED",
            "issued_at": now,
            "due_date": now + timedelta(days=INVOICE_DUE_DAYS),
            "voided_at": None,
        },
    )
    application["dues_invoice_id"] = invoice["id"]
    application["status"] = "APPROVED_PENDING_DUES"
    db.touch(application)
    return web.success_object(serialize_application(application), status=200)


# ---------------------------------------------------------------------------
# GET /businesses/{id}/dues-invoices
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/dues-invoices", methods=["GET"])
def list_invoices(business_id):
    web.authz(APP_LIST_ROLES)
    get_business_or_404(business_id)
    status = request.args.get("status")
    items = [i for i in db.STORE.invoices.values() if i["business_id"] == business_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return web.paginated_entities(items, serialize_invoice)


# ---------------------------------------------------------------------------
# POST /dues-invoices/{id}/ledger-entries
# ---------------------------------------------------------------------------
@bp.route("/dues-invoices/<invoice_id>/ledger-entries", methods=["POST"])
def post_ledger_entry(invoice_id):
    user_id, role = web.authz({ROLE_BUREAU_ADMIN, ROLE_BUSINESS_REP})
    invoice = get_invoice_or_404(invoice_id)
    data = web.body()
    # priority 5: schema
    kind = web.require_enum(data, "kind", LEDGER_KINDS)
    amount_cents = web.require_int(data, "amount_cents", minimum=1)
    # kind-level authorization: PAYMENT is the BusinessRep operation,
    # REFUND is the BureauAdmin operation
    if kind == "PAYMENT" and role != ROLE_BUSINESS_REP:
        raise ApiError("ERR_UNAUTHORIZED")
    if kind == "REFUND" and role != ROLE_BUREAU_ADMIN:
        raise ApiError("ERR_UNAUTHORIZED")
    # priority 3: ownership on payments
    if kind == "PAYMENT" and user_id != invoice["business_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    # priority 7: VOID / REFUNDED reject all new entries
    if invoice["status"] in ("VOID", "REFUNDED"):
        raise ApiError("ERR_INVOICE_INVALID_STATE")
    # priority 11: fiscal bounds
    balance = domain.invoice_balance_cents(invoice)
    net_paid = invoice["paid_cents"] - invoice["refunded_cents"]
    if kind == "PAYMENT" and amount_cents > balance:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")
    if kind == "REFUND" and amount_cents > net_paid:
        raise ApiError("ERR_REFUND_EXCEEDS_PAID")

    business = db.STORE.businesses.get(invoice["business_id"])

    if kind == "PAYMENT":
        invoice["paid_cents"] += amount_cents
        new_balance = domain.invoice_balance_cents(invoice)
        if new_balance == 0:
            invoice["status"] = "PAID"
            invoice["balance_cents"] = 0
            # accreditation cascade: the moment the invoice is paid in full
            application = db.STORE.applications.get(invoice["application_id"])
            if (
                application is not None
                and application["status"] == "APPROVED_PENDING_DUES"
            ):
                application["status"] = "ACCREDITED"
                db.touch(application)
            if business is not None and business["accreditation_status"] in (
                "NOT_ACCREDITED",
                "SUSPENDED",
            ):
                business["accreditation_status"] = "ACCREDITED"
                db.touch(business)
        else:
            invoice["balance_cents"] = new_balance
            if invoice["status"] == "ISSUED":
                invoice["status"] = "PARTIALLY_PAID"
            # PARTIALLY_PAID stays PARTIALLY_PAID; OVERDUE stays OVERDUE
    else:  # REFUND
        invoice["refunded_cents"] += amount_cents
        net_paid = invoice["paid_cents"] - invoice["refunded_cents"]
        if invoice["status"] == "PARTIALLY_PAID":
            if net_paid == 0:
                invoice["status"] = "ISSUED"
        elif invoice["status"] == "PAID":
            if net_paid == 0:
                invoice["status"] = "REFUNDED"
            else:
                invoice["status"] = "PARTIALLY_PAID"
        # ISSUED / OVERDUE: refund mutates balances only, status unchanged
        invoice["balance_cents"] = domain.invoice_balance_cents(invoice)
    db.touch(invoice)

    # bureau dues_collected_cents recomputes (live-derived value; bump here)
    if business is not None:
        bureau = db.STORE.bureaus.get(business["bureau_id"])
        if bureau is not None:
            db.touch(bureau)

    return web.success_object(serialize_invoice(invoice), status=201)
