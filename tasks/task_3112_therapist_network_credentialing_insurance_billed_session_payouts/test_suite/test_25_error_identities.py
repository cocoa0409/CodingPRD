"""The error identities reached through ordinary domain flows."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EARLY,
    CLOCK_ONBOARD,
    add_signed_note,
    api_client,
    attach_billable_clinician,
    complete_session,
    get_clinician,
    get_patient,
    get_session,
    make_clinician,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    open_and_lock_batch,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_clinician_headers

OPS = TEST_USERS["ops_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_the_third_resubmission_is_refused_on_the_counter_rather_than_the_clock():
    """PRD §3.5: "a claim that has already used both attempts is refused with
    `ERR_RESUBMISSION_LIMIT_REACHED`."
    PRD §3.5: "Resubmitting a denied claim is permitted only while the logical
    clock is strictly before `recovery_deadline` and only while
    `resubmission_count` is at most 1"

    Design: Corner/errors/enforcing_the_resubmission_cap_returns_resubmission_limit_reached
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = validate_success(api_client.create_claim({"session_id": session["id"]}, OPS), 201)

    claim = validate_success(
        api_client.adjudicate_claim(claim["id"], {"outcome": "DENIED", "denial_code": "MISSING_DOCUMENTATION"}, OPS)
    )
    validate_success(api_client.resubmit_claim(claim["id"], OPS))
    validate_success(api_client.decide_reprocessing(claim["id"], {"outcome": "ACCEPTED"}, OPS))
    claim = validate_success(
        api_client.adjudicate_claim(claim["id"], {"outcome": "DENIED", "denial_code": "MISSING_DOCUMENTATION"}, OPS)
    )
    validate_success(api_client.resubmit_claim(claim["id"], OPS))
    claim = validate_success(api_client.decide_reprocessing(claim["id"], {"outcome": "REJECTED"}, OPS))
    assert claim["resubmission_count"] == 2
    assert claim["denial_code"] == "DUPLICATE"

    third = api_client.resubmit_claim(claim["id"], OPS)
    error = validate_error(third, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED)
    assert third.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_TIMELY_FILING_EXPIRED.value
    assert validate_success(api_client.get_claim(claim["id"], OPS))["resubmission_count"] == 2


def test_a_note_whose_documented_length_trails_the_scheduled_hour_blocks_delivery():
    """PRD §3.4: "Every note on the session, not merely the newest, must have a
    `duration_minutes` equal to the session's scheduled length in minutes; a
    mismatch is `ERR_DURATION_MISMATCH`, and a session with no signed note at all
    is `ERR_DOCUMENTATION_MISSING`."
    PRD §3.4: "only when the `diagnosis_code` is present, the `narrative` is
    non-empty, and `duration_minutes` falls between 45 and 120 minutes inclusive"

    Design: Corner/errors/completing_a_session_with_a_mismatched_note_duration_returns_duration_mismatch
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"], duration_minutes=50)
    set_clock("2026-06-03T18:00:00Z")

    response = api_client.complete_session(session["id"], make_clinician_headers(clinician["id"]))
    error = validate_error(response, ApiErrorId.ERR_DURATION_MISMATCH)
    assert response.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_DOCUMENTATION_MISSING.value

    notes = api_client.list_session_notes(session["id"], OPS).json()["data"]
    assert notes[0]["duration_minutes"] == 50
    assert notes[0]["status"] == "SIGNED", (
        "the signing range check passed while the match check did not"
    )
    row = get_session(session["id"])
    assert row["status"] == "SCHEDULED"
    assert row["billing_state"] == "UNBILLED"


def test_a_patient_without_a_verified_snapshot_cannot_have_a_session_scheduled():
    """PRD §3.3: "A patient whose `benefit_status` is not `VERIFIED` cannot have
    a session scheduled; the attempt is refused with `ERR_BENEFIT_UNVERIFIED`."

    Design: Corner/errors/scheduling_an_unverified_patient_returns_benefit_unverified
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    # A verified patient is on file as the control; the subject below has no
    # snapshot at all.
    make_verified_patient(payer["id"])
    # A fresh patient with no snapshot at all, sharing the clinician's payer.
    bare = validate_success(
        api_client.create_patient(
            {
                "full_name": "Jordan Pike",
                "member_id": "MBR-7002",
                "payer_id": payer["id"],
                "plan_code": "PPO-1500",
                "state_code": "CA",
                "deductible_cents": 100_000,
                "coinsurance_rate": 0.20,
                "oop_max_cents": 200_000,
            },
            OPS,
        ),
        201,
    )
    session = api_client.create_session(
        {
            "clinician_id": clinician["id"],
            "patient_id": bare["id"],
            "scheduled_start": "2026-06-03T16:00:00Z",
            "scheduled_end": "2026-06-03T17:00:00Z",
            "cpt_code": "90837",
            "modality": "VIDEO",
        },
        OPS,
    ).json()["data"]

    response = api_client.schedule_session(session["id"], make_clinician_headers(clinician["id"]))
    error = validate_error(response, ApiErrorId.ERR_BENEFIT_UNVERIFIED)
    assert response.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_CLINICIAN_NOT_BILLABLE.value

    assert get_patient(bare["id"])["benefit_status"] == "UNVERIFIED"
    assert api_client.list_verifications(bare["id"], OPS).json()["data"] == []
    row = get_session(session["id"])
    assert row["status"] == "REQUESTED"
    assert row["quoted_cost_share_cents"] is None


def test_a_match_with_no_eligible_candidate_is_refused_without_writing_a_match():
    """PRD §3.7: "An empty candidate set is rejected with
    `ERR_NO_ELIGIBLE_CLINICIAN` at HTTP 422 and no match is written."

    Design: Corner/errors/matching_a_patient_with_no_eligible_clinician_returns_no_eligible_clinician
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(
        payer["id"], full_name="Rafael Duarte",
        specialty_tags=["TRAUMA"],
        availability_blocks=[{"weekday": 5, "start_minute": 480, "end_minute": 1080}],
    )["clinician"]
    patient = make_verified_patient(payer["id"])

    disjoint = api_client.match_patient(patient["id"], {"specialty_tags": ["GRIEF"]}, OPS)
    error = validate_error(disjoint, ApiErrorId.ERR_NO_ELIGIBLE_CLINICIAN)
    assert disjoint.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_MATCH_TIE_UNRESOLVABLE.value
    assert get_patient(patient["id"])["matched_clinician_id"] is None
    assert get_clinician(clinician["id"])["active_patient_count"] == 0

    matched = validate_success(
        api_client.match_patient(patient["id"], {"specialty_tags": ["TRAUMA"]}, OPS)
    )
    assert matched["matched_clinician_id"] == clinician["id"]
    assert get_clinician(clinician["id"])["active_patient_count"] == 1


def test_paying_a_batch_that_never_locked_is_refused_with_the_payable_identity():
    """PRD §3.6: "a batch in any status other than `LOCKED`, or one carrying a
    line in some other status, is refused with `ERR_BATCH_NOT_PAYABLE`."

    Design: Corner/errors/paying_an_open_batch_returns_batch_not_payable
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    complete_session(clinician["id"], session["id"])

    set_clock("2026-06-09T00:00:00Z")
    populated = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY")
    populated = validate_success(api_client.pay_payout_batch(populated["id"], OPS))
    assert populated["status"] == "PAID"

    lines = api_client.list_payout_batch_lines(populated["id"], OPS).json()["data"]
    assert lines[0]["line_status"] == "PAID"
    assert lines[0]["net_cents"] == 15_000

    empty = validate_success(
        api_client.create_payout_batch(
            {
                "period_start": "2026-06-08T00:00:00Z",
                "period_end": "2026-06-15T00:00:00Z",
                "schedule": "WEEKLY",
            },
            OPS,
        ),
        201,
    )
    empty_lock = api_client.lock_payout_batch(empty["id"], OPS)
    validate_error(empty_lock, ApiErrorId.ERR_BATCH_NOT_LOCKABLE)

    empty_lines, meta = validate_paginated(
        api_client.list_payout_batch_lines(empty["id"], OPS, {"limit": 10, "offset": 0})
    )
    assert empty_lines == [] and meta["total_count"] == 0
    assert validate_success(api_client.get_payout_batch(empty["id"], OPS))["status"] == "OPEN"

    response = api_client.pay_payout_batch(empty["id"], OPS)
    validate_error(response, ApiErrorId.ERR_BATCH_NOT_PAYABLE)
    assert response.status_code == 409
    assert get_clinician(clinician["id"])["payout_balance_cents"] == 15_000, (
        "only the populated batch moved the balance"
    )


def test_a_successor_assignment_past_the_extended_deadline_is_refused():
    """PRD §3.7: "Requested at or after the extended deadline for a declined or
    escalated plan, the attempt is refused with
    `ERR_CONTINUITY_DEADLINE_PASSED`."
    PRD §3.7: "this is permitted while the logical clock is strictly before
    `reassignment_deadline` from `DECLINED`, and while the clock is strictly
    before `reassignment_deadline` plus 7 days from `ESCALATED`"

    Design: Corner/errors/continuity_successor_assignment_past_the_extension_returns_deadline_passed
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    clinician = make_clinician()
    departing = make_clinician(
        full_name="Nadia Okonkwo", license_type="LMFT",
        availability_blocks=[{"weekday": 4, "start_minute": 480, "end_minute": 1080}],
    )
    patient = make_verified_patient(payer["id"])

    plan = validate_success(
        api_client.create_continuity_plan(
            {"clinician_id": departing["id"], "patient_id": patient["id"],
             "reason": "OFFBOARDING", "successor_clinician_id": clinician["id"]},
            OPS,
        ), 201
    )
    declined = validate_success(
        api_client.decline_continuity_plan(plan["id"], make_clinician_headers(clinician["id"]))
    )
    assert declined["reassignment_deadline"] == "2026-02-04T00:00:00Z", (
        "the plan opened at 2026-01-05 with no recorded offboarding, so the "
        "clock plus the 30-day grace window is the deadline"
    )

    set_clock("2026-02-12T00:00:00Z")
    escalated = validate_success(api_client.get_continuity_plan(plan["id"], OPS))
    assert escalated["status"] == "ESCALATED"

    response = api_client.assign_continuity_successor(
        plan["id"],
        {"successor_clinician_id": clinician["id"], "expected_plan_version": declined["version"]},
        OPS,
    )
    validate_error(response, ApiErrorId.ERR_CONTINUITY_DEADLINE_PASSED)
    assert response.status_code == 409
    row = validate_success(api_client.get_continuity_plan(plan["id"], OPS))
    assert row["status"] == "ESCALATED"
    assert row["successor_clinician_id"] == clinician["id"]
    assert get_patient(patient["id"])["swap_requested"] is True