"""Operator agreements: role boundaries, segregation of duties, tenure gate,
and the stand-suspension cascade from suspend and terminate."""
from test_helpers import (
    ApiErrorId,
    PA,
    RM,
    add_assignment,
    create_crew_member,
    create_draft_shift,
    create_loyalty_account,
    create_region,
    create_stand,
    list_items_of_order,
    make_crew_member_headers,
    make_loyalty_customer_headers,
    make_shift_lead_headers,
    make_stand_operator_headers,
    place_app_order,
    place_window_order,
    authorize_order,
    setup_open_stand_with_menu,
    setup_stand_with_agreement,
    stand_version,
    validate_error,
    validate_success,
)


class TestRbacRoleBoundaries:
    def test_crew_member_cannot_publish_shift(self, api):
        """PRD §2.1: "Each operation is restricted to a defined set of roles
        (enumerated per endpoint in §4); a request whose role is not permitted
        for that operation, or whose entity-backed ownership check fails, is
        rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/crew_member_cannot_publish_shift
        """
        ctx = setup_open_stand_with_menu()
        shift = create_draft_shift(
            ctx, starts_at="2026-09-02T07:00:00Z", ends_at="2026-09-02T09:00:00Z"
        )
        resp = api.publish_shift(
            shift["id"], make_crew_member_headers(ctx["taker"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        fetched = validate_success(
            api.get_shift(shift["id"], ctx["operator_headers"]), 200
        )
        assert fetched["status"] == "DRAFT"

    def test_loyalty_customer_cannot_manage_catalog_or_stand(self, api):
        """PRD §2.1: "When `X-User-Role` is `LoyaltyCustomer`, `X-User-ID` is the
        `id` of the acting `LoyaltyAccount`; ownership checks compare the order's
        `loyalty_account_id` to `X-User-ID`, so a customer may merge or authorize
        only their own orders."

        Design: Corner/rbac/loyalty_customer_cannot_manage_catalog_or_stand
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="App Amy")
        customer = make_loyalty_customer_headers(account["id"])

        throttle = api.throttle_stand(ctx["stand"]["id"], customer)
        validate_error(throttle, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        recipe = api.create_recipe(
            {
                "name": "Hacker Cola",
                "channel": "CORE",
                "base_price_cents": 100,
                "base_build_seconds": 10,
                "temperature_class": "ICED",
            },
            customer,
        )
        validate_error(recipe, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        points = api.adjust_points(
            account["id"], {"delta_points": 10000, "reason": "self-service"}, customer
        )
        validate_error(points, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        after = validate_success(
            api.get_loyalty_account(account["id"], ctx["operator_headers"]), 200
        )
        assert after["points"] == 0

    def test_stand_operator_cannot_nominate_or_terminate_agreements(self, api):
        """PRD §3.2: "A `RegionalManager` opens the process by nominating a crew
        member for a stand, supplying the `stand_id`, the `crew_member_id`, and
        a `revenue_share_pct` that must lie strictly between zero and one."
        PRD §3.2: "A `RegionalManager` may suspend an `ACTIVE` agreement
        (`ACTIVE → SUSPENDED`), reinstate a `SUSPENDED` one back to `ACTIVE`
        (again only while no other `ACTIVE` agreement exists for the stand), or
        terminate an agreement in either `ACTIVE` or `SUSPENDED` status, which
        is terminal."

        Design: Corner/rbac/stand_operator_cannot_nominate_or_terminate_agreements
        """
        ctx = setup_stand_with_agreement()
        op_headers = make_stand_operator_headers(ctx["op"]["id"])
        nominate = api.create_agreement(
            {
                "stand_id": ctx["stand"]["id"],
                "crew_member_id": ctx["op"]["id"],
                "revenue_share_pct": 0.30,
            },
            op_headers,
        )
        validate_error(nominate, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        terminate = api.terminate_agreement(ctx["agreement"]["id"], op_headers)
        validate_error(terminate, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


class TestAgreementSegregationOfDuties:
    def test_agreement_approval_enforces_segregation_of_duties(self, api):
        """PRD §3.2: "Approval belongs to a `PlatformAdmin`, and never to the
        nominator: if the approver's `X-User-ID` equals the agreement's
        `nominated_by`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`.
        Approval moves the agreement `NOMINATED → APPROVED` and stamps
        `approved_by`."

        Design: Corner/rbac/agreement_approval_enforces_segregation_of_duties
        """
        from prd_bench_local_runner.testing import build_user_headers

        ctx = setup_stand_with_agreement()
        agreement_id = ctx["agreement"]["id"]

        # The nominator was rm-1 (RegionalManager opaque id). Approving as a
        # PlatformAdmin *with the same identity* must fail the SoD check.
        same_identity = api.approve_agreement(
            agreement_id, build_user_headers("rm-1", "PlatformAdmin")
        )
        validate_error(same_identity, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        approved = validate_success(api.approve_agreement(agreement_id, PA), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "pa-1"

    def test_nominator_identity_recorded_on_agreement(self, api):
        """PRD §3.2: "The agreement is born `NOMINATED`, with `nominated_by`
        recording the nominating manager's `X-User-ID`."

        Design: Corner/rbac/agreement_approval_enforces_segregation_of_duties
        """
        ctx = setup_stand_with_agreement()
        assert ctx["agreement"]["status"] == "NOMINATED"
        assert ctx["agreement"]["nominated_by"] == "rm-1"


class TestOperatorTenure:
    def test_operator_nomination_requires_tenure(self, api):
        """PRD §3.2: "Two eligibility gates apply at nomination: the nominee's
        tenure — measured from `hired_on` against the current logical clock —
        must be at least 365 days (`ERR_TENURE_INSUFFICIENT`), and their
        `food_handler_cert_expires_on` must fall strictly after the current
        logical clock date (`ERR_CERTIFICATION_EXPIRED`)."

        Design: Corner/errors/operator_nomination_requires_tenure
        """
        from test_helpers import set_clock

        set_clock("2026-09-01T06:00:00Z")
        region = create_region()
        stand = create_stand(region["id"])
        validate_success(api.approve_stand(stand["id"], PA), 200)
        rookie = create_crew_member(
            stand["id"], full_name="Rookie Ray", hired_on="2026-01-01"
        )
        veteran = create_crew_member(
            stand["id"], full_name="Veteran Val", hired_on="2024-01-01"
        )
        rookie_nom = api.create_agreement(
            {
                "stand_id": stand["id"],
                "crew_member_id": rookie["id"],
                "revenue_share_pct": 0.30,
            },
            RM,
        )
        validate_error(rookie_nom, ApiErrorId.ERR_TENURE_INSUFFICIENT, 422)
        veteran_nom = validate_success(
            api.create_agreement(
                {
                    "stand_id": stand["id"],
                    "crew_member_id": veteran["id"],
                    "revenue_share_pct": 0.30,
                },
                RM,
            ),
            201,
        )
        assert veteran_nom["status"] == "NOMINATED"

    def test_veteran_nomination_succeeds_while_rookie_fails(self, api):
        """PRD §3.2: "the nominee's tenure — measured from `hired_on` against the
        current logical clock — must be at least 365 days (`ERR_TENURE_INSUFFICIENT`)"

        Design: Corner/errors/operator_nomination_requires_tenure
        """
        from test_helpers import set_clock

        set_clock("2026-09-01T06:00:00Z")
        region = create_region()
        stand = create_stand(region["id"])
        validate_success(api.approve_stand(stand["id"], PA), 200)
        rookie = create_crew_member(
            stand["id"], full_name="Rookie Ray", hired_on="2026-01-01"
        )
        resp = api.create_agreement(
            {
                "stand_id": stand["id"],
                "crew_member_id": rookie["id"],
                "revenue_share_pct": 0.30,
            },
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_TENURE_INSUFFICIENT, 422)


class TestTerminationCascade:
    def test_agreement_termination_cascades_stand_suspend_order_abandon_payment_void(
        self, api
    ):
        """PRD §3.2: "The critical machinery sits behind suspension and
        termination: when either action leaves **no** `ACTIVE` agreement for the
        stand, and the stand is `OPEN` or `THROTTLED`, the stand is suspended
        automatically, and the suspension drains the queue in a single cascade —
        every order at the stand whose `queue_status` is `QUEUED`, `MERGED`, or
        `AT_WINDOW` moves to `ABANDONED`, its lane slot (if any) is released and
        the stand's `lane_occupancy` recomputed, each such abandoned order whose
        payment is `AUTHORIZED` has that payment moved to `VOIDED`, and every
        open order item (`PENDING` or `BUILDING`) on those orders moves to
        `CANCELLED` with its parent order's totals recomputed."

        Design: Difficulty/transitive_cascade/agreement_termination_cascades_stand_suspend_order_abandon_payment_void
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="App Amy")
        order = place_app_order(ctx, ctx["recipe"]["id"], account["id"])
        payment = validate_success(
            api.authorize_payment(
                order["id"], {"card_token": "VISA-OK"},
                make_loyalty_customer_headers(account["id"]),
            ),
            201,
        )

        terminated = validate_success(
            api.terminate_agreement(ctx["agreement"]["id"], RM), 200
        )
        assert terminated["status"] == "TERMINATED"

        stand = validate_success(api.get_stand(ctx["stand"]["id"], RM), 200)
        assert stand["status"] == "SUSPENDED", (
            f"last ACTIVE agreement gone must suspend the stand, got {stand['status']}"
        )

        order_after = validate_success(api.get_order(order["id"], RM), 200)
        assert order_after["queue_status"] == "ABANDONED"

        payment_after = validate_success(api.get_payment(payment["id"], RM), 200)
        assert payment_after["status"] == "VOIDED"

        account_after = validate_success(
            api.get_loyalty_account(account["id"], ctx["operator_headers"]), 200
        )
        assert account_after["points"] == 0, (
            "a void is not a capture: no points may accrue"
        )

    def test_termination_suspends_stand_and_drains_merged_order_lane_slot(self, api):
        """PRD §3.2: "when either action leaves **no** `ACTIVE` agreement for the
        stand, and the stand is `OPEN` or `THROTTLED`, the stand is suspended
        automatically"

        Design: Difficulty/transitive_cascade/agreement_termination_cascades_stand_suspend_order_abandon_payment_void
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        payment = authorize_order(ctx, order["id"])
        validate_success(api.terminate_agreement(ctx["agreement"]["id"], RM), 200)

        stand = validate_success(api.get_stand(ctx["stand"]["id"], RM), 200)
        assert stand["status"] == "SUSPENDED"
        assert stand["lane_occupancy"].get("A", 0) == 0, "lane slot released"

        order_after = validate_success(api.get_order(order["id"], RM), 200)
        assert order_after["queue_status"] == "ABANDONED"
        assert order_after["payment_status"] == "VOIDED"

        payment_after = validate_success(api.get_payment(payment["id"], RM), 200)
        assert payment_after["status"] == "VOIDED"

        for item in list_items_of_order(ctx, order["id"]):
            assert item["build_status"] == "CANCELLED"


class TestSuspensionCascade:
    def test_cascade_from_suspend_drains_queue_and_voids_payments(self, api):
        """PRD §3.2: "The critical machinery sits behind suspension and
        termination: when either action leaves **no** `ACTIVE` agreement for the
        stand, and the stand is `OPEN` or `THROTTLED`, the stand is suspended
        automatically, and the suspension drains the queue in a single cascade —
        every order at the stand whose `queue_status` is `QUEUED`, `MERGED`, or
        `AT_WINDOW` moves to `ABANDONED`, its lane slot (if any) is released and
        the stand's `lane_occupancy` recomputed, each such abandoned order whose
        payment is `AUTHORIZED` has that payment moved to `VOIDED`, and every
        open order item (`PENDING` or `BUILDING`) on those orders moves to
        `CANCELLED` with its parent order's totals recomputed."

        Design: Corner/cross_cutting_complexity_layers/cascade_from_suspend_drains_queue_and_voids_payments
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        payment = authorize_order(ctx, order["id"])
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.throttle_stand(ctx["stand"]["id"], lead), 200)

        validate_success(api.suspend_agreement(ctx["agreement"]["id"], RM), 200)

        stand = validate_success(api.get_stand(ctx["stand"]["id"], RM), 200)
        assert stand["status"] == "SUSPENDED", (
            f"suspend must cascade from THROTTLED too, got {stand['status']}"
        )
        assert stand["lane_occupancy"].get("A", 0) == 0

        order_after = validate_success(api.get_order(order["id"], RM), 200)
        assert order_after["queue_status"] == "ABANDONED"
        assert order_after["payment_status"] == "VOIDED"

        payment_after = validate_success(api.get_payment(payment["id"], RM), 200)
        assert payment_after["status"] == "VOIDED"

    def test_suspended_stand_cascade_releases_lane_occupancy(self, api):
        """PRD §3.2: "its lane slot (if any) is released and the stand's
        `lane_occupancy` recomputed"

        Design: Corner/cross_cutting_complexity_layers/cascade_from_suspend_drains_queue_and_voids_payments
        """
        ctx = setup_open_stand_with_menu()
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="B")
        validate_success(api.suspend_agreement(ctx["agreement"]["id"], RM), 200)
        stand = validate_success(api.get_stand(ctx["stand"]["id"], RM), 200)
        assert stand["status"] == "SUSPENDED"
        assert stand["lane_occupancy"].get("A", 0) == 0
        assert stand["lane_occupancy"].get("B", 0) == 0
