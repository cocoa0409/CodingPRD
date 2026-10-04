"""Corner coverage: calculation rules — charge-time minimum on deposits and
call rates, historical-breach reporting, and the dormancy boundary
(PRD §2.6, §3.3, §3.5, §3.9).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    connect_and_end_call,
    connect_call,
    create_cap_amendment_payload,
    deposit,
    get_account,
    get_regulatory_summary,
    iso_days_after,
    make_account_holder_headers,
    setup_call_ready_account,
    setup_denied_refund_account,
    setup_funded_account,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_deposit_fee_uses_min_of_contract_and_current_cap(
    api, state_regulator_headers
):
    """PRD §3.3: "The deposit fee is the lesser of the contract's `deposit_fee_cents` and the jurisdiction's `max_deposit_fee_cents`, resolved at deposit time. The deposited `amount_cents` must strictly exceed that fee — otherwise `ERR_DEPOSIT_TOO_SMALL` — so a deposit exactly one cent larger than the fee is accepted and nets a single cent of credit."

    Design: Corner/calculations/deposit_fee_uses_min_of_contract_and_current_cap
    """
    env = setup_funded_account(
        deposit_amount=0, contract_overrides={"deposit_fee_cents": 300}
    )
    account = env["account"]
    holder = make_account_holder_headers(account["id"])
    cap = env["cap"]

    first = deposit(account, 1000)
    assert first["balance_cents"] == 700, "fee 300 (contract) under cap 500"

    validate_success(
        api.amend_regulatory_cap(
            cap["id"],
            create_cap_amendment_payload(cap["version"], max_deposit_fee_cents=200),
            state_regulator_headers,
        )
    )
    second = deposit(account, 1000)
    assert second["balance_cents"] == 1500, (
        "after the amendment the fee is min(300, 200) == 200, resolved at "
        "deposit time"
    )

    too_small = api.create_deposit(account["id"], 200, holder)
    validate_error(too_small, ApiErrorId.ERR_DEPOSIT_TOO_SMALL)

    one_cent_over = deposit(account, 201)
    assert one_cent_over["balance_cents"] == 1501, (
        "a deposit one cent larger than the 200 fee nets a single cent"
    )


def test_connect_time_rate_snapshot_survives_cap_amendment_mid_call(
    api, facility_staff_headers, state_regulator_headers
):
    """PRD §3.5: "Later cap amendments or schedule supersessions never rewrite these pinned values, and until the call ends its `ended_at`, `billable_minutes`, and `total_charge_cents` remain null."
    PRD §2.6: "Because each minimum is taken at charge time, a cap amendment is never retroactive: rate schedules keep the rates they were validated against at activation, calls already connected keep their pinned prices, and only the next charge observes the amended cap."

    Design: Corner/calculations/connect_time_rate_snapshot_survives_cap_amendment_mid_call
    """
    env = setup_call_ready_account(deposit_amount=2025)
    account, inmate, recipient = env["account"], env["inmate"], env["recipient"]
    cap = env["cap"]

    call1 = connect_call(account, inmate, recipient, call_type="INTERSTATE")
    assert call1["applied_per_minute_cents"] == 25

    validate_success(
        api.amend_regulatory_cap(
            cap["id"],
            create_cap_amendment_payload(cap["version"], max_per_minute_cents=21),
            state_regulator_headers,
        )
    )

    ended1 = validate_success(api.end_call(call1["id"], 60, facility_staff_headers))
    assert ended1["total_charge_cents"] == 225, (
        "call1 pinned 25/min at connect: 200 + 1 x 25 despite the amendment"
    )

    call2 = connect_call(account, inmate, recipient, call_type="INTERSTATE")
    assert call2["applied_per_minute_cents"] == 21, (
        "the next connect snapshots min(schedule 25, amended cap 21)"
    )
    ended2 = validate_success(api.end_call(call2["id"], 60, facility_staff_headers))
    assert ended2["total_charge_cents"] == 221

    account_after = get_account(account["id"])
    assert account_after["balance_cents"] == 2000 - 225 - 221


def test_regulatory_summary_flags_historical_breach_after_cap_lowered(
    api, state_regulator_headers
):
    """PRD §3.9: "The `cap_breach_count` counts those calls whose pinned `applied_per_minute_cents` exceeds the jurisdiction's current `max_per_minute_cents`: historical pins can legitimately exceed a cap that was amended downward after connect, so breaches are reported, never rejected."
    PRD §3.9: "The `avg_revenue_per_billable_minute_cents` divides total call revenue by total billable minutes, rounds half-up to a whole cent, and is pinned to zero when there are no billable minutes at all."

    Design: Corner/calculations/regulatory_summary_flags_historical_breach_after_cap_lowered
    """
    env = setup_call_ready_account(deposit_amount=1025)
    account, inmate, recipient = env["account"], env["inmate"], env["recipient"]
    cap = env["cap"]

    ended = connect_and_end_call(
        account, inmate, recipient, duration_seconds=60, call_type="INTERSTATE"
    )
    assert ended["applied_per_minute_cents"] == 25
    assert ended["total_charge_cents"] == 225

    validate_success(
        api.amend_regulatory_cap(
            cap["id"],
            create_cap_amendment_payload(cap["version"], max_per_minute_cents=21),
            state_regulator_headers,
        )
    )

    summary = get_regulatory_summary(
        env["facility"]["id"],
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        headers=state_regulator_headers,
    )
    assert summary["cap_breach_count"] == 1, (
        "the pinned 25/min exceeds the current cap 21 — reported, not rejected"
    )
    assert summary["total_call_revenue_cents"] == 225
    assert summary["total_billable_minutes"] == 1
    assert summary["avg_revenue_per_billable_minute_cents"] == 225
    assert summary["total_deposit_fees_cents"] == 25
    assert summary["complaints_filed"] == 0


def test_dormancy_scan_flags_at_exactly_dormancy_days_not_before(
    api, platform_admin_headers
):
    """PRD §3.9: "when the logical clock has reached `unclaimed_since` plus the jurisdiction's `dormancy_days` — an age exactly equal to the threshold qualifies — the account's `escheat_status` becomes `DORMANT`, and the scan reports how many accounts it flagged this run as `accounts_flagged`."

    Design: Corner/calculations/dormancy_scan_flags_at_exactly_dormancy_days_not_before
    """
    env = setup_denied_refund_account()
    account = env["account"]
    assert account["unclaimed_balance_cents"] == 900
    unclaimed_since = account["unclaimed_since"]
    assert unclaimed_since.startswith("2026-09-01T00:00:00")

    advance_clock_to(iso_days_after(unclaimed_since, 29))
    scan29 = validate_success(
        api.run_dormancy_scan(env["facility"]["id"], platform_admin_headers)
    )
    assert scan29["accounts_flagged"] == 0
    mid = get_account(account["id"])
    assert mid["escheat_status"] == "NONE", "29 days is one day short of 30"

    advance_clock_to(iso_days_after(unclaimed_since, 30))
    scan30 = validate_success(
        api.run_dormancy_scan(env["facility"]["id"], platform_admin_headers)
    )
    assert scan30["accounts_flagged"] == 1
    final = get_account(account["id"])
    assert final["escheat_status"] == "DORMANT"
    assert final["unclaimed_balance_cents"] == 900
    assert final["unclaimed_since"] == unclaimed_since
