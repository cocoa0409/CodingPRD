"""Difficulty rules: cross_entity_state_dependency, resource_temporal_overlap,
compensating_invariant."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_member,
    create_product,
    make_licensee_manager_headers,
    schedule_inspection,
    set_clock,
    setup_operating_store,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_assortment_item,
    create_approved_distributor,
    create_campaign,
    create_employee,
    create_supply_order,
    drive_order_to_disputed,
    setup_cert_pending_store,
)
from test_helpers.factories import create_certification_payload
from test_helpers.test_users import make_inspector_headers


class TestOrderSubmitRequiresStoreOperating:
    def _setup_cert_pending_order(self):
        bundle = setup_cert_pending_store()
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        product = create_product(unit_cost_cents=500, case_pack_units=1)
        add_assortment_item(store_id, lic_id, product["id"], par_level=50)
        distributor = create_approved_distributor()
        order = create_supply_order(
            store_id, lic_id, distributor["id"],
            lines=[{"product_item_id": product["id"], "quantity": 10}])
        return bundle, order

    def test_submit_rejected_while_store_cert_pending(self):
        """PRD §3.5: "It requires lines (an empty submission is
        `ERR_EMPTY_ORDER`), requires the store to be `OPERATING` (else
        `ERR_STORE_NOT_OPERATING`), requires the distributor's `approved` flag
        (else `ERR_DISTRIBUTOR_NOT_APPROVED`), and requires the total to fit
        within the per-order budget ceiling of 20000000 cents (else
        `ERR_ORDER_BUDGET_EXCEEDED`)."

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_store_operating
        """
        bundle, order = self._setup_cert_pending_order()
        resp = api_client.submit_supply_order(
            order["id"], make_licensee_manager_headers(bundle["licensee_id"]))
        validate_error(resp, ApiErrorId.ERR_STORE_NOT_OPERATING.value)
        order = validate_success(api_client.get_supply_order(order["id"], ADMIN))
        assert order["status"] == "DRAFT"

    def test_order_creation_allowed_before_operations(self):
        """PRD §3.5: "A **SupplyOrder** is created by the licensee against a
        `distributor_id`, in any store state short of `DELICENSED` — creation
        itself is not gated on operations; only submission is."

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_store_operating
        """
        bundle, order = self._setup_cert_pending_order()
        assert order["status"] == "DRAFT"
        assert order["store_id"] == bundle["store"]["id"]
        store = validate_success(api_client.get_store(bundle["store"]["id"], ADMIN))
        assert store["operating_status"] == "CERT_PENDING"


class TestBeginOperationsRequiresCertifiedStaff:
    def _setup(self):
        """Store in CERT_PENDING; one barista CERTIFIED, the other ENROLLED."""
        from test_helpers.fixtures import create_active_agreement, create_store
        set_clock()
        base = create_active_agreement()
        lic_id = base["licensee_id"]
        lic_headers = make_licensee_manager_headers(lic_id)
        store = create_store(base["agreement"]["id"], lic_id)
        emp1 = create_employee(lic_id, role_tag="BARISTA")
        emp2 = create_employee(lic_id, role_tag="BARISTA")
        cert1 = validate_success(api_client.create_certification(
            emp1["id"], create_certification_payload(), lic_headers),
            expected_status=201)
        validate_success(api_client.record_certification_exam(
            cert1["id"], {"exam_score": 90, "proctor_anomaly": False},
            make_inspector_headers("insp-P")))
        validate_success(api_client.audit_verify_certification(
            cert1["id"], make_inspector_headers("insp-Q")))
        # emp2 enrolled but never examined
        validate_success(api_client.create_certification(
            emp2["id"], create_certification_payload(), lic_headers),
            expected_status=201)
        validate_success(api_client.request_store_certification(store["id"], lic_headers))
        return base, store

    def test_one_certified_barista_fails_staffing_floor(self):
        """PRD §3.3: "First, a staffing floor: at least 2 employees of the
        agreement's licensee, each `active`, each with `role_tag` `BARISTA`,
        each holding a certification in `CERTIFIED` status — fewer means
        `ERR_INSUFFICIENT_CERTIFIED_STAFF`."

        Design: Difficulty/cross_entity_state_dependency/begin_operations_requires_certified_staff
        """
        base, store = self._setup()
        resp = api_client.begin_store_operations(
            store["id"], make_licensee_manager_headers(base["licensee_id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CERTIFIED_STAFF.value)
        store = validate_success(api_client.get_store(store["id"], ADMIN))
        assert store["operating_status"] == "CERT_PENDING"

    def test_second_certification_unblocks_begin_operations(self):
        """PRD §3.3: "First, a staffing floor: at least 2 employees of the
        agreement's licensee, each `active`, each with `role_tag` `BARISTA`,
        each holding a certification in `CERTIFIED` status — fewer means
        `ERR_INSUFFICIENT_CERTIFIED_STAFF`."

        Design: Difficulty/cross_entity_state_dependency/begin_operations_requires_certified_staff
        """
        base, store = self._setup()
        lic_id = base["licensee_id"]
        lic_headers = make_licensee_manager_headers(lic_id)
        resp = api_client.begin_store_operations(store["id"], lic_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CERTIFIED_STAFF.value)
        # certify the second barista, then begin-operations succeeds
        from test_helpers import validate_paginated
        from test_helpers.fixtures import certify_employee
        employees, _meta = validate_paginated(
            api_client.list_employees(lic_headers, params={"licensee_id": lic_id}))
        enrolled_emp = employees[1]
        certify_employee(lic_id, enrolled_emp["id"])
        opened = validate_success(api_client.begin_store_operations(store["id"], lic_headers))
        assert opened["operating_status"] == "OPERATING"


class TestInspectorHalfOpenAdjacencyAllowed:
    def test_adjacent_allowed_and_strict_overlap_rejected(self):
        """PRD §3.8: "Inspector load: the acting inspector must hold no other
        `SCHEDULED` inspection overlapping this one under half-open semantics —
        an existing inspection conflicts when it starts before the new one ends
        and the new one starts before it ends, which deliberately permits two
        inspections to touch, one ending exactly as the other begins; a true
        overlap is `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_adjacency_allowed
        """
        set_clock()
        bundle = setup_operating_store()
        store_id = bundle["store"]["id"]
        insp = make_inspector_headers("insp-Z")
        first = schedule_inspection(
            store_id, inspector="insp-Z",
            start="2026-09-03T09:00:00Z", end="2026-09-03T10:00:00Z")
        assert first["status"] == "SCHEDULED"
        adjacent = validate_success(api_client.create_inspection(
            store_id,
            {"scheduled_start_utc": "2026-09-03T10:00:00Z",
             "scheduled_end_utc": "2026-09-03T11:00:00Z"},
            insp), expected_status=201)
        assert adjacent["status"] == "SCHEDULED"
        resp = api_client.create_inspection(
            store_id,
            {"scheduled_start_utc": "2026-09-03T09:30:00Z",
             "scheduled_end_utc": "2026-09-03T10:30:00Z"},
            insp)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT.value)

    def test_other_inspector_unaffected_by_conflict(self):
        """PRD §3.8: "Inspector load: the acting inspector must hold no other
        `SCHEDULED` inspection overlapping this one under half-open semantics —
        an existing inspection conflicts when it starts before the new one ends
        and the new one starts before it ends, which deliberately permits two
        inspections to touch, one ending exactly as the other begins; a true
        overlap is `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_adjacency_allowed
        """
        set_clock()
        bundle = setup_operating_store()
        store_id = bundle["store"]["id"]
        schedule_inspection(
            store_id, inspector="insp-Z",
            start="2026-09-03T09:00:00Z", end="2026-09-03T10:00:00Z")
        # Same window for a DIFFERENT inspector is fine.
        other = validate_success(api_client.create_inspection(
            store_id,
            {"scheduled_start_utc": "2026-09-03T09:00:00Z",
             "scheduled_end_utc": "2026-09-03T10:00:00Z"},
            make_inspector_headers("insp-Y")), expected_status=201)
        assert other["status"] == "SCHEDULED"
        # The same window for the SAME inspector conflicts.
        resp = api_client.create_inspection(
            store_id,
            {"scheduled_start_utc": "2026-09-03T09:00:00Z",
             "scheduled_end_utc": "2026-09-03T10:00:00Z"},
            make_inspector_headers("insp-Z"))
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT.value)


class TestPromotionClosedIntervalBoundaryConflicts:
    def test_shared_boundary_conflicts_next_day_allowed(self):
        """PRD §3.9: "Two campaigns in `PLANNED` or `ACTIVE` status on the same
        store may not overlap — the windows are closed intervals, so even
        sharing a single boundary date conflicts, and the newcomer is
        `ERR_CAMPAIGN_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/promotion_closed_interval_boundary_conflicts
        """
        set_clock()
        bundle = setup_operating_store()
        store_id = bundle["store"]["id"]
        create_campaign(store_id, name="A",
                        start_date="2026-10-01", end_date="2026-10-10")
        resp = api_client.create_promotion_campaign(
            store_id,
            {"name": "B", "start_date": "2026-10-10", "end_date": "2026-10-20",
             "discount_pct": 10, "floor_price_cents": 100},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT.value)
        created = validate_success(api_client.create_promotion_campaign(
            store_id,
            {"name": "C", "start_date": "2026-10-11", "end_date": "2026-10-20",
             "discount_pct": 10, "floor_price_cents": 100},
            ADMIN), expected_status=201)
        assert created["status"] == "PLANNED"

    def test_strictly_overlapping_window_conflicts(self):
        """PRD §3.9: "Two campaigns in `PLANNED` or `ACTIVE` status on the same
        store may not overlap — the windows are closed intervals, so even
        sharing a single boundary date conflicts, and the newcomer is
        `ERR_CAMPAIGN_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/promotion_closed_interval_boundary_conflicts
        """
        set_clock()
        bundle = setup_operating_store()
        store_id = bundle["store"]["id"]
        create_campaign(store_id, name="A",
                        start_date="2026-10-01", end_date="2026-10-10")
        resp = api_client.create_promotion_campaign(
            store_id,
            {"name": "B", "start_date": "2026-10-05", "end_date": "2026-10-20",
             "discount_pct": 10, "floor_price_cents": 100},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT.value)


class TestDisputeCreditConservesOrderSpend:
    def _setup(self):
        set_clock()
        bundle = setup_operating_store()
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        product = create_product(unit_cost_cents=500, case_pack_units=1)
        add_assortment_item(store_id, lic_id, product["id"], par_level=50)
        distributor = create_approved_distributor()
        order = create_supply_order(
            store_id, lic_id, distributor["id"],
            lines=[{"product_item_id": product["id"], "quantity": 10}])
        order = drive_order_to_disputed(
            order, lic_id,
            [{"product_item_id": product["id"], "quantity_received": 6}])
        return bundle, distributor, order

    def test_over_shortage_credit_rejected_then_exact_shortage_closes(self):
        """PRD §3.5: "Resolution belongs to the distributor, who grants a
        `credit_cents` bounded on both sides: at least 0 and at most the
        shortage, defined as `total_cost_cents` minus `received_value_cents`;
        anything outside that band is `ERR_DISPUTE_CREDIT_EXCEEDS_SHORTAGE`."

        Design: Difficulty/compensating_invariant/dispute_credit_conserves_order_spend
        """
        bundle, distributor, order = self._setup()
        assert order["total_cost_cents"] == 5000
        assert order["received_value_cents"] == 3000
        assert order["status"] == "DISPUTED"
        agent = make_distributor_headers(distributor["id"])
        resp = api_client.resolve_supply_order_dispute(
            order["id"], {"credit_cents": 2001}, agent)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_CREDIT_EXCEEDS_SHORTAGE.value)
        still = validate_success(api_client.get_supply_order(order["id"], ADMIN))
        assert still["status"] == "DISPUTED"
        closed = validate_success(api_client.resolve_supply_order_dispute(
            order["id"], {"credit_cents": 2000}, agent))
        assert closed["status"] == "CLOSED"
        assert closed["credit_cents"] == 2000

    def test_closed_order_satisfies_spend_invariant(self):
        """PRD §3.5: "When the credit equals the shortage exactly, the
        invariant `total_cost_cents` equals `received_value_cents` plus
        `credit_cents` holds."

        Design: Difficulty/compensating_invariant/dispute_credit_conserves_order_spend
        """
        bundle, distributor, order = self._setup()
        agent = make_distributor_headers(distributor["id"])
        closed = validate_success(api_client.resolve_supply_order_dispute(
            order["id"], {"credit_cents": 2000}, agent))
        assert closed["total_cost_cents"] == (
            closed["received_value_cents"] + closed["credit_cents"])
        assert closed["total_cost_cents"] == 5000


def make_distributor_headers(distributor_id):
    from test_helpers.test_users import make_distributor_agent_headers
    return make_distributor_agent_headers(distributor_id)


class TestLoyaltyEarnRedeemConservesPointsBalance:
    def _setup(self):
        set_clock()
        bundle = setup_operating_store()
        member = create_member()
        return bundle, member

    def test_earn_then_redeem_returns_balance_to_zero(self):
        """PRD §3.9: "**LoyaltyMembers** register with a unique `email`
        (duplicates are `ERR_UNIQUENESS_CONFLICT`) and carry a `points_balance`
        flanked by `lifetime_earned` and `lifetime_redeemed`; the invariant
        `points_balance` equals `lifetime_earned` minus `lifetime_redeemed`
        holds after every event, with `ADJUST` credits feeding the earned side
        and `ADJUST` debits the redeemed side."

        Design: Difficulty/compensating_invariant/loyalty_earn_redeem_conserves_points_balance
        """
        bundle, member = self._setup()
        lic_headers = make_licensee_manager_headers(bundle["licensee_id"])
        earn = validate_success(api_client.create_loyalty_event(
            member["id"],
            {"event_type": "EARN", "store_format": "LICENSED",
             "store_id": bundle["store"]["id"], "purchase_cents": 10000},
            lic_headers), expected_status=201)
        assert earn["points"] == 50  # floor(10000/200) * 1
        redeem = validate_success(api_client.create_loyalty_event(
            member["id"],
            {"event_type": "REDEEM", "store_format": "LICENSED",
             "store_id": bundle["store"]["id"], "purchase_cents": 20000,
             "points": 50},
            lic_headers), expected_status=201)
        assert redeem["points"] == 50
        assert redeem["redemption_cents"] == 5000
        member = validate_success(api_client.get_loyalty_member(member["id"], ADMIN))
        assert member["points_balance"] == 0
        assert member["lifetime_earned"] == 50
        assert member["lifetime_redeemed"] == 50

    def test_licensed_earn_rate_is_half_company_rate(self):
        """PRD §3.9: "An `EARN` credits one point per whole 200 cents of
        purchase at a licensed store, but two points per whole 200 cents at a
        company-operated store — fractional remainders never earn."

        Design: Difficulty/compensating_invariant/loyalty_earn_redeem_conserves_points_balance
        """
        bundle, member = self._setup()
        lic_headers = make_licensee_manager_headers(bundle["licensee_id"])
        earn = validate_success(api_client.create_loyalty_event(
            member["id"],
            {"event_type": "EARN", "store_format": "LICENSED",
             "store_id": bundle["store"]["id"], "purchase_cents": 10000},
            lic_headers), expected_status=201)
        assert earn["points"] == 50
        member2 = create_member()
        earn2 = validate_success(api_client.create_loyalty_event(
            member2["id"],
            {"event_type": "EARN", "store_format": "COMPANY_OPERATED",
             "purchase_cents": 10000},
            ADMIN), expected_status=201)
        assert earn2["points"] == 100
