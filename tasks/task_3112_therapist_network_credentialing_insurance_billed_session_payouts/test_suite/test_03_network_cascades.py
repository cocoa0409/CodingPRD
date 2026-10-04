"""Network-wide cascades: a payer suspension propagating three hops into
session cancellation, and an offboarding request synthesising continuity plans
that a later session completion escalates."""
from test_helpers import (
    CLOCK_DELIVERY,
    CLOCK_ONBOARD,
    add_signed_note,
    api_client,
    attach_billable_clinician,
    complete_session,
    get_clinician,
    get_enrollment,
    get_patient,
    get_session,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    set_clock,
    setup_clinician_matched_to_two_patients,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_clinician_headers

OPS = TEST_USERS["ops_admin_headers"]
CLINICIAN_ROLE = "Clinician"


def _suspend_payer_scenario() -> dict:
    """A clinician whose only enrollment is with payer SOLO, holding two
    SCHEDULED sessions and one COMPLETED session. One 600-minute availability
    block, three 60-minute sessions."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer(payer_code="SOLO", payer_name="Solo Practice Assurance")
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])
    set_clock(CLOCK_DELIVERY)

    s1 = make_scheduled_session(clinician["id"], patient["id"], "2026-06-23T14:00:00Z", "2026-06-23T15:00:00Z")
    s2 = make_scheduled_session(clinician["id"], patient["id"], "2026-06-30T14:00:00Z", "2026-06-30T15:00:00Z")
    s3 = make_scheduled_session(clinician["id"], patient["id"], "2026-06-16T14:00:00Z", "2026-06-16T15:00:00Z")
    add_signed_note(clinician["id"], s3["id"])
    s3 = complete_session(clinician["id"], s3["id"])
    return {"payer": payer, "clinician": clinician, "patient": patient,
            "enrollment": attached["enrollment"], "s1": s1, "s2": s2, "s3": s3}


def test_payer_suspension_cascades_through_enrollment_into_clinician_posture_and_session_cancellation():
    """PRD §3.8: "First, every enrollment with that payer in `EFFECTIVE` status
    moves to `SUSPENDED`. Second, each enrollment that was suspended re-derives
    its clinician's `enrolled_payer_count` and posture, and a clinician whose
    `enrolled_payer_count` reaches zero becomes `FROZEN` — which is the route by
    which a payer-side problem can freeze a clinician even though every license
    and policy remains in order. Third, each clinician frozen in that hop has
    every session still in `REQUESTED` or `SCHEDULED` cancelled and each
    cancelled session's `slot_consumed` set back to false."

    Design: Difficulty/transitive_cascade/payer_suspension_cascades_three_hops_into_session_cancellation
    """
    scenario = _suspend_payer_scenario()
    clinician_id = scenario["clinician"]["id"]

    validate_success(
        api_client.patch_payer(scenario["payer"]["id"], {"status": "SUSPENDED_AT_PAYER"}, OPS)
    )

    assert get_enrollment(scenario["enrollment"]["id"])["status"] == "SUSPENDED"
    clinician = get_clinician(clinician_id)
    assert clinician["enrolled_payer_count"] == 0
    assert clinician["billing_posture"] == "FROZEN"
    assert get_session(scenario["s1"]["id"])["status"] == "CANCELLED"
    assert get_session(scenario["s2"]["id"])["status"] == "CANCELLED"
    assert get_session(scenario["s3"]["id"])["status"] == "COMPLETED"


def test_cancelled_open_sessions_release_their_slots_and_the_completed_session_keeps_its_billing_axis():
    """PRD §3.1: "A clinician whose posture reaches `FROZEN` for any reason has
    every open session cancelled and each cancelled session's `slot_consumed` set
    back to false; sessions already `COMPLETED` keep their `billing_state`
    untouched, though any later claim submission for them is refused because the
    clinician is no longer billable."
    PRD §3.4: "Cancellation frees the slot, re-derives `open_slot_count`, and
    leaves `billing_state` at `UNBILLED`."

    Design: Difficulty/transitive_cascade/payer_suspension_cascades_three_hops_into_session_cancellation
    """
    scenario = _suspend_payer_scenario()
    clinician_id = scenario["clinician"]["id"]
    assert get_clinician(clinician_id)["open_slot_count"] == 18, (
        "the two still-open sessions hold two of the block's twenty available "
        "hours; the completed third already released its own"
    )

    validate_success(
        api_client.patch_payer(scenario["payer"]["id"], {"status": "SUSPENDED_AT_PAYER"}, OPS)
    )

    for session_id in (scenario["s1"]["id"], scenario["s2"]["id"]):
        cancelled = get_session(session_id)
        assert cancelled["slot_consumed"] is False
        assert cancelled["billing_state"] == "UNBILLED"
    completed = get_session(scenario["s3"]["id"])
    assert completed["slot_consumed"] is False, (
        "completion had already released its own slot"
    )
    assert completed["billing_state"] == "UNBILLED", (
        "the completed session's billing axis was never touched"
    )
    assert get_clinician(clinician_id)["open_slot_count"] == 20, (
        "the two cancelled whole hours came back to the availability pool"
    )


def test_requesting_offboarding_synthesises_one_continuity_plan_per_matched_patient():
    """PRD §3.7: "an `OpsAdmin` may move an `ACTIVE` clinician into `OFFBOARDING`
    only when the clinician's `open_slot_count` is 0 and they carry at least one
    active patient, and doing so stamps `offboarding_requested_on` from the
    clock, drops `billing_posture` to `GATED`, and creates one plan per
    `PatientClient` whose `matched_clinician_id` is that clinician, each at
    `PENDING` with `reason` of `OFFBOARDING` and `successor_clinician_id` null."
    PRD §3.7: "its `reassignment_deadline` is the departure instant plus the
    30-day continuity grace window, computed on the logical clock".

    Design: Difficulty/transitive_cascade/offboarding_request_creates_continuity_plans_that_escalate_on_session_completion
    """
    scenario = setup_clinician_matched_to_two_patients()
    clinician_id = scenario["clinician"]["id"]

    assert get_clinician(clinician_id)["open_slot_count"] == 0
    assert get_clinician(clinician_id)["active_patient_count"] == 2

    offboarded = validate_success(api_client.request_offboarding(clinician_id, OPS))
    assert offboarded["status"] == "OFFBOARDING"
    assert offboarded["offboarding_requested_on"] == "2026-06-25T00:00:00Z"
    assert offboarded["billing_posture"] == "GATED"

    plans = api_client.list_clinician_continuity_plans(clinician_id, OPS).json()["data"]
    assert len(plans) == 2, "one plan per matched patient"
    for plan in plans:
        assert plan["status"] == "PENDING"
        assert plan["reason"] == "OFFBOARDING"
        assert plan["successor_clinician_id"] is None
        assert plan["reassignment_deadline"] == "2026-07-25T00:00:00Z", (
            "the deadline is the offboarding instant plus the 30-day grace window"
        )
    escalated = api_client.list_clinician_continuity_plans(
        clinician_id, OPS, {"status": "ESCALATED", "limit": 10, "offset": 0}
    ).json()["data"]
    assert escalated == [], (
        "the offboarding request alone escalates nothing"
    )


def test_a_session_completion_against_a_departing_clinician_escalates_the_pending_plan_and_raises_the_swap_flag():
    """PRD §3.4: "when the owning clinician's `status` is `OFFBOARDING` or
    `OFFBOARDED` at the moment of completion, the pending continuity plan for
    that clinician-and-patient pair escalates."
    PRD §3.7: "The first is a session for the patient completing while the owning
    clinician's `status` is `OFFBOARDING` or `OFFBOARDED`."
    PRD §3.7: "Whenever a plan escalates, the patient's `swap_requested` flag is
    set to true, and the flag is cleared only when the plan returns to `PENDING`
    or when a successor accepts it."

    Design: Difficulty/transitive_cascade/offboarding_request_creates_continuity_plans_that_escalate_on_session_completion
    """
    scenario = setup_clinician_matched_to_two_patients()
    clinician_id = scenario["clinician"]["id"]
    session_id = scenario["session"]["id"]
    completed_patient_id = scenario["session_patient"]["id"]
    other_patient_id = (
        scenario["pat_a"]["id"]
        if completed_patient_id == scenario["pat_b"]["id"]
        else scenario["pat_b"]["id"]
    )

    validate_success(api_client.request_offboarding(clinician_id, OPS))
    completed = validate_success(
        api_client.complete_session(session_id, make_clinician_headers(clinician_id))
    )
    assert completed["status"] == "COMPLETED"
    assert completed["billing_state"] == "UNBILLED", (
        "completion makes the session claim-eligible without creating a claim"
    )

    escalated = api_client.list_clinician_continuity_plans(
        clinician_id, OPS, {"status": "ESCALATED", "limit": 10, "offset": 0}
    ).json()["data"]
    assert len(escalated) == 1, "exactly the completed patient's plan escalates"
    assert escalated[0]["patient_id"] == completed_patient_id
    assert get_patient(completed_patient_id)["swap_requested"] is True
    assert get_patient(other_patient_id)["swap_requested"] is False, (
        "the other matched patient's flag is untouched"
    )