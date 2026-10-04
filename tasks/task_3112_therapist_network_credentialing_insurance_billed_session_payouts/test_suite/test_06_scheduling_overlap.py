"""Interval semantics: the clinician's buffered availability versus the
patient's exact half-open bookings."""
from test_helpers import (
    ApiErrorId,
    CLOCK_DELIVERY,
    CLOCK_ONBOARD,
    attach_billable_clinician,
    api_client,
    get_clinician,
    get_session,
    make_payer,
    make_rate,
    make_session,
    make_scheduled_session,
    make_verified_patient,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_clinician_headers

OPS = TEST_USERS["ops_admin_headers"]


def _buffer_scenario(include_14: bool = True) -> dict:
    """One BILLABLE clinician with a 600-minute Tuesday block, one scheduled
    one-hour session, and two requested follow-ups gated at 14 and 15 minutes.

    `include_14` drops the 14-minute probe: a REQUESTED session is itself
    non-terminal, so the two probes would overlap each other and the accepted one
    would be refused on that account rather than on the buffer.

    The follow-ups sit on three distinct patients so that the patient-level rule
    can never be the operative conflict: only the clinician buffer separates the
    rejected 14-minute gap from the accepted 15-minute one.
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(
        payer["id"],
        availability_blocks=[{"weekday": 2, "start_minute": 480, "end_minute": 1080}],
    )
    clinician = attached["clinician"]
    pat_a = make_verified_patient(payer["id"], full_name="Priya Anand", member_id="MBR-4410")
    pat_b = make_verified_patient(
        payer["id"], full_name="Marcus Cole", member_id="MBR-5182",
        verification={"deductible_remaining_cents": 40_000},
    )
    pat_c = make_verified_patient(
        payer["id"], full_name="Elena Vargas", member_id="MBR-6031",
        verification={"deductible_remaining_cents": 20_000},
    )
    set_clock(CLOCK_DELIVERY)
    s_a = make_scheduled_session(
        clinician["id"], pat_a["id"], "2026-06-23T14:00:00Z", "2026-06-23T15:00:00Z"
    )
    s_14 = (
        make_session(clinician["id"], pat_b["id"], "2026-06-23T15:14:00Z", "2026-06-23T16:14:00Z")
        if include_14
        else None
    )
    s_15 = make_session(
        clinician["id"], pat_c["id"], "2026-06-23T15:15:00Z", "2026-06-23T16:15:00Z"
    )
    return {"clinician": clinician, "s_a": s_a, "s_14": s_14, "s_15": s_15}


def test_a_session_starting_fourteen_minutes_after_another_ends_is_refused_on_the_clinician():
    """PRD §3.4: "neither the clinician nor the patient may hold an overlapping
    non-terminal session, where the clinician's own sessions additionally observe
    a 15-minute buffer — a session beginning exactly 15 minutes after another
    ends is accepted, while one beginning exactly 14 minutes after is rejected
    with `ERR_CLINICIAN_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/clinician_availability_enforces_a_fifteen_minute_handover_buffer_on_adjacent_sessions
    """
    scenario = _buffer_scenario()
    headers = make_clinician_headers(scenario["clinician"]["id"])

    rejected = api_client.schedule_session(scenario["s_14"]["id"], headers)
    validate_error(rejected, ApiErrorId.ERR_CLINICIAN_SLOT_CONFLICT)
    assert rejected.status_code == 409

    unfilled = get_session(scenario["s_14"]["id"])
    assert unfilled["status"] == "REQUESTED"
    assert unfilled["slot_consumed"] is False


def test_a_session_starting_exactly_fifteen_minutes_after_another_ends_is_accepted_and_frees_the_counter():
    """PRD §3.4: "a session beginning exactly 15 minutes after another ends is
    accepted, while one beginning exactly 14 minutes after is rejected"
    PRD §3.4: "On success `slot_consumed` becomes true, `quoted_cost_share_cents`
    is filled from the patient's newest verified snapshot under the provisional
    variant described in §3.3, and the clinician's `open_slot_count` and the
    patient's `visit_count_year` are re-derived."

    Design: Difficulty/resource_temporal_overlap/clinician_availability_enforces_a_fifteen_minute_handover_buffer_on_adjacent_sessions
    """
    scenario = _buffer_scenario(include_14=False)
    headers = make_clinician_headers(scenario["clinician"]["id"])

    accepted = validate_success(api_client.schedule_session(scenario["s_15"]["id"], headers))
    assert accepted["status"] == "SCHEDULED"
    assert accepted["slot_consumed"] is True

    assert get_clinician(scenario["clinician"]["id"])["open_slot_count"] == 8, (
        "the block's ten whole hours less the two one-hour bookings"
    )


def _patient_booking_scenario() -> dict:
    """Three BILLABLE clinicians so clinician capacity can never mask the
    patient-level rule: p1 and p2 sit on two of them, and the straddling probe
    p3 on a third which holds nothing else."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician_a = attach_billable_clinician(
        payer["id"], full_name="Dana Reyes", license_number="LCSW-CA-77120"
    )["clinician"]
    clinician_b = attach_billable_clinician(
        payer["id"], full_name="Zara Whitfield", license_number="LCSW-CA-90211"
    )["clinician"]
    clinician_c = attach_billable_clinician(
        payer["id"], full_name="Avery Lin", license_number="LCSW-CA-90212"
    )["clinician"]
    patient = make_verified_patient(payer["id"])
    set_clock(CLOCK_DELIVERY)
    p1 = make_scheduled_session(
        clinician_a["id"], patient["id"], "2026-06-23T14:00:00Z", "2026-06-23T15:00:00Z"
    )
    p2 = make_session(clinician_b["id"], patient["id"], "2026-06-23T13:00:00Z", "2026-06-23T14:00:00Z")
    p3 = make_session(clinician_c["id"], patient["id"], "2026-06-23T14:30:00Z", "2026-06-23T15:30:00Z")
    return {"clinician_a": clinician_a, "clinician_b": clinician_b,
            "clinician_c": clinician_c, "patient": patient,
            "p1": p1, "p2": p2, "p3": p3}


def test_a_patient_booking_touching_the_previous_one_is_accepted_while_a_straddling_one_is_refused():
    """PRD §3.4: "Overlap on the patient alone is reported as
    `ERR_PATIENT_DOUBLE_BOOKED`."
    PRD §3.1: "half-open in the same way an enrollment window is, the start
    bounds the interval inclusively and the end bounds it exclusively"

    Design: Difficulty/resource_temporal_overlap/patient_bookings_use_exact_half_open_intervals_with_no_buffer
    """
    scenario = _patient_booking_scenario()
    headers_b = make_clinician_headers(scenario["clinician_b"]["id"])
    headers_c = make_clinician_headers(scenario["clinician_c"]["id"])

    touching = validate_success(api_client.schedule_session(scenario["p2"]["id"], headers_b))
    assert touching["status"] == "SCHEDULED"
    assert touching["scheduled_start"] == "2026-06-23T13:00:00Z"

    straddling = api_client.schedule_session(scenario["p3"]["id"], headers_c)
    validate_error(straddling, ApiErrorId.ERR_PATIENT_DOUBLE_BOOKED)
    assert straddling.status_code == 409

    rows = api_client.list_patient_sessions(scenario["patient"]["id"], OPS).json()["data"]
    by_id = {row["id"]: row for row in rows}
    assert by_id[scenario["p1"]["id"]]["status"] == "SCHEDULED"
    assert by_id[scenario["p2"]["id"]]["status"] == "SCHEDULED"
    assert by_id[scenario["p3"]["id"]]["status"] == "REQUESTED", (
        "the refused straddling probe was never booked"
    )


def test_a_zero_length_interval_is_refused_at_creation_before_any_overlap_check_runs():
    """PRD §2.9: "A request that is structurally malformed — a required body
    field absent, a value outside its declared enumeration, a number outside its
    permitted range, or a field the endpoint does not recognise — is rejected
    with `ERR_INVALID_REQUEST` at HTTP status 400."

    Design: Difficulty/resource_temporal_overlap/patient_bookings_use_exact_half_open_intervals_with_no_buffer
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    rejected = api_client.create_session(
        {
            "clinician_id": clinician["id"],
            "patient_id": patient["id"],
            "scheduled_start": "2026-06-30T14:00:00Z",
            "scheduled_end": "2026-06-30T14:00:00Z",
            "cpt_code": "90837",
            "modality": "VIDEO",
        },
        OPS,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400

    rows = api_client.list_sessions(OPS, {"patient_id": patient["id"]}).json()["data"]
    assert rows == [], "the malformed request persisted no session row"