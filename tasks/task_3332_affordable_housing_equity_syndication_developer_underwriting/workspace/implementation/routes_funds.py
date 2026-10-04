"""Syndication funds: formation, repricing, read view and subscriptions."""

from flask import Blueprint, request

import calc
import clock
import errors
import response
import state
import store
import validate

bp = Blueprint("funds", __name__)

READ_FUND = ("Underwriter", "AssetManager", "Investor", "PlatformAdmin")
DEFAULT_CLOSE_THRESHOLD = 0.85


def _blank_fund_fields():
    return {
        "status": "FORMING",
        "posture": "OPEN",
        "funded_equity_cents": 0,
        "subscribed_equity_cents": 0,
        "awarded_credits_total_cents": 0,
        "delivered_credits_total_cents": 0,
        "priced_value_cents": 0,
        "realized_value_cents": 0,
        "priced_yield_pct": 0.0,
        "realized_yield_pct": 0.0,
        "subscription_count": 0,
    }


def _summary(fund_id):
    projects = [p for p in state.projects_of_fund(fund_id) if p["status"] != "EXITED"]
    allocations_rows = []
    for project in projects:
        allocations_rows.extend(state.committed_allocations(project["id"]))
    latest = {p["id"]: state.latest_review(p["id"]) for p in projects}
    return calc.portfolio_summary(projects, allocations_rows, latest)


def _fund_view(fund):
    view = store.public(fund)
    view.update(_summary(fund["id"]))
    return view


@bp.post("/funds")
def create_fund():
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("Underwriter", "PlatformAdmin"))
    payload = validate.body(request)
    fund_name = validate.as_string(payload, "fund_name")
    target = validate.non_negative(validate.as_int(payload, "target_equity_cents"),
                                   "target_equity_cents")
    price = validate.non_negative(validate.as_number(payload, "price_per_credit_dollar"),
                                  "price_per_credit_dollar")
    target_yield = validate.non_negative(validate.as_number(payload, "target_yield_pct"),
                                         "target_yield_pct")
    threshold = validate.as_number(payload, "close_threshold_pct", required_field=False)
    if threshold is None:
        threshold = DEFAULT_CLOSE_THRESHOLD
    validate.non_negative(threshold, "close_threshold_pct")
    open_date = validate.as_datetime(payload, "subscription_open_date")
    close_date = validate.as_datetime(payload, "subscription_close_date")

    fields = {
        "fund_name": fund_name,
        "target_equity_cents": target,
        "price_per_credit_dollar": price,
        "target_yield_pct": target_yield,
        "close_threshold_pct": threshold,
        "subscription_open_date": open_date,
        "subscription_close_date": close_date,
    }
    fields.update(_blank_fund_fields())
    fund = store.create(store.funds, fields)
    state.recompute_fund(fund["id"])
    return response.ok(_fund_view(fund), 201)


@bp.get("/funds/<fund_id>")
def read_fund(fund_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, READ_FUND)
    fund = validate.get_fund(fund_id)
    state.recompute_fund(fund_id)
    return response.ok(_fund_view(fund), 200)


@bp.put("/funds/<fund_id>")
def update_fund(fund_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("Underwriter",))
    payload = validate.body(request)
    price = validate.as_number(payload, "price_per_credit_dollar", required_field=False)
    target_yield = validate.as_number(payload, "target_yield_pct", required_field=False)
    threshold = validate.as_number(payload, "close_threshold_pct", required_field=False)
    for name, value in (("price_per_credit_dollar", price), ("target_yield_pct", target_yield),
                        ("close_threshold_pct", threshold)):
        validate.non_negative(value, name)
    expected = validate.as_int(payload, "expected_fund_version")

    fund = validate.get_fund(fund_id)
    if int(fund["version"]) != int(expected):
        errors.fail(errors.ERR_STALE_VERSION, "expected_fund_version is not current.")

    if price is not None:
        fund["price_per_credit_dollar"] = price
    if target_yield is not None:
        fund["target_yield_pct"] = target_yield
    if threshold is not None:
        fund["close_threshold_pct"] = threshold

    version_before = int(fund["version"])
    state.recompute_fund(fund_id)
    if int(fund["version"]) == version_before:
        store.touch(fund)
    return response.ok(_fund_view(fund), 200)


@bp.post("/funds/<fund_id>/subscriptions")
def create_subscription(fund_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, ("Investor", "PlatformAdmin"))
    payload = validate.body(request)
    investor_id = validate.as_string(payload, "investor_id")
    committed = validate.non_negative(validate.as_int(payload, "committed_cents"), "committed_cents")
    schedule = validate.as_payin_schedule(payload)
    expected = validate.as_int(payload, "expected_fund_version")

    fund = validate.get_fund(fund_id)
    investor = validate.get_investor(investor_id)

    # tier 5 — referential scope: an Investor subscribes only on its own behalf.
    if role == "Investor" and user_id != investor_id:
        errors.fail(errors.ERR_FORBIDDEN_SCOPE, "An Investor may subscribe only as itself.")

    # tier 8 — revision band and conflicts.
    if int(fund["version"]) != int(expected):
        errors.fail(errors.ERR_STALE_VERSION, "expected_fund_version is not current.")
    if not state.fund_allows_subscription(fund):
        errors.fail(errors.ERR_FUND_NOT_FORMING, "The fund is not accepting subscriptions.")
    if investor["status"] == "SUSPENDED":
        errors.fail(errors.ERR_INVESTOR_SUSPENDED, "The investor is suspended.")
    for existing in state.subscriptions_of_fund(fund_id):
        if existing["investor_id"] == investor_id and existing["status"] != "DEFAULTED":
            errors.fail(errors.ERR_DUPLICATE_SUBSCRIPTION,
                        "A non-defaulted subscription already exists for this pair.")

    # tier 9 — equity buckets.
    state.recompute_fund(fund_id)
    maximum = calc.max_subscription_cents(fund, investor)
    if committed > maximum:
        errors.fail(errors.ERR_SUBSCRIPTION_EXCEEDS_CAPACITY,
                    "committed_cents exceeds the fund's remaining raise or the investor's capacity.")

    # tier 10 — temporal window.
    now = clock.now()
    if now < clock._parse(fund["subscription_open_date"]) or now > clock._parse(fund["subscription_close_date"]):
        errors.fail(errors.ERR_SUBSCRIPTION_WINDOW_CLOSED,
                    "The logical clock is outside the subscription window.")

    subscription = store.create(store.subscriptions, {
        "fund_id": fund_id,
        "investor_id": investor_id,
        "committed_cents": committed,
        "payin_schedule": schedule,
        "executed_price_per_credit_dollar": fund["price_per_credit_dollar"],
        "status": "PLEDGED",
        "paid_in_cents": 0,
        "unfunded_commitment_cents": committed,
        "shortfall_cents": 0,
    })

    version_before = int(fund["version"])
    state.recompute_fund(fund_id)
    if int(fund["version"]) == version_before:
        store.touch(fund)
    state.recompute_subscription(subscription["id"])
    state.recompute_investor(investor_id)
    return response.ok(store.public(subscription), 201)


@bp.get("/funds/<fund_id>/portfolio-summary")
def read_portfolio_summary(fund_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, READ_FUND)
    validate.get_fund(fund_id)
    state.recompute_fund(fund_id)
    return response.ok(_summary(fund_id), 200)
