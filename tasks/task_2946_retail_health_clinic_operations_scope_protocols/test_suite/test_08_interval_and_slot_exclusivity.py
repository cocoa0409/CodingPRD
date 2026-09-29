"""Half-open shift intervals against a per-clinician resource, and slot buffers vs caps."""
from test_helpers import (
    ASSIGNMENT_SCHEDULED,
    QUEUE_SCHEDULED,
    ApiErrorId,
    add_appointment,
    appointment_payload,
    create_patient,
    error_id,
    read_clinician,
    read_physician,
    staffed_clinic,
    staffing_assignment_payload,
    validate_error,
    validate_success,
)

MORNING = ("2026-08-01T08:00:00Z", "2026-08-01T12:00:00Z")
AFTERNOON = ("2026-08-01T12:00:00Z", "2026-08-01T16:00:00Z")
STRADDLE = ("2026-08-01T11:00:00Z", "2026-08-01T15:00:00Z")


def _two_clinicians_under_one_physician(api):
    """A CA clinic with two CA-licensed clinicians and no shifts on the board yet."""
    env = staffed_clinic(api, with_protocol=False, staff=False, clinician_count=2,
                         physician={"full_name": "Dr Owen"})
    return env


def _file_shift(api, env, clinician_index, window):
    starts_at, ends_at = window
    payload = staffing_assignment_payload(
        env["clinic_id"], env["clinicians"][clinician_index]["id"],
        starts_at=starts_at, ends_at=ends_at,
        pinned_supervising_physician_id=env["physician_id"])
    return api.create_staffing_assignment(payload, env["admin"])


def test_back_to_back_shifts_touching_at_a_single_instant_are_both_accepted(api):
    """A 08:00–12:00 and a 12:00–16:00 shift for one clinician do not overlap.

    PRD: "Half-openness has a practical consequence worth stating plainly: back-to-back
    shifts where one ends at exactly the instant the next begins do not overlap and are
    perfectly legal, while any genuine straddle earns `ERR_CLINICIAN_DOUBLE_BOOKED`
    when the same clinician already holds a `SCHEDULED` or `ACTIVE` assignment across
    the same span."

    Design: Difficulty/resource_temporal_overlap/clinician_assignment_half_open_adjacency_legal_overlap_rejected
    """
    env = _two_clinicians_under_one_physician(api)

    morning = validate_success(_file_shift(api, env, 0, MORNING), 201)
    afternoon = validate_success(_file_shift(api, env, 0, AFTERNOON), 201)

    assert morning["ends_at"] == afternoon["starts_at"]
    assert read_clinician(api, env["clinicians"][0]["id"])["active_assignment_count"] == 2


def test_a_shift_whose_window_the_clock_has_not_reached_is_born_scheduled(api):
    """The logical clock is still at midnight, so neither shift has activated.

    PRD: "An assignment is born `SCHEDULED`. It advances `SCHEDULED → ACTIVE` the
    moment the logical clock sits inside its interval — either because the clock was
    already there when the assignment was created, in which case the activation happens
    inside the same request, or because a later clock move crossed `starts_at`."

    Design: Difficulty/resource_temporal_overlap/clinician_assignment_half_open_adjacency_legal_overlap_rejected
    """
    env = _two_clinicians_under_one_physician(api)

    morning = validate_success(_file_shift(api, env, 0, MORNING), 201)
    afternoon = validate_success(_file_shift(api, env, 0, AFTERNOON), 201)

    assert morning["status"] == ASSIGNMENT_SCHEDULED
    assert afternoon["status"] == ASSIGNMENT_SCHEDULED


def test_a_genuine_straddle_of_the_same_clinician_is_double_booked(api):
    """An 11:00–15:00 shift strictly overlaps the morning one and is refused.

    PRD: "A clinician's scheduled or active assignments must not overlap in time, else
    `ERR_CLINICIAN_DOUBLE_BOOKED` (409). This rung guards staffing creation and float
    coverage."

    Design: Difficulty/resource_temporal_overlap/clinician_assignment_half_open_adjacency_legal_overlap_rejected
    """
    env = _two_clinicians_under_one_physician(api)
    validate_success(_file_shift(api, env, 0, MORNING), 201)
    validate_success(_file_shift(api, env, 0, AFTERNOON), 201)

    response = _file_shift(api, env, 0, STRADDLE)

    validate_error(response, ApiErrorId.ERR_CLINICIAN_DOUBLE_BOOKED, 409)
    assert read_clinician(api, env["clinicians"][0]["id"])["active_assignment_count"] == 2


def test_the_overlap_exclusion_is_per_clinician_not_per_clinic(api):
    """The identical straddling window is accepted for the second clinician.

    PRD: "A physician's `current_supervised_count` is the number of **distinct**
    clinicians appearing on assignments that name that physician as pinned supervisor
    and sit in `SCHEDULED` or `ACTIVE` status; two shifts for the same clinician under
    the same physician count once, and `CANCELLED` or `COMPLETED` assignments are
    excluded entirely."

    Design: Difficulty/resource_temporal_overlap/clinician_assignment_half_open_adjacency_legal_overlap_rejected
    """
    env = _two_clinicians_under_one_physician(api)
    validate_success(_file_shift(api, env, 0, MORNING), 201)
    validate_success(_file_shift(api, env, 0, AFTERNOON), 201)
    _file_shift(api, env, 0, STRADDLE)

    other = validate_success(_file_shift(api, env, 1, STRADDLE), 201)

    assert other["status"] == ASSIGNMENT_SCHEDULED
    assert read_physician(api, env["physician_id"])["current_supervised_count"] == 2


def _clinic_with_one_slot_an_hour(api):
    """An OPEN CA clinic whose hourly appointment allowance is a single slot."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         clinic={"appointment_slots_per_hour": 1})
    env["patients"] = [
        create_patient(api, env["front_desk"], full_name=name, date_of_birth=birth)
        for name, birth in (("Nine Oclock", "1980-01-01"),
                            ("Nine Thirtyfive", "1980-02-01"),
                            ("Ten Oclock", "1980-03-01"),
                            ("Ten Twentyfive", "1980-04-01"))]
    return env


def _book(api, env, patient_index, scheduled_at):
    payload = appointment_payload(env["clinic_id"],
                                 env["patients"][patient_index]["id"], scheduled_at)
    return api.create_queue_entry(payload, env["front_desk"])


def test_the_first_appointment_in_an_empty_hour_is_booked(api):
    """A 09:00 slot with nothing else on the books is accepted.

    PRD: "The requested `scheduled_at` must not be earlier than the logical clock —
    the past cannot be booked — else `ERR_INVALID_TIME_RANGE`."

    Design: Difficulty/resource_temporal_overlap/appointment_thirty_minute_buffer_versus_hourly_slot_cap
    """
    env = _clinic_with_one_slot_an_hour(api)

    entry = add_appointment(api, env, env["patients"][0]["id"],
                            "2026-08-01T09:00:00Z")

    assert entry["status"] == QUEUE_SCHEDULED
    assert entry["scheduled_at"] is not None


def test_a_thirty_five_minute_gap_clears_the_buffer_but_the_hour_is_already_full(api):
    """09:35 is legally spaced from 09:00 yet the 09:00 hour holds its one slot.

    PRD: "And the clock hour into which `scheduled_at` falls must not already hold
    `appointment_slots_per_hour` appointments at that clinic — this is an aggregate
    check across the whole hour, not a per-slot check — else
    `ERR_HOURLY_SLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/appointment_thirty_minute_buffer_versus_hourly_slot_cap
    """
    env = _clinic_with_one_slot_an_hour(api)
    validate_success(_book(api, env, 0, "2026-08-01T09:00:00Z"), 201)

    response = _book(api, env, 1, "2026-08-01T09:35:00Z")

    validate_error(response, ApiErrorId.ERR_HOURLY_SLOT_CAPACITY_EXCEEDED, 409)
    assert error_id(response) != "ERR_APPOINTMENT_SLOT_CONFLICT"


def test_a_fresh_clock_hour_gets_its_own_slot_allowance(api):
    """The 10:00 hour is empty, so a 10:00 appointment books normally.

    PRD: "It must sit at least 30 minutes away from the slot of every other appointment
    at the same clinic that is currently `SCHEDULED` or `WAITING`, a spacing that
    reflects a 20-minute visit plus 10 minutes of turnover; a gap of exactly 30 minutes
    is legal, anything narrower is refused with `ERR_APPOINTMENT_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/appointment_thirty_minute_buffer_versus_hourly_slot_cap
    """
    env = _clinic_with_one_slot_an_hour(api)
    validate_success(_book(api, env, 0, "2026-08-01T09:00:00Z"), 201)
    _book(api, env, 1, "2026-08-01T09:35:00Z")

    entry = validate_success(_book(api, env, 2, "2026-08-01T10:00:00Z"), 201)

    assert entry["status"] == QUEUE_SCHEDULED


def test_a_twenty_five_minute_gap_reports_the_spacing_error_ahead_of_the_cap(api):
    """10:25 breaks both rules and the spacing rule is the earlier rung.

    PRD: "**Appointment spacing.** A new appointment must be at least 30 minutes away
    from every other scheduled or waiting appointment at the clinic, else
    `ERR_APPOINTMENT_SLOT_CONFLICT` (409). This rung guards queue intake."

    Design: Difficulty/resource_temporal_overlap/appointment_thirty_minute_buffer_versus_hourly_slot_cap
    """
    env = _clinic_with_one_slot_an_hour(api)
    validate_success(_book(api, env, 0, "2026-08-01T09:00:00Z"), 201)
    validate_success(_book(api, env, 2, "2026-08-01T10:00:00Z"), 201)

    response = _book(api, env, 3, "2026-08-01T10:25:00Z")

    validate_error(response, ApiErrorId.ERR_APPOINTMENT_SLOT_CONFLICT, 409)
    assert error_id(response) != "ERR_HOURLY_SLOT_CAPACITY_EXCEEDED"
