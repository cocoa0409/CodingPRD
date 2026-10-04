"""Error catalogue coverage: refusals, uniqueness, RBAC isolation, ownership,
decorative fields and the validator priority order."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    enroll_agent,
    enroll_capacity_owner,
    get_success_data,
    make_capacity_owner_headers,
    make_freight_agent_headers,
    post_ledger_entry,
    promote_load,
    register_customer,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SETTLEMENT_OPERATOR = TEST_USERS["settlement_operator_headers"]
SAFETY_REVIEWER = TEST_USERS["safety_reviewer_headers"]


class TestAuthenticationAndAuthorization:
    """Priority 1 and 2: the header gate and the role gate."""

    def test_list_loads_without_user_context_header_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role that
        is not one of the roles declared below, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD §2.10: "1. Authentication and user context — both headers present and
        the role declared. Refusal:
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/errors/list_loads_without_user_context_header_returns_401
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        promote_load(agent, customer["customer_ref"])

        refused = api.list_loads({})
        validate_error(
            refused, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, expected_status=401
        )
        assert refused.json()["data"]["error_id"] != "ERR_INSUFFICIENT_PERMISSIONS"

    def test_agent_create_by_freight_agent_cannot_succeed(self, api):
        """PRD §2.1: "A request whose role is valid but is not authorized for
        the operation it is attempting is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §2.10: "2. Role authority on the operation. Refusal:
        `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/errors/agent_create_by_freight_agent_cannot_succeed
        """
        set_logical_clock()
        refused = api.create_agent(
            {
                "agent_code": "AG-C30-X",
                "legal_name": "Unauthorized Enrollment",
                "home_state": "TX",
                "commission_rate_pct": 0.12,
                "territory_codes": ["TX"],
            },
            TEST_USERS["freight_agent_headers"],
        )
        validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

        rows, meta = validate_paginated(api.list_agents(TEST_USERS["network_admin_headers"]))
        assert meta["total_count"] == 0 and rows == []

    def test_capacity_owner_operator_cannot_promote_a_load(self, api):
        """PRD §2.1: "A `CapacityOwnerOperator` accepts and declines board
        offers, covers an awarded load, dispatches a trip, records delivery, and
        aborts a non-terminal trip, and reads its own fleet, credentials, ledger
        and trips."

        Design: Corner/rbac/capacity_owner_operator_cannot_promote_a_load
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        bco = enroll_capacity_owner()

        refused = api.create_load(
            {
                "agent_id": agent["id"],
                "customer_ref": customer["customer_ref"],
                "origin_state": "TX",
                "destination_state": "OK",
                "linehaul_revenue_cents": 180000,
                "dispatched_miles": 1240,
            },
            make_capacity_owner_headers(bco["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

        rows, meta = validate_paginated(api.list_loads(TEST_USERS["network_admin_headers"]))
        assert meta["total_count"] == 0

        allowed = validate_success(
            api.create_load(
                {
                    "agent_id": agent["id"],
                    "customer_ref": customer["customer_ref"],
                    "origin_state": "TX",
                    "destination_state": "OK",
                    "linehaul_revenue_cents": 180000,
                    "dispatched_miles": 1240,
                },
                make_freight_agent_headers(agent["id"]),
            ), 201
        )
        assert allowed["status"] == "POSTED"

    def test_load_cancel_by_a_non_owner_agent_is_rejected(self, api):
        """PRD §3.4: "the load must still be `POSTED` (else
        `ERR_LOAD_NOT_CANCELLABLE`) and the caller must own it (else
        `ERR_UNAUTHORIZED`)."
        PRD §2.10: "5. Ownership. Where the role model assigns ownership, the
        caller must own the resource it is acting on. Refusal: `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/load_cancel_by_a_non_owner_agent_is_rejected
        """
        set_logical_clock()
        owner = enroll_agent(territory_codes=["TX"])
        customer = register_customer(owner)
        load = promote_load(owner, customer["customer_ref"])
        intruder = enroll_agent(territory_codes=["OK"], home_state="OK")

        refused = api.cancel_load(
            load["id"], {"reason_code": "NOT_MINE"}, make_freight_agent_headers(intruder["id"])
        )
        validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

        unchanged = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert unchanged["status"] == "POSTED"

        allowed = validate_success(
            api.cancel_load(
                load["id"], {"reason_code": "SHIPPER_CANCELLED"},
                make_freight_agent_headers(owner["id"]),
            ), 200
        )
        assert allowed["status"] == "CANCELLED"


class TestExistenceErrors:
    """Priority 3: existence and the declared input ordering."""

    def test_capacity_owner_get_with_unknown_id_returns_capacity_owner_not_found(self, api):
        """PRD §2.10: "3. Existence. Path identifiers are resolved left to right,
        and a body foreign key must exist; the left-to-right order within a body
        is the order the endpoint's declared input list gives. Refusal by
        resource type: `ERR_AGENT_NOT_FOUND`, `ERR_CAPACITY_OWNER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_TRIP_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`".

        Design: Corner/entities/capacity_owner_get_with_unknown_id_returns_capacity_owner_not_found
        """
        set_logical_clock()
        refused = api.get_capacity_owner(
            "00000000-0000-4000-8000-000000000000", TEST_USERS["network_admin_headers"]
        )
        validate_error(refused, ApiErrorId.ERR_CAPACITY_OWNER_NOT_FOUND, expected_status=404)
        assert refused.json()["data"]["error_id"] != "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"

    def test_compliance_document_get_with_unknown_id_returns_document_not_found(self, api):
        """PRD §2.10: "3. Existence. Path identifiers are resolved left to right,
        and a body foreign key must exist; the left-to-right order within a body
        is the order the endpoint's declared input list gives."

        Design: Corner/errors/compliance_document_get_with_unknown_id_returns_document_not_found
        """
        set_logical_clock()
        refused = api.get_compliance_document(
            "00000000-0000-4000-8000-000000000000", SAFETY_REVIEWER
        )
        validate_error(refused, ApiErrorId.ERR_COMPLIANCE_DOCUMENT_NOT_FOUND, expected_status=404)
        assert refused.json()["data"]["error_id"] != "ERR_CAPACITY_OWNER_NOT_FOUND"

    def test_escrow_transaction_get_with_unknown_id_returns_transaction_not_found(self, api):
        """PRD §2.10: "3. Existence. Path identifiers are resolved left to right,
        and a body foreign key must exist; the left-to-right order within a body
        is the order the endpoint's declared input list gives."

        Design: Corner/errors/escrow_transaction_get_with_unknown_id_returns_transaction_not_found
        """
        set_logical_clock()
        refused = api.get_escrow_transaction(
            "00000000-0000-4000-8000-000000000000", SETTLEMENT_OPERATOR
        )
        validate_error(refused, ApiErrorId.ERR_ESCROW_TRANSACTION_NOT_FOUND, expected_status=404)

        rows, meta = validate_paginated(
            api.list_escrow_transactions(SETTLEMENT_OPERATOR)
        )
        assert meta["total_count"] == 0, "the read created no ledger row"

    def test_trip_create_body_foreign_keys_checked_in_declared_input_order(self, api):
        """PRD §2.10: "3. Existence. Path identifiers are resolved left to right,
        and a body foreign key must exist; the left-to-right order within a body
        is the order the endpoint's declared input list gives. Refusal by
        resource type: `ERR_AGENT_NOT_FOUND`, `ERR_CAPACITY_OWNER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`".

        Design: Corner/entities/trip_create_body_foreign_keys_checked_in_declared_input_order
        """
        set_logical_clock()
        refused = api.create_trip(
            {
                "load_id": "00000000-0000-4000-8000-000000000001",
                "capacity_owner_id": "00000000-0000-4000-8000-000000000002",
                "equipment_id": "00000000-0000-4000-8000-000000000003",
                "departed_at": "2026-09-01T03:00:00Z",
                "deadline_at": "2026-09-02T03:00:00Z",
            },
            TEST_USERS["capacity_owner_headers"],
        )
        validate_error(refused, ApiErrorId.ERR_LOAD_NOT_FOUND, expected_status=404)
        assert refused.json()["data"]["error_id"] != "ERR_CAPACITY_OWNER_NOT_FOUND"

        rows, meta = validate_paginated(api.list_trips(TEST_USERS["network_admin_headers"]))
        assert meta["total_count"] == 0


class TestUniqueness:
    """Network-wide versus fleet- or agent-scoped uniqueness."""

    def test_duplicate_agent_code_is_rejected(self, api):
        """PRD §3.1: "An independent freight agency enters the network when a
        `NetworkAdministrator` enrolls it with an `agent_code` that must be
        unique across the whole network (a repeat is refused with
        `ERR_DUPLICATE_AGENT_CODE`)".

        Design: Corner/errors/duplicate_agent_code_is_rejected
        """
        set_logical_clock()
        first = enroll_agent(agent_code="AG-C33")

        refused = api.create_agent(
            {
                "agent_code": "AG-C33",
                "legal_name": "Impostor Freight Agency",
                "home_state": "OK",
                "commission_rate_pct": 0.30,
                "territory_codes": ["OK"],
            },
            TEST_USERS["network_admin_headers"],
        )
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_AGENT_CODE, expected_status=409)

        rows, meta = validate_paginated(api.list_agents(TEST_USERS["network_admin_headers"]))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["commission_rate_pct"] == 0.12

    def test_duplicate_owner_code_is_rejected(self, api):
        """PRD §3.2: "A business capacity owner enters when a
        `NetworkAdministrator` enrolls one with an `owner_code` unique across the
        network (a repeat is refused with `ERR_DUPLICATE_OWNER_CODE`)".

        Design: Corner/errors/duplicate_owner_code_is_rejected
        """
        set_logical_clock()
        first = enroll_capacity_owner(owner_code="BCO-C45")

        refused = api.create_capacity_owner(
            {
                "owner_code": "BCO-C45",
                "legal_name": "Impostor Carriers LLC",
                "home_terminal_city": "Waco",
                "revenue_split_pct": 0.55,
            },
            TEST_USERS["network_admin_headers"],
        )
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_OWNER_CODE, expected_status=409)

        rows, meta = validate_paginated(
            api.list_capacity_owners(TEST_USERS["network_admin_headers"])
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["revenue_split_pct"] == 0.68

    def test_duplicate_customer_ref_is_agent_scoped(self, api):
        """PRD §3.1: "Customer accounts themselves are registered under an agent
        through a payload carrying the `agent_id`, a `customer_ref` unique within
        that agent (a repeat is refused with `ERR_DUPLICATE_CUSTOMER_REF`)".

        Design: Corner/errors/duplicate_customer_ref_for_one_agent_is_rejected
        """
        set_logical_clock()
        agent = enroll_agent(territory_codes=["TX"])
        other = enroll_agent(territory_codes=["OK"], home_state="OK")

        register_customer(agent, customer_ref="CUST-C46")

        refused = api.create_customer_account(
            {
                "agent_id": agent["id"],
                "customer_ref": "CUST-C46",
                "shipper_name": "Repeat Reference Co",
                "first_booked_at": "2026-09-01T00:00:00Z",
            },
            make_freight_agent_headers(agent["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_CUSTOMER_REF, expected_status=409)

        accepted = validate_success(
            api.create_customer_account(
                {
                    "agent_id": other["id"],
                    "customer_ref": "CUST-C46",
                    "shipper_name": "Same Reference Other Agent",
                    "first_booked_at": "2026-09-01T00:00:00Z",
                },
                make_freight_agent_headers(other["id"]),
            ), 201
        )
        assert accepted["customer_ref"] == "CUST-C46"

        _a, meta_a = validate_paginated(
            api.list_agent_customer_accounts(agent["id"], TEST_USERS["network_admin_headers"])
        )
        _b, meta_b = validate_paginated(
            api.list_agent_customer_accounts(other["id"], TEST_USERS["network_admin_headers"])
        )
        assert meta_a["total_count"] == 1 and meta_b["total_count"] == 1

    def test_duplicate_unit_number_is_fleet_scoped(self, api):
        """PRD §3.2: "Fleet units are added by a `SafetyReviewer` or
        `NetworkAdministrator` with the owning `capacity_owner_id`, a
        `unit_number` unique within that owner (a repeat is refused with
        `ERR_DUPLICATE_UNIT_NUMBER`)".

        Design: Corner/errors/duplicate_unit_number_within_a_fleet_is_rejected
        """
        set_logical_clock()
        first = enroll_capacity_owner()
        other = enroll_capacity_owner()

        validate_success(
            api.create_equipment(
                {"capacity_owner_id": first["id"], "unit_number": "T-1904",
                 "equipment_type": "TRACTOR", "model_year": 2021,
                 "inspection_due_at": "2027-01-01T00:00:00Z"},
                SAFETY_REVIEWER,
            ), 201
        )

        refused = api.create_equipment(
            {"capacity_owner_id": first["id"], "unit_number": "T-1904",
             "equipment_type": "TRACTOR", "model_year": 2022,
             "inspection_due_at": "2027-01-01T00:00:00Z"},
            SAFETY_REVIEWER,
        )
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER, expected_status=409)

        accepted = validate_success(
            api.create_equipment(
                {"capacity_owner_id": other["id"], "unit_number": "T-1904",
                 "equipment_type": "TRACTOR", "model_year": 2022,
                 "inspection_due_at": "2027-01-01T00:00:00Z"},
                SAFETY_REVIEWER,
            ), 201
        )
        assert accepted["unit_number"] == "T-1904"

        _fa, meta_fa = validate_paginated(
            api.list_capacity_owner_equipment(first["id"], TEST_USERS["network_admin_headers"])
        )
        _fb, meta_fb = validate_paginated(
            api.list_capacity_owner_equipment(other["id"], TEST_USERS["network_admin_headers"])
        )
        assert meta_fa["total_count"] == 1 and meta_fb["total_count"] == 1


class TestLedgerInvariants:
    """The escrow floor and the compensating entry's single application."""

    def test_escrow_release_below_zero_is_rejected(self, api):
        """PRD §2.11: "The escrow account has a floor of zero: no mutation may
        drive `escrow_balance_cents` below zero, and a mutation that would do so
        is refused with `ERR_ESCROW_BALANCE_INSUFFICIENT`."

        Design: Corner/errors/escrow_release_below_zero_is_rejected
        """
        set_logical_clock()
        bco = enroll_capacity_owner()
        post_ledger_entry(bco, 250000)

        refused = api.create_escrow_transaction(
            {
                "capacity_owner_id": bco["id"],
                "transaction_type": "ESCROW_RELEASE",
                "amount_cents": 300000,
                "effective_at": "2026-09-01T01:00:00Z",
            },
            SETTLEMENT_OPERATOR,
        )
        validate_error(refused, ApiErrorId.ERR_ESCROW_BALANCE_INSUFFICIENT, expected_status=402)

        owner = get_success_data(api.get_capacity_owner(bco["id"], SETTLEMENT_OPERATOR))
        assert owner["escrow_balance_cents"] == 250000

        rows, meta = validate_paginated(
            api.list_capacity_owner_ledger(bco["id"], SETTLEMENT_OPERATOR)
        )
        assert meta["total_count"] == 1, "the rejected release created no row"

    def test_escrow_double_reverse_is_rejected(self, api):
        """PRD §2.11: "A reversal whose target is already `REVERSED`, or whose
        type is not the declared compensating type for its target, is refused
        with `ERR_ESCROW_ALREADY_MATCHED`."

        Design: Corner/errors/escrow_double_reverse_is_rejected
        """
        set_logical_clock()
        bco = enroll_capacity_owner()
        deposit = post_ledger_entry(bco, 250000)

        first = validate_success(
            api.reverse_escrow_transaction(
                deposit["id"], {"effective_at": "2026-09-01T01:00:00Z"}, SETTLEMENT_OPERATOR
            ), 200
        )
        assert first["status"] == "POSTED"
        deposit_after = get_success_data(api.get_escrow_transaction(deposit["id"], SETTLEMENT_OPERATOR))
        assert deposit_after["status"] == "REVERSED"

        second = api.reverse_escrow_transaction(
            deposit["id"], {"effective_at": "2026-09-01T02:00:00Z"}, SETTLEMENT_OPERATOR
        )
        validate_error(second, ApiErrorId.ERR_ESCROW_ALREADY_MATCHED, expected_status=402)

        owner = get_success_data(api.get_capacity_owner(bco["id"], SETTLEMENT_OPERATOR))
        assert owner["escrow_balance_cents"] == 0, "the refused second reversal left no residue"


class TestInputDecorationAndDefaults:
    """Client-supplied system fields and declared defaults."""

    def test_client_supplied_offer_status_and_rank_are_ignored(self, api):
        """PRD §2.6: "Derived fields are mutations like any other."
        PRD §3.4: "The offer lands `OPEN`, recomputes `selected_rank` for every
        open offer on the load, and re-derives the `owner_pay_ceiling_cents` and
        `expires_at` described in §2.4."

        Design: Corner/entities/load_offer_client_supplied_status_input_ignored
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        load = promote_load(agent, customer["customer_ref"])
        bco = enroll_capacity_owner()

        created = validate_success(
            api.create_load_offer(
                {
                    "load_id": load["id"],
                    "capacity_owner_id": bco["id"],
                    "offered_pay_cents": 126000,
                    "offered_at": "2026-09-01T01:00:00Z",
                    "expected_network_load_version": get_success_data(
                        api.get_load(load["id"], TEST_USERS["network_admin_headers"])
                    )["version"],
                    "status": "ACCEPTED",
                    "selected_rank": 99,
                    "version": 42,
                },
                make_freight_agent_headers(agent["id"]),
            ), 201
        )
        assert created["status"] == "OPEN"
        assert created["version"] == 1
        assert created["selected_rank"] == 1

    def test_capacity_owner_create_omitting_optionals_applies_declared_defaults(self, api):
        """PRD §3.2: "A business capacity owner enters when a
        `NetworkAdministrator` enrolls one with an `owner_code` unique across the
        network (a repeat is refused with `ERR_DUPLICATE_OWNER_CODE`), a
        `legal_name`, a `home_terminal_city`, a `revenue_split_pct` between zero
        and one inclusive, an optional `oa_enrolled` that defaults to false, and
        an optional `liability_insurance_deductible_cents` that defaults to
        250000."
        PRD §3.2: "The row lands in `PENDING_QUALIFICATION` with
        `escrow_balance_cents` and `maintenance_balance_cents` both zero and
        `safety_score` initialized to 100."

        Design: Corner/entities/capacity_owner_create_omitting_optionals_applies_declared_defaults
        """
        set_logical_clock()
        created = validate_success(
            api.create_capacity_owner(
                {
                    "owner_code": "BCO-COR-DEF",
                    "legal_name": "Default Case Trucking LLC",
                    "home_terminal_city": "Amarillo",
                    "revenue_split_pct": 0.68,
                },
                TEST_USERS["network_admin_headers"],
            ), 201
        )
        assert created["oa_enrolled"] is False
        assert created["liability_insurance_deductible_cents"] == 250000
        assert created["safety_score"] == 100
        assert created["escrow_balance_cents"] == 0
        assert created["maintenance_balance_cents"] == 0

    def test_equipment_model_year_lower_bound_is_inclusive(self, api):
        """PRD §3.2: "Fleet units are added by a `SafetyReviewer` or
        `NetworkAdministrator` with the owning `capacity_owner_id`, a
        `unit_number` unique within that owner (a repeat is refused with
        `ERR_DUPLICATE_UNIT_NUMBER`), an `equipment_type`, a `model_year` between
        1980 and 2030 inclusive, and an `inspection_due_at`."

        Design: Corner/entities/equipment_model_year_lower_bound_is_inclusive
        """
        set_logical_clock()
        bco = enroll_capacity_owner()

        refused = api.create_equipment(
            {"capacity_owner_id": bco["id"], "unit_number": "T-1903",
             "equipment_type": "TRACTOR", "model_year": 1979,
             "inspection_due_at": "2027-01-01T00:00:00Z"},
            SAFETY_REVIEWER,
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        accepted = validate_success(
            api.create_equipment(
                {"capacity_owner_id": bco["id"], "unit_number": "T-1903",
                 "equipment_type": "TRACTOR", "model_year": 1980,
                 "inspection_due_at": "2027-01-01T00:00:00Z"},
                SAFETY_REVIEWER,
            ), 201
        )
        assert accepted["model_year"] == 1980

        rows, meta = validate_paginated(
            api.list_capacity_owner_equipment(bco["id"], TEST_USERS["network_admin_headers"])
        )
        assert meta["total_count"] == 1

    def test_load_create_missing_linehaul_returns_invalid_request(self, api):
        """PRD §3.4: "a `linehaul_revenue_cents` greater than zero, an optional
        `fuel_surcharge_cents` defaulting to zero, an optional
        `accessorial_revenue_cents` defaulting to zero, and a
        `dispatched_miles` greater than zero."

        Design: Corner/entities/load_create_missing_linehaul_returns_invalid_request
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)

        refused = api.create_load(
            {
                "agent_id": agent["id"],
                "customer_ref": customer["customer_ref"],
                "origin_state": "TX",
                "destination_state": "OK",
                "dispatched_miles": 1240,
            },
            make_freight_agent_headers(agent["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        rows, meta = validate_paginated(
            api.list_loads(TEST_USERS["network_admin_headers"], params={"agent_id": agent["id"]})
        )
        assert meta["total_count"] == 0, "nothing was persisted"

    def test_new_load_status_input_ignored_on_create(self, api):
        """PRD §3.4: "The load lands in `POSTED` with a null awarded owner and a
        recomputed `board_required`."
        PRD §3.4: "Promotion is evaluated in the §2.10 order: the origin state
        must be inside the promoting agent's territory (else
        `ERR_TERRITORY_VIOLATION`)".

        Design: Corner/state_machines/new_load_status_input_ignored_on_create
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)

        created = validate_success(
            api.create_load(
                {
                    "agent_id": agent["id"],
                    "customer_ref": customer["customer_ref"],
                    "origin_state": "TX",
                    "destination_state": "OK",
                    "linehaul_revenue_cents": 180000,
                    "dispatched_miles": 1240,
                    "status": "SETTLED",
                },
                make_freight_agent_headers(agent["id"]),
            ), 201
        )
        assert created["status"] == "POSTED"
        assert created["awarded_capacity_owner_id"] is None
        assert created["board_required"] is True


class TestTerritoryAndCustomerBook:
    """The territory gate and the customer-ownership window."""

    def test_load_promote_outside_agent_territory_returns_territory_violation(self, api):
        """PRD §3.4: "the origin state must be inside the promoting agent's
        territory (else `ERR_TERRITORY_VIOLATION`)".
        PRD §2.5: "a load's `origin_state` must be a member of the promoting
        agent's list for that load to be promotable or awardable. A promotion or
        award outside the list is refused with `ERR_TERRITORY_VIOLATION`".

        Design: Corner/validations/load_promote_outside_agent_territory_returns_territory_violation
        """
        set_logical_clock()
        agent = enroll_agent(territory_codes=["TX", "OK"])
        customer = register_customer(agent)

        refused = api.create_load(
            {
                "agent_id": agent["id"],
                "customer_ref": customer["customer_ref"],
                "origin_state": "NV",
                "destination_state": "OK",
                "linehaul_revenue_cents": 180000,
                "dispatched_miles": 1240,
            },
            make_freight_agent_headers(agent["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_TERRITORY_VIOLATION, expected_status=422)

        accepted = validate_success(
            api.create_load(
                {
                    "agent_id": agent["id"],
                    "customer_ref": customer["customer_ref"],
                    "origin_state": "OK",
                    "destination_state": "TX",
                    "linehaul_revenue_cents": 180000,
                    "dispatched_miles": 1240,
                },
                make_freight_agent_headers(agent["id"]),
            ), 201
        )
        assert accepted["origin_state"] == "OK"

        rows, meta = validate_paginated(
            api.list_loads(TEST_USERS["network_admin_headers"], params={"agent_id": agent["id"]})
        )
        assert meta["total_count"] == 1

    def test_load_promote_inside_territory_succeeds(self, api):
        """PRD §3.4: "A `FreightAgent` promotes a load with a payload carrying
        the owning `agent_id`, the `customer_ref` the load books under — which
        must match a customer account's `customer_ref` for the same agent — an
        `origin_state` and a `destination_state`".
        PRD §3.4: "The load lands in `POSTED` with a null awarded owner and a
        recomputed `board_required`."

        Design: Corner/validations/load_promote_inside_territory_succeeds
        """
        set_logical_clock()
        agent = enroll_agent(territory_codes=["TX", "OK"])
        customer = register_customer(agent)

        created = validate_success(
            api.create_load(
                {
                    "agent_id": agent["id"],
                    "customer_ref": customer["customer_ref"],
                    "origin_state": "TX",
                    "destination_state": "OK",
                    "linehaul_revenue_cents": 180000,
                    "dispatched_miles": 1240,
                },
                make_freight_agent_headers(agent["id"]),
            ), 201
        )
        assert created["status"] == "POSTED"
        assert created["board_required"] is True

    def test_customer_ownership_window_drives_exclusivity_status(self, api):
        """PRD §2.5: "The derived `exclusivity_status` is `OWNED_EXCLUSIVE`
        strictly before `ownership_expires_at`, and `OPEN_SHARED` at or after it
        — except that when the account carries a `released_reason` its status is
        `RELEASED` regardless of the clock, and when the owning agent's
        `customer_ownership_days` is zero the account is `OPEN_SHARED` from
        creation."
        PRD §3.1: "The derived `ownership_expires_at` is the `first_booked_at`
        advanced by the owning agent's `customer_ownership_days`".

        Design: Corner/cross_cutting_complexity_layers/agent_active_customer_count_reconciles_after_termination
        """
        set_logical_clock("2026-09-01T00:00:00Z")
        agent = enroll_agent(customer_ownership_days=30)
        customer = register_customer(agent, first_booked_at="2026-09-01T00:00:00Z")

        owned = get_success_data(
            api.get_customer_account(customer["id"], TEST_USERS["network_admin_headers"])
        )
        assert owned["exclusivity_status"] == "OWNED_EXCLUSIVE"
        assert owned["ownership_expires_at"] == "2026-10-01T00:00:00Z"

        set_logical_clock("2026-10-01T00:00:00Z")
        shared = get_success_data(
            api.get_customer_account(customer["id"], TEST_USERS["network_admin_headers"])
        )
        assert shared["exclusivity_status"] == "OPEN_SHARED", (
            "the window closes at ownership_expires_at"
        )


class TestPaginationContract:
    """The envelope's pagination fields and filtering."""

    def test_settlement_list_paginates_and_reports_total_count(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` object of the envelope,
        alongside `api_request_id` and `api_request_timestamp`."
        PRD §2.3: "`limit` sets the maximum number of entries returned; when
        omitted it defaults to 10".

        Design: Corner/entities/settlement_list_paginates_and_reports_total_count
        """
        set_logical_clock()
        enroll_agent()

        rows, meta = validate_paginated(api.list_settlements(SETTLEMENT_OPERATOR))
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert meta["limit"] == 10 and meta["offset"] == 0

        filtered, meta_filtered = validate_paginated(
            api.list_settlements(
                SETTLEMENT_OPERATOR, params={"settlement_method": "FINAL", "limit": 10, "offset": 0}
            )
        )
        assert filtered == []
        assert meta_filtered["total_count"] == 0

    def test_loads_list_filters_by_status_and_origin_state(self, api):
        """PRD §4: "The network-wide loads list narrows by `agent_id`,
        `awarded_capacity_owner_id`, `status` or `origin_state`".
        PRD §2.3: "Unless a specific ordering is stated for an endpoint, list
        endpoints return resources sorted by creation timestamp ascending."

        Design: Corner/cross_cutting_complexity_layers/loads_list_filters_by_status_and_origin_state
        """
        set_logical_clock()
        agent = enroll_agent(territory_codes=["TX", "OK"])
        customer = register_customer(agent)
        promote_load(agent, customer["customer_ref"], origin_state="TX")
        promote_load(agent, customer["customer_ref"], origin_state="OK")

        posted, meta = validate_paginated(
            api.list_loads(SETTLEMENT_OPERATOR, params={"status": "POSTED"})
        )
        assert meta["total_count"] == 2 and len(posted) == 2
        assert meta["has_more"] is False

        ok_only, meta_ok = validate_paginated(
            api.list_loads(SETTLEMENT_OPERATOR, params={"origin_state": "OK"})
        )
        assert meta_ok["total_count"] == 1
        assert ok_only[0]["origin_state"] == "OK"

        paged, meta_paged = validate_paginated(
            api.list_loads(SETTLEMENT_OPERATOR, params={"status": "POSTED", "limit": 1, "offset": 1})
        )
        assert len(paged) == 1
        assert meta_paged["total_count"] == 2
        assert meta_paged["has_more"] is False

    def test_resources_are_sorted_by_creation_timestamp_ascending(self, api):
        """PRD §2.3: "Unless a specific ordering is stated for an endpoint, list
        endpoints return resources sorted by creation timestamp ascending."
        PRD §2.6: "`id` — a unique, server-minted identifier formatted as a UUID."

        Design: Corner/entities/settlement_list_paginates_and_reports_total_count
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        first = promote_load(agent, customer["customer_ref"])
        second = promote_load(agent, customer["customer_ref"])

        rows, _meta = validate_paginated(
            api.list_loads(SETTLEMENT_OPERATOR, params={"status": "POSTED"})
        )
        ids = [row["id"] for row in rows]
        assert ids == [first["id"], second["id"]]

    def test_ledger_list_narrows_by_transaction_type(self, api):
        """PRD §4: "A ledger list under one capacity owner narrows by
        `transaction_type`, `status`, `from_effective_at` and `to_effective_at`."
        PRD §2.11: "Every movement of a capacity owner's restricted money is a
        posted `EscrowTransaction`."

        Design: Corner/entities/escrow_ledger_has_no_update_or_delete_surface
        """
        set_logical_clock()
        bco = enroll_capacity_owner()
        post_ledger_entry(bco, 250000, "ESCROW_DEPOSIT")
        post_ledger_entry(bco, 5000, "MAINTENANCE_DEPOSIT", "2026-09-01T01:00:00Z")

        deposits, meta_d = validate_paginated(
            api.list_capacity_owner_ledger(
                bco["id"], SETTLEMENT_OPERATOR, params={"transaction_type": "ESCROW_DEPOSIT"}
            )
        )
        assert meta_d["total_count"] == 1
        assert deposits[0]["status"] == "POSTED"
        assert deposits[0]["amount_cents"] == 250000

        maintenance, meta_m = validate_paginated(
            api.list_capacity_owner_ledger(
                bco["id"], SETTLEMENT_OPERATOR, params={"transaction_type": "MAINTENANCE_DEPOSIT"}
            )
        )
        assert meta_m["total_count"] == 1
        assert maintenance[0]["amount_cents"] == 5000