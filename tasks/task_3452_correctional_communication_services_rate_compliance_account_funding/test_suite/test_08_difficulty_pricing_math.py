"""Difficulty coverage: dual-variant calculations (GROSS vs NET commission,
SIMPLE_BALANCE vs LIFO_NET refund payout) and the combinatorial charge /
rounding formulas (PRD §2.6, §3.5, §3.8, §3.9).

All fixture literals were computed by executing the PRD formulas against the
pinned inputs: three LOCAL calls of 60/120/180 seconds at a 1-cent rate with
a 100-cent connection fee charge 101/102/103 (gross 306); 0.5 x 306 rounds
to 153 while 0.5 x (306 - 25 deposit fee) rounds to 141. Identical refund
ledgers (deposits 1000+500 with 300 fees, one 400-cent call, balance 500)
pay 400 under SIMPLE_BALANCE and 700 under LIFO_NET.
"""
from test_helpers import (
    activate_contract,
    close_account,
    connect_and_end_call,
    connect_call,
    create_cap_amendment_payload,
    create_contract,
    deposit,
    get_account,
    get_regulatory_summary,
    setup_call_ready_account,
    validate_success,
)

_ONE_CENT_SCHEDULE = {
    "local_per_minute_cents": 1,
    "intrastate_per_minute_cents": 1,
    "interstate_per_minute_cents": 1,
    "international_per_minute_cents": 1,
    "connection_fee_cents": 100,
    "message_price_cents": 15,
    "video_session_fee_cents": 500,
}

_PERIOD = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")


def _three_local_calls(env):
    """Drive the pinned 60s/120s/180s LOCAL calls (charges 101/102/103)."""
    for seconds in (60, 120, 180):
        connect_and_end_call(
            env["account"],
            env["inmate"],
            env["recipient"],
            duration_seconds=seconds,
            call_type="LOCAL",
        )


def _refund_ledger_env(state_code, refund_method):
    """One jurisdiction with the pinned ledger: deposits 1000 (fee 300) and
    500 (fee 300), one 480s INTERSTATE call charged 400 -> balance 500."""
    env = setup_call_ready_account(
        deposit_amount=0,
        cap_overrides={"state_code": state_code, "refund_method": refund_method},
        facility_overrides={"state_code": state_code},
        contract_overrides={"deposit_fee_cents": 300},
    )
    deposit(env["account"], 1000)
    deposit(env["account"], 500)
    connect_and_end_call(
        env["account"],
        env["inmate"],
        env["recipient"],
        duration_seconds=480,
        call_type="INTERSTATE",
    )
    assert get_account(env["account"]["id"])["balance_cents"] == 500
    return env


def test_commission_gross_basis_on_identical_ledger(api):
    """PRD §3.9: "The `commission_basis` of that contract is echoed, and `commission_accrued_cents` applies the contract's `commission_pct` to a basis total: under `GROSS`, the basis is the gross billed revenue — the magnitudes of all call, message, and video charges in the window — with no deductions; under `NET`, the basis is that gross billed revenue minus the deposit fees and minus the message and video refunds, so identical ledger data accrues a smaller commission under `NET`."

    Design: Difficulty/dual_variant_calc/commission_gross_vs_net_basis_diverge_on_identical_ledger
    """
    env = setup_call_ready_account(
        deposit_amount=1000, schedule_overrides=_ONE_CENT_SCHEDULE
    )
    _three_local_calls(env)

    summary = get_regulatory_summary(env["facility"]["id"], *_PERIOD)
    assert summary["commission_basis"] == "GROSS"
    assert summary["commission_accrued_cents"] == 153
    assert summary["total_call_revenue_cents"] == 306
    assert summary["total_billable_minutes"] == 6
    assert summary["total_deposit_fees_cents"] == 25


def test_commission_net_basis_on_identical_ledger_diverges(
    api, platform_admin_headers
):
    """PRD §3.9: "The commission block of that summary reflects the facility's currently active contract, whatever contract the historical revenue was billed under."
    PRD §3.9: "under `NET`, the basis is that gross billed revenue minus the deposit fees and minus the message and video refunds, so identical ledger data accrues a smaller commission under `NET`."

    Design: Difficulty/dual_variant_calc/commission_gross_vs_net_basis_diverge_on_identical_ledger
    """
    env = setup_call_ready_account(
        deposit_amount=1000, schedule_overrides=_ONE_CENT_SCHEDULE
    )
    _three_local_calls(env)

    gross = get_regulatory_summary(env["facility"]["id"], *_PERIOD)
    assert gross["commission_basis"] == "GROSS"
    assert gross["commission_accrued_cents"] == 153

    validate_success(
        api.terminate_contract(env["contract"]["id"], platform_admin_headers)
    )
    net_contract = create_contract(env["facility"]["id"], commission_basis="NET")
    activate_contract(net_contract["id"])

    net = get_regulatory_summary(env["facility"]["id"], *_PERIOD)
    assert net["commission_basis"] == "NET"
    assert net["commission_accrued_cents"] == 141, (
        "0.5 x (306 - 25 deposit fees) = 140.5, rounded half-up once"
    )
    assert gross["commission_accrued_cents"] != net["commission_accrued_cents"], (
        "no call, deposit, or ledger row changed between the two reads"
    )
    assert net["total_call_revenue_cents"] == 306


def test_refund_payout_simple_balance_variant(api, facility_staff_headers):
    """PRD §3.8: "Under `SIMPLE_BALANCE`, the payout is the closure snapshot minus the closure fee, floored at zero, and deposit fees are never returned."
    PRD §3.8: "When it is positive, a **RefundRequest** is created with `source` `CLOSURE` and status `REQUESTED`, its `requested_amount_cents` equal to the full closure snapshot; the balance stays frozen on the ledger, `latest_refund_request_id` is set on the account, and `requested_by_user_id` with `requested_by_role` record who closed it ('system' for the auto-close)."

    Design: Difficulty/dual_variant_calc/refund_payout_simple_balance_vs_lifo_net_identical_ledgers
    """
    env = _refund_ledger_env("SA", "SIMPLE_BALANCE")
    closed = close_account(env["account"], as_staff=True)
    assert closed["status"] == "CLOSED"
    assert closed["balance_at_closure_cents"] == 500
    assert closed["refundable_computed_cents"] == 400, (
        "SIMPLE_BALANCE: 500 - 100 closure fee; deposit fees never returned"
    )
    assert closed["latest_refund_request_id"], (
        "a positive refundable amount opens a RefundRequest"
    )


def test_refund_payout_lifo_net_variant_diverges(api):
    """PRD §3.8: "Under `LIFO_NET`, the computation is fee-restoring: take the total of all call, message, and video charge magnitudes on the ledger, reduced by the message and video refund magnitudes — deposit entries and fee entries are excluded from that total; then attribute the total against deposit principal amounts newest-first, so the most recent deposit is treated as spent before the one before it; call a deposit **intact** when no charge is attributed to it; the fee refund is the sum of the deposit-fee magnitudes attached to intact deposits; and the payout is the snapshot minus the closure fee plus that fee refund, again floored at zero."

    Design: Difficulty/dual_variant_calc/refund_payout_simple_balance_vs_lifo_net_identical_ledgers
    """
    env_sa = _refund_ledger_env("SA", "SIMPLE_BALANCE")
    env_lb = _refund_ledger_env("LB", "LIFO_NET")

    closed_sa = close_account(env_sa["account"], as_staff=True)
    closed_lb = close_account(env_lb["account"], as_staff=True)

    assert closed_sa["balance_at_closure_cents"] == 500
    assert closed_lb["balance_at_closure_cents"] == 500, (
        "the two ledgers are byte-identical in shape"
    )
    assert closed_sa["refundable_computed_cents"] == 400
    assert closed_lb["refundable_computed_cents"] == 700, (
        "LIFO_NET: 500 - 100 + 300 fee refund for the intact oldest deposit "
        "(the 400 charge consumes the newest 500 deposit first)"
    )
    assert closed_sa["latest_refund_request_id"]
    assert closed_lb["latest_refund_request_id"]
    assert (
        closed_sa["refundable_computed_cents"]
        != closed_lb["refundable_computed_cents"]
    )


def test_call_charge_ceil_minutes_full_billing(api, facility_staff_headers):
    """PRD §3.5: "The requested billable time is the duration in seconds rounded up to whole minutes: a call of 61 seconds bills as two minutes before any cutoff is considered. The full charge would be the applied connection fee plus the requested minutes multiplied by the applied per-minute rate."
    PRD §3.5: "When no truncation occurs, `cutoff_reason` stays `NONE` and the full charge stands."

    Design: Difficulty/combinatorial_formula/call_charge_ceil_min_cap_and_affordability_cutoff
    """
    env = setup_call_ready_account(deposit_amount=0)
    account, inmate, recipient = env["account"], env["inmate"], env["recipient"]
    deposit(account, 285)  # fee 25 -> balance 260

    call = connect_call(account, inmate, recipient, call_type="INTERSTATE")
    assert call["applied_per_minute_cents"] == 25
    assert call["applied_connection_fee_cents"] == 200

    ended = validate_success(api.end_call(call["id"], 61, facility_staff_headers))
    assert ended["status"] == "COMPLETED"
    assert ended["billable_minutes"] == 2, "61 seconds rounds up to 2 minutes"
    assert ended["total_charge_cents"] == 250, "200 + 2 x 25, no cutoff"
    assert ended["cutoff_reason"] == "NONE"
    assert get_account(account["id"])["balance_cents"] == 10


def test_call_charge_affordability_cutoff_after_cap_amendment(
    api, facility_staff_headers, state_regulator_headers
):
    """PRD §3.5: "Affordability, judged against the balance observed at connect time, can truncate that bill. For a `PREPAID` or `DEBIT` account, the affordable minutes are the connect-time balance minus the connection fee, divided by the per-minute rate, rounded down to a whole minute; when the requested minutes exceed the affordable minutes, the bill is cut to the affordable minutes — the charge becomes the connection fee plus the affordable minutes at the applied rate — and `cutoff_reason` is set to `BALANCE_EXHAUSTED`, though the call's status is still `COMPLETED`."
    PRD §2.6: "the charge-time minimum: every chargeable price is the lesser of the relevant value on the facility's active rate schedule and the corresponding jurisdictional regulatory cap, evaluated at the moment the charge is made."

    Design: Difficulty/combinatorial_formula/call_charge_ceil_min_cap_and_affordability_cutoff
    """
    env = setup_call_ready_account(deposit_amount=0)
    account, inmate, recipient = env["account"], env["inmate"], env["recipient"]
    deposit(account, 285)  # balance 260
    cap = env["cap"]

    validate_success(
        api.amend_regulatory_cap(
            cap["id"],
            create_cap_amendment_payload(cap["version"], max_per_minute_cents=21),
            state_regulator_headers,
        )
    )

    call = connect_call(account, inmate, recipient, call_type="INTERSTATE")
    assert call["applied_per_minute_cents"] == 21, (
        "charge-time minimum observes the amended cap on the next connect"
    )

    ended = validate_success(api.end_call(call["id"], 600, facility_staff_headers))
    assert ended["status"] == "COMPLETED"
    assert ended["billable_minutes"] == 2, (
        "floor((260 - 200) / 21) = 2 affordable minutes of the 10 requested"
    )
    assert ended["total_charge_cents"] == 242, "200 + 2 x 21"
    assert ended["cutoff_reason"] == "BALANCE_EXHAUSTED"
    assert get_account(account["id"])["balance_cents"] == 18


def test_commission_aggregates_then_rounds_half_up(api):
    """PRD §3.9: "The percentage is applied once to the aggregate basis and the result is rounded half-up to whole cents; rounding each transaction first and then summing would be a different, non-conformant algorithm that produces different cents."

    Design: Difficulty/combinatorial_formula/commission_aggregate_rounding_beats_per_line_sum
    """
    env = setup_call_ready_account(
        deposit_amount=1000, schedule_overrides=_ONE_CENT_SCHEDULE
    )
    _three_local_calls(env)

    summary = get_regulatory_summary(env["facility"]["id"], *_PERIOD)
    assert summary["commission_accrued_cents"] == 153, (
        "0.5 applied once to the aggregate 306 rounds half-up to 153"
    )
    assert summary["commission_accrued_cents"] != 154, (
        "per-line rounding (51 + 51 + 52) sums to 154 — the non-conformant "
        "reading of the same data"
    )


def test_regulatory_summary_avg_revenue_per_billable_minute(api):
    """PRD §3.9: "Over the facility's `COMPLETED` calls whose `ended_at` falls in the window, it reports `total_call_seconds`, `total_billable_minutes`, `total_call_revenue_cents`, and `total_connection_fees_cents` — the last counting only calls whose charge was positive. The `avg_revenue_per_billable_minute_cents` divides total call revenue by total billable minutes, rounds half-up to a whole cent, and is pinned to zero when there are no billable minutes at all."

    Design: Difficulty/combinatorial_formula/commission_aggregate_rounding_beats_per_line_sum
    """
    env = setup_call_ready_account(
        deposit_amount=1000, schedule_overrides=_ONE_CENT_SCHEDULE
    )
    _three_local_calls(env)

    summary = get_regulatory_summary(env["facility"]["id"], *_PERIOD)
    assert summary["total_call_revenue_cents"] == 306
    assert summary["total_billable_minutes"] == 6
    assert summary["total_call_seconds"] == 360
    assert summary["total_connection_fees_cents"] == 300
    assert summary["avg_revenue_per_billable_minute_cents"] == 51, (
        "round_half_up(306 / 6)"
    )
