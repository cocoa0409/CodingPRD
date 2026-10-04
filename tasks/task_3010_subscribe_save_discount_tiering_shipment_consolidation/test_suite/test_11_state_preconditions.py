"""State-machine preconditions and terminal-state lockdowns (PRD §3.4, §3.6,
§3.9, §3.10, §3.11)."""
from test_helpers import (
    ADMIN,
    SUPPORT,
    ApiErrorId,
    api_client,
    cancel_subscription_and_get_offer,
    create_customer,
    create_stocked_product,
    create_subscription,
    get_customer_by_id,
    get_plan,
    get_placement,
    get_subscription_by_id,
    get_success_data,
    list_plan_lines,
    make_customer_headers,
    report_damage_claim,
    set_clock,
    setup_customer_with_plan,
    setup_delivered_plan,
    setup_reported_claim,
    validate_error,
    validate_success,
)


class TestPauseRequiresActive:
    def test_pause_from_pending_cancel_returns_subscription_not_active(self):
        """PRD §3.4: "Pausing or resuming a subscription in any other status
        is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

        Design: Corner/state_machines/pause_from_pending_cancel_returns_subscription_not_active
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        sub = create_subscription(customer, product)
        cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        resp = api_client.pause_subscription(sub["id"], headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)
        assert get_subscription_by_id(sub["id"], customer)["status"] == \
            "PENDING_CANCEL"


class TestSecondLockRejected:
    def test_lock_a_locked_plan_returns_plan_not_open(self):
        """PRD §3.6: "the customer locks an `OPEN` plan — any other
        `plan_status` is rejected with `ERR_PLAN_NOT_OPEN`".

        Design: Corner/state_machines/lock_a_locked_plan_returns_plan_not_open
        """
        from test_helpers import setup_locked_plan
        customer, product, placement, subs, locked = setup_locked_plan()
        headers = make_customer_headers(customer["id"])
        resp = api_client.lock_plan(locked["id"], headers)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_OPEN)
        assert get_plan(locked["id"])["plan_status"] == "LOCKED"


class TestShipRequiresLocked:
    def test_ship_open_plan_returns_plan_not_locked(self):
        """PRD §3.9: "a `PlatformAdmin` ships a `LOCKED` plan — anything else
        is `ERR_PLAN_NOT_LOCKED`".

        Design: Corner/state_machines/ship_open_plan_returns_plan_not_locked
        """
        customer, product, placement, subs, plan = setup_customer_with_plan()
        resp = api_client.ship_plan(plan["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_LOCKED)
        placement_after = get_placement(placement["id"])
        assert placement_after["reserved_units"] == 0
        assert placement_after["shipped_units"] == 0


class TestClaimRequiresDelivered:
    def test_damage_claim_on_shipped_but_not_delivered_plan_rejected(self):
        """PRD §3.11: "the customer reports it on a `DELIVERED` plan — a claim
        against a plan in any other status is rejected with
        `ERR_PLAN_NOT_DELIVERED`".

        Design: Corner/state_machines/damage_claim_on_shipped_but_not_delivered_plan_rejected
        """
        from test_helpers import setup_shipped_plan
        customer, product, placement, subs, shipped = setup_shipped_plan()
        line = list_plan_lines(shipped, as_customer=customer)[0]
        resp = api_client.create_damage_claim(
            shipped["id"], {"damaged_line_ids": [line["id"]]},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DELIVERED)


class TestTerminalClaimLockdown:
    def test_review_of_completed_claim_returns_claim_not_reviewable(self):
        """PRD §3.11: "Review belongs to a `SupportAgent` and takes a
        `decision` of `APPROVE_REFUND`, `APPROVE_RESHIP`, or `REJECT`;
        reviewing a claim no longer in `REPORTED` status is rejected with
        `ERR_CLAIM_NOT_REVIEWABLE`."

        Design: Corner/state_machines/review_of_completed_claim_returns_claim_not_reviewable
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim())
        validate_success(api_client.review_damage_claim(
            claim["id"], {"decision": "APPROVE_REFUND"}, SUPPORT))
        resp = api_client.review_damage_claim(
            claim["id"], {"decision": "REJECT"}, SUPPORT)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE)
        claim_after = get_success_data(
            api_client.get_damage_claim(claim["id"], SUPPORT))
        assert claim_after["claim_status"] == "COMPLETED"


class TestDeclinedOfferTerminal:
    def test_accept_declined_offer_returns_offer_not_open(self):
        """PRD §3.4: "While the offer is `OFFERED`, the customer may accept or
        decline it; acting on an offer in any other status is rejected with
        `ERR_OFFER_NOT_OPEN`."
        PRD §3.4: "Declining moves the offer to `DECLINED` and the subscription
        to `CANCELLED`, which is terminal."

        Design: Corner/state_machines/accept_declined_offer_returns_offer_not_open
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        validate_success(api_client.decline_retention_offer(offer["id"], headers))
        resp = api_client.accept_retention_offer(offer["id"], headers)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_OPEN)
        assert get_subscription_by_id(sub["id"], customer)["status"] == "CANCELLED"
        assert get_customer_by_id(customer["id"])["credit_balance_cents"] == 0


class TestUnskipRequiresCustomerSkipped:
    def test_unskip_a_scheduled_line_returns_line_not_skippable(self):
        """PRD §3.10: "unskipping requires the line to be `SKIPPED` with
        `skip_reason` `CUSTOMER`".

        Design: Corner/state_machines/unskip_a_scheduled_line_returns_line_not_skippable
        """
        customer, product, placement, subs, plan = setup_customer_with_plan()
        line = list_plan_lines(plan, as_customer=customer)[0]
        headers = make_customer_headers(customer["id"])
        resp = api_client.unskip_line(plan["id"], line["id"], headers)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_SKIPPABLE)
        line_after = get_success_data(api_client.get_plan_line(
            line["id"], make_customer_headers(customer["id"])))
        assert line_after["line_status"] == "SCHEDULED"


class TestResolvedPlanLockdown:
    def test_resolved_plan_rejects_new_damage_claim(self):
        """PRD §3.11: "the customer reports it on a `DELIVERED` plan — a claim
        against a plan in any other status is rejected with
        `ERR_PLAN_NOT_DELIVERED`".
        PRD §3.9: "Resolution moves the plan to `RESOLVED`, which is
        terminal."

        Design: Corner/state_machines/resolved_plan_rejects_new_damage_claim
        """
        customer, product, placement, subs, plan = setup_delivered_plan()
        validate_success(api_client.resolve_plan(plan["id"], SUPPORT))
        line = list_plan_lines(plan, as_customer=customer)[0]
        resp = api_client.create_damage_claim(
            plan["id"], {"damaged_line_ids": [line["id"]]},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DELIVERED)
        assert get_plan(plan["id"])["plan_status"] == "RESOLVED"
