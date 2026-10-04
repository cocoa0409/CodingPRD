"""Depth tests: clearinghouse rejection conservation and volume-tier boundary."""

from test_helpers import (
    ApiClient,
)
from test_helpers.fixtures import (
    create_edit_rule,
    create_usage_invoice,
    finalize_invoice,
    forward_claim,
    get_provider,
    list_claims,
    set_clock,
    setup_claims_pipeline,
    submit_claim,
)


class TestClaimRejectionConservation:
    def test_rejected_claim_carries_clearinghouse_origin(self, api: ApiClient):
        """PRD §3.4: "If `edit_failures` contains at least one entry with
        severity `ERROR`, the claim transitions to `REJECTED_CLEARINGHOUSE`:
        the system writes a structured `rejection_payload` whose `origin` is
        `CLEARINGHOUSE`, carrying the offending `rule_codes` and a `message`".

        Design: Difficulty/compensating_invariant/claim_rejection_conserves_provider_submission_count
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Invariant Provider",
                "tax_identification_number": "343434343",
                "national_provider_identifier": "1343434340",
            },
            payer_code="PAYIV",
        )
        create_edit_rule(
            api,
            world.payer_id,
            rule_code="DX_REQUIRED",
            applies_to="CLAIM_INTAKE",
            severity="ERROR",
            expression="diagnosis_codes.nonempty",
            effective_from="2026-01-01T00:00:00Z",
        )

        bad = submit_claim(
            api,
            world,
            patient_control_number="PCN-BAD",
            idempotency_key="IDEM-BAD",
            diagnosis_codes=[],
        )
        assert bad["acceptance_status"] == "REJECTED_CLEARINGHOUSE"
        assert bad["rejection_payload"]["origin"] == "CLEARINGHOUSE"
        assert "DX_REQUIRED" in bad["rejection_payload"]["rule_codes"]

    def test_total_submissions_conserved_across_pass_and_fail(self, api: ApiClient):
        """PRD §3.4: "With zero `ERROR` entries the claim becomes `ACCEPTED`."
        and "`REJECTED_CLEARINGHOUSE` is terminal, never reaches the payer, and
        never enters adjudication". A passing claim and a failing claim are
        both persisted — the provider's submission count is the sum of the
        accepted and rejected rows.

        Design: Difficulty/compensating_invariant/claim_rejection_conserves_provider_submission_count
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Invariant2 Provider",
                "tax_identification_number": "343434344",
                "national_provider_identifier": "1343434357",
            },
            payer_code="PAYI2",
        )
        create_edit_rule(
            api,
            world.payer_id,
            rule_code="DX_REQUIRED",
            applies_to="CLAIM_INTAKE",
            severity="ERROR",
            expression="diagnosis_codes.nonempty",
            effective_from="2026-01-01T00:00:00Z",
        )

        ok = submit_claim(
            api, world, patient_control_number="PCN-OK", idempotency_key="IDEM-OK"
        )
        bad = submit_claim(
            api,
            world,
            patient_control_number="PCN-BAD",
            idempotency_key="IDEM-BAD",
            diagnosis_codes=[],
        )
        assert ok["acceptance_status"] == "ACCEPTED"
        assert bad["acceptance_status"] == "REJECTED_CLEARINGHOUSE"

        claims = list_claims(api, world.provider_id)
        assert len(claims) == 2, "both submissions must be persisted"
        accepted = [c for c in claims if c["acceptance_status"] == "ACCEPTED"]
        rejected = [c for c in claims if c["acceptance_status"] == "REJECTED_CLEARINGHOUSE"]
        assert len(accepted) + len(rejected) == len(claims) == 2


class TestVolumeTierBoundary:
    def test_no_history_finalizes_to_tier_1(self, api: ApiClient):
        """PRD §3.8: "at least 100000 trailing units earns `TIER_3`, at least
        10000 earns `TIER_2`, and anything below earns `TIER_1`. The floors are
        inclusive: a trailing sum of exactly 10000 yields `TIER_2`."

        Design: Difficulty/boundary_precision_check/volume_tier_floor_inclusive_boundary
        """
        world = setup_claims_pipeline(
            api,
            clock="2026-06-01T00:00:00Z",
            provider_overrides={
                "legal_name": "Boundary Provider",
                "tax_identification_number": "777777777",
                "national_provider_identifier": "1777777776",
            },
            payer_code="PAYBD",
        )
        invoice = create_usage_invoice(api, world.provider_id, period="2026-09")
        set_clock(api, "2026-10-01T00:00:00Z")
        finalized = finalize_invoice(api, invoice)
        assert finalized["status"] == "FINALIZED"

        provider = get_provider(api, world.provider_id)
        assert provider["volume_tier_code"] == "TIER_1", (
            f"zero trailing units must keep TIER_1, got {provider['volume_tier_code']}"
        )

    def test_below_floor_volume_remains_tier_1(self, api: ApiClient):
        """PRD §3.8: "at least 100000 trailing units earns `TIER_3`, at least
        10000 earns `TIER_2`, and anything below earns `TIER_1`."

        Design: Difficulty/boundary_precision_check/volume_tier_floor_inclusive_boundary
        """
        world = setup_claims_pipeline(
            api,
            clock="2026-09-01T00:00:00Z",
            provider_overrides={
                "legal_name": "Below Floor Provider",
                "tax_identification_number": "777777778",
                "national_provider_identifier": "1777777784",
            },
            payer_code="PAYB2",
        )
        # A single forwarded claim: trailing billable volume 1, far below the
        # inclusive 10000 floor.
        claim = submit_claim(
            api, world, patient_control_number="PCN-BF1", idempotency_key="IDEM-BF1"
        )
        forward_claim(api, claim)

        invoice = create_usage_invoice(api, world.provider_id, period="2026-09")
        set_clock(api, "2026-10-01T00:00:00Z")
        finalize_invoice(api, invoice)

        provider = get_provider(api, world.provider_id)
        assert provider["volume_tier_code"] == "TIER_1"
