"""Screening visit lifecycle: sub-records, clearance, expiry."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_center,
    make_donor,
    make_screening,
    record_pass_sub_record,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import physical_exam_payload, viral_marker_payload
from test_helpers.test_users import make_recorder_headers, make_screener_headers


def test_screening_initial_state_and_auto_in_progress(api):
    """PRD §3.3: "The first sub-record write under a `SCHEDULED` visit
    automatically advances the visit to `IN_PROGRESS`" and "Four boolean
    flags on the visit track completeness — `identity_verified`,
    `health_history_recorded`, `physical_exam_recorded`, and
    `viral_marker_recorded` — each initially false and set to true only by
    the corresponding sub-record write; they are never settable directly."

    Design: Corner/state_machines/screening_initial_state_and_auto_in_progress
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    assert visit["visit_status"] == "SCHEDULED"
    assert visit["identity_verified"] is False

    record_pass_sub_record(visit["id"], "IDENTITY", "rec-01")
    after = get_success_data(api.get_screening(visit["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "IN_PROGRESS"
    assert after["identity_verified"] is True
    assert after["health_history_recorded"] is False


def test_screening_clear_happy_path(api):
    """PRD §3.3: "A successful clearance moves the visit to `CLEARED`,
    increments its `version`, and writes a snapshot with `trigger_event`
    `screening.cleared`."

    Design: Corner/state_machines/screening_clear_happy_path
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    v0 = visit["version"]
    for rt in ("IDENTITY", "HEALTH_HISTORY", "PHYSICAL_EXAM", "VIRAL_MARKER"):
        record_pass_sub_record(visit["id"], rt, "rec-01")
    resp = api.clear_screening(visit["id"], make_screener_headers("ms-01"))
    data = validate_success(resp, 200)
    assert data["visit_status"] == "CLEARED"
    assert data["version"] > v0, "version must be incremented by the clear transition"


def test_screening_clear_with_three_subrecords_rejected(api):
    """PRD §3.3: "The screener clears an `IN_PROGRESS` visit, which succeeds
    only when every one of the four flags is true (otherwise
    `ERR_INCOMPLETE_SCREENING`, HTTP 409)".

    Design: Corner/state_machines/screening_clear_with_three_subrecords_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    for rt in ("IDENTITY", "HEALTH_HISTORY", "PHYSICAL_EXAM"):
        record_pass_sub_record(visit["id"], rt, "rec-01")
    resp = api.clear_screening(visit["id"], make_screener_headers("ms-01"))
    validate_error(resp, ApiErrorId.ERR_INCOMPLETE_SCREENING, 409)
    after = get_success_data(api.get_screening(visit["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "IN_PROGRESS", "no partial side effects"


def test_screening_clear_segregation_of_duties_rejected(api):
    """PRD §3.3: "the screener's `X-User-ID` differs from the
    `recorded_by_user_id` of **every** sub-record on the visit (a violation
    surfaces as `ERR_SEGREGATION_OF_DUTIES`, HTTP 403)".

    Design: Corner/state_machines/screening_clear_segregation_of_duties_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    for rt in ("IDENTITY", "HEALTH_HISTORY", "PHYSICAL_EXAM", "VIRAL_MARKER"):
        record_pass_sub_record(visit["id"], rt, "rec-01")
    # The clearing MedicalScreener reuses the recording user's id.
    resp = api.clear_screening(visit["id"], make_screener_headers("rec-01"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)


def test_screening_clear_terminal_lockdown(api):
    """PRD §3.3: "A visit that is not `IN_PROGRESS` at clearance time is
    rejected with `ERR_VISIT_NOT_IN_PROGRESS`." and "`CLEARED`, `FAILED`, and
    `EXPIRED` are all terminal states for a screening visit."

    Design: Corner/state_machines/screening_clear_terminal_lockdown
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    # Reactive viral marker flips the visit to FAILED (donor has no units).
    resp = api.record_sub_record(
        visit["id"],
        {
            "record_type": "VIRAL_MARKER",
            "payload": viral_marker_payload(hiv_ag_ab="REACTIVE"),
        },
        make_recorder_headers("rec-01"),
    )
    get_success_data(resp)
    resp = api.clear_screening(visit["id"], make_screener_headers("ms-01"))
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_IN_PROGRESS, 409)


def test_screening_expiry_from_scheduled_and_in_progress(api):
    """PRD §3.3: "When the logical clock reaches twenty-four hours past
    `scheduled_for` and the visit is still `SCHEDULED` or `IN_PROGRESS`, it
    transitions to `EXPIRED`".

    Design: Corner/state_machines/screening_expiry_from_scheduled_and_in_progress
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    s1 = make_screening(donor, center, "2026-09-01T08:00:00Z")
    s2 = make_screening(donor, center, "2026-09-01T10:00:00Z")
    set_clock("2026-09-01T09:30:00Z")
    record_pass_sub_record(s2["id"], "IDENTITY", "rec-01")

    set_clock("2026-09-02T08:00:00Z")
    st1 = get_success_data(api.get_screening(s1["id"], TEST_USERS["admin_headers"]))
    st2a = get_success_data(api.get_screening(s2["id"], TEST_USERS["admin_headers"]))
    assert st1["visit_status"] == "EXPIRED", "SCHEDULED visit expires at +24h"
    assert st2a["visit_status"] == "IN_PROGRESS", "s2's window ends at 10:00"

    set_clock("2026-09-02T10:00:00Z")
    st2b = get_success_data(api.get_screening(s2["id"], TEST_USERS["admin_headers"]))
    assert st2b["visit_status"] == "EXPIRED", "IN_PROGRESS visit expires at +24h"


def test_duplicate_sub_record_type_rejected(api):
    """PRD §3.3: "A second write of the same `record_type` under the same
    visit is rejected with `ERR_DUPLICATE_SUB_RECORD` (HTTP 409)."

    Design: Corner/entities/duplicate_sub_record_type_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    record_pass_sub_record(visit["id"], "IDENTITY", "rec-01")
    resp = api.record_sub_record(
        visit["id"],
        {"record_type": "IDENTITY", "payload": {"document_number": "TXDL-OTHER1"}},
        make_recorder_headers("rec-01"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUB_RECORD, 409)


def test_physical_exam_out_of_band_vital_fails_visit(api):
    """PRD §3.3: "A `PHYSICAL_EXAM` record fails when any vital is out of
    band: `weight_kg` below 50.0 (which surfaces as `ERR_DONOR_UNDERWEIGHT`,
    HTTP 422), `pulse_bpm` below 50 or above 100" and "Any sub-record write
    whose computed `outcome` is `FAIL` automatically transitions the visit
    from `IN_PROGRESS` to `FAILED`, with a snapshot `trigger_event` of
    `screening.failed`."

    Design: Corner/entities/physical_exam_out_of_band_vital_fails_visit
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    resp = api.record_sub_record(
        visit["id"],
        {
            "record_type": "PHYSICAL_EXAM",
            "payload": physical_exam_payload(pulse_bpm=120),
        },
        make_recorder_headers("rec-01"),
    )
    sub = get_success_data(resp)
    assert sub["outcome"] == "FAIL", "pulse_bpm 120 exceeds the 50..100 band"
    after = get_success_data(api.get_screening(visit["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "FAILED"


def test_underweight_physical_exam_rejected_422(api):
    """PRD §3.3: "A `PHYSICAL_EXAM` record fails when any vital is out of
    band: `weight_kg` below 50.0 (which surfaces as `ERR_DONOR_UNDERWEIGHT`,
    HTTP 422)".

    Design: Corner/entities/underweight_physical_exam_rejected_422
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center, weight_kg=49.9)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    resp = api.record_sub_record(
        visit["id"],
        {
            "record_type": "PHYSICAL_EXAM",
            "payload": physical_exam_payload(weight_kg=49.9),
        },
        make_recorder_headers("rec-01"),
    )
    validate_error(resp, ApiErrorId.ERR_DONOR_UNDERWEIGHT, 422)


def test_sub_record_on_terminal_visit_rejected(api):
    """PRD §3.3: "A `HEALTH_HISTORY` record fails when `risk_flags` is
    non-empty" and "`CLEARED`, `FAILED`, and `EXPIRED` are all terminal states
    for a screening visit." PRD §2.9 item 6: "State-machine applicability of
    the requested transition → `ERR_INVALID_STATE`."

    Design: Corner/entities/sub_record_on_terminal_visit_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    resp = api.record_sub_record(
        visit["id"],
        {"record_type": "HEALTH_HISTORY", "payload": {"risk_flags": ["TRAVEL_MALARIA"]}},
        make_recorder_headers("rec-01"),
    )
    sub = get_success_data(resp)
    assert sub["outcome"] == "FAIL"
    after = get_success_data(api.get_screening(visit["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "FAILED"

    resp = api.record_sub_record(
        visit["id"],
        {"record_type": "IDENTITY", "payload": {"document_number": "TXDL-883491"}},
        make_recorder_headers("rec-01"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict:
# clear_completeness_beats_segregation_of_duties (2 tests)
# ---------------------------------------------------------------------------

def test_clear_completeness_beats_segregation_error_id(api):
    """PRD §3.3: "The screener clears an `IN_PROGRESS` visit, which succeeds
    only when every one of the four flags is true (otherwise
    `ERR_INCOMPLETE_SCREENING`, HTTP 409), every sub-record's `outcome` is
    `PASS` (otherwise `ERR_SCREENING_NOT_PASSABLE`, HTTP 409), the screener's
    `X-User-ID` differs from the `recorded_by_user_id` of **every** sub-record
    on the visit (a violation surfaces as `ERR_SEGREGATION_OF_DUTIES`,
    HTTP 403)". The completeness condition is stated before the
    segregation-of-duties condition, so with only two of four sub-records the
    completeness error surfaces even when the clearing user id equals the
    recording user id.

    Design: Difficulty/priority_pair_validation_conflict/clear_completeness_beats_segregation_of_duties
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    for rt in ("IDENTITY", "HEALTH_HISTORY"):
        record_pass_sub_record(visit["id"], rt, "rec-01")
    # Clearing user id equals recorded_by_user_id AND only 2 of 4 records.
    resp = api.clear_screening(visit["id"], make_screener_headers("rec-01"))
    validate_error(resp, ApiErrorId.ERR_INCOMPLETE_SCREENING, 409)


def test_clear_completeness_beats_segregation_no_side_effects(api):
    """PRD §3.3: "A successful clearance moves the visit to `CLEARED`,
    increments its `version`". A rejected clearance (completeness fires ahead
    of segregation of duties per the condition order in §3.3) leaves the visit
    untouched in IN_PROGRESS.

    Design: Difficulty/priority_pair_validation_conflict/clear_completeness_beats_segregation_of_duties
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    for rt in ("IDENTITY", "HEALTH_HISTORY"):
        record_pass_sub_record(visit["id"], rt, "rec-01")
    resp = api.clear_screening(visit["id"], make_screener_headers("rec-01"))
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == "ERR_INCOMPLETE_SCREENING"
    after = get_success_data(api.get_screening(visit["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "IN_PROGRESS"
    assert after["viral_marker_recorded"] is False
