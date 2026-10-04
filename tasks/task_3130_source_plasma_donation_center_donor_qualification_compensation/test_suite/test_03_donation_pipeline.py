"""Donation pipeline: scheduling gates, check-in, volume bands, invalid transitions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_center,
    make_center_with_schedule,
    make_cleared_screening,
    make_donation,
    make_donor,
    make_screening,
    run_completed_donation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_recorder_headers, make_screener_headers


def _center_donor_screening(schedule_overrides=None, weight_kg=72.5,
                            center_overrides=None):
    set_clock("2026-09-01T09:00:00Z")
    center, schedule = make_center_with_schedule(
        center_overrides=center_overrides, **(schedule_overrides or {})
    )
    donor = make_donor(center, weight_kg=weight_kg)
    screening = make_cleared_screening(
        donor, center, "2026-09-01T08:00:00Z", weight_kg=weight_kg
    )
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    return center, schedule, donor, screening, donation


def test_screening_not_cleared_blocks_donation_scheduling(api):
    """PRD §3.4: "the referenced ScreeningVisit must belong to this donor,
    must currently be `CLEARED`, and must not have been consumed by any other
    DonationVisit that is `IN_PROGRESS` or `COMPLETED` — a violation is
    rejected with `ERR_SCREENING_NOT_CLEARED`."

    Design: Corner/validations/screening_not_cleared_blocks_donation_scheduling
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_screening(donor, center, "2026-09-02T08:00:00Z")
    resp = api.schedule_donation(
        donor["id"],
        {
            "center_id": center["id"],
            "screening_visit_id": screening["id"],
            "scheduled_for": "2026-09-02T10:00:00Z",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED, 409)


def test_screening_center_mismatch_rejected(api):
    """PRD §3.4: "the referenced screening's `center_id` must equal the
    donation's `center_id`, with any cross-center reuse rejected as
    `ERR_SCREENING_CENTER_MISMATCH`."

    Design: Corner/validations/screening_center_mismatch_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    c1 = make_center(center_code="CSL-DAL-014")
    c2 = make_center(
        center_code="CSL-FTW-002",
        legal_name="CSL Plasma Fort Worth 002",
        screening_lanes=1,
        donor_floor_beds=1,
        observation_chairs=1,
    )
    donor = make_donor(c1)
    screening = make_cleared_screening(donor, c1, "2026-09-01T08:00:00Z")
    resp = api.schedule_donation(
        donor["id"],
        {
            "center_id": c2["id"],
            "screening_visit_id": screening["id"],
            "scheduled_for": "2026-09-01T10:00:00Z",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SCREENING_CENTER_MISMATCH, 409)


def test_donation_no_show_auto_transition(api):
    """PRD §3.5: "A visit that was never checked in auto-fires `NO_SHOW` when
    the logical clock passes six hours past `scheduled_for` while the visit is
    still `SCHEDULED`."

    Design: Corner/state_machines/donation_no_show_auto_transition
    """
    center, _, donor, _, donation = _center_donor_screening()
    # No check-in happens; jump to exactly scheduled_for + 6h.
    set_clock("2026-09-01T15:30:00Z")
    after = get_success_data(api.get_donation(donation["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "NO_SHOW"
    data, meta = validate_paginated(
        api.get_payment_for_visit(donation["id"], TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 0, "no check-in means no payment row"


def test_donation_happy_path_side_effects(api):
    """PRD §3.4: "The visit transitions to `IN_PROGRESS`; `bed_index` is
    assigned via the lowest-free-bed rule; the donor's `weight_kg` is
    refreshed from the most recent `PHYSICAL_EXAM` sub-record on the
    qualifying screening; and `programmed_volume_ml` is computed once and
    frozen."
    PRD §3.5: "A successful discharge moves the visit to `COMPLETED`, frees
    the observation chair, and fires a cascade of side effects that the next
    three subsections unpack: the unit is created and quarantined,
    compensation is finalized, the donor's counters and status are updated".
    PRD §3.6: "Discharge creates exactly one **DonationUnit** for the
    completed visit, with `volume_ml` equal to the visit's
    `actual_volume_ml`, `collected_at` stamped from the logical clock, the
    parent visit's id recorded as `donation_visit_id`, and `donor_id` and
    `center_id` denormalized onto the row, and `unit_status` `QUARANTINED`."

    Design: Corner/state_machines/donation_happy_path_side_effects
    """
    center, _, donor, _, donation = _center_donor_screening()
    assert donation["visit_status"] == "SCHEDULED"

    checked = get_success_data(api.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    assert checked["visit_status"] == "IN_PROGRESS"
    assert checked["bed_index"] == 0
    assert checked["programmed_volume_ml"] == 690

    obs = get_success_data(
        api.complete_collection(
            donation["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    assert obs["visit_status"] == "OBSERVATION"
    assert obs["observation_chair_index"] == 0

    set_clock("2026-09-01T09:46:00Z")
    done = get_success_data(api.discharge(donation["id"], TEST_USERS["phlebotomist_headers"]))
    assert done["visit_status"] == "COMPLETED"

    pdata, pmeta = validate_paginated(
        api.get_payment_for_visit(donation["id"], TEST_USERS["admin_headers"])
    )
    assert pmeta["total_count"] == 1
    assert pdata[0]["payment_status"] == "FINALIZED"
    assert pdata[0]["variant"] == "FINAL"
    assert pdata[0]["net_cents"] == 3000

    d = get_success_data(api.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["lifetime_donation_count"] == 1
    assert d["ytd_compensation_cents"] == 3000
    assert d["applicant_window_started_on"] == "2026-09-01T09:46:00.000Z"

    udata, umeta = validate_paginated(
        api.list_units(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    assert umeta["total_count"] == 1
    assert udata[0]["unit_status"] == "QUARANTINED"
    assert udata[0]["volume_ml"] == 690


def test_donation_invalid_transition_matrix(api):
    """PRD §3.5: "The visit must be `OBSERVATION` (`ERR_VISIT_NOT_OBSERVABLE`
    otherwise)" for discharge; "The visit must be `IN_PROGRESS`
    (`ERR_VISIT_NOT_IN_PROGRESS` otherwise)" for complete-collection.
    PRD §3.9: "The visit must be `IN_PROGRESS` or `OBSERVATION`; any other
    state rejects with `ERR_VISIT_NOT_ABORTABLE`."

    Design: Corner/state_machines/donation_invalid_transition_matrix
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(center_overrides={"donor_floor_beds": 3})

    # dvC: COMPLETED first (clock ends at 09:46; keep the clock monotone).
    donor_c = make_donor(center, external_donor_ref="DL-TX-0000C1",
                         legal_first_name="Cat", legal_last_name="Carr",
                         date_of_birth="1992-11-30")
    dv_c = run_completed_donation(
        donor_c, center,
        screening_scheduled_for="2026-09-01T08:00:00Z",
        checkin_time="2026-09-01T09:30:00Z",
        discharge_time="2026-09-01T09:46:00Z",
        recorder_id="rec-03",
    )

    # dvA: will be checked in (IN_PROGRESS); dvB: stays SCHEDULED.
    donor_a = make_donor(center, external_donor_ref="DL-TX-0000A1",
                         legal_first_name="Ann", legal_last_name="Adler",
                         date_of_birth="1988-02-02")
    s_a = make_cleared_screening(donor_a, center, "2026-09-01T08:00:00Z", recorder_id="rec-01")
    dv_a = make_donation(donor_a, center, s_a, "2026-09-01T09:30:00Z")
    donor_b = make_donor(center, external_donor_ref="DL-TX-0000B1",
                         legal_first_name="Bob", legal_last_name="Baker",
                         date_of_birth="1985-07-19")
    s_b = make_cleared_screening(donor_b, center, "2026-09-01T08:00:00Z", recorder_id="rec-02")
    dv_b = make_donation(donor_b, center, s_b, "2026-09-01T09:30:00Z")

    get_success_data(api.check_in(dv_a["id"], TEST_USERS["phlebotomist_headers"]))

    r1 = api.discharge(dv_a["id"], TEST_USERS["phlebotomist_headers"])
    validate_error(r1, ApiErrorId.ERR_VISIT_NOT_OBSERVABLE, 409)

    r2 = api.complete_collection(
        dv_b["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
    )
    validate_error(r2, ApiErrorId.ERR_VISIT_NOT_IN_PROGRESS, 409)

    r3 = api.record_adverse_reaction(
        dv_c["id"],
        {
            "severity": "MILD",
            "reaction_code": "VASOVAGAL",
            "observed_at": "2026-09-01T09:46:00Z",
            "notes": "late faintness after completion",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    validate_error(r3, ApiErrorId.ERR_VISIT_NOT_ABORTABLE, 409)

    assert get_success_data(api.get_donation(dv_a["id"], TEST_USERS["admin_headers"]))["visit_status"] == "IN_PROGRESS"
    assert get_success_data(api.get_donation(dv_b["id"], TEST_USERS["admin_headers"]))["visit_status"] == "SCHEDULED"
    assert get_success_data(api.get_donation(dv_c["id"], TEST_USERS["admin_headers"]))["visit_status"] == "COMPLETED"


def test_recorder_cannot_check_in_donation(api):
    """PRD §4 lists POST `/donation-visits/{visitId}/check-in` with
    Phlebotomist as its only authorized role, so a Recorder attempting
    check-in acts outside the caller's designated role.
    PRD §2.1: "An attempt to perform an action outside of the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/validations/recorder_cannot_check_in_donation
    """
    center, _, donor, _, donation = _center_donor_screening()
    resp = api.check_in(donation["id"], TEST_USERS["recorder_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
    after = get_success_data(api.get_donation(donation["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner/calculations: weight bands
# ---------------------------------------------------------------------------

def _donor_with_checked_in_visit(center, ref, first, last, dob, weight):
    donor = make_donor(
        center, external_donor_ref=ref, legal_first_name=first,
        legal_last_name=last, date_of_birth=dob, weight_kg=weight,
    )
    screening = make_cleared_screening(
        donor, center, "2026-09-01T08:00:00Z",
        recorder_id="rec-01", weight_kg=weight,
    )
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    return donor, donation


def test_plasma_volume_upper_band_edges_79_and_110(api):
    """PRD §3.4: "From 79.0 up to but not including 110.0 kilograms it is
    825 mL. At 110.0 kilograms and above it is 880 mL. Boundaries are strictly
    greater-or-equal on the lower edge and strictly less-than on the upper
    edge".

    Design: Corner/calculations/plasma_volume_upper_band_edges_79_and_110
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    _, dv_a = _donor_with_checked_in_visit(
        center, "DL-TX-0000A1", "Ann", "Adler", "1988-02-02", 79.0
    )
    _, dv_b = _donor_with_checked_in_visit(
        center, "DL-TX-0000B1", "Bob", "Baker", "1985-07-19", 110.0
    )
    set_clock("2026-09-01T09:30:00Z")
    a = get_success_data(api.check_in(dv_a["id"], TEST_USERS["phlebotomist_headers"]))
    b = get_success_data(api.check_in(dv_b["id"], TEST_USERS["phlebotomist_headers"]))
    assert a["programmed_volume_ml"] == 825, "exactly 79.0 kg lands in the third band"
    assert b["programmed_volume_ml"] == 880, "exactly 110.0 kg lands in the top band"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check: weight_band_boundary_67_9_vs_68_0 (2 tests)
# ---------------------------------------------------------------------------

def test_weight_band_boundary_67_9_programs_625(api):
    """PRD §3.4: "From 50.0 up to but not including 68.0 kilograms the
    programmed volume is 625 mL. From 68.0 up to but not including 79.0
    kilograms it is 690 mL." and "Boundaries are strictly greater-or-equal on
    the lower edge and strictly less-than on the upper edge: a donor weighing
    exactly 68.0 kg lands in the 690-mL band".

    Design: Difficulty/boundary_precision_check/weight_band_boundary_67_9_vs_68_0
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    _, dv_a = _donor_with_checked_in_visit(
        center, "DL-TX-0000A1", "Ann", "Adler", "1988-02-02", 67.9
    )
    set_clock("2026-09-01T09:30:00Z")
    a = get_success_data(api.check_in(dv_a["id"], TEST_USERS["phlebotomist_headers"]))
    assert a["programmed_volume_ml"] == 625, "67.9 kg is strictly below the 68.0 band edge"


def test_weight_band_boundary_68_0_programs_690(api):
    """PRD §3.4: "Boundaries are strictly greater-or-equal on the lower edge
    and strictly less-than on the upper edge: a donor weighing exactly 68.0 kg
    lands in the 690-mL band".

    Design: Difficulty/boundary_precision_check/weight_band_boundary_67_9_vs_68_0
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    _, dv_b = _donor_with_checked_in_visit(
        center, "DL-TX-0000B1", "Bob", "Baker", "1985-07-19", 68.0
    )
    set_clock("2026-09-01T09:30:00Z")
    b = get_success_data(api.check_in(dv_b["id"], TEST_USERS["phlebotomist_headers"]))
    assert b["programmed_volume_ml"] == 690, "exactly 68.0 kg is inclusively inside the second band"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check:
# observation_dwell_exactly_fifteen_minutes (2 tests)
# ---------------------------------------------------------------------------

def _observation_visit():
    """Donation visit in OBSERVATION; observation entered at 09:30:00."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api_client.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api_client.complete_collection(
            donation["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    return center, donor, donation


def test_observation_dwell_at_14m59s_rejected(api):
    """PRD §3.5: "Discharge is gated on dwell time: the logical clock must be
    at least fifteen minutes past the instant the visit entered `OBSERVATION`,
    failing which the call is rejected with `ERR_OBSERVATION_TOO_EARLY`."

    Design: Difficulty/boundary_precision_check/observation_dwell_exactly_fifteen_minutes
    """
    _, _, donation = _observation_visit()
    set_clock("2026-09-01T09:44:59Z")
    resp = api.discharge(donation["id"], TEST_USERS["phlebotomist_headers"])
    validate_error(resp, ApiErrorId.ERR_OBSERVATION_TOO_EARLY, 409)
    after = get_success_data(api.get_donation(donation["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "OBSERVATION", "no side effects fired"


def test_observation_dwell_at_exactly_15m_succeeds(api):
    """PRD §3.5: "the logical clock must be at least fifteen minutes past the
    instant the visit entered `OBSERVATION`" — the 15-minute edge is
    inclusive, so discharge at exactly entry+15:00 succeeds and moves the
    visit to COMPLETED.

    Design: Difficulty/boundary_precision_check/observation_dwell_exactly_fifteen_minutes
    """
    _, _, donation = _observation_visit()
    set_clock("2026-09-01T09:45:00Z")
    done = get_success_data(api.discharge(donation["id"], TEST_USERS["phlebotomist_headers"]))
    assert done["visit_status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check:
# actual_volume_zero_and_overrun_bounds (2 tests)
# ---------------------------------------------------------------------------

def test_actual_volume_zero_and_overrun_rejected(api):
    """PRD §3.5: "The reported volume must be strictly greater than 0 and at
    most `programmed_volume_ml`; anything outside that range is rejected with
    `ERR_INVALID_ACTUAL_VOLUME` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/actual_volume_zero_and_overrun_bounds
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    checked = get_success_data(api.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    assert checked["programmed_volume_ml"] == 690

    r_zero = api.complete_collection(
        donation["id"], {"actual_volume_ml": 0}, TEST_USERS["phlebotomist_headers"]
    )
    validate_error(r_zero, ApiErrorId.ERR_INVALID_ACTUAL_VOLUME, 422)

    r_over = api.complete_collection(
        donation["id"], {"actual_volume_ml": 691}, TEST_USERS["phlebotomist_headers"]
    )
    validate_error(r_over, ApiErrorId.ERR_INVALID_ACTUAL_VOLUME, 422)

    still = get_success_data(api.get_donation(donation["id"], TEST_USERS["admin_headers"]))
    assert still["visit_status"] == "IN_PROGRESS", "rejected attempts are side-effect free"


def test_actual_volume_exact_programmed_accepted(api):
    """PRD §3.5: "The reported volume must be strictly greater than 0 and at
    most `programmed_volume_ml`" — the exact upper edge (690 of 690) is
    accepted and the visit moves to OBSERVATION; the interval is (0,
    programmed].

    Design: Difficulty/boundary_precision_check/actual_volume_zero_and_overrun_bounds
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    obs = get_success_data(
        api.complete_collection(
            donation["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    assert obs["visit_status"] == "OBSERVATION"
    assert obs["actual_volume_ml"] == 690
