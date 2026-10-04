"""Refund scheduling, interest computation, and disbursement release tests:
the PROVISIONAL/FINAL dual variants, per-component rounding order, the
45-day free-window boundary, the money-consistency handshake, terminal-state
lockdown, and fraud-confirmation compensation.

PRD section 3.8 (interest arithmetic per sections 2.6 and 3.6).
"""
from datetime import date

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_amount_consistency,
    assert_refund_disbursement,
    create_active_config,
    create_dependent_payload,
    create_taxpayer,
    date_of,
    file_passing_return,
    file_return,
    get_conflict_by_tin,
    get_return,
    get_return_disbursement,
    make_fraud_analyst_headers,
    next_dependent_tin,
    release_disbursement_payload,
    schedule_refund,
    set_clock,
    setup_released_return,
    setup_scheduled_refund,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["fraud_analyst_headers"]


def _setup_filed_passing_return(claimed=100000, prior=100000):
    """Clock at 2027-05-01 (after the 2027-04-15 filing deadline for tax year
    2026, so the anchor date is the filing date); pass-through config; a
    NONE-bank return scoring 0 -> FILTER_PASSED. Refund NOT yet scheduled."""
    set_clock("2027-05-01T00:00:00Z")
    create_active_config()
    return file_passing_return(
        taxpayer_overrides={"prior_year_refund_cents": prior},
        claimed_refund_cents=claimed,
        bank_product="NONE",
    )


# ─── Dual variant: PROVISIONAL vs FINAL ──────────────

def test_provisional_interest_simple_accrual_at_scheduling(api):
    """PRD section 3.8: "The provisional variant runs at scheduling and
    projects the release date as the scheduling date itself. Its days-late
    count is the number of days from the anchor date to the scheduling date,
    minus the 45 interest-free days. When that count is zero or negative,
    `provisional_interest_cents` is 0. Otherwise it is the base multiplied by
    the daily rate multiplied by the days-late count, rounded half-up to
    integer cents in a single rounding at the end."
    PRD section 3.8: "Both variants share an anchor date: the later of the
    return's filing date (the calendar date of its `received_at`) and the
    filing deadline for the return's tax year — for tax year 2026, that
    deadline is 2027-04-15."

    Design: Difficulty/dual_variant_calc/interest_provisional_vs_final_diverge
    """
    _taxpayer, rtn = _setup_filed_passing_return()
    # 2027-07-15 is 75 days after the 2027-05-01 filing: 30 days late.
    set_clock("2027-07-15T00:00:00Z")
    disb = schedule_refund(rtn["id"])

    assert_refund_disbursement(disb)
    assert disb["status"] == "SCHEDULED"
    assert disb["base_cents"] == 100000
    # round_half_up(100000 * 0.07/365 * 30) == 575, single rounding.
    assert disb["provisional_interest_cents"] == 575
    assert disb["amount_cents"] == 100575
    assert get_return(rtn["id"])["status"] == "REFUND_SCHEDULED"


def test_final_interest_compounding_diverges_at_release(api):
    """PRD section 3.8: "The final variant runs at release and compounds
    daily against the actual release date, rounding per component and then
    summing."
    PRD section 3.8: "The `final_interest_cents` is the sum of those
    per-component rounded amounts; rounding once after summing is explicitly
    rejected, and for identical base and day counts the final figure
    therefore differs from the provisional estimate."
    PRD section 3.8: "A successful release stamps `final_interest_cents`,
    finalizes `amount_cents` as `base_cents` plus `final_interest_cents`,
    sets `released_at` from the logical clock, moves the disbursement to
    `RELEASED`, and advances the return from `REFUND_SCHEDULED` to
    `REFUND_RELEASED`."

    Design: Difficulty/dual_variant_calc/interest_provisional_vs_final_diverge
    """
    _taxpayer, rtn = _setup_filed_passing_return()
    set_clock("2027-07-15T00:00:00Z")
    disb = schedule_refund(rtn["id"])
    assert disb["provisional_interest_cents"] == 575

    resp = api.release_disbursement(
        disb["id"], release_disbursement_payload(100577), ADMIN
    )
    released = validate_success(resp, 200)
    # round_half_up(100000 * ((1 + 0.07/365) ** 30 - 1)) == 577.
    assert released["final_interest_cents"] == 577
    assert released["final_interest_cents"] != disb["provisional_interest_cents"]
    assert released["amount_cents"] == 100577
    assert released["status"] == "RELEASED"
    assert_amount_consistency(released)
    assert get_return(rtn["id"])["status"] == "REFUND_RELEASED"


# ─── Per-component rounding order ────────────────────

def _setup_scheduled_return_then_conflict_resolution(api):
    """A and B file 300000-cent returns claiming the same dependent
    (conflict OPEN, both CONTESTED, both FILTER_PASSED under a pass-through
    config); B's refund is scheduled at 2027-05-01; the 30-day evidence
    window (PRD section 3.6) ends 2027-05-31, so advancing the clock to
    2027-06-30 makes the section-2.4 sweep auto-resolve the conflict
    FIRST_FILER with resolved_reason DEFAULT_NO_EVIDENCE — section 3.6
    applies the same credit adjustment and disbursement re-sync under
    default resolution as under analyst decision, so B loses 200000
    cents; clock then rests at 2027-07-15 for release."""
    set_clock("2027-05-01T00:00:00Z")
    create_active_config(model_version="MV-PC")
    dep_tin = next_dependent_tin()
    tp_a = create_taxpayer()
    tp_b = create_taxpayer()
    file_return(
        tp_a["id"], claimed_refund_cents=300000,
        filing_status="HEAD_OF_HOUSEHOLD", bank_product="NONE",
        dependents=[create_dependent_payload(dep_tin)],
    )
    rtn_b = file_return(
        tp_b["id"], claimed_refund_cents=300000, bank_product="NONE",
        dependents=[create_dependent_payload(dep_tin)],
    )

    disb = schedule_refund(rtn_b["id"])
    assert disb["base_cents"] == 300000

    # The evidence window closed 2027-05-31, so this advance fires the
    # section-2.4 sweep and auto-resolves the still-OPEN conflict.
    set_clock("2027-06-30T00:00:00Z")
    conflict = get_conflict_by_tin(dep_tin)
    assert conflict["status"] == "RESOLVED"
    assert conflict["resolution"] == "FIRST_FILER"
    assert conflict["resolved_reason"] == "DEFAULT_NO_EVIDENCE"
    set_clock("2027-07-15T00:00:00Z")
    return rtn_b, disb


def test_final_interest_rounds_each_component_then_sums(api):
    """PRD section 3.8: "Its component zero is the base as it stood at
    scheduling — the `claimed_refund_cents` at that time — accruing for the
    number of days from the anchor date to the release date minus the 45
    interest-free days, floored at zero days. Each signed adjustment the
    return absorbed after scheduling forms its own component: an adjustment
    applied at its resolution date accrues from the later of (the anchor date
    plus 45 days) and that adjustment's resolution date through the release
    date, again floored at zero days."
    PRD section 3.8: "The `final_interest_cents` is the sum of those
    per-component rounded amounts; rounding once after summing is explicitly
    rejected, and for identical base and day counts the final figure
    therefore differs from the provisional estimate."

    Design: Difficulty/combinatorial_formula/interest_per_component_rounding_order
    """
    rtn_b, disb = _setup_scheduled_return_then_conflict_resolution(api)

    # Section 3.6 re-synced base is 100000 + (-200000) == -100000, so the
    # section-3.8 handshake expects base + final = -100000 + 1155 = -98845.
    resp = api.release_disbursement(
        disb["id"], release_disbursement_payload(-98845), ADMIN
    )
    released = validate_success(resp, 200)
    assert released["base_cents"] == -100000
    # compound(300000, 30d) -> 1731 plus compound(-200000, 15d) -> -576,
    # each rounded individually; compounding the net 100000 base for 30 days
    # in a single component would give 577.
    assert released["final_interest_cents"] == 1155
    assert released["final_interest_cents"] != 577
    assert released["amount_cents"] == -98845


def test_scheduled_disbursement_base_resyncs_on_conflict_resolution(api):
    """PRD section 3.6: "If the losing return happens to be
    `REFUND_SCHEDULED` at that moment, its disbursement re-syncs: `base_cents`
    is rewritten to the new `claimed_refund_cents` plus `adjustment_cents`,
    and `provisional_interest_cents` is recomputed under the provisional
    interest rules of §3.8 against the new base."
    PRD section 3.6: "the adjustment amount is the lesser of 200000 cents
    (the dependent credit at stake) and the losing return's
    `claimed_refund_cents`; that amount is subtracted from
    `claimed_refund_cents` — the minimum guarantees the floor of 0 is never
    breached — and the same signed amount is subtracted from the return's
    `adjustment_cents`, which accumulates negative adjustments."

    Design: Difficulty/combinatorial_formula/interest_per_component_rounding_order
    """
    rtn_b, _disb = _setup_scheduled_return_then_conflict_resolution(api)

    loser = get_return(rtn_b["id"])
    assert loser["claimed_refund_cents"] == 100000
    assert loser["adjustment_cents"] == -200000
    assert loser["status"] == "REFUND_SCHEDULED"

    synced = get_return_disbursement(rtn_b["id"])
    assert synced["status"] == "SCHEDULED"
    # PRD section 3.6 re-sync formula applied to the values asserted above:
    # base_cents = new claimed_refund_cents (100000) + adjustment_cents
    # (-200000) == -100000. (The design index's "re-synced to 100000" drops
    # the "+ adjustment_cents" term and contradicts the PRD sentence.)
    assert synced["base_cents"] == -100000


# ─── Free-window boundary ────────────────────────────

def test_release_on_free_window_last_day_accrues_zero(api):
    """PRD section 3.8: "an interest-free window of 45 days after the
    anchor".
    PRD section 3.8: "Its component zero is the base as it stood at
    scheduling — the `claimed_refund_cents` at that time — accruing for the
    number of days from the anchor date to the release date minus the 45
    interest-free days, floored at zero days."

    Design: Difficulty/boundary_precision_check/interest_free_window_day45_exactly
    """
    _taxpayer, rtn = _setup_filed_passing_return()
    disb = schedule_refund(rtn["id"])
    # 2027-06-15 is exactly 45 days after the 2027-05-01 anchor: day 45 is
    # still inside the free window, so zero days accrue.
    set_clock("2027-06-15T00:00:00Z")

    resp = api.release_disbursement(
        disb["id"], release_disbursement_payload(100000), ADMIN
    )
    released = validate_success(resp, 200)
    assert released["final_interest_cents"] == 0
    assert released["amount_cents"] == 100000
    assert released["status"] == "RELEASED"
    assert get_return(rtn["id"])["status"] == "REFUND_RELEASED"


def test_day45_release_stamps_released_state(api):
    """PRD section 3.8: "A successful release stamps `final_interest_cents`,
    finalizes `amount_cents` as `base_cents` plus `final_interest_cents`,
    sets `released_at` from the logical clock, moves the disbursement to
    `RELEASED`, and advances the return from `REFUND_SCHEDULED` to
    `REFUND_RELEASED`."

    Design: Difficulty/boundary_precision_check/interest_free_window_day45_exactly
    """
    _taxpayer, rtn = _setup_filed_passing_return()
    disb = schedule_refund(rtn["id"])
    set_clock("2027-06-15T00:00:00Z")

    released = validate_success(
        api.release_disbursement(
            disb["id"], release_disbursement_payload(100000), ADMIN
        ),
        200,
    )
    assert released["status"] == "RELEASED"
    assert date_of(released["released_at"]) == date(2027, 6, 15)
    assert_amount_consistency(released)
    assert get_return(rtn["id"])["status"] == "REFUND_RELEASED"


def test_interest_day46_accrues_one_day(api):
    """PRD section 3.8: "Its component zero is the base as it stood at
    scheduling — the `claimed_refund_cents` at that time — accruing for the
    number of days from the anchor date to the release date minus the 45
    interest-free days, floored at zero days."
    PRD section 3.8: "Each component's interest is that component multiplied
    by the growth factor of one plus the daily rate, raised to the
    component's day count, minus one — rounded half-up to integer cents
    individually."

    Design: Corner/calculations/interest_day46_accrues_one_day
    """
    _taxpayer, rtn = _setup_filed_passing_return()
    disb = schedule_refund(rtn["id"])
    # 2027-06-16 is 46 days after the anchor: exactly one day accrues.
    set_clock("2027-06-16T00:00:00Z")

    resp = api.release_disbursement(
        disb["id"], release_disbursement_payload(100019), ADMIN
    )
    released = validate_success(resp, 200)
    # round_half_up(100000 * ((1 + 0.07/365) ** 1 - 1)) == 19.
    assert released["final_interest_cents"] == 19
    assert released["amount_cents"] == 100019


# ─── Terminal lockdown vs money consistency ──────────

def test_released_disbursement_rejects_second_release(api):
    """PRD section 3.8: "The disbursement must be `SCHEDULED` — a
    disbursement already `RELEASED` or `CANCELLED` rejects the attempt with
    `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_amount_mismatch
    """
    _taxpayer, _rtn, disb = setup_released_return(claimed_refund_cents=50000)
    assert disb["status"] == "RELEASED"

    resp = api.release_disbursement(
        disb["id"], release_disbursement_payload(1), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_terminal_rejection_masks_amount_mismatch(api):
    """PRD section 2.8: "Every request is validated against the following
    checks in strict priority order; the first failing check determines the
    response, so a higher-priority rejection always masks lower-priority
    ones."
    PRD section 2.8 check 6: "The target entity's current state permits the
    requested transition; requests against entities in a terminal state are
    rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) and all other
    impermissible transitions with `ERR_INVALID_STATE` (HTTP 409)."
    PRD section 2.8 check 12: "A disbursement release whose
    `expected_amount_cents` does not equal the computed total yields
    `ERR_DISBURSEMENT_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_amount_mismatch
    """
    _taxpayer, rtn, disb = setup_released_return(claimed_refund_cents=50000)

    # expected_amount_cents 1 also violates the p12 fiscal check, but the p6
    # terminal-state check is earlier in the ordered table and must win.
    resp = api.release_disbursement(
        disb["id"], release_disbursement_payload(1), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    assert get_return_disbursement(rtn["id"])["status"] == "RELEASED"
    assert get_return(rtn["id"])["status"] == "REFUND_RELEASED"


def test_disbursement_release_wrong_amount_rejected(api):
    """PRD section 3.8: "The release payload carries `expected_amount_cents`,
    which must equal the disbursement's `base_cents` plus the freshly
    computed `final_interest_cents`; a mismatch is rejected with
    `ERR_DISBURSEMENT_AMOUNT_MISMATCH` (HTTP 422), so the operator's
    expectation and the server's computation must agree to the cent before
    funds move."

    Design: Corner/endpoints/disbursement_release_wrong_amount_rejected
    """
    _taxpayer, rtn, disb = setup_scheduled_refund(claimed_refund_cents=50000)
    assert disb["status"] == "SCHEDULED"

    resp = api.release_disbursement(
        disb["id"], release_disbursement_payload(999999), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_AMOUNT_MISMATCH)

    assert get_return_disbursement(rtn["id"])["status"] == "SCHEDULED"


# ─── Fraud confirmation ──────────────────────────────

def test_confirm_fraud_cancels_scheduled_disbursement(api):
    """PRD section 3.8: "When the confirmed return was `REFUND_SCHEDULED`, a
    compensation step additionally moves its `SCHEDULED` disbursement to
    `CANCELLED` — no funds move, and the base and interest are voided."

    Design: Corner/state_machines/confirm_fraud_cancels_scheduled_disbursement
    """
    _taxpayer, rtn, disb = setup_scheduled_refund(claimed_refund_cents=40000)
    assert disb["status"] == "SCHEDULED"

    resp = api.confirm_fraud(
        rtn["id"], make_fraud_analyst_headers("analyst-fraud-1")
    )
    data = validate_success(resp, 200)
    assert data["status"] == "FRAUD_CONFIRMED"
    assert get_return_disbursement(rtn["id"])["status"] == "CANCELLED"


def test_confirm_fraud_on_released_return_rejected(api):
    """PRD section 3.8: "Confirming fraud is permitted while the return is
    `FILTER_HELD` or `REFUND_SCHEDULED` — attempts against any other
    non-terminal state fail the state rule with `ERR_INVALID_STATE`, and
    against a terminal return with `ERR_ALREADY_TERMINAL`."
    PRD section 2.10: "A request that targets an entity in one of the
    terminal states `REFUND_RELEASED`, `FRAUD_CONFIRMED`, `RELEASED`,
    `CANCELLED`, `VERIFIED`, `EXPIRED`, `RESOLVED`, `RETIRED`, or `SUSPENDED`
    is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409): terminal entities
    accept no further transitions."

    Design: Corner/state_machines/confirm_fraud_on_released_return_rejected
    """
    _taxpayer, rtn, _disb = setup_released_return(claimed_refund_cents=20000)

    resp = api.confirm_fraud(
        rtn["id"], make_fraud_analyst_headers("analyst-fraud-1")
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert get_return(rtn["id"])["status"] == "REFUND_RELEASED"
