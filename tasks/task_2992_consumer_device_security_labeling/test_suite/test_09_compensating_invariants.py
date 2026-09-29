"""Compensations over two different conserved quantities.

Vacating an upheld adjudication restores penalty currency exactly while leaving
the retailer-side side effect deliberately uncompensated; cancelling a bench
booking restores bench hours exactly and the freed capacity is genuinely
reusable.
"""
from test_helpers import (
    ADMIN,
    PUBLISHER,
    ApiErrorId,
    api_client,
    assert_bench_hour_ledger,
    assert_case_statuses,
    assert_grant_statuses,
    assert_money_cents,
    assert_penalty_ledger,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK

UNREGISTERED_CODE_F = "ZZ-NO-SUCH-CD-06"
PENALTY_CENTS = 28980


def _upheld_case_that_darkened_a_displayed_label():
    """An upheld penalty that suspended the grant and withdrew the display.

    Six IN_STORE units of `UNAUTHORIZED_DISPLAY` assess 28980 cents, which
    crosses the delinquency bar, so the standing cascade suspends the sponsor's
    ACTIVE grant and withdraws that grant's AUTHORIZED display.
    """
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    sponsor = fixtures.enrol_manufacturer()
    claim = fixtures.approved_claim(program=program, sponsor=sponsor)
    grant = fixtures.published_grant(claim, publisher_headers=PUBLISHER)
    store = fixtures.register_retailer(retailer_name="Cedar Home Retail")
    authorization = fixtures.authorize_display(
        grant,
        store,
        channel="IN_STORE",
        display_from="2026-08-10T00:00:00Z",
        display_until="2026-09-10T00:00:00Z",
    )
    case = fixtures.upheld_case(
        sponsor=sponsor,
        reported_scannable_code=UNREGISTERED_CODE_F,
        violation_type="UNAUTHORIZED_DISPLAY",
        violation_line_items=[factories.violation_line("LST-STORE-F", "IN_STORE", 6)],
        reporter_note="Unregistered mark on six retail units.",
    )
    assert_money_cents(case["penalty_cents"], PENALTY_CENTS, "penalty_cents")
    assert_status(sponsor.refresh(), "standing", "DELINQUENT")
    suspended = grant.refresh()
    assert_grant_statuses(suspended, "SUSPENDED", "PUBLISHED")
    assert_status(suspended, "suspension_reason", "SPONSOR_DELINQUENT")
    withdrawn = validate_success(
        api_client.get_display_authorization(authorization["id"], ADMIN)
    )
    assert_status(withdrawn, "status", "WITHDRAWN")
    return {
        "sponsor": sponsor,
        "claim": claim,
        "grant": grant,
        "store": store,
        "authorization": authorization,
        "case": case,
    }


class TestVacatedPenaltyRestoresManufacturerPenaltyLedger:
    """Vacating moves money between ledger buckets without rewriting the total."""

    def test_vacate_moves_the_amount_from_outstanding_to_vacated(self):
        """The case reaches VACATED on both dimensions and the money follows.

        PRD: "The penalty amount leaves `outstanding_penalty_cents` and enters `vacated_penalty_cents`, so `total_assessed_penalty_cents` is unchanged and the conservation identity still holds."
        Design: Difficulty/compensating_invariant/vacated_penalty_restores_manufacturer_penalty_ledger
        """
        ctx = _upheld_case_that_darkened_a_displayed_label()
        vacated = fixtures.vacate(
            ctx["case"],
            ADMIN,
            vacate_reason=(
                "Reconsideration: the reported units were counterfeit hardware, "
                "not the sponsor's."
            ),
        )
        assert_case_statuses(vacated, "VACATED", "VACATED")
        assert_money_cents(vacated["penalty_cents"], PENALTY_CENTS, "penalty_cents")

        ledger = ctx["sponsor"].refresh()
        assert_penalty_ledger(ledger, outstanding=0, paid=0, vacated=PENALTY_CENTS)

    def test_total_assessed_penalty_never_decreases_across_the_vacate(self):
        """The conserved total is the same 28980 before and after compensation.

        PRD: "For every `Manufacturer`, the sum of `outstanding_penalty_cents`, `paid_penalty_cents` and `vacated_penalty_cents` equals `total_assessed_penalty_cents` at all times, including immediately after a vacate has compensated an adjudication."
        Design: Difficulty/compensating_invariant/vacated_penalty_restores_manufacturer_penalty_ledger
        """
        ctx = _upheld_case_that_darkened_a_displayed_label()
        before = ctx["sponsor"].refresh()
        assert_penalty_ledger(before, outstanding=PENALTY_CENTS, paid=0, vacated=0)

        fixtures.vacate(ctx["case"], ADMIN)

        after = ctx["sponsor"].refresh()
        assert_penalty_ledger(after, outstanding=0, paid=0, vacated=PENALTY_CENTS)
        assert_money_cents(
            after["total_assessed_penalty_cents"],
            before["total_assessed_penalty_cents"],
            "total_assessed_penalty_cents",
        )
        assert_money_cents(
            after["total_assessed_penalty_cents"], PENALTY_CENTS, "total_assessed_penalty_cents"
        )

    def test_vacate_drops_the_upheld_case_count_and_restores_standing(self):
        """The count returns to zero and the standing is re-derived as GOOD.

        PRD: "Because those figures moved, `upheld_case_count` drops by one (the case is no longer `ADJUDICATED_UPHELD`) and `standing` is re-derived, returning to `GOOD` when `outstanding_penalty_cents` is below 25000 and `upheld_case_count` is below 3."
        Design: Difficulty/compensating_invariant/vacated_penalty_restores_manufacturer_penalty_ledger
        """
        ctx = _upheld_case_that_darkened_a_displayed_label()
        fixtures.vacate(ctx["case"], ADMIN)
        ledger = ctx["sponsor"].refresh()
        assert ledger["upheld_case_count"] == 0, ledger["upheld_case_count"]
        assert_status(ledger, "standing", "GOOD")

    def test_the_suspended_grant_comes_back_to_active(self):
        """The delinquency suspension is lifted and its reason cleared.

        PRD: "And because the standing recovered, every label grant of that subject whose `grant_status` is `SUSPENDED` with `suspension_reason` `SPONSOR_DELINQUENT` and `renewal_required` false returns to `ACTIVE` with `suspension_reason` cleared, provided the logical clock is still before that grant's `valid_until`."
        Design: Difficulty/compensating_invariant/vacated_penalty_restores_manufacturer_penalty_ledger
        """
        ctx = _upheld_case_that_darkened_a_displayed_label()
        fixtures.vacate(ctx["case"], ADMIN)
        restored = ctx["grant"].refresh()
        assert_grant_statuses(restored, "ACTIVE", "PUBLISHED")
        assert restored["suspension_reason"] is None, restored["suspension_reason"]
        assert restored["renewal_required"] is False, restored["renewal_required"]

    def test_the_withdrawn_display_is_deliberately_not_reinstated(self):
        """The retailer side of the cascade stays exactly where the suspension left it.

        PRD: "The compensation is deliberately asymmetric at its far edge: the grants come back, but the display authorizations withdrawn by the suspension are **not** reinstated."
        Design: Difficulty/compensating_invariant/vacated_penalty_restores_manufacturer_penalty_ledger
        """
        ctx = _upheld_case_that_darkened_a_displayed_label()
        fixtures.vacate(ctx["case"], ADMIN)

        authorization = validate_success(
            api_client.get_display_authorization(ctx["authorization"]["id"], ADMIN)
        )
        assert_status(authorization, "status", "WITHDRAWN")
        assert_status(authorization, "withdrawal_reason", "GRANT_SUSPENDED")

        retailer = ctx["store"].refresh()
        assert retailer["active_display_count"] == 0, retailer["active_display_count"]
        assert_status(retailer, "participation_tier", "BASELINE")


ROUTER_CATEGORY = {
    "category_code": "HOME_ROUTER",
    "display_name": "Home Router",
    "min_support_period_days": 1095,
}
TOTAL_BENCH_HOURS = 240
C1_WINDOW = ("2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z")
C2_WINDOW = ("2026-09-10T00:00:00Z", "2026-09-12T00:00:00Z")
NOVEMBER_WINDOW = ("2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z")


def _lab_with_two_scheduled_forty_eight_hour_engagements():
    """A 240-hour lab holding two SCHEDULED 48-hour bookings, so 96 are reserved."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("THIRD_PARTY_TEST", category_overrides=ROUTER_CATEGORY)
    sponsor = fixtures.enrol_manufacturer()
    lab = fixtures.register_lab()
    product = fixtures.register_product(
        program,
        sponsor,
        model_name="Northwind Router R7",
        sku="NW-RTR-R7",
        retail_units_shipped=40000,
    )
    assessment = fixtures.open_assessment(program, sponsor, product)
    fixtures.attach_responses(program, sponsor, assessment)
    assessment = validate_success(
        api_client.submit_assessment(assessment["id"], sponsor.headers), 201
    )
    ctx = {"sponsor": sponsor, "lab": lab, "assessment": assessment}
    ctx["first"] = validate_success(_book(ctx, *C1_WINDOW, 48), 201)
    ctx["second"] = validate_success(_book(ctx, *C2_WINDOW, 48), 201)

    ledger = lab.refresh()
    assert_bench_hour_ledger(ledger, reserved=96)
    assert ledger["available_bench_hours"] == 144, ledger
    assert ledger["total_bench_hours"] == TOTAL_BENCH_HOURS, ledger
    return ctx


def _book(ctx, window_start, window_end, bench_hours):
    return api_client.create_test_engagement(
        factories.create_test_engagement_payload(
            ctx["assessment"]["id"],
            ctx["lab"].id,
            window_start=window_start,
            window_end=window_end,
            bench_hours=bench_hours,
        ),
        ctx["sponsor"].headers,
    )


def _cancel(ctx, engagement, reason):
    """The lab operator performing the work cancels its own bench booking."""
    return api_client.cancel_test_engagement(
        engagement["id"],
        factories.cancel_engagement_payload(cancellation_reason=reason),
        ctx["lab"].headers,
    )


class TestCancelledEngagementRestoresLabBenchHourLedger:
    """Cancelling credits exactly its own hours back, and the freed capacity is reusable."""

    def test_cancelling_one_engagement_credits_exactly_its_own_hours(self):
        """48 of the 96 reserved hours come back, leaving 48 reserved and 192 available.

        PRD: "Cancellation is available to both the `Manufacturer` sponsoring the work and the `TestLabOperator` performing it, and it accepts a `cancellation_reason`."
        Design: Difficulty/compensating_invariant/cancelled_engagement_restores_lab_bench_hour_ledger
        """
        ctx = _lab_with_two_scheduled_forty_eight_hour_engagements()
        cancelled = validate_success(
            _cancel(ctx, ctx["first"], "Sample shipment delayed."), 201
        )
        assert_status(cancelled, "status", "CANCELLED")
        assert_status(cancelled, "cancellation_reason", "Sample shipment delayed.")

        ledger = ctx["lab"].refresh()
        assert_bench_hour_ledger(ledger, reserved=48)
        assert ledger["available_bench_hours"] == 192, ledger

    def test_cancelling_both_returns_the_ledger_to_its_pre_booking_values(self):
        """With no SCHEDULED engagement left, reserved is 0 and available is the full 240.

        PRD: "A laboratory's `reserved_bench_hours` is the sum of `bench_hours` over its engagements whose `status` is `SCHEDULED` or `IN_PROGRESS`; engagements in `COMPLETED` or `CANCELLED` are excluded."
        Design: Difficulty/compensating_invariant/cancelled_engagement_restores_lab_bench_hour_ledger
        """
        ctx = _lab_with_two_scheduled_forty_eight_hour_engagements()
        validate_success(_cancel(ctx, ctx["first"], "Sample shipment delayed."), 201)
        second = validate_success(
            _cancel(ctx, ctx["second"], "Second window released as well."), 201
        )
        assert_status(second, "status", "CANCELLED")

        ledger = ctx["lab"].refresh()
        assert_bench_hour_ledger(ledger, reserved=0)
        assert ledger["available_bench_hours"] == TOTAL_BENCH_HOURS, ledger

    def test_the_freed_window_takes_a_booking_of_the_whole_bench(self):
        """A 240-hour booking in the just-freed window succeeds and exhausts the ledger.

        PRD: "Reserving hours moves them from available to reserved; completing or cancelling an engagement moves exactly the same number back, returning `reserved_bench_hours` to precisely its pre-booking value with no drift."
        Design: Difficulty/compensating_invariant/cancelled_engagement_restores_lab_bench_hour_ledger
        """
        ctx = _lab_with_two_scheduled_forty_eight_hour_engagements()
        validate_success(_cancel(ctx, ctx["first"], "Sample shipment delayed."), 201)
        validate_success(_cancel(ctx, ctx["second"], "Second window released as well."), 201)

        rebooked = validate_success(_book(ctx, *C1_WINDOW, TOTAL_BENCH_HOURS), 201)
        assert_status(rebooked, "status", "SCHEDULED")
        assert rebooked["bench_hours"] == TOTAL_BENCH_HOURS, rebooked["bench_hours"]

        ledger = ctx["lab"].refresh()
        assert_bench_hour_ledger(ledger, reserved=TOTAL_BENCH_HOURS)
        assert ledger["available_bench_hours"] == 0, ledger

    def test_an_hour_in_a_free_calendar_window_is_still_refused(self):
        """The ledger, not the calendar, binds: 1 hour in empty November is rejected.

        PRD: "Finally the aggregate budget must hold: the requested `bench_hours` must be less than or equal to the laboratory's `available_bench_hours` as the ledger stands after the capacity check and before the write, otherwise the booking is rejected with `ERR_LAB_BENCH_HOURS_EXCEEDED`."
        Design: Difficulty/compensating_invariant/cancelled_engagement_restores_lab_bench_hour_ledger
        """
        ctx = _lab_with_two_scheduled_forty_eight_hour_engagements()
        validate_success(_cancel(ctx, ctx["first"], "Sample shipment delayed."), 201)
        validate_success(_cancel(ctx, ctx["second"], "Second window released as well."), 201)
        validate_success(_book(ctx, *C1_WINDOW, TOTAL_BENCH_HOURS), 201)

        response = _book(ctx, *NOVEMBER_WINDOW, 1)
        validate_error(response, ApiErrorId.ERR_LAB_BENCH_HOURS_EXCEEDED.value)
        assert response.status_code == 409, response.text

        ledger = ctx["lab"].refresh()
        assert_bench_hour_ledger(ledger, reserved=TOTAL_BENCH_HOURS)
        assert ledger["total_bench_hours"] == TOTAL_BENCH_HOURS, ledger

    def test_the_two_term_identity_holds_after_every_step(self):
        """Total stays 240 and reserved plus available matches it at each of the four steps.

        PRD: "For every `TestLab`, the sum of `reserved_bench_hours` and `available_bench_hours` equals `total_bench_hours` at all times."
        Design: Difficulty/compensating_invariant/cancelled_engagement_restores_lab_bench_hour_ledger
        """
        ctx = _lab_with_two_scheduled_forty_eight_hour_engagements()
        observed = []

        def _observe():
            ledger = ctx["lab"].refresh()
            assert_bench_hour_ledger(ledger)
            assert ledger["total_bench_hours"] == TOTAL_BENCH_HOURS, ledger
            observed.append(ledger["reserved_bench_hours"])

        _observe()
        validate_success(_cancel(ctx, ctx["first"], "Sample shipment delayed."), 201)
        _observe()
        validate_success(_cancel(ctx, ctx["second"], "Second window released as well."), 201)
        _observe()
        validate_success(_book(ctx, *C1_WINDOW, TOTAL_BENCH_HOURS), 201)
        _observe()
        validate_error(
            _book(ctx, *NOVEMBER_WINDOW, 1), ApiErrorId.ERR_LAB_BENCH_HOURS_EXCEEDED.value
        )
        _observe()

        assert observed == [96, 48, 0, 240, 240], observed
