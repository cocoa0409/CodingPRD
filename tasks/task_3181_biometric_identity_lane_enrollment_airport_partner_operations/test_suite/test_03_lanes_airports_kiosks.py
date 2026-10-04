"""Lanes, airports, and kiosks: lane open/maintenance cycle, capacity cascades,
agreement termination cascade, airport suspension cascade, lane-open gating,
priority of agreement-state over capacity, and kiosk auto-suspension."""
from test_helpers import (
    ApiErrorId,
    create_active_agreement,
    create_active_kiosk,
    create_agreement,
    create_airport,
    create_enrollment_center,
    create_kiosk,
    create_lane,
    create_open_lane,
    enroll_member_at_center,
    make_member_headers,
    open_enrollment,
    register_member,
    set_clock,
    setup_airport_with_active_agreement,
    submit_document,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.fixtures import OPS, PM


class TestLaneOpenMaintenanceCycle:
    def test_open_maintenance_open_cycle_preserves_capacity(self, api):
        """PRD §3.1: "The agreement's `lane_capacity` is the sum of `capacity_hours` across
        its lanes in `OPEN` or `MAINTENANCE`; `PLANNED` and `CLOSED` lanes do not
        count." and "Because `MAINTENANCE` lanes already count toward `lane_capacity`,
        re-opening a maintenance lane leaves the total unchanged, while opening a
        planned lane raises it."

        Design: Difficulty/non_linear_state_machine/lane_open_maintenance_open_cycle_before_close
        """
        airport, agreement = setup_airport_with_active_agreement(
            "SFO", staffing_footprint_seats=4
        )
        lane = create_open_lane(
            airport["id"], agreement["id"], terminal="T2", position_index=1,
            open_time="05:00", close_time="22:00", capacity_hours=6,
        )
        created_version = lane["version"]
        maintained = validate_success(api.close_lane(lane["id"], "MAINTENANCE", OPS))
        assert maintained["status"] == "MAINTENANCE"
        reopened = validate_success(api.open_lane(lane["id"], OPS))
        assert reopened["status"] == "OPEN"
        agreement_after = validate_success(api.get_agreement(agreement["id"], PM))
        assert agreement_after["lane_capacity"] == 6, (
            "MAINTENANCE lanes still count, so capacity never dropped during the cycle"
        )
        assert reopened["version"] == created_version + 2, (
            f"close + reopen = 2 mutations after create_open_lane, got version {reopened['version']}"
        )

    def test_closed_lane_is_terminal_for_reopen(self, api):
        """PRD §3.1: "Closing a lane takes a `mode`: maintenance mode moves an `OPEN` lane
        to `MAINTENANCE`, while closed mode moves an `OPEN` or `MAINTENANCE` lane to
        `CLOSED`." — no transition leads out of CLOSED, and per PRD §2.8 state
        legality failures surface `ERR_INVALID_STATE`.

        Design: Difficulty/non_linear_state_machine/lane_open_maintenance_open_cycle_before_close
        """
        airport, agreement = setup_airport_with_active_agreement(
            "SFO", staffing_footprint_seats=4
        )
        lane = create_open_lane(
            airport["id"], agreement["id"], terminal="T2", position_index=1,
            open_time="05:00", close_time="22:00", capacity_hours=6,
        )
        closed = validate_success(api.close_lane(lane["id"], "CLOSED", OPS))
        assert closed["status"] == "CLOSED"
        resp = api.open_lane(lane["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAgreementTerminationCascade:
    def test_terminate_closes_lanes_and_zeroes_capacity(self, api):
        """PRD §3.1: "Terminating an agreement, from either `ACTIVE` or `SUSPENDED`, moves
        every lane of that agreement in `PLANNED`, `OPEN`, or `MAINTENANCE` to
        `CLOSED` and drives `lane_capacity` to zero, releasing each lane's hours from
        the airport-day capacity pool so the airport's capacity accounting returns to
        zero."

        Design: Difficulty/transitive_cascade/agreement_terminate_cascades_lanes_then_capacity_zero
        """
        airport, agreement = setup_airport_with_active_agreement(
            "ORD", staffing_footprint_seats=4
        )
        lane1 = create_open_lane(
            airport["id"], agreement["id"], terminal="T1", position_index=1,
            open_time="05:00", close_time="22:00", capacity_hours=6,
        )
        lane2 = create_open_lane(
            airport["id"], agreement["id"], terminal="T3", position_index=2,
            open_time="05:00", close_time="22:00", capacity_hours=4,
        )
        agreement_mid = validate_success(api.get_agreement(agreement["id"], PM))
        assert agreement_mid["lane_capacity"] == 10
        terminated = validate_success(api.terminate_agreement(agreement["id"], PM))
        assert terminated["status"] == "TERMINATED"
        agreement_after = validate_success(api.get_agreement(agreement["id"], PM))
        assert agreement_after["lane_capacity"] == 0
        for lane in (lane1, lane2):
            lane_after = validate_success(api.get_lane(lane["id"], OPS))
            assert lane_after["status"] == "CLOSED"

    def test_reopen_after_termination_rejected_agreement_not_active(self, api):
        """PRD §3.1: "Opening a lane — from `PLANNED`, or re-opening from `MAINTENANCE` —
        requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise)"
        — after termination no lane of the agreement can open.

        Design: Difficulty/transitive_cascade/agreement_terminate_cascades_lanes_then_capacity_zero
        """
        airport, agreement = setup_airport_with_active_agreement(
            "ORD", staffing_footprint_seats=4
        )
        lane = create_open_lane(
            airport["id"], agreement["id"], terminal="T1", position_index=1,
            open_time="05:00", close_time="22:00", capacity_hours=6,
        )
        validate_success(api.terminate_agreement(agreement["id"], PM))
        resp = api.open_lane(lane["id"], OPS)
        # PRD names ERR_AGREEMENT_NOT_ACTIVE for opening with a non-ACTIVE
        # agreement, but termination also moved this lane to CLOSED, so a
        # state-check-first serialization legitimately yields ERR_INVALID_STATE.
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, ApiErrorId.ERR_INVALID_STATE]
        )


class TestAirportSuspensionCascade:
    def test_airport_suspend_cascades_agreement_and_lanes(self, api):
        """PRD §3.1: "Suspending an `ACTIVE` airport pushes its `ACTIVE` agreement to
        `SUSPENDED` and each of that agreement's `OPEN` lanes to `MAINTENANCE` (the
        lanes still count toward capacity while in maintenance)."

        Design: Corner/state_machines/airport_suspend_cascades_agreement_and_lanes
        """
        airport, agreement = setup_airport_with_active_agreement(
            "BNA", staffing_footprint_seats=4
        )
        lane = create_open_lane(
            airport["id"], agreement["id"], terminal="T1", position_index=1,
            open_time="05:00", close_time="22:00", capacity_hours=4,
        )
        suspended = validate_success(api.suspend_airport(airport["id"], OPS))
        assert suspended["status"] == "SUSPENDED"
        agreement_after = validate_success(api.get_agreement(agreement["id"], PM))
        assert agreement_after["status"] == "SUSPENDED"
        lane_after = validate_success(api.get_lane(lane["id"], OPS))
        assert lane_after["status"] == "MAINTENANCE"


class TestLaneOpenAgreementGate:
    def test_lane_open_blocked_while_agreement_suspended(self, api):
        """PRD §3.1: "Opening a lane — from `PLANNED`, or re-opening from `MAINTENANCE` —
        requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise)"

        Design: Difficulty/cross_entity_state_dependency/lane_open_blocked_by_agreement_state
        """
        airport, agreement = setup_airport_with_active_agreement(
            "DAL", staffing_footprint_seats=4
        )
        lane = create_lane(
            airport["id"], agreement["id"], terminal="T1", position_index=1,
            open_time="05:00", close_time="22:00", capacity_hours=4,
        )
        validate_success(api.suspend_agreement(agreement["id"], PM))
        resp = api.open_lane(lane["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        lane_after = validate_success(api.get_lane(lane["id"], OPS))
        assert lane_after["status"] == "PLANNED"

    def test_lane_open_succeeds_after_agreement_reactivation(self, api):
        """PRD §3.1: "A `SUSPENDED` agreement may be re-activated, but only while the logical
        clock is still before `effective_to`; at or past that instant the attempt
        fails with `ERR_AGREEMENT_EXPIRED`." — re-activation before effective_to
        restores ACTIVE, and the previously blocked lane open then succeeds.

        Design: Difficulty/cross_entity_state_dependency/lane_open_blocked_by_agreement_state
        """
        airport, agreement = setup_airport_with_active_agreement(
            "DAL", staffing_footprint_seats=4
        )
        lane = create_lane(
            airport["id"], agreement["id"], terminal="T1", position_index=1,
            open_time="05:00", close_time="22:00", capacity_hours=4,
        )
        validate_success(api.suspend_agreement(agreement["id"], PM))
        reactivated = validate_success(api.activate_agreement(agreement["id"], PM))
        assert reactivated["status"] == "ACTIVE"
        opened = validate_success(api.open_lane(lane["id"], OPS))
        assert opened["status"] == "OPEN"


class TestAgreementStateOutranksCapacity:
    def test_suspended_agreement_and_capacity_breach_reports_agreement_not_active(self, api):
        """PRD §2.8: "cross-entity state requirements (agreement active, member active, lane
        open, subscription active, right ambassador); and finally capacity and quota
        rules (lane footprint, family slots, discount redemptions and expiry, rate
        bands)" — the agreement-state requirement is evaluated before the capacity
        rule, so a request failing both reports `ERR_AGREEMENT_NOT_ACTIVE`.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_lane_open_on_planned_with_capacity_breach
        """
        airport, agreement = setup_airport_with_active_agreement(
            "IAH", staffing_footprint_seats=4
        )
        create_open_lane(
            airport["id"], agreement["id"], terminal="TA", position_index=1,
            open_time="05:00", close_time="22:00", capacity_hours=10,
        )
        create_open_lane(
            airport["id"], agreement["id"], terminal="TB", position_index=2,
            open_time="05:00", close_time="22:00", capacity_hours=6,
        )
        lane3 = create_lane(
            airport["id"], agreement["id"], terminal="TC", position_index=3,
            open_time="05:00", close_time="22:00", capacity_hours=1,
        )
        # Footprint ceiling is 4 seats * 4 hours = 16; opening lane3 would breach it,
        # but the agreement is suspended first so only the state error can surface.
        validate_success(api.suspend_agreement(agreement["id"], PM))
        resp = api.open_lane(lane3["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        lane3_after = validate_success(api.get_lane(lane3["id"], OPS))
        assert lane3_after["status"] == "PLANNED"

    def test_capacity_breach_alone_reports_capacity_exceeded(self, api):
        """PRD §3.1: "Opening is allowed only if the resulting total, including the lane
        being opened, stays within the agreement's `staffing_footprint_seats`
        multiplied by four ambassador seat-hours per seat; a projected total exactly
        equal to that ceiling is allowed, and anything above it is refused with
        `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_lane_open_on_planned_with_capacity_breach
        """
        airport, agreement = setup_airport_with_active_agreement(
            "IAH", staffing_footprint_seats=4
        )
        create_open_lane(
            airport["id"], agreement["id"], terminal="TA", position_index=1,
            open_time="05:00", close_time="22:00", capacity_hours=10,
        )
        create_open_lane(
            airport["id"], agreement["id"], terminal="TB", position_index=2,
            open_time="05:00", close_time="22:00", capacity_hours=6,
        )
        lane3 = create_lane(
            airport["id"], agreement["id"], terminal="TC", position_index=3,
            open_time="05:00", close_time="22:00", capacity_hours=1,
        )
        resp = api.open_lane(lane3["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


class TestKioskAutoSuspension:
    def test_third_consecutive_capture_failure_auto_suspends(self, api):
        """PRD §3.3: "The capture requires `biometric_capture_ok` to be true; a false flag is
        refused with `ERR_BIOMETRIC_CAPTURE_FAILED`, and when the failed capture
        happens at a kiosk site the kiosk's `consecutive_capture_failures` increments
        — the third consecutive failure auto-suspends the kiosk."
        PRD §3.2: "An `ACTIVE` kiosk can be suspended — manually, or automatically the
        moment a third consecutive capture failure is recorded"

        Design: Corner/state_machines/kiosk_third_consecutive_capture_failure_auto_suspends
        """
        airport, _ = setup_airport_with_active_agreement("RDU")
        kiosk = create_active_kiosk(airport["id"], code="RDU-K1")
        enrollments = []
        members = []
        for i in (1, 2, 3):
            member = register_member(
                email=f"k{i}@x.com", full_name=f"K {i}", date_of_birth="1990-01-01"
            )
            enrollment = open_enrollment(
                member, "KIOSK", kiosk["id"],
                document_number=f"PK00000{i}", biometric_capture_ok=False,
            )
            submitted = submit_document(enrollment, member)
            assert submitted["status"] == "DOCUMENT_VERIFIED", (
                f"SELFIE_MISMATCH +5 alone is below the review threshold, "
                f"got {submitted['status']}"
            )
            enrollments.append(submitted)
            members.append(member)
        for member, enrollment in zip(members, enrollments):
            resp = api.capture_biometric(
                enrollment["id"], make_member_headers(member["id"])
            )
            validate_error(resp, ApiErrorId.ERR_BIOMETRIC_CAPTURE_FAILED)
        kiosk_after = validate_success(api.get_kiosk(kiosk["id"], OPS))
        assert kiosk_after["consecutive_capture_failures"] == 3
        assert kiosk_after["status"] == "SUSPENDED", (
            "system auto-transition on the third consecutive failure"
        )


class TestDuplicateAgreement:
    def test_second_draft_agreement_rejected_then_allowed_after_terminate(self, api):
        """PRD §3.1: "At most one agreement per airport may sit in `DRAFT` or `ACTIVE` at a
        time; a second attempt is refused with `ERR_DUPLICATE_AGREEMENT`."

        Design: Corner/validations/duplicate_agreement_per_airport_rejected
        """
        airport = create_airport("COS")
        first = create_agreement(airport["id"])
        payload = {
            "airport_id": airport["id"],
            "rev_share_rate": 0.10,
            "subscription_share_rate": 0.02,
            "monthly_minimum_cents": 10000,
            "federal_integration": False,
            "staffing_footprint_seats": 4,
            "term_months": 12,
            "effective_from": "2026-09-01T00:00:00Z",
        }
        resp = api.create_agreement(payload, PM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_AGREEMENT)
        validate_success(api.activate_agreement(first["id"], PM))
        validate_success(api.terminate_agreement(first["id"], PM))
        payload2 = dict(payload, rev_share_rate=0.11, subscription_share_rate=0.03,
                        monthly_minimum_cents=12000, federal_integration=True,
                        staffing_footprint_seats=6, term_months=24)
        second = validate_success(api.create_agreement(payload2, PM), expected_status=201)
        assert second["status"] == "DRAFT"


class TestAgreementActivationWindow:
    def test_activation_before_effective_from_rejected_then_allowed_at(self, api):
        """PRD §3.1: "Activating a `DRAFT` agreement requires the logical clock to have
        reached `effective_from`; earlier activation is refused with
        `ERR_AGREEMENT_NOT_YET_EFFECTIVE`."

        Design: Corner/errors/agreement_activation_before_effective_from_rejected
        """
        airport = create_airport("MLI")
        agreement = create_agreement(
            airport["id"], effective_from="2026-09-15T00:00:00Z"
        )
        resp = api.activate_agreement(agreement["id"], PM)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_YET_EFFECTIVE)
        set_clock("2026-09-15T00:00:00Z")
        activated = validate_success(api.activate_agreement(agreement["id"], PM))
        assert activated["status"] == "ACTIVE"
