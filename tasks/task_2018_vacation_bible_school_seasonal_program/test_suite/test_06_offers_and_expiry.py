"""Waitlist offers: decline/accept divergence, strict expiry, the ops sweep,
and seat conservation (PRD §2.5, §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId,
    accept_offer,
    assert_instant_equals,
    cancel_registration,
    create_program,
    decline_offer,
    get_classroom,
    get_program,
    get_registration,
    open_registration,
    set_clock,
    setup_classroom_with_queue,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_parent_headers

_REGCOORD = TEST_USERS["registration_coordinator_headers"]


def _setup_offered_head(capacity=1, waitlisted=2):
    """capacity-N classroom with the head of the waitlist OFFERED after the
    first enrollee's cancellation; returns (ctx, offered_registration)."""
    ctx = setup_classroom_with_queue(capacity=capacity, waitlisted=waitlisted)
    reg_a = ctx["registrations"][0]
    cancel_registration(reg_a["id"], ctx["family"]["id"])
    offered = ctx["registrations"][capacity]
    assert get_registration(offered["id"])["status"] == "OFFERED"
    return ctx, offered


class TestOfferBranchDivergence:
    def test_decline_fires_waterfall_for_next_head(self, api):
        """PRD §3.3: "From `OFFERED`, a registration has exactly three exits."
        and "Declining moves `OFFERED` → `DECLINED`, frees the reserved seat,
        and runs the waterfall for the classroom."

        Design: Difficulty/non_linear_state_machine/registration_offer_branch_divergence
        """
        ctx, reg_b = _setup_offered_head(capacity=1, waitlisted=3)
        reg_c = ctx["registrations"][2]
        declined = decline_offer(reg_b["id"], ctx["family"]["id"])
        assert declined["status"] == "DECLINED"

        reg_c_after = get_registration(reg_c["id"])
        assert reg_c_after["status"] == "OFFERED", (
            "the decline fired the promotion loop for the next head"
        )
        assert_instant_equals(reg_c_after["offer_expires_at"], "2026-08-03T00:00:00Z")

    def test_accept_consumes_seat_without_further_promotion(self, api):
        """PRD §3.3: "A successful acceptance moves the registration `OFFERED`
        → `ENROLLED`, stamps `enrolled_at`, clears `offer_expires_at`" — the
        seat is consumed rather than freed, so no further promotion runs (the
        divergent side-effect set between the decline and accept exits).

        Design: Difficulty/non_linear_state_machine/registration_offer_branch_divergence
        """
        ctx, reg_b = _setup_offered_head(capacity=1, waitlisted=3)
        reg_c, reg_d = ctx["registrations"][2], ctx["registrations"][3]
        decline_offer(reg_b["id"], ctx["family"]["id"])

        accepted = accept_offer(reg_c["id"], ctx["family"]["id"])
        assert accepted["status"] == "ENROLLED"
        assert accepted["enrolled_at"] is not None

        reg_d_after = get_registration(reg_d["id"])
        assert reg_d_after["status"] == "WAITLISTED"
        assert reg_d_after["waitlist_position"] == 1

        view = get_classroom(ctx["classroom"]["id"])
        assert view["enrolled_count"] == 1
        assert view["status"] == "FULL"


class TestOfferExpiryStrictBoundary:
    def _setup_expired_offer(self):
        """B OFFERED with offer_expires_at 2026-08-03T00:00:00Z (default clock
        plus the 48-hour TTL); the logical clock then set to exactly that
        expiry instant."""
        ctx, reg_b = _setup_offered_head(capacity=1, waitlisted=2)
        set_clock("2026-08-03T00:00:00Z")
        return ctx, reg_b

    def test_accept_at_exact_expiry_rejected(self, api):
        """PRD §3.3: "Acceptance requires the registration to be `OFFERED`
        (`ERR_INVALID_STATE` otherwise) and the clock to read strictly before
        `offer_expires_at`: an acceptance at or after the expiry is rejected
        with `ERR_OFFER_EXPIRED`, the registration itself flips to `EXPIRED`,
        and the waterfall runs for the classroom."

        Design: Difficulty/boundary_precision_check/offer_expiry_strict_less_than
        """
        ctx, reg_b = self._setup_expired_offer()
        resp = api.accept_registration(
            reg_b["id"], make_parent_headers(ctx["family"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED, 409)
        assert get_registration(reg_b["id"])["status"] == "EXPIRED", (
            "the late accept flips the offer inline"
        )

    def test_expired_accept_promotes_next_head_from_new_now(self, api):
        """PRD §3.3: "an acceptance at or after the expiry is rejected with
        `ERR_OFFER_EXPIRED`, the registration itself flips to `EXPIRED`, and
        the waterfall runs for the classroom", and §2.7 stamps the fresh offer "with an
        `offer_expires_at` of the promotion instant plus the program's
        `waitlist_offer_ttl_hours`" — the promotion instant is the current
        logical clock (2026-08-03T00:00:00Z), so the new expiry reads
        2026-08-05T00:00:00Z.

        Design: Difficulty/boundary_precision_check/offer_expiry_strict_less_than
        """
        ctx, reg_b = self._setup_expired_offer()
        reg_c = ctx["registrations"][2]
        api.accept_registration(reg_b["id"], make_parent_headers(ctx["family"]["id"]))

        reg_c_after = get_registration(reg_c["id"])
        assert reg_c_after["status"] == "OFFERED"
        assert_instant_equals(reg_c_after["offer_expires_at"], "2026-08-05T00:00:00Z")


class TestOfferSweep:
    def test_sweep_expires_offer_and_promotes_next(self, api):
        """PRD §3.3: expiry "fires in two ways: inline, on a late acceptance as
        above; and in batch, through the coordinator-run sweep, which flips
        every `OFFERED` registration of the program whose `offer_expires_at`
        reads at or before the current instant and then runs the waterfall per
        affected classroom" — so past expiry but before the sweep, the offer
        still stands.

        Design: Corner/cross_cutting_layers/offer_expiry_sweep_deferred_action
        """
        ctx, reg_b = _setup_offered_head(capacity=1, waitlisted=2)
        reg_c = ctx["registrations"][2]
        # Past B's expiry (2026-08-03T00:00:00Z) but no sweep has run yet.
        set_clock("2026-08-04T00:00:00Z")
        assert get_registration(reg_b["id"])["status"] == "OFFERED", (
            "expiry is deferred until the sweep runs"
        )

        program = get_program(ctx["program"]["id"])
        resp = api.sweep_expired_offers(
            ctx["program"]["id"],
            {"expected_program_version": program["version"]},
            _REGCOORD,
        )
        validate_success(resp)

        assert get_registration(reg_b["id"])["status"] == "EXPIRED"
        reg_c_after = get_registration(reg_c["id"])
        assert reg_c_after["status"] == "OFFERED"
        assert_instant_equals(reg_c_after["offer_expires_at"], "2026-08-06T00:00:00Z")

    def test_sweep_occ_stale_program_version_rejected(self, api, registration_coordinator_headers):
        """PRD §2.5: "Running the expired-offer sweep (`POST
        /vbs/programs/{program_id}/sweep-expired-offers`) requires the
        non-optional field `expected_program_version`, matching the program's
        current `version`" — mismatch reports `ERR_STALE_VERSION` (HTTP 412);
        PRD §3.3: "a sweep that finds nothing to expire is a legitimate no-op.
        A sweep increments the program's `version` by one."

        Design: Corner/cross_cutting_layers/occ_sweep_stale_program_version_rejected
        """
        program = create_program()
        open_registration(program["id"])
        observed = get_program(program["id"])["version"]

        resp1 = api.sweep_expired_offers(
            program["id"], {"expected_program_version": observed},
            registration_coordinator_headers,
        )
        data1 = validate_success(resp1)
        assert data1["version"] == observed + 1, (
            "even a no-op sweep advances the version"
        )

        resp2 = api.sweep_expired_offers(
            program["id"], {"expected_program_version": observed},
            registration_coordinator_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_STALE_VERSION, 412)


class TestSeatConservation:
    def _setup(self):
        """capacity 2 FULL: A, B ENROLLED; C WAITLISTED."""
        return setup_classroom_with_queue(capacity=2, waitlisted=1)

    def test_cancel_then_accept_restores_enrolled_count(self, api):
        """PRD §2.7: "A classroom's `open_seats` is its `capacity` minus the
        number of its `ENROLLED` registrations minus the number of its
        `OFFERED` registrations" — the cancel (-1) and the compensating accept
        (+1) return `enrolled_count` to its original value with zero drift;
        the reserved OFFERED seat is converted, not duplicated.

        Design: Difficulty/compensating_invariant/seat_conservation_cancel_then_accept
        """
        ctx = self._setup()
        reg_a, _reg_b, reg_c = ctx["registrations"]
        cancel_registration(reg_a["id"], ctx["family"]["id"])
        mid = get_classroom(ctx["classroom"]["id"])
        assert mid["enrolled_count"] == 1
        assert mid["offered_count"] == 1

        accepted = accept_offer(reg_c["id"], ctx["family"]["id"])
        assert accepted["status"] == "ENROLLED"

        final = get_classroom(ctx["classroom"]["id"])
        assert final["enrolled_count"] == 2
        assert final["offered_count"] == 0
        assert final["status"] == "FULL", "compensation restores the original fill"

    def test_enrolled_count_matches_source_rows(self, api):
        """PRD §2.10: "Derived counters and rollups are recomputed from their
        source rows rather than cached: classroom `enrolled_count`,
        `offered_count`, `waitlist_count`, `open_seats`, `required_adults`,
        `confirmed_adult_count`, and `staffing_status`" — the counter
        never drifts from a filtered count of its ENROLLED source rows.

        Design: Difficulty/compensating_invariant/seat_conservation_cancel_then_accept
        """
        ctx = self._setup()
        reg_a, _reg_b, reg_c = ctx["registrations"]
        cancel_registration(reg_a["id"], ctx["family"]["id"])
        accept_offer(reg_c["id"], ctx["family"]["id"])

        data, meta = validate_paginated(
            api.list_registrations(
                _REGCOORD,
                params={"classroom_id": ctx["classroom"]["id"], "status": "ENROLLED"},
            )
        )
        view = get_classroom(ctx["classroom"]["id"])
        assert meta["total_count"] == 2
        assert view["enrolled_count"] == meta["total_count"], (
            "derived counter and source rows reconcile"
        )
