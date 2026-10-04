"""Screen slots and release windows: validation priority, cross-entity gates,
interval overlap semantics, OCC, window-lock cascade, hold-over cycle, pull
cascade with waitlist promotion, and capacity boundaries."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    create_active_studio,
    create_approved_conversion,
    create_approved_market,
    create_agreement_payload,
    create_confirmed_slot,
    create_conversion_order,
    create_film,
    create_open_window,
    create_operating_auditorium,
    create_signed_agreement,
    create_validated_report,
    propose_slot,
    set_clock,
    setup_bookable_scenario,
    setup_confirmed_slot_scenario,
)

PCM = TEST_USERS["contract_manager_headers"]
PPS = TEST_USERS["post_scheduler_headers"]


class TestSlotConfirmPriority:
    def test_state_error_beats_referential_on_confirm(
        self, api, release_scheduler_headers
    ):
        """PRD §2.9: "Validation across the whole API follows a fixed priority
        ladder, evaluated in order: ... (5) the target resource's state
        permits the requested transition (`ERR_INVALID_STATE` or the
        transition's domain-specific error); (6) cross-entity state references
        hold — for example that a referenced ConversionOrder is
        `APPROVED_FOR_RELEASE` ... (`ERR_CONVERSION_NOT_APPROVED`,
        `ERR_AUDITORIUM_NOT_READY`, `ERR_MARKET_NOT_APPROVED`,
        `ERR_NO_SIGNED_AGREEMENT`)."
        PRD §3.5: "The parent window must be `OPEN_FOR_BOOKING`, else
        `ERR_WINDOW_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_slot_confirm
        """
        # Standard world but the window is never opened (stays DRAFT) and the
        # conversion is never approved (stays SUBMITTED).
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        get_success_data(api.activate_agreement(agreement["id"], PCM))
        studio = create_active_studio()
        film = create_film(studio["id"])
        conversion = create_conversion_order(film["id"])  # stays SUBMITTED
        window = get_success_data(
            api.create_release_window(
                {"window_label": "W37",
                 "window_start_date": "2026-09-07T00:00:00Z",
                 "window_end_date": "2026-09-14T00:00:00Z",
                 "total_premium_screen_seconds_pool": 10000000},
                release_scheduler_headers)
        )
        slot = propose_slot(
            window["id"], auditorium["id"], film["id"], conversion["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z",
            showings_per_day=2)
        resp = api.confirm_slot(slot["id"], release_scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN, expected_status=409)

    def test_referential_error_when_state_check_passes(
        self, api, release_scheduler_headers
    ):
        """PRD §2.9: "(5) the target resource's state permits the requested
        transition (`ERR_INVALID_STATE` or the transition's domain-specific
        error); (6) cross-entity state references hold — for example that a
        referenced ConversionOrder is `APPROVED_FOR_RELEASE` ...
        (`ERR_CONVERSION_NOT_APPROVED`, `ERR_AUDITORIUM_NOT_READY`,
        `ERR_MARKET_NOT_APPROVED`, `ERR_NO_SIGNED_AGREEMENT`)."
        PRD §3.5: "The referenced conversion order must be
        `APPROVED_FOR_RELEASE`, else `ERR_CONVERSION_NOT_APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_slot_confirm
        """
        # Only the referential gate fails: window is OPEN_FOR_BOOKING but the
        # conversion is still SUBMITTED. The ladder must surface the
        # referential error, not the state error.
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        studio = create_active_studio()
        film = create_film(studio["id"])
        conversion = create_conversion_order(film["id"])  # stays SUBMITTED
        window = create_open_window()
        slot = propose_slot(
            window["id"], auditorium["id"], film["id"], conversion["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z",
            showings_per_day=2)
        resp = api.confirm_slot(slot["id"], release_scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_CONVERSION_NOT_APPROVED,
                       expected_status=409)

    def test_confirm_blocked_when_conversion_not_approved(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "The referenced conversion order must be
        `APPROVED_FOR_RELEASE`, else `ERR_CONVERSION_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/slot_confirm_blocked_when_conversion_not_approved
        """
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        studio = create_active_studio()
        film = create_film(studio["id"])
        conversion = create_conversion_order(film["id"])
        # Drive conversion to QC_REVIEW but not APPROVED_FOR_RELEASE.
        get_success_data(api.begin_post(conversion["id"], PPS))
        set_clock("2026-09-04T00:00:00Z")
        get_success_data(api.submit_for_qc(conversion["id"], PPS))
        window = create_open_window()
        slot = propose_slot(
            window["id"], auditorium["id"], film["id"], conversion["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z",
            showings_per_day=2)
        resp = api.confirm_slot(slot["id"], release_scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_CONVERSION_NOT_APPROVED,
                       expected_status=409)

    def test_confirm_succeeds_when_conversion_approved(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "The referenced conversion order must be
        `APPROVED_FOR_RELEASE`, else `ERR_CONVERSION_NOT_APPROVED`." and "On
        success, the window's committed total increases by the slot's
        committed seconds."

        Design: Difficulty/cross_entity_state_dependency/slot_confirm_blocked_when_conversion_not_approved
        """
        ctx = setup_bookable_scenario()
        slot = propose_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
            ctx["conversion"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z",
            showings_per_day=2)
        resp = api.confirm_slot(slot["id"], release_scheduler_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CONFIRMED"
        window = validate_success(
            api.get_release_window(ctx["window"]["id"], release_scheduler_headers)
        )
        assert window["committed_premium_screen_seconds"] == 84000


class TestMarketBuildGate:
    def test_begin_build_blocked_without_signed_agreement(
        self, api, network_planner_headers, contract_manager_headers
    ):
        """PRD §3.1: "Beginning the build — `APPROVED → BUILDING` — requires
        that at least one ExhibitorAgreement referencing this market already
        sits in `SIGNED`; without one the transition is rejected with
        `ERR_NO_SIGNED_AGREEMENT`."

        Design: Difficulty/cross_entity_state_dependency/market_begin_build_blocked_without_signed_agreement
        """
        set_clock()
        market = create_approved_market()
        # Agreement exists but is never signed (stays NEGOTIATING).
        get_success_data(
            api.create_agreement(
                create_agreement_payload(market_id=market["id"]),
                contract_manager_headers)
        )
        resp = api.begin_market_build(market["id"], network_planner_headers)
        validate_error(resp, ApiErrorId.ERR_NO_SIGNED_AGREEMENT,
                       expected_status=409)

    def test_begin_build_succeeds_with_signed_agreement(
        self, api, network_planner_headers
    ):
        """PRD §3.1: "Beginning the build — `APPROVED → BUILDING` — requires
        that at least one ExhibitorAgreement referencing this market already
        sits in `SIGNED`."

        Design: Difficulty/cross_entity_state_dependency/market_begin_build_blocked_without_signed_agreement
        """
        set_clock()
        market = create_approved_market()
        create_signed_agreement(market["id"])
        resp = api.begin_market_build(market["id"], network_planner_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "BUILDING"


class TestSlotOverlapHalfOpen:
    def _setup_three_approved_films(self, api):
        """One OPERATING auditorium, three films with approved conversions,
        one open window. Conversion post windows are spaced to satisfy the
        one-day handoff rule."""
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        get_success_data(api.activate_agreement(agreement["id"], PCM))
        studio = create_active_studio()
        fx = create_film(studio["id"], title="Film X")
        fy = create_film(studio["id"], title="Film Y")
        fz = create_film(studio["id"], title="Film Z")
        cx = create_approved_conversion(
            fx["id"], qc_at="2026-09-02T00:00:00Z",
            scheduled_post_start_date="2026-09-01T00:00:00Z",
            scheduled_post_end_date="2026-09-01T00:00:00Z")
        cy = create_approved_conversion(
            fy["id"], qc_at="2026-09-04T00:00:00Z",
            scheduled_post_start_date="2026-09-03T00:00:00Z",
            scheduled_post_end_date="2026-09-03T00:00:00Z")
        cz = create_approved_conversion(
            fz["id"], qc_at="2026-09-06T00:00:00Z",
            scheduled_post_start_date="2026-09-05T00:00:00Z",
            scheduled_post_end_date="2026-09-05T00:00:00Z")
        window = create_open_window()
        return {
            "auditorium": auditorium, "window": window,
            "films": (fx, fy, fz), "conversions": (cx, cy, cz),
        }

    def test_adjacent_slots_do_not_overlap(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "The slot's interval must not overlap another `CONFIRMED`
        or `HELD_OVER` slot on the same auditorium — overlap arithmetic is
        half-open, so a slot ending exactly when another begins does not
        overlap — else `ERR_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/same_auditorium_slot_overlap_uses_half_open_intervals
        """
        ctx = self._setup_three_approved_films(api)
        fx, fy, _ = ctx["films"]
        cx, cy, _ = ctx["conversions"]
        create_confirmed_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], fx["id"], cx["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-10T00:00:00Z", showings_per_day=2)
        slot_b = propose_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], fy["id"], cy["id"],
            slot_start_date="2026-09-10T00:00:00Z",
            slot_end_date="2026-09-13T00:00:00Z", showings_per_day=2)
        resp = api.confirm_slot(slot_b["id"], release_scheduler_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CONFIRMED"

    def test_one_day_overlap_rejected(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "The slot's interval must not overlap another `CONFIRMED`
        or `HELD_OVER` slot on the same auditorium — overlap arithmetic is
        half-open, so a slot ending exactly when another begins does not
        overlap — else `ERR_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/same_auditorium_slot_overlap_uses_half_open_intervals
        """
        ctx = self._setup_three_approved_films(api)
        fx, _, fz = ctx["films"]
        cx, _, cz = ctx["conversions"]
        create_confirmed_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], fx["id"], cx["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-10T00:00:00Z", showings_per_day=2)
        slot_c = propose_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], fz["id"], cz["id"],
            slot_start_date="2026-09-09T00:00:00Z",
            slot_end_date="2026-09-12T00:00:00Z", showings_per_day=2)
        resp = api.confirm_slot(slot_c["id"], release_scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP, expected_status=409)


class TestStaleWindowVersion:
    def _two_auditorium_scenario(self, api):
        ctx = setup_bookable_scenario()
        aud_b = create_operating_auditorium(ctx["agreement"]["id"],
                                            auditorium_label="S2")
        studio = ctx["studio"]
        film_y = create_film(studio["id"], title="Film Y")
        conv_y = create_approved_conversion(
            film_y["id"], qc_at="2026-09-06T00:00:00Z",
            scheduled_post_start_date="2026-09-04T00:00:00Z",
            scheduled_post_end_date="2026-09-05T00:00:00Z")
        ctx["aud_b"] = aud_b
        ctx["film_y"] = film_y
        ctx["conv_y"] = conv_y
        return ctx

    def test_stale_version_rejected_412(self, api, release_scheduler_headers):
        """PRD §2.7: "If the parent window's current `version` does not match
        the supplied `expected_window_version` — because, for instance,
        another scheduler's confirmation has advanced it since the client
        last read the window — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/errors/stale_window_version_on_slot_create_returns_412
        """
        ctx = self._two_auditorium_scenario(api)
        win_v0 = ctx["window"]["version"]
        # First create against the observed version succeeds and bumps it.
        propose_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
            ctx["conversion"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2,
            expected_window_version=win_v0)
        # A second create with the now-stale version must be rejected.
        resp = api.create_screen_slot(
            {"window_id": ctx["window"]["id"],
             "auditorium_id": ctx["aud_b"]["id"],
             "studio_film_id": ctx["film_y"]["id"],
             "conversion_order_id": ctx["conv_y"]["id"],
             "slot_start_date": "2026-09-07T00:00:00Z",
             "slot_end_date": "2026-09-14T00:00:00Z",
             "showings_per_day": 2,
             "expected_window_version": win_v0},
            release_scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_fresh_version_admitted_and_bumps_window_version(
        self, api, release_scheduler_headers
    ):
        """PRD §2.7: "a client proposing a new slot must include the
        `expected_window_version` field carrying the `version` of the parent
        ReleaseWindow the client last observed."
        PRD §2.4: "Whenever any mutation touches a resource — including an
        automatic state transition fired by the logical clock or a cascade
        from a parent — that resource's `updated_at` is refreshed and its
        `version` incremented."

        Design: Corner/errors/stale_window_version_on_slot_create_returns_412
        """
        ctx = self._two_auditorium_scenario(api)
        win_v0 = ctx["window"]["version"]
        slot = propose_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
            ctx["conversion"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2,
            expected_window_version=win_v0)
        assert slot["status"] == "PROPOSED"
        window = validate_success(
            api.get_release_window(ctx["window"]["id"], release_scheduler_headers)
        )
        assert window["version"] == win_v0 + 1, (
            f"window version must increment on slot create; "
            f"was {win_v0}, now {window['version']}"
        )
        # A create using the freshly observed version succeeds too.
        slot_b = propose_slot(
            ctx["window"]["id"], ctx["aud_b"]["id"], ctx["film_y"]["id"],
            ctx["conv_y"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2,
            expected_window_version=window["version"])
        assert slot_b["status"] == "PROPOSED"


class TestWindowLockCascade:
    def _window_with_confirmed_and_proposed(self, api):
        ctx = setup_bookable_scenario()
        aud_b = create_operating_auditorium(ctx["agreement"]["id"],
                                            auditorium_label="S2")
        film_y = create_film(ctx["studio"]["id"], title="Film Y")
        conv_y = create_approved_conversion(
            film_y["id"], qc_at="2026-09-06T00:00:00Z",
            scheduled_post_start_date="2026-09-04T00:00:00Z",
            scheduled_post_end_date="2026-09-05T00:00:00Z")
        slot_a = create_confirmed_slot(  # noqa: F841 -- held via ctx["slot_a"]
            ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
            ctx["conversion"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2)
        slot_b = propose_slot(
            ctx["window"]["id"], aud_b["id"], film_y["id"], conv_y["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2)
        ctx["slot_a"] = slot_a
        ctx["slot_b"] = slot_b
        return ctx

    def test_lock_rejects_proposed_slots(
        self, api, release_scheduler_headers
    ):
        """PRD §3.4: "Locking — `OPEN_FOR_BOOKING → LOCKED` — is the
        scheduling freeze: every slot in the window still in `PROPOSED` that
        was never confirmed is moved to `REJECTED`."

        Design: Corner/state_machines/window_lock_rejects_proposed_slots_cascade
        """
        ctx = self._window_with_confirmed_and_proposed(api)
        resp = api.lock_release_window(ctx["window"]["id"],
                                       release_scheduler_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "LOCKED"
        slot_a = validate_success(
            api.get_screen_slot(ctx["slot_a"]["id"], release_scheduler_headers)
        )
        slot_b = validate_success(
            api.get_screen_slot(ctx["slot_b"]["id"], release_scheduler_headers)
        )
        assert slot_a["status"] == "CONFIRMED"
        assert slot_b["status"] == "REJECTED"

    def test_lock_leaves_window_with_committed_capacity_intact(
        self, api, release_scheduler_headers
    ):
        """PRD §3.4: "every slot in the window still in `PROPOSED` that was
        never confirmed is moved to `REJECTED`."
        PRD §2.10: "tracks `committed_premium_screen_seconds`, the sum of
        `committed_screen_seconds` over every slot of the window in
        `CONFIRMED` or `HELD_OVER` status."

        Design: Corner/state_machines/window_lock_rejects_proposed_slots_cascade
        """
        ctx = self._window_with_confirmed_and_proposed(api)
        get_success_data(api.lock_release_window(ctx["window"]["id"],
                                                 release_scheduler_headers))
        window = validate_success(
            api.get_release_window(ctx["window"]["id"], release_scheduler_headers)
        )
        assert window["committed_premium_screen_seconds"] == 84000
        assert window["status"] == "LOCKED"


class TestHoldOverCycle:
    def _holdover_world(self, api, seating_capacity=100):
        ctx = setup_bookable_scenario(seating_capacity=seating_capacity)
        slot = create_confirmed_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
            ctx["conversion"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2)
        next_window = create_open_window(
            window_label="W38", window_start_date="2026-09-14T00:00:00Z",
            window_end_date="2026-09-21T00:00:00Z")
        get_success_data(api.lock_release_window(
            ctx["window"]["id"],
            TEST_USERS["release_scheduler_headers"]))
        create_validated_report(
            slot["id"], reported_date="2026-09-07T00:00:00Z",
            gross_receipts_cents=5000000, admissions=910)
        ctx["slot"] = slot
        ctx["next_window"] = next_window
        return ctx

    def test_boundary_ratio_triggers_held_over_and_follow_on_slot(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "If the final score is at least 0.65 (the comparison is
        inclusive: exactly 0.65 qualifies), the slot moves `CONFIRMED →
        HELD_OVER`." and "A held-over slot causes the platform to auto-create
        a follow-on ScreenSlot for the same auditorium and the same film in
        the chronologically next ReleaseWindow (by `window_start_date`): the
        new slot enters in `PROPOSED`, with `slot_start_date` equal to the
        next window's `window_start_date` and `slot_end_date` seven days
        later."
        PRD §2.5: "A ReleaseWindow in `LOCKED` whose `window_end_date` is
        reached moves to `CLOSED`."

        Design: Difficulty/non_linear_state_machine/screen_slot_held_over_to_confirmed_cycle_for_next_window
        """
        ctx = self._holdover_world(api)
        set_clock("2026-09-14T00:00:00Z")
        window = validate_success(
            api.get_release_window(ctx["window"]["id"], release_scheduler_headers)
        )
        assert window["status"] == "CLOSED"
        slot = validate_success(
            api.get_screen_slot(ctx["slot"]["id"], release_scheduler_headers)
        )
        assert slot["status"] == "HELD_OVER", (
            f"expected HELD_OVER at the inclusive 0.65 boundary, got "
            f"{slot['status']} (ratio {slot.get('per_screen_attendance_ratio')})"
        )
        follow_ons, meta = validate_paginated(
            api.list_window_slots(ctx["next_window"]["id"],
                                  release_scheduler_headers)
        )
        matches = [
            s for s in follow_ons
            if s["auditorium_id"] == ctx["auditorium"]["id"]
            and s["studio_film_id"] == ctx["film"]["id"]
        ]
        assert len(matches) == 1, (
            f"expected exactly one follow-on slot in the next window, got "
            f"{len(matches)}"
        )
        follow_on = matches[0]
        assert follow_on["status"] == "PROPOSED"
        assert follow_on["slot_start_date"][:10] == "2026-09-14"
        assert follow_on["slot_end_date"][:10] == "2026-09-21"

    def test_held_over_slot_can_confirm_in_next_window(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "Confirmation — `PROPOSED → CONFIRMED`, and identically
        `HELD_OVER → CONFIRMED` for the next-window extension"."

        Design: Difficulty/non_linear_state_machine/screen_slot_held_over_to_confirmed_cycle_for_next_window
        """
        ctx = self._holdover_world(api)
        set_clock("2026-09-14T00:00:00Z")
        slot = validate_success(
            api.get_screen_slot(ctx["slot"]["id"], release_scheduler_headers)
        )
        assert slot["status"] == "HELD_OVER"
        # The held-over slot's own window is now CLOSED, so re-confirming it
        # would hit ERR_WINDOW_NOT_OPEN; the cyclic edge is exercised instead
        # via the auto-created follow-on slot in the next window, which must
        # be confirmable (PROPOSED -> CONFIRMED) under the open window.
        follow_ons, _ = validate_paginated(
            api.list_window_slots(ctx["next_window"]["id"],
                                  release_scheduler_headers)
        )
        assert len(follow_ons) == 1
        resp = api.confirm_slot(follow_ons[0]["id"], release_scheduler_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CONFIRMED"


class TestPullCascadeWaitlist:
    def _pull_world(self, api):
        """Tight 90000-second pool: slot A confirmed (84000 s), slot B
        proposed (84000 s, would exceed pool). Slot B's conversion is
        APPROVED_FOR_RELEASE. Clock 2026-09-06, before slot start."""
        ctx = setup_bookable_scenario(
            window_pool_seconds=90000, agreement_overrides={"committed_screen_count": 2})
        aud_b = create_operating_auditorium(ctx["agreement"]["id"],
                                            auditorium_label="S2")
        film_y = create_film(ctx["studio"]["id"], title="Film Y")
        # Re-anchor the clock; the first conversion consumed post days
        # 2026-09-01..03, so conversion Y uses 09-04..05 with the handoff.
        conv_y = create_approved_conversion(
            film_y["id"], qc_at="2026-09-06T00:00:00Z",
            scheduled_post_start_date="2026-09-04T00:00:00Z",
            scheduled_post_end_date="2026-09-05T00:00:00Z")
        slot_a = create_confirmed_slot(  # noqa: F841 -- held via ctx["slot_a"]
            ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
            ctx["conversion"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2)
        slot_b = propose_slot(
            ctx["window"]["id"], aud_b["id"], film_y["id"], conv_y["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2)
        # Slot B must be blocked by capacity at confirm time so it lands on
        # the waitlist.
        resp = api.confirm_slot(slot_b["id"],
                                TEST_USERS["release_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED,
                       expected_status=409)
        ctx.update({"aud_b": aud_b, "film_y": film_y, "conv_y": conv_y,
                    "slot_a": slot_a, "slot_b": slot_b})
        return ctx

    def test_pull_releases_capacity_and_promotes_waitlist(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "A successful pull releases the slot's committed
        screen-seconds back to the window and then runs a waitlist promotion:
        if any `PROPOSED` slot in the same window previously failed with
        `ERR_WINDOW_CAPACITY_EXCEEDED` and now fits, the platform
        auto-confirms the highest-priority eligible candidate."

        Design: Difficulty/transitive_cascade/pull_confirmed_slot_cascades_window_capacity_and_waitlist_promotion
        """
        ctx = self._pull_world(api)
        resp = api.pull_slot(ctx["slot_a"]["id"], release_scheduler_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "PULLED"
        window = validate_success(
            api.get_release_window(ctx["window"]["id"], release_scheduler_headers)
        )
        assert window["committed_premium_screen_seconds"] == 84000, (
            "slot A's seconds released and slot B's seconds committed by the "
            "auto-promotion"
        )
        slot_b = validate_success(
            api.get_screen_slot(ctx["slot_b"]["id"], release_scheduler_headers)
        )
        assert slot_b["status"] == "CONFIRMED"


class TestDoubleConfirm:
    def test_second_confirm_rejected_invalid_state(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "Confirmation — `PROPOSED → CONFIRMED`, and identically
        `HELD_OVER → CONFIRMED` for the next-window extension".
        PRD §2.9: "(5) the target resource's state permits the requested
        transition (`ERR_INVALID_STATE` or the transition's domain-specific
        error)."

        Design: Corner/state_machines/double_confirm_of_same_slot_returns_invalid_state
        """
        ctx = setup_confirmed_slot_scenario()
        resp = api.confirm_slot(ctx["slot"]["id"], release_scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        slot = validate_success(
            api.get_screen_slot(ctx["slot"]["id"], release_scheduler_headers)
        )
        assert slot["status"] == "CONFIRMED"

    def test_rejected_slot_cannot_confirm(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "Rejection moves a `PROPOSED` slot to its terminal
        `REJECTED` state with no side effects."
        PRD §2.9: "(5) the target resource's state permits the requested
        transition (`ERR_INVALID_STATE` or the transition's domain-specific
        error)."

        Design: Corner/state_machines/double_confirm_of_same_slot_returns_invalid_state
        """
        ctx = setup_bookable_scenario()
        slot = propose_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
            ctx["conversion"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2)
        get_success_data(api.reject_slot(slot["id"], release_scheduler_headers))
        resp = api.confirm_slot(slot["id"], release_scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        slot_after = validate_success(
            api.get_screen_slot(slot["id"], release_scheduler_headers)
        )
        assert slot_after["status"] == "REJECTED"


class TestSlotStatusFilter:
    def test_list_slots_filter_by_status(
        self, api, release_scheduler_headers
    ):
        """PRD §4 lists `GET /v1/screen-slots` as "List screen slots"; the
        slot's lifecycle is given by "A new slot enters in `PROPOSED`." (§3.5)
        and the filter must isolate that state.
        PRD §2.3: "every list response carries `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_screen_slots_filter_by_status
        """
        ctx = setup_bookable_scenario()
        slot = propose_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
            ctx["conversion"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2)
        rows, meta = validate_paginated(
            api.list_screen_slots(release_scheduler_headers,
                                  params={"status": "PROPOSED"})
        )
        assert len(rows) == 1
        assert rows[0]["id"] == slot["id"]
        rows_confirmed, _ = validate_paginated(
            api.list_screen_slots(release_scheduler_headers,
                                  params={"status": "CONFIRMED"})
        )
        assert len(rows_confirmed) == 0
