"""Credit application filing, adjudication and account minting."""

from flask import Blueprint

import auth
import calc
import clock
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("applications", __name__, url_prefix="/retail")

APP_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer")
KINDS = ("REVOLVING", "LEASE")
SOURCES = ("FRANCHISEE", "FRANCHISOR")
ACTIONS = ("REVIEW", "APPROVE", "DECLINE", "WITHDRAW", "REOPEN")
DECIDED = ("APPROVED", "DECLINED", "WITHDRAWN")


@bp.post("/shop-locations/<shop_id>/credit-applications")
def file_application(shop_id):
    user_id, role = auth.require("FranchiseOwner", "CreditOfficer")
    shop = lookup.shop(shop_id)
    auth.ensure_owned(user_id, role, auth.shop_owner_id(shop))
    payload = envelope.body()
    technician_id = envelope.as_str(payload, "technician_id")
    requested_limit_cents = envelope.as_int(payload, "requested_limit_cents", minimum=0)
    requested_kind = envelope.as_enum(payload, "requested_kind", KINDS)
    requested_term_months = envelope.as_int(payload, "requested_term_months", required=False,
                                            default=None, minimum=0)
    employment_verified = envelope.as_bool(payload, "employment_verified")
    months_in_trade = envelope.as_int(payload, "months_in_trade", minimum=0)
    prior_delinquency_count = envelope.as_int(payload, "prior_delinquency_count", minimum=0)
    decision_source = envelope.as_enum(payload, "decision_source", SOURCES)

    technician = lookup.technician(technician_id)
    if technician.get("current_shop_location_id") != shop["id"]:
        fail("ERR_INVALID_REQUEST",
             "The applicant's current shop is not the shop this application is filed under.")

    if requested_kind == "LEASE" and requested_term_months is None:
        fail("ERR_LEASE_TERM_REQUIRED")
    if requested_limit_cents > calc.CREDIT_ABSOLUTE_CAP_CENTS:
        fail("ERR_CREDIT_REQUEST_ABOVE_CAP")

    application = store.create(
        store.applications,
        shop_location_id=shop["id"],
        technician_id=technician["id"],
        requested_limit_cents=requested_limit_cents,
        requested_kind=requested_kind,
        requested_term_months=requested_term_months if requested_kind == "LEASE" else 0,
        employment_verified=employment_verified,
        months_in_trade=months_in_trade,
        prior_delinquency_count=prior_delinquency_count,
        decision_source=decision_source,
        application_status="SUBMITTED",
        decision_score=0,
        approved_limit_cents=0,
        approved_kind=None,
        approved_term_months=0,
        decision_note=None,
    )
    application["decision_score"] = calc.credit_decision_score(application)
    return envelope.ok(application, 201)


@bp.get("/credit-applications")
def list_applications():
    auth.require(*APP_ROLES)
    rows = envelope.filter_query(store.ordered(store.applications), {
        "application_status": "application_status",
        "decision_source": "decision_source",
        "technician_id": "technician_id",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/credit-applications/<application_id>")
def get_application(application_id):
    auth.require(*APP_ROLES)
    return envelope.ok(lookup.application(application_id))


@bp.post("/credit-applications/<application_id>/status")
def advance_application(application_id):
    user_id, role = auth.require("CreditOfficer", "FranchiseOwner")
    application = lookup.application(application_id)
    auth.ensure_owned(user_id, role, auth.application_owner_id(application))
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", ACTIONS)

    status = application.get("application_status")
    source = application.get("decision_source")

    if action == "REVIEW":
        if role != "CreditOfficer":
            fail("ERR_UNAUTHORIZED")
        if status in DECIDED:
            fail("ERR_APPLICATION_ALREADY_DECIDED")
        if status != "SUBMITTED" or source != "FRANCHISOR":
            fail("ERR_INVALID_STATE")
        store.set_field(application, "application_status", "UNDER_REVIEW")
        store.set_field(application, "decision_score", calc.credit_decision_score(application))
    elif action == "APPROVE":
        if status in DECIDED:
            fail("ERR_APPLICATION_ALREADY_DECIDED")
        if source == "FRANCHISOR":
            if role != "CreditOfficer":
                fail("ERR_UNAUTHORIZED")
            if status != "UNDER_REVIEW":
                fail("ERR_INVALID_STATE")
            if application.get("decision_score", 0) < 55:
                fail("ERR_INVALID_STATE", "The decision score is below the franchisor hurdle.")
        else:
            if role != "FranchiseOwner":
                fail("ERR_UNAUTHORIZED")
            if status != "SUBMITTED":
                fail("ERR_INVALID_STATE")
            if application.get("decision_score", 0) < 40:
                fail("ERR_INVALID_STATE", "The decision score is below the franchisee hurdle.")
            if not application.get("employment_verified"):
                fail("ERR_INVALID_STATE", "Employment has not been verified.")
        _approve(application)
    elif action == "DECLINE":
        if status in DECIDED:
            fail("ERR_APPLICATION_ALREADY_DECIDED")
        if source == "FRANCHISOR":
            if role != "CreditOfficer":
                fail("ERR_UNAUTHORIZED")
            if status != "UNDER_REVIEW":
                fail("ERR_INVALID_STATE")
        else:
            if role != "FranchiseOwner":
                fail("ERR_UNAUTHORIZED")
            if status != "SUBMITTED":
                fail("ERR_INVALID_STATE")
        store.set_field(application, "application_status", "DECLINED")
        store.set_field(application, "approved_limit_cents", 0)
        store.set_field(application, "approved_kind", None)
        store.set_field(application, "approved_term_months", 0)
        store.set_field(application, "decision_note", "Application declined.")
    elif action == "WITHDRAW":
        if role != "FranchiseOwner":
            fail("ERR_UNAUTHORIZED")
        if status not in ("SUBMITTED", "UNDER_REVIEW"):
            fail("ERR_INVALID_STATE")
        store.set_field(application, "application_status", "WITHDRAWN")
        store.set_field(application, "decision_note", "Application withdrawn.")
    else:
        if role != "FranchiseOwner":
            fail("ERR_UNAUTHORIZED")
        if status != "DECLINED" or source != "FRANCHISEE":
            fail("ERR_INVALID_STATE")
        store.set_field(application, "application_status", "SUBMITTED")
        store.set_field(application, "decision_score", calc.credit_decision_score(application))

    store.stamp(application)
    return envelope.ok(application)


def _approve(application):
    score = application.get("decision_score", 0)
    requested = application.get("requested_limit_cents", 0)
    if requested > calc.CREDIT_ABSOLUTE_CAP_CENTS:
        fail("ERR_CREDIT_REQUEST_ABOVE_CAP")
    store.set_field(application, "application_status", "APPROVED")
    store.set_field(application, "approved_limit_cents",
                    calc.credit_decision_limit(score, requested))
    store.set_field(application, "approved_kind", application.get("requested_kind"))
    term = application.get("requested_term_months") or 0
    store.set_field(application, "approved_term_months",
                    0 if application.get("requested_kind") == "REVOLVING" else term)
    store.set_field(application, "decision_note", "Application approved.")


@bp.post("/credit-applications/<application_id>/accounts")
def mint_account(application_id):
    auth.require("CreditOfficer")
    application = lookup.application(application_id)
    payload = envelope.body()
    expected = envelope.as_int(payload, "expected_application_version")
    if expected != application.get("version"):
        fail("ERR_STALE_VERSION")
    if application.get("application_status") != "APPROVED":
        fail("ERR_APPLICATION_NOT_APPROVED")

    technician = lookup.technician(application.get("technician_id"))
    shop = store.shops.get(application.get("shop_location_id"))
    route = store.routes.get(shop.get("route_id")) if shop else None
    kind = application.get("approved_kind")
    limit = application.get("approved_limit_cents", 0)

    if kind == "REVOLVING":
        headroom = max(0, technician.get("credit_line_limit_cents", 0)
                       - technician.get("revolving_used_cents", 0))
        if limit > headroom:
            fail("ERR_CREDIT_LIMIT_EXCEEDED")

    term_months = application.get("approved_term_months", 0) or 0
    installment = calc.lease_amortization(0, term_months, "ACTIVE") if kind == "LEASE" else 0
    minimum_due = calc.minimum_payment_due(0, "ACTIVE", kind == "LEASE", installment)

    account = store.create(
        store.accounts,
        application_id=application["id"],
        technician_id=technician["id"],
        territory_id=route["id"] if route else None,
        account_kind=kind,
        credit_limit_cents=limit,
        term_months=application.get("approved_term_months", 0) or 0,
        account_status="ACTIVE",
        account_status_changed_at=clock.fmt_week(clock.now()),
        payment_due_weekday=route.get("visit_weekday", 1) if route else 1,
        recourse_holder=resolve_recourse_holder(route),
        is_lease_program=(kind == "LEASE"),
        is_revolving_program=(kind == "REVOLVING"),
        use_final_basis=(kind == "LEASE"),
        principal_balance_cents=0,
        accrued_finance_charge_cents=0,
        current_balance_cents=0,
        credit_available_cents=limit,
        next_due_weekday=route.get("visit_weekday", 1) if route else 1,
        missed_payment_count=0,
        last_payment_week_start=None,
        installment_due_cents=installment,
        minimum_payment_due_cents=minimum_due,
    )

    store.stamp(application)
    recompute.recompute_technician(technician)
    if route:
        recompute.recompute_franchisee_of_route(route)
    return envelope.ok(account, 201)


def resolve_recourse_holder(route):
    """Deterministic selection over in-force QUALIFIED territories."""
    current_week = clock.current_week_start()
    candidates = []
    if route is not None:
        if route.get("territory_development_status") == "QUALIFIED":
            start = route.get("in_force_from_week")
            end = route.get("in_force_to_week")
            started = start is not None and clock.parse_utc(start) <= current_week
            open_window = end is None or current_week < clock.parse_utc(end)
            if started and open_window:
                candidates.append(route)
    if not candidates:
        return "FRANCHISOR"
    chosen = min(candidates, key=lambda r: r.get("created_at") or "")
    if chosen.get("territory_model") == "FRANCHISEE_ASSUMED":
        return "FRANCHISOR"
    return "FRANCHISEE"
