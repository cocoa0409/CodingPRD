"""Cross-entity state gating and temporal window conflicts."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_assignment,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_store,
    load_route_day,
    lot_entry,
    make_rep_headers,
    make_supervisor_headers,
    set_clock,
    start_route_day,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOrderCreationGatedByRouteDayState:
    def _setup_loaded_not_started_day(self):
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 50)], rep
        )
        return rep, store, product, day

    def test_order_create_on_loaded_day_rejected(self, api):
        """PRD §3.4: "While the route day is IN_PROGRESS and the store is
        ACTIVE, the rep captures an order on the handheld: a payload containing
        the route_day_id, the store_id, an order_type (defaulting to STANDARD;
        EVENT_SURGE is permitted only on an event day, and supplying it on a
        standard day is ERR_VALIDATION), and a lines array."
        PRD §5: "ERR_ROUTE_DAY_NOT_IN_PROGRESS | 409 Conflict".

        Design: Difficulty/cross_entity_state_dependency/order_creation_gated_by_route_day_state
        """
        rep, store, product, day = self._setup_loaded_not_started_day()

        resp = api.create_order(
            {
                "route_day_id": day["id"],
                "store_id": store["id"],
                "lines": [{"product_id": product["id"], "qty_ordered_cases": 5}],
            },
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_NOT_IN_PROGRESS)

    def test_no_order_persisted_on_rejected_create(self, api):
        """PRD §3.4: "While the route day is IN_PROGRESS and the store is
        ACTIVE, the rep captures an order on the handheld: a payload containing
        the route_day_id, the store_id, an order_type (defaulting to STANDARD;
        EVENT_SURGE is permitted only on an event day, and supplying it on a
        standard day is ERR_VALIDATION), and a lines array."

        Design: Difficulty/cross_entity_state_dependency/order_creation_gated_by_route_day_state
        """
        rep, store, product, day = self._setup_loaded_not_started_day()

        resp = api.create_order(
            {
                "route_day_id": day["id"],
                "store_id": store["id"],
                "lines": [{"product_id": product["id"], "qty_ordered_cases": 5}],
            },
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_NOT_IN_PROGRESS)

        orders, meta = validate_paginated(
            api.list_orders(
                make_supervisor_headers(), params={"route_day_id": day["id"]}
            )
        )
        assert len(orders) == 0
        assert meta["total_count"] == 0


class TestPromoExecutionGatedByAgreementState:
    def _setup_scheduled_agreement(self):
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 10)], rep
        )
        start_route_day(day["id"], rep)
        resp = api_client.create_promo_agreement(
            {
                "store_id": store["id"],
                "product_id": product["id"],
                "window_start": "2026-09-01",
                "window_end": "2026-09-10",
                "display_type": "ENDCAP",
                "rebate_cents": 5000,
            },
            make_supervisor_headers(),
        )
        agreement = validate_success(resp, expected_status=201)
        return rep, day, agreement

    def test_execution_against_scheduled_agreement_rejected(self, api):
        """PRD §3.8: "The rep executes against an ACTIVE agreement by submitting
        a promo execution carrying the agreement_id, the route_day_id of an
        IN_PROGRESS day, a photo_url of compliance evidence, and the
        expected_promo_agreement_version concurrency guard — a stale view of the
        agreement fails with ERR_STALE_VERSION."

        Design: Difficulty/cross_entity_state_dependency/promo_execution_gated_by_agreement_state
        """
        rep, day, agreement = self._setup_scheduled_agreement()
        assert agreement["status"] == "SCHEDULED"

        resp = api.create_promo_execution(
            {
                "agreement_id": agreement["id"],
                "route_day_id": day["id"],
                "photo_url": "https://photos/x.jpg",
                "expected_promo_agreement_version": agreement["version"],
            },
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

        executions, meta = validate_paginated(
            api.list_promo_executions(
                make_supervisor_headers(), params={"agreement_id": agreement["id"]}
            )
        )
        assert len(executions) == 0

    def test_rejected_create_does_not_bump_agreement_version(self, api):
        """PRD §2.4: "an integer version that starts at 1 and increments by
        exactly 1 on every mutation of that resource."
        PRD §3.8: "Verification — permitted only while the agreement remains
        ACTIVE."

        Design: Difficulty/cross_entity_state_dependency/promo_execution_gated_by_agreement_state
        """
        rep, day, agreement = self._setup_scheduled_agreement()

        resp = api.create_promo_execution(
            {
                "agreement_id": agreement["id"],
                "route_day_id": day["id"],
                "photo_url": "https://photos/x.jpg",
                "expected_promo_agreement_version": agreement["version"],
            },
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

        # The rejected create is not a mutation: the OCC parent's version is
        # unchanged.
        after = validate_success(
            api.get_promo_agreement(agreement["id"], make_supervisor_headers())
        )
        assert after["version"] == agreement["version"]
        assert after["status"] == "SCHEDULED"


class TestPromoWindowHalfOpenOverlap:
    def _setup_first_agreement(self):
        set_clock()
        store = create_store()
        product = create_product()
        resp = api_client.create_promo_agreement(
            {
                "store_id": store["id"],
                "product_id": product["id"],
                "window_start": "2026-09-01",
                "window_end": "2026-09-10",
                "display_type": "ENDCAP",
                "rebate_cents": 5000,
            },
            make_supervisor_headers(),
        )
        agreement = validate_success(resp, expected_status=201)
        return store, product, agreement

    def test_adjacent_window_permitted(self, api):
        """PRD §3.8: "while pure adjacency (one window's end equal to the
        other's start) is permitted."

        Design: Difficulty/resource_temporal_overlap/promo_window_half_open_overlap_and_adjacency
        """
        store, product, agreement = self._setup_first_agreement()

        resp = api.create_promo_agreement(
            {
                "store_id": store["id"],
                "product_id": product["id"],
                "window_start": "2026-09-10",
                "window_end": "2026-09-20",
                "display_type": "AISLE",
                "rebate_cents": 3000,
            },
            make_supervisor_headers(),
        )
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "SCHEDULED"

    def test_genuine_overlap_rejected(self, api):
        """PRD §3.8: "Agreements for the same store and product may not
        overlap: creation is rejected with ERR_PROMO_WINDOW_OVERLAP when an
        existing SCHEDULED, ACTIVE, or COMPLETED agreement's window intersects
        the new one — intersection meaning the existing window starts before the
        new window ends and the new window starts before the existing window
        ends — while pure adjacency (one window's end equal to the other's
        start) is permitted."

        Design: Difficulty/resource_temporal_overlap/promo_window_half_open_overlap_and_adjacency
        """
        store, product, agreement = self._setup_first_agreement()

        # Adjacent one goes through, so the pair count check sees both.
        resp = api.create_promo_agreement(
            {
                "store_id": store["id"],
                "product_id": product["id"],
                "window_start": "2026-09-10",
                "window_end": "2026-09-20",
                "display_type": "AISLE",
                "rebate_cents": 3000,
            },
            make_supervisor_headers(),
        )
        validate_success(resp, expected_status=201)

        resp = api.create_promo_agreement(
            {
                "store_id": store["id"],
                "product_id": product["id"],
                "window_start": "2026-09-05",
                "window_end": "2026-09-12",
                "display_type": "DUMP_BIN",
                "rebate_cents": 1000,
            },
            make_supervisor_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PROMO_WINDOW_OVERLAP)

        agreements, meta = validate_paginated(
            api.list_promo_agreements(
                make_supervisor_headers(), params={"store_id": store["id"]}
            )
        )
        assert len(agreements) == 2


class TestStoreAssignmentWeekdayIntersection:
    def _setup_two_routes_one_store(self):
        set_clock()
        rep1 = create_rep(full_name="Rep One")
        rep2 = create_rep(full_name="Rep Two")
        store = create_store()
        route1 = create_route(rep1["id"], territory_code="T-1")
        route2 = create_route(rep2["id"], territory_code="T-2")
        resp = api_client.create_assignment(
            {
                "route_id": route1["id"],
                "store_id": store["id"],
                "service_weekdays": ["TUE", "WED"],
                "stop_sequence": 1,
            },
            make_supervisor_headers(),
        )
        asg1 = validate_success(resp, expected_status=201)
        return store, route2, asg1

    def test_intersecting_weekday_set_conflicts(self, api):
        """PRD §3.2: "The system refuses to create an assignment whose weekday
        set intersects that of another ACTIVE assignment for the same store —
        regardless of which route the other assignment belongs to — rejecting
        with ERR_ASSIGNMENT_DAY_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/store_assignment_weekday_set_intersection_conflict
        """
        store, route2, asg1 = self._setup_two_routes_one_store()

        resp = api_client.create_assignment(
            {
                "route_id": route2["id"],
                "store_id": store["id"],
                "service_weekdays": ["WED", "FRI"],
                "stop_sequence": 1,
            },
            make_supervisor_headers(),
        )
        # Intersection {WED} is non-empty.
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_DAY_CONFLICT)

    def test_disjoint_weekday_set_allowed(self, api):
        """PRD §3.2: "The system refuses to create an assignment whose weekday
        set intersects that of another ACTIVE assignment for the same store —
        regardless of which route the other assignment belongs to — rejecting
        with ERR_ASSIGNMENT_DAY_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/store_assignment_weekday_set_intersection_conflict
        """
        store, route2, asg1 = self._setup_two_routes_one_store()

        resp = api_client.create_assignment(
            {
                "route_id": route2["id"],
                "store_id": store["id"],
                "service_weekdays": ["FRI"],
                "stop_sequence": 1,
            },
            make_supervisor_headers(),
        )
        asg2 = validate_success(resp, expected_status=201)
        assert asg2["status"] == "ACTIVE"

        assignments, meta = validate_paginated(
            api_client.list_assignments(
                make_supervisor_headers(), params={"store_id": store["id"]}
            )
        )
        assert len(assignments) == 2
        assert all(a["status"] == "ACTIVE" for a in assignments)
