"""Capacity boundaries and interval overlap semantics: station occupancy >=
capacity admission, drop exhaustion boundary, host overlap with touching
endpoints, and buffered station windows."""
from test_helpers import (
    ApiErrorId,
    create_collection_drop_payload,
    create_customer,
    create_party,
    create_staff,
    create_store,
    create_walk_in_session,
    create_workshop_payload,
    get_success_data,
    make_customer_headers,
    pay_party_deposit,
    pay_session_cash,
    set_clock,
    setup_workshop_env,
    validate_error,
    validate_success,
)
from test_helpers import ASSOCIATE, advance_session, advance_to_dressed


class TestStationOccupancyBoundary:
    def _setup(self, api):
        env = setup_workshop_env(
            store_name="Boundary Store",
            fiber_qty=10000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Boundary Bat",
                "sku": "BB-01",
                "base_price_cents": 2000,
                "required_stuffing_grams": 100,
            },
        )
        c_a = create_customer(email="c11a@example.com", full_name="A")
        c_b = create_customer(email="c11b@example.com", full_name="B")
        c_c = create_customer(email="c11c@example.com", full_name="C")
        return env, c_a, c_b, c_c

    def test_third_walkin_rejected_at_exact_capacity(self, api):
        """PRD §3.3: "If the relevant `SELECT`-type station pool at the store has
        every station at occupancy equal to `capacity`, the new session is rejected
        with `ERR_STATION_AT_CAPACITY`."

        Design: Difficulty/boundary_precision_check/station_occupancy_at_exact_capacity_admission_boundary
        """
        env, c_a, c_b, c_c = self._setup(api)
        w_a = create_walk_in_session(env, customer=c_a)
        advance_session(w_a["id"])
        w_b = create_walk_in_session(env, customer=c_b)
        advance_session(w_b["id"])
        # Both stations of the SELECT pool... the single capacity-2 station now
        # holds two occupants: occupancy 2 >= capacity 2.
        validate_error(
            api.create_workshop(
                create_workshop_payload(env["store"]["id"], c_c["id"], env["model"]["id"]),
                ASSOCIATE,
            ),
            ApiErrorId.ERR_STATION_AT_CAPACITY,
        )

    def test_admission_recovers_after_occupant_goes_terminal(self, api):
        """PRD §3.3: "The occupancy of a station at any instant is the count of
        non-terminal sessions at the same store whose occupied interval covers that
        instant, counting sessions that begin exactly when another ends as
        non-overlapping."

        Design: Difficulty/boundary_precision_check/station_occupancy_at_exact_capacity_admission_boundary
        """
        env, c_a, c_b, c_c = self._setup(api)
        w_a = create_walk_in_session(env, customer=c_a)
        advance_session(w_a["id"])
        w_b = create_walk_in_session(env, customer=c_b)
        advance_session(w_b["id"])
        validate_error(
            api.create_workshop(
                create_workshop_payload(env["store"]["id"], c_c["id"], env["model"]["id"]),
                ASSOCIATE,
            ),
            ApiErrorId.ERR_STATION_AT_CAPACITY,
        )
        advance_to_dressed(w_a["id"])
        pay_session_cash(w_a["id"], c_a["id"])
        admitted = validate_success(
            api.create_workshop(
                create_workshop_payload(env["store"]["id"], c_c["id"], env["model"]["id"]),
                ASSOCIATE,
            ),
            expected_status=201,
        )
        assert admitted["status"] == "SELECT"


class TestDropExhaustionBoundary:
    def _setup_drop(self, api):
        from test_helpers import MANAGER

        env = setup_workshop_env(
            store_name="Drop Store",
            fiber_qty=10000,
            chip_qty=None,
            station_capacity=4,
            model_overrides={
                "name": "Licensed Lynx",
                "sku": "LL-01",
                "base_price_cents": 6000,
                "is_licensed": True,
                "required_stuffing_grams": 300,
            },
        )
        c_a = create_customer(email="c12a@example.com", full_name="DA")
        c_b = create_customer(email="c12b@example.com", full_name="DB")
        set_clock("2026-10-01T00:00:00Z")
        drop = get_success_data(
            api.create_collection_drop(
                create_collection_drop_payload(
                    env["model"]["id"],
                    name="Lynx Drop",
                    drop_start="2026-10-01T00:00:00Z",
                    drop_end="2026-11-01T00:00:00Z",
                    per_customer_limit=5,
                    total_units=1,
                ),
                MANAGER,
            )
        )
        return env, c_a, c_b, drop

    def test_advance_rejected_at_exact_total_units(self, api):
        """PRD §3.2: "The guard rails reject claims with `ERR_DROP_LIMIT_REACHED` in
        two situations: when the customer has already selected `per_customer_limit`
        units of the drop's model across their non-terminal sessions, and when
        `units_claimed` has reached `total_units`."

        Design: Difficulty/boundary_precision_check/collection_drop_units_claimed_at_total_units_exhaustion
        """
        env, c_a, c_b, drop = self._setup_drop(api)
        w_a = create_walk_in_session(env, customer=c_a, collection_drop_id=drop["id"])
        advance_session(w_a["id"])  # claims the only unit
        w_b = create_walk_in_session(env, customer=c_b, collection_drop_id=drop["id"])
        validate_error(
            api.advance_workshop(w_b["id"], ASSOCIATE),
            ApiErrorId.ERR_DROP_LIMIT_REACHED,
        )

    def test_abandon_releases_unit_reopening_drop(self, api):
        """PRD §3.4: "From `SELECTED`, it additionally decrements `units_claimed` on
        the associated drop by one when the model is licensed, restoring availability
        for other customers' claims."

        Design: Difficulty/boundary_precision_check/collection_drop_units_claimed_at_total_units_exhaustion
        """
        env, c_a, c_b, drop = self._setup_drop(api)
        w_a = create_walk_in_session(env, customer=c_a, collection_drop_id=drop["id"])
        advance_session(w_a["id"])
        w_b = create_walk_in_session(env, customer=c_b, collection_drop_id=drop["id"])
        validate_error(
            api.advance_workshop(w_b["id"], ASSOCIATE),
            ApiErrorId.ERR_DROP_LIMIT_REACHED,
        )
        validate_success(api.abandon_workshop(w_a["id"], ASSOCIATE))
        after = validate_success(api.advance_workshop(w_b["id"], ASSOCIATE))
        assert after["status"] == "SELECTED", (
            "abandoning the claiming session must restore units_claimed and reopen the drop"
        )


class TestHostOverlapTouchingEndpoints:
    def _setup_hosts(self, api):
        store = create_store(name="Host Store", party_room_count=4)
        create_staff(store["id"], role_title="PARTY_HOST", display_name="Host Solo")
        c_a = create_customer(email="c15a@example.com", full_name="HA")
        c_b = create_customer(email="c15b@example.com", full_name="HB")
        c_c = create_customer(email="c15c@example.com", full_name="HC")
        set_clock("2026-10-01T00:00:00Z")
        party_a = create_party(
            c_a, store["id"],
            party_start="2026-10-10T10:00:00Z", guest_count=6,
            package_tier="BASIC", staffing_mode="STAFF_HOSTED",
        )
        pay_party_deposit(party_a, c_a["id"])
        party_b = create_party(
            c_b, store["id"],
            party_start="2026-10-10T12:00:00Z", guest_count=6,
            package_tier="BASIC", staffing_mode="STAFF_HOSTED",
        )
        party_c = create_party(
            c_c, store["id"],
            party_start="2026-10-10T11:00:00Z", guest_count=6,
            package_tier="BASIC", staffing_mode="STAFF_HOSTED",
        )
        return store, c_b, c_c, party_b, party_c

    def test_touching_endpoint_booking_succeeds_with_same_host(self, api):
        """PRD §3.6: "a `StaffMember` at the same store whose `role_title` is
        `PARTY_HOST` and who holds no `ACTIVE` block overlapping the party interval
        (touching endpoints permitted)"

        Design: Difficulty/resource_temporal_overlap/party_host_overlap_with_touching_endpoints_allowed
        """
        _, c_b, _, party_b, _ = self._setup_hosts(api)
        paid = pay_party_deposit(party_b, c_b["id"])
        assert paid["status"] == "DEPOSIT_PAID", (
            "12:00-14:00 only touches the existing 10:00-12:00 block, so the same "
            "host must be selectable"
        )

    def test_strict_overlap_rejected_host_unavailable(self, api):
        """PRD §3.6: "an empty pool rejects the deposit with `ERR_HOST_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/party_host_overlap_with_touching_endpoints_allowed
        """
        _, _, c_c, _, party_c = self._setup_hosts(api)
        validate_error(
            api.pay_party_deposit(
                party_c["id"],
                {"payment_amount_cents": party_c["deposit_amount_cents"]},
                make_customer_headers(c_c["id"]),
            ),
            ApiErrorId.ERR_HOST_UNAVAILABLE,
        )


class TestStationBufferWindowOverlap:
    def _setup_buffer_store(self, api):
        return setup_workshop_env(
            store_name="Buffer Store",
            fiber_qty=10000,
            chip_qty=None,
            station_capacity=1,
            model_overrides={
                "name": "Buffer Bear",
                "sku": "BBE-01",
                "base_price_cents": 2000,
                "required_stuffing_grams": 100,
            },
        )

    def test_session_thirty_minutes_later_collides_with_buffer(self, api):
        """PRD §3.3: "A session occupies its station across a half-open interval that
        begins fifteen minutes before the session start (the setup buffer) and
        extends forty-five minutes of session duration plus a further fifteen minutes
        (the teardown buffer) — a ninety-minute occupied span in total."

        Design: Difficulty/resource_temporal_overlap/station_buffer_window_overlap_vs_half_open_room_semantics
        """
        env = self._setup_buffer_store(api)
        c_a = create_customer(email="c16a@example.com", full_name="BA")
        c_b = create_customer(email="c16b@example.com", full_name="BB")
        set_clock("2026-10-01T10:00:00Z")
        w_a = create_walk_in_session(env, customer=c_a)
        advance_session(w_a["id"])
        set_clock("2026-10-01T10:30:00Z")
        validate_error(
            api.create_workshop(
                create_workshop_payload(env["store"]["id"], c_b["id"], env["model"]["id"]),
                ASSOCIATE,
            ),
            ApiErrorId.ERR_STATION_AT_CAPACITY,
        )

    def test_session_after_full_buffered_span_is_admitted(self, api):
        """PRD §3.3: "counting sessions that begin exactly when another ends as
        non-overlapping."

        Design: Difficulty/resource_temporal_overlap/station_buffer_window_overlap_vs_half_open_room_semantics
        """
        env = self._setup_buffer_store(api)
        c_a = create_customer(email="c16a@example.com", full_name="BA")
        c_b = create_customer(email="c16b@example.com", full_name="BB")
        set_clock("2026-10-01T10:00:00Z")
        w_a = create_walk_in_session(env, customer=c_a)
        advance_session(w_a["id"])
        # First session's buffered span: [09:45, 11:00). At 11:00 the spans only
        # touch, so the second walk-in is admitted.
        set_clock("2026-10-01T11:00:00Z")
        admitted = validate_success(
            api.create_workshop(
                create_workshop_payload(env["store"]["id"], c_b["id"], env["model"]["id"]),
                ASSOCIATE,
            ),
            expected_status=201,
        )
        assert admitted["status"] == "SELECT"
