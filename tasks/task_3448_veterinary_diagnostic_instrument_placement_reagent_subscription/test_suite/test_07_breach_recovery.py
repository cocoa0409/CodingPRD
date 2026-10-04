"""Shortfall breach cascade, recovery, and clinic termination gates (PRD §3.1, §3.5)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_2026_11_01,
    CLOCK_2027_01_15,
    CLOCK_2028_09_02,
    TEST_USERS,
    advance_clock,
    api_client,
    close_commitment_period,
    close_periods_chronologically,
    get_agreement,
    get_clinic,
    get_period_by_month,
    patch_clinic_payload,
    record_exact_payment,
    setup_breached_agreement,
    setup_clinic_with_active_reagent_commitment,
    validate_error,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


def test_breach_triggers_exactly_at_threshold_on_fourth_close(api):
    """PRD §3.5: "When a close leaves `cumulative_unpaid_billed_cents` at or
    above the breach threshold of 250000 cents
    (`SHORTFALL_BREACH_THRESHOLD_CENTS`), an `ACTIVE` agreement is breached:
    it moves `ACTIVE` → `BREACHED` with a `version` increment". Three
    consecutive 80000c bills total 240000 (below), the fourth totals 320000
    (at or above).

    Design: Difficulty/transitive_cascade/close_period_breach_cascade
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    agreement = scenario["agreement"]
    advance_clock(CLOCK_2027_01_15)

    close_periods_chronologically(agreement["id"], ["2026-09", "2026-10", "2026-11"])
    mid = get_agreement(agreement["id"])
    assert mid["cumulative_unpaid_billed_cents"] == 240000
    assert mid["status"] == "ACTIVE"

    close_commitment_period(agreement["id"], "2026-12")
    after = get_agreement(agreement["id"])
    assert after["cumulative_unpaid_billed_cents"] == 320000
    assert after["status"] == "BREACHED"


def test_breach_cascade_suspends_clinic_without_direct_write(api):
    """PRD §3.5: "the cascade suspends the owning clinic `ACTIVE` →
    `SUSPENDED`, incrementing the clinic's `version` as well." PRD §3.5: the
    close locks "fulfilled_cents" (0 with no orders), computes the shortfall
    and bills 80000c per period, "and when `billed_cents` is positive the
    same mutation flips `billing_status` from `NONE` to `ISSUED`".

    Design: Difficulty/transitive_cascade/close_period_breach_cascade
    """
    scenario = setup_breached_agreement()
    agreement = scenario["agreement"]
    clinic = scenario["clinic"]

    assert agreement["status"] == "BREACHED"
    assert agreement["cumulative_unpaid_billed_cents"] == 320000
    assert clinic["status"] == "SUSPENDED"  # cascaded; never written directly

    for period in scenario["closed_periods"]:
        assert period["period_status"] == "CLOSED"
        assert period["billing_status"] == "ISSUED"
        assert period["fulfilled_cents"] == 0
        assert period["billed_cents"] == 80000


def test_clinic_terminate_blocked_by_unpaid_shortfall(api):
    """PRD §3.1: "Termination is reachable from either `ACTIVE` or
    `SUSPENDED` and demands two clean bills of health: every placement
    agreement of the clinic must be `COMPLETED` (else
    `ERR_AGREEMENT_INVALID_STATE`), and no agreement may carry
    `cumulative_unpaid_billed_cents` above zero (else
    `ERR_OUTSTANDING_SHORTFALL_UNPAID`, HTTP 402)." PRD §3.5: "the agreement
    recovers automatically — back to `ACTIVE` when the logical clock is at or
    before `end_date`, or forward to `COMPLETED` when the clock has passed
    it." — here the agreement completed via past-end recovery yet still
    carries 80000c unpaid, so the state gate passes and the fiscal gate
    fires.

    Design: Corner/validations/clinic_terminate_blocked_by_unpaid_shortfall
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]  # term ends 2028-09-01
    advance_clock(CLOCK_2026_11_01)
    close_periods_chronologically(agreement["id"], ["2026-09", "2026-10"])  # 160000 unpaid
    september = get_period_by_month(agreement["id"], "2026-09")

    advance_clock(CLOCK_2028_09_02)  # past end_date with unpaid > 0: sweep breaches
    assert get_agreement(agreement["id"])["status"] == "BREACHED"

    record_exact_payment(september["id"], 80000)  # unpaid 80000 < 250000, past end_date
    recovered = get_agreement(agreement["id"])
    assert recovered["status"] == "COMPLETED"
    assert recovered["cumulative_unpaid_billed_cents"] == 80000

    resp = api_client.update_clinic(
        clinic["id"], patch_clinic_payload(status="TERMINATED"), _ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_SHORTFALL_UNPAID)
    # The earlier breach cascade suspended the clinic; recovery to COMPLETED
    # does not unsuspend it.
    assert get_clinic(clinic["id"])["status"] == "SUSPENDED"
