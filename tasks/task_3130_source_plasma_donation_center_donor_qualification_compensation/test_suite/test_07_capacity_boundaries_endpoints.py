"""Capacity slots, snapshots, frequency/gap/applicant boundaries, lookups."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_center_with_schedule,
    make_cleared_screening,
    make_donation,
    make_donor,
    make_screening,
    record_pass_sub_record,
    run_completed_donation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


def _registered_donor(center, ref, first, last, dob, weight=72.5):
    return make_donor(
        center, external_donor_ref=ref, legal_first_name=first,
        legal_last_name=last, date_of_birth=dob, weight_kg=weight,
    )


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap:
# donor_floor_bed_aggregate_capacity_and_reuse (2 tests)
# ---------------------------------------------------------------------------

def _one_bed_center_two_pending_donors():
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(
        center_overrides={"donor_floor_beds": 1, "observation_chairs": 2}
    )
    da = _registered_donor(center, "DL-TX-0000A1", "Ann", "Adler", "1988-02-02")
    db = _registered_donor(center, "DL-TX-0000B1", "Bob", "Baker", "1985-07-19")
    sa = make_cleared_screening(da, center, "2026-09-01T08:00:00Z", recorder_id="rec-01")
    sb = make_cleared_screening(db, center, "2026-09-01T08:00:00Z", recorder_id="rec-02")
    dva = make_donation(da, center, sa, "2026-09-01T09:30:00Z")
    dvb = make_donation(db, center, sb, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    return center, da, db, dva, dvb


def test_bed_capacity_exhausted_rejects_second_checkin(api):
    """PRD §3.4: "The center must have a free donor-floor bed at that
    instant, with `donor_floor_beds_in_use` strictly less than
    `donor_floor_beds` — equality rejects with `ERR_NO_BED_AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/donor_floor_bed_aggregate_capacity_and_reuse
    """
    center, da, db, dva, dvb = _one_bed_center_two_pending_donors()
    checked = get_success_data(api_client.check_in(dva["id"], TEST_USERS["phlebotomist_headers"]))
    assert checked["bed_index"] == 0, "first occupant takes the lowest slot"
    resp = api_client.check_in(dvb["id"], TEST_USERS["phlebotomist_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_BED_AVAILABLE, 409)


def test_bed_freed_by_collection_complete_and_reused(api):
    """PRD §2.12: "A bed is freed when its visit leaves `IN_PROGRESS`" and
    "the assigned index is the minimum of the free set" — after A's
    collection completes, B's retry reuses slot 0.

    Design: Difficulty/resource_temporal_overlap/donor_floor_bed_aggregate_capacity_and_reuse
    """
    center, da, db, dva, dvb = _one_bed_center_two_pending_donors()
    get_success_data(api_client.check_in(dva["id"], TEST_USERS["phlebotomist_headers"]))
    resp = api_client.check_in(dvb["id"], TEST_USERS["phlebotomist_headers"])
    assert resp.status_code == 409

    get_success_data(
        api_client.complete_collection(
            dva["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    checked_b = get_success_data(api_client.check_in(dvb["id"], TEST_USERS["phlebotomist_headers"]))
    assert checked_b["bed_index"] == 0, "freed slot reused at index 0"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap:
# screening_lane_half_open_interval_adjacency (2 tests)
# ---------------------------------------------------------------------------

def test_screening_lane_adjacent_windows_both_get_lane_zero(api):
    """PRD §2.12: "Screening lanes follow the same lowest-free rule with one
    refinement: the server assigns the lane whose current-shift intervals do
    not overlap the new visit". PRD §2.11 defines the screening load window
    as "the half-open interval that begins at `scheduled_for` and ends
    twenty-four hours later" — a window starting exactly when another ends
    does not overlap, so a single lane is reusable.

    Design: Difficulty/resource_temporal_overlap/screening_lane_half_open_interval_adjacency
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(center_overrides={"screening_lanes": 1})
    da = _registered_donor(center, "DL-TX-0000A1", "Ann", "Adler", "1988-02-02")
    db = _registered_donor(center, "DL-TX-0000B1", "Bob", "Baker", "1985-07-19")
    sa = make_screening(da, center, "2026-09-01T08:00:00Z")
    sb = make_screening(db, center, "2026-09-02T08:00:00Z")
    record_pass_sub_record(sa["id"], "IDENTITY", "rec-01")
    set_clock("2026-09-02T07:59:00Z")

    record_pass_sub_record(sb["id"], "IDENTITY", "rec-02")
    sa_after = get_success_data(api_client.get_screening(sa["id"], TEST_USERS["admin_headers"]))
    sb_after = get_success_data(api_client.get_screening(sb["id"], TEST_USERS["admin_headers"]))
    assert sa_after["visit_status"] == "IN_PROGRESS"
    assert sa_after["screening_lane_index"] == 0
    assert sb_after["visit_status"] == "IN_PROGRESS"
    assert sb_after["screening_lane_index"] == 0, "adjacent (gap 0) windows do not overlap"


def test_screening_lane_index_in_declared_range(api):
    """PRD §2.12: "The lane index lands in the range from 0 up to but not
    including the center's `screening_lanes`." With one lane, the only legal
    assignment is 0 for both adjacent (non-overlapping) windows.

    Design: Difficulty/resource_temporal_overlap/screening_lane_half_open_interval_adjacency
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(center_overrides={"screening_lanes": 1})
    da = _registered_donor(center, "DL-TX-0000A1", "Ann", "Adler", "1988-02-02")
    db = _registered_donor(center, "DL-TX-0000B1", "Bob", "Baker", "1985-07-19")
    sa = make_screening(da, center, "2026-09-01T08:00:00Z")
    sb = make_screening(db, center, "2026-09-02T08:00:00Z")
    record_pass_sub_record(sa["id"], "IDENTITY", "rec-01")
    set_clock("2026-09-02T07:59:00Z")
    record_pass_sub_record(sb["id"], "IDENTITY", "rec-02")
    for visit_id in (sa["id"], sb["id"]):
        v = get_success_data(api_client.get_screening(visit_id, TEST_USERS["admin_headers"]))
        assert 0 <= v["screening_lane_index"] < center["screening_lanes"]


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap:
# observation_chair_aggregate_capacity_and_reuse (2 tests)
# ---------------------------------------------------------------------------

def _one_chair_center_two_checked_in():
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(
        center_overrides={"donor_floor_beds": 2, "observation_chairs": 1}
    )
    da = _registered_donor(center, "DL-TX-0000A1", "Ann", "Adler", "1988-02-02")
    db = _registered_donor(center, "DL-TX-0000B1", "Bob", "Baker", "1985-07-19")
    sa = make_cleared_screening(da, center, "2026-09-01T08:00:00Z", recorder_id="rec-01")
    sb = make_cleared_screening(db, center, "2026-09-01T08:00:00Z", recorder_id="rec-02")
    dva = make_donation(da, center, sa, "2026-09-01T09:30:00Z")
    dvb = make_donation(db, center, sb, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api_client.check_in(dva["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(api_client.check_in(dvb["id"], TEST_USERS["phlebotomist_headers"]))
    return center, da, db, dva, dvb


def test_chair_capacity_exhausted_rejects_complete_collection(api):
    """PRD §3.5: "The center must have a free observation chair —
    `observation_chairs_in_use` strictly less than `observation_chairs` — or
    the call is rejected with `ERR_NO_OBSERVATION_CHAIR`."

    Design: Difficulty/resource_temporal_overlap/observation_chair_aggregate_capacity_and_reuse
    """
    center, da, db, dva, dvb = _one_chair_center_two_checked_in()
    obs_a = get_success_data(
        api_client.complete_collection(
            dva["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    assert obs_a["observation_chair_index"] == 0
    resp = api_client.complete_collection(
        dvb["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_NO_OBSERVATION_CHAIR, 409)
    b_after = get_success_data(api_client.get_donation(dvb["id"], TEST_USERS["admin_headers"]))
    assert b_after["visit_status"] == "IN_PROGRESS"


def test_chair_freed_by_discharge_and_reused(api):
    """PRD §2.12: "an observation chair is freed when its visit leaves
    `OBSERVATION`" — after A discharges, B's retried complete-collection
    reuses chair 0 and moves to OBSERVATION.

    Design: Difficulty/resource_temporal_overlap/observation_chair_aggregate_capacity_and_reuse
    """
    center, da, db, dva, dvb = _one_chair_center_two_checked_in()
    get_success_data(
        api_client.complete_collection(
            dva["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    resp = api_client.complete_collection(
        dvb["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
    )
    assert resp.status_code == 409

    set_clock("2026-09-01T09:45:00Z")
    get_success_data(api_client.discharge(dva["id"], TEST_USERS["phlebotomist_headers"]))
    obs_b = get_success_data(
        api_client.complete_collection(
            dvb["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    assert obs_b["visit_status"] == "OBSERVATION"
    assert obs_b["observation_chair_index"] == 0


# ---------------------------------------------------------------------------
# Corner/calculations: lowest_free_bed_reuses_middle_hole
# ---------------------------------------------------------------------------

def test_lowest_free_bed_reuses_middle_hole(api):
    """PRD §2.12: "For a pool of size N, the occupied set is the indexes
    currently held by visits in the relevant state; the free set is the
    complement; the assigned index is the minimum of the free set" and
    "Assignment never consults the entity `id`, and there is no tie-breaking
    on `created_at` because a minimum over a set is total."

    Design: Corner/calculations/lowest_free_bed_reuses_middle_hole
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(
        center_overrides={"donor_floor_beds": 3, "observation_chairs": 3}
    )
    donors = [
        _registered_donor(center, f"DL-TX-0000{r}1", first, last, dob)
        for r, first, last, dob in (
            ("A", "Ann", "Adler", "1988-02-02"),
            ("B", "Bob", "Baker", "1985-07-19"),
            ("C", "Cat", "Carr", "1992-11-30"),
            ("D", "Dan", "Dunn", "1995-01-01"),
        )
    ]
    dvs = []
    for i, donor in enumerate(donors):
        s = make_cleared_screening(
            donor, center, "2026-09-01T08:00:00Z", recorder_id=f"rec-0{i+1}"
        )
        dvs.append(make_donation(donor, center, s, "2026-09-01T09:30:00Z"))
    set_clock("2026-09-01T09:30:00Z")
    beds = []
    for dv in dvs[:3]:
        checked = get_success_data(api_client.check_in(dv["id"], TEST_USERS["phlebotomist_headers"]))
        beds.append(checked["bed_index"])
    assert beds == [0, 1, 2], "initial fill order"

    # B's collection completes: frees bed 1 (middle hole), takes a chair.
    get_success_data(
        api_client.complete_collection(
            dvs[1]["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    checked_d = get_success_data(api_client.check_in(dvs[3]["id"], TEST_USERS["phlebotomist_headers"]))
    assert checked_d["bed_index"] == 1, "D lands in the middle hole via min(free)"


# ---------------------------------------------------------------------------
# Corner/calculations: capacity_snapshot_trigger_events_and_counts
# ---------------------------------------------------------------------------

def test_capacity_snapshot_trigger_events_and_counts(api):
    """PRD §2.11: "`donor_floor_beds_in_use` counts DonationVisit rows at the
    center whose `visit_status` is `IN_PROGRESS`" and
    "`screening_lanes_in_use` counts ScreeningVisit rows at the center whose
    `visit_status` is `IN_PROGRESS` with the logical clock inside the
    half-open interval that begins at `scheduled_for` and ends twenty-four
    hours later"; a check-in writes a snapshot "with `trigger_event`
    `donation.check_in`". Snapshots are listed "newest first" (PRD §4).

    Design: Corner/calculations/capacity_snapshot_trigger_events_and_counts
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    # s1 stays IN_PROGRESS (one sub-record only).
    s1 = make_screening(donor, center, "2026-09-01T08:00:00Z")
    record_pass_sub_record(s1["id"], "IDENTITY", "rec-01")
    # s2 cleared and drives a donation to check-in.
    s2 = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z", recorder_id="rec-02")
    donation = make_donation(donor, center, s2, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api_client.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))

    snaps, meta = validate_paginated(
        api_client.list_capacity_snapshots(center["id"], TEST_USERS["admin_headers"])
    )
    newest = snaps[0]
    assert newest["trigger_event"] == "donation.check_in"
    assert newest["screening_lanes_in_use"] == 1, "s1 still IN_PROGRESS"
    assert newest["donor_floor_beds_in_use"] == 1
    assert newest["observation_chairs_in_use"] == 0
    assert newest["pending_releases_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant:
# capacity_slot_conservation_across_abort_and_discharge (2 tests)
# ---------------------------------------------------------------------------

def _capacity_conservation_scenario():
    """2 beds / 1 chair; A and B checked in; A completed collection (chair 0).
    Then A aborts in OBSERVATION (frees chair), B completes (chair 0), B
    discharges."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(
        center_overrides={"donor_floor_beds": 2, "observation_chairs": 1}
    )
    da = _registered_donor(center, "DL-TX-0000A1", "Ann", "Adler", "1988-02-02")
    db = _registered_donor(center, "DL-TX-0000B1", "Bob", "Baker", "1985-07-19")
    sa = make_cleared_screening(da, center, "2026-09-01T08:00:00Z", recorder_id="rec-01")
    sb = make_cleared_screening(db, center, "2026-09-01T08:00:00Z", recorder_id="rec-02")
    dva = make_donation(da, center, sa, "2026-09-01T09:30:00Z")
    dvb = make_donation(db, center, sb, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api_client.check_in(dva["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(api_client.check_in(dvb["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api_client.complete_collection(
            dva["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    return center, da, db, dva, dvb


def test_abort_frees_both_slots_for_reuse(api):
    """PRD §3.9: "The bed is freed (when the reaction occurred in
    `IN_PROGRESS`) and the observation chair is freed (when it occurred in
    `OBSERVATION`)." A's abort in OBSERVATION frees chair 0, so B's
    complete-collection lands chair 0.

    Design: Difficulty/compensating_invariant/capacity_slot_conservation_across_abort_and_discharge
    """
    center, da, db, dva, dvb = _capacity_conservation_scenario()
    get_success_data(
        api_client.record_adverse_reaction(
            dva["id"],
            {
                "severity": "MILD",
                "reaction_code": "VASOVAGAL",
                "observed_at": "2026-09-01T09:30:00Z",
                "notes": "lightheaded in observation chair",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    obs_b = get_success_data(
        api_client.complete_collection(
            dvb["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    assert obs_b["observation_chair_index"] == 0, "B reuses the freed chair"


def test_capacity_snapshot_conserved_after_abort_and_discharge(api):
    """PRD §2.11: "`donor_floor_beds_in_use` counts DonationVisit rows at the
    center whose `visit_status` is `IN_PROGRESS`. `observation_chairs_in_use`
    counts DonationVisit rows at the center whose `visit_status` is
    `OBSERVATION`. `pending_releases_count` counts DonationUnit rows at the
    center whose `unit_status` is `QUARANTINED`." PRD §2.11 also requires
    every load-changing mutation to write a snapshot with a `trigger_event`
    label such as `donation.completed`. After abort + discharge the newest
    snapshot shows 0 beds and 0 chairs in use and 2 pending quarantined
    units.

    Design: Difficulty/compensating_invariant/capacity_slot_conservation_across_abort_and_discharge
    """
    center, da, db, dva, dvb = _capacity_conservation_scenario()
    get_success_data(
        api_client.record_adverse_reaction(
            dva["id"],
            {
                "severity": "MILD",
                "reaction_code": "VASOVAGAL",
                "observed_at": "2026-09-01T09:30:00Z",
                "notes": "lightheaded in observation chair",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    get_success_data(
        api_client.complete_collection(
            dvb["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    set_clock("2026-09-01T09:51:00Z")
    get_success_data(api_client.discharge(dvb["id"], TEST_USERS["phlebotomist_headers"]))

    snaps, _ = validate_paginated(
        api_client.list_capacity_snapshots(center["id"], TEST_USERS["admin_headers"])
    )
    newest = snaps[0]
    assert newest["trigger_event"] == "donation.completed"
    assert newest["donor_floor_beds_in_use"] == 0, "slots conserved, none leaked"
    assert newest["observation_chairs_in_use"] == 0
    assert newest["pending_releases_count"] == 2, (
        "A's partial unit from the OBSERVATION abort plus B's full unit"
    )


# ---------------------------------------------------------------------------
# Corner/calculations: frequency window and inter-donation gap
# ---------------------------------------------------------------------------

def _donor_with_two_completions_and_third_pending():
    """Completions at 2026-09-01T09:46 and 2026-09-04T09:46; dv3 scheduled
    for 2026-09-08T09:30 against a cleared third screening."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-01T08:00:00Z",
        checkin_time="2026-09-01T09:30:00Z",
        discharge_time="2026-09-01T09:46:00Z",
    )
    set_clock("2026-09-04T09:00:00Z")
    run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-04T08:00:00Z",
        checkin_time="2026-09-04T09:30:00Z",
        discharge_time="2026-09-04T09:46:00Z",
    )
    set_clock("2026-09-07T09:00:00Z")
    s3 = make_cleared_screening(donor, center, "2026-09-07T08:00:00Z")
    dv3 = make_donation(donor, center, s3, "2026-09-08T09:30:00Z")
    return center, donor, dv3


def test_rolling_frequency_window_inclusive_lower_edge_blocks(api):
    """PRD §3.4: "the boundary at exactly seven days ago is inclusive (a
    completion exactly one hundred sixty-eight hours in the past does count).
    When that count is at least 2, the check-in is rejected with
    `ERR_FREQUENCY_LIMIT_EXCEEDED`."

    Design: Corner/calculations/rolling_frequency_window_inclusive_lower_edge
    """
    center, donor, dv3 = _donor_with_two_completions_and_third_pending()
    # Exactly 7*24h after the first completion: it still counts (2 in window).
    set_clock("2026-09-08T09:46:00Z")
    resp = api_client.check_in(dv3["id"], TEST_USERS["phlebotomist_headers"])
    validate_error(resp, ApiErrorId.ERR_FREQUENCY_LIMIT_EXCEEDED, 409)


def test_rolling_frequency_window_one_second_later_passes(api):
    """PRD §3.4: "This is a rolling window rather than a calendar-week
    bucket: a donation six days and twenty-three hours ago still counts; a
    donation seven days and one second ago does not." One second past the
    inclusive lower edge the first completion ages out and the check-in
    succeeds.

    Design: Corner/calculations/rolling_frequency_window_inclusive_lower_edge
    """
    center, donor, dv3 = _donor_with_two_completions_and_third_pending()
    set_clock("2026-09-08T09:46:01Z")
    checked = get_success_data(api_client.check_in(dv3["id"], TEST_USERS["phlebotomist_headers"]))
    assert checked["visit_status"] == "IN_PROGRESS"


def test_inter_donation_gap_exactly_48h_boundary(api):
    """PRD §3.4: "When fewer than 48 hours have elapsed between that
    completion and the present instant, the check-in is rejected with
    `ERR_INTER_DONATION_GAP_VIOLATION`. The boundary is inclusive on the pass
    side: a gap of exactly 48 hours passes; a gap one second shorter fails."

    Design: Corner/calculations/inter_donation_gap_exactly_48h_boundary
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-01T08:00:00Z",
        checkin_time="2026-09-01T09:30:00Z",
        discharge_time="2026-09-01T09:46:00Z",
    )
    set_clock("2026-09-03T09:00:00Z")
    s2 = make_cleared_screening(donor, center, "2026-09-03T08:00:00Z")
    dv2 = make_donation(donor, center, s2, "2026-09-03T09:30:00Z")

    # 47h59m59s after the 09-01T09:46 completion.
    set_clock("2026-09-03T09:45:59Z")
    resp = api_client.check_in(dv2["id"], TEST_USERS["phlebotomist_headers"])
    validate_error(resp, ApiErrorId.ERR_INTER_DONATION_GAP_VIOLATION, 409)

    # Exactly 48h00m00s.
    set_clock("2026-09-03T09:46:00Z")
    checked = get_success_data(api_client.check_in(dv2["id"], TEST_USERS["phlebotomist_headers"]))
    assert checked["visit_status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Corner/calculations: applicant window boundary and restart
# ---------------------------------------------------------------------------

def _setup_applicant_window_pair():
    """Two donors whose first completions both stamp 2026-09-01T09:46 and
    whose second donations are scheduled for 2027-02-28T09:30 against cleared
    screenings. Schedule window covers both years."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(
        effective_from="2026-08-01T00:00:00Z", effective_to="2027-06-01T00:00:00Z",
    )
    da = _registered_donor(center, "DL-TX-0000A1", "Ann", "Adler", "1988-02-02")
    db = _registered_donor(center, "DL-TX-0000B1", "Bob", "Baker", "1985-07-19")
    for donor in (da, db):
        run_completed_donation(
            donor, center,
            screening_scheduled_for="2026-09-01T08:00:00Z",
            checkin_time="2026-09-01T09:30:00Z",
            discharge_time="2026-09-01T09:46:00Z",
            recorder_id="rec-01" if donor is da else "rec-02",
        )
    set_clock("2027-02-28T09:00:00Z")
    sa2 = make_cleared_screening(da, center, "2027-02-28T08:00:00Z", recorder_id="rec-01")
    dva2 = make_donation(da, center, sa2, "2027-02-28T09:30:00Z")
    sb2 = make_cleared_screening(db, center, "2027-02-28T08:00:00Z", recorder_id="rec-02")
    dvb2 = make_donation(db, center, sb2, "2027-02-28T09:30:00Z")
    return center, da, db, dva2, dvb2


def test_applicant_window_exactly_180_days_promotes(api):
    """PRD §3.7: "the donor is promoted to `QUALIFIED`. The boundary is
    inclusive: a second completion at exactly 180 days after the first
    passes; one second later fails." The PRD §3.7 sentence runs in full: "If,
    after this completion, the donor is still `APPLICANT` **and** the donor's
    lifetime completion count is at least 2 **and** the elapsed time between
    `applicant_window_started_on` and the current instant is at most 180 days
    (that is, 180 times 24 hours), the donor is promoted to `QUALIFIED`."
    First completion 2026-09-01T09:46:00Z + 180 days = 2027-02-28T09:46:00Z
    exactly.

    Design: Corner/calculations/applicant_window_exactly_180_days_boundary_and_restart
    """
    center, da, db, dva2, dvb2 = _setup_applicant_window_pair()
    set_clock("2027-02-28T09:30:00Z")
    get_success_data(api_client.check_in(dva2["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(api_client.check_in(dvb2["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api_client.complete_collection(dva2["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"])
    )
    get_success_data(
        api_client.complete_collection(dvb2["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"])
    )
    set_clock("2027-02-28T09:46:00Z")
    get_success_data(api_client.discharge(dva2["id"], TEST_USERS["phlebotomist_headers"]))
    d = get_success_data(api_client.get_donor(da["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "QUALIFIED", "inclusive upper edge at exactly 180 days"


def test_applicant_window_one_second_past_resets_window(api):
    """PRD §3.7: "If instead the second completion arrives more than 180 days
    after the first, the donor **remains** `APPLICANT`. The applicant window
    has lapsed. On the completion that outlasts the window, the donor's
    `applicant_window_started_on` is **reset** to the current completion's
    timestamp".

    Design: Corner/calculations/applicant_window_exactly_180_days_boundary_and_restart
    """
    center, da, db, dva2, dvb2 = _setup_applicant_window_pair()
    set_clock("2027-02-28T09:30:00Z")
    get_success_data(api_client.check_in(dvb2["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api_client.complete_collection(dvb2["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"])
    )
    set_clock("2027-02-28T09:46:01Z")
    get_success_data(api_client.discharge(dvb2["id"], TEST_USERS["phlebotomist_headers"]))
    d = get_success_data(api_client.get_donor(db["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "APPLICANT", "one second past the edge fails"
    assert d["applicant_window_started_on"] == "2027-02-28T09:46:01.000Z", (
        "window restarted at this completion's collected_at"
    )


# ---------------------------------------------------------------------------
# Corner/endpoints and Corner/consistency_model
# ---------------------------------------------------------------------------

def test_compensation_payment_endpoint_array_zero_then_one(api):
    """PRD §4: "Get the
    compensation payment for a visit (array of 0 or 1)" for endpoint GET
    /donation-visits/{visitId}/compensation-payment. PRD §3.4: "Check-in
    also creates the visit's **CompensationPayment** and stores its id on
    the visit as `compensation_payment_id`. The payment is created in the
    `PROVISIONAL` variant with `payment_status` `PROVISIONAL`".

    Design: Corner/endpoints/compensation_payment_endpoint_array_zero_then_one
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")

    data0, meta0 = validate_paginated(
        api_client.get_payment_for_visit(donation["id"], TEST_USERS["admin_headers"])
    )
    assert data0 == [] and meta0["total_count"] == 0

    get_success_data(api_client.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    data1, meta1 = validate_paginated(
        api_client.get_payment_for_visit(donation["id"], TEST_USERS["admin_headers"])
    )
    assert meta1["total_count"] == 1
    assert data1[0]["payment_status"] == "PROVISIONAL"
    assert data1[0]["variant"] == "PROVISIONAL"
    assert data1[0]["base_cents"] == 3000


def test_fk_reverse_reachability_lists(api):
    """PRD §4 defines the reverse-lookup list endpoints used here:
    "List screening visits for a donor" (GET
    /donors/{donorId}/screening-visits), "List deferral entries for a donor"
    (GET /donors/{donorId}/deferrals), "List donation units (optional
    `donor_id`, `center_id`, `unit_status` filters)" (GET /donation-units),
    "List donation visits for a donor" (GET
    /donors/{donorId}/donation-visits), and "List sub-records for a screening
    visit" (GET /screening-visits/{visitId}/sub-records).

    Design: Corner/endpoints/fk_reverse_reachability_lists
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    dv = run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-01T08:00:00Z",
        checkin_time="2026-09-01T09:30:00Z",
        discharge_time="2026-09-01T09:46:00Z",
    )
    get_success_data(
        api_client.file_deferral(
            donor["id"],
            {
                "reason_code": "LOW_HEMATOCRIT",
                "deferral_type": "TEMPORARY",
                "deferral_ends_on": "2026-09-20T00:00:00Z",
            },
            TEST_USERS["compliance_headers"],
        )
    )
    svs, meta_sv = validate_paginated(
        api_client.list_screenings(donor["id"], TEST_USERS["admin_headers"])
    )
    assert meta_sv["total_count"] == 1
    assert svs[0]["donor_id"] == donor["id"]

    dfs, meta_df = validate_paginated(
        api_client.list_deferrals(donor["id"], TEST_USERS["admin_headers"])
    )
    assert meta_df["total_count"] == 1
    assert dfs[0]["reason_code"] == "LOW_HEMATOCRIT"

    units, meta_u = validate_paginated(
        api_client.list_units(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    assert meta_u["total_count"] == 1
    assert units[0]["unit_status"] == "QUARANTINED"

    dvs, meta_dv = validate_paginated(
        api_client.list_donations(donor["id"], TEST_USERS["admin_headers"])
    )
    assert meta_dv["total_count"] == 1
    assert dvs[0]["visit_status"] == "COMPLETED"

    subs, meta_sub = validate_paginated(
        api_client.list_sub_records(dv["screening_visit_id"], TEST_USERS["admin_headers"])
    )
    assert meta_sub["total_count"] == 4


def test_adverse_reaction_list_endpoint_returns_created_row(api):
    """PRD §3.9: "An AdverseReaction row is created" carrying the posted
    `severity`, `reaction_code`, `observed_at` and `notes`; PRD §4: PRD §4 lists GET
    /donation-visits/{visitId}/adverse-reactions as "List adverse reactions for
    a visit".

    Design: Corner/endpoints/adverse_reaction_list_endpoint_returns_created_row
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api_client.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api_client.record_adverse_reaction(
            donation["id"],
            {
                "severity": "MODERATE",
                "reaction_code": "CITRATE",
                "observed_at": "2026-09-01T09:30:00Z",
                "notes": "perioral tingling mid-collection",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    rows, meta = validate_paginated(
        api_client.list_adverse_reactions(donation["id"], TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["severity"] == "MODERATE"
    assert rows[0]["reaction_code"] == "CITRATE"
    assert rows[0]["notes"] == "perioral tingling mid-collection"


def test_immediate_consistency_read_after_write(api):
    """PRD §3.5: "A successful discharge moves the visit to `COMPLETED`, frees
    the observation chair, and fires a cascade of side effects that the next
    three subsections unpack: the unit is created and quarantined,
    compensation is finalized, the donor's counters and status are updated" — the discharge response already
    shows COMPLETED, and an immediate re-read of the visit, the payment, and
    the donor reflect the unit creation, the FINALIZED payment, and the
    incremented lifetime count.

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
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
    set_clock("2026-09-01T09:46:00Z")
    done = get_success_data(api_client.discharge(donation["id"], TEST_USERS["phlebotomist_headers"]))
    assert done["visit_status"] == "COMPLETED"

    reread = get_success_data(api_client.get_donation(donation["id"], TEST_USERS["admin_headers"]))
    assert reread["visit_status"] == "COMPLETED", "response and re-read agree immediately"
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["lifetime_donation_count"] == 1
    assert d["ytd_compensation_cents"] == 3000
    units, meta_u = validate_paginated(
        api_client.list_units(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    assert meta_u["total_count"] == 1
    assert units[0]["unit_status"] == "QUARANTINED"


def test_platform_admin_cannot_release_unit(api):
    """PRD §4: PRD §4 lists POST
    /donation-units/{unitId}/release with ComplianceOfficer as its only
    authorized role, so even the PlatformAdmin is denied.
    PRD §2.1: "An attempt to perform an action outside of the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/platform_admin_cannot_release_unit
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-01T08:00:00Z",
        checkin_time="2026-09-01T09:30:00Z",
        discharge_time="2026-09-01T09:46:00Z",
    )
    units, meta = validate_paginated(
        api_client.list_units(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    assert meta["total_count"] == 1
    resp = api_client.release_unit(units[0]["id"], TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
