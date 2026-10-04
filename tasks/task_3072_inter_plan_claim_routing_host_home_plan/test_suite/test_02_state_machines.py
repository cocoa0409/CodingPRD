"""Claim state machine: pricing variants, precondition enforcement, denial lockdown."""

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    ApiClient,
    assert_claim,
    create_routed_claim,
    get_success_data,
    set_clock,
    setup_two_plan_world,
    validate_error,
    validate_success,
)
from test_helpers import factories as f


class TestClaimPricingVariants:
    def test_provisional_fallback_to_billed_amount_and_final_hard_failure(self, api: ApiClient):
        """PRD §3.5: "when no schedule window covers the service date — falls back to setting `provisional_allowed_cents` equal to the full `billed_amount_cents`."
        PRD §3.5: "Final pricing has no fallback: when no rate window covers the pricing date, the transition fails with `ERR_RATE_SCHEDULE_MISSING` (HTTP 422)."

        Design: Corner/state_machines/claim_pricing_provisional_fallback_to_billed_amount
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        assert claim["provisional_allowed_cents"] == 20000

        res = api.price_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_RATE_SCHEDULE_MISSING", 422)

        from test_helpers import create_rate_schedule

        create_rate_schedule(api, world["host"], negotiated_rate_cents=30000)
        priced = validate_success(api.price_claim(claim["id"], world["host_headers"]), 200)
        assert priced["status"] == "PRICED"
        assert priced["priced_allowed_cents"] == 20000

    def test_provisional_uses_matched_rate_below_billed(self, api: ApiClient):
        """PRD §3.5: "sets `provisional_allowed_cents` to the smaller of `billed_amount_cents` and that schedule's `negotiated_rate_cents`"

        Design: Corner/state_machines/claim_pricing_provisional_fallback_to_billed_amount
        """
        world = setup_two_plan_world(api, with_rate_schedule=True, with_fee_schedule=False)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"], billed_amount_cents=50000),
                world["host_headers"],
            )
        )
        assert claim["provisional_allowed_cents"] == 30000


class TestPayPrecondition:
    def test_pay_on_routed_claim_rejected_invalid_state(self, api: ApiClient):
        """PRD §3.6: "A `HostPlanOperator` of the host plan pays a `BENEFIT_DETERMINED` claim, moving it to `PAID`."
        PRD §2.8: "whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/pay_on_routed_claim_rejected_invalid_state
        """
        world = setup_two_plan_world(api)
        claim = create_routed_claim(api, world)

        res = api.pay_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_INVALID_STATE", 409)

        after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert after["status"] == "ROUTED"
        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 0

    def test_pay_on_received_claim_rejected_invalid_state(self, api: ApiClient):
        """PRD §3.6: "A `HostPlanOperator` of the host plan pays a `BENEFIT_DETERMINED` claim, moving it to `PAID`."
        PRD §2.8: "whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/pay_on_routed_claim_rejected_invalid_state
        """
        world = setup_two_plan_world(api)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        res = api.pay_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_INVALID_STATE", 409)
        after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert after["status"] == "RECEIVED"


class TestDenialTerminalLockdown:
    def test_deny_from_routed_is_terminal_and_blocks_pay(self, api: ApiClient):
        """PRD §3.6: "Denial moves the claim from `ROUTED` to the terminal `DENIED` state; a denied claim never generates a provider payment and never appears on any settlement line."

        Design: Corner/state_machines/deny_from_routed_is_terminal_and_blocks_pay
        """
        world = setup_two_plan_world(api)
        claim = create_routed_claim(api, world)
        denied = validate_success(api.deny_claim(claim["id"], world["home_headers"]), 200)
        assert denied["status"] == "DENIED"

        res = api.pay_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_INVALID_STATE", 409)

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 0
        assert host_after["fees_receivable_balance_cents"] == 0

    def test_deny_terminal_blocks_further_transitions(self, api: ApiClient):
        """PRD §3.6: "Denial moves the claim from `ROUTED` to the terminal `DENIED` state; a denied claim never generates a provider payment and never appears on any settlement line."

        Design: Corner/state_machines/deny_from_routed_is_terminal_and_blocks_pay
        """
        world = setup_two_plan_world(api)
        claim = create_routed_claim(api, world)
        validate_success(api.deny_claim(claim["id"], world["home_headers"]), 200)

        res_price = api.price_claim(claim["id"], world["host_headers"])
        validate_error(res_price, "ERR_INVALID_STATE", 409)
        res_route = api.route_claim(claim["id"], world["host_headers"])
        validate_error(res_route, "ERR_INVALID_STATE", 409)

        final = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert final["status"] == "DENIED"


class TestRevokeCascade:
    def test_revoked_plan_cascades_controlled_accounts_to_terminated(self, api: ApiClient):
        """PRD §3.1: "Revocation has a sweeping cascade: every national account controlled by the revoked plan that is currently `ACTIVE` or `SUSPENDED` automatically transitions to `TERMINATED`."

        Design: Corner/state_machines/revoked_plan_cascades_controlled_accounts_to_terminated
        """
        set_clock(api)
        from test_helpers import create_licensed_plan

        home = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA"])
        account = get_success_data(
            api.create_national_account(
                f.national_account_payload(home["id"]),
                ASSOCIATION_ADMIN_HEADERS,
            )
        )
        get_success_data(api.activate_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS))

        revoked = validate_success(api.revoke_license(home["id"], ASSOCIATION_ADMIN_HEADERS), 200)
        assert revoked["brand_license_status"] == "REVOKED"

        account_after = get_success_data(api.get_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS))
        assert account_after["status"] == "TERMINATED"

    def test_revoke_cascades_suspended_account_to_terminated(self, api: ApiClient):
        """PRD §3.1: "Revocation has a sweeping cascade: every national account controlled by the revoked plan that is currently `ACTIVE` or `SUSPENDED` automatically transitions to `TERMINATED`."

        Design: Corner/state_machines/revoked_plan_cascades_controlled_accounts_to_terminated
        """
        set_clock(api)
        from test_helpers import create_licensed_plan

        home = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA"])
        account = get_success_data(
            api.create_national_account(
                f.national_account_payload(home["id"]),
                ASSOCIATION_ADMIN_HEADERS,
            )
        )
        get_success_data(api.activate_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS))
        get_success_data(api.suspend_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS))

        validate_success(api.revoke_license(home["id"], ASSOCIATION_ADMIN_HEADERS), 200)
        account_after = get_success_data(api.get_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS))
        assert account_after["status"] == "TERMINATED"


class TestAdjustmentRejectRevert:
    def test_adjustment_reject_reverts_claim_to_paid_without_balance_change(self, api: ApiClient):
        """PRD §3.7: "rejection reverts the parent claim from `ADJUSTMENT_PENDING` back to `PAID` with no balance change whatsoever."

        Design: Corner/state_machines/adjustment_reject_reverts_claim_to_paid_without_balance_change
        """
        from test_helpers import setup_paid_claim_world

        world = setup_paid_claim_world(api)
        claim = world["claim"]
        adjustment = get_success_data(
            api.create_adjustment(
                claim["id"],
                f.adjustment_payload(claim["version"], reason="disputed", delta_allowed_cents=-5000),
                world["host_headers"],
            )
        )
        rejected = validate_success(api.reject_adjustment(adjustment["id"], world["home_headers"]), 200)
        assert rejected["status"] == "REJECTED"

        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["status"] == "PAID"
        assert claim_after["current_allowed_cents"] == 20000

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 20000

    def test_reject_from_validated_also_reverts_without_balance_change(self, api: ApiClient):
        """PRD §3.7: "the home plan may reject an adjustment that is still in `INITIATED` or `VALIDATED` status, moving it to `REJECTED`; rejection reverts the parent claim from `ADJUSTMENT_PENDING` back to `PAID` with no balance change whatsoever."

        Design: Corner/state_machines/adjustment_reject_reverts_claim_to_paid_without_balance_change
        """
        from test_helpers import setup_paid_claim_world

        world = setup_paid_claim_world(api)
        claim = world["claim"]
        adjustment = get_success_data(
            api.create_adjustment(
                claim["id"],
                f.adjustment_payload(claim["version"], reason="disputed", delta_allowed_cents=-5000),
                world["host_headers"],
            )
        )
        get_success_data(api.validate_adjustment(adjustment["id"], world["host_headers"]))
        rejected = validate_success(api.reject_adjustment(adjustment["id"], world["home_headers"]), 200)
        assert rejected["status"] == "REJECTED"

        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["status"] == "PAID"
        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 20000


class TestEligibilityInquiryAnswer:
    def test_eligibility_inquiry_answered_with_member_status(self, api: ApiClient):
        """PRD §3.2: "On a successful answer, the inquiry's `answer_eligibility_status` is populated with the member's current `eligibility_status` (either `ACTIVE` or `TERMINATED`) and the inquiry moves from `ROUTED` to `ANSWERED`."

        Design: Corner/state_machines/eligibility_inquiry_answered_with_member_status
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        inquiry = get_success_data(
            api.create_eligibility_inquiry(
                f.eligibility_inquiry_payload(world["host"]["id"], world["home"]["id"], member_number="M1"),
                world["host_headers"],
            )
        )
        answered = validate_success(api.answer_eligibility_inquiry(inquiry["id"], world["home_headers"]), 200)
        assert answered["status"] == "ANSWERED"
        assert answered["answer_eligibility_status"] == "ACTIVE"

        res = api.answer_eligibility_inquiry(inquiry["id"], world["home_headers"])
        validate_error(res, "ERR_INVALID_STATE", 409)

    def test_eligibility_inquiry_reject_leaves_answer_null(self, api: ApiClient):
        """PRD §3.2: "Alternatively, the home plan may reject the inquiry outright at any time while it is `ROUTED`, with no answer recorded — `answer_eligibility_status` remains `null`."

        Design: Corner/state_machines/eligibility_inquiry_answered_with_member_status
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        inquiry = get_success_data(
            api.create_eligibility_inquiry(
                f.eligibility_inquiry_payload(world["host"]["id"], world["home"]["id"], member_number="M1"),
                world["host_headers"],
            )
        )
        rejected = validate_success(api.reject_eligibility_inquiry(inquiry["id"], world["home_headers"]), 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["answer_eligibility_status"] is None
