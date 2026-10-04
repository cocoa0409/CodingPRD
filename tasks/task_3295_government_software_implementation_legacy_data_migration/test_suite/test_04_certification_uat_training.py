"""Certification windows, UAT scheduling, training capacity, and audit log."""
from test_helpers import (
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS, api_client,
    certification_payload, create_contract_in_implementation, create_interface,
    create_milestone, create_uat_tester, get_success_data, reset_clock,
    staff_payload, submit_milestone, training_session_payload,
    uat_cycle_payload, uat_session_payload, validate_error,
    validate_paginated, validate_success, walk_contract_to_award_pending,
    award_contract, create_agency, create_draft_contract,
)


def test_certification_window_adjacency_vs_overlap():
    """PRD §3.6: "a new window is rejected with
    `ERR_CERTIFICATION_WINDOW_OVERLAP` (HTTP 409) only when it shares interior
    dates with a non-`CANCELLED` certification window of the same interface ...
    Adjacency, meaning one window's end plus one day equals the other's start,
    is allowed; touching boundaries do not collide here".

    Design: Difficulty/resource_temporal_overlap/certification_window_adjacency_vs_overlap
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    iface = create_interface(ctx["contract"]["id"], name="StateGW")
    get_success_data(api_client.start_interface_development(
        iface["id"], TEST_USERS["interface_engineer"]))
    get_success_data(api_client.start_interface_testing(
        iface["id"], TEST_USERS["interface_engineer"]))
    cert1 = get_success_data(api_client.create_certification(
        iface["id"], certification_payload(
            window_starts_on="2026-09-01", window_ends_on="2026-09-10"),
        TEST_USERS["interface_engineer"]))
    assert cert1["status"] == "SCHEDULED"
    adjacent = api_client.create_certification(
        iface["id"], certification_payload(
            window_starts_on="2026-09-11", window_ends_on="2026-09-20"),
        TEST_USERS["interface_engineer"])
    validate_success(adjacent, expected_status=201)
    overlapping = api_client.create_certification(
        iface["id"], certification_payload(
            window_starts_on="2026-09-10", window_ends_on="2026-09-15"),
        TEST_USERS["interface_engineer"])
    validate_error(overlapping, ApiErrorId.ERR_CERTIFICATION_WINDOW_OVERLAP)


def test_certification_window_overlap_symmetric_direction():
    """PRD §3.6: "Windows of one interface follow the contiguous-touch rule: a
    new window is rejected with `ERR_CERTIFICATION_WINDOW_OVERLAP` (HTTP 409)
    only when it shares interior dates with a non-`CANCELLED` certification
    window of the same interface". PRD §3.6: "Adjacency, meaning one window's
    end plus one day equals the other's start, is allowed".

    Companion: a new window entirely before the existing one, ending the day
    before it starts, is adjacent and allowed; one overlapping the start fails.

    Design: Difficulty/resource_temporal_overlap/certification_window_adjacency_vs_overlap
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    iface = create_interface(ctx["contract"]["id"], name="StateGW")
    get_success_data(api_client.start_interface_development(
        iface["id"], TEST_USERS["interface_engineer"]))
    get_success_data(api_client.start_interface_testing(
        iface["id"], TEST_USERS["interface_engineer"]))
    get_success_data(api_client.create_certification(
        iface["id"], certification_payload(
            window_starts_on="2026-09-10", window_ends_on="2026-09-20"),
        TEST_USERS["interface_engineer"]))
    before_adjacent = api_client.create_certification(
        iface["id"], certification_payload(
            window_starts_on="2026-09-01", window_ends_on="2026-09-09"),
        TEST_USERS["interface_engineer"])
    validate_success(before_adjacent, expected_status=201)
    overlapping_start = api_client.create_certification(
        iface["id"], certification_payload(
            window_starts_on="2026-09-05", window_ends_on="2026-09-10"),
        TEST_USERS["interface_engineer"])
    validate_error(overlapping_start, ApiErrorId.ERR_CERTIFICATION_WINDOW_OVERLAP)


def test_certification_begin_outside_window_rejected():
    """PRD §3.6: "Beginning a certification (`SCHEDULED → IN_PROGRESS`)
    requires the parent interface to be `IN_TESTING` and the logical clock
    date to fall within the certification window inclusive — beginning outside
    the window is rejected with `ERR_CERTIFICATION_OUTSIDE_WINDOW` (HTTP 422)".

    Design: Corner/validations/certification_begin_outside_window_rejected
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    iface = create_interface(ctx["contract"]["id"], name="StateGW")
    get_success_data(api_client.start_interface_development(
        iface["id"], TEST_USERS["interface_engineer"]))
    get_success_data(api_client.start_interface_testing(
        iface["id"], TEST_USERS["interface_engineer"]))
    cert = get_success_data(api_client.create_certification(
        iface["id"], certification_payload(
            window_starts_on="2026-10-01", window_ends_on="2026-10-10"),
        TEST_USERS["interface_engineer"]))
    resp = api_client.begin_certification(cert["id"], TEST_USERS["interface_engineer"])
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_OUTSIDE_WINDOW)


def test_certification_pass_interface_certified_readiness_recompute():
    """PRD §3.6: "A pass cascades twice: the parent interface moves to
    `CERTIFIED` when this is its first `PASSED` certification, and the
    contract's readiness score is recomputed; a pass also appends an audit
    entry."

    Design: Difficulty/transitive_cascade/certification_pass_interface_certified_readiness_recompute
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    iface = create_interface(ctx["contract"]["id"], name="StateGW")
    get_success_data(api_client.start_interface_development(
        iface["id"], TEST_USERS["interface_engineer"]))
    get_success_data(api_client.start_interface_testing(
        iface["id"], TEST_USERS["interface_engineer"]))
    cert = get_success_data(api_client.create_certification(
        iface["id"], certification_payload(
            window_starts_on="2026-09-01", window_ends_on="2026-09-10"),
        TEST_USERS["interface_engineer"]))
    get_success_data(api_client.begin_certification(cert["id"], TEST_USERS["interface_engineer"]))
    gl = get_success_data(api_client.create_go_live_event(
        ctx["contract"]["id"], {"planned_date": "2026-12-01"},
        TEST_USERS["implementation_manager"]))
    before = get_success_data(api_client.get_go_live_event(
        gl["id"], TEST_USERS["implementation_manager"]))["readiness_score"]
    passed = get_success_data(api_client.pass_certification(
        cert["id"], TEST_USERS["agency_pm"]))
    assert passed["status"] == "PASSED"
    iface_after = get_success_data(api_client.get_interface(
        iface["id"], TEST_USERS["interface_engineer"]))
    assert iface_after["status"] == "CERTIFIED"
    after = get_success_data(api_client.get_go_live_event(
        gl["id"], TEST_USERS["implementation_manager"]))["readiness_score"]
    assert after == before + 20, "interface component (weight 20) must now be 100"


def test_certification_pass_recompute_visible_on_go_live_read():
    """PRD §3.6: "A pass cascades twice: the parent interface moves to
    `CERTIFIED` when this is its first `PASSED` certification, and the
    contract's readiness score is recomputed". PRD §3.11: "The interface
    component is one hundred times the number of endpoints in `CERTIFIED`,
    divided by the total number of endpoints — zero when there are none."

    Second test: from score 0 with one interface, a pass leaves the event's
    recomputed interface contribution at weight 20.

    Design: Difficulty/transitive_cascade/certification_pass_interface_certified_readiness_recompute
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    iface = create_interface(ctx["contract"]["id"], name="StateGW")
    get_success_data(api_client.start_interface_development(
        iface["id"], TEST_USERS["interface_engineer"]))
    get_success_data(api_client.start_interface_testing(
        iface["id"], TEST_USERS["interface_engineer"]))
    cert = get_success_data(api_client.create_certification(
        iface["id"], certification_payload(
            window_starts_on="2026-09-01", window_ends_on="2026-09-10"),
        TEST_USERS["interface_engineer"]))
    get_success_data(api_client.begin_certification(cert["id"], TEST_USERS["interface_engineer"]))
    gl = get_success_data(api_client.create_go_live_event(
        ctx["contract"]["id"], {"planned_date": "2026-12-01"},
        TEST_USERS["implementation_manager"]))
    assert get_success_data(api_client.get_go_live_event(
        gl["id"], TEST_USERS["implementation_manager"]))["readiness_score"] == 0
    get_success_data(api_client.pass_certification(cert["id"], TEST_USERS["agency_pm"]))
    assert get_success_data(api_client.get_go_live_event(
        gl["id"], TEST_USERS["implementation_manager"]))["readiness_score"] == 20
    assert get_success_data(api_client.get_interface(
        iface["id"], TEST_USERS["interface_engineer"]))["status"] == "CERTIFIED"


def test_tester_unavailability_closed_interval_touch_conflicts():
    """PRD §3.7: "Scheduling is refused with `ERR_TESTER_UNAVAILABLE` (HTTP
    422) in two cases: when the date falls inside any of the tester's
    unavailability windows, where the window is a closed interval and a session
    landing exactly on the window's first or last day does conflict; and when
    the tester's per-day session cap would be exceeded — under
    `parallel_operations` the tester may carry at most one session on a given
    date, otherwise at most two".

    Design: Difficulty/resource_temporal_overlap/tester_unavailability_closed_interval_touch_conflicts
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    agency = ctx["agency"]
    tester = create_uat_tester(agency["id"], full_name="T One", email="t1@x.gov",
                               tenure_years=5)
    get_success_data(api_client.create_unavailability_window(
        tester["id"],
        {"starts_on": "2026-09-03", "ends_on": "2026-09-05",
         "reason": "election duty"},
        TEST_USERS["agency_pm"]))
    cycle_a = get_success_data(api_client.create_uat_cycle(
        ctx["contract"]["id"], {"label": "UAT-A"}, TEST_USERS["agency_pm"]))
    cycle_b = get_success_data(api_client.create_uat_cycle(
        ctx["contract"]["id"],
        {"label": "UAT-B", "parallel_operations": True}, TEST_USERS["agency_pm"]))
    on_boundary = api_client.create_uat_session(
        cycle_a["id"],
        uat_session_payload(tester["id"], scenario_code="S1",
                            scheduled_on="2026-09-05"),
        TEST_USERS["agency_pm"])
    validate_error(on_boundary, ApiErrorId.ERR_TESTER_UNAVAILABLE)
    first = get_success_data(api_client.create_uat_session(
        cycle_a["id"],
        uat_session_payload(tester["id"], scenario_code="S2",
                            scheduled_on="2026-09-06"),
        TEST_USERS["agency_pm"]))
    second = get_success_data(api_client.create_uat_session(
        cycle_a["id"],
        uat_session_payload(tester["id"], scenario_code="S3",
                            scheduled_on="2026-09-06"),
        TEST_USERS["agency_pm"]))
    assert first["result"] == "SCHEDULED" and second["result"] == "SCHEDULED"
    third = api_client.create_uat_session(
        cycle_b["id"],
        uat_session_payload(tester["id"], scenario_code="S4",
                            scheduled_on="2026-09-06"),
        TEST_USERS["agency_pm"])
    validate_error(third, ApiErrorId.ERR_TESTER_UNAVAILABLE)


def test_tester_unavailability_first_day_of_window_conflicts():
    """PRD §3.7: "the window is a closed interval and a session landing exactly
    on the window's first or last day does conflict".

    Companion: the first day of the window conflicts just as the last does.

    Design: Difficulty/resource_temporal_overlap/tester_unavailability_closed_interval_touch_conflicts
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    agency = ctx["agency"]
    tester = create_uat_tester(agency["id"], full_name="T One", email="t1@x.gov")
    get_success_data(api_client.create_unavailability_window(
        tester["id"],
        {"starts_on": "2026-09-03", "ends_on": "2026-09-05",
         "reason": "election duty"},
        TEST_USERS["agency_pm"]))
    cycle = get_success_data(api_client.create_uat_cycle(
        ctx["contract"]["id"], {"label": "UAT-A"}, TEST_USERS["agency_pm"]))
    first_day = api_client.create_uat_session(
        cycle["id"],
        uat_session_payload(tester["id"], scheduled_on="2026-09-03"),
        TEST_USERS["agency_pm"])
    validate_error(first_day, ApiErrorId.ERR_TESTER_UNAVAILABLE)
    outside = api_client.create_uat_session(
        cycle["id"],
        uat_session_payload(tester["id"], scheduled_on="2026-09-02"),
        TEST_USERS["agency_pm"])
    validate_success(outside, expected_status=201)


def test_reference_not_found_on_fk_input():
    """PRD §3.7: "a `scenario_code`, an `assigned_tester_id` referencing a
    staff member who must hold the `UAT_TESTER` function (a missing tester
    returns `ERR_REFERENCE_NOT_FOUND`, HTTP 404)".

    Design: Corner/errors/reference_not_found_on_fk_input
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    cycle = get_success_data(api_client.create_uat_cycle(
        ctx["contract"]["id"], {"label": "UAT-1"}, TEST_USERS["agency_pm"]))
    resp = api_client.create_uat_session(
        cycle["id"],
        {"scenario_code": "S1", "assigned_tester_id": NON_EXISTENT_UUID,
         "scheduled_on": "2026-09-05"},
        TEST_USERS["agency_pm"])
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_training_capacity_exact_fit_allowed():
    """PRD §3.7: "an enrollment is allowed only when the consumed weight plus
    the new enrollment's weight is less than or equal to `capacity`, with an
    exactly-full fit allowed. Exceeding capacity is rejected with
    `ERR_SESSION_FULL` (HTTP 422)". PRD §3.7: "the enrolling staff member's
    `seat_weight` is 2 when their `tenure_years` is at least ten — the
    long-tenured change-management surcharge — and 1 otherwise."

    Design: Difficulty/boundary_precision_check/training_capacity_exact_fit_allowed
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    agency = ctx["agency"]
    apm = TEST_USERS["agency_pm"]
    l1 = get_success_data(api_client.create_staff(
        agency["id"], staff_payload(full_name="Long Timer", email="l1@x.gov",
                                    tenure_years=12), apm))
    s1 = get_success_data(api_client.create_staff(
        agency["id"], staff_payload(full_name="Short One", email="s1@x.gov",
                                    tenure_years=2), apm))
    s2 = get_success_data(api_client.create_staff(
        agency["id"], staff_payload(full_name="Short Two", email="s2@x.gov",
                                    tenure_years=1), apm))
    ts = get_success_data(api_client.create_training_session(
        ctx["contract"]["id"],
        training_session_payload(title="GL 101", capacity=3),
        TEST_USERS["implementation_manager"]))
    e1 = get_success_data(api_client.create_enrollment(
        ts["id"], {"staff_member_id": l1["id"]}, TEST_USERS["implementation_manager"]))
    assert e1["seat_weight"] == 2
    e2 = get_success_data(api_client.create_enrollment(
        ts["id"], {"staff_member_id": s1["id"]}, TEST_USERS["implementation_manager"]))
    assert e2["seat_weight"] == 1
    resp = api_client.create_enrollment(
        ts["id"], {"staff_member_id": s2["id"]}, TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL)


def test_training_capacity_exact_fit_at_capacity_minus_one():
    """PRD §3.7: "an enrollment is allowed only when the consumed weight plus
    the new enrollment's weight is less than or equal to `capacity`, with an
    exactly-full fit allowed. Exceeding capacity is rejected with
    `ERR_SESSION_FULL` (HTTP 422)".

    Boundary companion: capacity 2 with a single long-tenured enrollee (weight
    2) fits exactly; the next weight-1 enrollment overflows.

    Design: Difficulty/boundary_precision_check/training_capacity_exact_fit_allowed
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    agency = ctx["agency"]
    apm = TEST_USERS["agency_pm"]
    l1 = get_success_data(api_client.create_staff(
        agency["id"], staff_payload(full_name="Long Timer", email="l1@x.gov",
                                    tenure_years=12), apm))
    s1 = get_success_data(api_client.create_staff(
        agency["id"], staff_payload(full_name="Short One", email="s1@x.gov",
                                    tenure_years=2), apm))
    ts = get_success_data(api_client.create_training_session(
        ctx["contract"]["id"],
        training_session_payload(title="GL 101", capacity=2),
        TEST_USERS["implementation_manager"]))
    e1 = get_success_data(api_client.create_enrollment(
        ts["id"], {"staff_member_id": l1["id"]}, TEST_USERS["implementation_manager"]))
    assert e1["seat_weight"] == 2
    resp = api_client.create_enrollment(
        ts["id"], {"staff_member_id": s1["id"]}, TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL)


def test_training_capacity_conservation_across_cancel():
    """PRD §3.7: "cancelling a session moves it `SCHEDULED → CANCELLED` and
    cascades every enrollment to `WITHDRAWN`." PRD §3.7: "The session's
    consumed capacity is the sum of `seat_weight` over its enrollments whose
    `outcome` is `ENROLLED` or `COMPLETED`".

    Design: Difficulty/compensating_invariant/training_capacity_conservation_across_cancel
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    agency = ctx["agency"]
    apm = TEST_USERS["agency_pm"]
    impl = TEST_USERS["implementation_manager"]
    l1 = get_success_data(api_client.create_staff(
        agency["id"], staff_payload(full_name="Long Timer", email="l1@x.gov",
                                    tenure_years=12), apm))
    s1 = get_success_data(api_client.create_staff(
        agency["id"], staff_payload(full_name="Short One", email="s1@x.gov",
                                    tenure_years=2), apm))
    ts1 = get_success_data(api_client.create_training_session(
        ctx["contract"]["id"], training_session_payload(title="GL 101", capacity=3), impl))
    e1 = get_success_data(api_client.create_enrollment(
        ts1["id"], {"staff_member_id": l1["id"]}, impl))
    e2 = get_success_data(api_client.create_enrollment(
        ts1["id"], {"staff_member_id": s1["id"]}, impl))
    get_success_data(api_client.cancel_training_session(ts1["id"], impl))
    rows, _meta = validate_paginated(api_client.list_enrollments(ts1["id"], impl))
    by_id = {r["id"]: r for r in rows}
    assert by_id[e1["id"]]["outcome"] == "WITHDRAWN"
    assert by_id[e2["id"]]["outcome"] == "WITHDRAWN"
    ts2 = get_success_data(api_client.create_training_session(
        ctx["contract"]["id"],
        training_session_payload(title="GL 102", scheduled_on="2026-10-02",
                                 capacity=3), impl))
    e3 = get_success_data(api_client.create_enrollment(
        ts2["id"], {"staff_member_id": l1["id"]}, impl))
    e4 = get_success_data(api_client.create_enrollment(
        ts2["id"], {"staff_member_id": s1["id"]}, impl))
    assert e3["seat_weight"] + e4["seat_weight"] == 3


def test_training_cancel_releases_exact_consumed_weight():
    """PRD §3.7: "cancelling a session moves it `SCHEDULED → CANCELLED` and
    cascades every enrollment to `WITHDRAWN`." PRD §3.7: "an enrollment is
    allowed only when the consumed weight plus the new enrollment's weight is
    less than or equal to `capacity`, with an exactly-full fit allowed."

    Companion: after cancel, a fresh session accepts the same roster to its
    exact-fit boundary — no seats leak from the cancelled session.

    Design: Difficulty/compensating_invariant/training_capacity_conservation_across_cancel
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    agency = ctx["agency"]
    apm = TEST_USERS["agency_pm"]
    impl = TEST_USERS["implementation_manager"]
    staff_ids = []
    for i, tenure in enumerate((12, 2, 1)):
        s = get_success_data(api_client.create_staff(
            agency["id"],
            staff_payload(full_name=f"S{i}", email=f"s{i}@x.gov",
                          tenure_years=tenure), apm))
        staff_ids.append(s["id"])
    ts1 = get_success_data(api_client.create_training_session(
        ctx["contract"]["id"], training_session_payload(title="T1", capacity=3), impl))
    get_success_data(api_client.create_enrollment(
        ts1["id"], {"staff_member_id": staff_ids[0]}, impl))
    get_success_data(api_client.create_enrollment(
        ts1["id"], {"staff_member_id": staff_ids[1]}, impl))
    get_success_data(api_client.cancel_training_session(ts1["id"], impl))
    ts2 = get_success_data(api_client.create_training_session(
        ctx["contract"]["id"],
        training_session_payload(title="T2", scheduled_on="2026-10-02",
                                 capacity=3), impl))
    for sid in staff_ids[:2]:
        get_success_data(api_client.create_enrollment(
            ts2["id"], {"staff_member_id": sid}, impl))
    resp = api_client.create_enrollment(
        ts2["id"], {"staff_member_id": staff_ids[2]}, impl)
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL)


def test_audit_log_records_mutations_in_order():
    """PRD §2.10: "Contract creation, the draft-to-posted step, protest
    resolution and the other award-path transitions, award itself, contract
    close, milestone acceptance and payment, decision ratification,
    migration-batch acceptance, certification passes, UAT cycle completion,
    go-live approval, execution, and rollback, support-transition advancement,
    and maintenance activation and renewal each append an entry." PRD §2.10:
    "The hash is the SHA-256 of the previous entry's `entry_hash` for the same
    contract concatenated with the canonical detail of the current entry; the
    first entry of a contract's chain is seeded with an empty string."

    Design: Corner/endpoints/audit_log_records_mutations_in_order
    """
    reset_clock()
    agency = create_agency()
    contract = create_draft_contract(agency["id"])
    get_success_data(api_client.transition_contract(
        contract["id"], {"target": "POSTED"}, TEST_USERS["procurement_officer"]))
    rows, _meta = validate_paginated(api_client.list_audit_log(
        contract["id"], TEST_USERS["platform_admin"]))
    assert len(rows) >= 2
    for row in rows:
        assert row["actor_role"] == "ProcurementOfficer"
        assert isinstance(row["entry_hash"], str)
    hashes = [r["entry_hash"] for r in rows]
    assert len(set(hashes)) == len(hashes), "hash chain must link distinct entries"
