"""Corner — state machines: screening transitions, check-in bounds, relist, no-show sweep, appeal gate."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    create_station,
    create_published_block,
    register_driver,
    latest_screening_id,
    begin_screening_review,
    decide_screening,
    onboard_active_driver,
    deactivate_driver,
    submit_appeal,
    accept_block,
    check_in,
    forfeit,
    get_assignment,
    get_block,
    get_driver,
    make_driver_headers,
    validate_error,
    validate_success,
    validate_paginated,
    run_surge_cycle,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["appeals_reviewer_headers"]


class TestScreeningTransitions:
    def test_screening_clear_happy_path_records_decided_at(self, api):
        """PRD §3.1: "A clearing decision moves the screening to `CLEARED`, records the
        logical-clock instant in `decided_at`, and leaves `failure_reason` null."
        PRD §2.4: "Before any clock-setting call, the logical clock reads exactly
        2026-09-01T00:00:00Z, and it never falls back to wall-clock time."

        Design: Corner/state_machines/screening_clear_happy_path_records_decided_at
        """
        set_clock("2026-09-01T00:00:00Z")
        driver = register_driver()
        sc = latest_screening_id(driver["id"])
        begin_screening_review(sc)
        cleared = decide_screening(sc, "CLEARED")

        assert cleared["status"] == "CLEARED"
        assert cleared["decided_at"] is not None
        assert cleared["decided_at"].startswith("2026-09-01T00:00:00")
        assert cleared["failure_reason"] is None

    def test_decide_from_initiated_rejected_invalid_state(self, api):
        """PRD §3.1: "Screening review is administrative. A `PlatformAdmin` begins
        review, moving the screening from `INITIATED` to `IN_REVIEW`, and then decides
        it."

        Design: Corner/state_machines/decide_from_initiated_rejected_invalid_state
        """
        set_clock()
        driver = register_driver()
        sc = latest_screening_id(driver["id"])

        resp = api_client.decide_screening(sc, {"decision": "CLEARED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # State is unchanged.
        data, meta = validate_paginated(
            api_client.list_driver_screenings(driver["id"], ADMIN)
        )
        assert data[0]["status"] == "INITIATED"

    def test_failed_decision_missing_reason_rejected(self, api):
        """PRD §3.1: "A failing decision moves it to `FAILED`, records `decided_at` the
        same way, and requires a `failure_reason` in the request."
        PRD §2.5: "The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role permission and ownership (`ERR_FORBIDDEN`, or `ERR_OFFER_WRONG_DRIVER` for wrong-driver offer actions); third, existence of path and body references (`ERR_NOT_FOUND`); fourth, state-machine legality, including the domain state errors `ERR_DRIVER_NOT_ACTIVE` and `ERR_BLOCK_NOT_PUBLISHED`, all rejected with `ERR_INVALID_STATE` or the named domain error (HTTP 409); fifth, business safety gates — screening, vehicle, and insurance checks such as `ERR_SCREENING_NOT_CLEARED`, `ERR_NO_ELIGIBLE_VEHICLE`, `ERR_INSURANCE_NOT_ATTESTED`, `ERR_VEHICLE_CLASS_MISMATCH`, and `ERR_INSURANCE_WINDOW_LAPSE`; sixth, temporal business gates such as `ERR_BLOCK_NOT_VISIBLE_YET`, `ERR_BLOCK_WINDOW_OVERLAP`, `ERR_OFFER_BUFFER_CONFLICT`, `ERR_OFFER_EXPIRED`, `ERR_CHECKIN_TOO_EARLY`, and `ERR_CHECKIN_WINDOW_CLOSED`; seventh, aggregate and uniqueness constraints such as `ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_VIN`, and `ERR_APPEAL_NOT_OPEN`; eighth, money-side and optimistic-concurrency checks including `ERR_STALE_VERSION`; and ninth, request body shape (`ERR_VALIDATION` for malformed JSON, missing required fields, invalid enum members, or unparseable datetimes)."

        Design: Corner/state_machines/failed_decision_missing_reason_rejected
        """
        set_clock()
        driver = register_driver()
        sc = latest_screening_id(driver["id"])
        begin_screening_review(sc)

        resp = api_client.decide_screening(sc, {"decision": "FAILED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        data, meta = validate_paginated(
            api_client.list_driver_screenings(driver["id"], ADMIN)
        )
        assert data[0]["status"] == "IN_REVIEW"

    def test_cleared_screening_reopen_rejected_terminal(self, api):
        """PRD §3.1: "Failure is not final: the affected driver may reopen their own
        screening, moving it from `FAILED` back to `IN_REVIEW` and clearing
        `failure_reason` to null, and this fail–reopen loop may repeat without bound."

        Design: Corner/state_machines/cleared_screening_reopen_rejected_terminal
        """
        set_clock()
        driver = register_driver()
        sc = latest_screening_id(driver["id"])
        begin_screening_review(sc)
        decide_screening(sc, "CLEARED")

        resp = api_client.reopen_screening(sc, make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        data, meta = validate_paginated(
            api_client.list_driver_screenings(driver["id"], ADMIN)
        )
        assert data[0]["status"] == "CLEARED"


class TestCheckinBounds:
    def test_checkin_too_early_rejected_upper_bound_inclusive(self, api):
        """PRD §3.4: "Check-in moves the assignment from `ASSIGNED` to `CHECKED_IN` and
        is bounded on both sides: it may not happen earlier than 30 minutes before the
        block's `starts_at` (otherwise `ERR_CHECKIN_TOO_EARLY`), and may not happen
        later than 15 minutes after `starts_at` (otherwise `ERR_CHECKIN_WINDOW_CLOSED`);
        both bounds are inclusive. … A successful check-in stamps `check_in_at` with the
        logical-clock instant and advances the block itself from `ASSIGNED` to
        `IN_PROGRESS`."

        Design: Corner/state_machines/checkin_too_early_rejected_upper_bound_inclusive
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        assignment = accept_block(block["id"], driver["id"], vehicle["id"])

        # 31 minutes before starts_at: too early.
        set_clock("2026-09-01T01:29:00Z")
        resp = api_client.check_in_assignment(
            assignment["id"], make_driver_headers(driver["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CHECKIN_TOO_EARLY)

        # Exactly starts_at + 15 minutes: inclusive upper bound, succeeds.
        set_clock("2026-09-01T02:15:00Z")
        checked = check_in(assignment["id"], driver["id"])
        assert checked["status"] == "CHECKED_IN"
        assert get_block(block["id"])["status"] == "IN_PROGRESS"


class TestForfeitAndRelist:
    def test_forfeit_relists_block_published_relist_cycle(self, api):
        """PRD §3.7: "The forfeit stamps `forfeited_at`, records `forfeit_cause` as
        `DRIVER_INITIATED`, leaves `strike_reversed` false, and immediately relists the
        block: the block returns from `ASSIGNED` to `PUBLISHED` with
        `assigned_driver_id` cleared, and — importantly — its `surge_multiplier_bp` and
        `estimated_pay_cents` are retained, not reset."

        Design: Corner/state_machines/forfeit_relists_block_published_relist_cycle
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T12:00:00Z",
            ends_at="2026-09-01T14:00:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")
        assignment = accept_block(block["id"], driver["id"], vehicle["id"])

        forfeited = forfeit(assignment["id"], driver["id"])
        assert forfeited["status"] == "FORFEITED"
        assert forfeited["forfeit_cause"] == "DRIVER_INITIATED"
        assert forfeited["strike_reversed"] is False

        block_after = get_block(block["id"])
        assert block_after["status"] == "PUBLISHED"
        assert block_after["assigned_driver_id"] is None
        assert block_after["estimated_pay_cents"] == 4000
        assert block_after["surge_multiplier_bp"] == 10000

    def test_forfeit_after_checkin_rejected_invalid_state(self, api):
        """PRD §3.7: "A driver may forfeit an assignment while it is still `ASSIGNED`,
        optionally giving a `reason`. … Once a driver has checked in, driver-initiated
        forfeit is no longer available."

        Design: Corner/state_machines/forfeit_after_checkin_rejected_invalid_state
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        assignment = accept_block(block["id"], driver["id"], vehicle["id"])
        set_clock("2026-09-01T01:45:00Z")
        check_in(assignment["id"], driver["id"])

        resp = api_client.forfeit_assignment(
            assignment["id"], {}, make_driver_headers(driver["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        assert get_assignment(assignment["id"])["status"] == "CHECKED_IN"
        assert get_driver(driver["id"])["reliability_score_bp"] == 10000


class TestNoShowSweep:
    def test_surge_cycle_sweeps_no_show_and_relists_block(self, api):
        """PRD §3.7: "A driver who simply never arrives is swept by the surge cycle:
        when an assignment is still `ASSIGNED` and the logical clock has reached 15
        minutes past the block's `starts_at`, the assignment becomes `NO_SHOW` with
        `no_show_at` stamped, the block is relisted the same way, and the strike costs
        1000 basis points instead."

        Design: Corner/state_machines/surge_cycle_sweeps_no_show_and_relists_block
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T01:00:00Z")
        assignment = accept_block(block["id"], driver["id"], vehicle["id"])

        # Exactly starts_at + 15 minutes: inclusive no-show boundary.
        set_clock("2026-09-01T02:15:00Z")
        run_surge_cycle(station["id"], station["version"])

        swept = get_assignment(assignment["id"])
        assert swept["status"] == "NO_SHOW"
        assert get_driver(driver["id"])["reliability_score_bp"] == 9000
        block_after = get_block(block["id"])
        assert block_after["status"] == "PUBLISHED"
        assert block_after["assigned_driver_id"] is None


class TestAppealDecideGate:
    def test_appeal_decide_without_evidence_rejected(self, api):
        """PRD §3.8: "Decision requires at least one piece of evidence: a reviewer
        deciding an appeal with `evidence_count` still at 0 cannot proceed."

        Design: Corner/state_machines/appeal_decide_without_evidence_rejected
        """
        set_clock()
        driver, vehicle, _s = onboard_active_driver()
        deactivate_driver(driver["id"], reason="policy violation")
        appeal = submit_appeal(driver["id"], reason="mistaken identity")
        assert appeal["status"] == "SUBMITTED"
        assert appeal["evidence_count"] == 0

        resp = api_client.decide_appeal(appeal["id"], {"decision": "UPHELD"}, REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        data, meta = validate_paginated(
            api_client.list_driver_appeals(
                driver["id"], make_driver_headers(driver["id"])
            )
        )
        assert data[0]["status"] == "SUBMITTED"
        assert data[0]["evidence_count"] == 0
