"""Derived figures: the selector that picks the branch and the rounding that ends it.

Each figure here is computed by the server and never supplied by a client, so the
only way to observe the rule is to vary a single input and read the stored result.
The tests hold everything else fixed and move one selector at a time — the chart
type, the policy form, the notice date, the filing date, the model type — and
they pin the direction of each rounding, because truncation and half-up rounding
disagree by exactly the amount that decides several downstream gates.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BENCHMARK_BASIS_TOTAL_CASH_COMP,
    CHART_TYPE_IMAGING,
    CHART_TYPE_SCANNED_DOCUMENT,
    CHART_TYPE_STRUCTURED,
    CONTRACT_FORM_ASSIGNABLE,
    CONVERSION_STATUS_NOT_STARTED,
    CONVERSION_TYPE_FREESTANDING_CLINIC,
    CONVERSION_TYPE_PROVIDER_BASED_DEPARTMENT,
    DEAL_STATUS_BOARD_REVIEW,
    DEAL_STATUS_SIGNED,
    FULL_NOTICE_COVERAGE_BPS,
    HR_COVERAGE_COMPLETE_PCT,
    MIN_NOTICE_LEAD_DAYS,
    MINOR_RETENTION_AGE_BASE,
    MODEL_STRAIGHT_SALARY,
    NOVATION_ACTION_DENY,
    NOVATION_ACTION_SEND_NOTICE,
    NOVATION_DENIED,
    NOVATION_NOT_REQUESTED,
    OFFER_STATUS_DRAFT,
    OFFER_STATUS_EXTENDED,
    PACKAGE_STATUS_DRAFT,
    PAYER_TYPE_COMMERCIAL,
    PLAN_STATUS_DRAFT,
    POLICY_FORM_CLAIMS_MADE,
    PROVIDER_BASED_UPLIFT_BPS,
    RETENTION_YEARS_DEFAULT,
    RETENTION_YEARS_IMAGING,
    ROLE_CODE_MA,
    SOURCE_SYSTEM_PAPER_CHART,
    SPECIALTY_CARDIOLOGY,
    SPECIALTY_PRIMARY_CARE,
    STANDARD_FMV_CONCLUDED_CENTS,
    STANDARD_PLAN_PERCENTILE,
    STANDARD_PLAN_PER_WRVU_CENTS,
    STANDARD_PLAN_TOTAL_CENTS,
    STRUCTURE_EQUITY,
    TAIL_RATE_BPS_BY_SPECIALTY,
    TASK_HR_STAFFING_PLAN,
    TASK_STATUS_IN_PROGRESS,
)
from test_helpers.fixtures import (
    COMPENSATION_DESIGNER,
    INTEGRATION_MANAGER,
    acquisition_version,
    act_on_novation,
    board_review_deal,
    create_acquisition,
    create_batch,
    create_conversion,
    create_offer,
    create_package,
    create_payer_contract,
    create_physician,
    create_plan,
    diligence_deal,
    in_progress_task,
    read_acquisition,
    read_task,
    reset_clock,
    second_physician,
    set_offer_status,
    signed_deal,
)

# --- Statutory retention ----------------------------------------------------

LAST_ENCOUNTER_ON = "2026-07-15"
YOUNGEST_PATIENT_AGE_YEARS = 6
MINOR_RETENTION_YEARS = MINOR_RETENTION_AGE_BASE - YOUNGEST_PATIENT_AGE_YEARS
MINOR_PURGE_ELIGIBLE_ON = "2041-07-15"
DEFAULT_PURGE_ELIGIBLE_ON = "2036-07-15"
IMAGING_PURGE_ELIGIBLE_ON = "2033-07-15"
BATCH_RECORD_COUNT = 20_000

# --- Malpractice tail -------------------------------------------------------

# The occurrence deal keeps every default: no tail is required, so no rate is read.
OCCURRENCE_PURCHASE_PRICE_CENTS = STANDARD_FMV_CONCLUDED_CENTS
PRIMARY_CARE_TAIL_AT_STANDARD_TERM_CENTS = 7_200_000

# A cardiology practice on a claims-made policy buys seventy-two months of tail:
# 9,600,000 at 22500 basis points is 21,600,000 for the standard sixty-month term,
# and the twelve extra months scale it to 25,920,000.
CARDIOLOGY_PREMIUM_CENTS = 9_600_000
CARDIOLOGY_TAIL_MONTHS = 72
CARDIOLOGY_TAIL_PREMIUM_CENTS = 25_920_000
PRIMARY_CARE_RATE_ON_THE_SAME_INPUTS_CENTS = 17_280_000
CARDIOLOGY_EBITDA_CENTS = 240_000_000
CARDIOLOGY_MULTIPLE_BPS = 65_000
CARDIOLOGY_PURCHASE_PRICE_CENTS = 1_560_000_000
CARDIOLOGY_RESERVE_CENTS = 54_600_000
CARDIOLOGY_GROSS_CENTS = 1_640_520_000
CARDIOLOGY_SYNERGY_BPS = 275
CARDIOLOGY_SYNERGY_CENTS = 45_114_300
CARDIOLOGY_NET_CENTS = 1_595_405_700
CARDIOLOGY_NPI = "1730492857"
CARDIOLOGY_PHYSICIAN_NAME = "Idris Colefax MD"
CARDIOLOGY_LICENSE_EXPIRY = "2029-03-31"

# --- Patient notification ---------------------------------------------------

REQUIRED_NOTICE_COUNT = 1_200
ONE_SHORT_NOTIFIED_COUNT = 1_199
# 1199 x 10000 / 1200 is 9991.66..., truncated to 9991 rather than rounded to 9992.
ONE_SHORT_COVERAGE_BPS = 9_991
HALF_UP_COVERAGE_BPS = 9_992
NOTICES_ISSUED_ON = "2026-10-02"
LATE_NOTICES_ISSUED_ON = "2026-10-03"
CONVERSION_EFFECTIVE_ON = "2026-11-01"
SHORT_NOTICE_LEAD_DAYS = 29

# --- Credentialing committee cycles -----------------------------------------

MEETING_DAY_FILING_ON = "2026-09-15"
DAY_AFTER_MEETING_FILING_ON = "2026-09-16"
MEETING_DAY_CYCLE_KEY = "2026-09-15"
NEXT_CYCLE_KEY = "2026-10-01"
COMMERCIAL_LEAD_DAYS = 90
ROLLED_PROJECTED_EFFECTIVE_ON = "2026-12-15"

# --- Workforce coverage -----------------------------------------------------

HEADCOUNT_OF_THREE = 3
POOL_TOTAL_CENTS = 3_000_000
MA_LEGACY_WAGE_CENTS = 3_600_000
MA_PTO_HOURS = 40
MA_SERVICE_MONTHS = 30
MA_FLOOR_WAGE_CENTS = 4_200_000
MA_BONUS_CENTS = 210_000
NO_COVERAGE_PCT = 0.00
ONE_OF_THREE_PCT = 33.33
TWO_OF_THREE_PCT = 66.67
TRUNCATED_TWO_OF_THREE_PCT = 66.66
COMMITTED_FOR_TWO_CENTS = 420_000
AVAILABLE_AFTER_TWO_CENTS = 2_580_000

# --- Compensation projection ------------------------------------------------

INCENTIVE_VOLUME = 1_400
WHOLE_VOLUME_ALTERNATIVE_CENTS = 50_800_000
AT_THRESHOLD_WRVU = 3_000
AT_THRESHOLD_TOTAL_CENTS = 20_000_000
AT_THRESHOLD_PER_WRVU_CENTS = 6_667
SALARY_ONLY_BASE_CENTS = 26_500_000
MEDIAN_PERCENTILE = 50.00

# --- Payer term overlap -----------------------------------------------------

INCUMBENT_PAYER = "Aetna Choice"
OTHER_PAYER = "Cigna Connect"
INCUMBENT_EFFECTIVE_ON = "2026-11-01"
INCUMBENT_TERMINATES_ON = "2027-10-31"
REPLACEMENT_REVENUE_SHARE_BPS = 2_200
THIRD_TERM_EFFECTIVE_ON = "2027-01-01"
THIRD_TERM_TERMINATES_ON = "2027-06-30"
DENIAL_NOTE = "Aetna will not consent to assignment."
NOTICE_SENT_ON = "2026-08-01"


def test_a_minor_chart_holds_the_batch_to_the_age_of_majority(api: ApiClient):
    """The minor-derived candidate is larger than the structured base and so wins.

    PRD: "When it is true, a second candidate is computed as 21 years minus
    `youngest_patient_age_years`, holding the record until the youngest patient
    would reach the age of majority, and `retention_years` is whichever of the base
    period and that minor-derived period is larger."

    Design: Corner/calculations/minor_record_retention_overrides_the_structured_base_years
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    minors = create_batch(
        api,
        acquisition["id"],
        batch_label="PEDS-CHARTS-2026-A",
        source_system=SOURCE_SYSTEM_PAPER_CHART,
        chart_type=CHART_TYPE_STRUCTURED,
        record_count=BATCH_RECORD_COUNT,
        contains_minor_records=True,
        youngest_patient_age_years=YOUNGEST_PATIENT_AGE_YEARS,
        last_encounter_on=LAST_ENCOUNTER_ON,
    )

    assert MINOR_RETENTION_YEARS == 15
    assert minors["retention_years"] == MINOR_RETENTION_YEARS
    assert minors["legacy_purge_eligible_on"] == MINOR_PURGE_ELIGIBLE_ON
    assert minors["validated_count"] == 0
    assert minors["defect_count"] == 0
    assert minors["unprocessed_count"] == BATCH_RECORD_COUNT
    assert minors["match_rate_bps"] == 0

    adults = create_batch(
        api,
        acquisition["id"],
        batch_label="ADULT-CHARTS-2026-A",
        source_system=SOURCE_SYSTEM_PAPER_CHART,
        chart_type=CHART_TYPE_STRUCTURED,
        record_count=BATCH_RECORD_COUNT,
        contains_minor_records=False,
        last_encounter_on=LAST_ENCOUNTER_ON,
    )
    assert adults["retention_years"] == RETENTION_YEARS_DEFAULT
    assert adults["legacy_purge_eligible_on"] == DEFAULT_PURGE_ELIGIBLE_ON
    assert adults["last_encounter_on"] == minors["last_encounter_on"]


def test_the_minor_rule_also_beats_the_shorter_imaging_base(api: ApiClient):
    """Taking the larger candidate makes the imaging discount irrelevant for a child.

    PRD: "The base period is 7 years when `chart_type` is `IMAGING` and 10 years for
    both `STRUCTURED` and `SCANNED_DOCUMENT` — imaging studies carry a shorter
    statutory base than other records."

    Design: Corner/calculations/minor_record_retention_overrides_the_structured_base_years
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    imaging_minors = create_batch(
        api,
        acquisition["id"],
        batch_label="PEDS-IMAGING-2026-A",
        source_system=SOURCE_SYSTEM_PAPER_CHART,
        chart_type=CHART_TYPE_IMAGING,
        record_count=BATCH_RECORD_COUNT,
        contains_minor_records=True,
        youngest_patient_age_years=YOUNGEST_PATIENT_AGE_YEARS,
        last_encounter_on=LAST_ENCOUNTER_ON,
    )

    assert imaging_minors["retention_years"] == MINOR_RETENTION_YEARS
    assert MINOR_RETENTION_YEARS > RETENTION_YEARS_IMAGING
    assert imaging_minors["legacy_purge_eligible_on"] == MINOR_PURGE_ELIGIBLE_ON
    assert imaging_minors["contains_minor_records"] is True
    assert imaging_minors["youngest_patient_age_years"] == YOUNGEST_PATIENT_AGE_YEARS


def test_chart_type_alone_accounts_for_the_three_year_retention_gap(api: ApiClient):
    """Two adult-only batches from the same encounter date part on chart type only.

    PRD: "`legacy_purge_eligible_on` is then `last_encounter_on` plus
    `retention_years` calendar years, preserving month and day-of-month, with 29
    February mapping to 28 February in a non-leap target year."

    Design: Corner/calculations/imaging_chart_type_selects_the_seven_year_retention_base
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    imaging = create_batch(
        api,
        acquisition["id"],
        batch_label="IMAGING-2026-A",
        chart_type=CHART_TYPE_IMAGING,
        record_count=BATCH_RECORD_COUNT,
        contains_minor_records=False,
        last_encounter_on=LAST_ENCOUNTER_ON,
    )
    scanned = create_batch(
        api,
        acquisition["id"],
        batch_label="SCANNED-2026-A",
        chart_type=CHART_TYPE_SCANNED_DOCUMENT,
        record_count=BATCH_RECORD_COUNT,
        contains_minor_records=False,
        last_encounter_on=LAST_ENCOUNTER_ON,
    )

    assert imaging["retention_years"] == RETENTION_YEARS_IMAGING
    assert imaging["legacy_purge_eligible_on"] == IMAGING_PURGE_ELIGIBLE_ON
    assert scanned["retention_years"] == RETENTION_YEARS_DEFAULT
    assert scanned["legacy_purge_eligible_on"] == DEFAULT_PURGE_ELIGIBLE_ON
    assert imaging["last_encounter_on"] == LAST_ENCOUNTER_ON
    assert scanned["last_encounter_on"] == LAST_ENCOUNTER_ON
    assert scanned["retention_years"] - imaging["retention_years"] == 3


def test_an_occurrence_policy_prices_the_tail_at_zero_without_reading_the_rate(api: ApiClient):
    """The exemption short-circuits the whole tail calculation, rate table included.

    PRD: "When `tail_coverage_required` is false, `tail_premium_cents` is exactly 0
    and no rate is consulted."

    Design: Corner/calculations/occurrence_policy_form_prices_the_tail_at_exactly_zero
    """
    reset_clock(api)
    deal = board_review_deal(api)

    priced = deal["acquisition"]
    a.assert_status(priced, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    assert priced["tail_coverage_required"] is False
    a.assert_money_equals(priced["tail_premium_cents"], 0, "tail_premium_cents")
    a.assert_money_equals(
        priced["purchase_price_cents"], OCCURRENCE_PURCHASE_PRICE_CENTS, "purchase_price_cents"
    )
    assert priced["tail_coverage_months"] == 0
    assert TAIL_RATE_BPS_BY_SPECIALTY[SPECIALTY_PRIMARY_CARE] == 15_000
    assert priced["tail_premium_cents"] != PRIMARY_CARE_TAIL_AT_STANDARD_TERM_CENTS


def test_the_occurrence_deal_signs_without_any_tail_reserve_test(api: ApiClient):
    """Every downstream tail rule is gated on the same flag, so all of them are skipped.

    PRD: "When `tail_coverage_required` is true, `escrow_total_cents` must be at
    least the computed `tail_premium_cents`, or the request fails with
    `ERR_TAIL_RESERVE_INSUFFICIENT` — the escrow must be able to fund the tail it is
    there to fund."

    Design: Corner/calculations/occurrence_policy_form_prices_the_tail_at_exactly_zero
    """
    reset_clock(api)
    deal = signed_deal(api)

    signed = deal["acquisition"]
    a.assert_status(signed, DEAL_STATUS_SIGNED, "deal_status")
    assert signed["tail_coverage_required"] is False
    assert signed["tail_coverage_months"] == 0
    a.assert_money_equals(signed["tail_premium_cents"], 0, "tail_premium_cents")


def test_a_claims_made_tail_scales_by_the_specialty_rate_and_the_months(api: ApiClient):
    """Both multipliers are live: the specialty rate and the purchased term.

    PRD: "`tail_premium_cents` is then `annual_malpractice_premium_cents` multiplied
    by that rate, divided by 10000, multiplied by `tail_coverage_months`, divided by
    60, with the whole expression rounded half up to a whole cent exactly once at
    the end."

    Design: Corner/calculations/claims_made_tail_premium_scales_by_specialty_rate_and_purchased_months
    """
    reset_clock(api)
    deal = _cardiology_board_review_deal(api)

    priced = deal["acquisition"]
    assert priced["specialty"] == SPECIALTY_CARDIOLOGY
    assert priced["tail_coverage_required"] is True
    assert priced["tail_coverage_months"] == CARDIOLOGY_TAIL_MONTHS
    a.assert_money_equals(
        priced["tail_premium_cents"], CARDIOLOGY_TAIL_PREMIUM_CENTS, "tail_premium_cents"
    )
    assert TAIL_RATE_BPS_BY_SPECIALTY[SPECIALTY_CARDIOLOGY] == 22_500
    assert priced["tail_premium_cents"] != PRIMARY_CARE_RATE_ON_THE_SAME_INPUTS_CENTS


def _cardiology_board_review_deal(api: ApiClient):
    """A claims-made cardiology deal priced at BOARD_REVIEW with 72 months of tail."""
    return board_review_deal(
        api,
        physician_overrides={
            "npi": CARDIOLOGY_NPI,
            "full_name": CARDIOLOGY_PHYSICIAN_NAME,
            "specialty": SPECIALTY_CARDIOLOGY,
            "state_license_expires_on": CARDIOLOGY_LICENSE_EXPIRY,
        },
        fmv_overrides={
            "normalized_ebitda_cents": CARDIOLOGY_EBITDA_CENTS,
            "market_multiple_bps": CARDIOLOGY_MULTIPLE_BPS,
        },
        target_practice_name="Northgate Cardiology Associates",
        specialty=SPECIALTY_CARDIOLOGY,
        structure=STRUCTURE_EQUITY,
        malpractice_policy_form=POLICY_FORM_CLAIMS_MADE,
        annual_malpractice_premium_cents=CARDIOLOGY_PREMIUM_CENTS,
        tail_coverage_months=CARDIOLOGY_TAIL_MONTHS,
        trailing_annual_collections_cents=900_000_000,
        target_close_on="2026-12-01",
        required_staff_headcount=8,
        retention_pool_total_cents=6_000_000,
        escrow_total_cents=40_000_000,
    )


def test_the_tail_premium_flows_into_the_gross_the_synergy_tier_reads(api: ApiClient):
    """The tail is one of the four terms summed before the tier ladder is consulted.

    PRD: "`gross_consideration_cents` is then the sum of four terms: the base,
    `integration_reserve_cents`, `tail_premium_cents`, and `escrow_committed_cents`
    as it stands at the moment of the transition."

    Design: Corner/calculations/claims_made_tail_premium_scales_by_specialty_rate_and_purchased_months
    """
    reset_clock(api)
    deal = _cardiology_board_review_deal(api)

    priced = deal["acquisition"]
    a.assert_consideration_chain(
        priced,
        CARDIOLOGY_PURCHASE_PRICE_CENTS,
        CARDIOLOGY_RESERVE_CENTS,
        CARDIOLOGY_GROSS_CENTS,
        CARDIOLOGY_SYNERGY_BPS,
        CARDIOLOGY_SYNERGY_CENTS,
        CARDIOLOGY_NET_CENTS,
    )
    assert (
        CARDIOLOGY_PURCHASE_PRICE_CENTS
        + CARDIOLOGY_RESERVE_CENTS
        + CARDIOLOGY_TAIL_PREMIUM_CENTS
        == CARDIOLOGY_GROSS_CENTS
    )
    a.assert_money_equals(priced["escrow_committed_cents"], 0, "escrow_committed_cents")


def test_one_unnotified_patient_floors_the_coverage_short_of_complete(api: ApiClient):
    """Truncation, not rounding, is what keeps a near-complete mailing incomplete.

    PRD: "`notice_coverage_bps` is `notified_patient_count` multiplied by 10000,
    divided by `required_notice_count`, and **truncated** toward zero to whole basis
    points; notifying all but one patient never rounds up to complete coverage, so
    one missed patient out of twelve hundred reports 9991 basis points and fails."

    Design: Corner/calculations/notice_coverage_bps_truncates_one_patient_short_of_complete
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    short = create_conversion(
        api,
        acquisition["id"],
        site_name="Lakeside Annex Clinic",
        conversion_type=CONVERSION_TYPE_PROVIDER_BASED_DEPARTMENT,
        required_notice_count=REQUIRED_NOTICE_COUNT,
        notified_patient_count=ONE_SHORT_NOTIFIED_COUNT,
        notices_issued_on=NOTICES_ISSUED_ON,
        effective_on=CONVERSION_EFFECTIVE_ON,
    )
    complete = create_conversion(
        api,
        acquisition["id"],
        site_name="Lakeside Main Campus Clinic",
        conversion_type=CONVERSION_TYPE_PROVIDER_BASED_DEPARTMENT,
        required_notice_count=REQUIRED_NOTICE_COUNT,
        notified_patient_count=REQUIRED_NOTICE_COUNT,
        notices_issued_on=NOTICES_ISSUED_ON,
        effective_on=CONVERSION_EFFECTIVE_ON,
    )

    assert short["notice_coverage_bps"] == ONE_SHORT_COVERAGE_BPS
    assert short["notice_coverage_bps"] != HALF_UP_COVERAGE_BPS
    assert short["notice_coverage_bps"] < FULL_NOTICE_COVERAGE_BPS
    assert complete["notice_coverage_bps"] == FULL_NOTICE_COVERAGE_BPS
    for row in (short, complete):
        assert row["notice_lead_days"] == MIN_NOTICE_LEAD_DAYS
        assert row["provider_based_uplift_bps"] == PROVIDER_BASED_UPLIFT_BPS


def test_the_uplift_and_the_coverage_are_computed_independently(api: ApiClient):
    """A freestanding site earns no uplift yet reports the identical coverage figure.

    PRD: "`provider_based_uplift_bps` is 4000 when `conversion_type` is
    `PROVIDER_BASED_DEPARTMENT` and exactly 0 when it is `FREESTANDING_CLINIC`."

    Design: Corner/calculations/notice_coverage_bps_truncates_one_patient_short_of_complete
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    freestanding = create_conversion(
        api,
        acquisition["id"],
        site_name="Lakeside Freestanding Clinic",
        conversion_type=CONVERSION_TYPE_FREESTANDING_CLINIC,
        required_notice_count=REQUIRED_NOTICE_COUNT,
        notified_patient_count=ONE_SHORT_NOTIFIED_COUNT,
        notices_issued_on=NOTICES_ISSUED_ON,
        effective_on=CONVERSION_EFFECTIVE_ON,
    )

    assert freestanding["provider_based_uplift_bps"] == 0
    assert freestanding["notice_coverage_bps"] == ONE_SHORT_COVERAGE_BPS
    assert freestanding["notice_lead_days"] == MIN_NOTICE_LEAD_DAYS
    a.assert_status(freestanding, CONVERSION_STATUS_NOT_STARTED)


def test_the_notice_lead_time_counts_whole_days_and_is_null_when_unissued(api: ApiClient):
    """Thirty days of lead time is adequate, twenty-nine is short, and none is null.

    PRD: "`notice_lead_days` is the whole number of days from `notices_issued_on` to
    `effective_on`, and is null for as long as `notices_issued_on` is null."

    Design: Corner/calculations/notice_lead_days_counts_whole_calendar_days_to_the_effective_date
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    adequate = create_conversion(
        api,
        acquisition["id"],
        site_name="Lakeside Exactly Thirty Clinic",
        notices_issued_on=NOTICES_ISSUED_ON,
        effective_on=CONVERSION_EFFECTIVE_ON,
    )
    short = create_conversion(
        api,
        acquisition["id"],
        site_name="Lakeside One Day Short Clinic",
        notices_issued_on=LATE_NOTICES_ISSUED_ON,
        effective_on=CONVERSION_EFFECTIVE_ON,
    )
    unissued = validate_success(
        api.create_billing_conversion(
            f.without(
                f.billing_conversion_payload(
                    acquisition["id"],
                    site_name="Lakeside Unnoticed Clinic",
                    conversion_type=CONVERSION_TYPE_FREESTANDING_CLINIC,
                    required_notice_count=REQUIRED_NOTICE_COUNT,
                    effective_on=CONVERSION_EFFECTIVE_ON,
                ),
                "notices_issued_on",
                "notified_patient_count",
            ),
            INTEGRATION_MANAGER,
        ),
        201,
    )

    assert adequate["notice_lead_days"] == MIN_NOTICE_LEAD_DAYS
    assert short["notice_lead_days"] == SHORT_NOTICE_LEAD_DAYS
    a.assert_fields_null(unissued, "notices_issued_on", "notice_lead_days")
    assert unissued["notified_patient_count"] == 0
    assert unissued["notice_coverage_bps"] == 0


def test_a_package_filed_on_a_meeting_day_seats_in_that_very_meeting(api: ApiClient):
    """Lower-inclusive on both roll-forwards, so one day apart can share an effect date.

    PRD: "The assignment is lower-inclusive: a package with `submitted_on` of
    2026-09-15 belongs to the 2026-09-15 cycle, while one with `submitted_on` of
    2026-09-16 belongs to the 2026-10-01 cycle."

    Design: Corner/calculations/committee_cycle_key_is_lower_inclusive_on_a_meeting_day
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    physician_a = create_physician(api, acquisition["id"])
    physician_b = second_physician(api, acquisition["id"])
    contract = create_payer_contract(
        api,
        acquisition["id"],
        payer_name=INCUMBENT_PAYER,
        payer_type=PAYER_TYPE_COMMERCIAL,
        contract_form=CONTRACT_FORM_ASSIGNABLE,
    )

    on_day = create_package(
        api,
        acquisition["id"],
        physician_a["id"],
        contract["id"],
        submitted_on=MEETING_DAY_FILING_ON,
    )
    next_day = create_package(
        api,
        acquisition["id"],
        physician_b["id"],
        contract["id"],
        submitted_on=DAY_AFTER_MEETING_FILING_ON,
    )

    assert on_day["committee_cycle_key"] == MEETING_DAY_CYCLE_KEY
    assert next_day["committee_cycle_key"] == NEXT_CYCLE_KEY
    for row in (on_day, next_day):
        assert row["lead_days"] == COMMERCIAL_LEAD_DAYS
        assert row["retro_billing_allowed"] is False
        assert row["projected_effective_on"] == ROLLED_PROJECTED_EFFECTIVE_ON
        a.assert_status(row, PACKAGE_STATUS_DRAFT)


def _three_drafted_medical_assistant_offers(api: ApiClient):
    """A three-seat practice with three identical MA offers, all still drafted."""
    reset_clock(api)
    deal = diligence_deal(
        api,
        required_staff_headcount=HEADCOUNT_OF_THREE,
        retention_pool_total_cents=POOL_TOTAL_CENTS,
    )
    deal["offers"] = [
        create_offer(
            api,
            deal["acquisition"]["id"],
            staff_member_name=name,
            role_code=ROLE_CODE_MA,
            legacy_annual_wage_cents=MA_LEGACY_WAGE_CENTS,
            legacy_pto_hours=MA_PTO_HOURS,
            credited_service_months=MA_SERVICE_MONTHS,
            offer_expires_on=MEETING_DAY_FILING_ON,
        )
        for name in ("Priya Solano", "Kwesi Ampofo", "Noor Halabi")
    ]
    return deal


def test_workforce_coverage_rounds_half_up_to_two_decimal_places(api: ApiClient):
    """One of three is 33.33 and two of three is 66.67, not a truncated 66.66.

    PRD: "`hr_staffing_coverage_pct` counts the offers that hold a seat — those in
    `EXTENDED` or in `ACCEPTED`, since an extended offer holds a seat as surely as it
    holds pool money — multiplies that count by 100, divides by
    `required_staff_headcount`, and rounds half up to exactly two decimal places."

    Design: Corner/calculations/hr_staffing_coverage_rounds_to_two_decimal_places
    """
    deal = _three_drafted_medical_assistant_offers(api)
    acquisition_id = deal["acquisition"]["id"]

    at_draft = read_acquisition(api, acquisition_id)
    a.assert_percentage_equals(
        at_draft["hr_staffing_coverage_pct"], NO_COVERAGE_PCT, "hr_staffing_coverage_pct"
    )

    set_offer_status(api, deal["offers"][0]["id"], OFFER_STATUS_EXTENDED)
    after_one = read_acquisition(api, acquisition_id)
    a.assert_percentage_equals(
        after_one["hr_staffing_coverage_pct"], ONE_OF_THREE_PCT, "hr_staffing_coverage_pct"
    )

    set_offer_status(api, deal["offers"][1]["id"], OFFER_STATUS_EXTENDED)
    after_two = read_acquisition(api, acquisition_id)
    a.assert_percentage_equals(
        after_two["hr_staffing_coverage_pct"], TWO_OF_THREE_PCT, "hr_staffing_coverage_pct"
    )
    assert after_two["hr_staffing_coverage_pct"] != TRUNCATED_TWO_OF_THREE_PCT


def test_a_drafted_offer_moves_neither_the_coverage_nor_the_pool(api: ApiClient):
    """Every offer is priced identically, so only the seat-holding ones count.

    PRD: "Offers still in `DRAFT` do not count."

    Design: Corner/calculations/hr_staffing_coverage_rounds_to_two_decimal_places
    """
    deal = _three_drafted_medical_assistant_offers(api)
    acquisition_id = deal["acquisition"]["id"]
    line = in_progress_task(api, acquisition_id, task_code=TASK_HR_STAFFING_PLAN)

    for offer in deal["offers"]:
        a.assert_status(offer, OFFER_STATUS_DRAFT)
        a.assert_money_equals(
            offer["offered_annual_wage_cents"], MA_FLOOR_WAGE_CENTS, "offered_annual_wage_cents"
        )
        assert offer["wage_floor_applied"] is True
        a.assert_money_equals(
            offer["retention_bonus_cents"], MA_BONUS_CENTS, "retention_bonus_cents"
        )

    set_offer_status(api, deal["offers"][0]["id"], OFFER_STATUS_EXTENDED)
    set_offer_status(api, deal["offers"][1]["id"], OFFER_STATUS_EXTENDED)
    still_drafted = validate_success(
        api.get_staff_transition_offer(deal["offers"][2]["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(still_drafted, OFFER_STATUS_DRAFT)

    ledger = read_acquisition(api, acquisition_id)
    a.assert_retention_pool(
        ledger, POOL_TOTAL_CENTS, COMMITTED_FOR_TWO_CENTS, AVAILABLE_AFTER_TWO_CENTS
    )
    a.assert_percentage_equals(
        ledger["hr_staffing_coverage_pct"], TWO_OF_THREE_PCT, "hr_staffing_coverage_pct"
    )
    assert ledger["hr_staffing_coverage_pct"] < HR_COVERAGE_COMPLETE_PCT
    a.assert_status(read_task(api, line["id"]), TASK_STATUS_IN_PROGRESS)


def test_the_conversion_factor_is_paid_only_on_the_excess_volume(api: ApiClient):
    """The incentive volume is the excess over the threshold, not the whole projection.

    PRD: "Under `BASE_PLUS_INCENTIVE` the incentive volume is
    `projected_annual_wrvu` minus `threshold_wrvu`, floored at zero so a physician
    projected below the threshold earns no incentive rather than a negative one, and
    the total is `base_salary_cents` plus the product of
    `conversion_factor_cents_per_wrvu` and that incentive volume, rounded half up to
    a whole cent."

    Design: Corner/calculations/threshold_wrvu_pays_the_conversion_factor_only_above_the_threshold
    """
    reset_clock(api)
    deal = diligence_deal(api)

    plan = create_plan(api, deal["acquisition"]["id"], deal["physician"]["id"])

    a.assert_status(plan, PLAN_STATUS_DRAFT)
    a.assert_money_equals(
        plan["projected_total_cash_comp_cents"],
        STANDARD_PLAN_TOTAL_CENTS,
        "projected_total_cash_comp_cents",
    )
    assert plan["projected_total_cash_comp_cents"] != WHOLE_VOLUME_ALTERNATIVE_CENTS
    assert plan["projected_annual_wrvu"] - plan["threshold_wrvu"] == INCENTIVE_VOLUME
    a.assert_money_equals(
        plan["comp_per_wrvu_cents"], STANDARD_PLAN_PER_WRVU_CENTS, "comp_per_wrvu_cents"
    )
    assert plan["benchmark_basis"] == BENCHMARK_BASIS_TOTAL_CASH_COMP
    a.assert_percentage_equals(
        plan["benchmark_percentile"], STANDARD_PLAN_PERCENTILE, "benchmark_percentile"
    )


def test_a_plan_at_the_threshold_earns_no_incentive_at_all(api: ApiClient):
    """The floor at zero bites exactly at the threshold, and the divisor stays whole.

    PRD: "`comp_per_wrvu_cents` is then `projected_total_cash_comp_cents` divided by
    `projected_annual_wrvu`, rounded half up to a whole cent — except when
    `projected_annual_wrvu` is 0, in which case `comp_per_wrvu_cents` is exactly 0
    and no division is attempted."

    Design: Corner/calculations/threshold_wrvu_pays_the_conversion_factor_only_above_the_threshold
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    physician_id = deal["physician"]["id"]

    at_threshold = create_plan(
        api, acquisition_id, physician_id, projected_annual_wrvu=AT_THRESHOLD_WRVU
    )

    assert at_threshold["threshold_wrvu"] == AT_THRESHOLD_WRVU
    a.assert_money_equals(
        at_threshold["projected_total_cash_comp_cents"],
        AT_THRESHOLD_TOTAL_CENTS,
        "projected_total_cash_comp_cents",
    )
    a.assert_money_equals(
        at_threshold["comp_per_wrvu_cents"],
        AT_THRESHOLD_PER_WRVU_CENTS,
        "comp_per_wrvu_cents",
    )


def test_a_straight_salary_plan_projects_its_base_and_sits_at_the_median(api: ApiClient):
    """With every work-RVU input omitted the model still resolves, on the base alone.

    PRD: "Under `STRAIGHT_SALARY` it is simply `base_salary_cents`."

    Design: Corner/calculations/threshold_wrvu_pays_the_conversion_factor_only_above_the_threshold
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    version = acquisition_version(api, acquisition_id, COMPENSATION_DESIGNER)

    salary_only = validate_success(
        api.create_compensation_plan(
            f.without(
                f.compensation_plan_payload(
                    acquisition_id,
                    version,
                    deal["physician"]["id"],
                    model_type=MODEL_STRAIGHT_SALARY,
                    base_salary_cents=SALARY_ONLY_BASE_CENTS,
                ),
                "conversion_factor_cents_per_wrvu",
                "threshold_wrvu",
                "projected_annual_wrvu",
            ),
            COMPENSATION_DESIGNER,
        ),
        201,
    )

    a.assert_money_equals(
        salary_only["projected_total_cash_comp_cents"],
        SALARY_ONLY_BASE_CENTS,
        "projected_total_cash_comp_cents",
    )
    a.assert_money_equals(salary_only["comp_per_wrvu_cents"], 0, "comp_per_wrvu_cents")
    assert salary_only["benchmark_basis"] == BENCHMARK_BASIS_TOTAL_CASH_COMP
    a.assert_percentage_equals(
        salary_only["benchmark_percentile"], MEDIAN_PERCENTILE, "benchmark_percentile"
    )


def _deal_with_a_denied_incumbent_term(api: ApiClient):
    """A BOARD_REVIEW deal whose only Aetna term has been denied by the payer."""
    reset_clock(api)
    deal = board_review_deal(api)
    contract = create_payer_contract(
        api,
        deal["acquisition"]["id"],
        payer_name=INCUMBENT_PAYER,
        payer_type=PAYER_TYPE_COMMERCIAL,
        contract_form=CONTRACT_FORM_ASSIGNABLE,
        notice_days_required=0,
        effective_on=INCUMBENT_EFFECTIVE_ON,
        terminates_on=INCUMBENT_TERMINATES_ON,
    )
    act_on_novation(api, contract["id"], NOVATION_ACTION_SEND_NOTICE)
    deal["incumbent"] = act_on_novation(
        api, contract["id"], NOVATION_ACTION_DENY, note=DENIAL_NOTE
    )
    return deal


def _aetna_term(api: ApiClient, acquisition_id: str, effective_on: str, terminates_on: str, **extra):
    return api.create_payer_contract(
        f.payer_contract_payload(
            acquisition_id,
            payer_name=INCUMBENT_PAYER,
            payer_type=PAYER_TYPE_COMMERCIAL,
            contract_form=CONTRACT_FORM_ASSIGNABLE,
            effective_on=effective_on,
            terminates_on=terminates_on,
            **extra,
        ),
        INTEGRATION_MANAGER,
    )


def test_a_denied_term_stops_constraining_the_payer_calendar(api: ApiClient):
    """A term that covers nothing is not a peer, so an identical replacement is stored.

    PRD: "At creation the server compares the new term against every other contract
    that shares both the `acquisition_id` and the `payer_name` and whose
    `novation_status` is neither `DENIED` nor `TERMINATED` — denied and terminated
    contracts cover nothing and are excluded from the comparison."

    Design: Corner/calculations/payer_contract_denied_peer_excluded_from_the_overlap_set
    """
    deal = _deal_with_a_denied_incumbent_term(api)
    assert deal["incumbent"]["novation_status"] == NOVATION_DENIED
    assert deal["incumbent"]["notice_sent_on"] == NOTICE_SENT_ON

    replacement = validate_success(
        _aetna_term(
            api,
            deal["acquisition"]["id"],
            INCUMBENT_EFFECTIVE_ON,
            INCUMBENT_TERMINATES_ON,
            annual_revenue_share_bps=REPLACEMENT_REVENUE_SHARE_BPS,
        ),
        201,
    )

    assert replacement["effective_on"] == deal["incumbent"]["effective_on"]
    assert replacement["terminates_on"] == deal["incumbent"]["terminates_on"]
    assert replacement["novation_status"] == NOVATION_NOT_REQUESTED
    assert replacement["annual_revenue_share_bps"] == REPLACEMENT_REVENUE_SHARE_BPS


def test_the_peer_filter_removes_denied_rows_and_nothing_else(api: ApiClient):
    """The live replacement still contends, and the filter is still keyed on the payer.

    PRD: "The term is a closed interval on both endpoints, so two terms collide
    whenever the new `effective_on` is on or before the peer's `terminates_on` and
    the peer's `effective_on` is on or before the new `terminates_on`."

    Design: Corner/calculations/payer_contract_denied_peer_excluded_from_the_overlap_set
    """
    deal = _deal_with_a_denied_incumbent_term(api)
    acquisition_id = deal["acquisition"]["id"]
    validate_success(
        _aetna_term(
            api,
            acquisition_id,
            INCUMBENT_EFFECTIVE_ON,
            INCUMBENT_TERMINATES_ON,
            annual_revenue_share_bps=REPLACEMENT_REVENUE_SHARE_BPS,
        ),
        201,
    )

    contained = _aetna_term(
        api, acquisition_id, THIRD_TERM_EFFECTIVE_ON, THIRD_TERM_TERMINATES_ON
    )
    validate_error(contained, ApiErrorId.PAYER_CONTRACT_INTERVAL_OVERLAP, 409)

    other_payer = validate_success(
        api.create_payer_contract(
            f.payer_contract_payload(
                acquisition_id,
                payer_name=OTHER_PAYER,
                payer_type=PAYER_TYPE_COMMERCIAL,
                contract_form=CONTRACT_FORM_ASSIGNABLE,
                effective_on=INCUMBENT_EFFECTIVE_ON,
                terminates_on=INCUMBENT_TERMINATES_ON,
            ),
            INTEGRATION_MANAGER,
        ),
        201,
    )
    assert other_payer["payer_name"] == OTHER_PAYER
    assert other_payer["effective_on"] == INCUMBENT_EFFECTIVE_ON
    assert other_payer["terminates_on"] == INCUMBENT_TERMINATES_ON
