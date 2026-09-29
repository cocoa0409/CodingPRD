"""Validation corners of the aviation underwriting API.

Every boundary here is tested twice: once exactly at the limit the PRD declares,
where the request must be accepted, and once exactly one unit beyond it, where the
request must be refused with the identifier the PRD names.  Where two rules fail
on the same request, the assertion is on which of the two is reported, because the
PRD ranks its rules explicitly rather than leaving the choice open.
"""

from test_helpers import (
    AdjustmentStatus,
    ApiErrorId,
    AssessmentVerdict,
    CoverageDecision,
    CoverageStatus,
    LicenseType,
    LossType,
    NON_EXISTENT_UUID,
    OperatorType,
    PilotBand,
    PolicyStatus,
    PolicyType,
    SalvageAction,
    SalvageStatus,
    SettlementBasis,
    TerritorialLimit,
    UseClass,
    WarrantyStatus,
    validate_error,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


# An airline transport pilot whose medical runs well past every window used here,
# so no test in this module ever trips the medical gate by accident.
ATPL_PILOT = {
    "pilot_name": "Morgan Vale",
    "license_type": LicenseType.ATPL,
    "total_logged_hours": 3000,
    "hours_on_type": 300,
    "instrument_rated": False,
    "last_training_completed_at": "2026-07-01T00:00:00Z",
    "medical_expires_at": "2028-01-31T00:00:00Z",
}
POLICY_BASE_RATE_PPM = 18000


# ----------------------------------------------------------------------
# The 120 per cent over-insurance cap is inclusive
# ----------------------------------------------------------------------
OVER_INSURANCE_NEW_VALUE_CENTS = 66000000
OVER_INSURANCE_MANUFACTURE_YEAR = 2016


def _over_insurance_book(api):
    """A draft policy and an airframe whose depreciated value fixes the cap."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    airframe = fx.make_aircraft(
        api,
        f.aircraft_payload(
            registration_mark=f.unique_registration_mark(),
            manufacture_year=OVER_INSURANCE_MANUFACTURE_YEAR,
            hull_new_value_cents=OVER_INSURANCE_NEW_VALUE_CENTS,
        ),
    )
    pilot = fx.make_pilot(api, f.pilot_payload(**ATPL_PILOT))
    policy = fx.make_policy(
        api,
        operator["id"],
        base_hull_rate_ppm=POLICY_BASE_RATE_PPM,
        permitted_use_classes=[UseClass.PRIVATE, UseClass.BUSINESS],
    )
    return {
        "aircraft_id": airframe["id"],
        "pilot_id": pilot["id"],
        "policy_id": policy["id"],
    }


def _over_insurance_ceiling():
    """The greatest agreed value the airframe supports at the schedule's own year."""
    reference_year = c.calendar_year_of(f.POLICY_EFFECTIVE_FROM)
    depreciated = c.depreciated_value_cents(
        OVER_INSURANCE_NEW_VALUE_CENTS,
        OVER_INSURANCE_MANUFACTURE_YEAR,
        reference_year,
    )
    return c.over_insurance_ceiling_cents(depreciated)


def _attach(api, book, agreed_value_cents):
    """Attempt a private hull at the given agreed value, returning the response."""
    return api.create_schedule(
        f.schedule_payload(
            book["policy_id"],
            book["aircraft_id"],
            book["pilot_id"],
            use_class=UseClass.PRIVATE,
            agreed_value_cents=agreed_value_cents,
        ),
        headers=users.UNDERWRITER,
    )


def test_an_agreed_value_exactly_at_the_over_insurance_cap_is_accepted(api):
    """PRD §3.4: "Agreed value may not exceed 1,200,000 parts per million — one
    hundred and twenty per cent — of the airframe's depreciated value, where that
    depreciated value is derived exactly as in §3.1 but with the reference year
    taken as the calendar year of the schedule's `effective_from`: take that
    depreciated value, multiply by 1,200,000, divide by 1,000,000, discard the
    fraction, and require `agreed_value_cents` to be no greater than the result."

    Design: Corner/validations/corner_over_insurance_cap_accepted_at_the_cap_refused_one_cent_above
    """
    book = _over_insurance_book(api)
    ceiling = _over_insurance_ceiling()

    schedule = validate_unpaginated(_attach(api, book, ceiling), expected_status=201)
    assert schedule["agreed_value_cents"] == ceiling

    expected_rate = c.rate_ppm_for(
        POLICY_BASE_RATE_PPM,
        UseClass.PRIVATE,
        TerritorialLimit.WORLDWIDE,
        PilotBand.BAND_A,
    )
    assert schedule["rate_ppm"] == expected_rate
    assert schedule["hull_premium_cents"] == c.annual_premium_cents(
        ceiling, expected_rate, PolicyType.FLEET, 1
    )

    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["total_hull_sum_insured_cents"] == ceiling
    assert policy["live_schedule_count"] == 1


def test_one_cent_above_the_over_insurance_cap_is_refused(api):
    """PRD §3.4: "Over-insurance is refused with `ERR_OVER_INSURED_VALUE`."

    Design: Corner/validations/corner_over_insurance_cap_accepted_at_the_cap_refused_one_cent_above
    """
    book = _over_insurance_book(api)
    ceiling = _over_insurance_ceiling()

    validate_error(
        _attach(api, book, ceiling + 1), ApiErrorId.OVER_INSURED_VALUE
    )

    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["live_schedule_count"] == 0, "the refusal must create no schedule"
    assert policy["total_hull_sum_insured_cents"] == 0

    rows, meta = validate_list(
        api.list_schedules(
            headers=users.UNDERWRITER,
            params={"policy_id": book["policy_id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


# ----------------------------------------------------------------------
# The certificate number is conditionally, not structurally, mandatory
# ----------------------------------------------------------------------
CARRIER_LEGAL_NAME = "Cascade Air Charter"
CARRIER_HOME_BASE_ICAO = "KPDX"
CARRIER_AOC_NUMBER = "AOC-7781"


def test_an_air_carrier_registered_without_a_certificate_number_is_refused(api):
    """PRD §3.1: "An operator registered as an `AIR_CARRIER` without an
    `aoc_number` is refused with `ERR_CONDITIONAL_FIELD_REQUIRED`."

    Design: Corner/validations/corner_aoc_number_required_only_for_air_carriers
    """
    without_certificate = f.operator_payload(
        legal_name=CARRIER_LEGAL_NAME,
        operator_type=OperatorType.AIR_CARRIER,
        home_base_icao=CARRIER_HOME_BASE_ICAO,
    )
    assert "aoc_number" not in without_certificate, (
        "the omission under test must be a genuinely absent field"
    )
    validate_error(
        api.create_operator(without_certificate, headers=users.UNDERWRITER),
        ApiErrorId.CONDITIONAL_FIELD_REQUIRED,
    )

    with_certificate = f.operator_payload(
        legal_name=CARRIER_LEGAL_NAME,
        operator_type=OperatorType.AIR_CARRIER,
        home_base_icao=CARRIER_HOME_BASE_ICAO,
        aoc_number=CARRIER_AOC_NUMBER,
    )
    carrier = validate_unpaginated(
        api.create_operator(with_certificate, headers=users.UNDERWRITER),
        expected_status=201,
    )
    assert carrier["operator_type"] == OperatorType.AIR_CARRIER
    assert carrier["aoc_number"] == CARRIER_AOC_NUMBER


def test_the_same_omission_on_a_flight_school_registers_a_null_certificate(api):
    """PRD §3.1: "An `aoc_number` — the Air Operator Certificate reference — is
    optional in general and defaults to null, but it is mandatory whenever
    `operator_type` is `AIR_CARRIER`; supplying it when the operator is not an air
    carrier is permitted, and when it is supplied it must be between 4 and 16
    characters drawn from uppercase letters, digits and the hyphen."

    Design: Corner/validations/corner_aoc_number_required_only_for_air_carriers
    """
    school_payload = f.operator_payload()
    assert "aoc_number" not in school_payload

    school = validate_unpaginated(
        api.create_operator(school_payload, headers=users.UNDERWRITER),
        expected_status=201,
    )
    assert school["operator_type"] == OperatorType.FLIGHT_SCHOOL
    assert school["aoc_number"] is None, (
        "the byte-identical omission is a default on anything but an air carrier"
    )
    assert school["policy_count"] == 0

    # The same optional field may still be supplied by a non-carrier.
    club = validate_unpaginated(
        api.create_operator(
            f.flying_club_operator_payload(aoc_number=CARRIER_AOC_NUMBER),
            headers=users.UNDERWRITER,
        ),
        expected_status=201,
    )
    assert club["operator_type"] == OperatorType.FLYING_CLUB
    assert club["aoc_number"] == CARRIER_AOC_NUMBER


# ----------------------------------------------------------------------
# A use class is measured against the policy and against the operator
# ----------------------------------------------------------------------
USE_CLASS_AGREED_VALUE_CENTS = 30000000
PERMITTED_ON_BOTH_POLICIES = [
    UseClass.PRIVATE,
    UseClass.INSTRUCTIONAL,
    UseClass.COMMERCIAL,
]


def _two_operator_book(api):
    """A flight school and an air carrier, each with its own airframe and policy."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    school = fx.make_operator(api)
    carrier = fx.make_operator(
        api,
        f.operator_payload(
            legal_name=CARRIER_LEGAL_NAME,
            operator_type=OperatorType.AIR_CARRIER,
            home_base_icao=CARRIER_HOME_BASE_ICAO,
            aoc_number=CARRIER_AOC_NUMBER,
        ),
    )
    school_airframe = fx.make_aircraft(
        api,
        f.single_piston_aircraft_payload(
            registration_mark=f.unique_registration_mark()
        ),
    )
    carrier_airframe = fx.make_aircraft(
        api,
        f.single_piston_aircraft_payload(
            registration_mark=f.unique_registration_mark()
        ),
    )
    pilot = fx.make_pilot(api, f.pilot_payload(**ATPL_PILOT))
    school_policy = fx.make_policy(
        api,
        school["id"],
        base_hull_rate_ppm=POLICY_BASE_RATE_PPM,
        permitted_use_classes=PERMITTED_ON_BOTH_POLICIES,
    )
    carrier_policy = fx.make_policy(
        api,
        carrier["id"],
        base_hull_rate_ppm=POLICY_BASE_RATE_PPM,
        permitted_use_classes=PERMITTED_ON_BOTH_POLICIES,
    )
    return {
        "pilot_id": pilot["id"],
        "school_policy_id": school_policy["id"],
        "carrier_policy_id": carrier_policy["id"],
        "school_aircraft_id": school_airframe["id"],
        "carrier_aircraft_id": carrier_airframe["id"],
    }


def _attach_use_class(api, book, side, use_class):
    """Attempt one hull of the given use class on one of the two policies."""
    return api.create_schedule(
        f.schedule_payload(
            book[f"{side}_policy_id"],
            book[f"{side}_aircraft_id"],
            book["pilot_id"],
            use_class=use_class,
            agreed_value_cents=USE_CLASS_AGREED_VALUE_CENTS,
        ),
        headers=users.UNDERWRITER,
    )


def test_a_use_class_the_operator_type_cannot_carry_is_refused(api):
    """PRD §3.4: "The `use_class` must appear in the policy's
    `permitted_use_classes` and must be plausible for the operator:
    `INSTRUCTIONAL` requires the operator's `operator_type` to be `FLIGHT_SCHOOL`
    or `FLYING_CLUB`, and `COMMERCIAL` requires `operator_type` to be
    `AIR_CARRIER` with a non-null `aoc_number`."

    Design: Corner/validations/corner_use_class_must_suit_both_policy_and_operator_type
    """
    book = _two_operator_book(api)

    # Instruction on an air carrier, and commercial work at a flight school, are
    # both refused even though each policy lists both classes.
    validate_error(
        _attach_use_class(api, book, "carrier", UseClass.INSTRUCTIONAL),
        ApiErrorId.USE_CLASS_NOT_PERMITTED,
    )
    validate_error(
        _attach_use_class(api, book, "school", UseClass.COMMERCIAL),
        ApiErrorId.USE_CLASS_NOT_PERMITTED,
    )

    # Each class attaches on the operator type that can carry it.
    instructional = validate_unpaginated(
        _attach_use_class(api, book, "school", UseClass.INSTRUCTIONAL),
        expected_status=201,
    )
    commercial = validate_unpaginated(
        _attach_use_class(api, book, "carrier", UseClass.COMMERCIAL),
        expected_status=201,
    )

    expected_instructional_rate = c.rate_ppm_for(
        POLICY_BASE_RATE_PPM,
        UseClass.INSTRUCTIONAL,
        TerritorialLimit.WORLDWIDE,
        PilotBand.BAND_A,
    )
    expected_commercial_rate = c.rate_ppm_for(
        POLICY_BASE_RATE_PPM,
        UseClass.COMMERCIAL,
        TerritorialLimit.WORLDWIDE,
        PilotBand.BAND_A,
    )
    assert instructional["rate_ppm"] == expected_instructional_rate
    assert instructional["hull_premium_cents"] == c.annual_premium_cents(
        USE_CLASS_AGREED_VALUE_CENTS,
        expected_instructional_rate,
        PolicyType.FLEET,
        1,
    )
    assert commercial["rate_ppm"] == expected_commercial_rate
    assert commercial["hull_premium_cents"] == c.annual_premium_cents(
        USE_CLASS_AGREED_VALUE_CENTS, expected_commercial_rate, PolicyType.FLEET, 1
    )

    assert fx.fetch_policy(api, book["school_policy_id"])["live_schedule_count"] == 1
    assert fx.fetch_policy(api, book["carrier_policy_id"])["live_schedule_count"] == 1


def test_a_use_class_absent_from_the_policy_is_refused_on_any_operator(api):
    """PRD §3.4: "Either failure yields `ERR_USE_CLASS_NOT_PERMITTED`."

    Design: Corner/validations/corner_use_class_must_suit_both_policy_and_operator_type
    """
    book = _two_operator_book(api)
    assert UseClass.BUSINESS not in PERMITTED_ON_BOTH_POLICIES

    for side in ("school", "carrier"):
        validate_error(
            _attach_use_class(api, book, side, UseClass.BUSINESS),
            ApiErrorId.USE_CLASS_NOT_PERMITTED,
        )
        policy = fx.fetch_policy(api, book[f"{side}_policy_id"])
        assert policy["live_schedule_count"] == 0
        assert policy["total_hull_sum_insured_cents"] == 0


# ----------------------------------------------------------------------
# The survey instant is bounded on both sides, by two moving references
# ----------------------------------------------------------------------
ASSESSMENT_LOSS_DATE = f.CLOCK_AFTER_LOSS
SURVEY_CLOCK = f.CLOCK_LATE_TERM
ONE_DAY_BEFORE_THE_LOSS = "2026-10-14T00:00:00Z"
ONE_DAY_AFTER_THE_CLOCK = "2026-11-02T00:00:00Z"
EARLY_REPAIR_ESTIMATE_CENTS = 12000000
LATER_REPAIR_ESTIMATE_CENTS = 15000000


def _investigating_claim(api):
    """A hull damage claim under investigation, with the clock past the loss."""
    book = fx.bound_policy_with_hull(api)
    fx.advance_clock(api, SURVEY_CLOCK)
    return fx.investigated_claim(api, book, loss_date=ASSESSMENT_LOSS_DATE)


def _survey(api, claim_id, assessed_at, repair_cost_estimate_cents, reference):
    """Attempt one damage assessment, returning the raw response."""
    return api.create_damage_assessment(
        f.damage_assessment_payload(
            claim_id,
            repair_cost_estimate_cents=repair_cost_estimate_cents,
            assessed_at=assessed_at,
            assessor_reference=reference,
        ),
        headers=users.CLAIMS_ADJUSTER,
    )


def test_a_survey_before_the_loss_or_after_the_clock_is_refused(api):
    """PRD §3.9: "The `assessed_at` instant must be at or after the claim's
    `loss_date` and must not be after the current logical clock; either failure is
    refused with `ERR_ASSESSED_AT_OUT_OF_RANGE`."

    Design: Corner/validations/corner_assessment_timestamp_bounded_by_loss_date_and_clock
    """
    book = _investigating_claim(api)

    validate_error(
        _survey(
            api,
            book["claim_id"],
            ONE_DAY_BEFORE_THE_LOSS,
            EARLY_REPAIR_ESTIMATE_CENTS,
            "ASR-EARLY",
        ),
        ApiErrorId.ASSESSED_AT_OUT_OF_RANGE,
    )
    validate_error(
        _survey(
            api,
            book["claim_id"],
            ONE_DAY_AFTER_THE_CLOCK,
            EARLY_REPAIR_ESTIMATE_CENTS,
            "ASR-LATE",
        ),
        ApiErrorId.ASSESSED_AT_OUT_OF_RANGE,
    )

    claim = fx.fetch_claim(api, book["claim_id"])
    assert claim["assessment_count"] == 0
    assert claim["ctl_flag"] is False
    assert claim["ctl_ratio_ppm"] is None
    assert claim["adjustment_status"] == AdjustmentStatus.INVESTIGATING

    rows, meta = validate_list(
        api.list_damage_assessments(
            headers=users.UNDERWRITER,
            params={"claim_id": book["claim_id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_survey_exactly_at_the_loss_date_or_exactly_at_the_clock_is_accepted(api):
    """PRD §3.9: "Its `verdict` is `CONSTRUCTIVE_TOTAL_LOSS` when that ratio has
    reached at least 750,000 parts per million — seventy-five per cent of agreed
    value — and `REPAIRABLE` otherwise."

    Design: Corner/validations/corner_assessment_timestamp_bounded_by_loss_date_and_clock
    """
    book = _investigating_claim(api)
    agreed_value = book["schedule"]["agreed_value_cents"]

    at_loss = validate_unpaginated(
        _survey(
            api,
            book["claim_id"],
            ASSESSMENT_LOSS_DATE,
            EARLY_REPAIR_ESTIMATE_CENTS,
            "ASR-AT-LOSS",
        ),
        expected_status=201,
    )
    at_clock = validate_unpaginated(
        _survey(
            api,
            book["claim_id"],
            SURVEY_CLOCK,
            LATER_REPAIR_ESTIMATE_CENTS,
            "ASR-AT-CLOCK",
        ),
        expected_status=201,
    )

    expected_at_loss = c.ctl_ratio_ppm(EARLY_REPAIR_ESTIMATE_CENTS, agreed_value)
    expected_at_clock = c.ctl_ratio_ppm(LATER_REPAIR_ESTIMATE_CENTS, agreed_value)
    assert at_loss["ctl_ratio_ppm"] == expected_at_loss
    assert at_loss["verdict"] == AssessmentVerdict.REPAIRABLE
    assert at_clock["ctl_ratio_ppm"] == expected_at_clock
    assert at_clock["verdict"] == AssessmentVerdict.REPAIRABLE
    assert expected_at_clock < c.CTL_THRESHOLD_PPM

    claim = fx.fetch_claim(api, book["claim_id"])
    assert claim["assessment_count"] == 2, "only the accepted surveys are counted"
    assert claim["ctl_flag"] is False
    assert claim["ctl_ratio_ppm"] == expected_at_clock
    assert claim["loss_type"] == LossType.HULL_DAMAGE


# ----------------------------------------------------------------------
# The hull aggregate is a collective ceiling, tested inclusively
# ----------------------------------------------------------------------
AGGREGATE_LIMIT_CENTS = 60000000
AGGREGATE_AGREED_VALUE_CENTS = 30000000
AGGREGATE_NEW_VALUE_CENTS = 40000000
AGGREGATE_MANUFACTURE_YEAR = 2020


def _aggregate_book(api):
    """Three interchangeable airframes and a policy whose aggregate holds two."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    airframes = [
        fx.make_aircraft(
            api,
            f.single_piston_aircraft_payload(
                registration_mark=f.unique_registration_mark(),
                manufacture_year=AGGREGATE_MANUFACTURE_YEAR,
                hull_new_value_cents=AGGREGATE_NEW_VALUE_CENTS,
            ),
        )
        for _ in range(3)
    ]
    pilot = fx.make_pilot(api, f.pilot_payload(**ATPL_PILOT))
    policy = fx.make_policy(
        api,
        operator["id"],
        base_hull_rate_ppm=POLICY_BASE_RATE_PPM,
        hull_aggregate_limit_cents=AGGREGATE_LIMIT_CENTS,
        permitted_use_classes=[UseClass.PRIVATE, UseClass.BUSINESS],
    )
    return {
        "aircraft_ids": [airframe["id"] for airframe in airframes],
        "pilot_id": pilot["id"],
        "policy_id": policy["id"],
    }


def _attach_to_aggregate(api, book, index, agreed_value_cents):
    """Attempt one private hull on the aggregate-limited policy."""
    return api.create_schedule(
        f.schedule_payload(
            book["policy_id"],
            book["aircraft_ids"][index],
            book["pilot_id"],
            use_class=UseClass.PRIVATE,
            agreed_value_cents=agreed_value_cents,
        ),
        headers=users.UNDERWRITER,
    )


def _individually_within_the_over_insurance_cap():
    """Each hull in this block clears the per-airframe cap on its own."""
    depreciated = c.depreciated_value_cents(
        AGGREGATE_NEW_VALUE_CENTS,
        AGGREGATE_MANUFACTURE_YEAR,
        c.calendar_year_of(f.POLICY_EFFECTIVE_FROM),
    )
    return AGGREGATE_AGREED_VALUE_CENTS <= c.over_insurance_ceiling_cents(depreciated)


def test_the_hull_aggregate_counts_the_schedule_being_created_and_is_inclusive(api):
    """PRD §3.4: "Separately, the policy's hull sum insured may not outgrow its
    aggregate: the sum of `agreed_value_cents` over the policy's live schedules,
    counting the one being created or revised, must be no greater than
    `hull_aggregate_limit_cents`, and a breach is refused with
    `ERR_HULL_AGGREGATE_EXCEEDED`."

    Design: Corner/validations/corner_hull_aggregate_limit_is_collective_not_per_schedule
    """
    book = _aggregate_book(api)
    assert _individually_within_the_over_insurance_cap()

    first = validate_unpaginated(
        _attach_to_aggregate(api, book, 0, AGGREGATE_AGREED_VALUE_CENTS),
        expected_status=201,
    )
    assert (
        fx.fetch_policy(api, book["policy_id"])["total_hull_sum_insured_cents"]
        == AGGREGATE_AGREED_VALUE_CENTS
    )

    second = validate_unpaginated(
        _attach_to_aggregate(api, book, 1, AGGREGATE_AGREED_VALUE_CENTS),
        expected_status=201,
    )
    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["total_hull_sum_insured_cents"] == AGGREGATE_LIMIT_CENTS, (
        "the running sum may land exactly on the aggregate"
    )
    assert policy["live_schedule_count"] == 2

    expected_rate = c.rate_ppm_for(
        POLICY_BASE_RATE_PPM,
        UseClass.PRIVATE,
        TerritorialLimit.WORLDWIDE,
        PilotBand.BAND_A,
    )
    expected_premium = c.annual_premium_cents(
        AGGREGATE_AGREED_VALUE_CENTS, expected_rate, PolicyType.FLEET, 2
    )
    for schedule in (first, second):
        assert schedule["rate_ppm"] == expected_rate
        assert schedule["hull_premium_cents"] == expected_premium


def test_one_cent_past_the_hull_aggregate_is_refused_however_small_the_hull(api):
    """PRD §3.4: "Separately, the policy's hull sum insured may not outgrow its
    aggregate: the sum of `agreed_value_cents` over the policy's live schedules,
    counting the one being created or revised, must be no greater than
    `hull_aggregate_limit_cents`, and a breach is refused with
    `ERR_HULL_AGGREGATE_EXCEEDED`."

    Design: Corner/validations/corner_hull_aggregate_limit_is_collective_not_per_schedule
    """
    book = _aggregate_book(api)
    validate_unpaginated(
        _attach_to_aggregate(api, book, 0, AGGREGATE_AGREED_VALUE_CENTS),
        expected_status=201,
    )
    validate_unpaginated(
        _attach_to_aggregate(api, book, 1, AGGREGATE_AGREED_VALUE_CENTS),
        expected_status=201,
    )

    validate_error(
        _attach_to_aggregate(api, book, 2, 1), ApiErrorId.HULL_AGGREGATE_EXCEEDED
    )

    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["total_hull_sum_insured_cents"] == AGGREGATE_LIMIT_CENTS
    assert policy["live_schedule_count"] == 2
    assert policy["status"] == PolicyStatus.DRAFT


# ----------------------------------------------------------------------
# A lapsed medical blocks attachment outright, measured at inception
# ----------------------------------------------------------------------
MEDICAL_LAPSED_AT = "2026-08-31T00:00:00Z"
MEDICAL_EXPIRING_AT_INCEPTION = f.POLICY_EFFECTIVE_FROM
MEDICAL_AGREED_VALUE_CENTS = 30000000


def _medical_book(api):
    """Two otherwise identical pilots, differing only in when the medical lapses."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    airframes = [
        fx.make_aircraft(
            api,
            f.single_piston_aircraft_payload(
                registration_mark=f.unique_registration_mark(),
                manufacture_year=AGGREGATE_MANUFACTURE_YEAR,
                hull_new_value_cents=AGGREGATE_NEW_VALUE_CENTS,
            ),
        )
        for _ in range(2)
    ]
    lapsed = fx.make_pilot(
        api,
        f.pilot_payload(
            **dict(
                ATPL_PILOT,
                pilot_name="Lapsed Medical Pilot",
                medical_expires_at=MEDICAL_LAPSED_AT,
            )
        ),
    )
    boundary = fx.make_pilot(
        api,
        f.pilot_payload(
            **dict(
                ATPL_PILOT,
                pilot_name="Boundary Medical Pilot",
                medical_expires_at=MEDICAL_EXPIRING_AT_INCEPTION,
            )
        ),
    )
    policy = fx.make_policy(
        api,
        operator["id"],
        base_hull_rate_ppm=POLICY_BASE_RATE_PPM,
        permitted_use_classes=[UseClass.PRIVATE, UseClass.BUSINESS],
    )
    return {
        "policy_id": policy["id"],
        "lapsed_pilot_id": lapsed["id"],
        "boundary_pilot_id": boundary["id"],
        "aircraft_ids": [airframe["id"] for airframe in airframes],
    }


def _attach_with_pilot(api, book, index, pilot_id):
    """Attempt a private hull naming one of the two pilots."""
    return api.create_schedule(
        f.schedule_payload(
            book["policy_id"],
            book["aircraft_ids"][index],
            pilot_id,
            use_class=UseClass.PRIVATE,
            agreed_value_cents=MEDICAL_AGREED_VALUE_CENTS,
        ),
        headers=users.UNDERWRITER,
    )


def test_a_medical_lapsing_before_cover_starts_blocks_attachment_outright(api):
    """PRD §3.4: "The named pilot's medical must still be current when cover
    starts, meaning `medical_expires_at` must be at or after the schedule's
    `effective_from`; a lapsed medical blocks attachment outright with
    `ERR_PILOT_MEDICAL_EXPIRED` and is not treated as a warranty matter."

    Design: Corner/validations/corner_expired_medical_blocks_attachment_outright
    """
    book = _medical_book(api)
    assert c.parse_instant(MEDICAL_LAPSED_AT) < c.parse_instant(
        f.POLICY_EFFECTIVE_FROM
    )

    validate_error(
        _attach_with_pilot(api, book, 0, book["lapsed_pilot_id"]),
        ApiErrorId.PILOT_MEDICAL_EXPIRED,
    )

    rows, meta = validate_list(
        api.list_schedules(
            headers=users.UNDERWRITER,
            params={"named_pilot_id": book["lapsed_pilot_id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 0, (
        "the refusal must leave no schedule behind, suspended or otherwise"
    )
    assert rows == []

    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["live_schedule_count"] == 0
    assert policy["total_hull_sum_insured_cents"] == 0


def test_a_medical_expiring_exactly_at_inception_still_attaches(api):
    """PRD §3.4: "Either way the schedule is born with `coverage_status` `PENDING`
    and `warranty_status` `PENDING_EVIDENCE`, the latter recording that evidence of
    the pilot warranty has not yet been sighted."

    Design: Corner/validations/corner_expired_medical_blocks_attachment_outright
    """
    book = _medical_book(api)

    schedule = validate_unpaginated(
        _attach_with_pilot(api, book, 1, book["boundary_pilot_id"]),
        expected_status=201,
    )
    assert schedule["named_pilot_id"] == book["boundary_pilot_id"]
    assert schedule["coverage_status"] == CoverageStatus.PENDING
    assert schedule["warranty_status"] == WarrantyStatus.PENDING_EVIDENCE
    assert schedule["warranty_breach_reason"] is None

    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["live_schedule_count"] == 1
    assert policy["total_hull_sum_insured_cents"] == MEDICAL_AGREED_VALUE_CENTS


# ----------------------------------------------------------------------
# The precedence ladder reports the lowest-numbered failing rule
# ----------------------------------------------------------------------
def _policy_with_nothing_to_insure(api):
    """A draft policy carrying no schedules, so a bind would fail at the last rank."""
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    policy = fx.make_policy(api, operator["id"])
    assert policy["status"] == PolicyStatus.DRAFT
    assert policy["live_schedule_count"] == 0
    return policy


def test_authentication_and_role_recognition_outrank_resource_existence(api):
    """PRD §2.11: "When a single request would fail more than one rule, the outcome
    is not free choice: the rules form a strict ladder and the highest-ranked
    failing rule decides the response."

    Design: Corner/validations/corner_validation_ladder_returns_the_lowest_priority_number
    """
    policy = _policy_with_nothing_to_insure(api)

    # Both requests also name a policy that does not exist, which would be a 404.
    validate_error(
        api.bind_policy(NON_EXISTENT_UUID, headers=users.NO_HEADERS),
        ApiErrorId.MISSING_AUTH_HEADERS,
    )
    validate_error(
        api.bind_policy(NON_EXISTENT_UUID, headers=users.UNKNOWN_ROLE),
        ApiErrorId.UNKNOWN_ROLE,
    )

    unchanged = fx.fetch_policy(api, policy["id"])
    assert unchanged["status"] == PolicyStatus.DRAFT
    assert unchanged["version"] == policy["version"]


def test_authorisation_outranks_state_and_existence_outranks_request_shape(api):
    """PRD §2.11: "When a single request would fail more than one rule, the outcome
    is not free choice: the rules form a strict ladder and the highest-ranked
    failing rule decides the response."

    Design: Corner/validations/corner_validation_ladder_returns_the_lowest_priority_number
    """
    policy = _policy_with_nothing_to_insure(api)

    # A broker binding a policy that has nothing to insure fails two rules at once;
    # the authorisation rule outranks the state rule.
    validate_error(
        api.bind_policy(policy["id"], headers=users.BROKER), ApiErrorId.UNAUTHORIZED
    )

    # A value revision on a schedule that does not exist, with a body missing both
    # of its mandatory fields, is answered by the existence rule.
    validate_error(
        api.revise_schedule_value(NON_EXISTENT_UUID, {}, headers=users.UNDERWRITER),
        ApiErrorId.SCHEDULE_NOT_FOUND,
    )

    unchanged = fx.fetch_policy(api, policy["id"])
    assert unchanged["status"] == PolicyStatus.DRAFT
    assert unchanged["version"] == policy["version"]


# ----------------------------------------------------------------------
# The basis gate must be passed before the salvage gate is even reachable
# ----------------------------------------------------------------------
SETTLEMENT_HULL_DEDUCTIBLE_PPM = 15000
SETTLEMENT_LOSS_DATE = f.CLOCK_AFTER_LOSS
SETTLEMENT_CLOCK = f.CLOCK_LATE_TERM
SETTLEMENT_SURVEY_AT = "2026-10-25T00:00:00Z"
SETTLEMENT_REPAIR_ESTIMATE_CENTS = 40000000
SETTLEMENT_RESERVE_CENTS = 40000000


def _reserved_claim_without_evidence(api):
    """A reserved claim on a compliant hull, carrying no assessment and no salvage."""
    book = fx.bound_policy_with_hull(
        api,
        compliant_warranty=True,
        base_hull_rate_ppm=POLICY_BASE_RATE_PPM,
        hull_deductible_ppm=SETTLEMENT_HULL_DEDUCTIBLE_PPM,
    )
    fx.advance_clock(api, SETTLEMENT_CLOCK)
    book = fx.investigated_claim(api, book, loss_date=SETTLEMENT_LOSS_DATE)
    book["claim"] = fx.decide_coverage(
        api,
        book["claim_id"],
        decision=CoverageDecision.COVERED,
        reserve_cents=SETTLEMENT_RESERVE_CENTS,
    )
    return book


def _attempt_agreed_value_settlement(api, claim_id):
    """The one settlement request that this block repeats unchanged."""
    return api.settle_claim(
        claim_id,
        f.settlement_payload(SettlementBasis.AGREED_VALUE),
        headers=users.SECOND_CLAIMS_ADJUSTER,
    )


def _append_total_loss_survey(api, book):
    """One assessment large enough to carry the claim over the total-loss line."""
    return fx.make_damage_assessment(
        api,
        book["claim_id"],
        repair_cost_estimate_cents=SETTLEMENT_REPAIR_ESTIMATE_CENTS,
        assessed_at=SETTLEMENT_SURVEY_AT,
        assessor_reference="ASR-9200",
    )


def test_the_basis_check_is_reported_before_the_salvage_check(api):
    """PRD §3.10: "The requested basis must match the claim's evidence, and a
    mismatch is refused with `ERR_SETTLEMENT_BASIS_NOT_PERMITTED`: `AGREED_VALUE`
    requires the claim's `ctl_flag` to be true **and** the schedule's
    `warranty_status` to be exactly `COMPLIANT`; `DEPRECIATED_VALUE` requires
    `ctl_flag` to be true; `PARTIAL_REPAIR` requires `ctl_flag` to be false; and
    every basis requires `assessment_count` to be at least 1, so a claim with no
    assessment cannot be settled on any basis."

    Design: Corner/validations/corner_settlement_basis_check_gates_the_salvage_check
    """
    book = _reserved_claim_without_evidence(api)
    assert book["claim"]["adjustment_status"] == AdjustmentStatus.RESERVED
    assert book["claim"]["assessment_count"] == 0
    assert book["claim"]["salvage_status"] == SalvageStatus.NONE

    # Both the basis rule and the salvage rule fail here; the basis rule answers.
    validate_error(
        _attempt_agreed_value_settlement(api, book["claim_id"]),
        ApiErrorId.SETTLEMENT_BASIS_NOT_PERMITTED,
    )
    held = fx.fetch_claim(api, book["claim_id"])
    assert held["adjustment_status"] == AdjustmentStatus.RESERVED
    assert held["reserve_cents"] == SETTLEMENT_RESERVE_CENTS

    agreed_value = book["schedule"]["agreed_value_cents"]
    assessment = _append_total_loss_survey(api, book)
    expected_ratio = c.ctl_ratio_ppm(SETTLEMENT_REPAIR_ESTIMATE_CENTS, agreed_value)
    assert expected_ratio >= c.CTL_THRESHOLD_PPM
    assert assessment["ctl_ratio_ppm"] == expected_ratio
    assert assessment["verdict"] == AssessmentVerdict.CONSTRUCTIVE_TOTAL_LOSS

    promoted = fx.fetch_claim(api, book["claim_id"])
    assert promoted["ctl_flag"] is True
    assert promoted["loss_type"] == LossType.TOTAL_LOSS

    # The basis rule now passes, so the next rule in the chain is finally reached.
    validate_error(
        _attempt_agreed_value_settlement(api, book["claim_id"]),
        ApiErrorId.SALVAGE_DISPOSITION_REQUIRED,
    )
    still_held = fx.fetch_claim(api, book["claim_id"])
    assert still_held["adjustment_status"] == AdjustmentStatus.RESERVED
    assert still_held["reserve_cents"] == SETTLEMENT_RESERVE_CENTS
    assert still_held["salvage_status"] == SalvageStatus.NONE
    assert still_held["settlement_amount_cents"] is None


def test_the_same_settlement_request_succeeds_once_both_gates_are_satisfied(api):
    """PRD §3.10: "Where the basis is a total-loss basis — `AGREED_VALUE` or
    `DEPRECIATED_VALUE` — the claim's `salvage_status` must no longer be `NONE`,
    because a total loss cannot be paid until the wreck has been dealt with; an
    attempt is refused with `ERR_SALVAGE_DISPOSITION_REQUIRED`."

    Design: Corner/validations/corner_settlement_basis_check_gates_the_salvage_check
    """
    book = _reserved_claim_without_evidence(api)
    agreed_value = book["schedule"]["agreed_value_cents"]
    _append_total_loss_survey(api, book)

    disposed = fx.dispose_salvage(api, book["claim_id"], SalvageAction.RETAIN)
    assert disposed["salvage_status"] == SalvageStatus.RETAINED_BY_INSURED
    assert disposed["adjustment_status"] == AdjustmentStatus.RESERVED

    settled = validate_unpaginated(
        _attempt_agreed_value_settlement(api, book["claim_id"])
    )
    expected_deductible = c.deductible_cents(
        agreed_value, SETTLEMENT_HULL_DEDUCTIBLE_PPM
    )
    assert settled["adjustment_status"] == AdjustmentStatus.SETTLED
    assert settled["settlement_basis"] == SettlementBasis.AGREED_VALUE
    assert settled["deductible_applied_cents"] == expected_deductible
    assert settled["settlement_amount_cents"] == agreed_value - expected_deductible
    assert settled["reserve_cents"] == 0

    schedule = fx.fetch_schedule(api, book["schedule_id"])
    assert schedule["coverage_status"] == CoverageStatus.TOTAL_LOSS_SETTLED

    policy = fx.fetch_policy(api, book["policy_id"])
    assert policy["outstanding_reserve_cents"] == 0
    assert policy["paid_hull_cents"] == agreed_value - expected_deductible
