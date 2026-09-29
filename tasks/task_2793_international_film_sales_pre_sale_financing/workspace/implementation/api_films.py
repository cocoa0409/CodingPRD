"""Films and sales agency agreements."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint

import calc
from calc import EXPENSE_LOG_TOLERANCE
from envelope import created, ok, ok_list
from errors import ApiError
from serializers import agreement_out, film_out
from store import (
    accounts_of_film,
    agreements_of_film,
    base_row,
    contracts_of_film,
    db,
    get_agreement,
    get_film,
    now,
    touch,
    valuations_of_film,
)
from util import ZERO2, add_months, q2
from validation import actor, body, page, require_roles

bp = Blueprint("films", __name__)

GENRES = ("ACTION", "DRAMA", "COMEDY", "THRILLER", "DOCUMENTARY")
COMPLETION_STATUSES = ("SCRIPT", "IN_PRODUCTION", "POST", "DELIVERED")
FILM_STATUSES = ("DEVELOPMENT", "PACKAGING", "IN_MARKET", "SOLD_OUT", "WRAPPED")
AGREEMENT_STATUSES = ("DRAFT", "EXECUTED", "TERMINATED", "EXPIRED")

READ_ROLES = (
    "SalesAgent",
    "HeadOfSales",
    "DeliveryManager",
    "CollectionAgent",
    "Lender",
    "PlatformAdmin",
)


# --------------------------------------------------------------------- films


@bp.post("/films")
@require_roles("PlatformAdmin")
def create_film():
    payload = body()
    row = base_row()
    row.update(
        {
            "title": payload.req_string("title"),
            "genre": payload.req_enum("genre", GENRES),
            "production_budget_usd": q2(payload.req_number("production_budget_usd")),
            "principal_cast_score": payload.req_int("principal_cast_score", 0, 100),
            "completion_status": payload.opt_enum(
                "completion_status", COMPLETION_STATUSES, "SCRIPT"
            ),
            "estimated_delivery_date": payload.req_instant("estimated_delivery_date"),
            "theatrical_release_date": payload.req_instant("theatrical_release_date"),
            "sales_status": "DEVELOPMENT",
        }
    )
    db.films[row["id"]] = row
    return created(film_out(row))


@bp.get("/films")
@require_roles(*READ_ROLES)
def list_films():
    from flask import request

    rows = list(db.films.values())
    sales_status = request.args.get("sales_status")
    genre = request.args.get("genre")
    if sales_status:
        rows = [r for r in rows if r["sales_status"] == sales_status]
    if genre:
        rows = [r for r in rows if r["genre"] == genre]
    # created_at DESC then id ASC
    rows.sort(key=lambda r: r["id"])
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    items, meta = page(rows, film_out)
    return ok_list(items, meta)


@bp.get("/films/<film_id>")
@require_roles(*READ_ROLES)
def read_film(film_id):
    return ok(film_out(get_film(film_id)))


@bp.patch("/films/<film_id>")
@require_roles("PlatformAdmin")
def patch_film(film_id):
    film = get_film(film_id)
    payload = body()
    completion_status = payload.opt_enum("completion_status", COMPLETION_STATUSES)
    cast_score = payload.opt_int("principal_cast_score", 0, 100)
    theatrical = payload.opt_instant("theatrical_release_date")
    estimated = payload.opt_instant("estimated_delivery_date")

    cast_changed = cast_score is not None and cast_score != film["principal_cast_score"]
    if completion_status is not None:
        film["completion_status"] = completion_status
    if cast_score is not None:
        film["principal_cast_score"] = cast_score
    if theatrical is not None:
        film["theatrical_release_date"] = theatrical
    if estimated is not None:
        film["estimated_delivery_date"] = estimated
    touch(film)
    if cast_changed:
        for valuation in valuations_of_film(film["id"]):
            if valuation["status"] == "PUBLISHED":
                valuation["status"] = "STALE"
                touch(valuation)
    return ok(film_out(film))


def wrap_film(film):
    """The WRAPPED cascade, shared by the film and agreement state endpoints."""
    film["sales_status"] = "WRAPPED"
    touch(film)
    for contract in contracts_of_film(film["id"]):
        if contract["negotiation_status"] in ("OFFERED", "COUNTERED"):
            contract["negotiation_status"] = "LAPSED"
            touch(contract)
    for account in accounts_of_film(film["id"]):
        if account["status"] == "OPEN":
            account["status"] = "CLOSED"
            touch(account)
    for agreement in agreements_of_film(film["id"]):
        if agreement["status"] == "EXECUTED":
            agreement["status"] = "EXPIRED"
            touch(agreement)


@bp.post("/films/<film_id>/state")
@require_roles("HeadOfSales", "PlatformAdmin")
def film_state(film_id):
    film = get_film(film_id)
    payload = body()
    to_status = payload.req_enum("to_status", FILM_STATUSES)
    current = film["sales_status"]

    if to_status == current:
        raise ApiError("ERR_INVALID_STATE")
    if to_status == "PACKAGING":
        if current != "DEVELOPMENT":
            raise ApiError("ERR_INVALID_STATE")
        if calc.executed_agreement(film_id) is None:
            raise ApiError(
                "ERR_INVALID_STATE",
                "The film has no EXECUTED sales agency agreement.",
            )
        film["sales_status"] = "PACKAGING"
        touch(film)
    elif to_status == "IN_MARKET":
        if current != "PACKAGING":
            raise ApiError("ERR_INVALID_STATE")
        if calc.published_count(film) < 1:
            raise ApiError(
                "ERR_INVALID_STATE", "The film has no published territory valuation."
            )
        if calc.agreement_in_force(film_id) is None:
            raise ApiError("ERR_INVALID_STATE", "No agency agreement is in force.")
        film["sales_status"] = "IN_MARKET"
        touch(film)
    elif to_status == "WRAPPED":
        if current not in ("IN_MARKET", "SOLD_OUT"):
            raise ApiError("ERR_INVALID_STATE")
        for contract in contracts_of_film(film_id):
            if contract["negotiation_status"] in calc.LIVE_NEGOTIATION:
                raise ApiError(
                    "ERR_INVALID_STATE", "The film still has live contracts."
                )
        for account in accounts_of_film(film_id):
            if calc.account_balance(account) != ZERO2:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "Every collection account balance must be zero.",
                )
        wrap_film(film)
    else:
        # DEVELOPMENT and SOLD_OUT are never operator reachable.
        raise ApiError("ERR_INVALID_STATE")
    return ok(film_out(film))


# --------------------------------------------------------- agency agreements


@bp.post("/films/<film_id>/agency-agreements")
@require_roles("HeadOfSales")
def create_agreement(film_id):
    film = get_film(film_id)
    payload = body()
    commission_pct = payload.req_number(
        "commission_pct", minimum=Decimal("0"), maximum=Decimal("0.25"), exclusive_min=True
    )
    expense_cap = q2(payload.req_number("expense_cap_usd"))
    term_months = payload.req_int("term_months", minimum=6)
    term_start = payload.req_instant("term_start_date")
    row = base_row()
    row.update(
        {
            "film_id": film["id"],
            "commission_pct": commission_pct,
            "expense_cap_usd": expense_cap,
            "term_months": term_months,
            "term_start_date": term_start,
            "term_end_date": add_months(term_start, term_months),
            "status": "DRAFT",
            "expenses_incurred_usd": ZERO2,
            "expenses_recouped_usd": ZERO2,
            "commission_earned_usd": ZERO2,
            "gross_collected_usd": ZERO2,
            "executed_by_user_id": None,
        }
    )
    db.agreements[row["id"]] = row
    return created(agreement_out(row))


@bp.get("/films/<film_id>/agency-agreements")
@require_roles("SalesAgent", "HeadOfSales", "CollectionAgent", "Lender", "PlatformAdmin")
def list_agreements(film_id):
    film = get_film(film_id)
    items, meta = page(agreements_of_film(film["id"]), agreement_out)
    return ok_list(items, meta)


@bp.post("/agency-agreements/<agreement_id>/state")
@require_roles("HeadOfSales")
def agreement_state(agreement_id):
    agreement = get_agreement(agreement_id)
    payload = body()
    to_status = payload.req_enum("to_status", AGREEMENT_STATUSES)
    current = agreement["status"]
    film = db.films.get(agreement["film_id"])

    if to_status == current:
        raise ApiError("ERR_INVALID_STATE")
    if to_status == "EXECUTED":
        if current != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        for other in agreements_of_film(agreement["film_id"]):
            if other["id"] != agreement["id"] and other["status"] == "EXECUTED":
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "Another agreement for this film is already EXECUTED.",
                )
        agreement["status"] = "EXECUTED"
        agreement["executed_by_user_id"] = actor()
        agreement["term_end_date"] = add_months(
            agreement["term_start_date"], agreement["term_months"]
        )
        touch(agreement)
    elif to_status == "TERMINATED":
        if current != "EXECUTED":
            raise ApiError("ERR_INVALID_STATE")
        for contract in contracts_of_film(agreement["film_id"]):
            if contract["negotiation_status"] in calc.LIVE_NEGOTIATION:
                raise ApiError(
                    "ERR_INVALID_STATE", "The film still has live contracts."
                )
        agreement["status"] = "TERMINATED"
        touch(agreement)
        if film is not None and film["sales_status"] in ("IN_MARKET", "SOLD_OUT"):
            wrap_film(film)
    else:
        # EXPIRED is only ever reached through the film WRAPPED cascade.
        raise ApiError("ERR_INVALID_STATE")
    return ok(agreement_out(agreement))


@bp.post("/agency-agreements/<agreement_id>/expenses")
@require_roles("SalesAgent", "HeadOfSales")
def log_expense(agreement_id):
    agreement = get_agreement(agreement_id)
    payload = body()
    amount = q2(payload.req_number("amount_usd"))
    payload.req_string("memo")
    if calc.agreement_in_force(agreement["film_id"]) is None:
        raise ApiError("ERR_AGENCY_AGREEMENT_NOT_IN_FORCE")
    ceiling = q2(agreement["expense_cap_usd"] * EXPENSE_LOG_TOLERANCE)
    if amount <= 0 or q2(agreement["expenses_incurred_usd"] + amount) > ceiling:
        raise ApiError("ERR_EXPENSE_LOG_LIMIT")
    agreement["expenses_incurred_usd"] = q2(agreement["expenses_incurred_usd"] + amount)
    touch(agreement)
    calc.resync_expense_tier(agreement["film_id"], agreement)
    return ok(agreement_out(agreement))
