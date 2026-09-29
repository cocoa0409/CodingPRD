"""Gates at the door of a booking: the clock, the surveillance file and a credential.

Each scenario fires exactly one gate while holding every other precondition valid, and
then proves the refusal wrote nothing at all by re-reading the rows an accepted call
would have moved.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

ACCESS_PLACED_ON = "2026-03-01"
SIBLING_PLACED_ON = "2026-03-10"
PAST_SLOT_START = "2026-07-31T13:00:00Z"
PAST_SLOT_END = "2026-07-31T14:00:00Z"
LATE_SLOT_START = "2026-08-02T13:00:00Z"
LATE_SLOT_END = "2026-08-02T14:00:00Z"
CRITICAL_READING_AT = "2026-07-25T08:00:00Z"
BENIGN_READING_AT = "2026-07-30T09:00:00Z"
LAPSED_CREDENTIAL_ON = "2026-07-01"


def test_01_a_slot_that_has_already_passed_is_refused_and_the_referral_keeps_its_version(api):
    """The room is free, the operator is right, and the date is yesterday.

    The PRD states: "A booking whose `scheduled_start` is earlier than the clock is
    refused with `ERR_SCHEDULE_IN_PAST`."

    The referral is `ROUTINE`, so the urgency window that follows this gate cannot be
    what fired: the PRD states "A `ROUTINE` referral carries no date constraint."

    Nothing was consumed by the refusal, which the identical payload proves by booking a
    future slot against the very same declared referral version. The PRD states: "As a
    system side effect in the same request the parent referral advances
    `TRIAGED → SCHEDULED`, which increments its `version`."

    Design: Corner/validations/booking_a_slot_before_the_clock_is_rejected
    """
    center = fx.seed_center(api)
    triaged = fx.seed_triaged_referral(api, center)
    referral = triaged["referral"]
    assert referral["status"] == "TRIAGED"
    assert referral["urgency"] == "ROUTINE"

    refused = api.create_procedure(
        {
            "referral_id": referral["id"],
            "room_id": center["room_id"],
            "primary_operator_id": center["operator_id"],
            "procedure_type": "ANGIOPLASTY",
            "sedation_level": "NONE",
            "scheduled_start": PAST_SLOT_START,
            "scheduled_end": PAST_SLOT_END,
            "expected_referral_version": referral["version"],
        },
        fx.COORDINATOR,
    )
    validate_error(refused, "ERR_SCHEDULE_IN_PAST", 422)

    unchanged = fx.read_referral(api, referral["id"])
    assertions.assert_referral(unchanged)
    assert unchanged["status"] == "TRIAGED"
    assert unchanged["version"] == referral["version"]

    stranded, empty_meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"referral_id": referral["id"]})
    )
    assert stranded == []
    assert empty_meta["total_count"] == 0

    booked = fx.book_case(
        api,
        referral["id"],
        center["room_id"],
        center["operator_id"],
        referral["version"],
    )
    assert booked["clinical_status"] == "SCHEDULED"

    rebooked = fx.read_referral(api, referral["id"])
    assert rebooked["status"] == "SCHEDULED"
    assert rebooked["version"] == referral["version"] + 1

    procedures, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"referral_id": referral["id"]})
    )
    assert meta["total_count"] == 1
    assert [procedure["id"] for procedure in procedures] == [booked["id"]]


def _referral_on_an_access_with_an_empty_surveillance_file(api):
    """A perfectly ordinary stenosis referral whose access carries no readings at all.

    The referring facility is newly registered, so its contract posture is ACTIVE and the
    posture gate that shares this operation cannot be what refuses the triage.
    """
    center = fx.seed_center(api)
    access = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVG",
        laterality="LEFT",
        site="FOREARM",
        placed_on=ACCESS_PLACED_ON,
    )
    referral = fx.seed_referral(
        api,
        access["id"],
        center["facility_id"],
        suspected_problem="STENOSIS",
        clinical_narrative="prolonged bleeding reported, no flow surveillance on file yet",
        missed_treatment_count=0,
    )
    assert referral["status"] == "SUBMITTED"
    assert fx.read_facility(api, center["facility_id"])["contract_status"] == "ACTIVE"
    return center, access, referral


def test_02_a_triage_with_nothing_to_score_is_refused_and_writes_no_triage_fields(api):
    """There is no reading to score, so there is no score, no variant and no urgency.

    The PRD states: "At least one surveillance reading must exist on the referral's
    access with a `reading_at` at or before the clock, otherwise
    `ERR_INSUFFICIENT_SURVEILLANCE`".

    The refusal is total rather than partial: the referral is still `SUBMITTED` at its
    original version with every triage field null, and the mechanical-failure consequence
    of a successful triage has not fired either, so the access is still `IN_USE`.

    Design: Corner/validations/triage_without_any_surveillance_reading_is_rejected
    """
    _center, access, referral = _referral_on_an_access_with_an_empty_surveillance_file(api)

    refused = api.triage_referral(referral["id"], fx.COORDINATOR)
    validate_error(refused, "ERR_INSUFFICIENT_SURVEILLANCE", 422)

    unchanged = fx.read_referral(api, referral["id"])
    assertions.assert_referral(unchanged)
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["version"] == referral["version"]
    assert unchanged["triage_score"] is None
    assert unchanged["triage_variant"] is None
    assert unchanged["urgency"] is None
    assert unchanged["triaged_at"] is None

    assert fx.read_access(api, access["id"])["status"] == "IN_USE"


def test_03_one_reading_is_enough_and_the_identical_call_then_scores_it(api):
    """The same request, one reading later, is the absolute-based variant scoring zero.

    The PRD states: "When exactly one reading qualifies, `triage_variant` is
    `ABSOLUTE_BASED`."

    It also states: "`urgency` is then banded off the score: `SAME_DAY` when
    `triage_score` is 70 or above, otherwise `NEXT_DAY` when it is 45 or above, otherwise
    `ROUTINE`."

    A flow of 900 earns nothing from either absolute band, a venous pressure of 100 and a
    recirculation of 2.0 are both below their thresholds and the missed-treatment burden
    is zero, so the score is 0 and the urgency `ROUTINE`. The consequence the refused call
    withheld now fires: the PRD states "and the referral's access is currently `IN_USE`,
    that access is moved `IN_USE → DYSFUNCTIONAL`."

    Design: Corner/validations/triage_without_any_surveillance_reading_is_rejected
    """
    center, access, referral = _referral_on_an_access_with_an_empty_surveillance_file(api)
    validate_error(
        api.triage_referral(referral["id"], fx.COORDINATOR),
        "ERR_INSUFFICIENT_SURVEILLANCE",
        422,
    )

    reading = fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        reading_at=BENIGN_READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="ROUTINE",
    )
    assertions.assert_surveillance_reading(reading)

    triaged = validate_success(api.triage_referral(referral["id"], fx.COORDINATOR))
    assert triaged["status"] == "TRIAGED"
    assert triaged["triage_variant"] == "ABSOLUTE_BASED"
    assert triaged["triage_score"] == 0
    assert triaged["urgency"] == "ROUTINE"
    assertions.assert_instant_equals(
        triaged["triaged_at"], fx.CLOCK_STARTUP_UTC, "triaged_at"
    )

    assert fx.read_access(api, access["id"])["status"] == "DYSFUNCTIONAL"


def _a_same_day_referral_beside_a_routine_one(api):
    """Two triaged referrals on one patient, banded at opposite ends of the urgency scale.

    The critical access carries a single reading of 500 ml/min with a venous pressure of
    160 and a recirculation of 12.0 and one missed treatment, which is 40 + 15 + 10 + 6;
    the sibling access carries a benign single reading and no missed treatments.
    """
    center = fx.seed_center(api)
    critical_access = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVG",
        laterality="LEFT",
        site="FOREARM",
        placed_on=ACCESS_PLACED_ON,
    )
    fx.seed_reading(
        api,
        critical_access["id"],
        center["facility_id"],
        reading_at=CRITICAL_READING_AT,
        access_flow_ml_min=500,
        venous_pressure_mmhg=160,
        recirculation_pct=12.0,
        kind="URGENT",
    )
    critical = fx.triage(
        api,
        fx.seed_referral(
            api,
            critical_access["id"],
            center["facility_id"],
            suspected_problem="STENOSIS",
            clinical_narrative="flows collapsing with a missed treatment already lost",
            missed_treatment_count=1,
        )["id"],
    )
    assert critical["triage_variant"] == "ABSOLUTE_BASED"
    assert critical["triage_score"] == 71
    assert critical["urgency"] == "SAME_DAY"
    assertions.assert_instant_equals(
        critical["triaged_at"], fx.CLOCK_STARTUP_UTC, "triaged_at"
    )

    routine_access = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVF",
        laterality="RIGHT",
        site="UPPER_ARM",
        placed_on=SIBLING_PLACED_ON,
    )
    fx.seed_reading(
        api,
        routine_access["id"],
        center["facility_id"],
        reading_at=CRITICAL_READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="ROUTINE",
    )
    routine = fx.triage(
        api,
        fx.seed_referral(
            api,
            routine_access["id"],
            center["facility_id"],
            suspected_problem="STENOSIS",
            clinical_narrative="mild pressures, elective review requested",
            missed_treatment_count=0,
        )["id"],
    )
    assert routine["triage_score"] == 0
    assert routine["urgency"] == "ROUTINE"
    return center, critical, routine


def test_04_a_same_day_promise_cannot_be_kept_on_the_following_day(api):
    """The slot is bookable; it is the urgency that forbids that date.

    The PRD states: "when the referral's `urgency` is `SAME_DAY`, the calendar date of
    `scheduled_start` must equal the calendar date of the referral's `triaged_at`".

    It also states: "A violation of either is refused with `ERR_SAME_DAY_WINDOW_MISSED`."

    The control proves the refusal is a property of the referral rather than of the room
    or the date: the identical 2026-08-02 slot in the identical room with the identical
    operator is accepted for the `ROUTINE` referral, which the PRD exempts because "A
    `ROUTINE` referral carries no date constraint."

    Design: Corner/validations/same_day_urgency_must_be_booked_on_the_triage_date_and_routine_is_unconstrained
    """
    center, critical, routine = _a_same_day_referral_beside_a_routine_one(api)

    refused = api.create_procedure(
        {
            "referral_id": critical["id"],
            "room_id": center["room_id"],
            "primary_operator_id": center["operator_id"],
            "procedure_type": "ANGIOPLASTY",
            "sedation_level": "NONE",
            "scheduled_start": LATE_SLOT_START,
            "scheduled_end": LATE_SLOT_END,
            "expected_referral_version": critical["version"],
        },
        fx.COORDINATOR,
    )
    validate_error(refused, "ERR_SAME_DAY_WINDOW_MISSED", 422)

    unchanged = fx.read_referral(api, critical["id"])
    assert unchanged["status"] == "TRIAGED"
    assert unchanged["version"] == critical["version"]
    assert unchanged["urgency"] == "SAME_DAY"

    empty, empty_meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"referral_id": critical["id"]})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0

    elective = fx.book_case(
        api,
        routine["id"],
        center["room_id"],
        center["operator_id"],
        routine["version"],
        LATE_SLOT_START,
        LATE_SLOT_END,
    )
    assert elective["clinical_status"] == "SCHEDULED"
    assert fx.read_referral(api, routine["id"])["status"] == "SCHEDULED"


def test_05_the_refused_booking_left_the_version_intact_for_the_lawful_date(api):
    """One calendar day earlier, the same declared version and the same room succeed.

    The PRD states: "`triaged_at` is set to the clock, and the calendar date of
    `triaged_at` becomes the anchor of the scheduling window enforced in §3.5."

    The booking that follows the refusal declares the very version the refused call
    declared, which is only possible because a refused booking bumps nothing.

    Design: Corner/validations/same_day_urgency_must_be_booked_on_the_triage_date_and_routine_is_unconstrained
    """
    center, critical, _routine = _a_same_day_referral_beside_a_routine_one(api)
    validate_error(
        api.create_procedure(
            {
                "referral_id": critical["id"],
                "room_id": center["room_id"],
                "primary_operator_id": center["operator_id"],
                "procedure_type": "ANGIOPLASTY",
                "sedation_level": "NONE",
                "scheduled_start": LATE_SLOT_START,
                "scheduled_end": LATE_SLOT_END,
                "expected_referral_version": critical["version"],
            },
            fx.COORDINATOR,
        ),
        "ERR_SAME_DAY_WINDOW_MISSED",
        422,
    )

    booked = fx.book_case(
        api,
        critical["id"],
        center["room_id"],
        center["operator_id"],
        critical["version"],
    )
    assert booked["clinical_status"] == "SCHEDULED"
    assert booked["coding_status"] == "UNCODED"
    assertions.assert_procedure(booked)

    scheduled = fx.read_referral(api, critical["id"])
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["version"] == critical["version"] + 1

    procedures, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"referral_id": critical["id"]})
    )
    assert meta["total_count"] == 1
    assert [procedure["id"] for procedure in procedures] == [booked["id"]]


def _a_nurse_whose_credential_lapsed_in_july(api):
    """A sedation nurse credentialed on paper but expired a month before the clock."""
    center = fx.seed_center(api)
    lapsed = fx.seed_sedation_rn(
        api,
        moderate_sedation_credentialed=True,
        credential_expires_on=LAPSED_CREDENTIAL_ON,
        max_concurrent_sedation_cases=2,
    )
    assertions.assert_clinician(lapsed)
    assert lapsed["clinician_role"] == "SEDATION_RN"
    assert lapsed["moderate_sedation_credentialed"] is True
    assert lapsed["credential_expires_on"] == LAPSED_CREDENTIAL_ON

    triaged = fx.seed_triaged_referral(api, center)
    assert triaged["referral"]["urgency"] == "ROUTINE"
    return center, lapsed, triaged["referral"]


def test_06_an_unsedated_case_accepts_the_nurse_whose_credential_has_lapsed(api):
    """Priority ten never runs, because this case is not a sedation case.

    The PRD states: "`sedation_rn_id` is **required** when `sedation_level` is `MODERATE`
    and **ignored** when it is `NONE`."

    So the booking is accepted with the lapsed nurse named in the request, and the case
    starts from the zeroes the PRD declares: "`clinical_status` is `SCHEDULED`,
    `coding_status` is `UNCODED`, `allowed_amount_cents`, `billed_amount_cents`,
    `denied_amount_cents`, `net_receivable_cents` and `rebill_count` are all 0".

    Design: Corner/validations/expired_sedation_credential_only_blocks_moderate_cases
    """
    center, lapsed, referral = _a_nurse_whose_credential_lapsed_in_july(api)

    booked = fx.book_case(
        api,
        referral["id"],
        center["room_id"],
        center["operator_id"],
        referral["version"],
        sedation_level="NONE",
        sedation_rn_id=lapsed["id"],
    )
    assertions.assert_procedure(booked)
    assert booked["clinical_status"] == "SCHEDULED"
    assert booked["sedation_level"] == "NONE"
    assert booked["coding_status"] == "UNCODED"
    assert booked["allowed_amount_cents"] == 0
    assert booked["billed_amount_cents"] == 0
    assert booked["denied_amount_cents"] == 0
    assert booked["net_receivable_cents"] == 0
    assert booked["rebill_count"] == 0
    assert booked["sedation_end_at"] is None

    assert fx.read_referral(api, referral["id"])["status"] == "SCHEDULED"


def test_07_the_same_nurse_in_the_same_slot_is_refused_once_the_case_is_sedated(api):
    """Only the sedation level changes between the accepted booking and the refused one.

    The PRD states: "For a `MODERATE` case the sedation nurse must additionally hold
    `moderate_sedation_credentialed` as `true` and a `credential_expires_on` falling on or
    after the clock's current calendar date, otherwise
    `ERR_SEDATION_CREDENTIAL_INVALID`."

    The slot is genuinely free for the second attempt, because the PRD states "On this
    explicitly requested cancellation the parent referral reverts `SCHEDULED → TRIAGED` so
    that the case can be rebooked" and, of the cancelled case it leaves behind, that
    "aborted and cancelled cases are excluded from the count and therefore free capacity
    back up."

    Design: Corner/validations/expired_sedation_credential_only_blocks_moderate_cases
    """
    center, lapsed, referral = _a_nurse_whose_credential_lapsed_in_july(api)
    unsedated = fx.book_case(
        api,
        referral["id"],
        center["room_id"],
        center["operator_id"],
        referral["version"],
        sedation_level="NONE",
        sedation_rn_id=lapsed["id"],
    )

    cancelled = fx.cancel_case(
        api, unsedated["id"], cancel_note="reopening the slot as a sedation case"
    )
    assert cancelled["clinical_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "COORDINATOR_CANCEL"

    freed = fx.read_referral(api, referral["id"])
    assert freed["status"] == "TRIAGED"

    refused = api.create_procedure(
        {
            "referral_id": referral["id"],
            "room_id": center["room_id"],
            "primary_operator_id": center["operator_id"],
            "sedation_rn_id": lapsed["id"],
            "procedure_type": "ANGIOPLASTY",
            "sedation_level": "MODERATE",
            "scheduled_start": fx.DEFAULT_SLOT_START,
            "scheduled_end": fx.DEFAULT_SLOT_END,
            "expected_referral_version": freed["version"],
        },
        fx.COORDINATOR,
    )
    validate_error(refused, "ERR_SEDATION_CREDENTIAL_INVALID", 422)

    unchanged = fx.read_referral(api, referral["id"])
    assert unchanged["status"] == "TRIAGED"
    assert unchanged["version"] == freed["version"]

    procedures, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"referral_id": referral["id"]})
    )
    assert meta["total_count"] == 1
    assert [procedure["id"] for procedure in procedures] == [unsedated["id"]]
    assert procedures[0]["clinical_status"] == "CANCELLED"
