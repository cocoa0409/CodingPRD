"""Depth tests: enrollment decision-round cycle and provider-suspend cascade."""

from test_helpers import (
    ApiClient,
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    get_enrollment,
    get_inquiry,
    setup_claims_pipeline,
    setup_world,
    submit_inquiry,
)
from test_helpers.test_users import (
    CLEARINGHOUSE_OPS_HEADERS,
)


class TestEnrollmentRejectionResubmitCycle:
    def test_reject_resubmit_cycle_increments_decision_round(self, api: ApiClient):
        """PRD §3.3: "A `ProviderAdmin` may resubmit a `REJECTED` enrollment —
        again requiring the provider to be `ACTIVE` — which moves it to
        `RE_SUBMITTED`, stamps a fresh `submitted_at`, increments
        `decision_round` by 1, recomputes `payer_decision_due_at` against the
        new submission instant, and increments `version`."

        Design: Difficulty/non_linear_state_machine/payer_enrollment_rejection_resubmit_cycle_increments_decision_round
        """
        world = setup_world(
            api,
            provider_overrides={
                "legal_name": "Cycle Provider",
                "tax_identification_number": "111111111",
                "national_provider_identifier": "1111111112",
            },
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
            },
            payer_code="PAYCC",
        )
        admin = world.admin_headers()
        payer_h = world.payer_headers()

        enrollment = get_success_data(
            api.create_enrollment(
                world.provider_id,
                {"payer_id": world.payer_id, "transaction_type": "CLAIMS_837"},
                admin,
            )
        )

        submitted = validate_success(
            api.submit_enrollment(world.provider_id, enrollment["id"], admin)
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["decision_round"] == 1

        resp = api.advance_enrollment_to_review(enrollment["id"], CLEARINGHOUSE_OPS_HEADERS)
        assert resp.status_code == 200, f"Setup failed: advance-to-review {resp.text}"
        current = get_enrollment(api, world, enrollment["id"])

        rejected = validate_success(
            api.record_payer_decision(
                enrollment["id"],
                {
                    "decision": "REJECT",
                    "expected_enrollment_version": current["version"],
                    "rejection_reason": "Missing W-9",
                },
                payer_h,
            )
        )
        assert rejected["status"] == "REJECTED"

        resubmitted = validate_success(
            api.resubmit_enrollment(world.provider_id, enrollment["id"], admin)
        )
        assert resubmitted["status"] == "RE_SUBMITTED"
        assert resubmitted["decision_round"] == 2, (
            f"decision_round must increment to 2 on resubmit, got {resubmitted['decision_round']}"
        )

    def test_cycle_completes_with_second_round_approval(self, api: ApiClient):
        """PRD §3.3: "From `RE_SUBMITTED` the same system handoff (gated on the
        payer not being `OFFLINE` for the transaction type) returns the
        enrollment to `PAYER_REVIEW`, and the decide cycle repeats". PRD §3.3:
        "Approval ... on success stamps `approved_at` and increments `version`."

        Design: Difficulty/non_linear_state_machine/payer_enrollment_rejection_resubmit_cycle_increments_decision_round
        """
        world = setup_world(
            api,
            provider_overrides={
                "legal_name": "Cycle2 Provider",
                "tax_identification_number": "111111113",
                "national_provider_identifier": "1111111138",
            },
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
            },
            payer_code="PAYC2",
        )
        admin = world.admin_headers()
        payer_h = world.payer_headers()

        enrollment = get_success_data(
            api.create_enrollment(
                world.provider_id,
                {"payer_id": world.payer_id, "transaction_type": "CLAIMS_837"},
                admin,
            )
        )
        validate_success(api.submit_enrollment(world.provider_id, enrollment["id"], admin))
        resp = api.advance_enrollment_to_review(enrollment["id"], CLEARINGHOUSE_OPS_HEADERS)
        assert resp.status_code == 200, f"Setup failed: advance-to-review {resp.text}"
        current = get_enrollment(api, world, enrollment["id"])
        validate_success(
            api.record_payer_decision(
                enrollment["id"],
                {
                    "decision": "REJECT",
                    "expected_enrollment_version": current["version"],
                    "rejection_reason": "Missing W-9",
                },
                payer_h,
            )
        )
        validate_success(api.resubmit_enrollment(world.provider_id, enrollment["id"], admin))

        # Second traversal of the cycle: RE_SUBMITTED -> PAYER_REVIEW -> APPROVED.
        resp = api.advance_enrollment_to_review(enrollment["id"], CLEARINGHOUSE_OPS_HEADERS)
        assert resp.status_code == 200, f"Setup failed: advance-to-review {resp.text}"
        current = get_enrollment(api, world, enrollment["id"])
        assert current["status"] == "PAYER_REVIEW"

        approved = validate_success(
            api.record_payer_decision(
                enrollment["id"],
                {"decision": "APPROVE", "expected_enrollment_version": current["version"]},
                payer_h,
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["decision_round"] == 2
        assert approved.get("approved_at"), "approved_at must be stamped on APPROVE"


class TestProviderSuspendCascade:
    def test_suspend_cancels_in_flight_enrollment(self, api: ApiClient):
        """PRD §3.1: "Suspension is aggressive: every enrollment of that
        provider sitting in `SUBMITTED` or `PAYER_REVIEW` is cancelled with
        `rejection_reason` set to `PROVIDER_SUSPENDED`"."

        Design: Difficulty/transitive_cascade/provider_suspend_cascades_through_enrollment_and_inquiry
        """
        world = setup_world(
            api,
            provider_overrides={
                "legal_name": "Cascade Provider",
                "tax_identification_number": "333333333",
                "national_provider_identifier": "1333333338",
            },
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 3600,
            },
            payer_code="PAYCS",
        )
        admin = world.admin_headers()

        # Enrollment advanced to PAYER_REVIEW but not yet decided.
        enrollment = get_success_data(
            api.create_enrollment(
                world.provider_id,
                {"payer_id": world.payer_id, "transaction_type": "CLAIMS_837"},
                admin,
            )
        )
        validate_success(api.submit_enrollment(world.provider_id, enrollment["id"], admin))
        resp = api.advance_enrollment_to_review(enrollment["id"], CLEARINGHOUSE_OPS_HEADERS)
        assert resp.status_code == 200, f"Setup failed: advance-to-review {resp.text}"

        suspended = validate_success(api.suspend_provider(world.provider_id, CLEARINGHOUSE_OPS_HEADERS))
        assert suspended["status"] == "SUSPENDED"

        after = get_enrollment(api, world, enrollment["id"])
        assert after["status"] == "CANCELLED", (
            f"in-flight enrollment must be cancelled by suspension, got {after['status']}"
        )
        assert after["rejection_reason"] == "PROVIDER_SUSPENDED"

    def test_suspend_times_out_pending_eligibility_inquiry(self, api: ApiClient):
        """PRD §3.1: "every `PENDING` eligibility inquiry belonging to the
        provider transitions to `TIMED_OUT`, and the provider's `version`
        increments."

        Design: Difficulty/transitive_cascade/provider_suspend_cascades_through_enrollment_and_inquiry
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Cascade2 Provider",
                "tax_identification_number": "333333334",
                "national_provider_identifier": "1333333346",
            },
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 3600,
            },
            payer_code="PAYC3",
            transaction_types=("ELIGIBILITY_270",),
        )
        inquiry = submit_inquiry(
            api, world, subscriber_id="MBR-C1", idempotency_key="IDEM-CA1"
        )
        assert inquiry["status"] == "PENDING"

        suspended = validate_success(api.suspend_provider(world.provider_id, CLEARINGHOUSE_OPS_HEADERS))
        assert suspended["status"] == "SUSPENDED"

        after = get_inquiry(api, inquiry["id"])
        assert after["status"] == "TIMED_OUT", (
            f"pending inquiry must time out on provider suspension, got {after['status']}"
        )
