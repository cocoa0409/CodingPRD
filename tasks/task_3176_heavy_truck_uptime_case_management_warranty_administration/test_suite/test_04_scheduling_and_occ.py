"""Scheduling constraints: priority conflicts, dealer availability, bay
time-conflict half-open intervals, and OCC stale-version checks."""
from test_helpers import (
    ApiErrorId,
    setup_case_in_state,
    setup_clock,
    setup_full_environment,
    validate_error,
    validate_paginated,
    validate_success,
    create_case_payload,
)

SCHED_START = "2026-09-01T13:00:00Z"
SCHED_END = "2026-09-01T17:00:00Z"


def _schedule(api, env, case_id, start=SCHED_START, end=SCHED_END, **overrides):
    fid, tid = env["fleet"]["id"], env["truck"]["id"]
    truck_now = validate_success(api.get_truck(fid, tid, env["fm"]))
    payload = {
        "dealer_id": env["dealer"]["id"],
        "bay_id": env["bay"]["id"],
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "expected_truck_version": truck_now["version"],
    }
    payload.update(overrides)
    return api.schedule_case(fid, tid, case_id, payload, env["uc"])


def _new_triaged_case(api, env, fault_code="SPN3216_FMI4"):
    fid, tid = env["fleet"]["id"], env["truck"]["id"]
    case = validate_success(
        api.create_case(fid, tid, create_case_payload(fault_code=fault_code), env["uc"]),
        expected_status=201,
    )
    return validate_success(api.triage_case(fid, tid, case["id"], env["uc"]))


class TestPriorityPairConflict:
    def test_state_vs_business_safety_case_schedule_both_violated(self, api):
        """PRD §3.3: "From `TRIAGE`, the coordinator schedules the case onto a
        specific dealer's bay by supplying `dealer_id`, `bay_id`,
        `scheduled_start_at`, `scheduled_end_at`, the OCC field
        `expected_truck_version`, and an optional `allow_cross_region` flag."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_case_schedule_both_violated
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Prio Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        # Case A occupies the bay 13:00-17:00 with an AUTHORIZED work order.
        ctx = setup_case_in_state(env, "SCHEDULED")
        case_a = ctx["case"]
        validate_success(
            api.authorize_work_order(
                fid, tid, case_a["id"], ctx["work_order"]["id"],
                {"diagnostic_minutes_authorized": 30}, env["uc"],
            )
        )
        # Case B is in OPEN (never TRIAGED) — schedule from OPEN is invalid.
        case_b = validate_success(
            api.create_case(fid, tid, create_case_payload(fault_code="SPN3226_FMI4"), env["uc"]),
            expected_status=201,
        )
        assert case_b["case_status"] == "OPEN"

        resp = _schedule(api, env, case_b["id"], start="2026-09-01T14:00:00Z", end="2026-09-01T16:00:00")
        body = resp.json()
        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, (
            f"state check must win over bay conflict, got {body['data']['error_id']}"
        )
        assert body["data"]["error_id"] != ApiErrorId.ERR_BAY_TIME_CONFLICT.value

    def test_open_case_schedule_rejected_even_with_free_bay(self, api):
        """PRD §3.3: "From `TRIAGE`, the coordinator schedules the case onto a
        specific dealer's bay by supplying `dealer_id`, `bay_id`,
        `scheduled_start_at`, `scheduled_end_at`, the OCC field
        `expected_truck_version`, and an optional `allow_cross_region` flag."
        and PRD §5: "`ERR_INVALID_STATE_TRANSITION` | 409 Conflict".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_case_schedule_both_violated
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Prio1b Fleet")
        case_b = validate_success(
            api.create_case(
                env["fleet"]["id"], env["truck"]["id"],
                create_case_payload(fault_code="SPN3226_FMI4"), env["uc"],
            ),
            expected_status=201,
        )
        resp = _schedule(api, env, case_b["id"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


class TestDealerAvailability:
    def test_case_schedule_blocked_by_cross_region_dealer(self, api):
        """PRD §3.3: "Then the dealer-availability check — the dealer's
        `dealer_status` must be `ACTIVE`, and the dealer's `region` must match
        the fleet's `home_region` unless the request sets `allow_cross_region`
        to true; a suspended dealer or a cross-region dispatch without that
        flag is rejected with `ERR_DEALER_NOT_AVAILABLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/case_schedule_blocked_by_suspended_dealer
        """
        setup_clock()
        env = setup_full_environment(
            fleet_name="XRegion Fleet", home_region="SE", dealer_region="PNW"
        )
        case = _new_triaged_case(api, env)
        resp = _schedule(api, env, case["id"])
        validate_error(resp, ApiErrorId.ERR_DEALER_NOT_AVAILABLE.value, expected_status=409)
        after = validate_success(
            api.get_case(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        )
        assert after["case_status"] == "TRIAGE"
        bay = validate_success(api.get_bay_by_id(env["bay"]["id"], env["uc"]))
        assert bay["bay_status"] == "AVAILABLE"

    def test_case_schedule_with_matching_region_succeeds(self, api):
        """PRD §3.3: "Then the dealer-availability check — the dealer's
        `dealer_status` must be `ACTIVE`, and the dealer's `region` must match
        the fleet's `home_region` unless the request sets `allow_cross_region`
        to true; a suspended dealer or a cross-region dispatch without that
        flag is rejected with `ERR_DEALER_NOT_AVAILABLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/case_schedule_blocked_by_suspended_dealer
        """
        setup_clock()
        env = setup_full_environment(
            fleet_name="InRegion Fleet", home_region="SE", dealer_region="SE"
        )
        case = _new_triaged_case(api, env)
        scheduled = validate_success(_schedule(api, env, case["id"]))
        assert scheduled["case_status"] == "SCHEDULED", (
            "an ACTIVE dealer in the fleet's home region satisfies the dependency"
        )

    def test_case_close_blocked_by_under_review_claim(self, api):
        """PRD §3.6: "A case cannot be closed while any of its claims is in
        `SUBMITTED` or `UNDER_REVIEW`: such a close is rejected with
        `ERR_CASE_HAS_OPEN_CLAIM` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/case_close_blocked_by_under_review_claim
        """
        setup_clock()
        env = setup_full_environment(fleet_name="XDep Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        claim = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                {"claim_type": "BASE_WARRANTY", "labor_minutes_claimed": 100, "parts_claimed_cents": 50000},
                env["wa"],
            ),
            expected_status=201,
        )
        case_now = validate_success(api.get_case(fid, tid, case["id"], env["uc"]))
        validate_success(
            api.submit_claim(
                fid, tid, case["id"], claim["id"],
                {"expected_case_version": case_now["version"]}, env["wa"],
            )
        )
        validate_success(api.begin_review_claim(fid, tid, case["id"], claim["id"], env["wa"]))

        resp = api.close_case(fid, tid, case["id"], env["uc"])
        validate_error(resp, ApiErrorId.ERR_CASE_HAS_OPEN_CLAIM.value, expected_status=409)
        after = validate_success(api.get_case(fid, tid, case["id"], env["uc"]))
        assert after["case_status"] == "PENDING_CLOSE"

    def test_case_close_succeeds_once_claim_adjudicated(self, api):
        """PRD §3.6: "A case cannot be closed while any of its claims is in
        `SUBMITTED` or `UNDER_REVIEW`: such a close is rejected with
        `ERR_CASE_HAS_OPEN_CLAIM` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/case_close_blocked_by_under_review_claim
        """
        setup_clock()
        env = setup_full_environment(fleet_name="XDep2 Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        claim = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                {"claim_type": "BASE_WARRANTY", "labor_minutes_claimed": 100, "parts_claimed_cents": 50000},
                env["wa"],
            ),
            expected_status=201,
        )
        case_now = validate_success(api.get_case(fid, tid, case["id"], env["uc"]))
        validate_success(
            api.submit_claim(
                fid, tid, case["id"], claim["id"],
                {"expected_case_version": case_now["version"]}, env["wa"],
            )
        )
        # Adjudicate: SUBMITTED -> UNDER_REVIEW -> DENIED (terminal).
        validate_success(api.begin_review_claim(fid, tid, case["id"], claim["id"], env["wa"]))
        denied = validate_success(api.deny_claim(fid, tid, case["id"], claim["id"], env["wa"]))
        assert denied["submission_status"] == "DENIED"

        closed = validate_success(api.close_case(fid, tid, case["id"], env["uc"]))
        assert closed["case_status"] == "CLOSED", (
            "with no claim in SUBMITTED or UNDER_REVIEW the close dependency is satisfied"
        )


class TestBayTimeConflictHalfOpen:
    def test_service_bay_half_open_interval_overlap(self, api):
        """PRD §3.3: "the bay must be `AVAILABLE` for the requested window, and
        no other `AUTHORIZED` or `IN_PROGRESS` work order on the same bay may
        have an overlapping `[start, end)` interval with the requested one; a
        conflict is rejected with `ERR_BAY_TIME_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/service_bay_half_open_interval_overlap
        """
        setup_clock()
        env = setup_full_environment(fleet_name="BayOvl Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        # Case B occupies bay 13:00-17:00 with an AUTHORIZED work order.
        case_b = _new_triaged_case(api, env, fault_code="SPN3226_FMI4")
        scheduled_b = validate_success(_schedule(api, env, case_b["id"]))
        assert scheduled_b["case_status"] == "SCHEDULED"
        wos_b = validate_paginated(api.list_work_orders(fid, tid, case_b["id"], env["uc"]))[0]
        validate_success(
            api.authorize_work_order(
                fid, tid, case_b["id"], wos_b[0]["id"],
                {"diagnostic_minutes_authorized": 30}, env["uc"],
            )
        )

        # Case C touches the boundary: 17:00-19:00 must be allowed.
        case_c = _new_triaged_case(api, env, fault_code="SPN168_FMI4")
        resp_c = _schedule(api, env, case_c["id"], start="2026-09-01T17:00:00Z", end="2026-09-01T19:00:00Z")
        scheduled_c = validate_success(resp_c)
        assert scheduled_c["case_status"] == "SCHEDULED", (
            "touching half-open boundary [13:00,17:00) vs [17:00,19:00) must be accepted"
        )

        # Case D overlaps by one minute: 16:59-18:00 must be rejected.
        case_d = _new_triaged_case(api, env, fault_code="SPN3216_FMI4")
        resp_d = _schedule(api, env, case_d["id"], start="2026-09-01T16:59:00Z", end="2026-09-01T18:00:00Z")
        validate_error(resp_d, ApiErrorId.ERR_BAY_TIME_CONFLICT.value, expected_status=409)
        after_d = validate_success(api.get_case(fid, tid, case_d["id"], env["uc"]))
        assert after_d["case_status"] == "TRIAGE"

    def test_service_bay_exact_adjacency_allowed_when_touching(self, api):
        """PRD §3.3: "the bay must be `AVAILABLE` for the requested window, and
        no other `AUTHORIZED` or `IN_PROGRESS` work order on the same bay may
        have an overlapping `[start, end)` interval with the requested one; a
        conflict is rejected with `ERR_BAY_TIME_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/service_bay_half_open_interval_overlap
        """
        setup_clock()
        env = setup_full_environment(fleet_name="BayOvl2 Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        case_a = _new_triaged_case(api, env, fault_code="SPN3226_FMI4")
        validate_success(
            _schedule(api, env, case_a["id"], start="2026-09-01T13:00:00Z", end="2026-09-01T17:00:00Z")
        )
        wos_a = validate_paginated(api.list_work_orders(fid, tid, case_a["id"], env["uc"]))[0]
        validate_success(
            api.authorize_work_order(
                fid, tid, case_a["id"], wos_a[0]["id"],
                {"diagnostic_minutes_authorized": 30}, env["uc"],
            )
        )
        # Touching at the boundary: end of A == start of B is NOT an overlap
        # under half-open [start, end) semantics.
        case_b = _new_triaged_case(api, env, fault_code="SPN168_FMI4")
        scheduled_b = validate_success(
            _schedule(api, env, case_b["id"], start="2026-09-01T17:00:00Z", end="2026-09-01T18:00:00Z")
        )
        assert scheduled_b["case_status"] == "SCHEDULED"

    def test_satisfaction_of_bay_availability_allows_schedule(self, api):
        """PRD §3.3: "Scheduling enforces its business checks in order: first
        the bay-time check — the bay must be `AVAILABLE` for the requested
        window, and no other `AUTHORIZED` or `IN_PROGRESS` work order on the
        same bay may have an overlapping `[start, end)` interval with the
        requested one"

        Design: Corner/validations/satisfaction_of_bay_availability_allows_schedule
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Sat Fleet")
        case = _new_triaged_case(api, env)
        resp = _schedule(api, env, case["id"], start="2026-09-01T14:00:00Z", end="2026-09-01T17:00:00Z")
        scheduled = validate_success(resp)
        assert scheduled["case_status"] == "SCHEDULED"
        bay = validate_success(api.get_bay_by_id(env["bay"]["id"], env["uc"]))
        assert bay["bay_status"] == "RESERVED"


class TestStaleVersionOnSchedule:
    def test_err_stale_version_on_case_schedule(self, api):
        """PRD §2.8: "Scheduling a case requires the request to carry
        `expected_truck_version` equal to the truck's current `version`. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/err_stale_version_on_case_schedule
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Stale Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        stale_version = env["truck"]["version"]
        case = _new_triaged_case(api, env)
        resp = api.schedule_case(
            fid,
            tid,
            case["id"],
            {
                "dealer_id": env["dealer"]["id"],
                "bay_id": env["bay"]["id"],
                "scheduled_start_at": "2026-09-01T14:00:00Z",
                "scheduled_end_at": "2026-09-01T17:00:00Z",
                "expected_truck_version": stale_version,
            },
            env["uc"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
        after = validate_success(api.get_case(fid, tid, case["id"], env["uc"]))
        assert after["case_status"] == "TRIAGE"

    def test_schedule_with_fresh_truck_version_succeeds(self, api):
        """PRD §2.8: "Scheduling a case requires the request to carry
        `expected_truck_version` equal to the truck's current `version`. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/err_stale_version_on_case_schedule
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Fresh Fleet")
        case = _new_triaged_case(api, env)
        resp = _schedule(api, env, case["id"])
        scheduled = validate_success(resp)
        assert scheduled["case_status"] == "SCHEDULED"
