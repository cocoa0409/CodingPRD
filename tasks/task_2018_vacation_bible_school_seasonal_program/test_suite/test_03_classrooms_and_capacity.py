"""Classroom shape, seat-pool accounting, close cascades, OCC (PRD §2.5, §2.7, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    cancel_registration,
    create_classroom,
    create_classroom_payload,
    create_program,
    get_classroom,
    register_child,
    setup_classroom_with_queue,
    setup_open_program_with_classroom,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_parent_headers

_DIRECTOR = TEST_USERS["program_director_headers"]
_REGCOORD = TEST_USERS["registration_coordinator_headers"]


class TestClassroomShape:
    def test_inverted_age_band_rejected(self, api, registration_coordinator_headers):
        """PRD §2.9 (priority 0): "`age_min` is not greater than `age_max`;
        `capacity` is at least 1" — well-formedness failures report
        `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/entities/classroom_create_inverted_age_band_rejected
        """
        program = create_program()
        resp = api.create_classroom(
            create_classroom_payload(program["id"], age_min=7, age_max=4),
            registration_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_get_nonexistent_classroom_returns_not_found(self, api, registration_coordinator_headers):
        """PRD §2.9 (priority 3): "path and body references exist, validated
        left to right" — failures report `ERR_NOT_FOUND` (HTTP 404).

        Design: Corner/entities/classroom_get_nonexistent_returns_not_found
        """
        resp = api.get_classroom(NON_EXISTENT_UUID, registration_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_undeclared_computed_field_rejected(self, api, registration_coordinator_headers):
        """PRD §2.9 (priority 0): "all required fields are present; no
        undeclared fields appear; enums, integers, and dates parse" —
        well-formedness failures report `ERR_INVALID_REQUEST` (HTTP 400), and
        `enrolled_count` is a derived counter (PRD §2.10), never an input.

        Design: Corner/entities/classroom_create_rejects_undeclared_computed_field
        """
        program = create_program()
        payload = create_classroom_payload(program["id"])
        payload["enrolled_count"] = 99
        resp = api.create_classroom(payload, registration_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestCapacityBoundary:
    def test_exact_fill_enrolls_and_flips_full(self, api):
        """PRD §3.2: "When the classroom has at least one open seat, the
        registration is born `ENROLLED` with `enrolled_at` stamped to the
        current instant; if that enrollment consumed the last open seat, the
        classroom flips `ACCEPTING` → `FULL`."

        Design: Difficulty/boundary_precision_check/capacity_boundary_exact_fill
        """
        program, classroom = setup_open_program_with_classroom(capacity=2)
        from test_helpers import setup_family_with_children
        family, children = setup_family_with_children(count=3)

        reg1 = register_child(children[0]["id"], classroom["id"], family["id"])
        assert reg1["status"] == "ENROLLED", "open_seats was 2 >= 1"
        reg2 = register_child(children[1]["id"], classroom["id"], family["id"])
        assert reg2["status"] == "ENROLLED", (
            "boundary: open_seats was exactly 1 — admission is >= 1"
        )
        view = get_classroom(classroom["id"])
        assert view["status"] == "FULL"
        assert view["enrolled_count"] == 2
        assert view["open_seats"] == 0

    def test_registration_at_zero_open_seats_waitlists(self, api):
        """PRD §3.2: "When no seat is open, the registration is born
        `WAITLISTED` and receives its `waitlist_position` per §2.7." — a full
        classroom waitlists rather than erroring.

        Design: Difficulty/boundary_precision_check/capacity_boundary_exact_fill
        """
        program, classroom = setup_open_program_with_classroom(capacity=2)
        from test_helpers import setup_family_with_children
        family, children = setup_family_with_children(count=3)
        register_child(children[0]["id"], classroom["id"], family["id"])
        register_child(children[1]["id"], classroom["id"], family["id"])

        reg3 = register_child(children[2]["id"], classroom["id"], family["id"])
        assert reg3["status"] == "WAITLISTED"
        assert reg3["waitlist_position"] == 1


class TestOfferedSeatsConsumePool:
    def _setup_offered_reservation(self):
        """capacity 2: A, B ENROLLED then A cancelled -> C OFFERED
        (enrolled 1, offered 1)."""
        ctx = setup_classroom_with_queue(capacity=2, waitlisted=1)
        reg_a, _reg_b, reg_c = ctx["registrations"]
        cancel_registration(reg_a["id"], ctx["family"]["id"])
        ctx["offered_registration"] = reg_c
        return ctx

    def test_new_registration_waitlists_despite_enrolled_below_capacity(self, api):
        """PRD §2.7: "A classroom's `open_seats` is its `capacity` minus the
        number of its `ENROLLED` registrations minus the number of its
        `OFFERED` registrations: an outstanding waitlist offer reserves a seat,
        while a `WAITLISTED` registration consumes none."

        Design: Difficulty/resource_temporal_overlap/classroom_capacity_pool_counts_offers
        """
        ctx = self._setup_offered_reservation()
        from test_helpers import create_child
        extra = create_child(ctx["family"]["id"])
        reg = register_child(extra["id"], ctx["classroom"]["id"], ctx["family"]["id"])
        assert reg["status"] == "WAITLISTED", (
            "the pool is full even though enrolled_count 1 < capacity 2"
        )
        assert reg["waitlist_position"] == 1

    def test_pool_counters_reflect_offer_reservation(self, api):
        """PRD §2.7: "A classroom's `open_seats` is its `capacity` minus the
        number of its `ENROLLED` registrations minus the number of its
        `OFFERED` registrations".

        Design: Difficulty/resource_temporal_overlap/classroom_capacity_pool_counts_offers
        """
        ctx = self._setup_offered_reservation()
        view = get_classroom(ctx["classroom"]["id"])
        assert view["enrolled_count"] == 1
        assert view["offered_count"] == 1
        assert view["open_seats"] == 0


class TestClassroomPatch:
    def test_capacity_below_enrolled_rejected(self, api):
        """PRD §3.1: "`capacity` may not drop below the current
        `enrolled_count` (`ERR_CAPACITY_BELOW_ENROLLED`)".

        Design: Corner/validations/patch_capacity_below_enrolled_rejected
        """
        ctx = setup_classroom_with_queue(capacity=2, waitlisted=0)
        classroom = get_classroom(ctx["classroom"]["id"])
        assert classroom["enrolled_count"] == 2
        resp = api.patch_classroom(
            classroom["id"],
            {"capacity": 1, "expected_classroom_version": classroom["version"]},
            _REGCOORD,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_BELOW_ENROLLED, 409)
        assert get_classroom(classroom["id"])["capacity"] == 2

    def test_occ_stale_classroom_version_rejected(self, api, registration_coordinator_headers):
        """PRD §2.5: "Editing a classroom's configuration (`PATCH
        /vbs/classrooms/{classroom_id}`) requires the non-optional field
        `expected_classroom_version`, carrying the `version` the client last
        observed on that classroom. If the classroom's version has advanced
        since — through a status flip or a prior edit — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_classroom_patch_stale_version_rejected
        """
        program = create_program()
        classroom = create_classroom(program["id"], capacity=10)
        observed_version = classroom["version"]

        resp1 = api.patch_classroom(
            classroom["id"],
            {"capacity": 20, "expected_classroom_version": observed_version},
            registration_coordinator_headers,
        )
        data1 = validate_success(resp1)
        assert data1["capacity"] == 20
        assert data1["version"] == observed_version + 1

        resp2 = api.patch_classroom(
            classroom["id"],
            {"age_max": 7, "expected_classroom_version": observed_version},
            registration_coordinator_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_STALE_VERSION, 412)
        assert get_classroom(classroom["id"])["age_max"] == 6, (
            "the rejected patch applied nothing"
        )

    def test_accept_after_capacity_shrink_returns_classroom_full(self, api):
        """PRD §3.3: "Acceptance also re-checks capacity, because an offer's
        reserved seat survives a capacity shrink: if `enrolled_count` has
        reached `capacity`, acceptance fails with `ERR_CLASSROOM_FULL`."

        Design: Corner/validations/accept_after_capacity_shrink_returns_classroom_full
        """
        ctx = setup_classroom_with_queue(capacity=2, waitlisted=1)
        reg_a, _reg_b, reg_c = ctx["registrations"]
        cancel_registration(reg_a["id"], ctx["family"]["id"])

        classroom = get_classroom(ctx["classroom"]["id"])
        resp_patch = api.patch_classroom(
            classroom["id"],
            {"capacity": 1, "expected_classroom_version": classroom["version"]},
            _REGCOORD,
        )
        data_patch = validate_success(resp_patch)
        assert data_patch["capacity"] == 1, "shrink to exactly enrolled_count is legal"

        resp_accept = api.accept_registration(
            reg_c["id"], make_parent_headers(ctx["family"]["id"])
        )
        validate_error(resp_accept, ApiErrorId.ERR_CLASSROOM_FULL, 409)
        assert get_registration_status(api, reg_c["id"]) == "OFFERED", (
            "the offer survives; only the accept failed"
        )


def get_registration_status(api, registration_id) -> str:
    resp = api.get_registration(registration_id, _REGCOORD)
    return validate_success(resp)["status"]


class TestClassroomClose:
    def test_close_with_enrolled_rejected(self, api):
        """PRD §3.1: "Closing a classroom requires `enrolled_count` zero —
        otherwise `ERR_CLASSROOM_NOT_EMPTY`".

        Design: Corner/validations/classroom_close_with_enrolled_rejected
        """
        # capacity 2 with two children fills the classroom exactly: the second
        # enrollment flips ACCEPTING -> FULL (PRD §3.2). The failed close must
        # leave that state untouched.
        ctx = setup_classroom_with_queue(capacity=2, waitlisted=0)
        resp = api.close_classroom(ctx["classroom"]["id"], _REGCOORD)
        validate_error(resp, ApiErrorId.ERR_CLASSROOM_NOT_EMPTY, 409)
        assert get_classroom(ctx["classroom"]["id"])["status"] == "FULL"

    def test_close_cancels_waitlisted_and_offered(self, api):
        """PRD §3.1: "On close, every `WAITLISTED` or `OFFERED` registration of
        the classroom transitions to `CANCELLED` with `cancellation_reason`
        `CLASSROOM_CLOSED`".

        Design: Corner/state_machines/classroom_close_cancels_waitlisted_and_offered
        """
        # capacity 1: A ENROLLED; B, C, D WAITLISTED; D cancelled early;
        # A cancelled -> B promoted OFFERED, C still WAITLISTED.
        ctx = setup_classroom_with_queue(capacity=1, waitlisted=3)
        reg_a, reg_b, reg_c, reg_d = ctx["registrations"]
        cancel_registration(reg_d["id"], ctx["family"]["id"])
        cancel_registration(reg_a["id"], ctx["family"]["id"])
        assert get_registration_status(api, reg_b["id"]) == "OFFERED"

        resp = api.close_classroom(ctx["classroom"]["id"], _REGCOORD)
        data = validate_success(resp)
        assert data["status"] == "CLOSED"

        reg_b_after = validate_success(api.get_registration(reg_b["id"], _REGCOORD))
        assert reg_b_after["status"] == "CANCELLED"
        assert reg_b_after["cancellation_reason"] == "CLASSROOM_CLOSED"
        reg_c_after = validate_success(api.get_registration(reg_c["id"], _REGCOORD))
        assert reg_c_after["status"] == "CANCELLED"
        assert reg_c_after["cancellation_reason"] == "CLASSROOM_CLOSED"
        reg_d_after = validate_success(api.get_registration(reg_d["id"], _REGCOORD))
        assert reg_d_after["status"] == "CANCELLED"
        assert reg_d_after["cancellation_reason"] == "FAMILY_REQUEST", (
            "an already-terminal registration is untouched by the cascade"
        )

    def test_close_releases_confirmed_assignments(self, api):
        """PRD §3.1: "`PROPOSED` role assignments of the classroom are
        unaffected, while `CONFIRMED` ones transition to `RELEASED`".

        Design: Corner/state_machines/classroom_close_releases_confirmed_assignments
        """
        from test_helpers import create_volunteer_with_assignment, get_assignment
        program, classroom = setup_open_program_with_classroom(capacity=10)
        cleared = create_volunteer_with_assignment(
            program["id"], classroom["id"], "LEAD_TEACHER", decide_count=3
        )
        assert cleared["assignment"]["status"] == "CONFIRMED"
        pending = create_volunteer_with_assignment(
            program["id"], classroom["id"], "CRAFT_LEADER", decide_count=0
        )
        assert pending["assignment"]["status"] == "PROPOSED"

        resp = api.close_classroom(classroom["id"], _REGCOORD)
        assert validate_success(resp)["status"] == "CLOSED"

        released = get_assignment(cleared["assignment"]["id"])
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None
        untouched = get_assignment(pending["assignment"]["id"])
        assert untouched["status"] == "PROPOSED"


class TestDerivedCounters:
    def test_enrolled_count_reconciles_after_cancel(self, api):
        """PRD §2.10: "Derived counters and rollups are recomputed from their
        source rows rather than cached: classroom `enrolled_count`,
        `offered_count`, `waitlist_count`, `open_seats`, `required_adults`,
        `confirmed_adult_count`, and `staffing_status`". PRD §2.7: "A
        classroom's `open_seats` is its `capacity` minus the number of its
        `ENROLLED` registrations minus the number of its `OFFERED`
        registrations".

        Design: Corner/cross_cutting_layers/derived_enrolled_count_reconciles_after_cancel
        """
        # capacity 1 with one child: enrolled fills the only seat.
        ctx = setup_classroom_with_queue(capacity=1, waitlisted=0)
        reg_a = ctx["registrations"][0]
        mid = get_classroom(ctx["classroom"]["id"])
        assert mid["enrolled_count"] == 1
        assert mid["open_seats"] == 0

        cancel_registration(reg_a["id"], ctx["family"]["id"])
        after = get_classroom(ctx["classroom"]["id"])
        assert after["enrolled_count"] == 0
        assert after["open_seats"] == 1, (
            "derived counters reconcile with the source row change immediately"
        )
