"""Center lifecycle: inspection holds, decommission, OCC, capacity and slots."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_center,
    make_center_with_schedule,
    make_cleared_screening,
    make_donation,
    make_donor,
    make_schedule,
    make_screening,
    record_pass_sub_record,
    run_completed_donation,
    set_clock,
    setup_qualified_donor_with_released_units,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_schedule_payload


def _donor_with_donation(center):
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    return donor, screening, donation


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine:
# center_inspection_hold_cycle_with_visit_cascades (2 tests)
# ---------------------------------------------------------------------------

def _hold_scenario():
    """Center with donor; s1 left SCHEDULED; s2 CLEARED; dv SCHEDULED on s2."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    s1 = make_screening(donor, center, "2026-09-02T08:00:00Z")
    s2 = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    dv = make_donation(donor, center, s2, "2026-09-01T10:00:00Z")
    center = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    return center, donor, s1, s2, dv


def test_inspection_hold_outbound_leg_cascades(api):
    """PRD §3.11: "A successful hold transitions the center to
    `INSPECTION_HOLD`, increments its `version` by 1, and cascades the
    pipeline: every DonationVisit at the center still in `SCHEDULED` is moved
    to `NO_SHOW` (its `scheduled_for` is left unchanged, and its
    CompensationPayment if any stays `PROVISIONAL`), and every ScreeningVisit
    at the center still in `SCHEDULED` is moved to `EXPIRED`."

    Design: Difficulty/non_linear_state_machine/center_inspection_hold_cycle_with_visit_cascades
    """
    center, donor, s1, s2, dv = _hold_scenario()
    v_before = center["version"]
    resp = api_client.place_inspection_hold(
        center["id"],
        {"expected_center_version": v_before, "reason": "unannounced state inspection"},
        TEST_USERS["compliance_headers"],
    )
    held = validate_success(resp, 200)
    assert held["status"] == "INSPECTION_HOLD"
    assert held["version"] == v_before + 1

    dv_after = get_success_data(api_client.get_donation(dv["id"], TEST_USERS["admin_headers"]))
    assert dv_after["visit_status"] == "NO_SHOW"
    s1_after = get_success_data(api_client.get_screening(s1["id"], TEST_USERS["admin_headers"]))
    assert s1_after["visit_status"] == "EXPIRED"
    s2_after = get_success_data(api_client.get_screening(s2["id"], TEST_USERS["admin_headers"]))
    assert s2_after["visit_status"] == "CLEARED", "a CLEARED screening survives the hold"


def test_inspection_hold_cycle_returns_to_operational(api):
    """PRD §3.11: "A successful clear returns the center to `OPERATIONAL`,
    increments its `version`, and writes a snapshot with `trigger_event`
    `center.inspection_hold_cleared`."

    Design: Difficulty/non_linear_state_machine/center_inspection_hold_cycle_with_visit_cascades
    """
    center, donor, s1, s2, dv = _hold_scenario()
    held = get_success_data(
        api_client.place_inspection_hold(
            center["id"],
            {"expected_center_version": center["version"], "reason": "state inspection"},
            TEST_USERS["compliance_headers"],
        )
    )
    resp = api_client.clear_inspection_hold(
        center["id"],
        {"expected_center_version": held["version"]},
        TEST_USERS["compliance_headers"],
    )
    cleared = validate_success(resp, 200)
    assert cleared["status"] == "OPERATIONAL"
    assert cleared["version"] == held["version"] + 1


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency:
# donation_scheduling_gated_by_center_hold (2 tests)
# ---------------------------------------------------------------------------

def test_donation_scheduling_blocked_under_inspection_hold(api):
    """PRD §3.11: "For as long as the hold is active, every visit-pipeline
    write at the center — sub-record posting, screening clearance, donation
    scheduling, check-in, complete-collection, discharge, adverse-reaction
    recording, schedule creation — is rejected with
    `ERR_CENTER_NOT_OPERATIONAL`."

    Design: Difficulty/cross_entity_state_dependency/donation_scheduling_gated_by_center_hold
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    center = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    held = get_success_data(
        api_client.place_inspection_hold(
            center["id"],
            {"expected_center_version": center["version"], "reason": "state inspector on site"},
            TEST_USERS["compliance_headers"],
        )
    )
    resp = api_client.schedule_donation(
        donor["id"],
        {
            "center_id": center["id"],
            "screening_visit_id": screening["id"],
            "scheduled_for": "2026-09-02T10:00:00Z",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CENTER_NOT_OPERATIONAL, 409)


def test_donation_scheduling_succeeds_after_hold_cleared(api):
    """PRD §3.11: "A successful clear returns the center to `OPERATIONAL`" —
    after the hold is cleared the identical donation-scheduling request
    succeeds and the visit starts in `SCHEDULED`.
    PRD §3.4: "The visit begins life in `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/donation_scheduling_gated_by_center_hold
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    center = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    held = get_success_data(
        api_client.place_inspection_hold(
            center["id"],
            {"expected_center_version": center["version"], "reason": "state inspector on site"},
            TEST_USERS["compliance_headers"],
        )
    )
    blocked = api_client.schedule_donation(
        donor["id"],
        {
            "center_id": center["id"],
            "screening_visit_id": screening["id"],
            "scheduled_for": "2026-09-02T10:00:00Z",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    assert blocked.status_code == 409

    get_success_data(
        api_client.clear_inspection_hold(
            center["id"],
            {"expected_center_version": held["version"]},
            TEST_USERS["compliance_headers"],
        )
    )
    resp = api_client.schedule_donation(
        donor["id"],
        {
            "center_id": center["id"],
            "screening_visit_id": screening["id"],
            "scheduled_for": "2026-09-02T10:00:00Z",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    donation = validate_success(resp, 201)
    assert donation["visit_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict:
# checkin_state_beats_fiscal_when_schedule_retired (2 tests)
# ---------------------------------------------------------------------------

def _checked_in_then_schedule_retired():
    """Donation checked in; its pinned schedule retired afterwards. Returns
    (center, schedule, donor, donation)."""
    set_clock("2026-09-01T09:00:00Z")
    center, schedule = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api_client.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api_client.retire_schedule(
            schedule["id"],
            {"expected_schedule_version": schedule["version"]},
            TEST_USERS["admin_headers"],
        )
    )
    return center, schedule, donor, donation


def test_double_checkin_reports_state_error_not_fiscal(api):
    """PRD §3.4: "A visit that is not `SCHEDULED` is rejected with
    `ERR_VISIT_NOT_SCHEDULED`." PRD §2.9: "the server evaluates them in the
    following fixed priority order and reports the **first** rule that fails"
    — state-machine applicability (item 6) precedes "Active compensation
    schedule covering the check-in instant → `ERR_NO_ACTIVE_COMP_SCHEDULE`"
    (item 17).

    Design: Difficulty/priority_pair_validation_conflict/checkin_state_beats_fiscal_when_schedule_retired
    """
    _, _, _, donation = _checked_in_then_schedule_retired()
    resp = api_client.check_in(donation["id"], TEST_USERS["phlebotomist_headers"])
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_SCHEDULED, 409)


def test_double_checkin_after_schedule_retire_is_side_effect_free(api):
    """PRD §3.4: "A visit that is not `SCHEDULED` is rejected with
    `ERR_VISIT_NOT_SCHEDULED`." The rejected second check-in leaves the visit
    IN_PROGRESS; PRD §2.9 fixes state applicability (item 6) ahead of the
    fiscal schedule rule (item 17) even though the pinned schedule was
    retired.

    Design: Difficulty/priority_pair_validation_conflict/checkin_state_beats_fiscal_when_schedule_retired
    """
    _, _, _, donation = _checked_in_then_schedule_retired()
    resp = api_client.check_in(donation["id"], TEST_USERS["phlebotomist_headers"])
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == "ERR_VISIT_NOT_SCHEDULED"
    after = get_success_data(api_client.get_donation(donation["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict:
# schedule_donation_safety_beats_referential (2 tests)
# ---------------------------------------------------------------------------

def _deferred_donor_with_pending_screening():
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_screening(donor, center, "2026-09-02T08:00:00Z")
    get_success_data(
        api_client.file_deferral(
            donor["id"],
            {
                "reason_code": "TRAVEL_MALARIA",
                "deferral_type": "TEMPORARY",
                "deferral_ends_on": "2026-09-20T00:00:00Z",
            },
            TEST_USERS["compliance_headers"],
        )
    )
    return center, donor, screening


def test_schedule_donation_deferred_donor_reports_safety_error(api):
    """PRD §3.4: "A donor who is `DEFERRED_TEMP` or `DEFERRED_PERM` cannot
    schedule at all and is rejected under the donor-eligibility rule with
    `ERR_DONOR_NOT_ELIGIBLE`." PRD §2.9: item 8 "Donor eligibility by status
    → `ERR_DONOR_NOT_ELIGIBLE`." precedes item 13 "Screening clearance,
    ownership, and consumption → `ERR_SCREENING_NOT_CLEARED`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_donation_safety_beats_referential
    """
    center, donor, screening = _deferred_donor_with_pending_screening()
    resp = api_client.schedule_donation(
        donor["id"],
        {
            "center_id": center["id"],
            "screening_visit_id": screening["id"],
            "scheduled_for": "2026-09-02T10:00:00Z",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DONOR_NOT_ELIGIBLE, 409)


def test_schedule_donation_deferred_donor_creates_nothing(api):
    """PRD §3.4: "A donor who is `DEFERRED_TEMP` or `DEFERRED_PERM` cannot
    schedule at all and is rejected under the donor-eligibility rule with
    `ERR_DONOR_NOT_ELIGIBLE`." — with the screening also still SCHEDULED, the
    safety error (PRD §2.9 item 8) wins over the referential error (item 13)
    and no DonationVisit is created.

    Design: Difficulty/priority_pair_validation_conflict/schedule_donation_safety_beats_referential
    """
    center, donor, screening = _deferred_donor_with_pending_screening()
    resp = api_client.schedule_donation(
        donor["id"],
        {
            "center_id": center["id"],
            "screening_visit_id": screening["id"],
            "scheduled_for": "2026-09-02T10:00:00Z",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == "ERR_DONOR_NOT_ELIGIBLE"
    _, meta = validate_paginated(
        api_client.list_donations(donor["id"], TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Corner/cross_cutting: OCC family
# ---------------------------------------------------------------------------

def test_occ_schedule_create_stale_center_version(api):
    """PRD §2.7: "matched against the current `version`
    of the parent PlasmaCenter. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_schedule_create_stale_center_version
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    v1 = center["version"]
    make_schedule(center)  # bumps center version via side effect
    resp = api_client.create_schedule(
        center["id"],
        create_schedule_payload(
            v1,
            effective_from="2026-10-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
            base_cents_first_donation=3200,
            base_cents_second_donation=2600,
            base_cents_subsequent_donation=2100,
        ),
        TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    _, meta = validate_paginated(
        api_client.list_schedules(center["id"], TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 1, "the rejected create left no row"


def test_occ_inspection_hold_stale_center_version(api):
    """PRD §2.7: "matched against the current `version` of the
    PlasmaCenter being held. A mismatch is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_inspection_hold_stale_center_version
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    v1 = center["version"]
    make_schedule(center)  # center now at v1+1
    resp = api_client.place_inspection_hold(
        center["id"],
        {"expected_center_version": v1, "reason": "stale hold attempt"},
        TEST_USERS["compliance_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    fresh = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    assert fresh["status"] == "OPERATIONAL"

    resp = api_client.place_inspection_hold(
        center["id"],
        {"expected_center_version": fresh["version"], "reason": "fresh hold attempt"},
        TEST_USERS["compliance_headers"],
    )
    held = validate_success(resp, 200)
    assert held["status"] == "INSPECTION_HOLD"


def test_occ_schedule_retire_stale_version(api):
    """PRD §2.7: "matched against the schedule's current
    `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    and "The check is performed **before** any business-rule evaluation".

    Design: Corner/cross_cutting_complexity_layers/occ_schedule_retire_stale_version
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    s1 = make_schedule(center)
    center = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    # S2 supersedes S1, bumping S1's version via the supersede side effect.
    make_schedule(
        center,
        effective_from="2026-10-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
        base_cents_first_donation=3200,
        base_cents_second_donation=2600,
        base_cents_subsequent_donation=2100,
    )
    resp = api_client.retire_schedule(
        s1["id"],
        {"expected_schedule_version": s1["version"]},
        TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    s1_after = get_success_data(api_client.get_schedule(s1["id"], TEST_USERS["admin_headers"]))
    assert s1_after["schedule_status"] == "SUPERSEDED"
    assert s1_after["version"] == s1["version"] + 1, "only the supersede bumped it"


# ---------------------------------------------------------------------------
# Corner/state_machines: schedule lifecycle
# ---------------------------------------------------------------------------

def test_schedule_supersede_rewrites_prior_window(api):
    """PRD §3.1: "Creating a new schedule whose `effective_from` precedes the
    current `ACTIVE` schedule's `effective_to` causes the prior schedule to
    auto-supersede: its `schedule_status` transitions to `SUPERSEDED`, its
    `effective_to` is rewritten to the new schedule's `effective_from`, its
    `version` increments by 1, and the new schedule is created in `ACTIVE`
    status. The new-schedule creation also bumps the parent center's `version`
    by 1 as a side effect."

    Design: Corner/state_machines/schedule_supersede_rewrites_prior_window
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    cv1 = center["version"]
    s1 = make_schedule(center)
    center = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    cv2 = center["version"]
    assert cv2 == cv1 + 1

    s2 = get_success_data(
        api_client.create_schedule(
            center["id"],
            create_schedule_payload(
                cv2,
                effective_from="2026-10-01T00:00:00Z",
                effective_to="2027-03-01T00:00:00Z",
                base_cents_first_donation=3200,
                base_cents_second_donation=2600,
                base_cents_subsequent_donation=2100,
            ),
            TEST_USERS["admin_headers"],
        )
    )
    assert s2["schedule_status"] == "ACTIVE"
    s1_after = get_success_data(api_client.get_schedule(s1["id"], TEST_USERS["admin_headers"]))
    assert s1_after["schedule_status"] == "SUPERSEDED"
    assert s1_after["effective_to"] == "2026-10-01T00:00:00.000Z"
    assert s1_after["version"] == s1["version"] + 1
    center = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    assert center["version"] == cv2 + 1


def test_schedule_retire_then_checkin_fails_and_double_retire(api):
    """PRD §3.1: "A successful retirement moves `schedule_status` to
    `RETIRED` and increments the schedule's `version`. From that instant,
    future check-ins at the center fail with `ERR_NO_ACTIVE_COMP_SCHEDULE`
    until a replacement schedule is created" and "attempting to retire a
    schedule that is not currently `ACTIVE` is rejected with
    `ERR_SCHEDULE_NOT_ACTIVE`."

    Design: Corner/state_machines/schedule_retire_then_checkin_fails_and_double_retire
    """
    set_clock("2026-09-01T09:00:00Z")
    center, schedule = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")

    resp = api_client.retire_schedule(
        schedule["id"],
        {"expected_schedule_version": schedule["version"]},
        TEST_USERS["admin_headers"],
    )
    retired = validate_success(resp, 200)
    assert retired["schedule_status"] == "RETIRED"

    r1 = api_client.check_in(donation["id"], TEST_USERS["phlebotomist_headers"])
    validate_error(r1, ApiErrorId.ERR_NO_ACTIVE_COMP_SCHEDULE, 409)

    r2 = api_client.retire_schedule(
        schedule["id"],
        {"expected_schedule_version": retired["version"]},
        TEST_USERS["admin_headers"],
    )
    validate_error(r2, ApiErrorId.ERR_SCHEDULE_NOT_ACTIVE, 409)


# ---------------------------------------------------------------------------
# Corner/state_machines: decommission / clear-hold edge cases
# ---------------------------------------------------------------------------

def test_center_decommission_blocked_by_active_visits(api):
    """PRD §3.11: decommission is rejected "with
    `ERR_CENTER_HAS_ACTIVE_VISITS` when any DonationVisit at the center is
    `SCHEDULED`, `IN_PROGRESS`, or `OBSERVATION`, or any ScreeningVisit at
    the center is `SCHEDULED` or `IN_PROGRESS`."

    Design: Corner/state_machines/center_decommission_blocked_by_active_visits
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor, _, donation = _donor_with_donation(center)
    get_success_data(api_client.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    center = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    resp = api_client.decommission_center(
        center["id"],
        {"expected_center_version": center["version"]},
        TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CENTER_HAS_ACTIVE_VISITS, 409)
    after = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    assert after["status"] == "OPERATIONAL"


def test_clear_hold_when_not_on_hold_rejected(api):
    """PRD §2.10: "Attempting to clear a hold on a center that is not
    currently on hold is rejected with `ERR_CENTER_NOT_ON_HOLD`."

    Design: Corner/state_machines/clear_hold_when_not_on_hold_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    resp = api_client.clear_inspection_hold(
        center["id"],
        {"expected_center_version": center["version"]},
        TEST_USERS["compliance_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CENTER_NOT_ON_HOLD, 409)


def test_decommissioned_center_blocks_new_screening(api):
    """PRD §3.11: "A successful decommission transitions the center to
    `DECOMMISSIONED` (a terminal state), increments its `version`, and
    destroys every `QUARANTINED` unit at the center with
    `destruction_reason` `EXPIRED_HOLD`. From that point every write
    against the center is rejected." PRD §2.9 item 7: "Center operational
    status (an inspection hold blocks all visit-pipeline writes at the center;
    a decommissioned center blocks everything) → `ERR_CENTER_NOT_OPERATIONAL`."

    Design: Corner/state_machines/decommissioned_center_blocks_new_screening
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    get_success_data(
        api_client.decommission_center(
            center["id"],
            {"expected_center_version": center["version"]},
            TEST_USERS["admin_headers"],
        )
    )
    resp = api_client.schedule_screening(
        donor["id"],
        {"center_id": center["id"], "scheduled_for": "2026-09-02T08:00:00Z"},
        TEST_USERS["recorder_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CENTER_NOT_OPERATIONAL, 409)


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant:
# unit_cardinality_conservation_across_decommission (2 tests)
# ---------------------------------------------------------------------------

def _qualified_donor_plus_quarantined_unit():
    """Center with donor QUALIFIED after d1/d2 (u1/u2 RELEASED) and a third
    completion leaving u3 QUARANTINED; all visits terminal."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    donor, (dv1, dv2) = setup_qualified_donor_with_released_units(center, donor)
    # d3's screening is scheduled before the 09-12 clock jump; sub-records
    # written within its 24h window.
    s3 = get_success_data(
        api_client.schedule_screening(
            donor["id"],
            {"center_id": center["id"], "scheduled_for": "2026-09-12T08:00:00Z"},
            TEST_USERS["recorder_headers"],
        )
    )
    set_clock("2026-09-12T09:30:00Z")
    from test_helpers.fixtures import record_pass_sub_record
    from test_helpers.test_users import make_screener_headers
    for rt in ("IDENTITY", "HEALTH_HISTORY", "PHYSICAL_EXAM", "VIRAL_MARKER"):
        record_pass_sub_record(s3["id"], rt, "rec-01")
    get_success_data(api_client.clear_screening(s3["id"], make_screener_headers("ms-01")))
    dv3 = get_success_data(
        api_client.schedule_donation(
            donor["id"],
            {
                "center_id": center["id"],
                "screening_visit_id": s3["id"],
                "scheduled_for": "2026-09-12T10:00:00Z",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    get_success_data(api_client.check_in(dv3["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api_client.complete_collection(
            dv3["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]
        )
    )
    set_clock("2026-09-12T10:16:00Z")
    get_success_data(api_client.discharge(dv3["id"], TEST_USERS["phlebotomist_headers"]))
    center = get_success_data(api_client.get_center(center["id"], TEST_USERS["admin_headers"]))
    return center, donor


def test_decommission_destroys_quarantined_units_with_expired_hold(api):
    """PRD §3.11: "A successful decommission transitions the center to
    `DECOMMISSIONED` (a terminal state), increments its `version`, and
    destroys every `QUARANTINED` unit at the center with `destruction_reason`
    `EXPIRED_HOLD`."

    Design: Difficulty/compensating_invariant/unit_cardinality_conservation_across_decommission
    """
    center, donor = _qualified_donor_plus_quarantined_unit()
    resp = api_client.decommission_center(
        center["id"],
        {"expected_center_version": center["version"]},
        TEST_USERS["admin_headers"],
    )
    after = validate_success(resp, 200)
    assert after["status"] == "DECOMMISSIONED"

    destroyed, meta_d = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"center_id": center["id"], "unit_status": "DESTROYED"},
        )
    )
    assert meta_d["total_count"] == 1
    assert destroyed[0]["destruction_reason"] == "EXPIRED_HOLD"


def test_decommission_preserves_unit_cardinality(api):
    """PRD §3.11: decommission "destroys every `QUARANTINED` unit at the
    center with `destruction_reason` `EXPIRED_HOLD`" — units in other statuses
    are untouched, so the per-status partition shifts without changing the
    total count (no unit created, duplicated, or lost).
    PRD §3.6: "the row remains queryable via the unit list and read
    endpoints."

    Design: Difficulty/compensating_invariant/unit_cardinality_conservation_across_decommission
    """
    center, donor = _qualified_donor_plus_quarantined_unit()
    before, meta_before = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"], params={"center_id": center["id"]}
        )
    )
    assert meta_before["total_count"] == 3

    get_success_data(
        api_client.decommission_center(
            center["id"],
            {"expected_center_version": center["version"]},
            TEST_USERS["admin_headers"],
        )
    )
    _, meta_q = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"center_id": center["id"], "unit_status": "QUARANTINED"},
        )
    )
    _, meta_r = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"center_id": center["id"], "unit_status": "RELEASED"},
        )
    )
    _, meta_d = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"center_id": center["id"], "unit_status": "DESTROYED"},
        )
    )
    assert meta_q["total_count"] == 0
    assert meta_r["total_count"] == 2
    assert meta_d["total_count"] == 1
    assert meta_q["total_count"] + meta_r["total_count"] + meta_d["total_count"] == 3
