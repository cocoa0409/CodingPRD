"""Benefit-network booking admissibility and remaining depth assertions."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    TEST_USERS,
    book,
    create_client,
    create_session,
    ensure_tier,
    get_success_data,
    make_client_headers,
    make_studio_owner_headers,
    same_instant,
    set_clock,
    setup_studio_roster,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import create_studio


class TestBenefitBookingAdmissibilityPrecedence:

    def test_slow_client_shortfall_outranks_benefit_network_resolution(self, api):
        """PRD §2.11: "then the cross-entity referential dependencies (`ERR_CLIENT_NOT_ADMISSIBLE`, `ERR_INSTRUCTOR_NOT_ELIGIBLE`, `ERR_NETWORK_NOT_ACTIVE`, all HTTP 409)."
        PRD §3.3: "An attempt by a client whose own `status` is `PORTABILITY_HOLD`, `PORTED` or `ANONYMIZED` is refused with `ERR_CLIENT_NOT_ADMISSIBLE`, because such a client may not take new bookings or holds."

        Design: Difficulty/priority_pair_validation_conflict/slow_client_shortfall_outranks_benefit_network_resolution_on_benefit_booking
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        book(maya["id"], ctx["session"]["id"])

        request = validate_success(api.create_portability_request({
            "studio_id": ctx["studio"]["id"], "requesting_client_id": bea["id"],
            "dispute_reason": "moving on"}, make_client_headers(bea["id"])),
            expected_status=201)
        get_success_data(api.resolve_portability_release(
            request["id"],
            {"include_booking_history": True, "include_financial_history": False},
            ctx["owner"]))
        held = validate_success(api.get_client(bea["id"], ctx["owner"]))
        assert held["status"] == "PORTABILITY_HOLD"

        # The session is full AND the benefit network is unregistered: the
        # referential band must report the client, not either of the others.
        error = validate_error(api.create_booking({
            "client_id": bea["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "BENEFIT_NETWORK",
            "benefit_network_code": "WELLPASS",
        }, ctx["owner"]), ApiErrorId.ERR_CLIENT_NOT_ADMISSIBLE)
        assert error["error_id"] != ApiErrorId.ERR_NETWORK_NOT_ACTIVE, \
            "the client-admissibility band fires before any network lookup"
        assert error["error_id"] != ApiErrorId.ERR_STUDIO_CAPACITY_EXCEEDED

    def test_the_refused_attempt_leaves_the_session_and_client_untouched(self, api):
        """PRD §3.3: "An attempt by a client whose own `status` is `PORTABILITY_HOLD`, `PORTED` or `ANONYMIZED` is refused with `ERR_CLIENT_NOT_ADMISSIBLE`, because such a client may not take new bookings or holds."

        Design: Difficulty/priority_pair_validation_conflict/slow_client_shortfall_outranks_benefit_network_resolution_on_benefit_booking
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        book(maya["id"], ctx["session"]["id"])
        request = validate_success(api.create_portability_request({
            "studio_id": ctx["studio"]["id"], "requesting_client_id": bea["id"],
            "dispute_reason": "moving on"}, make_client_headers(bea["id"])),
            expected_status=201)
        get_success_data(api.resolve_portability_release(
            request["id"],
            {"include_booking_history": True, "include_financial_history": False},
            ctx["owner"]))

        api.create_booking({
            "client_id": bea["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "BENEFIT_NETWORK",
            "benefit_network_code": "WELLPASS",
        }, ctx["owner"])

        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["seats_taken"] == 1, "the session is untouched"
        assert session["fullness_posture"] == "FULL"
        still_held = validate_success(api.get_client(bea["id"], ctx["owner"]))
        assert still_held["status"] == "PORTABILITY_HOLD"


class TestSessionClosureAndCommissionConservation:

    def test_cancelling_a_scheduled_session_accrues_no_commission(self, api):
        """PRD §3.6: "The sum, across a studio, of commission_base_cents on
        bookings that are or have been ATTENDED is invariant under every reversal
        and substitution."
        PRD §3.2: "it cancels every booking in RESERVED or CHECKED_IN with
        fee_status NONE."

        Design: Difficulty/compensating_invariant/studio_commission_and_attendance_conservation_across_a_late_substitution
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        booking = book(maya["id"], ctx["session"]["id"])
        validate_success(api.cancel_class_session(
            ctx["session"]["id"], {"reason": "studio closed for the day"},
            ctx["owner"]))

        after = validate_success(api.get_booking(booking["id"], ctx["owner"]))
        assert after["status"] == "CANCELLED"
        assert after["commission_base_cents"] == 0, \
            "a booking that never attended carries no attended revenue"

        rows, meta = validate_paginated(api.list_commission_entries(
            ctx["owner"], params={"studio_id": ctx["studio"]["id"]}))
        assert meta["total_count"] == 0, "no commission accrues off a cancelled seat"


class TestRoomOverlapBackstop:

    def test_overlapping_room_sessions_never_coexist(self, api):
        """PRD §3.2: "Two sessions in the same room_code may not collide: their
        half-open intervals from start_at up to but excluding end_at must not
        intersect, or the schedule is refused with ERR_ROOM_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/room_overlap_uses_a_half_open_interval_so_adjacency_is_admitted
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z",
                                  room_code="ROOM-A")

        # A candidate inside the first session's half-open interval.
        result = api.create_class_session({
            "studio_id": ctx["studio"]["id"],
            "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-A",
            "start_at": "2026-06-20T17:10:00Z", "capacity": 2,
            "expected_subscription_version": ctx["subscription_version"],
        }, ctx["owner"])
        if result.status_code == 201:
            pytest.fail("an overlapping ROOM-A session was admitted")
        assert result.status_code == 409

        rows, meta = validate_paginated(api.list_class_sessions(
            ctx["owner"], params={"studio_id": ctx["studio"]["id"],
                                  "room_code": "ROOM-A"}))
        assert meta["total_count"] == 1, \
            "only the original ROOM-A session exists"
        assert same_instant(rows[0]["start_at"], "2026-06-20T17:00:00Z")