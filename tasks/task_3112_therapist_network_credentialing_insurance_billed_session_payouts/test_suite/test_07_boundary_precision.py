"""Threshold boundaries where adjacent operations disagree at the same instant."""
from test_helpers import (
    ApiErrorId,
    CLOCK_ONBOARD,
    add_signed_note,
    api_client,
    attach_billable_clinician,
    complete_session,
    get_clinician,
    get_patient,
    get_session,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    set_clock,
    submit_claim,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_clinician_headers

OPS = TEST_USERS["ops_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
DEADLINE = "2026-09-14T16:00:00Z"


def _denied_claim_at_deadline_scenario() -> dict:
    """A claim submitted at 2026-06-16T16:00:00Z under a payer with a 90-day
    timely-filing window, so its recovery deadline is 2026-09-14T16:00:00Z."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer(timely_filing_days=90)
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-16T14:00:00Z", "2026-06-16T15:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-16T16:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])
    claim = validate_success(
        api_client.adjudicate_claim(claim["id"], {"outcome": "DENIED", "denial_code": "NOT_COVERED"}, OPS)
    )
    set_clock("2026-09-14T15:59:59Z")
    return {"payer": payer, "clinician": clinician, "patient": patient,
            "session": session, "claim": claim}


def test_resubmission_one_second_before_the_deadline_is_accepted():
    """PRD §3.5: "Resubmitting a denied claim is permitted only while the logical
    clock is strictly before `recovery_deadline` and only while
    `resubmission_count` is at most 1"
    PRD §3.5: "An accepted resubmission clears the `denial_code` to null,
    increments `resubmission_count` by 1, and passes the claim through an
    intermediate `REPROCESSING` state before it returns to `SUBMITTED`"

    Design: Difficulty/boundary_precision_check/resubmission_rejected_at_the_recovery_deadline_exactly_while_write_off_is_allowed
    """
    scenario = _denied_claim_at_deadline_scenario()
    claim_id = scenario["claim"]["id"]

    assert scenario["claim"]["recovery_deadline"] == DEADLINE, (
        "the deadline is the submission instant plus the payer's timely-filing days"
    )
    accepted = validate_success(api_client.resubmit_claim(claim_id, OPS))
    assert accepted["claim_status"] == "REPROCESSING"
    assert accepted["resubmission_count"] == 1
    assert accepted["denial_code"] is None


def test_resubmission_exactly_at_the_deadline_is_refused_while_write_off_at_the_same_instant_succeeds():
    """PRD §3.5: "At the deadline instant itself resubmission is refused with
    `ERR_TIMELY_FILING_EXPIRED`"
    PRD §3.5: "Writing a claim off, finally, is permitted when the logical clock
    is at or after `recovery_deadline` or when `resubmission_count` has reached 2
    regardless of the clock"
    PRD §3.5: "The deadline boundary therefore carries opposite senses in its two
    readings: at exactly `recovery_deadline`, resubmission is rejected and
    write-off is permitted."

    Design: Difficulty/boundary_precision_check/resubmission_rejected_at_the_recovery_deadline_exactly_while_write_off_is_allowed
    """
    scenario = _denied_claim_at_deadline_scenario()
    claim_id = scenario["claim"]["id"]

    set_clock(DEADLINE)
    rejected = api_client.resubmit_claim(claim_id, OPS)
    validate_error(rejected, ApiErrorId.ERR_TIMELY_FILING_EXPIRED)
    assert rejected.status_code == 422

    written_off = validate_success(api_client.write_off_claim(claim_id, OPS))
    assert written_off["claim_status"] == "WRITTEN_OFF"
    assert written_off["resubmission_count"] == 0, (
        "the refused resubmission never incremented the counter"
    )
    assert get_session(scenario["session"]["id"])["billing_state"] == "WRITTEN_OFF"


def test_continuity_acceptance_at_the_caseload_target_is_refused_with_caseload_full():
    """PRD §3.7: "Acceptance of a new patient is allowed only while
    `active_patient_count` is strictly less than the target."
    PRD §3.7: "Attempting to push a clinician to or past their target through
    continuity acceptance or through a match is refused with `ERR_CASELOAD_FULL`
    at HTTP 409."

    Design: Difficulty/boundary_precision_check/caseload_acceptance_uses_strict_inequality_while_waitlist_utilization_is_inclusive
    """
    scenario = _at_target_scenario()
    full_id = scenario["full"]["id"]
    assert scenario["full"]["active_patient_count"] == scenario["full"]["weekly_caseload_target"] == 2

    headers = make_clinician_headers(full_id)
    rejected = api_client.accept_continuity_plan(scenario["plan_full"]["id"], headers)
    validate_error(rejected, ApiErrorId.ERR_CASELOAD_FULL)
    assert rejected.status_code == 409
    assert get_clinician(full_id)["active_patient_count"] == 2, (
        "the rejected acceptance wrote nothing"
    )


def test_acceptance_one_patient_below_the_target_succeeds_and_transfers_the_match():
    """PRD §3.7: "Utilization is the floor of one hundred times the clinician's
    `active_patient_count` divided by the `weekly_caseload_target`."
    PRD §3.7: "Waitlist eligibility begins once utilization reaches 90 hundredths
    or more, inclusively. The senses are opposite on the same numbers: at a
    patient count exactly equal to the target, acceptance is not allowed while
    waitlist eligibility is true."

    Design: Difficulty/boundary_precision_check/caseload_acceptance_uses_strict_inequality_while_waitlist_utilization_is_inclusive
    """
    scenario = _at_target_scenario()
    full = scenario["full"]
    roomy_id = scenario["roomy"]["id"]
    assert full["active_patient_count"] == full["weekly_caseload_target"] == 2
    assert (100 * full["active_patient_count"]) // full["weekly_caseload_target"] >= 90, (
        "the inclusive waitlist rule fires at exactly this utilization"
    )

    accepted = validate_success(
        api_client.accept_continuity_plan(
            scenario["plan_roomy"]["id"], make_clinician_headers(roomy_id)
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert get_patient(scenario["pat_c"]["id"])["matched_clinician_id"] == roomy_id
    assert get_clinician(roomy_id)["active_patient_count"] == 1


def _at_target_scenario() -> dict:
    """Dana exactly at a target of 2 with two matched patients, and Zara with a
    target of 2 who currently carries none.

    The setup shapes the candidate pool instead of relying on selector tie-breaks:
    while Priya and Marcus are matched, Zara is tagged for a specialty neither
    requests, so she is not a candidate. Only once the two plans are in place is
    Zara's tag widened, and by then the two earlier matches have already landed.
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    dana = attach_billable_clinician(
        payer["id"], full_name="Dana Reyes", weekly_caseload_target=2,
        license_number="LCSW-CA-77120",
    )["clinician"]
    zara = attach_billable_clinician(
        payer["id"], full_name="Zara Whitfield", weekly_caseload_target=2,
        specialty_tags=["GRIEF"],
        license_number="LCSW-CA-90211",
        availability_blocks=[{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
    )["clinician"]

    pat_a = make_verified_patient(payer["id"], full_name="Priya Anand", member_id="MBR-4410")
    pat_b = make_verified_patient(
        payer["id"], full_name="Marcus Cole", member_id="MBR-5182",
        verification={"deductible_remaining_cents": 40_000},
    )
    pat_c = make_verified_patient(
        payer["id"], full_name="Elena Vargas", member_id="MBR-6031",
        verification={"deductible_remaining_cents": 20_000},
    )
    for patient in (pat_a, pat_b):
        matched = validate_success(
            api_client.match_patient(patient["id"], {"specialty_tags": ["ANXIETY"]}, OPS)
        )
        assert matched["matched_clinician_id"] == dana["id"], (
            "Dana is the only eligible candidate while Zara is tagged for GRIEF"
        )

    departing = api_client.create_clinician(
        {
            "full_name": "Nadia Okonkwo",
            "license_type": "LMFT",
            "primary_state": "CA",
            "specialty_tags": ["ANXIETY"],
            "weekly_caseload_target": 8,
            "availability_blocks": [{"weekday": 4, "start_minute": 480, "end_minute": 1080}],
        },
        OPS,
    ).json()["data"]
    plan_full = validate_success(
        api_client.create_continuity_plan(
            {"clinician_id": departing["id"], "patient_id": pat_c["id"],
             "reason": "OFFBOARDING", "successor_clinician_id": dana["id"]},
            OPS,
        ), 201
    )
    plan_roomy = validate_success(
        api_client.create_continuity_plan(
            {"clinician_id": departing["id"], "patient_id": pat_c["id"],
             "reason": "CLINICAL_CONFLICT", "successor_clinician_id": zara["id"]},
            OPS,
        ), 201
    )
    return {
        "full": get_clinician(dana["id"]),
        "roomy": get_clinician(zara["id"]),
        "departing": departing,
        "pat_c": pat_c,
        "plan_full": plan_full,
        "plan_roomy": plan_roomy,
    }