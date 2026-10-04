"""Retail service audits: score ranges, component-level violations, the strike
counter, and the third-strike auto-suspension cascade.

Covers PRD §3.5 (audit composite, violation rule, strike mechanism) and §3.7
(suspension cascade). Instances:
Difficulty/transitive_cascade/audit_strike_auto_suspend_cascade_releases_capacity,
Difficulty/boundary_precision_check/audit_score_70_passes_69_violates_component_level,
Corner/entities/audit_score_out_of_range_returns_400,
Corner/endpoints/audit_post_returns_account_with_appended_log.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_retail_account,
    audit_payload,
    create_retail_account,
    find_production_day,
    get_agreement,
    list_orders,
    order_line,
    post_audit,
    post_violation_audit,
    set_clock,
    setup_active_cash_agreement,
    setup_confirmed_order,
    validate_error,
    validate_success,
)

_ROUTE_OPS = TEST_USERS["route_ops_manager_headers"]


def _setup_strike_cascade():
    """Active cash agreement; one retail account; a CONFIRMED 25-unit order on
    production day 2026-09-05; two violation audits posted (2026-09-01 and
    2026-09-02); clock at 2026-09-03."""
    ctx = setup_active_cash_agreement()
    account = create_retail_account(
        ctx["distributor"],
        store_name="QuickStop Elm",
        delivery_weekdays=["MON", "THU"],
    )
    day, order = setup_confirmed_order(
        ctx, "2026-09-05", [order_line("WHT-24", 25)]
    )
    post_violation_audit(account["id"], "2026-09-01")
    post_violation_audit(account["id"], "2026-09-02")
    set_clock("2026-09-03T09:00:00Z")
    return ctx, account, day, order


def test_third_strike_auto_suspends_and_releases_capacity(api):
    """PRD §3.5: "When the newly posted audit is itself a violation and the
    recomputed count has reached three, the agreement auto-suspends: `ACTIVE →
    SUSPENDED_SERVICE` with `suspension_reason` `SERVICE_DEFAULT`, firing the
    same future-order cancellation cascade as a manual suspension (§3.7)."
    PRD §3.7: "every order of this distributor under this agreement that is
    still `SUBMITTED` or `CONFIRMED` and whose `delivery_date` falls on or
    after the current logical date moves to `CANCELLED` with
    `cancelled_reason` `AGREEMENT_SUSPENDED`, and each confirmed order so
    cancelled releases its production-day reservation — the day's
    `allocated_units` drops by the order's `units_total` and its `version`
    advances by one."

    Design: Difficulty/transitive_cascade/audit_strike_auto_suspend_cascade_releases_capacity
    """
    ctx, account, day, order = _setup_strike_cascade()
    post_violation_audit(account["id"], "2026-09-03")

    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["strike_count"] == 3
    assert agreement["status"] == "SUSPENDED_SERVICE"
    assert agreement["suspension_reason"] == "SERVICE_DEFAULT"

    current = [
        o for o in list_orders(ctx["distributor"]["id"]) if o["id"] == order["id"]
    ][0]
    assert current["status"] == "CANCELLED"
    assert current["cancelled_reason"] == "AGREEMENT_SUSPENDED"

    day_now = find_production_day(ctx["bakery"]["id"], "2026-09-05")
    assert day_now["allocated_units"] == 0, "25 reserved units released"
    assert day_now["version"] == 3, "create 1, confirm 2, cascade release 3"


def test_two_strikes_do_not_suspend(api):
    """PRD §3.5: "A count of exactly three triggers the suspension; two does
    not."
    PRD §3.5: "The composite is a weighted blend — 40% of shelf stocking, 30%
    of rotation, and 30% of display — rounded half-up to an integer."

    Design: Difficulty/transitive_cascade/audit_strike_auto_suspend_cascade_releases_capacity
    """
    ctx, account, day, order = _setup_strike_cascade()
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["strike_count"] == 2
    assert agreement["status"] == "ACTIVE"

    updated = post_violation_audit(account["id"], "2026-09-03")
    assert len(updated["audit_log"]) == 3
    for entry in updated["audit_log"]:
        assert entry["is_violation"] is True, "shelf 60 < 70"
        assert entry["composite_score"] == 78, (
            "round_half_up(0.4*60 + 0.3*90 + 0.3*90)"
        )

    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["strike_count"] == 3
    assert agreement["status"] == "SUSPENDED_SERVICE"


def test_audit_score_70_passes_69_violates(api):
    """PRD §3.5: "Violation is component-level, not composite-level: the audit
    is a violation when any single component score is strictly below 70. A
    score set of 69, 70, 70 composites to 70 yet is a violation; a set of
    exactly 70, 70, 70 sits at the threshold and is not a violation."

    Design: Difficulty/boundary_precision_check/audit_score_70_passes_69_violates_component_level
    """
    ctx = setup_active_cash_agreement()
    acct_p = create_retail_account(
        ctx["distributor"],
        store_name="ValueBasket North",
        delivery_weekdays=["MON"],
    )
    acct_q = create_retail_account(
        ctx["distributor"],
        store_name="ValueBasket South",
        delivery_weekdays=["TUE"],
    )
    updated_p = post_audit(acct_p["id"], "2026-09-01", 70, 70, 70)
    assert updated_p["compliance_score"] == 70
    assert updated_p["audit_log"][-1]["is_violation"] is False

    updated_q = post_audit(acct_q["id"], "2026-09-01", 69, 70, 70)
    assert updated_q["compliance_score"] == 70, (
        "round_half_up(0.4*69 + 0.3*70 + 0.3*70) = round_half_up(69.6)"
    )
    assert updated_q["audit_log"][-1]["is_violation"] is True, (
        "one component below 70 violates even though the composite is 70"
    )


def test_audit_violation_count_drives_strike_count(api):
    """PRD §3.5: "Each posted audit also recomputes the agreement's
    `strike_count`: the count of violation-flagged audit entries across all of
    the distributor's retail accounts under the `ACTIVE` agreement whose
    `audit_date` lies within the trailing ninety calendar days ending on — and
    including — the new audit's date."
    PRD §3.5: "A count of exactly three triggers the suspension; two does not."

    Design: Difficulty/boundary_precision_check/audit_score_70_passes_69_violates_component_level
    """
    ctx = setup_active_cash_agreement()
    acct_p = create_retail_account(
        ctx["distributor"],
        store_name="ValueBasket North",
        delivery_weekdays=["MON"],
    )
    acct_q = create_retail_account(
        ctx["distributor"],
        store_name="ValueBasket South",
        delivery_weekdays=["TUE"],
    )
    post_audit(acct_p["id"], "2026-09-01", 70, 70, 70)
    post_audit(acct_q["id"], "2026-09-01", 69, 70, 70)
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["strike_count"] == 1, "only the 69-component audit counts"
    assert agreement["status"] == "ACTIVE", "1 strike < 3"


def test_audit_score_out_of_range_returns_400(api):
    """PRD §3.5: "Service audits are posted by a `RouteOpsManager` and carry an
    `audit_date` plus three component scores — `shelf_stock_score`,
    `rotation_score`, and `display_score` — each an integer from 0 to 100
    inclusive; a score outside that range is rejected with
    `ERR_AUDIT_SCORE_RANGE`."
    PRD §3.5: "The composite is a weighted blend — 40% of shelf stocking, 30%
    of rotation, and 30% of display — rounded half-up to an integer."

    Design: Corner/entities/audit_score_out_of_range_returns_400
    """
    ctx = setup_active_cash_agreement()
    account = create_retail_account(ctx["distributor"])
    resp = api_client.post_audit(
        account["id"],
        audit_payload("2026-09-01", 101, 90, 90),
        _ROUTE_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_SCORE_RANGE)

    updated = post_audit(account["id"], "2026-09-01", 100, 0, 90)
    assert updated["audit_log"][-1]["composite_score"] == 67, (
        "round_half_up(0.4*100 + 0.3*0 + 0.3*90)"
    )
    assert len(updated["audit_log"]) == 1, "the rejected audit was not appended"


def test_audit_post_returns_account_with_appended_log(api):
    """PRD §3.5: "The audit is appended to the account's `audit_log` together
    with its computed `composite_score` and `is_violation` flag."
    PRD §3.5: "The account's `compliance_score` always reflects the latest
    audit by `audit_date`, with ties broken toward the later-created audit
    entry, and `last_audit_on` tracks that date."
    PRD §4: "Operations that create new resources — a bakery, a territory, a
    distributor, a production day, an agreement, a financing plan, a retail
    account, an audit entry, an order, or a stale claim — return a `201
    Created` status code."

    Design: Corner/endpoints/audit_post_returns_account_with_appended_log
    """
    ctx = setup_active_cash_agreement()
    account = create_retail_account(ctx["distributor"])
    resp = api_client.post_audit(
        account["id"],
        audit_payload("2026-09-01", 90, 85, 95),
        _ROUTE_OPS,
    )
    data = validate_success(resp, 201)
    assert data["id"] == account["id"], "the 201 body is the updated account"
    assert_retail_account(data)
    assert len(data["audit_log"]) == 1
    entry = data["audit_log"][0]
    assert entry["audit_date"] == "2026-09-01"
    assert entry["composite_score"] == 90, (
        "round_half_up(0.4*90 + 0.3*85 + 0.3*95) = round_half_up(90.0)"
    )
    assert entry["is_violation"] is False
    assert data["compliance_score"] == 90
    assert data["last_audit_on"] == "2026-09-01"
    assert get_agreement(ctx["agreement"]["id"])["strike_count"] == 0
