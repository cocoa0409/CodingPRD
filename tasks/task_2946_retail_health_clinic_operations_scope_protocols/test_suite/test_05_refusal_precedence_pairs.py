"""Requests that break two rules at once must name the higher rung of the ladder."""
from test_helpers import (
    ApiErrorId,
    QUEUE_WAITING,
    add_appointment,
    create_clinician,
    create_patient,
    error_id,
    read_clinician,
    read_physician,
    read_queue_entry,
    set_clock,
    staffed_clinic,
    staffing_assignment_payload,
    validate_error,
    validate_success,
)

APPOINTMENT_SLOT = "2026-08-01T09:00:00Z"


def _appointment_checked_in_then_the_clock_runs_past_the_window(api):
    """A 09:00 appointment arrives at 08:50; the clock then moves to 09:30."""
    env = staffed_clinic(api, protocol={"requires_cosign": True})
    patient = create_patient(api, env["front_desk"], full_name="Tim Timely",
                             date_of_birth="1991-09-09")
    entry = add_appointment(api, env, patient["id"], APPOINTMENT_SLOT)
    set_clock(api, "2026-08-01T08:50:00Z", env["admin"])
    env["first_arrival"] = validate_success(
        api.arrive_queue_entry(entry["id"], env["front_desk"]))
    set_clock(api, "2026-08-01T09:30:00Z", env["admin"])
    env["entry"] = entry
    return env


def test_an_appointment_checking_in_ten_minutes_early_is_admitted_to_the_room(api):
    """08:50 sits inside the window that opens 15 minutes before a 09:00 slot.

    PRD: "The arrival window is generous on the early side and tight on the late
    side: the logical clock must fall between 15 minutes before `scheduled_at` and 10
    minutes after it, both endpoints included; outside that window the check-in is
    refused with `ERR_APPOINTMENT_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/arrive_twice_after_window_returns_state_error_not_window_error
    """
    env = _appointment_checked_in_then_the_clock_runs_past_the_window(api)

    assert env["first_arrival"]["status"] == QUEUE_WAITING
    assert env["first_arrival"]["arrived_at"] is not None


def test_arriving_twice_past_the_window_names_the_state_error_not_the_window_error(api):
    """Both rules are broken and the earlier rung — the transition — must answer.

    PRD: "When a single request violates several rules at once, the response must
    name the earliest violated rule in the fixed ladder below, not whichever check the
    implementation happens to run first."

    Design: Difficulty/priority_pair_validation_conflict/arrive_twice_after_window_returns_state_error_not_window_error
    """
    env = _appointment_checked_in_then_the_clock_runs_past_the_window(api)

    response = api.arrive_queue_entry(env["entry"]["id"], env["front_desk"])

    validate_error(response, ApiErrorId.ERR_QUEUE_ENTRY_INVALID_STATE, 409)
    assert error_id(response) != "ERR_APPOINTMENT_WINDOW_CLOSED"


def test_the_refused_second_arrival_leaves_the_entry_exactly_as_it_was(api):
    """The entry is still WAITING with its original arrival stamp.

    PRD: "It applies only to entries whose `kind` is `APPOINTMENT`; an entry that is
    not currently `SCHEDULED` — because it is already `WAITING`, or `SERVED`, or
    `ABANDONED`, or `DEFERRED_CLOSURE` — is refused with
    `ERR_QUEUE_ENTRY_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/arrive_twice_after_window_returns_state_error_not_window_error
    """
    env = _appointment_checked_in_then_the_clock_runs_past_the_window(api)

    api.arrive_queue_entry(env["entry"]["id"], env["front_desk"])

    entry = read_queue_entry(api, env["entry"]["id"])
    assert entry["status"] == QUEUE_WAITING
    assert entry["arrived_at"] == env["first_arrival"]["arrived_at"]


def _physician_at_her_cap_with_an_out_of_state_candidate(api):
    """Dr Jinn's effective cap of one is used up; a TX clinician awaits a shift."""
    env = staffed_clinic(api, with_protocol=False,
                         physician={"full_name": "Dr Jinn",
                                    "max_supervised_clinicians": 1},
                         clinician={"full_name": "NP J One"})
    env["out_of_state"] = create_clinician(
        api, env["clinic_id"], env["physician_id"], env["admin"],
        full_name="PA J Two", credential="PA", license_state_code="TX")
    return env


def test_one_supervised_clinician_already_meets_the_smaller_of_the_two_caps(api):
    """A physician cap of 1 under a state cap of 3 makes the effective cap 1.

    PRD: "Before a new assignment is accepted, the system compares that count against
    the effective cap — the smaller of the physician's `max_supervised_clinicians` and
    the state's `max_supervised_clinicians_per_physician` — and refuses with
    `ERR_SUPERVISION_CAPACITY_EXCEEDED` when the assignment would introduce a
    clinician not already counted and the count has already reached or passed the cap."

    Design: Difficulty/priority_pair_validation_conflict/unlicensed_clinician_over_capacity_returns_licensing_error
    """
    env = _physician_at_her_cap_with_an_out_of_state_candidate(api)

    physician = read_physician(api, env["physician_id"])

    assert physician["current_supervised_count"] == 1
    assert physician["max_supervised_clinicians"] == 1


def test_staffing_an_unlicensed_clinician_over_cap_names_the_licensure_error(api):
    """Licensure sits above supervision capacity, so licensure answers.

    PRD: "The acting clinician's `license_state_code` must equal the clinic's
    `state_code`, else `ERR_CLINICIAN_NOT_LICENSED_IN_STATE` (422). This rung guards
    staffing creation, float coverage and visit creation."

    Design: Difficulty/priority_pair_validation_conflict/unlicensed_clinician_over_capacity_returns_licensing_error
    """
    env = _physician_at_her_cap_with_an_out_of_state_candidate(api)
    payload = staffing_assignment_payload(
        env["clinic_id"], env["out_of_state"]["id"],
        pinned_supervising_physician_id=env["physician_id"])

    response = api.create_staffing_assignment(payload, env["admin"])

    validate_error(response, ApiErrorId.ERR_CLINICIAN_NOT_LICENSED_IN_STATE, 422)
    assert error_id(response) != "ERR_SUPERVISION_CAPACITY_EXCEEDED"


def test_the_refused_assignment_moves_neither_staffing_counter(api):
    """No assignment row exists, so both derived counts stand where they were.

    PRD: "A physician's `current_supervised_count` is the number of **distinct**
    clinicians appearing on assignments that name that physician as pinned supervisor
    and sit in `SCHEDULED` or `ACTIVE` status; two shifts for the same clinician under
    the same physician count once, and `CANCELLED` or `COMPLETED` assignments are
    excluded entirely."

    Design: Difficulty/priority_pair_validation_conflict/unlicensed_clinician_over_capacity_returns_licensing_error
    """
    env = _physician_at_her_cap_with_an_out_of_state_candidate(api)
    payload = staffing_assignment_payload(
        env["clinic_id"], env["out_of_state"]["id"],
        pinned_supervising_physician_id=env["physician_id"])

    api.create_staffing_assignment(payload, env["admin"])

    assert read_physician(api, env["physician_id"])["current_supervised_count"] == 1
    assert read_clinician(api, env["out_of_state"]["id"])["active_assignment_count"] == 0
