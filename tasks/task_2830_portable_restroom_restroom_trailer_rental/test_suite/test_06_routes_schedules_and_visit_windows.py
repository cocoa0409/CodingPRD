"""Routes and schedules: the frozen unit load, capacity, densities and visit windows."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_route_density,
    assert_service_schedule,
    assert_service_visit,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]
DRIVER = TEST_USERS["driver_operator_headers"]


def _schedule_payload(contract_id, route_id, service_day="MON",
                      window_start_minute=480, window_end_minute=600):
    return {
        "contract_id": contract_id,
        "route_id": route_id,
        "service_day": service_day,
        "window_start_minute": window_start_minute,
        "window_end_minute": window_end_minute,
    }


def _visit_payload(schedule_id, scheduled_date, window_start_minute,
                   window_end_minute, visit_kind="SERVICE"):
    return {
        "schedule_id": schedule_id,
        "visit_kind": visit_kind,
        "scheduled_date": scheduled_date,
        "window_start_minute": window_start_minute,
        "window_end_minute": window_end_minute,
    }


class TestScheduleLinking:
    """Creating the join row: both ends resolved, the load frozen, capacity gated."""

    def test_01_the_link_resolves_both_ends_and_freezes_the_unit_load(self):
        """Unknown contract and unknown route each 404; the accepted link freezes 7 units.

        PRD 3.5: "The load a schedule places on the truck is frozen at creation into
        `units_on_route`: it is the sum of `quantity` over every quote line of the named
        contract that has not been superseded, taken at the instant the schedule is
        created."
        PRD 3.5: "The word *frozen* is exact — a later re-quote that supersedes those
        lines, or a demobilization that replaces them, does not retroactively change an
        existing schedule's `units_on_route`."
        PRD 3.5: "`committed_units` is the sum of `units_on_route` over the schedules on
        that route whose `state` is `ACTIVE` — suspended and terminated schedules are
        excluded — and `density_planned_pct` is that sum multiplied by 100, divided by
        `truck_capacity_units`, with the fraction discarded."

        Design: Corner/endpoints/service_schedule_links_a_contract_to_a_route_and_freezes_units_on_route
        """
        env = fx.setup_quoted_contract(
            shape=fx.SEVEN_UNIT,
            legal_name="Ravensworth Concrete",
            site_label="Ravensworth Pour",
            authority_ref="PL-11701",
            authority_decision_ref="AD-11701",
            site_overrides={"jurisdiction_code": "OH-FR-CITY"},
        )
        assert env["contract"]["quoted_cents"] == 91500
        route = fx.create_route(
            "RT-MON-118", service_day="MON", truck_capacity_units=20,
            waste_capacity_gallons=3000,
        )

        validate_error(
            api_client.create_service_schedule(
                _schedule_payload(NON_EXISTENT_UUID, route["id"]), PLANNER
            ),
            "ERR_CONTRACT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.create_service_schedule(
                _schedule_payload(env["contract"]["id"], NON_EXISTENT_UUID), PLANNER
            ),
            "ERR_ROUTE_NOT_FOUND",
            404,
        )

        schedule = validate_success(
            api_client.create_service_schedule(
                _schedule_payload(env["contract"]["id"], route["id"]), PLANNER
            ),
            201,
        )
        assert_service_schedule(schedule)
        assert schedule["contract_id"] == env["contract"]["id"]
        assert schedule["route_id"] == route["id"]
        assert schedule["units_on_route"] == 7
        assert schedule["state"] == "ACTIVE"

        assert_route_density(
            fx.read_route(route["id"]), committed_units=7, density_planned_pct=35
        )

        requoted = validate_success(
            api_client.quote_rental_contract(
                env["contract"]["id"],
                {
                    "expected_contract_version": env["contract"]["version"],
                    "quote_note": "raise the headcount",
                },
                SALES,
            )
        )
        assert requoted["quoted_cents"] == 91500
        assert fx.read_schedule(schedule["id"])["units_on_route"] == 7

        rows, meta = validate_paginated(
            api_client.list_service_schedules(PLANNER, {"route_id": route["id"]})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == schedule["id"]

    def test_02_a_service_day_that_differs_from_the_route_day_is_a_shape_violation(self):
        """TUE on a MON route is ERR_INVALID_REQUEST, and the same payload with MON passes.

        PRD 3.5: "The declared `service_day` must equal the route's own `service_day`; a
        Tuesday schedule on a Thursday route is a request-shape violation rejected with
        `ERR_INVALID_REQUEST`."
        PRD 2.11: "3. Request shape: required fields present, types correct, enum values
        declared members, integers inside their declared ranges, and the same-payload
        ordering and conditional-field rules enumerated in §3 — `ERR_INVALID_REQUEST`."

        Design: Corner/validations/schedule_service_day_differing_from_the_route_service_day_is_refused
        """
        env = fx.setup_quoted_contract(
            shape=fx.SEVEN_UNIT,
            legal_name="Blackthorn Utilities",
            site_label="Blackthorn Trench",
            authority_ref="PL-10901",
            authority_decision_ref="AD-10901",
            site_overrides={"jurisdiction_code": "NM-BE-CITY"},
        )
        route = fx.create_route(
            "RT-MON-85", service_day="MON", truck_capacity_units=20,
            waste_capacity_gallons=3000,
        )
        assert route["service_day"] == "MON"
        assert route["status"] == "ACTIVE"

        validate_error(
            api_client.create_service_schedule(
                _schedule_payload(
                    env["contract"]["id"], route["id"], service_day="TUE"
                ),
                PLANNER,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        assert fx.read_route(route["id"])["committed_units"] == 0

        schedule = validate_success(
            api_client.create_service_schedule(
                _schedule_payload(env["contract"]["id"], route["id"]), PLANNER
            ),
            201,
        )
        assert schedule["service_day"] == "MON"
        assert schedule["units_on_route"] == 7

    def test_03_a_schedule_may_land_exactly_on_capacity_but_not_past_it(self):
        """13 units onto a 13-unit truck is accepted; the next 7 units are refused.

        PRD 3.5: "A schedule may be created only when the route's current
        `committed_units` plus the new schedule's `units_on_route` is less than or equal
        to the route's `truck_capacity_units`; landing exactly on capacity is allowed,
        and only a strictly greater total is refused, with
        `ERR_ROUTE_UNIT_CAPACITY_EXCEEDED` (HTTP 422)."
        PRD 3.5: "Because a schedule may never be added past capacity, planned density
        can never exceed 100 percent."

        Design: Corner/validations/schedule_at_exactly_route_capacity_passes_and_the_next_unit_is_refused
        """
        env = fx.setup_quoted_contract(
            shape=fx.THIRTEEN_UNIT,
            legal_name="Pennyroyal Site Group",
            site_label="Pennyroyal Flats",
            authority_ref="PL-10601",
            authority_decision_ref="AD-10601",
            site_overrides={"jurisdiction_code": "NE-DO-CITY"},
        )
        assert env["contract"]["quoted_cents"] == 181500
        smaller = fx.quote_contract(
            fx.raise_contract(env["account"]["id"], env["site"]["id"])
        )
        assert smaller["quoted_cents"] == 91500

        route = fx.create_route(
            "RT-MON-63", service_day="MON", truck_capacity_units=13,
            waste_capacity_gallons=2600,
        )

        at_capacity = validate_success(
            api_client.create_service_schedule(
                _schedule_payload(env["contract"]["id"], route["id"]), PLANNER
            ),
            201,
        )
        assert at_capacity["units_on_route"] == 13
        assert at_capacity["state"] == "ACTIVE"
        assert_route_density(
            fx.read_route(route["id"]), committed_units=13, density_planned_pct=100
        )

        validate_error(
            api_client.create_service_schedule(
                _schedule_payload(
                    smaller["id"], route["id"],
                    window_start_minute=640, window_end_minute=720,
                ),
                PLANNER,
            ),
            "ERR_ROUTE_UNIT_CAPACITY_EXCEEDED",
            422,
        )

        assert fx.read_route(route["id"])["committed_units"] == 13
        rows, meta = validate_paginated(
            api_client.list_service_schedules(PLANNER, {"route_id": route["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == at_capacity["id"]


def _forty_unit_route_with_twenty_six_committed_units():
    """One MON route at capacity 40 carrying two 13-unit schedules, each with a visit."""
    env = fx.setup_quoted_contract(
        shape=fx.THIRTEEN_UNIT,
        legal_name="Harbor Civil Works",
        site_label="Harbor Yard",
        authority_ref="PL-2001",
        authority_decision_ref="AD-2001",
        site_overrides={
            "jurisdiction_code": "CA-SD-CITY",
            "gate_open_minute": 360,
            "gate_close_minute": 1080,
            "max_truck_length_ft": 40,
        },
    )
    route = fx.create_route(
        "RT-MON-40", service_day="MON", truck_capacity_units=40,
        waste_capacity_gallons=2500,
    )
    twin = fx.quote_contract(
        fx.raise_thirteen_unit_contract(env["account"]["id"], env["site"]["id"])
    )
    first_schedule = fx.attach_schedule(env["contract"]["id"], route["id"], "MON", 480, 540)
    second_schedule = fx.attach_schedule(twin["id"], route["id"], "MON", 600, 660)
    first_visit = fx.plan_visit(first_schedule["id"], "2026-08-10", 480, 540)
    second_visit = fx.plan_visit(second_schedule["id"], "2026-08-10", 600, 660)
    env.update({
        "route": route,
        "twin": twin,
        "first_schedule": first_schedule,
        "second_schedule": second_schedule,
        "first_visit": first_visit,
        "second_visit": second_visit,
    })
    return env


class TestRouteDensityVariants:
    """Planned and realized density on one unchanged ACTIVE schedule set."""

    def test_04_planned_density_is_the_active_schedule_set_over_capacity(self):
        """Two 13-unit schedules on a 40-unit truck: committed 26, planned 65, realized 0.

        PRD 3.5: "Both density figures are integer percentages and both discard any
        fractional part."
        PRD 3.5: "`committed_units` is the sum of `units_on_route` over the schedules on
        that route whose `state` is `ACTIVE` — suspended and terminated schedules are
        excluded — and `density_planned_pct` is that sum multiplied by 100, divided by
        `truck_capacity_units`, with the fraction discarded."
        PRD 3.6: "If the route's `last_run_date` is null the realized figure is 0."

        Design: Difficulty/dual_variant_calc/route_density_planned_vs_realized_diverge_on_same_schedule_set
        """
        env = _forty_unit_route_with_twenty_six_committed_units()
        assert env["first_schedule"]["units_on_route"] == 13
        assert env["second_schedule"]["units_on_route"] == 13

        route = fx.read_route(env["route"]["id"])
        assert_route_density(
            route, committed_units=26, density_planned_pct=65, density_realized_pct=0
        )
        assert route["last_run_date"] is None
        assert env["first_visit"]["units_serviced"] == 0

    def test_05_realized_density_counts_only_serviced_units_on_the_last_run_date(self):
        """One stop serviced and one missed: planned stays 65 while realized reads 32.

        PRD 3.6: "Otherwise, sum `units_serviced` over the visits on that route whose
        `scheduled_date` equals the route's `last_run_date` and whose `state` is
        `SERVICED`, multiply by 100, divide by the route's `truck_capacity_units` and
        discard the fraction."
        PRD 3.6: "Visits in `MISSED`, `CANCELLED`, `PLANNED` or `EN_ROUTE` contribute
        nothing, which is precisely why a single missed stop pushes realized density
        below planned density on an otherwise unchanged schedule set."
        PRD 3.6: "Completion writes that figure onto the visit, sets the visit's
        `units_serviced` to the frozen `units_on_route` of its schedule —
        `units_serviced` is 0 in every state other than `SERVICED` — recomputes the
        route's `density_realized_pct`, and refreshes the rolled-up volume of every open
        haul manifest sharing the visit's route and date (§3.7)."

        Design: Difficulty/dual_variant_calc/route_density_planned_vs_realized_diverge_on_same_schedule_set
        """
        env = _forty_unit_route_with_twenty_six_committed_units()

        fx.dispatch_visit(env["first_visit"]["id"])
        serviced = fx.complete_visit(env["first_visit"]["id"], 420)
        assert serviced["state"] == "SERVICED"
        assert serviced["units_serviced"] == 13

        missed = fx.mark_visit_missed(
            env["second_visit"]["id"], "gate padlocked on arrival"
        )
        assert missed["state"] == "MISSED"
        assert missed["units_serviced"] == 0

        route = fx.read_route(env["route"]["id"])
        assert route["last_run_date"] == "2026-08-10"
        assert_route_density(
            route, committed_units=26, density_planned_pct=65, density_realized_pct=32
        )
        assert route["density_planned_pct"] - route["density_realized_pct"] == 33


def _incumbent_visit_on_a_wide_open_gate():
    """A MON route carrying one PLANNED visit at 480..540 on 2026-08-10."""
    env = fx.setup_quoted_contract(
        shape=fx.THIRTEEN_UNIT,
        legal_name="Westfall Stadium Events",
        site_label="Westfall North Gate",
        authority_ref="PL-8501",
        authority_decision_ref="AD-8501",
        account_overrides={"account_type": "EVENT", "credit_terms_days": 15},
        site_overrides={
            "jurisdiction_code": "CO-DE-CITY",
            "gate_open_minute": 360,
            "gate_close_minute": 1080,
            "max_truck_length_ft": 40,
        },
    )
    route = fx.create_route(
        "RT-MON-25", service_day="MON", truck_capacity_units=20,
        waste_capacity_gallons=3000,
    )
    schedule = fx.attach_schedule(env["contract"]["id"], route["id"], "MON", 420, 1020)
    incumbent = fx.plan_visit(schedule["id"], "2026-08-10", 480, 540)
    assert incumbent["state"] == "PLANNED"
    assert incumbent["window_start_minute"] == 480
    assert incumbent["window_end_minute"] == 540
    env.update({"route": route, "schedule": schedule, "incumbent": incumbent})
    return env


class TestVisitWindows:
    """Gate containment on the site, and buffered occupation on the route-date."""

    def test_06_gate_containment_is_inclusive_at_both_edges(self):
        """One minute early and ten minutes late are refused; the exact edges are accepted.

        PRD 3.6: "The first is **gate-window containment**: the site of the visit's
        schedule's contract publishes a gate window, and the visit's window must sit
        inside it — the site's `gate_open_minute` must be less than or equal to the
        visit's `window_start_minute`, and the visit's `window_end_minute` must be less
        than or equal to the site's `gate_close_minute`."
        PRD 3.6: "A violation is rejected with `ERR_ACCESS_WINDOW_VIOLATION` (HTTP 422)."
        PRD 3.6: "This applies to every kind of visit, including the same-day `SETUP` and
        `TEARDOWN` legs of an event surge, where the temptation to arrive before the
        gates open is strongest."

        Design: Corner/validations/visit_windows_outside_the_site_gate_window_are_refused_at_either_edge
        """
        env = fx.setup_quoted_contract(
            shape=fx.THIRTEEN_UNIT,
            legal_name="Wrenfield Municipal",
            site_label="Wrenfield Lot B",
            authority_ref="PL-10701",
            authority_decision_ref="AD-10701",
            account_overrides={"account_type": "MUNICIPAL", "credit_terms_days": 45},
            site_overrides={
                "jurisdiction_code": "UT-SL-CITY",
                "access_class": "GATED",
                "gate_open_minute": 480,
                "gate_close_minute": 1020,
                "max_truck_length_ft": 40,
            },
        )
        route = fx.create_route(
            "RT-MON-74", service_day="MON", truck_capacity_units=20,
            waste_capacity_gallons=3000,
        )
        schedule = fx.attach_schedule(
            env["contract"]["id"], route["id"], "MON", 480, 1020
        )

        validate_error(
            api_client.create_service_visit(
                _visit_payload(schedule["id"], "2026-08-10", 479, 540, "SETUP"),
                PLANNER,
            ),
            "ERR_ACCESS_WINDOW_VIOLATION",
            422,
        )
        validate_error(
            api_client.create_service_visit(
                _visit_payload(schedule["id"], "2026-08-10", 960, 1030, "TEARDOWN"),
                PLANNER,
            ),
            "ERR_ACCESS_WINDOW_VIOLATION",
            422,
        )

        on_open_edge = validate_success(
            api_client.create_service_visit(
                _visit_payload(schedule["id"], "2026-08-10", 480, 540), PLANNER
            ),
            201,
        )
        assert_service_visit(on_open_edge)
        assert on_open_edge["state"] == "PLANNED"

        on_close_edge = validate_success(
            api_client.create_service_visit(
                _visit_payload(schedule["id"], "2026-08-10", 960, 1020), PLANNER
            ),
            201,
        )
        assert on_close_edge["state"] == "PLANNED"

        rows, meta = validate_paginated(
            api_client.list_service_visits(PLANNER, {"schedule_id": schedule["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {
            on_open_edge["id"], on_close_edge["id"]
        }

    def test_07_adjacency_and_a_fifteen_minute_gap_both_conflict_on_either_side(self):
        """The twenty-minute turnaround buffer rejects gap 0 and gap 15 on both sides.

        PRD 3.6: "Our trucks need twenty minutes between stops to break down and set up,
        so each window is compared as though extended by twenty minutes at its end: the
        new visit conflicts with a candidate when the new `window_start_minute` is
        strictly less than the candidate's `window_end_minute` plus twenty **and** the
        candidate's `window_start_minute` is strictly less than the new
        `window_end_minute` plus twenty."
        PRD 3.6: "Exact adjacency therefore conflicts — a new visit starting at the very
        minute a candidate's window ends is refused — while a clear gap of exactly twenty
        minutes does not conflict."
        PRD 3.6: "Rejection carries `ERR_ROUTE_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/route_visit_windows_use_twenty_minute_buffered_half_open_minute_intervals
        """
        env = _incumbent_visit_on_a_wide_open_gate()
        schedule_id = env["schedule"]["id"]

        for start, end, kind in [
            (540, 600, "SETUP"),
            (555, 615, "SETUP"),
            (400, 465, "TEARDOWN"),
        ]:
            validate_error(
                api_client.create_service_visit(
                    _visit_payload(schedule_id, "2026-08-10", start, end, kind),
                    PLANNER,
                ),
                "ERR_ROUTE_WINDOW_CONFLICT",
                409,
            )

        rows, meta = validate_paginated(
            api_client.list_service_visits(
                PLANNER,
                {"route_id": env["route"]["id"], "scheduled_date": "2026-08-10"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == env["incumbent"]["id"]

    def test_08_a_twenty_minute_gap_clears_and_another_date_is_a_different_candidate_set(self):
        """Gap 20 is accepted on both sides, and the gap-0 window passes on the next Monday.

        PRD 3.6: "The candidate set is every visit sharing the new visit's `route_id` and
        `scheduled_date` whose `state` is `PLANNED`, `EN_ROUTE` or `SERVICED`."
        PRD 3.6: "Exact adjacency therefore conflicts — a new visit starting at the very
        minute a candidate's window ends is refused — while a clear gap of exactly twenty
        minutes does not conflict."

        Design: Difficulty/resource_temporal_overlap/route_visit_windows_use_twenty_minute_buffered_half_open_minute_intervals
        """
        env = _incumbent_visit_on_a_wide_open_gate()
        schedule_id = env["schedule"]["id"]

        before = validate_success(
            api_client.create_service_visit(
                _visit_payload(schedule_id, "2026-08-10", 400, 460, "TEARDOWN"),
                PLANNER,
            ),
            201,
        )
        assert before["state"] == "PLANNED"

        after = validate_success(
            api_client.create_service_visit(
                _visit_payload(schedule_id, "2026-08-10", 560, 620, "SETUP"), PLANNER
            ),
            201,
        )
        assert after["state"] == "PLANNED"

        other_date = validate_success(
            api_client.create_service_visit(
                _visit_payload(schedule_id, "2026-08-17", 540, 600, "SETUP"), PLANNER
            ),
            201,
        )
        assert other_date["state"] == "PLANNED"

        same_date, same_date_meta = validate_paginated(
            api_client.list_service_visits(
                PLANNER,
                {"route_id": env["route"]["id"], "scheduled_date": "2026-08-10"},
            )
        )
        assert same_date_meta["total_count"] == 3
        assert {row["id"] for row in same_date} == {
            env["incumbent"]["id"], before["id"], after["id"]
        }

        _, all_meta = validate_paginated(
            api_client.list_service_visits(PLANNER, {"route_id": env["route"]["id"]})
        )
        assert all_meta["total_count"] == 4


def _two_routes_differing_only_in_status():
    """One contract scheduled onto a SUSPENDED route and an ACTIVE route, one visit each."""
    env = fx.setup_quoted_contract(
        shape=fx.THIRTEEN_UNIT,
        legal_name="Brightwater Utilities",
        site_label="Brightwater Yard 3",
        authority_ref="PL-8301",
        authority_decision_ref="AD-8301",
        account_overrides={"account_type": "MUNICIPAL", "credit_terms_days": 45},
        site_overrides={
            "jurisdiction_code": "MI-WA-CITY",
            "gate_open_minute": 360,
            "gate_close_minute": 1080,
            "max_truck_length_ft": 40,
        },
    )
    suspended = fx.create_route(
        "RT-MON-SUSP", service_day="MON", truck_capacity_units=20,
        waste_capacity_gallons=3000, status="SUSPENDED",
    )
    live = fx.create_route(
        "RT-MON-LIVE", service_day="MON", truck_capacity_units=20,
        waste_capacity_gallons=3000, status="ACTIVE",
    )
    assert suspended["status"] == "SUSPENDED"
    assert live["status"] == "ACTIVE"

    suspended_schedule = fx.attach_schedule(
        env["contract"]["id"], suspended["id"], "MON", 480, 600
    )
    live_schedule = fx.attach_schedule(
        env["contract"]["id"], live["id"], "MON", 480, 600
    )
    env.update({
        "suspended_route": suspended,
        "live_route": live,
        "suspended_schedule": suspended_schedule,
        "live_schedule": live_schedule,
        "visit_on_suspended": fx.plan_visit(
            suspended_schedule["id"], "2026-08-10", 480, 540
        ),
        "visit_on_live": fx.plan_visit(live_schedule["id"], "2026-08-10", 480, 540),
    })
    return env


class TestVisitDispatch:
    """Dispatch is decided by the guard entity — the route — not by the visit row."""

    def test_09_dispatch_onto_a_suspended_route_is_refused_and_writes_nothing(self):
        """The visit is PLANNED and legal, yet its route's status alone refuses the dispatch.

        PRD 3.6: "The route must be available: a route whose `status` is `SUSPENDED`
        rather than `ACTIVE` is refused with `ERR_ROUTE_SUSPENDED` (HTTP 409)."
        PRD 3.6: "its `route_id` is denormalized from the schedule's route at creation
        and is never changed thereafter."
        PRD 3.6: "Dispatch advances the route's `last_run_date` to whichever is later,
        the route's existing `last_run_date` or this visit's `scheduled_date`, compared
        as `YYYY-MM-DD` strings with a null existing value treated as lower than any
        date."

        Design: Difficulty/cross_entity_state_dependency/visit_dispatch_depends_on_route_status_being_active
        """
        env = _two_routes_differing_only_in_status()
        visit = env["visit_on_suspended"]
        assert visit["route_id"] == env["suspended_route"]["id"]
        assert visit["state"] == "PLANNED"

        validate_error(
            api_client.dispatch_service_visit(visit["id"], DRIVER),
            "ERR_ROUTE_SUSPENDED",
            409,
        )

        assert fx.read_visit(visit["id"])["state"] == "PLANNED"
        route = fx.read_route(env["suspended_route"]["id"])
        assert route["last_run_date"] is None
        assert route["density_realized_pct"] == 0

    def test_10_the_byte_identical_visit_on_an_active_route_goes_en_route(self):
        """Control: the same window on the ACTIVE route dispatches and moves last_run_date.

        PRD 3.6: "Dispatching is the `DriverOperator`'s action and advances `PLANNED →
        EN_ROUTE`."
        PRD 3.6: "Dispatch advances the route's `last_run_date` to whichever is later,
        the route's existing `last_run_date` or this visit's `scheduled_date`, compared
        as `YYYY-MM-DD` strings with a null existing value treated as lower than any
        date."
        PRD 3.6: "Visits in `MISSED`, `CANCELLED`, `PLANNED` or `EN_ROUTE` contribute
        nothing, which is precisely why a single missed stop pushes realized density
        below planned density on an otherwise unchanged schedule set."

        Design: Difficulty/cross_entity_state_dependency/visit_dispatch_depends_on_route_status_being_active
        """
        env = _two_routes_differing_only_in_status()

        dispatched = validate_success(
            api_client.dispatch_service_visit(env["visit_on_live"]["id"], DRIVER)
        )
        assert dispatched["state"] == "EN_ROUTE"
        assert dispatched["units_serviced"] == 0

        live = fx.read_route(env["live_route"]["id"])
        assert live["last_run_date"] == "2026-08-10"
        assert_route_density(live, committed_units=13, density_planned_pct=65,
                             density_realized_pct=0)

        suspended = fx.read_route(env["suspended_route"]["id"])
        assert suspended["last_run_date"] is None
        assert suspended["density_realized_pct"] == 0
