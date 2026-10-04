"""Benefit providers, license agreements, and royalty statements."""

from datetime import date

from flask import Blueprint, request

from auth import forbidden, require_roles
from db import locked, mint, store, touch
from serializers import agreement_view, provider_view, statement_view
from services import (
    AGREEMENT_PROBATION_THRESHOLD,
    PROVIDER_SUSPENSION_THRESHOLD,
    agreement_trailing_count,
    clock_date,
    compute_royalty_cents,
    provider_trailing_count,
)
from util import err, get_body, is_int, paginate, parse_date_strict, require_str, success_object

bp = Blueprint("providers", __name__)

PRODUCT_CATEGORIES = {
    "INSURANCE_HEALTH",
    "INSURANCE_AUTO",
    "INSURANCE_LIFE",
    "FINANCIAL_SERVICES",
    "TRAVEL_SERVICES",
    "HOME_SERVICES",
}

AGREEMENT_ACTION_ROLES = {
    "ACTIVATE": "GovernanceOfficer",
    "TERMINATE": "GovernanceOfficer",
    "PROBATE": "OversightAnalyst",
    "REINSTATE": "OversightAnalyst",
}

AGREEMENT_VALID_FROM = {
    "ACTIVATE": ("DRAFT",),
    "PROBATE": ("ACTIVE",),
    "REINSTATE": ("PROBATION",),
    "TERMINATE": ("DRAFT", "ACTIVE", "PROBATION"),
}

PROVIDER_READ_ROLES = ("ProviderManager", "GovernanceOfficer", "OversightAnalyst", "FinanceController", "PlatformAdmin")


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

@bp.post("/api/providers")
@locked
def create_provider():
    require_roles("GovernanceOfficer")
    body = get_body()
    legal_name = require_str(body, "legal_name")
    provider = mint(store.providers)
    provider.update({"legal_name": legal_name, "status": "APPLICANT", "royalty_balance_cents": 0})
    return success_object(provider_view(provider), status=201)


@bp.get("/api/providers/<provider_id>")
@locked
def get_provider(provider_id):
    require_roles(*PROVIDER_READ_ROLES)
    provider = store.providers.get(provider_id)
    if provider is None:
        err("ERR_NOT_FOUND", 404, "Provider not found")
    return success_object(provider_view(provider))


@bp.post("/api/providers/<provider_id>/admit")
@locked
def admit_provider(provider_id):
    require_roles("GovernanceOfficer")
    provider = store.providers.get(provider_id)
    if provider is None:
        err("ERR_NOT_FOUND", 404, "Provider not found")
    if provider["status"] == "APPLICANT":
        provider["status"] = "LICENSED"
        touch(provider)
    elif provider["status"] == "SUSPENDED":
        # Re-admission is threshold-gated; probationed agreements are NOT
        # auto-reinstated (each needs its own REINSTATE action).
        if provider_trailing_count(provider_id) >= PROVIDER_SUSPENSION_THRESHOLD:
            err("ERR_REINSTATE_BLOCKED", 422, "Provider escalations_trailing_12mo has not fallen below 5")
        provider["status"] = "LICENSED"
        touch(provider)
    return success_object(provider_view(provider))


# ---------------------------------------------------------------------------
# License agreements
# ---------------------------------------------------------------------------

@bp.post("/api/providers/<provider_id>/license-agreements")
@locked
def create_agreement(provider_id):
    user_id, _ = require_roles("ProviderManager")
    # Rung 3: entity-backed ownership (string comparison on the path id).
    if user_id != provider_id:
        forbidden("ProviderManager may only draft agreements for their own provider")
    body = get_body()
    # Rung 5: schema.
    category = body.get("product_category")
    if category is None or category not in PRODUCT_CATEGORIES:
        err("ERR_INVALID_REQUEST", 400, "product_category is required and must be a declared category")
    eff_from_raw = body.get("effective_from")
    eff_to_raw = body.get("effective_to")
    eff_from = parse_date_strict(eff_from_raw)
    eff_to = parse_date_strict(eff_to_raw)
    if eff_from is None or eff_to is None:
        err("ERR_INVALID_REQUEST", 400, "effective_from and effective_to are required ISO dates")
    if eff_to <= eff_from:
        err("ERR_INVALID_REQUEST", 400, "effective_to must be strictly after effective_from")
    expected_version = body.get("expected_provider_version")
    if expected_version is None or not is_int(expected_version):
        err("ERR_INVALID_REQUEST", 400, "expected_provider_version is required and must be an integer")
    # Rung 6: existence.
    provider = store.providers.get(provider_id)
    if provider is None:
        err("ERR_NOT_FOUND", 404, "Provider not found")
    # Rung 7: optimistic concurrency.
    if expected_version != provider["version"]:
        err("ERR_STALE_PROVIDER_VERSION", 412, "expected_provider_version does not match the provider's current version")
    # Rung 9: cross-entity state.
    if provider["status"] != "LICENSED":
        err("ERR_PROVIDER_NOT_LICENSED", 409, "Provider must be LICENSED to draft an agreement")
    # Rung 11: category coverage unique among DRAFT/ACTIVE agreements.
    for other in store.agreements.values():
        if (
            other["provider_id"] == provider_id
            and other["product_category"] == category
            and other["status"] in ("DRAFT", "ACTIVE")
        ):
            err("ERR_DUPLICATE_CATEGORY_AGREEMENT", 409, "A DRAFT or ACTIVE agreement already exists for this provider and category")
    agreement = mint(store.agreements)
    agreement.update(
        {
            "provider_id": provider_id,
            "product_category": category,
            "effective_from": eff_from_raw,
            "effective_to": eff_to_raw,
            "status": "DRAFT",
            "probation_count": 0,
            "recognized_royalty_cents": 0,
            "provisional_outstanding_cents": 0,
        }
    )
    # Drafting is a provider mutation.
    touch(provider)
    return success_object(agreement_view(agreement), status=201)


@bp.get("/api/providers/<provider_id>/license-agreements")
@locked
def list_provider_agreements(provider_id):
    require_roles(*PROVIDER_READ_ROLES)
    if provider_id not in store.providers:
        err("ERR_NOT_FOUND", 404, "Provider not found")
    status_filter = request.args.get("status")
    agreements = [
        a
        for a in sorted(store.agreements.values(), key=lambda r: r["_seq"])
        if a["provider_id"] == provider_id
    ]
    if status_filter is not None:
        agreements = [a for a in agreements if a["status"] == status_filter]
    return paginate([agreement_view(a) for a in agreements])


@bp.get("/api/license-agreements/<agreement_id>")
@locked
def get_agreement(agreement_id):
    require_roles(*PROVIDER_READ_ROLES)
    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        err("ERR_NOT_FOUND", 404, "License agreement not found")
    return success_object(agreement_view(agreement))


@bp.post("/api/license-agreements/<agreement_id>/transitions")
@locked
def transition_agreement(agreement_id):
    _, role = require_roles("GovernanceOfficer", "OversightAnalyst")
    body = get_body()
    action = body.get("action")
    # Rung 2: the role must own the requested action (checked only when the
    # action names a declared transition; otherwise schema rung 5 rejects it).
    if action in AGREEMENT_ACTION_ROLES and role != AGREEMENT_ACTION_ROLES[action]:
        forbidden("Role %s may not perform action %s" % (role, action))
    # Rung 5: schema.
    if action not in AGREEMENT_ACTION_ROLES:
        err("ERR_INVALID_REQUEST", 400, "action must be one of ACTIVATE, PROBATE, REINSTATE, TERMINATE")
    # Rung 6: existence.
    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        err("ERR_NOT_FOUND", 404, "License agreement not found")
    # Rung 8: transition valid from the current status.
    if agreement["status"] not in AGREEMENT_VALID_FROM[action]:
        err("ERR_AGREEMENT_STATE", 409, "Action %s is not valid from status %s" % (action, agreement["status"]))

    provider = store.providers.get(agreement["provider_id"])
    if action == "ACTIVATE":
        # Rung 9: provider must be LICENSED.
        if provider is None or provider["status"] != "LICENSED":
            err("ERR_PROVIDER_NOT_LICENSED", 409, "Provider must be LICENSED to activate an agreement")
        # Rung 11: the clock date must lie inside the window (both bounds inclusive).
        today = clock_date()
        if not (date.fromisoformat(agreement["effective_from"]) <= today <= date.fromisoformat(agreement["effective_to"])):
            err("ERR_AGREEMENT_NOT_IN_WINDOW", 422, "Clock date is outside the agreement window")
        # Rung 11: no other ACTIVE agreement for (provider, category).
        for other in store.agreements.values():
            if (
                other["id"] != agreement["id"]
                and other["provider_id"] == agreement["provider_id"]
                and other["product_category"] == agreement["product_category"]
                and other["status"] == "ACTIVE"
            ):
                err("ERR_DUPLICATE_CATEGORY_AGREEMENT", 409, "Another ACTIVE agreement already covers this provider and category")
        agreement["status"] = "ACTIVE"
    elif action == "PROBATE":
        agreement["status"] = "PROBATION"
        agreement["probation_count"] += 1
    elif action == "REINSTATE":
        # Rung 9: provider must be LICENSED.
        if provider is None or provider["status"] != "LICENSED":
            err("ERR_PROVIDER_NOT_LICENSED", 409, "Provider must be LICENSED to reinstate an agreement")
        # Rung 11: escalation threshold must have cleared.
        if agreement_trailing_count(agreement_id) >= AGREEMENT_PROBATION_THRESHOLD:
            err("ERR_REINSTATE_BLOCKED", 422, "Agreement escalations_trailing_12mo is still at or above 3")
        agreement["status"] = "ACTIVE"
    else:  # TERMINATE
        agreement["status"] = "TERMINATED"
    touch(agreement)
    return success_object(agreement_view(agreement))


# ---------------------------------------------------------------------------
# Royalty statements
# ---------------------------------------------------------------------------

@bp.post("/api/license-agreements/<agreement_id>/royalty-statements")
@locked
def submit_statement(agreement_id):
    user_id, _ = require_roles("ProviderManager")
    agreement = store.agreements.get(agreement_id)
    # Rung 3: ownership compares X-User-ID to the provider that owns the
    # agreement (requires the agreement; nonexistent ids fall through to the
    # schema/existence rungs, which a missing resource resolves as 404).
    if agreement is not None and user_id != agreement["provider_id"]:
        forbidden("ProviderManager may only submit statements for their own provider")
    body = get_body()
    # Rung 5: schema.
    period_year = body.get("period_year")
    period_quarter = body.get("period_quarter")
    reported_sales = body.get("reported_sales_cents")
    expected_version = body.get("expected_agreement_version")
    if period_year is None or not is_int(period_year):
        err("ERR_INVALID_REQUEST", 400, "period_year is required and must be an integer")
    if period_quarter is None or not is_int(period_quarter) or not (1 <= period_quarter <= 4):
        err("ERR_INVALID_REQUEST", 400, "period_quarter is required and must be between 1 and 4")
    if reported_sales is None or not is_int(reported_sales):
        err("ERR_INVALID_REQUEST", 400, "reported_sales_cents is required and must be an integer")
    if expected_version is None or not is_int(expected_version):
        err("ERR_INVALID_REQUEST", 400, "expected_agreement_version is required and must be an integer")
    # Rung 6: existence.
    if agreement is None:
        err("ERR_NOT_FOUND", 404, "License agreement not found")
    # Rung 7: optimistic concurrency.
    if expected_version != agreement["version"]:
        err("ERR_STALE_AGREEMENT_VERSION", 412, "expected_agreement_version does not match the agreement's current version")
    # Rung 11: one live statement per quarter; a FINALIZED quarter is closed.
    prior_provisional = None
    for s in store.statements.values():
        if (
            s["license_agreement_id"] == agreement_id
            and s["period_year"] == period_year
            and s["period_quarter"] == period_quarter
        ):
            if s["status"] == "FINALIZED":
                err("ERR_QUARTER_ALREADY_FINALIZED", 409, "This quarter already has a FINALIZED statement")
            if s["status"] == "PROVISIONAL":
                prior_provisional = s

    provider = store.providers.get(agreement["provider_id"])
    # Supersede: reverse the old provisional posting first, then post the new.
    if prior_provisional is not None:
        agreement["provisional_outstanding_cents"] -= prior_provisional["provisional_royalty_cents"]
        if provider is not None:
            provider["royalty_balance_cents"] -= prior_provisional["provisional_royalty_cents"]
            touch(provider)
        prior_provisional["status"] = "SUPERSEDED"
        touch(prior_provisional)
        # The bucket reversal is itself an agreement mutation.
        touch(agreement)

    provisional = compute_royalty_cents(agreement_id, period_year, period_quarter, reported_sales)
    statement = mint(store.statements)
    statement.update(
        {
            "license_agreement_id": agreement_id,
            "period_year": period_year,
            "period_quarter": period_quarter,
            "reported_sales_cents": reported_sales,
            "audited_sales_cents": None,
            "provisional_royalty_cents": provisional,
            "final_royalty_cents": None,
            "delta_cents": None,
            "status": "PROVISIONAL",
        }
    )
    agreement["provisional_outstanding_cents"] += provisional
    if provider is not None:
        provider["royalty_balance_cents"] += provisional
        touch(provider)
    # The submission's own side effects increment the agreement version again.
    touch(agreement)
    return success_object(statement_view(statement), status=201)


@bp.get("/api/license-agreements/<agreement_id>/royalty-statements")
@locked
def list_statements(agreement_id):
    require_roles("ProviderManager", "FinanceController", "PlatformAdmin")
    if agreement_id not in store.agreements:
        err("ERR_NOT_FOUND", 404, "License agreement not found")
    status_filter = request.args.get("status")
    statements = [
        s
        for s in sorted(store.statements.values(), key=lambda r: r["_seq"])
        if s["license_agreement_id"] == agreement_id
    ]
    if status_filter is not None:
        statements = [s for s in statements if s["status"] == status_filter]
    return paginate([statement_view(s) for s in statements])


@bp.post("/api/royalty-statements/<statement_id>/finalize")
@locked
def finalize_statement(statement_id):
    require_roles("FinanceController")
    body = get_body()
    audited = body.get("audited_sales_cents")
    if audited is None or not is_int(audited):
        err("ERR_INVALID_REQUEST", 400, "audited_sales_cents is required and must be an integer")
    statement = store.statements.get(statement_id)
    if statement is None:
        err("ERR_NOT_FOUND", 404, "Royalty statement not found")
    if statement["status"] != "PROVISIONAL":
        err("ERR_STATEMENT_NOT_PROVISIONAL", 409, "Only a PROVISIONAL statement can be finalized")

    final = compute_royalty_cents(
        statement["license_agreement_id"],
        statement["period_year"],
        statement["period_quarter"],
        audited,
    )
    delta = final - statement["provisional_royalty_cents"]
    statement["audited_sales_cents"] = audited
    statement["final_royalty_cents"] = final
    statement["delta_cents"] = delta
    statement["status"] = "FINALIZED"
    touch(statement)

    agreement = store.agreements.get(statement["license_agreement_id"])
    provider = None
    if agreement is not None:
        # Bucket conservation: recognized += final; provisional_outstanding -= provisional.
        agreement["recognized_royalty_cents"] += final
        agreement["provisional_outstanding_cents"] -= statement["provisional_royalty_cents"]
        touch(agreement)
        provider = store.providers.get(agreement["provider_id"])
    if provider is not None:
        provider["royalty_balance_cents"] += delta
        touch(provider)
    return success_object(statement_view(statement))
