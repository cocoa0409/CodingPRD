"""RBAC denials, error envelope shape, OCC, consistency, seat reconciliation,
format support, and filtered listings."""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_active_member,
    create_confirmed_reservation,
    create_held_reservation,
    create_on_sale_showtime,
    create_published_plan,
    create_reservation_payload,
    create_showtime_payload,
    create_theater_with_auditorium,
    create_auditorium_payload,
    current_showtime,
    enroll_member,
    get_success_data,
    is_iso8601_timestamp,
    make_member_headers,
    set_clock,
    setup_checked_in_scenario,
    setup_theater_with_on_sale_showtime,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
SERVICES = TEST_USERS["member_services_headers"]
STAFF = TEST_USERS["theater_staff_headers"]
STUDIO = TEST_USERS["studio_rep_headers"]


class TestRbac:

    def test_member_cannot_open_showtime_sales(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 endpoint table: "| POST | `/cinemas/showtimes/{showtime_id}/open_sales`
        | Open a showtime for sales | ProgramAdmin |"

        Design: Corner/roles/member_cannot_open_showtime_sales
        """
        set_clock()
        theater, auditorium = create_theater_with_auditorium()
        showtime = get_success_data(api.create_showtime(
            create_showtime_payload(auditorium["id"], starts_at="2026-09-05T19:00:00Z"),
            ADMIN))
        member = create_active_member(email="rb1@x.com", full_name="RB1")
        resp = api.open_showtime_sales(showtime["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        st = current_showtime(showtime["id"])
        assert st["status"] == "SCHEDULED"

    def test_studio_rep_cannot_submit_report(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.11: "Submitting the report — a `TheaterStaff` action requiring
        at least one line, else `ERR_EMPTY_REPORT`"

        Design: Corner/roles/studio_rep_cannot_submit_report
        """
        ctx = setup_checked_in_scenario()
        get_success_data(api.add_settlement_line(
            ctx["report"]["id"], {"reservation_id": ctx["reservation"]["id"]}, STAFF))
        resp = api.submit_settlement_report(ctx["report"]["id"], STUDIO)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        report = get_success_data(api.get_settlement_report(ctx["report"]["id"], STAFF))
        assert report["status"] == "DRAFT"

    def test_member_cannot_reverse_own_strike(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.10: "`MemberServices` may reverse a strike as a goodwill
        correction, supplying a `reversal_reason`"

        Design: Corner/roles/member_cannot_reverse_own_strike
        """
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-02T19:00:00Z"})
        member = create_active_member(email="rb3@x.com", full_name="RB3")
        sub = enroll_member(member["id"], plan["id"])
        create_confirmed_reservation(member, sub, showtime)
        set_clock("2026-09-03T12:00:00Z")  # swept to NO_SHOW -> one ACTIVE strike
        strikes, meta = validate_paginated(
            api.list_member_strikes(member["id"], SERVICES))
        assert meta["total_count"] == 1
        strike_id = strikes[0]["id"]
        resp = api.reverse_strike(
            strike_id, {"reversal_reason": "self service attempt"},
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        strike = get_success_data(api.get_strike(strike_id, SERVICES))
        assert strike["status"] == "ACTIVE"

    def test_member_cannot_touch_other_members_reservation(self, api):
        """PRD §2.1: "ownership checks on any resource that references a member
        compare the resource's `member_id` field against `X-User-ID`, and a
        mismatch is rejected with `ERR_FORBIDDEN`."

        Design: Corner/roles/member_cannot_touch_other_members_reservation
        """
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member_a = create_active_member(email="rb4a@x.com", full_name="RB4 A")
        sub_a = enroll_member(member_a["id"], plan["id"])
        member_b = create_active_member(email="rb4b@x.com", full_name="RB4 B")
        reservation = create_held_reservation(member_a, sub_a, showtime)
        resp = api.confirm_reservation(
            reservation["id"], make_member_headers(member_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_reservation(reservation["id"], SERVICES))
        assert after["status"] == "HELD"


class TestErrorEnvelope:

    def test_error_envelope_shape_and_request_id(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard error envelope format" with `response_type` "error" and
        `data.error_id`; "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.1: "A request missing either header, or naming a role the system
        does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_envelope_shape_and_request_id
        """
        resp = api.get_member(NON_EXISTENT_UUID, headers={})
        assert resp.status_code == 401, f"expected 401, got {resp.status_code}"
        body = resp.json()
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] == "ERR_UNAUTHENTICATED"
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"]
        assert "api_request_id" in body.get("meta", {})
        assert body["meta"]["api_request_id"].startswith("req_")


class TestOptimisticConcurrency:

    def test_stale_showtime_version_rejected_on_reservation_create(self, api):
        """PRD §2.9: "Reservation creation requires the request to carry
        `expected_showtime_version`, the client-observed `version` of the
        target `Showtime`. ... if the supplied value does not match the parent
        entity's current `version` — because another writer has advanced the
        resource since the client last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_showtime_version_rejected_on_reservation_create
        """
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member_a = create_active_member(email="occa@x.com", full_name="OCC A")
        sub_a = enroll_member(member_a["id"], plan["id"])
        member_b = create_active_member(email="occb@x.com", full_name="OCC B")
        sub_b = enroll_member(member_b["id"], plan["id"])
        v0 = showtime["version"]
        # B books first, advancing the showtime version beyond v0
        resp_b = api.create_reservation(
            create_reservation_payload(sub_b["id"], showtime["id"], v0),
            make_member_headers(member_b["id"]))
        validate_success(resp_b, expected_status=201)
        # A retries with the stale version
        resp_a = api.create_reservation(
            create_reservation_payload(sub_a["id"], showtime["id"], v0),
            make_member_headers(member_a["id"]))
        validate_error(resp_a, ApiErrorId.ERR_STALE_VERSION)
        st = current_showtime(showtime["id"])
        assert st["seats_held_subscription"] == 1

    def test_stale_subscription_version_rejected_on_change_plan(self, api):
        """PRD §2.9: "Plan change on a subscription requires
        `expected_subscription_version`, the client-observed `version` of the
        target `Subscription`. In both cases, if the supplied value does not
        match the parent entity's current `version` — because another writer
        has advanced the resource since the client last read it — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_subscription_version_rejected_on_change_plan
        """
        set_clock()
        plan_basic = create_published_plan()
        plan_premier = create_published_plan(
            tier="PREMIER", monthly_fee_cents=2999, weekly_reservation_quota=4,
            premium_format_allowed=True, max_future_reservations=6,
            loyalty_points_multiplier_pct=150, concession_discount_pct=15)
        member = create_active_member(email="oc2@x.com", full_name="OC2")
        sub = enroll_member(member["id"], plan_basic["id"])
        v0 = sub["version"]
        mhdr = make_member_headers(member["id"])
        # An intervening pause advances Subscription.version beyond v0
        get_success_data(api.pause_subscription(sub["id"], {"pause_days": 7}, mhdr))
        resp = api.change_subscription_plan(
            sub["id"],
            {"new_plan_id": plan_premier["id"], "expected_subscription_version": v0},
            mhdr)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestImmediateConsistency:

    def _setup(self, api, email):
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member = create_active_member(email=email, full_name=email)
        sub = enroll_member(member["id"], plan["id"])
        return member, sub, showtime

    def test_reservation_create_response_reflects_all_mutations(self, api):
        """PRD §3.5: "the current week's bucket is debited (`credits_used`
        increases by one and `credit_consumed` flips true), the showtime's
        `seats_held_subscription` increases by one, the showtime's `version`
        increments by one, and the reservation is stamped with its `bucket_id`
        and its `cancel_deadline`"

        Design: Corner/consistency_model/reservation_create_response_reflects_all_mutations
        """
        member, sub, showtime = self._setup(api, "ic@x.com")
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], showtime["id"], showtime["version"]),
            make_member_headers(member["id"]))
        reservation = validate_success(resp, expected_status=201)
        assert reservation["status"] == "HELD"
        assert reservation["credit_consumed"] is True
        assert reservation["bucket_id"], "create response must carry bucket_id"
        bucket = get_success_data(api.get_bucket(reservation["bucket_id"], ADMIN))
        assert bucket["credits_used"] == 1
        st = current_showtime(showtime["id"])
        assert st["seats_held_subscription"] == 1
        assert st["version"] == showtime["version"] + 1

    def test_reservation_create_stamps_cancel_deadline(self, api):
        """PRD §3.5: "the reservation is stamped with its `bucket_id` and its
        `cancel_deadline` — the showtime's `starts_at` minus the program's
        cancellation window (`CANCELLATION_WINDOW_MINUTES`)."

        Design: Corner/consistency_model/reservation_create_response_reflects_all_mutations
        """
        member, sub, showtime = self._setup(api, "ic2@x.com")
        reservation = create_held_reservation(member, sub, showtime)
        # PRD pins cancel_deadline = showtime.starts_at - CANCELLATION_WINDOW_MINUTES
        # (a fixed program window). Assert the PRD-derivable content without
        # assuming the constant's un-named value or a specific serialization:
        # the deadline is a timestamp strictly before starts_at, and identical
        # for equal starts_at.
        deadline = reservation.get("cancel_deadline")
        assert is_iso8601_timestamp(deadline), (
            f"cancel_deadline must be an ISO 8601 UTC timestamp, got {deadline!r}")
        deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        starts_dt = datetime.fromisoformat(
            showtime["starts_at"].replace("Z", "+00:00"))
        assert deadline_dt < starts_dt, (
            f"cancel_deadline {deadline!r} must precede starts_at "
            f"{showtime['starts_at']!r}")
        # Same starts_at -> identical stamped deadline (fixed program window).
        st2 = create_on_sale_showtime(
            showtime["auditorium_id"], starts_at=showtime["starts_at"])
        r2 = create_held_reservation(member, sub, current_showtime(st2["id"]))
        assert r2["cancel_deadline"] == deadline, (
            "a fixed program window must stamp the same deadline for the "
            f"same starts_at: {r2['cancel_deadline']!r} != {deadline!r}")


class TestSeatReconciliation:

    def _setup(self, api, email):
        set_clock("2026-09-01T12:00:00Z")
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member = create_active_member(email=email, full_name=email)
        sub = enroll_member(member["id"], plan["id"])
        return member, sub, showtime

    def test_derived_seat_counters_reconcile_across_lifecycle(self, api):
        """PRD §3.7: "Seat availability is derived, never stored independently:
        `seats_available` is the auditorium's `seat_count` minus the showtime's
        `seats_held_subscription` minus its `seats_held_paid`."

        Design: Corner/cross_cutting_layers/derived_seat_counters_reconcile_across_lifecycle
        """
        member, sub, showtime = self._setup(api, "dr@x.com")
        st0 = current_showtime(showtime["id"])
        assert st0["seats_held_subscription"] == 0
        assert st0["seats_available"] == 10
        reservation = create_held_reservation(member, sub, showtime)
        st1 = current_showtime(showtime["id"])
        assert st1["seats_held_subscription"] == 1
        assert st1["seats_available"] == 9
        get_success_data(api.cancel_reservation(
            reservation["id"], make_member_headers(member["id"])))
        st2 = current_showtime(showtime["id"])
        assert st2["seats_held_subscription"] == 0
        assert st2["seats_available"] == 10, "create+cancel must reconcile with no drift"

    def test_hold_expiry_reconciles_seat_counters(self, api):
        """PRD §3.7: "Seat availability is derived, never stored independently:
        `seats_available` is the auditorium's `seat_count` minus the showtime's
        `seats_held_subscription` minus its `seats_held_paid`."
        PRD §3.5: "A hold that outlives its window without confirmation is
        auto-swept to `EXPIRED` by the system, releasing the seat"

        Design: Corner/cross_cutting_layers/derived_seat_counters_reconcile_across_lifecycle
        """
        member, sub, showtime = self._setup(api, "dr2@x.com")
        create_held_reservation(member, sub, showtime)
        st1 = current_showtime(showtime["id"])
        assert st1["seats_held_subscription"] == 1
        set_clock("2026-09-01T12:16:00Z")
        st2 = current_showtime(showtime["id"])
        assert st2["seats_held_subscription"] == 0
        assert st2["seats_available"] == 10


class TestShowtimeFormat:

    def test_format_unsupported_by_auditorium_rejected(self, api):
        """PRD §3.6: "a `format` that must be among the auditorium's
        `supported_formats` (a mismatch is rejected with
        `ERR_FORMAT_UNSUPPORTED`)"

        Design: Corner/validations/format_unsupported_by_auditorium_rejected
        """
        set_clock()
        theater, auditorium = create_theater_with_auditorium(formats=("STANDARD",))
        resp = api.create_showtime(
            create_showtime_payload(
                auditorium["id"], format="DOLBY",
                starts_at="2026-09-05T19:00:00Z", premium_surcharge_cents=400),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORMAT_UNSUPPORTED)


class TestFilteredListings:

    def test_member_reservations_list_filtered_by_status(self, api):
        """PRD §2.3: "All list endpoints sort by `created_at` in ascending
        order unless otherwise specified. The `meta` object of every list
        response carries the four pagination fields `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §4 endpoint table: "| GET | `/cinemas/members/{member_id}/reservations`
        | List a member's reservations | Member, MemberServices, ProgramAdmin |"

        Design: Corner/endpoints/member_reservations_list_filtered_by_status
        """
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member = create_active_member(email="fl@x.com", full_name="FL")
        sub = enroll_member(member["id"], plan["id"])
        mhdr = make_member_headers(member["id"])
        r1 = create_held_reservation(member, sub, showtime)
        get_success_data(api.cancel_reservation(r1["id"], mhdr))
        st = current_showtime(showtime["id"])
        r2 = get_success_data(api.create_reservation(
            create_reservation_payload(sub["id"], st["id"], st["version"]), mhdr))
        get_success_data(api.confirm_reservation(r2["id"], mhdr))
        rows, meta = validate_paginated(
            api.list_member_reservations(member["id"], mhdr,
                                         params={"status": "CANCELLED"}))
        assert meta["total_count"] == 1, f"expected 1 CANCELLED row, got {meta['total_count']}"
        assert rows[0]["id"] == r1["id"]
        assert rows[0]["status"] == "CANCELLED"


class TestAuditoriumSeatConservation:

    def _two_members_confirmed_on_showtime(self, api):
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member_a = create_active_member(email="m19a@x.com", full_name="M19 A")
        sub_a = enroll_member(member_a["id"], plan["id"])
        member_b = create_active_member(email="m19b@x.com", full_name="M19 B")
        sub_b = enroll_member(member_b["id"], plan["id"])
        r_a = create_confirmed_reservation(member_a, sub_a, showtime)
        st = current_showtime(showtime["id"])
        r_b = create_confirmed_reservation(member_b, sub_b, st)
        return showtime, (r_a, r_b)

    def test_auditorium_seat_conservation_on_showtime_cancel(self, api):
        """PRD §3.7: "Seat availability is derived, never stored independently:
        `seats_available` is the auditorium's `seat_count` minus the showtime's
        `seats_held_subscription` minus its `seats_held_paid`."
        PRD §3.6: "every `HELD` or `CONFIRMED` reservation is cancelled with a
        full credit refund regardless of `cancel_deadline`, and both seat-held
        counters reset to zero."

        Design: Difficulty/compensating_invariant/auditorium_seat_conservation_on_showtime_cancel
        """
        showtime, (r_a, r_b) = self._two_members_confirmed_on_showtime(api)
        before = current_showtime(showtime["id"])
        assert before["seats_held_subscription"] == 2
        assert before["seats_held_paid"] == 0
        assert before["seats_available"] == 8
        assert (before["seats_held_subscription"] + before["seats_held_paid"]
                + before["seats_available"]) == 10
        get_success_data(api.cancel_showtime(showtime["id"], ADMIN))
        after = current_showtime(showtime["id"])
        assert after["seats_held_subscription"] == 0
        assert after["seats_held_paid"] == 0
        assert after["seats_available"] == 10
        for r in (r_a, r_b):
            refreshed = get_success_data(api.get_reservation(r["id"], SERVICES))
            assert refreshed["status"] == "CANCELLED"

    def test_showtime_cancel_refunds_credits_regardless_of_deadline(self, api):
        """PRD §3.6: "every `HELD` or `CONFIRMED` reservation is cancelled with
        a full credit refund regardless of `cancel_deadline`, and both
        seat-held counters reset to zero."

        Design: Difficulty/compensating_invariant/auditorium_seat_conservation_on_showtime_cancel
        """
        showtime, (r_a, r_b) = self._two_members_confirmed_on_showtime(api)
        get_success_data(api.cancel_showtime(showtime["id"], ADMIN))
        for r in (r_a, r_b):
            bucket = get_success_data(api.get_bucket(r["bucket_id"], ADMIN))
            assert bucket["credits_used"] == 0, (
                "force-majeure cancel must refund every held credit")
