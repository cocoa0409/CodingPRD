"""Breadth tests: remittance balance math, connectivity posture aggregation,
and the provider account-balance derivation."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_outage,
    create_pricing_tier,
    create_remittance,
    create_usage_invoice,
    finalize_invoice,
    forward_claim,
    get_payer,
    get_provider,
    set_clock,
    setup_claims_pipeline,
    setup_remittance_world,
    submit_claim,
)
from test_helpers.test_users import CLEARINGHOUSE_OPS_HEADERS


class TestRemittanceBalance:
    def test_imbalanced_amounts_refused_with_remittance_imbalance(self, api: ApiClient):
        """PRD §3.5: "the arithmetic balances — `paid_amount_cents` plus
        `adjustment_amount_cents` plus `patient_responsibility_cents` equals
        the claim's `total_charge_cents` exactly. A balance failure is rejected
        with `ERR_REMITTANCE_IMBALANCE` (HTTP 422)".

        Design: Corner/calculations/remittance_post_refused_when_amounts_imbalanced
        """
        world, claim = setup_remittance_world(
            api,
            claim_total_cents=10000,
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYIM",
        )
        # 9000 + 500 + 0 = 9500 != 10000
        remittance = create_remittance(
            api,
            world,
            claim["id"],
            check_number="CHK-IM1",
            paid_amount_cents=9000,
            adjustment_amount_cents=500,
            patient_responsibility_cents=0,
            denial_reason_codes=[],
        )

        resp = api.post_remittance(remittance["id"], CLEARINGHOUSE_OPS_HEADERS)
        validate_error(resp, ApiErrorId.REMITTANCE_IMBALANCE)

        claim_now = get_success_data(api.get_claim(claim["id"], CLEARINGHOUSE_OPS_HEADERS))
        assert claim_now["adjudication_status"] == "PENDING"

    def test_zero_paid_with_empty_denial_codes_refused(self, api: ApiClient):
        """PRD §3.5: "A balance failure is rejected with
        `ERR_REMITTANCE_IMBALANCE` (HTTP 422), as is the degenerate case of a
        zero `paid_amount_cents` accompanied by an empty `denial_reason_codes`
        — with nothing paid and no denial reasons, neither a paid nor a denied
        outcome is expressible."

        Design: Corner/calculations/remittance_post_paid_zero_with_empty_denial_codes_refused
        """
        world, claim = setup_remittance_world(
            api,
            claim_total_cents=10000,
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYZP",
        )
        # Balanced arithmetically (0 + 10000 + 0 == 10000) but paid == 0 with
        # no denial reasons.
        remittance = create_remittance(
            api,
            world,
            claim["id"],
            check_number="CHK-ZP1",
            paid_amount_cents=0,
            adjustment_amount_cents=10000,
            patient_responsibility_cents=0,
            denial_reason_codes=[],
        )

        resp = api.post_remittance(remittance["id"], CLEARINGHOUSE_OPS_HEADERS)
        validate_error(resp, ApiErrorId.REMITTANCE_IMBALANCE)


class TestConnectivityPosture:
    def test_payer_status_is_worst_case_across_transaction_types(self, api: ApiClient):
        """PRD §2.10: "For a given payer and transaction type, the posture is
        `OFFLINE` if any `ACTIVE` outage with severity `FULL` lists that
        transaction type in `affects_transaction_types`; otherwise `DEGRADED`
        if any `ACTIVE` outage with severity `PARTIAL` lists it; otherwise
        `ONLINE`. The payer-level `connectivity_status` is the worst posture
        across the three transaction types, where `OFFLINE` outranks
        `DEGRADED` outranks `ONLINE`."

        Design: Corner/calculations/connectivity_posture_worst_case_across_transaction_types
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        world_payer = get_success_data(
            api.create_payer(
                {
                    "payer_id_code": "PAYCP",
                    "display_name": "Posture Payer",
                    "claims_lead_time_days": 5,
                    "remittance_lead_time_days": 5,
                    "eligibility_lead_time_seconds": 60,
                    "pricing_model": "PROVIDER_FUNDED",
                },
                CLEARINGHOUSE_OPS_HEADERS,
            )
        )

        partial = create_outage(
            api, world_payer["id"], severity="PARTIAL", affects_transaction_types=["CLAIMS_837"]
        )
        full = create_outage(
            api, world_payer["id"], severity="FULL", affects_transaction_types=["ELIGIBILITY_270"]
        )

        payer = get_payer(api, world_payer["id"])
        assert payer["connectivity_status"] == "OFFLINE", (
            "a FULL outage on any transaction type dominates the payer-level posture"
        )

        validate_success(api.resolve_outage(full["id"], CLEARINGHOUSE_OPS_HEADERS))
        payer = get_payer(api, world_payer["id"])
        assert payer["connectivity_status"] == "DEGRADED", (
            "with the FULL outage resolved, the remaining PARTIAL outage degrades the payer"
        )

        validate_success(api.resolve_outage(partial["id"], CLEARINGHOUSE_OPS_HEADERS))
        payer = get_payer(api, world_payer["id"])
        assert payer["connectivity_status"] == "ONLINE"


class TestAccountBalance:
    def test_balance_reflects_finalize_then_payment(self, api: ApiClient):
        """PRD §3.8: "The provider's `account_balance_cents` is a derived
        figure with a precise definition: the sum of `amount_due_cents` over
        the provider's `FINALIZED` invoices minus the sum over its `PAID`
        invoices". PRD §3.8: "success moves the invoice to `PAID` and subtracts
        that amount from the provider's balance."

        Design: Corner/endpoints/computed_read_provider_account_balance_reflects_invoice_state
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Balance Provider",
                "tax_identification_number": "111111112",
                "national_provider_identifier": "1111111120",
            },
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYBL",
        )
        create_pricing_tier(api, world.payer_id, applies_to="CLAIM", volume_floor=1, rate_cents=10)

        claim = submit_claim(
            api, world, patient_control_number="PCN-BL1", idempotency_key="IDEM-BL1"
        )
        forward_claim(api, claim)
        invoice = create_usage_invoice(api, world.provider_id, period="2026-09")

        set_clock(api, "2026-10-01T00:00:00Z")
        finalized = finalize_invoice(api, invoice)
        # 1 claim unit x 10 cents, provider-funded: amount due 10.
        assert finalized["amount_due_cents"] == 10

        provider = get_provider(api, world.provider_id)
        assert provider["account_balance_cents"] == 10, (
            f"finalize adds amount_due to the balance, got {provider['account_balance_cents']}"
        )

        paid = validate_success(
            api.record_payment(
                invoice["id"], {"payment_amount_cents": 10}, CLEARINGHOUSE_OPS_HEADERS
            )
        )
        assert paid["status"] == "PAID"

        provider = get_provider(api, world.provider_id)
        assert provider["account_balance_cents"] == 0, (
            f"record-payment subtracts amount_due from the balance, got {provider['account_balance_cents']}"
        )


class TestForwardFromState:
    def test_forward_on_terminal_claim_returns_invalid_state(self, api: ApiClient):
        """PRD §3.4: "Forwarding moves an `ACCEPTED` claim to `FORWARDED`." —
        no transition out of a terminal state exists. PRD §2.7: "Target state
        compatibility — the addressed resource must be in a state from which
        the requested transition is defined, else `ERR_INVALID_STATE`".

        Design: Corner/endpoints/forward_action_endpoint_blocked_when_claim_not_accepted
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "FromState Provider",
                "tax_identification_number": "767676767",
                "national_provider_identifier": "1767676764",
            },
            payer_code="PAYFS",
        )
        from test_helpers.fixtures import create_edit_rule

        create_edit_rule(
            api,
            world.payer_id,
            rule_code="DX_REQUIRED",
            severity="ERROR",
            expression="diagnosis_codes.nonempty",
            effective_from="2026-01-01T00:00:00Z",
        )
        claim = submit_claim(
            api,
            world,
            patient_control_number="PCN-FS1",
            idempotency_key="IDEM-FS1",
            diagnosis_codes=[],
        )
        assert claim["acceptance_status"] == "REJECTED_CLEARINGHOUSE"

        resp = api.forward_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, CLEARINGHOUSE_OPS_HEADERS
        )
        validate_error(resp, ApiErrorId.INVALID_STATE)

        claim_now = get_success_data(api.get_claim(claim["id"], CLEARINGHOUSE_OPS_HEADERS))
        assert claim_now["acceptance_status"] == "REJECTED_CLEARINGHOUSE"
