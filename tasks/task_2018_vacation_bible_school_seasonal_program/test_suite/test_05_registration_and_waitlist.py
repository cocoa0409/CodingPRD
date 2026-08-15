"""Registration intake rules and the waitlist queue (PRD §2.7, §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    cancel_registration,
    create_child,
    get_classroom,
    get_registration,
    register_child,
    set_clock,
    setup_classroom_with_queue,
    setup_family_with_children,
    setup_open_program_with_classroom,
    validate_error,
    validate_paginated,
)
from test_helpers.test_users import TEST_USERS, make_parent_headers

_REGCOORD = TEST_USERS["registration_coordinator_headers"]


class TestIntakeConstraints:
    def test_duplicate_registration_same_program_rejected(self, api):
        """PRD §3.2: "the child must not already hold an `ENROLLED`,
        `WAITLISTED`, or `OFFERED` registration in the same program
        (`ERR_DUPLICATE_REGISTRATION`)".

        Design: Corner/validations/duplicate_registration_same_program_rejected
        """
        program = create_two_classroom_program()
        family, children = setup_family_with_children(count=1)
        register_child(children[0]["id"], program["koalas"]["id"], family["id"])
        resp = api.create_registration(
            {"child_id": children[0]["id"], "classroom_id": program["bears"]["id"]},
            make_parent_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION, 409)

    def test_age_boundary_birthday_on_start_date_counted(self, api):
        """PRD §3.2: "A birthday falling exactly on `start_date` counts as
        already turned, so nothing is subtracted in that case. The band check
        is inclusive on both ends: an age below `age_min` or above `age_max` is
        rejected with `ERR_AGE_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/calculations/age_boundary_birthday_on_start_date_counted
        """
        _program, classroom = setup_open_program_with_classroom(
            capacity=10, age_min=4, age_max=6
        )
        family = create_family_alone()
        child_in = create_child(family["id"], birth_date="2020-08-17")
        reg = register_child(child_in["id"], classroom["id"], family["id"])
        assert reg["status"] == "ENROLLED"
        assert reg["age_at_registration"] == 6, (
            "birthday on the 2026-08-17 start_date counts as turned"
        )

        child_out = create_child(
            family["id"], birth_date="2019-08-16", grade_completed="GRADE_1"
        )
        resp = api.create_registration(
            {"child_id": child_out["id"], "classroom_id": classroom["id"]},
            make_parent_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGE_OUT_OF_RANGE, 422)

    def test_registration_after_window_close_rejected(self, api):
        """PRD §3.2: "the program must be `REGISTRATION_OPEN` with the clock
        reading within the inclusive registration window
        (`ERR_REGISTRATION_WINDOW_CLOSED`)".

        Design: Corner/validations/registration_after_window_close_rejected
        """
        _program, classroom = setup_open_program_with_classroom(capacity=10)
        family, children = setup_family_with_children(count=1)
        # Window closes 2026-08-15T23:59:59Z; move the logical clock past it.
        set_clock("2026-08-16T00:00:00Z")
        resp = api.create_registration(
            {"child_id": children[0]["id"], "classroom_id": classroom["id"]},
            make_parent_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED, 409)


class TestInvalidTransitions:
    def test_accept_from_enrolled_returns_invalid_state(self, api):
        """PRD §3.3: "Acceptance requires the registration to be `OFFERED`
        (`ERR_INVALID_STATE` otherwise)".

        Design: Corner/state_machines/accept_from_enrolled_returns_invalid_state
        """
        # capacity 1 with one child: exactly one ENROLLED registration.
        ctx = setup_classroom_with_queue(capacity=1, waitlisted=0)
        reg_a = ctx["registrations"][0]
        assert reg_a["status"] == "ENROLLED"
        resp = api.accept_registration(
            reg_a["id"], make_parent_headers(ctx["family"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_classroom(ctx["classroom"]["id"])["enrolled_count"] == 1, (
            "no double-enroll side effect"
        )

    def test_second_cancel_returns_invalid_state(self, api):
        """PRD §3.2: "Cancelling from any other state — including `OFFERED`,
        whose answer paths live in §3.3 — fails with `ERR_INVALID_STATE`." A
        `CANCELLED` registration is terminal, so a second cancel is such a
        case.

        Design: Corner/state_machines/registration_second_cancel_returns_invalid_state
        """
        # capacity 1 with one child: after the first cancel, enrolled drops to
        # zero; the second cancel must be a clean no-op.
        ctx = setup_classroom_with_queue(capacity=1, waitlisted=0)
        reg_a = ctx["registrations"][0]
        cancel_registration(reg_a["id"], ctx["family"]["id"])
        resp = api.cancel_registration(
            reg_a["id"], make_parent_headers(ctx["family"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        view = get_classroom(ctx["classroom"]["id"])
        assert view["enrolled_count"] == 0
        assert view["offered_count"] == 0, (
            "no phantom side effects from the rejected call"
        )


class TestWaitlistPositions:
    def test_fcfs_positions_recompute_after_withdrawal(self, api):
        """PRD §2.7: "Queue order is `created_at` ascending on server-assigned
        monotonic timestamps with no id-based tie-break; `waitlist_position` is
        the 1-based dense rank in that order, is null whenever the registration
        is not `WAITLISTED`, and recomputes whenever a registration enters or
        leaves the queue."

        Design: Corner/calculations/waitlist_position_fcfs_recompute
        """
        ctx = setup_classroom_with_queue(capacity=1, waitlisted=3)
        _reg_a, reg_b, reg_c, reg_d = ctx["registrations"]
        assert reg_b["waitlist_position"] == 1
        assert reg_c["waitlist_position"] == 2
        assert reg_d["waitlist_position"] == 3

        cancel_registration(reg_b["id"], ctx["family"]["id"])
        assert get_registration(reg_c["id"])["waitlist_position"] == 1
        assert get_registration(reg_d["id"])["waitlist_position"] == 2

    def test_status_filter_is_exact(self, api):
        """PRD §2.3: "Individual list endpoints additionally expose
        resource-specific filters — `status`, `program_id`, `family_id`,
        `child_id`, `classroom_id`, `volunteer_id`, `email`, `category`,
        `supply_item_id`, `program_day_id`, `registration_id`, `priority_tier`,
        and `include_archived` — which §3 introduces with the workflows and §4
        enumerates per endpoint."

        Design: Corner/endpoints/registrations_filter_by_status
        """
        ctx = setup_classroom_with_queue(capacity=2, waitlisted=1)
        reg_c = ctx["registrations"][2]
        data, meta = validate_paginated(
            api.list_registrations(
                _REGCOORD,
                params={"classroom_id": ctx["classroom"]["id"], "status": "WAITLISTED"},
            )
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == reg_c["id"]
        assert data[0]["status"] == "WAITLISTED"


class TestCancelPromotesWaitlistHead:
    """Depth-3 cascade: cancel -> seat flip -> promotion -> re-rank."""

    def _setup(self):
        """capacity 2 FULL: A, B ENROLLED; C, D WAITLISTED (positions 1, 2)."""
        ctx = setup_classroom_with_queue(capacity=2, waitlisted=2)
        assert get_classroom(ctx["classroom"]["id"])["status"] == "FULL"
        return ctx

    def test_cancel_flips_full_back_to_accepting(self, api):
        """PRD §3.2: "Cancelling an `ENROLLED` registration — by a `Parent`,
        with `cancellation_reason` `FAMILY_REQUEST`, or by a
        `RegistrationCoordinator`, with `ADMIN` — drops the classroom's
        `enrolled_count` by one; if the classroom was `FULL` it flips back to
        `ACCEPTING` and the promotion waterfall runs".

        Design: Difficulty/transitive_cascade/cancel_enrollee_promotes_waitlist_head
        """
        ctx = self._setup()
        reg_a = ctx["registrations"][0]
        resp = api.cancel_registration(
            reg_a["id"], make_parent_headers(ctx["family"]["id"])
        )
        from test_helpers import validate_success
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        assert data["cancellation_reason"] == "FAMILY_REQUEST"

        view = get_classroom(ctx["classroom"]["id"])
        assert view["status"] == "ACCEPTING", "seat freed: FULL flipped back"
        assert view["enrolled_count"] == 1

    def test_promotion_stamps_ttl_and_recomputes_positions(self, api):
        """PRD §2.7: "the waiting registration with the earliest `created_at`
        is promoted to `OFFERED` and stamped with an `offer_expires_at` of the
        promotion instant plus the program's `waitlist_offer_ttl_hours`
        (default 48 hours, at least 1)"; PRD §2.4: "At startup the clock reads
        exactly 2026-08-01T00:00:00Z"; and positions recompute on leaving the
        queue (§2.7).

        Design: Difficulty/transitive_cascade/cancel_enrollee_promotes_waitlist_head
        """
        ctx = self._setup()
        reg_a, _reg_b, reg_c, reg_d = ctx["registrations"]
        cancel_registration(reg_a["id"], ctx["family"]["id"])

        reg_c_after = get_registration(reg_c["id"])
        assert reg_c_after["status"] == "OFFERED"
        assert_instant_equals(reg_c_after["offer_expires_at"], "2026-08-03T00:00:00Z")
        reg_d_after = get_registration(reg_d["id"])
        assert reg_d_after["status"] == "WAITLISTED"
        assert reg_d_after["waitlist_position"] == 1

        view = get_classroom(ctx["classroom"]["id"])
        assert view["offered_count"] == 1


class TestPromotionEvaluationOrder:
    """The waterfall promotes one head, recomputes open_seats, and repeats."""

    def _setup(self):
        """capacity 2: A, B ENROLLED; C, D, E WAITLISTED (positions 1, 2, 3);
        then A cancelled."""
        ctx = setup_classroom_with_queue(capacity=2, waitlisted=3)
        reg_a = ctx["registrations"][0]
        cancel_registration(reg_a["id"], ctx["family"]["id"])
        return ctx

    def test_exactly_one_promotion_per_freed_seat(self, api):
        """PRD §2.7: "Because the fresh offer itself consumes a seat,
        `open_seats` is recomputed after every single promotion; the loop
        promotes exactly one, recomputes, and repeats, stopping as soon as no
        open seat or no waiting registration remains."

        Design: Difficulty/combinatorial_formula/waitlist_promotion_evaluation_order_loop
        """
        ctx = self._setup()
        _reg_a, _reg_b, reg_c, reg_d, reg_e = ctx["registrations"]
        reg_c_after = get_registration(reg_c["id"])
        assert reg_c_after["status"] == "OFFERED"
        assert_instant_equals(reg_c_after["offer_expires_at"], "2026-08-03T00:00:00Z")

        reg_d_after = get_registration(reg_d["id"])
        assert reg_d_after["status"] == "WAITLISTED", (
            "promotion stopped after one: open_seats recomputed to 0"
        )
        assert reg_d_after["waitlist_position"] == 1
        reg_e_after = get_registration(reg_e["id"])
        assert reg_e_after["status"] == "WAITLISTED"
        assert reg_e_after["waitlist_position"] == 2

    def test_pool_counters_after_single_promotion(self, api):
        """PRD §2.7: "A classroom's `open_seats` is its `capacity` minus the
        number of its `ENROLLED` registrations minus the number of its
        `OFFERED` registrations" — after one promotion into a capacity-2
        classroom with one enrollee, the pool reads zero open seats.

        Design: Difficulty/combinatorial_formula/waitlist_promotion_evaluation_order_loop
        """
        ctx = self._setup()
        view = get_classroom(ctx["classroom"]["id"])
        assert view["enrolled_count"] == 1
        assert view["offered_count"] == 1
        assert view["open_seats"] == 0


def create_two_classroom_program():
    from test_helpers import create_classroom, create_program, open_registration
    program = create_program()
    koalas = create_classroom(program["id"], name="Koalas", age_min=4, age_max=6)
    bears = create_classroom(program["id"], name="Bears", age_min=4, age_max=6)
    open_registration(program["id"])
    return {"program": program, "koalas": koalas, "bears": bears}


def create_family_alone():
    from test_helpers import create_family
    return create_family()
