"""Depth tests: remittance posting lifecycle, parallel claim axes, and the
void cascade's conserved counters."""

from test_helpers import (
    ApiClient,
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    create_remittance,
    create_usage_invoice,
    get_claim,
    get_invoice,
    post_remittance,
    setup_remittance_world,
)
from test_helpers.test_users import CLEARINGHOUSE_OPS_HEADERS


class TestClaimParallelDimensions:
    def test_acceptance_axis_unchanged_by_remittance_posting(self, api: ApiClient):
        """PRD §3.4: "`acceptance_status` tracks the routing journey
        (`RECEIVED` → `VALIDATING` → `ACCEPTED` → `FORWARDED` →
        `ACKNOWLEDGED_BY_PAYER`, with the two rejection terminals);
        `adjudication_status` tracks the financial outcome (`NONE` → `PENDING`
        → `PAID` | `DENIED` | `PARTIAL`) and continues to evolve after
        acceptance has settled, driven by remittance posting".

        Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_acceptance_and_adjudication_evolve_independently
        """
        world, claim = setup_remittance_world(
            api,
            claim_total_cents=20000,
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYPP",
        )
        remittance = create_remittance(
            api,
            world,
            claim["id"],
            check_number="CHK-001",
            paid_amount_cents=20000,
            adjustment_amount_cents=0,
            patient_responsibility_cents=0,
            denial_reason_codes=[],
        )
        posted = post_remittance(api, remittance["id"])
        assert posted["status"] == "POSTED"

        claim_now = get_claim(api, claim["id"])
        assert claim_now["acceptance_status"] == "ACKNOWLEDGED_BY_PAYER", (
            "acceptance axis must not move when a remittance posts"
        )

    def test_adjudication_axis_moves_to_paid_on_posting(self, api: ApiClient):
        """PRD §3.5: "It classifies the outcome and moves the claim's
        `adjudication_status` accordingly: ... `PAID` when `paid_amount_cents`
        equals the claim's `total_charge_cents` and both
        `adjustment_amount_cents` and `patient_responsibility_cents` are zero".

        Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_acceptance_and_adjudication_evolve_independently
        """
        world, claim = setup_remittance_world(
            api,
            claim_total_cents=20000,
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYP2",
        )
        remittance = create_remittance(
            api,
            world,
            claim["id"],
            check_number="CHK-002",
            paid_amount_cents=20000,
            adjustment_amount_cents=0,
            patient_responsibility_cents=0,
            denial_reason_codes=[],
        )
        post_remittance(api, remittance["id"])

        claim_now = get_claim(api, claim["id"])
        assert claim_now["adjudication_status"] == "PAID", (
            f"adjudication axis must move to PAID, got {claim_now['adjudication_status']}"
        )


class TestRemittanceVoidCascade:
    def test_void_fails_ready_posting_file(self, api: ApiClient):
        """PRD §3.5: "Voiding moves the remittance to `VOIDED`, cascades any
        `READY` posting file to `FAILED`, returns the claim's
        `adjudication_status` to `PENDING`, and decrements the invoice's
        remittance unit count."

        Design: Difficulty/transitive_cascade/remittance_void_cascades_to_posting_file_and_claim
        """
        world, claim = setup_remittance_world(
            api,
            claim_total_cents=30000,
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYVD",
        )
        remittance = create_remittance(
            api,
            world,
            claim["id"],
            check_number="CHK-V1",
            paid_amount_cents=30000,
            adjustment_amount_cents=0,
            patient_responsibility_cents=0,
            denial_reason_codes=[],
        )
        post_remittance(api, remittance["id"])

        resp = api.list_posting_files(remittance["id"], CLEARINGHOUSE_OPS_HEADERS)
        files = get_success_data(resp)
        assert len(files) == 1, "posting must spawn exactly one posting file"
        posting_file = files[0]

        voided = validate_success(api.void_remittance(remittance["id"], CLEARINGHOUSE_OPS_HEADERS))
        assert voided["status"] == "VOIDED"

        file_now = get_success_data(api.get_posting_file(posting_file["id"], CLEARINGHOUSE_OPS_HEADERS))
        assert file_now["status"] == "FAILED", (
            f"void must cascade the READY posting file to FAILED, got {file_now['status']}"
        )

    def test_void_returns_claim_adjudication_to_pending(self, api: ApiClient):
        """PRD §3.5: "Voiding moves the remittance to `VOIDED`, cascades any
        `READY` posting file to `FAILED`, returns the claim's
        `adjudication_status` to `PENDING`, and decrements the invoice's
        remittance unit count."

        Design: Difficulty/transitive_cascade/remittance_void_cascades_to_posting_file_and_claim
        """
        world, claim = setup_remittance_world(
            api,
            claim_total_cents=30000,
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYV2",
        )
        remittance = create_remittance(
            api,
            world,
            claim["id"],
            check_number="CHK-V2",
            paid_amount_cents=30000,
            adjustment_amount_cents=0,
            patient_responsibility_cents=0,
            denial_reason_codes=[],
        )
        post_remittance(api, remittance["id"])
        claim_after_post = get_claim(api, claim["id"])
        assert claim_after_post["adjudication_status"] == "PAID"

        validate_success(api.void_remittance(remittance["id"], CLEARINGHOUSE_OPS_HEADERS))

        claim_after_void = get_claim(api, claim["id"])
        assert claim_after_void["adjudication_status"] == "PENDING", (
            "void must return the adjudication axis to PENDING"
        )
        assert claim_after_void["acceptance_status"] == "ACKNOWLEDGED_BY_PAYER"


class TestRemittanceUnitsConservation:
    def test_void_decrements_invoice_remittance_units_to_zero(self, api: ApiClient):
        """PRD §3.5: "It increments the current period's remittance unit count
        for the provider's usage invoice." and "Voiding ... decrements the
        invoice's remittance unit count."

        Design: Difficulty/compensating_invariant/remittance_void_restores_billable_units_and_adjudication_pending
        """
        world, claim = setup_remittance_world(
            api,
            claim_total_cents=7000,
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYVI",
        )
        remittance = create_remittance(
            api,
            world,
            claim["id"],
            check_number="CHK-VI1",
            paid_amount_cents=7000,
            adjustment_amount_cents=0,
            patient_responsibility_cents=0,
            denial_reason_codes=[],
        )
        invoice = create_usage_invoice(api, world.provider_id, period="2026-09")
        post_remittance(api, remittance["id"])

        invoice_after_post = get_invoice(api, invoice["id"])
        assert invoice_after_post["remittance_units"] == 1, (
            f"posting must increment remittance_units to 1, got {invoice_after_post['remittance_units']}"
        )

        validate_success(api.void_remittance(remittance["id"], CLEARINGHOUSE_OPS_HEADERS))

        invoice_after_void = get_invoice(api, invoice["id"])
        assert invoice_after_void["remittance_units"] == 0, (
            f"void must decrement remittance_units back to 0, got {invoice_after_void['remittance_units']}"
        )

    def test_post_void_cycle_leaves_no_drift_in_adjudication(self, api: ApiClient):
        """PRD §3.5: "Voiding moves the remittance to `VOIDED`, cascades any
        `READY` posting file to `FAILED`, returns the claim's
        `adjudication_status` to `PENDING`, and decrements the invoice's
        remittance unit count." After a post+void cycle both the invoice
        counter and the claim's adjudication axis equal their pre-post values.

        Design: Difficulty/compensating_invariant/remittance_void_restores_billable_units_and_adjudication_pending
        """
        world, claim = setup_remittance_world(
            api,
            claim_total_cents=7000,
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYV3",
        )
        remittance = create_remittance(
            api,
            world,
            claim["id"],
            check_number="CHK-VI2",
            paid_amount_cents=7000,
            adjustment_amount_cents=0,
            patient_responsibility_cents=0,
            denial_reason_codes=[],
        )
        invoice = create_usage_invoice(api, world.provider_id, period="2026-09")

        post_remittance(api, remittance["id"])
        validate_success(api.void_remittance(remittance["id"], CLEARINGHOUSE_OPS_HEADERS))

        invoice_now = get_invoice(api, invoice["id"])
        claim_now = get_claim(api, claim["id"])
        assert invoice_now["remittance_units"] == 0
        assert claim_now["adjudication_status"] == "PENDING"
