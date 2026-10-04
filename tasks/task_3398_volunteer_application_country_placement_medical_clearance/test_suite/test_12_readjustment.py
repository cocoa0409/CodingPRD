"""Service completion and the readjustment allowance: variant selection,
pinned per-month rounding, the 12-month NCE boundary, and the
paid-plus-forfeited conservation invariant."""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_START,
    ET_11MO_END_CLOCK,
    ET_11MO_FORFEITED_CENTS,
    ET_11MO_GROSS_CENTS,
    ET_11MO_MONTHS,
    ET_11MO_PAID_CENTS,
    ET_12MO_END_CLOCK,
    ET_12MO_FORFEITED_CENTS,
    ET_12MO_GROSS_CENTS,
    ET_12MO_MONTHS,
    ET_12MO_PAID_CENTS,
    ET_3MO_END_CLOCK,
    ET_3MO_FORFEITED_CENTS,
    ET_3MO_GROSS_CENTS,
    ET_3MO_MONTHS,
    ET_3MO_PAID_CENTS,
    ET_6MO_END_CLOCK,
    ET_6MO_FORFEITED_CENTS,
    ET_6MO_GROSS_CENTS,
    ET_6MO_MONTHS,
    ET_6MO_PAID_CENTS,
    EXPECTED_COMPLETION_DATE,
    FULL_GROSS_CENTS,
    FULL_MONTHS,
    PENALIZED_MONTHLY_CENTS,
    TEST_USERS,
    api_client,
    assert_completion_record,
    assert_completion_record_invariants,
    complete_service_at,
    create_sworn_in_scenario,
    early_terminate_service_at,
    get_service,
    set_clock,
    validate_error,
)

DIRECTOR = TEST_USERS["country_director_headers"]

# Day 540 of service (2027-01-01 + 540 days): months_served = (540+15)//30 = 18.
ET_18MO_END_CLOCK = "2028-06-24T00:00:00Z"
ET_18MO_MONTHS = 18
ET_18MO_GROSS_CENTS = 18 * 47500  # 855000
# Day 30 of service: months_served = (30+15)//30 = 1.
ET_1MO_END_CLOCK = "2027-01-31T00:00:00Z"


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class TestCompletionGateAndFullVariant:
    def test_complete_before_term_rejected_then_full_completion(self):
        """PRD §3.8: "Completion is available only while the service is
        `ACTIVE` (`ERR_SERVICE_NOT_ACTIVE`) and only once the logical clock
        has reached the `expected_completion_date` — earlier attempts fail
        with `ERR_SERVICE_TERM_NOT_REACHED` (HTTP 422)."
        PRD §3.8: "Both paths stamp `actual_end_date` from the logical clock,
        compute `days_served` as the whole days between `service_start_date`
        and that end, derive `months_served`, end every live site placement,
        and write exactly one completion record for the service:
        `completion_type` `FULL` with `et_reason` null on completion, or
        `EARLY` with `et_reason` taken from the request's `reason`."
        PRD §3.9: "A `FULL` completion pays the standard accrual in full."
        PRD §3.9: "`nce_eligible` is true exactly when at least 12 months
        were served and either the completion is `FULL` or the
        early-termination reason is `MEDICAL`; `nce_duration_months` is 12
        when eligible and 0 otherwise."

        Design: Corner/state_machines/complete_before_term_rejected_then_full_completion
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        # Six months in: far short of the 810-day term.
        set_clock(ET_6MO_END_CLOCK)
        validate_error(
            api_client.complete_service(service["id"], DIRECTOR),
            ApiErrorId.ERR_SERVICE_TERM_NOT_REACHED, 422)
        assert get_service(service["id"])["status"] == "ACTIVE"

        # Exactly at expected_completion_date the >= boundary admits it.
        completed, record = complete_service_at(service["id"], EXPECTED_COMPLETION_DATE)
        assert completed["status"] == "COMPLETED"
        assert _ts(completed["actual_end_date"]) == _ts(EXPECTED_COMPLETION_DATE)
        assert completed["days_served"] == 810
        assert completed["months_served"] == FULL_MONTHS

        assert_completion_record(record)
        assert record["completion_type"] == "FULL"
        assert record["et_reason"] is None
        assert record["months_served"] == FULL_MONTHS  # 810 days -> 27 months
        assert record["gross_accrued_cents"] == FULL_GROSS_CENTS
        assert record["allowance_paid_cents"] == FULL_GROSS_CENTS
        assert record["allowance_forfeited_cents"] == 0
        assert record["nce_eligible"] is True
        assert record["nce_duration_months"] == 12
        assert_completion_record_invariants(record)


class TestVariantSelection:
    def test_penalized_six_month_early_termination(self):
        """PRD §3.9: "An `EARLY` termination with fewer than 18 months is
        penalized: each served month pays two-thirds of the standard rate,
        with that per-month amount rounded half-up to a whole cent before
        being multiplied by the number of months."
        PRD §3.9: "Gross accrual is months times the standard monthly rate of
        47,500 cents: `gross_accrued_cents` equals `months_served` multiplied
        by 47,500, regardless of how the service ended."

        Design: Difficulty/dual_variant_calc/readjustment_penalized_vs_standard_divergence
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        # Day 180 -> months_served 6 (< 18): the PENALIZED variant applies.
        closed, record = early_terminate_service_at(
            service["id"], "FAMILY", ET_6MO_END_CLOCK)
        assert closed["status"] == "EARLY_TERMINATED"
        assert _ts(closed["actual_end_date"]) == _ts(ET_6MO_END_CLOCK)
        assert_completion_record(record)
        assert record["completion_type"] == "EARLY"
        assert record["et_reason"] == "FAMILY"
        assert record["months_served"] == ET_6MO_MONTHS
        assert record["gross_accrued_cents"] == ET_6MO_GROSS_CENTS  # 6 * 47500
        assert record["allowance_paid_cents"] == ET_6MO_PAID_CENTS  # 6 * 31667
        # The divergence: penalized pays strictly less than the gross a
        # STANDARD-variant record would pay for the same six months.
        assert record["allowance_paid_cents"] < record["gross_accrued_cents"]
        assert record["allowance_forfeited_cents"] == ET_6MO_FORFEITED_CENTS
        assert record["nce_eligible"] is False  # 6 < 12
        assert record["nce_duration_months"] == 0
        assert_completion_record_invariants(record)

    def test_standard_eighteen_month_early_termination(self):
        """PRD §3.9: "An `EARLY` termination with at least 18 months served
        also pays in full — length of service, not the label, earns the
        standard treatment."
        PRD §3.9: "`nce_eligible` is true exactly when at least 12 months
        were served and either the completion is `FULL` or the
        early-termination reason is `MEDICAL`; `nce_duration_months` is 12
        when eligible and 0 otherwise."

        Design: Difficulty/dual_variant_calc/readjustment_penalized_vs_standard_divergence
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        # Day 540 -> months_served 18 (>= 18): EARLY but STANDARD variant.
        closed, record = early_terminate_service_at(
            service["id"], "FAMILY", ET_18MO_END_CLOCK)
        assert closed["status"] == "EARLY_TERMINATED"
        assert record["completion_type"] == "EARLY"
        assert record["months_served"] == ET_18MO_MONTHS
        assert record["gross_accrued_cents"] == ET_18MO_GROSS_CENTS
        assert record["allowance_paid_cents"] == ET_18MO_GROSS_CENTS, \
            "at 18 months the EARLY record pays the full standard accrual"
        assert record["allowance_forfeited_cents"] == 0
        # Length alone does not grant NCE: the reason is FAMILY, not MEDICAL.
        assert record["nce_eligible"] is False
        assert record["nce_duration_months"] == 0
        assert_completion_record_invariants(record)


class TestPerMonthRounding:
    def test_per_month_rounding_before_summation_three_months(self):
        """PRD §3.9: "The rounding order is pinned — round the month first,
        then multiply — so the penalized month is exactly 31,667 cents, and
        three penalized months pay 95,001 cents rather than the 95,000 that
        rounding the total instead would produce."

        Design: Difficulty/combinatorial_formula/readjustment_per_month_rounding_before_summation
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        # Day 90 -> months_served 3: 3 * 31667 = 95001, not round(142500*2/3).
        _, record = early_terminate_service_at(
            service["id"], "FAMILY", ET_3MO_END_CLOCK)
        assert record["months_served"] == ET_3MO_MONTHS
        assert record["gross_accrued_cents"] == ET_3MO_GROSS_CENTS
        assert record["allowance_paid_cents"] == ET_3MO_PAID_CENTS, \
            "3 * round_half_up(47500*2/3) = 95001; sum-then-round gives 95000"
        assert record["allowance_forfeited_cents"] == ET_3MO_FORFEITED_CENTS
        assert_completion_record_invariants(record)

    def test_per_month_rounding_before_summation_one_month(self):
        """PRD §3.9: "The rounding order is pinned — round the month first,
        then multiply — so the penalized month is exactly 31,667 cents, and
        three penalized months pay 95,001 cents rather than the 95,000 that
        rounding the total instead would produce."
        PRD §3.9: "Service converts to months by a half-month round-up:
        `months_served` is the whole days served plus fifteen, divided by
        thirty, rounded down — so the forty-fourth day of service still
        counts as one month while the forty-fifth counts as two."

        Design: Difficulty/combinatorial_formula/readjustment_per_month_rounding_before_summation
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        # Day 30 -> months_served floor((30+15)/30) = 1; the single penalized
        # month is exactly 31667 cents (47500*2/3 = 31666.66... rounded up).
        _, record = early_terminate_service_at(
            service["id"], "FAMILY", ET_1MO_END_CLOCK)
        assert record["months_served"] == 1
        assert record["gross_accrued_cents"] == 47500
        assert record["allowance_paid_cents"] == PENALIZED_MONTHLY_CENTS
        assert record["allowance_forfeited_cents"] == 47500 - PENALIZED_MONTHLY_CENTS
        assert_completion_record_invariants(record)


class TestNceTwelveMonthBoundary:
    def test_nce_boundary_eleven_months_denied(self):
        """PRD §3.9: "`nce_eligible` is true exactly when at least 12 months
        were served and either the completion is `FULL` or the
        early-termination reason is `MEDICAL`; `nce_duration_months` is 12
        when eligible and 0 otherwise."
        PRD §3.9: "Service converts to months by a half-month round-up:
        `months_served` is the whole days served plus fifteen, divided by
        thirty, rounded down — so the forty-fourth day of service still
        counts as one month while the forty-fifth counts as two."

        Design: Difficulty/boundary_precision_check/nce_eligibility_twelve_month_boundary
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        # Day 344 -> months_served floor((344+15)/30) = 11: one month short.
        _, record = early_terminate_service_at(
            service["id"], "MEDICAL", ET_11MO_END_CLOCK)
        assert record["months_served"] == ET_11MO_MONTHS
        assert record["et_reason"] == "MEDICAL"
        assert record["nce_eligible"] is False, "11 < 12 despite the MEDICAL reason"
        assert record["nce_duration_months"] == 0
        assert record["gross_accrued_cents"] == ET_11MO_GROSS_CENTS
        assert record["allowance_paid_cents"] == ET_11MO_PAID_CENTS  # 11 * 31667
        assert record["allowance_forfeited_cents"] == ET_11MO_FORFEITED_CENTS
        assert_completion_record_invariants(record)

    def test_nce_boundary_twelve_months_granted(self):
        """PRD §3.9: "`nce_eligible` is true exactly when at least 12 months
        were served and either the completion is `FULL` or the
        early-termination reason is `MEDICAL`; `nce_duration_months` is 12
        when eligible and 0 otherwise."

        Design: Difficulty/boundary_precision_check/nce_eligibility_twelve_month_boundary
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        # Day 345 -> months_served floor((345+15)/30) = 12: the boundary flips.
        _, record = early_terminate_service_at(
            service["id"], "MEDICAL", ET_12MO_END_CLOCK)
        assert record["months_served"] == ET_12MO_MONTHS
        assert record["et_reason"] == "MEDICAL"
        assert record["nce_eligible"] is True, "12 >= 12 with a MEDICAL early termination"
        assert record["nce_duration_months"] == 12
        assert record["gross_accrued_cents"] == ET_12MO_GROSS_CENTS
        assert record["allowance_paid_cents"] == ET_12MO_PAID_CENTS  # 12 * 31667
        assert record["allowance_forfeited_cents"] == ET_12MO_FORFEITED_CENTS
        assert_completion_record_invariants(record)


class TestConservationInvariant:
    def test_paid_plus_forfeited_conserves_gross_penalized(self):
        """PRD §3.9: "The withheld third is the `allowance_forfeited_cents`,
        which always equals `gross_accrued_cents` minus
        `allowance_paid_cents`, so paid plus forfeited conserves the gross."

        Design: Difficulty/compensating_invariant/allowance_paid_plus_forfeited_conserves_gross_accrual
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        _, record = early_terminate_service_at(
            service["id"], "FAMILY", ET_6MO_END_CLOCK)
        # 190002 + 94998 == 285000: the split neither leaks nor creates cents.
        assert record["gross_accrued_cents"] == ET_6MO_GROSS_CENTS
        assert (record["allowance_paid_cents"] + record["allowance_forfeited_cents"]
                == record["gross_accrued_cents"])
        assert 0 <= record["allowance_paid_cents"] <= record["gross_accrued_cents"]
        assert_completion_record_invariants(record)

    def test_paid_plus_forfeited_conserves_gross_full(self):
        """PRD §3.9: "The withheld third is the `allowance_forfeited_cents`,
        which always equals `gross_accrued_cents` minus
        `allowance_paid_cents`, so paid plus forfeited conserves the gross."
        PRD §3.9: "A `FULL` completion pays the standard accrual in full."

        Design: Difficulty/compensating_invariant/allowance_paid_plus_forfeited_conserves_gross_accrual
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        _, record = complete_service_at(service["id"], EXPECTED_COMPLETION_DATE)
        assert record["completion_type"] == "FULL"
        assert record["allowance_paid_cents"] == record["gross_accrued_cents"]
        assert record["allowance_forfeited_cents"] == 0
        assert_completion_record_invariants(record)
