"""Marketplace listing, marketplace pricing, commission walks and promotions."""
import pytest

from test_helpers import (
    ADMIN,
    ANONYMOUS,
    ApiErrorId,
    TEST_USERS,
    book,
    create_client,
    create_session,
    create_staff,
    create_template,
    ensure_tier,
    get_success_data,
    make_client_headers,
    make_staff_member_headers,
    make_studio_owner_headers,
    set_clock,
    setup_studio_roster,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import create_payroll_period, create_studio


class TestMarketplaceListingVisibility:

    def test_marketplace_browsing_hides_sessions_of_suspended_studios(self, api):
        """PRD §3.7: "Browsing the marketplace requires no authentication; only
        sessions whose studio is ACTIVE and whose tier has
        marketplace_listing_enabled set appear in the marketplace class list."

        Design: Corner/errors/marketplace_browsing_hides_sessions_of_suspended_studios
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")

        studio_a = create_studio(legal_name="Prana Loft")
        owner_a = make_studio_owner_headers(studio_a["id"])
        ctx_a = _build_scheduled(studio_a, owner_a, start_at="2026-06-20T17:00:00Z")

        studio_b = create_studio(legal_name="Stillwater Studio", home_state_code="CO")
        owner_b = make_studio_owner_headers(studio_b["id"])
        ctx_b = _build_scheduled(studio_b, owner_b, start_at="2026-06-20T18:00:00Z")

        _, before = validate_paginated(api.browse_marketplace_classes(
            ANONYMOUS, params={"limit": 10, "offset": 0}))
        assert before["total_count"] == 2, "both active studios are visible"

        sub = validate_success(api.get_subscription(studio_a["subscription_id"], ADMIN))
        get_success_data(api.suspend_subscription(
            studio_a["subscription_id"],
            {"reason": "non-payment", "expected_subscription_version": sub["version"]},
            owner_a))

        rows, after = validate_paginated(api.browse_marketplace_classes(
            ANONYMOUS, params={"limit": 10, "offset": 0}))
        assert after["total_count"] == 1
        assert rows[0]["studio_id"] == studio_b["id"]
        assert ctx_a["session"]["id"] not in [row["id"] for row in rows]

    def test_a_write_against_the_suspended_studio_reports_the_posture_error(self, api):
        """PRD §2.11: "Tenant posture and tier entitlement are then evaluated —
        ERR_STUDIO_NOT_OPERATING and ERR_SUBSCRIPTION_INACTIVE at HTTP 409,
        ERR_PAYROLL_HOLD at HTTP 409, and ERR_FEATURE_NOT_IN_TIER at HTTP 403."

        Design: Corner/errors/marketplace_browsing_hides_sessions_of_suspended_studios
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Loft")
        owner = make_studio_owner_headers(studio["id"])
        ctx = _build_scheduled(studio, owner, start_at="2026-06-20T17:00:00Z")
        sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        get_success_data(api.suspend_subscription(
            studio["subscription_id"],
            {"reason": "non-payment", "expected_subscription_version": sub["version"]},
            owner))

        # The OCC precondition carries the version the caller last observed, so
        # the suspended-posture refusal is exercised against a current version.
        current = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        validate_error(api.create_class_session({
            "studio_id": studio["id"], "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-Z",
            "start_at": "2026-06-22T17:00:00Z", "capacity": 2,
            "expected_subscription_version": current["version"],
        }, owner), ApiErrorId.ERR_STUDIO_NOT_OPERATING)


class TestMarketplaceBookingChannel:

    def test_marketplace_booking_settles_against_the_payment_ref(self, api):
        """PRD §3.7: "A marketplace booking is made by a Client against a
        client_id and a class_session_id with a payment_ref and a promo_redeem
        flag. It is always written with channel MARKETPLACE and payment_source
        DROP_IN, and it never debits a studio membership or pack."

        Design: Corner/endpoints/marketplace_booking_refuses_a_membership_credit_payment_source
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=4,
                                  start_at="2026-06-20T18:00:00Z",
                                  room_code="ROOM-C")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        booking = validate_success(api.create_marketplace_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "payment_ref": "pm_ok_1", "promo_redeem": False,
        }, make_client_headers(maya["id"])), expected_status=201)

        assert booking["channel"] == "MARKETPLACE"
        assert booking["payment_source"] == "DROP_IN"
        assert booking["is_promotional_seat"] is False
        assert booking["commission_base_cents"] == ctx["session"]["marketplace_price_cents"]

    def test_extra_studio_channel_fields_do_not_route_a_pack_through(self, api):
        """PRD §3.7: "it never debits a studio membership or pack — those are refused with `ERR_PAYMENT_SOURCE_NOT_PERMITTED`."

        Design: Corner/endpoints/marketplace_booking_refuses_a_membership_credit_payment_source
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=4,
                                  start_at="2026-06-20T18:00:00Z",
                                  room_code="ROOM-C")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": maya["id"],
            "pack_size": 5, "purchased_at": "2026-06-01T00:00:00Z",
            "expiry_scheme": "NONE", "expected_client_version": maya["version"],
        }, ctx["owner"]), expected_status=201)

        # Naming a pack on the marketplace channel must not debit it.
        result = api.create_marketplace_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "payment_ref": "pm_ok_2", "promo_redeem": False,
            "class_pack_id": pack["id"],
        }, make_client_headers(maya["id"]))
        if result.status_code == 201:
            after = validate_success(api.get_class_pack(pack["id"], ctx["owner"]))
            assert after["credits_remaining"] == 5, \
                "the marketplace channel never debits a studio pack"
        else:
            validate_error(result, ApiErrorId.ERR_PAYMENT_SOURCE_NOT_PERMITTED)


class TestMarketplaceSettlementWalk:

    def test_settlement_reports_both_commission_forms_and_a_booking_count(self, api):
        """PRD §3.7: "The settlement form walks the studio's non-terminal
        marketplace bookings in ascending created_at order, tie-broken by
        ascending creation_seq — the UUID identifier is never the ordering key —
        accumulating a running un-rounded total of each booking's raw commission
        and flooring the running total as it goes."
        PRD §3.7: "multiplied by the off-peak factor and by the tier factor, div"

        Design: Difficulty/dual_variant_calc/pack_seat_gross_differs_between_booked_and_attended_variant
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=4,
                                  start_at="2026-06-20T18:00:00Z",
                                  room_code="ROOM-C")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        get_success_data(api.create_marketplace_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "payment_ref": "pm_1", "promo_redeem": False,
        }, make_client_headers(maya["id"])))
        second = create_session(ctx["studio"]["id"], ctx["owner"],
                                ctx["template"]["id"], ctx["instructor"]["id"],
                                ctx["subscription_version"], capacity=4,
                                room_code="ROOM-D",
                                start_at="2026-06-21T18:00:00Z")
        get_success_data(api.create_marketplace_booking({
            "client_id": bea["id"], "class_session_id": second["id"],
            "payment_ref": "pm_2", "promo_redeem": False,
        }, make_client_headers(bea["id"])))

        settlement = validate_success(api.get_marketplace_settlement(
            ctx["owner"], params={"studio_id": ctx["studio"]["id"]}))
        assert settlement["booking_count"] == 2
        assert "marketplace_commission_cents" in settlement
        assert "per_booking_commission_cents" in settlement
        # The walking form floors the accumulator, so it can differ from the sum
        # of the individual floors by at most the discarded fractional cents.
        assert abs(settlement["marketplace_commission_cents"] -
                   settlement["per_booking_commission_cents"]) <= 2


class TestStudioClosure:

    def test_cancelling_a_completed_session_is_refused(self, api):
        """PRD §3.2: "A studio-side cancellation is admitted while the session is
        SCHEDULED or IN_PROGRESS and moves it to CANCELLED_BY_STUDIO."
        PRD §2.11: "State admissibility follows, yielding ERR_INVALID_STATE,
        ERR_ALREADY_TERMINAL, ERR_BOOKING_NOT_RESERVED, ERR_ENTRY_NOT_OFFERED,
        ERR_WAITLIST_TERMINAL, ERR_SESSION_NOT_SCHEDULED,
        ERR_PAYROLL_PERIOD_NOT_OPEN or ERR_PORTABILITY_ALREADY_DECIDED as
        applicable, all at HTTP 409."

        Design: Difficulty/compensating_invariant/studio_commission_and_attendance_conservation_across_a_late_substitution
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        get_success_data(api.complete_class_session(ctx["session"]["id"], ADMIN))
        validate_error(api.cancel_class_session(
            ctx["session"]["id"], {"reason": "studio closed for the day"},
            ctx["owner"]), ApiErrorId.ERR_INVALID_STATE)

    def test_studio_cancellation_never_fees_the_client_and_frees_the_hall(self, api):
        """PRD §3.2: "it cancels every booking in RESERVED or CHECKED_IN with
        fee_status NONE, because a studio-side cancellation never fees a client,
        and it restores the class-pack and membership credits those bookings
        consumed. Every waitlist hold in ACTIVE, STANDBY or OFFERED on that
        session moves to EXPIRED."
        PRD §3.2: "The session's `fullness_posture` is re-derived to `CANCELLED`, which is what blocks any further booking attempt on it with `ERR_STUDIO_CAPACITY_EXCEEDED`."

        Design: Difficulty/transitive_cascade/subscription_lapse_closes_sessions_and_purges_their_waitlists
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        booking = book(maya["id"], ctx["session"]["id"])
        hold = _join(bea["id"], ctx["session"]["id"])

        cancelled = validate_success(api.cancel_class_session(
            ctx["session"]["id"], {"reason": "instructor unavailable"}, ctx["owner"]))
        assert cancelled["status"] == "CANCELLED_BY_STUDIO"
        assert cancelled["fullness_posture"] == "CANCELLED"

        after_booking = validate_success(api.get_booking(booking["id"], ctx["owner"]))
        assert after_booking["status"] == "CANCELLED"
        assert after_booking["fee_status"] == "NONE"

        holds = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))
        assert all(row["status"] == "EXPIRED" for row in holds)

        validate_error(api.create_booking({
            "client_id": bea["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "DROP_IN",
        }, make_client_headers(bea["id"])),
            ApiErrorId.ERR_STUDIO_CAPACITY_EXCEEDED)


class TestSubscriptionLapseCascade:

    def test_subscription_lapse_closes_sessions_and_purges_their_waitlists(self, api):
        """PRD §3.1: "Letting the clock pass `grace_until` moves the subscription from `GRACE` to `SUSPENDED`, flips `dunning_stage` to `SUSPENDED` and `payroll_hold` to true, and re-derives the studio posture to `SUSPENDED`. That posture change then cascades down through the studio's scheduled sessions and their waitlists as described in §3.2."

        Design: Difficulty/transitive_cascade/subscription_lapse_closes_sessions_and_purges_their_waitlists
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Loft")
        owner = make_studio_owner_headers(studio["id"])
        sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))

        # A failed renewal parks the subscription in PAST_DUE without moving the
        # clock.  PRD §3.1 admits a renewal only once the clock is at or past
        # renewal_due_at (signup + 30 days), so the clock first reaches the due
        # date and advance_clock stays false so the due date itself is unmoved.
        set_clock("2026-07-01T00:00:00Z")
        sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        failed = validate_success(api.advance_renewal(
            studio["subscription_id"],
            {"advance_clock": False, "outcome": "FAILED",
             "expected_subscription_version": sub["version"]}, owner))
        assert failed["status"] == "PAST_DUE"

        set_clock("2026-07-02T00:00:00Z")
        period = create_payroll_period(studio["id"], owner, start_date="2026-07-01T00:00:00Z",
                                       end_date="2026-07-31T23:59:59Z")
        template = create_template(studio["id"], owner, default_capacity=1)
        instructor = create_staff(studio["id"], owner, template_id=template["id"])
        current = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        session = create_session(studio["id"], owner, template["id"],
                                 instructor["id"], current["version"], capacity=1,
                                 start_at="2026-07-15T17:00:00Z")
        maya = create_client(studio["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(studio["id"], display_name="Bea Tan",
                            email="bea@example.com")
        booking = book(maya["id"], session["id"])
        hold = _join(bea["id"], session["id"])
        get_success_data(api.cancel_booking(
            booking["id"], {"reason": "schedule conflict"},
            make_client_headers(maya["id"])))

        holds = validate_success(api.list_session_waitlist_entries(session["id"], owner))
        assert holds[0]["status"] == "OFFERED", \
            "the freed seat offered the session's only hold before the lapse"

        # Passing grace_until drives GRACE to SUSPENDED and cascades downward.
        set_clock("2026-07-10T00:00:00Z")

        after_sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        assert after_sub["status"] == "SUSPENDED", "the clock passed grace_until"
        assert after_sub["payroll_hold"] is True
        after_studio = validate_success(api.get_studio(studio["id"], owner))
        assert after_studio["status"] == "SUSPENDED"
        assert after_studio["suspension_reason"], "the cascade stamps a reason"

        after_session = validate_success(api.get_class_session(session["id"], owner))
        assert after_session["status"] == "CANCELLED_BY_STUDIO"
        assert after_session["fullness_posture"] == "CANCELLED"

        after_holds = validate_success(api.list_session_waitlist_entries(session["id"], owner))
        assert after_holds[0]["status"] == "EXPIRED", \
            "the session closure expired the offered hold"

    def test_no_hold_of_the_lapsed_session_is_left_actionable(self, api):
        """PRD §3.1: "a stale subscription expectation the write fails earlier at `ERR_STALE_VERSION`. The failed-charge path has a side ef"

        Design: Difficulty/transitive_cascade/subscription_lapse_closes_sessions_and_purges_their_waitlists
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Loft")
        owner = make_studio_owner_headers(studio["id"])
        sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        # PRD §3.1 admits a renewal only once the clock is at or past
        # renewal_due_at (signup + 30 days).
        set_clock("2026-07-01T00:00:00Z")
        sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        validate_success(api.advance_renewal(
            studio["subscription_id"],
            {"advance_clock": False, "outcome": "FAILED",
             "expected_subscription_version": sub["version"]}, owner))
        set_clock("2026-07-02T00:00:00Z")
        create_payroll_period(studio["id"], owner, start_date="2026-07-01T00:00:00Z",
                              end_date="2026-07-31T23:59:59Z")
        template = create_template(studio["id"], owner, default_capacity=1)
        instructor = create_staff(studio["id"], owner, template_id=template["id"])
        current = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        session = create_session(studio["id"], owner, template["id"],
                                 instructor["id"], current["version"], capacity=1,
                                 start_at="2026-07-15T17:00:00Z")
        bea = create_client(studio["id"], display_name="Bea Tan",
                            email="bea@example.com")
        _join(bea["id"], session["id"])

        set_clock("2026-07-10T00:00:00Z")

        holds = validate_success(api.list_session_waitlist_entries(session["id"], owner))
        for row in holds:
            assert row["status"] not in ("ACTIVE", "STANDBY", "OFFERED"), \
                "no hold of a closed session remains actionable"
        rows, _ = validate_paginated(api.list_bookings(
            owner, params={"class_session_id": session["id"]}))
        for row in rows:
            assert row["fee_status"] == "NONE", \
                "a studio-side closure never fees the client"


# --- local helpers ----------------------------------------------------------

def _join(client_id, session_id):
    from test_helpers import api_client, make_client_headers
    return get_success_data(api_client.join_waitlist(
        {"class_session_id": session_id, "client_id": client_id,
         "position_mode": "QUEUED"}, make_client_headers(client_id)))


def _build_scheduled(studio, owner, start_at: str):
    """Payroll period, template, instructor and one scheduled session."""
    from test_helpers import api_client
    sub = validate_success(api_client.get_subscription(studio["subscription_id"], ADMIN))
    period = create_payroll_period(studio["id"], owner)
    template = create_template(studio["id"], owner)
    instructor = create_staff(studio["id"], owner, template_id=template["id"])
    session = create_session(studio["id"], owner, template["id"], instructor["id"],
                             capacity=2, start_at=start_at)
    return {"studio": studio, "owner": owner, "subscription": sub,
            "subscription_version": sub["version"], "period": period,
            "template": template, "instructor": instructor, "session": session}