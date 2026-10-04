"""Breadth corners: response envelope, authentication, existence, RBAC denials,
creation defaults, unique and range constraints, terminal lockdowns, birth
certificate immutability, ownership checks, and selector determinism."""
from test_helpers import (
    ASSOCIATE,
    MANAGER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_to_dressed,
    create_customer,
    create_party,
    create_paid_walk_in,
    create_store,
    create_walk_in_session,
    create_workshop_payload,
    is_iso8601_timestamp,
    make_customer_headers,
    pay_party_deposit,
    pay_session_cash,
    set_clock,
    setup_workshop_env,
    validate_error,
    validate_success,
)
from test_helpers import (
    create_gift_card_payload,
    create_plush_model_payload,
    create_consumable_payload,
    create_station_payload,
)


class TestResponseEnvelope:
    def test_success_object_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" with
        meta.api_request_id / meta.api_request_timestamp / response_type / data, and:
        "The `api_request_id` is a server-generated unique identifier for the request
        that starts with `req_`."

        Design: Corner/endpoints/response_envelope_success_object_shape
        """
        store = create_store(name="Envelope Store", party_room_count=1)
        resp = api.get_store(store["id"], MANAGER)
        body = resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        request_id = body["meta"].get("api_request_id", "")
        assert isinstance(request_id, str) and request_id.startswith("req_"), (
            f"api_request_id must start with req_, got {request_id!r}"
        )
        assert is_iso8601_timestamp(body["meta"].get("api_request_timestamp", "")), (
            "api_request_timestamp must be ISO 8601"
        )
        assert body["response_type"] == "object"
        assert body["data"]["id"] == store["id"]


class TestAuthAndExistence:
    def test_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing `X-User-Role`, carrying an undeclared role
        value, or — for an entity-backed role — missing `X-User-ID` is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/endpoints/unauthenticated_missing_role_header_returns_401
        """
        store = create_store(name="Auth Store", party_room_count=1)
        validate_error(
            api.get_store(store["id"], headers={"X-User-ID": "whoever"}),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )

    def test_get_nonexistent_store_returns_not_found(self, api):
        """PRD §2.8: "the server validates existence sequentially from left to right
        and rejects immediately with `ERR_NOT_FOUND` at the first identifier that
        does not resolve."

        Design: Corner/endpoints/get_nonexistent_store_returns_404
        """
        create_store(name="Ghost Store", party_room_count=1)
        validate_error(
            api.get_store(NON_EXISTENT_UUID, MANAGER),
            ApiErrorId.ERR_NOT_FOUND,
        )


class TestRbacDenials:
    def test_customer_cannot_finalize_party(self, api):
        """PRD §4: the finalize endpoint's authorized role is StoreManager
        ("| POST | `/parties/{id}/finalize` | Finalize a confirmed party and compute
        the final amount due | StoreManager |"), and PRD §2.1: "A request whose role
        is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/endpoints/customer_cannot_finalize_party_rbac_denied
        """
        store = create_store(name="RBAC Store", party_room_count=1)
        customer = create_customer(email="rbac@example.com", full_name="R Back")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-10T18:00:00Z",
            guest_count=6,
            package_tier="BASIC",
            staffing_mode="SELF_GUIDED",
        )
        pay_party_deposit(party, customer["id"])
        validate_error(
            api.finalize_party(party["id"], make_customer_headers(customer["id"])),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

    def test_associate_cannot_create_plush_model(self, api):
        """PRD §4: the plush-model creation endpoint's authorized role is
        StoreManager ("| POST | `/plush-models` | Create a plush model |
        StoreManager |"), and PRD §2.1: "A request whose role is not permitted for
        the target endpoint is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/endpoints/associate_cannot_create_plush_model_rbac_denied
        """
        create_store(name="Model Store", party_room_count=1)
        validate_error(
            api.create_plush_model(
                create_plush_model_payload(
                    name="Denied Duck",
                    sku="DDK-01",
                    base_price_cents=1000,
                    required_stuffing_grams=100,
                ),
                ASSOCIATE,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )


class TestEntityCreationCorners:
    def test_consumable_on_hand_initialized_from_initial_qty(self, api):
        """PRD §3.1: "The row's `on_hand_qty` starts at `initial_qty`, is decremented
        as workshop sessions and build-and-ship assemblies consume stock, and is
        incremented when a manager records a restock with a `quantity`."

        Design: Corner/entities/consumable_on_hand_initialized_from_initial_qty
        """
        store = create_store(name="Stock Store", party_room_count=1)
        chip = validate_success(
            api.create_consumable(
                create_consumable_payload(store["id"], "SOUND_CHIP", initial_qty=25),
                MANAGER,
            ),
            expected_status=201,
        )
        assert chip["on_hand_qty"] == 25
        assert chip["version"] == 1
        assert isinstance(chip["id"], str) and chip["id"]

    def test_workshop_session_starts_in_select_with_zero_consumption(self, api):
        """PRD §3.3: "A new session begins in `SELECT` status, stamps `started_at`
        from the logical clock, and has no assigned station yet:
        `assigned_station_id` stays empty until the first advance." and
        "the session records the same amount as `stuffing_grams_used` (zero until
        this point)."

        Design: Corner/entities/workshop_session_starts_in_select_with_zero_consumption
        """
        env = setup_workshop_env(
            store_name="Init Store",
            fiber_qty=5000,
            chip_qty=None,
            model_overrides={
                "name": "Init Ibis",
                "sku": "II-01",
                "base_price_cents": 1500,
                "required_stuffing_grams": 100,
            },
        )
        session = create_walk_in_session(env)
        assert session["status"] == "SELECT"
        assert session["stuffing_grams_used"] == 0
        assert session["sound_chip_used"] is False
        assert session["assigned_station_id"] is None

    def test_duplicate_gift_card_code_rejected(self, api):
        """PRD §3.9: "A `StoreManager` issues a gift card with a `code` unique across
        all gift cards and a strictly positive `initial_balance_cents`"

        Design: Corner/entities/duplicate_gift_card_code_rejected
        """
        validate_success(
            api.create_gift_card(
                create_gift_card_payload(code="GC-DUP", initial_balance_cents=1000),
                MANAGER,
            ),
            expected_status=201,
        )
        validate_error(
            api.create_gift_card(
                create_gift_card_payload(code="GC-DUP", initial_balance_cents=2000),
                MANAGER,
            ),
            ApiErrorId.ERR_VALIDATION,
        )

    def test_party_guest_count_out_of_range_rejected(self, api):
        """PRD §3.6: "a `guest_count` between 6 and 20 inclusive"

        Design: Corner/entities/party_guest_count_out_of_range_rejected
        """
        store = create_store(name="Range Store", party_room_count=1)
        customer = create_customer(email="range@example.com", full_name="Range R")
        set_clock("2026-10-01T00:00:00Z")
        validate_error(
            api.create_party(
                {
                    "store_id": store["id"],
                    "customer_id": customer["id"],
                    "party_start": "2026-10-10T18:00:00Z",
                    "duration_minutes": 120,
                    "guest_count": 5,
                    "package_tier": "BASIC",
                    "staffing_mode": "SELF_GUIDED",
                },
                make_customer_headers(customer["id"]),
            ),
            ApiErrorId.ERR_VALIDATION,
        )


class TestStateMachineCorners:
    def test_advance_step_on_paid_session_returns_invalid_state(self, api):
        """PRD §3.3: "An advance attempted from a state with no outgoing transition —
        such as any advance on a terminal session — is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/advance_step_on_paid_session_returns_invalid_state
        """
        env = setup_workshop_env(
            store_name="Term Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Term Tern",
                "sku": "TT-01",
                "base_price_cents": 1500,
                "required_stuffing_grams": 100,
            },
        )
        session = create_walk_in_session(env)
        advance_to_dressed(session["id"])
        pay_session_cash(session["id"], env["customer"]["id"])
        validate_error(
            api.advance_workshop(session["id"], ASSOCIATE),
            ApiErrorId.ERR_INVALID_STATE,
        )

    def test_abandon_on_abandoned_session_returns_invalid_state(self, api):
        """PRD §3.4: "A `WorkshopAssociate` may abandon any non-terminal session,
        moving it to `ABANDONED`."

        Design: Corner/state_machines/abandon_on_abandoned_session_returns_invalid_state
        """
        env = setup_workshop_env(
            store_name="Dbl Store",
            fiber_qty=5000,
            chip_qty=None,
            model_overrides={
                "name": "Dbl Dove",
                "sku": "DDO-01",
                "base_price_cents": 1500,
                "required_stuffing_grams": 100,
            },
        )
        session = create_walk_in_session(env)
        from test_helpers import advance_session

        advance_session(session["id"])
        validate_success(api.abandon_workshop(session["id"], ASSOCIATE))
        validate_error(
            api.abandon_workshop(session["id"], ASSOCIATE),
            ApiErrorId.ERR_INVALID_STATE,
        )

    def test_handoff_before_ready_returns_invalid_state(self, api):
        """PRD §3.8: "When the session is eventually paid, the order auto-transitions
        from `IN_ASSEMBLY` to `READY_FOR_PICKUP`. Handoff to the carrier is performed
        by an associate supplying a `carrier_code` and a `tracking_number`, both
        required; the order moves to `HANDED_TO_CARRIER`"

        Design: Corner/state_machines/handoff_before_ready_returns_invalid_state
        """
        env = setup_workshop_env(
            store_name="Ship Corner",
            fiber_qty=5000,
            chip_qty=None,
            model_overrides={
                "name": "Ship Shark",
                "sku": "SSH-01",
                "base_price_cents": 2500,
                "required_stuffing_grams": 200,
            },
        )
        from test_helpers import create_build_ship_order

        order = create_build_ship_order(
            env["store"]["id"], env["customer"], env["model"]["id"], recipient_name="Rcpt"
        )
        validate_error(
            api.handoff_build_ship_order(
                order["id"], {"carrier_code": "UPS", "tracking_number": "1ZX"}, ASSOCIATE
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )

    def test_birth_certificate_immutable_after_payment(self, api):
        """PRD §3.9: "once the origin session reaches `PAID`, both fields are
        immutable and further personalization attempts are rejected with
        `ERR_REFERENTIAL_INTEGRITY`."

        Design: Corner/state_machines/birth_certificate_immutable_after_payment
        """
        env = setup_workshop_env(
            store_name="Cert Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Cert Cat",
                "sku": "CCA-01",
                "base_price_cents": 1500,
                "required_stuffing_grams": 100,
            },
        )
        customer = env["customer"]
        headers = make_customer_headers(customer["id"])
        session = create_walk_in_session(env)
        advance_to_dressed(session["id"])
        animal_id = validate_success(api.get_workshop(session["id"], headers))[
            "stuffed_animal_id"
        ]
        validate_success(
            api.personalize_birth_certificate(
                animal_id,
                {"birth_cert_name": "Whiskers", "birth_cert_birth_date": "2026-10-01"},
                headers,
            )
        )
        pay_session_cash(session["id"], customer["id"])
        validate_error(
            api.personalize_birth_certificate(
                animal_id,
                {"birth_cert_name": "Changed", "birth_cert_birth_date": "2026-10-02"},
                headers,
            ),
            ApiErrorId.ERR_REFERENTIAL_INTEGRITY,
        )

    def test_report_lost_by_non_owner_forbidden(self, api):
        """PRD §3.9: "The lost-toy service applies to completed animals and is
        strictly owner-only: the acting customer's identity must match the animal's
        `customer_id`, otherwise the request is rejected with `ERR_UNAUTHORIZED`"

        Design: Corner/state_machines/report_lost_by_non_owner_forbidden
        """
        env = setup_workshop_env(
            store_name="Own Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Own Owl",
                "sku": "OO-01",
                "base_price_cents": 1500,
                "required_stuffing_grams": 100,
            },
            customer_email="ownA@example.com",
        )
        _, animal_id = create_paid_walk_in(env)
        other = create_customer(email="ownB@example.com", full_name="Owner B")
        validate_error(
            api.report_animal_lost(animal_id, make_customer_headers(other["id"])),
            ApiErrorId.ERR_UNAUTHORIZED,
        )


class TestStationSelectorCorner:
    def test_selector_picks_lowest_occupancy_then_earliest_created(self, api):
        """PRD §3.3: "Among candidates, the station with the lowest current occupancy
        wins; ties break to the station created earliest, and the entity identifier
        is never consulted as a tie-breaker."

        Design: Corner/calculations/station_selector_picks_lowest_occupancy_then_earliest_created_at
        """
        store = create_store(name="Selector Store", party_room_count=1)
        customer = create_customer(email="sel@example.com", full_name="Sel S")
        from test_helpers import create_model, provision_consumables

        model = create_model(
            name="Sel Swan",
            sku="SSW-01",
            base_price_cents=1500,
            required_stuffing_grams=100,
        )
        provision_consumables(store["id"], fiber_qty=5000)
        first = validate_success(
            api.create_station(
                create_station_payload(store["id"], "STUFF", capacity=1), MANAGER
            ),
            expected_status=201,
        )
        validate_success(
            api.create_station(
                create_station_payload(store["id"], "STUFF", capacity=1), MANAGER
            ),
            expected_status=201,
        )
        session = validate_success(
            api.create_workshop(
                create_workshop_payload(store["id"], customer["id"], model["id"]),
                ASSOCIATE,
            ),
            expected_status=201,
        )
        after = validate_success(api.advance_workshop(session["id"], ASSOCIATE))
        assert after["assigned_station_id"] == first["id"], (
            "at equal occupancy the earliest-created station must win the tie"
        )
