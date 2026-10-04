"""Look-back, deferral, and donor qualification cascades."""
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
    record_pass_sub_record,
    run_completed_donation,
    set_clock,
    setup_lookback_case_ready,
    setup_qualified_donor_with_released_units,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import viral_marker_payload
from test_helpers.fixtures import get_payment
from test_helpers.test_users import make_recorder_headers, make_screener_headers


def _complete_two_donations_and_open_case():
    """Donor QUALIFIED after d1/d2; reactive marker on a third screening opens
    a look-back case and sweeps both units into LOOKBACK_HOLD."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    donor, (dv1, dv2) = setup_qualified_donor_with_released_units(center, donor)
    case = setup_lookback_case_ready(center, donor, "2026-09-05")
    return center, donor, dv1, dv2, case


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade: reactive_marker_lookback_depth_four (2 tests)
# ---------------------------------------------------------------------------

def test_reactive_marker_fails_screening_and_opens_case(api):
    """PRD §3.3: "Any sub-record write whose computed `outcome` is `FAIL`
    automatically transitions the visit from `IN_PROGRESS` to `FAILED`".
    PRD §3.6: "When a viral-marker sub-record on a subsequent screening comes
    back `REACTIVE`, the failing visit moves to `FAILED` and a **LookBackCase**
    is opened for the donor with `case_status` `OPEN`, an `opened_at` stamp
    from the logical clock, a fixed `lookback_window_days` of 180".

    Design: Difficulty/transitive_cascade/reactive_marker_lookback_depth_four_cascade
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    donor, _ = setup_qualified_donor_with_released_units(center, donor)
    # Third completed donation leaves u3 QUARANTINED. Its screening is
    # scheduled while the clock is still on 09-04 so the logical clock never
    # moves backward; sub-records are written after the 09-12 clock set,
    # inside the screening's 24h window.
    s3 = get_success_data(
        api_client.schedule_screening(
            donor["id"],
            {"center_id": center["id"], "scheduled_for": "2026-09-12T08:00:00Z"},
            TEST_USERS["recorder_headers"],
        )
    )
    set_clock("2026-09-12T09:30:00Z")
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
    # Fourth screening in progress with three PASS records.
    s4 = make_screening(donor, center, "2026-09-13T08:00:00Z")
    set_clock("2026-09-13T09:00:00Z")
    for rt in ("IDENTITY", "HEALTH_HISTORY", "PHYSICAL_EXAM"):
        record_pass_sub_record(s4["id"], rt, "rec-01")

    resp = api_client.record_sub_record(
        s4["id"],
        {
            "record_type": "VIRAL_MARKER",
            "payload": viral_marker_payload(hbv_surface_ag="REACTIVE"),
        },
        make_recorder_headers("rec-01"),
    )
    sub = get_success_data(resp)
    assert sub["outcome"] == "FAIL", "reactive marker fails the record"
    s4_after = get_success_data(api_client.get_screening(s4["id"], TEST_USERS["admin_headers"]))
    assert s4_after["visit_status"] == "FAILED"

    cases, meta = validate_paginated(
        api_client.list_lookback_cases(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    assert meta["total_count"] == 1
    assert cases[0]["lookback_window_days"] == 180


def test_reactive_marker_sweeps_all_in_window_units_to_hold(api):
    """PRD §3.6: "Every DonationUnit the donor has produced whose
    `collected_at` falls within one hundred eighty days of the reactive
    instant is moved to `LOOKBACK_HOLD`, whether it was `QUARANTINED` or
    already `RELEASED`" and "When every in-window unit has been moved, the
    case transitions `OPEN → UNITS_QUARANTINED`".

    Design: Difficulty/transitive_cascade/reactive_marker_lookback_depth_four_cascade
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    donor, _ = setup_qualified_donor_with_released_units(center, donor)
    # Third completed donation leaves u3 QUARANTINED (screening scheduled
    # before the 09-12 clock jump; sub-records written within its window).
    s3 = get_success_data(
        api_client.schedule_screening(
            donor["id"],
            {"center_id": center["id"], "scheduled_for": "2026-09-12T08:00:00Z"},
            TEST_USERS["recorder_headers"],
        )
    )
    set_clock("2026-09-12T09:30:00Z")
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
    s4 = make_screening(donor, center, "2026-09-13T08:00:00Z")
    set_clock("2026-09-13T09:00:00Z")
    get_success_data(
        api_client.record_sub_record(
            s4["id"],
            {
                "record_type": "VIRAL_MARKER",
                "payload": viral_marker_payload(hbv_surface_ag="REACTIVE"),
            },
            make_recorder_headers("rec-01"),
        )
    )
    cases, _ = validate_paginated(
        api_client.list_lookback_cases(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    assert cases[0]["case_status"] == "UNITS_QUARANTINED"
    held, meta = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"donor_id": donor["id"], "unit_status": "LOOKBACK_HOLD"},
        )
    )
    assert meta["total_count"] == 3, "QUARANTINED u3 plus previously RELEASED u1, u2"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine: donation_unit cycle (2 tests)
# ---------------------------------------------------------------------------

def test_unit_cycle_released_to_hold_and_case_ready(api):
    """PRD §3.6: "Every DonationUnit the donor has produced whose
    `collected_at` falls within one hundred eighty days of the reactive
    instant is moved to `LOOKBACK_HOLD`, whether it was `QUARANTINED` or
    already `RELEASED`; for a previously released unit the original
    `released_at` is preserved for audit."

    Design: Difficulty/non_linear_state_machine/donation_unit_quarantine_release_lookback_cycle
    """
    center, donor, dv1, dv2, case = _complete_two_donations_and_open_case()
    assert case["case_status"] == "UNITS_QUARANTINED", (
        "cycle leg 2 fired: units held, case advanced"
    )
    held, meta = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"donor_id": donor["id"], "unit_status": "LOOKBACK_HOLD"},
        )
    )
    assert meta["total_count"] == 2, "both previously RELEASED units held"
    for unit in held:
        assert unit["released_at"] is not None, "original released_at preserved for audit"


def test_unit_cycle_release_resolution_returns_units_to_released(api):
    """PRD §3.6: "Under `RELEASE`, every held unit transitions
    `LOOKBACK_HOLD → RELEASED` with `released_at` stamped — this is the
    false-positive retest path — and the donor must be `QUALIFIED` at
    resolution time (`ERR_DONOR_NOT_QUALIFIED` otherwise). When the last
    held unit is released, the case transitions to `RESOLVED_RELEASED` with
    `resolved_at` stamped."

    Design: Difficulty/non_linear_state_machine/donation_unit_quarantine_release_lookback_cycle
    """
    center, donor, dv1, dv2, case = _complete_two_donations_and_open_case()
    resp = api_client.resolve_lookback_case(
        case["id"],
        {
            "resolution": "RELEASE",
            "resolution_rationale": "confirmatory retest negative on all held units",
        },
        TEST_USERS["compliance_headers"],
    )
    data = validate_success(resp, 200)
    assert data["case_status"] == "RESOLVED_RELEASED"
    held, meta_held = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"donor_id": donor["id"], "unit_status": "LOOKBACK_HOLD"},
        )
    )
    assert meta_held["total_count"] == 0
    rel, meta_rel = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"donor_id": donor["id"], "unit_status": "RELEASED"},
        )
    )
    assert meta_rel["total_count"] == 2, "both units returned to RELEASED"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade: lookback_destroy_clawback_ytd (2 tests)
# ---------------------------------------------------------------------------

def test_lookback_destroy_claws_back_payments(api):
    """PRD §3.6: "Under `DESTROY`, every held unit transitions
    `LOOKBACK_HOLD → DESTROYED` with `destruction_reason` `REACTIVE_LOOKBACK`
    and `destroyed_at` stamped; each destroyed unit's CompensationPayment, if
    it was `FINALIZED`, transitions to `CLAWED_BACK`".

    Design: Difficulty/transitive_cascade/lookback_destroy_clawback_ytd_cascade
    """
    center, donor, dv1, dv2, case = _complete_two_donations_and_open_case()
    d_pre = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d_pre["ytd_compensation_cents"] == 5500, "3000 + 2500 FINALIZED"

    resp = api_client.resolve_lookback_case(
        case["id"],
        {
            "resolution": "DESTROY",
            "resolution_rationale": "confirmatory test positive; destroying units",
        },
        TEST_USERS["compliance_headers"],
    )
    data = validate_success(resp, 200)
    assert data["case_status"] == "RESOLVED_DESTROYED"
    assert get_payment(dv1["id"])["payment_status"] == "CLAWED_BACK"
    assert get_payment(dv2["id"])["payment_status"] == "CLAWED_BACK"
    destroyed, meta = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"donor_id": donor["id"], "unit_status": "DESTROYED"},
        )
    )
    assert meta["total_count"] == 2
    assert destroyed[0]["destruction_reason"] == "REACTIVE_LOOKBACK"


def test_lookback_destroy_debits_ytd_exactly(api):
    """PRD §3.8: "When a look-back destroys a unit whose payment was
    `FINALIZED`, that payment transitions to `CLAWED_BACK` and the donor's
    `ytd_compensation_cents` is debited by the payment's `net_cents`."

    Design: Difficulty/transitive_cascade/lookback_destroy_clawback_ytd_cascade
    """
    center, donor, dv1, dv2, case = _complete_two_donations_and_open_case()
    get_success_data(
        api_client.resolve_lookback_case(
            case["id"],
            {
                "resolution": "DESTROY",
                "resolution_rationale": "confirmatory test positive; destroying units",
            },
            TEST_USERS["compliance_headers"],
        )
    )
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["ytd_compensation_cents"] == 0, "5500 - 3000 - 2500"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade: severe_reaction_deferral_noshow (2 tests)
# ---------------------------------------------------------------------------

def _setup_severe_reaction_scenario():
    """dv1 checked in (IN_PROGRESS); dv2 SCHEDULED for the same donor."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    s1 = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z", recorder_id="rec-01")
    dv1 = make_donation(donor, center, s1, "2026-09-01T09:30:00Z")
    s2 = make_cleared_screening(donor, center, "2026-09-01T08:30:00Z", recorder_id="rec-02")
    dv2 = make_donation(donor, center, s2, "2026-09-01T10:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api_client.check_in(dv1["id"], TEST_USERS["phlebotomist_headers"]))
    set_clock("2026-09-01T09:35:00Z")
    return center, donor, dv1, dv2


def test_severe_reaction_autofiles_deferral_and_defers_donor(api):
    """PRD §3.9: "A `SEVERE` reaction has an additional consequence. The
    system auto-files a DeferralRegistryEntry on the donor with
    `deferral_type` `TEMPORARY`, `deferral_ends_on` set 7 days after the
    current instant, and `reason_code` `ADVERSE_REACTION_SEVERE`. The donor
    transitions to `DEFERRED_TEMP` with the standard side effects enumerated
    in §3.10."

    Design: Difficulty/transitive_cascade/severe_reaction_deferral_noshow_cascade
    """
    center, donor, dv1, dv2 = _setup_severe_reaction_scenario()
    resp = api_client.record_adverse_reaction(
        dv1["id"],
        {
            "severity": "SEVERE",
            "reaction_code": "ARTERIAL_PUNCTURE",
            "observed_at": "2026-09-01T09:35:00Z",
            "notes": "arterial puncture with significant bleed",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    reaction = get_success_data(resp)
    assert reaction["severity"] == "SEVERE"
    dv1_after = get_success_data(api_client.get_donation(dv1["id"], TEST_USERS["admin_headers"]))
    assert dv1_after["visit_status"] == "ABORTED_REACTION"

    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "DEFERRED_TEMP"
    assert d["deferred_reason_code"] == "ADVERSE_REACTION_SEVERE"

    entries, meta = validate_paginated(
        api_client.list_deferrals(donor["id"], TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 1
    assert entries[0]["deferral_type"] == "TEMPORARY"
    assert entries[0]["registry_status"] == "ACTIVE"


def test_severe_reaction_cascades_other_scheduled_visit_to_no_show(api):
    """PRD §3.10: "Every DonationVisit the donor has in `SCHEDULED` status is
    moved to `NO_SHOW`." — the donor status change triggered by the severe
    reaction cascades to the donor's OTHER scheduled visit.
    PRD §3.5: "The same `NO_SHOW` terminal state is reached by cascade when
    the donor is deferred or the center is placed on inspection hold; in
    those cases `scheduled_for` is left unchanged."

    Design: Difficulty/transitive_cascade/severe_reaction_deferral_noshow_cascade
    """
    center, donor, dv1, dv2 = _setup_severe_reaction_scenario()
    get_success_data(
        api_client.record_adverse_reaction(
            dv1["id"],
            {
                "severity": "SEVERE",
                "reaction_code": "ARTERIAL_PUNCTURE",
                "observed_at": "2026-09-01T09:35:00Z",
                "notes": "arterial puncture with significant bleed",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    dv2_after = get_success_data(api_client.get_donation(dv2["id"], TEST_USERS["admin_headers"]))
    assert dv2_after["visit_status"] == "NO_SHOW"
    assert dv2_after["scheduled_for"] == "2026-09-01T10:30:00.000Z", "scheduled_for unchanged"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine: donor_deferral_auto_clear_cycle (2)
# ---------------------------------------------------------------------------

def test_deferral_auto_clear_cycle_leg1_deferred_then_cleared(api):
    """PRD §3.10: "A temporary deferral clears automatically. When the
    logical clock reaches `deferral_ends_on` and the entry is still `ACTIVE`,
    the entry's `registry_status` transitions to `CLEARED`, the donor's
    `active_deferral_id`, `deferral_ends_on`, and `deferred_reason_code` are
    all set to null, and the donor's `version` increments. The donor's status
    is recomputed from donation history: a donor with
    `lifetime_donation_count` 0 returns to `APPLICANT`".

    Design: Difficulty/non_linear_state_machine/donor_deferral_auto_clear_cycle
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    resp = api_client.file_deferral(
        donor["id"],
        {
            "reason_code": "TRAVEL_MALARIA",
            "deferral_type": "TEMPORARY",
            "deferral_ends_on": "2026-09-10T00:00:00Z",
        },
        TEST_USERS["compliance_headers"],
    )
    entry = validate_success(resp, 201)
    assert entry["registry_status"] == "ACTIVE"

    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "DEFERRED_TEMP"
    assert d["deferred_reason_code"] == "TRAVEL_MALARIA"
    assert d["deferral_ends_on"] == "2026-09-10T00:00:00.000Z"

    set_clock("2026-09-10T00:00:00Z")
    d2 = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d2["donor_status"] == "APPLICANT", "lifetime count 0 -> APPLICANT"
    assert d2["active_deferral_id"] is None
    assert d2["deferral_ends_on"] is None

    entries, _ = validate_paginated(
        api_client.list_deferrals(donor["id"], TEST_USERS["admin_headers"])
    )
    assert entries[0]["registry_status"] == "CLEARED"


def test_deferral_auto_clear_cycle_repeatable(api):
    """PRD §3.10: "when an `ACTIVE` DeferralRegistryEntry already exists for
    this donor, the new filing is rejected with `ERR_ACTIVE_DEFERRAL_EXISTS`"
    — after the first deferral auto-CLEARS, no ACTIVE entry exists anymore, so
    a second TEMPORARY filing is accepted.

    Design: Difficulty/non_linear_state_machine/donor_deferral_auto_clear_cycle
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    get_success_data(
        api_client.file_deferral(
            donor["id"],
            {
                "reason_code": "TRAVEL_MALARIA",
                "deferral_type": "TEMPORARY",
                "deferral_ends_on": "2026-09-10T00:00:00Z",
            },
            TEST_USERS["compliance_headers"],
        )
    )
    set_clock("2026-09-10T00:00:00Z")
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "APPLICANT"

    resp = api_client.file_deferral(
        donor["id"],
        {
            "reason_code": "MEDICAL_HOLD",
            "deferral_type": "TEMPORARY",
            "deferral_ends_on": "2026-09-20T00:00:00Z",
        },
        TEST_USERS["compliance_headers"],
    )
    entry = validate_success(resp, 201)
    assert entry["registry_status"] == "ACTIVE", "cycle is repeatable"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency:
# unit_release_gated_by_donor_qualification (2 tests)
# ---------------------------------------------------------------------------

def _applicant_donor_with_one_quarantined_unit():
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    dv1 = run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-01T08:00:00Z",
        checkin_time="2026-09-01T09:30:00Z",
        discharge_time="2026-09-01T09:46:00Z",
    )
    units, meta = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"donor_id": donor["id"], "unit_status": "QUARANTINED"},
        )
    )
    assert meta["total_count"] == 1
    return center, donor, dv1, units[0]


def test_unit_release_blocked_while_donor_applicant(api):
    """PRD §3.6: "When the donor is `QUALIFIED` at release time and there is
    no `OPEN` or `UNITS_QUARANTINED` LookBackCase for the donor, a Compliance
    Officer may release the unit" and "a donor who is not `QUALIFIED` rejects
    with `ERR_DONOR_NOT_QUALIFIED`".

    Design: Difficulty/cross_entity_state_dependency/unit_release_gated_by_donor_qualification
    """
    center, donor, dv1, unit = _applicant_donor_with_one_quarantined_unit()
    resp = api_client.release_unit(unit["id"], TEST_USERS["compliance_headers"])
    validate_error(resp, ApiErrorId.ERR_DONOR_NOT_QUALIFIED, 409)


def test_donor_qualification_cascade_releases_quarantined_unit(api):
    """PRD §3.7: "The promotion releases every `QUARANTINED` unit the donor
    has produced whose triggering visit's screening had no reactive viral
    marker — each such unit moves to `RELEASED` with `released_at` stamped".

    Design: Difficulty/cross_entity_state_dependency/unit_release_gated_by_donor_qualification
    """
    center, donor, dv1, unit = _applicant_donor_with_one_quarantined_unit()
    # Second donation completes inside the applicant window.
    set_clock("2026-09-04T09:00:00Z")
    run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-04T08:00:00Z",
        checkin_time="2026-09-04T09:30:00Z",
        discharge_time="2026-09-04T09:46:00Z",
    )
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "QUALIFIED"
    u = get_success_data(api_client.get_unit(unit["id"], TEST_USERS["admin_headers"]))
    assert u["unit_status"] == "RELEASED"
    assert u["released_at"] == "2026-09-04T09:46:00.000Z"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency:
# unit_release_gated_by_open_lookback_case (2 tests)
# ---------------------------------------------------------------------------

def _case_open_with_post_case_quarantined_unit():
    """Donor QUALIFIED after d1/d2; d3 completed (u3 QUARANTINED); reactive
    marker on s4 opens case C1 and holds u1..u3; d4 completed after the case
    opened leaves u4 QUARANTINED. Returns (center, donor, case, u4)."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    donor, _ = setup_qualified_donor_with_released_units(center, donor)
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
    case = setup_lookback_case_ready(center, donor, "2026-09-13")
    assert case["case_status"] == "UNITS_QUARANTINED"
    # d4: clean screening + completion AFTER the case opened.
    set_clock("2026-09-20T09:00:00Z")
    run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-20T08:00:00Z",
        checkin_time="2026-09-20T11:00:00Z",
        discharge_time="2026-09-20T11:16:00Z",
    )
    units, meta = validate_paginated(
        api_client.list_units(
            TEST_USERS["admin_headers"],
            params={"donor_id": donor["id"], "unit_status": "QUARANTINED"},
        )
    )
    assert meta["total_count"] == 1, "u4 was created after the case opened"
    return center, donor, case, units[0]


def test_unit_release_blocked_by_open_lookback_case(api):
    """PRD §3.6: "When the donor is `QUALIFIED` at release time and there is
    no `OPEN` or `UNITS_QUARANTINED` LookBackCase for the donor, a Compliance
    Officer may release the unit" and "an open look-back rejects with
    `ERR_LOOKBACK_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/unit_release_gated_by_open_lookback_case
    """
    center, donor, case, u4 = _case_open_with_post_case_quarantined_unit()
    resp = api_client.release_unit(u4["id"], TEST_USERS["compliance_headers"])
    validate_error(resp, ApiErrorId.ERR_LOOKBACK_OPEN, 409)


def test_unit_release_succeeds_after_case_resolved(api):
    """PRD §3.6: "When the donor is `QUALIFIED` at release time and there is
    no `OPEN` or `UNITS_QUARANTINED` LookBackCase for the donor, a Compliance
    Officer may release the unit, transitioning it to `RELEASED` and stamping
    `released_at`."

    Design: Difficulty/cross_entity_state_dependency/unit_release_gated_by_open_lookback_case
    """
    center, donor, case, u4 = _case_open_with_post_case_quarantined_unit()
    resp = api_client.resolve_lookback_case(
        case["id"],
        {
            "resolution": "RELEASE",
            "resolution_rationale": "repeat testing negative; false positive",
        },
        TEST_USERS["compliance_headers"],
    )
    data = validate_success(resp, 200)
    assert data["case_status"] == "RESOLVED_RELEASED"
    resp = api_client.release_unit(u4["id"], TEST_USERS["compliance_headers"])
    unit = validate_success(resp, 200)
    assert unit["unit_status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Corner look-back and deferral tests
# ---------------------------------------------------------------------------

def test_lookback_zero_unit_degenerate_autoresolve(api):
    """PRD §3.6: "in the degenerate case where zero units fall in the window,
    the case immediately auto-resolves to `RESOLVED_DESTROYED` with
    `resolved_at` equal to `opened_at` — a no-op resolution recorded for
    audit."

    Design: Corner/state_machines/lookback_zero_unit_degenerate_autoresolve
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    record_pass_sub_record(visit["id"], "IDENTITY", "rec-01")
    get_success_data(
        api_client.record_sub_record(
            visit["id"],
            {
                "record_type": "VIRAL_MARKER",
                "payload": viral_marker_payload(hcv_ab="REACTIVE"),
            },
            make_recorder_headers("rec-01"),
        )
    )
    cases, meta = validate_paginated(
        api_client.list_lookback_cases(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    assert meta["total_count"] == 1
    case = cases[0]
    assert case["case_status"] == "RESOLVED_DESTROYED"
    assert case["resolved_at"] == case["opened_at"]
    assert case["opened_at"] == "2026-09-01T09:00:00.000Z"


def test_lookback_resolve_on_terminal_case_rejected(api):
    """PRD §3.6: "A case that is not `UNITS_QUARANTINED` rejects with
    `ERR_LOOKBACK_NOT_READY`." and "`RESOLVED_DESTROYED` and
    `RESOLVED_RELEASED` are both terminal."

    Design: Corner/state_machines/lookback_resolve_on_terminal_case_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = make_screening(donor, center, "2026-09-01T08:00:00Z")
    get_success_data(
        api_client.record_sub_record(
            visit["id"],
            {
                "record_type": "VIRAL_MARKER",
                "payload": viral_marker_payload(hiv_ag_ab="REACTIVE"),
            },
            make_recorder_headers("rec-01"),
        )
    )
    cases, _ = validate_paginated(
        api_client.list_lookback_cases(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    case = cases[0]
    resp = api_client.resolve_lookback_case(
        case["id"],
        {
            "resolution": "DESTROY",
            "resolution_rationale": "attempting to re-resolve a closed case",
        },
        TEST_USERS["compliance_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_LOOKBACK_NOT_READY, 409)


def test_lookback_release_resolution_requires_qualified_donor(api):
    """PRD §3.6: "Under `RELEASE`, every held unit transitions
    `LOOKBACK_HOLD → RELEASED` with `released_at` stamped — this is the
    false-positive retest path — and the donor must be `QUALIFIED` at
    resolution time (`ERR_DONOR_NOT_QUALIFIED` otherwise)." Under `DESTROY`,
    "each destroyed unit's CompensationPayment, if it was `FINALIZED`,
    transitions to `CLAWED_BACK` and the donor's `ytd_compensation_cents` is
    debited by that payment's `net_cents`."

    Design: Corner/state_machines/lookback_release_resolution_requires_qualified_donor
    """
    center, donor, dv1, unit = _applicant_donor_with_one_quarantined_unit()
    # Reactive marker on a second screening holds u1. The donor is then
    # moved out of QUALIFIED by a TEMPORARY deferral (DEFERRED_TEMP) so the
    # RELEASE resolution precondition fails.
    case = setup_lookback_case_ready(center, donor, "2026-09-02", marker="hbv_surface_ag")
    assert case["case_status"] == "UNITS_QUARANTINED"
    get_success_data(
        api_client.file_deferral(
            donor["id"],
            {
                "reason_code": "MEDICAL_HOLD",
                "deferral_type": "TEMPORARY",
                "deferral_ends_on": "2026-09-20T00:00:00Z",
            },
            TEST_USERS["compliance_headers"],
        )
    )
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "DEFERRED_TEMP"

    resp = api_client.resolve_lookback_case(
        case["id"],
        {
            "resolution": "RELEASE",
            "resolution_rationale": "attempted release resolution too early",
        },
        TEST_USERS["compliance_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DONOR_NOT_QUALIFIED, 409)

    resp = api_client.resolve_lookback_case(
        case["id"],
        {
            "resolution": "DESTROY",
            "resolution_rationale": "confirmed reactive; unit destroyed",
        },
        TEST_USERS["compliance_headers"],
    )
    data = validate_success(resp, 200)
    assert data["case_status"] == "RESOLVED_DESTROYED"
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["ytd_compensation_cents"] == 0, "was 3000 before the claw-back"


def test_deferral_on_already_deferred_donor_rejected(api):
    """PRD §3.10: "The donor must currently be `APPLICANT` or `QUALIFIED`; a
    donor already deferred is rejected with `ERR_DONOR_NOT_DEFERRABLE`."

    Design: Corner/state_machines/deferral_on_already_deferred_donor_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    d1 = make_donor(center)
    d2 = make_donor(
        center, external_donor_ref="DL-TX-000002", legal_first_name="John",
        legal_last_name="Roe", date_of_birth="1985-05-05", weight_kg=80.0,
    )
    get_success_data(
        api_client.file_deferral(
            d1["id"],
            {
                "reason_code": "TRAVEL_MALARIA",
                "deferral_type": "TEMPORARY",
                "deferral_ends_on": "2026-09-20T00:00:00Z",
            },
            TEST_USERS["compliance_headers"],
        )
    )
    get_success_data(
        api_client.file_deferral(
            d2["id"],
            {"reason_code": "REACTIVE_HCV", "deferral_type": "PERMANENT"},
            TEST_USERS["compliance_headers"],
        )
    )
    r1 = api_client.file_deferral(
        d1["id"],
        {
            "reason_code": "MEDICAL_HOLD",
            "deferral_type": "TEMPORARY",
            "deferral_ends_on": "2026-10-01T00:00:00Z",
        },
        TEST_USERS["compliance_headers"],
    )
    validate_error(r1, ApiErrorId.ERR_DONOR_NOT_DEFERRABLE, 409)
    r2 = api_client.file_deferral(
        d2["id"],
        {
            "reason_code": "MEDICAL_HOLD",
            "deferral_type": "TEMPORARY",
            "deferral_ends_on": "2026-10-01T00:00:00Z",
        },
        TEST_USERS["compliance_headers"],
    )
    validate_error(r2, ApiErrorId.ERR_DONOR_NOT_DEFERRABLE, 409)
    for d in (d1, d2):
        _, meta = validate_paginated(
            api_client.list_deferrals(d["id"], TEST_USERS["admin_headers"])
        )
        assert meta["total_count"] == 1


def test_deferral_temporary_requires_end_date(api):
    """PRD §3.10: "a `deferral_type` of either `TEMPORARY` or `PERMANENT`,
    and — when the type is `TEMPORARY` — a `deferral_ends_on` that must be
    strictly later than the logical-clock `created_at` of the entry."
    PRD §2.9 item 22: "Required-field presence, types, enum membership,
    string-length floors, numeric ranges → `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/deferral_temporary_requires_end_date
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    resp = api_client.file_deferral(
        donor["id"],
        {"reason_code": "TRAVEL_MALARIA", "deferral_type": "TEMPORARY"},
        TEST_USERS["compliance_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "APPLICANT", "no partial side effects"


def test_permanent_deferral_destroys_quarantined_units(api):
    """PRD §3.10: "A `TEMPORARY` filing drives the donor to `DEFERRED_TEMP`;
    a `PERMANENT` filing drives the donor to `DEFERRED_PERM`." and "A
    permanent deferral has two further cascades: every `QUARANTINED` unit the
    donor has produced is destroyed with `destruction_reason`
    `DONOR_PERMANENT_DEFERRAL`" and "for a permanent deferral
    `deferral_ends_on` is set to null."

    Design: Corner/state_machines/permanent_deferral_destroys_quarantined_units
    """
    center, donor, dv1, unit = _applicant_donor_with_one_quarantined_unit()
    resp = api_client.file_deferral(
        donor["id"],
        {"reason_code": "REACTIVE_HIV", "deferral_type": "PERMANENT"},
        TEST_USERS["compliance_headers"],
    )
    entry = validate_success(resp, 201)
    assert entry["deferral_type"] == "PERMANENT"
    assert entry["registry_status"] == "ACTIVE"

    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "DEFERRED_PERM"
    assert d["deferral_ends_on"] is None

    u = get_success_data(api_client.get_unit(unit["id"], TEST_USERS["admin_headers"]))
    assert u["unit_status"] == "DESTROYED"
    assert u["destruction_reason"] == "DONOR_PERMANENT_DEFERRAL"


def test_deferral_override_recomputes_donor_status(api):
    """PRD §3.10: "A Compliance Officer can override an `ACTIVE` deferral by
    supplying an `override_rationale` of at least 20 characters — anything
    shorter is rejected with `ERR_INVALID_REQUEST`. A successful override
    moves the entry's `registry_status` to `OVERRIDDEN`, clears the donor's
    `active_deferral_id` to null, and recomputes the donor's status from
    donation history by the same rule: `APPLICANT` when
    `lifetime_donation_count` is 0, otherwise `QUALIFIED`."

    Design: Corner/state_machines/deferral_override_recomputes_donor_status
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    resp = api_client.file_deferral(
        donor["id"],
        {
            "reason_code": "TRAVEL_MALARIA",
            "deferral_type": "TEMPORARY",
            "deferral_ends_on": "2026-09-20T00:00:00Z",
        },
        TEST_USERS["compliance_headers"],
    )
    entry = validate_success(resp, 201)

    r_short = api_client.override_deferral(
        entry["id"], {"override_rationale": "too short"}, TEST_USERS["compliance_headers"]
    )
    validate_error(r_short, ApiErrorId.ERR_INVALID_REQUEST, 400)

    resp = api_client.override_deferral(
        entry["id"],
        {"override_rationale": "medical director reviewed chart and cleared donor"},
        TEST_USERS["compliance_headers"],
    )
    overridden = validate_success(resp, 200)
    assert overridden["registry_status"] == "OVERRIDDEN"
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["donor_status"] == "APPLICANT", "lifetime 0 -> APPLICANT"
    assert d["active_deferral_id"] is None


# ---------------------------------------------------------------------------
# Corner/cross_cutting: lifetime count monotonic
# ---------------------------------------------------------------------------

def test_lifetime_donation_count_monotonic_despite_clawback(api):
    """PRD §3.7: the donation history "is not erased from
    `lifetime_donation_count`, which is monotonically increasing for audit".
    PRD §3.8: a look-back claw-back debits `ytd_compensation_cents` but the
    completion count never moves backward.

    Design: Corner/cross_cutting_complexity_layers/lifetime_donation_count_monotonic_despite_clawback
    """
    center, donor, dv1, dv2, case = _complete_two_donations_and_open_case()
    get_success_data(
        api_client.resolve_lookback_case(
            case["id"],
            {
                "resolution": "DESTROY",
                "resolution_rationale": "confirmed reactive on retest; destroy",
            },
            TEST_USERS["compliance_headers"],
        )
    )
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["ytd_compensation_cents"] == 0, "claw-back reconciled ytd to 0"
    assert d["lifetime_donation_count"] == 2, "the count never moves backward"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant:
# ytd_finalize_clawback_conservation_with_sticky_1099 (2 tests)
# ---------------------------------------------------------------------------

def _setup_ytd_conservation_scenario():
    """Schedule first=35000 second=30000; donor QUALIFIED after d1/d2 with
    ytd 65000 and requires_1099 true; reactive marker opened a case holding
    u1/u2."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(
        base_cents_first_donation=35000, base_cents_second_donation=30000,
    )
    donor = make_donor(center)
    donor, (dv1, dv2) = setup_qualified_donor_with_released_units(center, donor)
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    case = setup_lookback_case_ready(center, donor, "2026-09-05")
    return center, donor, case, d


def test_ytd_finalize_clawback_conservation(api):
    """PRD §3.8: "The donor's `ytd_compensation_cents` is recomputed on every
    finalize and every claw-back as the sum of `net_cents` over all
    CompensationPayment rows for this donor whose `payment_status` is
    `FINALIZED` and whose `payment_issued_on` falls within the calendar year
    of the logical clock."

    Design: Difficulty/compensating_invariant/ytd_finalize_clawback_conservation_with_sticky_1099
    """
    center, donor, case, d_pre = _setup_ytd_conservation_scenario()
    assert d_pre["ytd_compensation_cents"] == 65000, "35000 + 30000"
    assert d_pre["requires_1099"] is True, "crossed TAX_REPORTING_THRESHOLD_CENTS 60000"

    get_success_data(
        api_client.resolve_lookback_case(
            case["id"],
            {
                "resolution": "DESTROY",
                "resolution_rationale": "confirmatory positive; full unit destruction",
            },
            TEST_USERS["compliance_headers"],
        )
    )
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["ytd_compensation_cents"] == 0, "exactly the pre-donation baseline, no drift"


def test_requires_1099_sticky_downward_after_clawback(api):
    """PRD §3.8: "The flag is **sticky downward** — once true it remains true
    even if a later claw-back pulls the year-to-date total below the
    threshold, because a 1099 obligation incurred mid-year is not voided by a
    later claw-back."

    Design: Difficulty/compensating_invariant/ytd_finalize_clawback_conservation_with_sticky_1099
    """
    center, donor, case, d_pre = _setup_ytd_conservation_scenario()
    assert d_pre["requires_1099"] is True
    get_success_data(
        api_client.resolve_lookback_case(
            case["id"],
            {
                "resolution": "DESTROY",
                "resolution_rationale": "confirmatory positive; full unit destruction",
            },
            TEST_USERS["compliance_headers"],
        )
    )
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["ytd_compensation_cents"] == 0
    assert d["requires_1099"] is True, "NOT part of the conserved quantity"
