"""
Two conserved quantities of the licensing contract, checked at every checkpoint.

The money invariant is the venue's four-column ledger: a part payment moves cash
from the outstanding column into the settled column, and writing off the unpaid
remainder at termination moves what is left into the voided column, so the three
columns always add back to the same lifetime figure — the compensating action
never rewrites history.  The coverage invariant is the venue's covered share
across a renewal hand-over: the predecessor's share leaves the sum at the exact
instant the successor's enters it, so a venue licensed by one society at 4600
basis points reads 4600 before the hand-over and 4600 after, never 9200 and never
zero.
"""

from test_helpers import (
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_KIND_RENEWAL,
    ASSESSMENT_STATUS_ISSUED,
    ASSESSMENT_STATUS_VOIDED,
    BILLING_INVOICED,
    BILLING_UNBILLED,
    BILLING_WRITTEN_OFF,
    CLOCK_START_INSTANT,
    COVERAGE_ACTIVE,
    COVERAGE_EXPIRED,
    COVERAGE_PENDING_ACTIVATION,
    COVERAGE_TERMINATED,
    POSTURE_PARTIALLY_COVERED,
    POSTURE_UNCOVERED,
    RENEWAL_OUTSTANDING_LIMIT_CENTS,
    SHARE_BMI_BP,
    WINDOW_KIND_ANNUAL_TERM,
    WINDOW_STATUS_ACTIVE,
    WINDOW_STATUS_VOIDED,
    admin_headers,
    assert_assessment,
    assert_bp,
    assert_count,
    assert_coverage,
    assert_days_apart,
    assert_instant_equals,
    assert_license_dimensions,
    assert_money,
    assert_venue_ledger,
    assessments_of_license,
    assessments_of_venue,
    bar_grill_venue_payload,
    bmi_payload,
    find_row,
    given_active_license,
    given_effective_schedule,
    given_society,
    given_venue,
    license_row,
    move_clock,
    payment_payload,
    renew_payload,
    terminate_payload,
    validate_success,
    venue_operator_headers,
    venue_row,
    windows_of_license,
)

_VENUE_CATEGORY = "BAR_GRILL"
_SCHEDULE_FROM = "2026-01-01T00:00:00Z"

# A term that begins at the logical clock's start-up instant, so the annual
# window activation creates really does contain "now".
_TERM_START = CLOCK_START_INSTANT
_TERM_END = "2027-08-01T00:00:00Z"
# PRD §3.7: the successor's "`term_end` exactly 365 days later".  2028 is a leap
# year, so 365 days on from 2027-08-01 lands on 2028-07-31, not 2028-08-01.
_SUCCESSOR_TERM_END = "2028-07-31T00:00:00Z"

_FEE_CENTS = 90017
_PART_PAYMENT_CENTS = 40017
_REMAINDER_CENTS = _FEE_CENTS - _PART_PAYMENT_CENTS
_TWO_TERMS_CENTS = _FEE_CENTS * 2


def _build_invoiced_licence(api):
    """One ACTIVE BMI licence and the single ISSUED initial invoice it raised."""
    bmi = given_society(api, bmi_payload())
    given_effective_schedule(api, bmi["id"], _VENUE_CATEGORY, _SCHEDULE_FROM)
    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(
        api, venue_row(api, venue["id"]), bmi["id"], _TERM_START
    )
    assert_money(licence["annual_fee_cents"], _FEE_CENTS, "annual_fee_cents")
    invoices = assessments_of_license(api, licence["id"])
    assert len(invoices) == 1, (
        f"activation should have raised exactly one invoice, got {len(invoices)}"
    )
    return {"bmi": bmi, "venue": venue, "license": licence, "invoice": invoices[0]}


def test_invariant_money_a_part_payment_shifts_cash_without_closing_the_invoice(api):
    """Forty thousand-odd cents against a ninety thousand-cent invoice moves two columns.

    PRD §2.9: "`settled_amount_cents` is the sum of `paid_amount_cents` over
    *every* assessment of the venue, whatever its status — so a partial payment
    against a still-`ISSUED` row counts here the moment the cash lands."

    PRD §3.9: "The owning licence's `billing_status` moves from `DELINQUENT` to
    `INVOICED` when the venue's `outstanding_balance_cents` has fallen to at most
    250000 cents, but it **never** reaches `PAID` on a part payment, because an
    `ISSUED` assessment necessarily remains."

    Design: Difficulty/compensating_invariant/invariant_money_ledger_across_part_payment_and_void
    """
    world = _build_invoiced_licence(api)
    assert_venue_ledger(
        venue_row(api, world["venue"]["id"]), _FEE_CENTS, 0, 0, _FEE_CENTS
    )
    assert_assessment(
        world["invoice"],
        ASSESSMENT_KIND_INITIAL,
        _FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )

    paid = validate_success(
        api.pay_assessment(
            world["invoice"]["id"],
            payment_payload(_PART_PAYMENT_CENTS),
            venue_operator_headers(world["venue"]["id"]),
        )
    )
    assert_assessment(
        paid,
        ASSESSMENT_KIND_INITIAL,
        _FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=_PART_PAYMENT_CENTS,
    )

    assert_venue_ledger(
        venue_row(api, world["venue"]["id"]),
        _REMAINDER_CENTS,
        _PART_PAYMENT_CENTS,
        0,
        _FEE_CENTS,
    )
    assert_license_dimensions(
        license_row(api, world["license"]["id"]), COVERAGE_ACTIVE, BILLING_INVOICED
    )


def test_invariant_money_writing_off_the_remainder_preserves_the_lifetime_total(api):
    """Terminating with the void switch on moves the unpaid remainder, never deletes it.

    PRD §2.9: "Those four totals satisfy a **ledger identity** that must hold after
    every forward action and after every compensating action:
    `outstanding_balance_cents` plus `settled_amount_cents` plus
    `voided_amount_cents` equals `lifetime_assessed_cents`."

    PRD §3.7: "When `void_unpaid_assessments` is true, every `FeeAssessment` of
    this licence whose `status` is `ISSUED` moves to `VOIDED` with its
    `paid_amount_cents` left exactly as it was, the licence's `billing_status`
    becomes the terminal `WRITTEN_OFF`, the venue's `outstanding_balance_cents`
    decreases by the total of `amount_cents` less `paid_amount_cents` summed over
    those voided assessments, and the venue's `voided_amount_cents` increases by
    that same total."

    Design: Difficulty/compensating_invariant/invariant_money_ledger_across_part_payment_and_void
    """
    world = _build_invoiced_licence(api)
    assert_venue_ledger(
        venue_row(api, world["venue"]["id"]), _FEE_CENTS, 0, 0, _FEE_CENTS
    )

    validate_success(
        api.pay_assessment(
            world["invoice"]["id"],
            payment_payload(_PART_PAYMENT_CENTS),
            venue_operator_headers(world["venue"]["id"]),
        )
    )
    assert_venue_ledger(
        venue_row(api, world["venue"]["id"]),
        _REMAINDER_CENTS,
        _PART_PAYMENT_CENTS,
        0,
        _FEE_CENTS,
    )

    terminated = validate_success(
        api.terminate_license(
            world["license"]["id"],
            terminate_payload(void_unpaid_assessments=True),
            admin_headers(),
        )
    )
    assert_license_dimensions(terminated, COVERAGE_TERMINATED, BILLING_WRITTEN_OFF)

    written_off = find_row(
        assessments_of_venue(api, world["venue"]["id"]), id=world["invoice"]["id"]
    )
    assert_assessment(
        written_off,
        ASSESSMENT_KIND_INITIAL,
        _FEE_CENTS,
        ASSESSMENT_STATUS_VOIDED,
        paid=_PART_PAYMENT_CENTS,
    )

    assert_venue_ledger(
        venue_row(api, world["venue"]["id"]),
        0,
        _PART_PAYMENT_CENTS,
        _REMAINDER_CENTS,
        _FEE_CENTS,
    )


def test_invariant_money_termination_voids_the_annual_window_and_empties_the_coverage(api):
    """The coverage roll-up falls to nothing once the licence's only window is voided.

    PRD §3.7: "Whatever its value, `coverage_status` becomes the terminal
    `TERMINATED` with a `version` increment, and **every** `CoverageWindow` of that
    licence still in `ACTIVE` status moves to the terminal `VOIDED`, each with its
    own `version` increment and each triggering a recomputation of the venue's
    `covered_share_bp` and `coverage_posture`."

    PRD §2.10: "`coverage_posture` is then read off that sum: `FULLY_COVERED` when
    `covered_share_bp` is at least 9500, `PARTIALLY_COVERED` when
    `covered_share_bp` is at least 1 and below 9500, and `UNCOVERED` when
    `covered_share_bp` is exactly 0."

    Design: Difficulty/compensating_invariant/invariant_money_ledger_across_part_payment_and_void
    """
    world = _build_invoiced_licence(api)
    assert_coverage(
        venue_row(api, world["venue"]["id"]), SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED
    )
    validate_success(
        api.pay_assessment(
            world["invoice"]["id"],
            payment_payload(_PART_PAYMENT_CENTS),
            venue_operator_headers(world["venue"]["id"]),
        )
    )

    validate_success(
        api.terminate_license(
            world["license"]["id"],
            terminate_payload(void_unpaid_assessments=True),
            admin_headers(),
        )
    )

    windows = windows_of_license(api, world["license"]["id"])
    annual = find_row(windows, window_kind=WINDOW_KIND_ANNUAL_TERM)
    assert annual["status"] == WINDOW_STATUS_VOIDED, (
        f"the annual window should be VOIDED, got {annual['status']!r}"
    )

    venue = venue_row(api, world["venue"]["id"])
    assert_coverage(venue, 0, POSTURE_UNCOVERED)
    assert_money(venue["lifetime_assessed_cents"], _FEE_CENTS, "lifetime_assessed_cents")


# ─── The coverage invariant across a renewal hand-over ────────────────────


def _build_pending_renewal(api):
    """One ACTIVE BMI licence for 2026-08-01 to 2027-08-01 plus its minted successor.

    The successor is created by renewing the incumbent while the clock still reads
    its start-up instant, so at this point two licence rows exist on the same
    venue-and-society calendar but only one of them is coverage.
    """
    bmi = given_society(api, bmi_payload())
    given_effective_schedule(api, bmi["id"], _VENUE_CATEGORY, _SCHEDULE_FROM)
    venue = given_venue(api, bar_grill_venue_payload())
    predecessor = given_active_license(
        api, venue_row(api, venue["id"]), bmi["id"], _TERM_START
    )
    assert_money(predecessor["annual_fee_cents"], _FEE_CENTS, "annual_fee_cents")
    assert_instant_equals(predecessor["term_end"], _TERM_END, "predecessor term_end")
    # PRD §4: a renewal brings "a successor licence" into existence, so it
    # answers 201 rather than 200.
    successor = validate_success(
        api.renew_license(
            predecessor["id"],
            renew_payload(_TERM_END, expected_license_version=predecessor["version"]),
            admin_headers(),
        ),
        201,
    )
    return {
        "bmi": bmi,
        "venue": venue,
        "predecessor": predecessor,
        "successor": successor,
    }


def test_invariant_coverage_a_pending_successor_contributes_nothing_before_activation(api):
    """Two licence rows, one covered share: the successor is not yet coverage.

    PRD §3.7: "The successor is not yet coverage: it still has to be activated, and
    activation is what expires the predecessor once the clock has passed its
    `term_end`."

    PRD §2.4: "Moving the clock writes no row and mutates no state on its own: a
    licence whose term has elapsed does not become `EXPIRED` merely because the
    clock advanced past `term_end`, and a schedule whose `effective_from` has
    passed does not become `EFFECTIVE` merely because the clock advanced past it."

    Design: Difficulty/compensating_invariant/invariant_covered_share_bp_across_renewal_handover
    """
    world = _build_pending_renewal(api)

    before_clock_move = venue_row(api, world["venue"]["id"])
    assert_coverage(before_clock_move, SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
    assert_venue_ledger(before_clock_move, _FEE_CENTS, 0, 0, _FEE_CENTS)
    assert before_clock_move["outstanding_balance_cents"] <= RENEWAL_OUTSTANDING_LIMIT_CENTS, (
        "the renewal above was only permitted because the balance sits at or below "
        f"{RENEWAL_OUTSTANDING_LIMIT_CENTS} cents"
    )
    assert_license_dimensions(
        license_row(api, world["successor"]["id"]),
        COVERAGE_PENDING_ACTIVATION,
        BILLING_UNBILLED,
    )
    assert_count(
        validate_success(api.get_society(world["bmi"]["id"], admin_headers()))[
            "licensed_venue_count"
        ],
        1,
        "licensed_venue_count before the hand-over",
    )

    move_clock(api, _TERM_END)
    after_clock_move = venue_row(api, world["venue"]["id"])
    assert_coverage(after_clock_move, SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
    assert license_row(api, world["predecessor"]["id"])["coverage_status"] == COVERAGE_ACTIVE, (
        "the predecessor stays ACTIVE until an actual business call retires it"
    )


def test_invariant_coverage_the_successor_carries_the_term_chain_and_the_verified_fee(api):
    """The successor picks up exactly where the predecessor stops, at the same price.

    PRD §3.7: "The supplied `requested_term_start` must equal the predecessor's
    `term_end` exactly, to the instant, otherwise `ERR_RENEWAL_TERM_MISMATCH` — no
    gap and no overlap is tolerated in the chain of terms."

    PRD §3.7: "Both fee fields — `provisional_annual_fee_cents` and
    `annual_fee_cents` — are computed with the **final verified** variant of §3.5,
    so they agree and `verified_fee_delta_cents` is 0; a renewal has no operator
    declaration to be provisional about."

    Design: Difficulty/compensating_invariant/invariant_covered_share_bp_across_renewal_handover
    """
    world = _build_pending_renewal(api)

    successor = license_row(api, world["successor"]["id"])
    assert successor["renewal_of_license_id"] == world["predecessor"]["id"], (
        "renewal_of_license_id must point back at the predecessor, got "
        f"{successor['renewal_of_license_id']!r}"
    )
    assert_instant_equals(successor["term_start"], _TERM_END, "successor term_start")
    assert_instant_equals(
        successor["term_end"], _SUCCESSOR_TERM_END, "successor term_end"
    )
    assert_days_apart(_TERM_END, _SUCCESSOR_TERM_END, 365, "successor term")
    assert_money(successor["annual_fee_cents"], _FEE_CENTS, "successor annual_fee_cents")
    assert_money(
        successor["provisional_annual_fee_cents"],
        _FEE_CENTS,
        "successor provisional_annual_fee_cents",
    )
    assert_money(
        successor["verified_fee_delta_cents"], 0, "successor verified_fee_delta_cents"
    )

    predecessor = license_row(api, world["predecessor"]["id"])
    assert predecessor["renewal_issued_at"] is not None, (
        "issuing the renewal stamps the predecessor's renewal_issued_at"
    )


def test_invariant_coverage_the_handover_neither_double_counts_nor_gaps(api):
    """The share leaves the predecessor and enters the successor in one act.

    PRD §3.6: "When `renewal_of_license_id` is not null *and* the current logical
    clock instant is at or after the predecessor licence's `term_end`, the
    predecessor moves from `ACTIVE` to the terminal `EXPIRED`, its `version`
    increments by 1, and the venue's `covered_share_bp` and `coverage_posture` are
    recomputed."

    PRD §2.10: "A society that holds two qualifying licences on the same venue is
    counted once."

    Design: Difficulty/compensating_invariant/invariant_covered_share_bp_across_renewal_handover
    """
    world = _build_pending_renewal(api)
    move_clock(api, _TERM_END)

    activated = validate_success(
        api.activate_license(world["successor"]["id"], admin_headers())
    )
    assert_license_dimensions(activated, COVERAGE_ACTIVE, BILLING_INVOICED)
    retired = license_row(api, world["predecessor"]["id"])
    assert retired["coverage_status"] == COVERAGE_EXPIRED, (
        f"the predecessor should have expired, got {retired['coverage_status']!r}"
    )

    venue = venue_row(api, world["venue"]["id"])
    assert_coverage(venue, SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
    assert_bp(venue["covered_share_bp"], SHARE_BMI_BP, "covered_share_bp")
    assert venue["covered_share_bp"] != SHARE_BMI_BP * 2, (
        "the one society's share must not be counted twice across the hand-over"
    )
    assert venue["covered_share_bp"] != 0, (
        "the hand-over must not leave the venue momentarily uncovered"
    )
    assert_count(
        validate_success(api.get_society(world["bmi"]["id"], admin_headers()))[
            "licensed_venue_count"
        ],
        1,
        "licensed_venue_count after the hand-over",
    )

    old_annual = find_row(
        windows_of_license(api, world["predecessor"]["id"]),
        window_kind=WINDOW_KIND_ANNUAL_TERM,
    )
    assert old_annual["status"] == WINDOW_STATUS_ACTIVE, (
        "expiry voids no windows, so the predecessor's annual window is untouched, got "
        f"{old_annual['status']!r}"
    )
    new_annual = find_row(
        windows_of_license(api, world["successor"]["id"]),
        window_kind=WINDOW_KIND_ANNUAL_TERM,
    )
    assert_instant_equals(new_annual["window_start"], _TERM_END, "new window_start")
    assert_instant_equals(
        new_annual["window_end"], _SUCCESSOR_TERM_END, "new window_end"
    )
    assert new_annual["status"] == WINDOW_STATUS_ACTIVE, (
        f"the successor's annual window should be ACTIVE, got {new_annual['status']!r}"
    )

    renewal_invoices = assessments_of_license(api, world["successor"]["id"])
    assert len(renewal_invoices) == 1, (
        f"activating the successor raises exactly one invoice, got {len(renewal_invoices)}"
    )
    assert_assessment(
        renewal_invoices[0],
        ASSESSMENT_KIND_RENEWAL,
        _FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )
    assert_venue_ledger(venue, _TWO_TERMS_CENTS, 0, 0, _TWO_TERMS_CENTS)
