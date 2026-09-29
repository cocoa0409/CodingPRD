"""Two violations present in one request body, resolved by the ordered ladder."""

from test_helpers import (
    ComplianceWorld,
    assert_equals,
    assert_fields,
    assert_null,
    assert_provider_counters,
    build_signing_ready_provider,
    expect_error,
    expect_list_total,
)
from test_helpers.api_errors import (
    ERR_CALL_DETAIL_MISMATCH,
    ERR_CUSTOMER_NOT_KYC_VERIFIED,
    ERR_NO_ACTIVE_CERTIFICATE,
    ERR_RESPONSE_WINDOW_CLOSED,
)
from test_helpers.constants import NUMBER_1, NUMBER_CALLED, NUMBER_CALLED_ALT
from test_helpers.factories import (
    call_attestation_payload,
    traceback_response_payload,
)


def _build_doubly_blocked_signing(world: ComplianceWorld):
    """A provider whose certificate is merely issued and whose only customer is
    still under KYC review: one signing body, two live violations."""
    provider = world.register_provider()
    world.accepted_plan(
        provider["id"],
        practices=["KYC_ONBOARDING", "TRACEBACK_COOPERATION", "CONTRACT_TERMS_PROHIBITION"],
    )
    certificate = world.issued_certificate(provider["id"])
    customer = world.onboard_customer(
        provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
    )
    world.kyc_submit(customer["id"])
    body = call_attestation_payload(
        provider["id"],
        customer["id"],
        NUMBER_1,
        NUMBER_CALLED,
        "2026-08-01T00:00:00Z",
    )
    return provider["id"], certificate["id"], customer["id"], body


class TestAttestationCertificateOutranksKyc:
    """The certificate-state gate reported ahead of the customer-posture gate."""

    def test_missing_active_certificate_masks_the_unverified_customer(self, world):
        """The state gate answers first: 409 rather than the 422 also owed.

        PRD: "Because the certificate-status check sits at step 11 and the posture check at step 12, a signing attempt against a provider that has no `ACTIVE` certificate reports `ERR_NO_ACTIVE_CERTIFICATE` (409) rather than `ERR_SIGNING_SUSPENDED`, even though the missing certificate is itself one of the reasons the posture is `SIGNING_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/attestation_certificate_state_outranks_kyc_safety_check
        """
        provider_id, _certificate_id, customer_id, body = _build_doubly_blocked_signing(
            world
        )

        expect_error(
            world.client.create_call_attestation(body, world.provider_admin(provider_id)),
            ERR_NO_ACTIVE_CERTIFICATE,
        )

        _items, _meta = expect_list_total(
            world.client.list_call_attestations(world.regulator, customer_id=customer_id),
            0,
        )

    def test_activating_the_certificate_exposes_the_masked_kyc_violation(self, world):
        """The identical body then reports the customer-posture refusal, 422.

        PRD: "The pairs are reconciled not by cascade but by refusal at the point of use — a call signed for a customer that is not `VERIFIED` is rejected with `ERR_CUSTOMER_NOT_KYC_VERIFIED` (422) no matter what `origination_state` says."

        Design: Difficulty/priority_pair_validation_conflict/attestation_certificate_state_outranks_kyc_safety_check
        """
        provider_id, certificate_id, customer_id, body = _build_doubly_blocked_signing(
            world
        )
        world.activate_certificate(certificate_id, provider_id)
        assert_provider_counters(
            world.read_provider(provider_id),
            active_certificate_id=certificate_id,
            auth_posture="FULL_ATTESTATION",
        )

        expect_error(
            world.client.create_call_attestation(body, world.provider_admin(provider_id)),
            ERR_CUSTOMER_NOT_KYC_VERIFIED,
        )

        assert_equals(world.read_customer(customer_id), "kyc_state", "UNDER_REVIEW")
        _items, _meta = expect_list_total(
            world.client.list_call_attestations(world.regulator, customer_id=customer_id),
            0,
        )


def _build_mismatched_response(world: ComplianceWorld):
    """A traceback whose only candidate attestation names a different called
    number, left unanswered until its hard cutoff has passed."""
    setup = build_signing_ready_provider(world)
    attestation = world.sign_call(
        setup.provider_id,
        setup.customer_id,
        NUMBER_1,
        NUMBER_CALLED_ALT,
        "2026-08-02T00:00:00Z",
    )
    world.set_clock("2026-08-05T00:00:00Z")
    traceback = world.open_traceback(
        setup.provider_id,
        calling_number=NUMBER_1,
        called_number=NUMBER_CALLED,
        origination_time="2026-08-02T00:00:00Z",
    )
    body = traceback_response_payload(setup.customer_id, attestation["id"])
    return setup, traceback, body


class TestTracebackWindowClosureOutranksMismatch:
    """The temporal gate reported ahead of the referential one."""

    def test_a_closed_window_masks_the_mismatched_call_detail(self, world):
        """Past the hard cutoff the answer is refused 409 and the request stands still.

        PRD: "If the current logical clock is strictly after `hard_cutoff_at`, the response is refused outright with `ERR_RESPONSE_WINDOW_CLOSED` (409) and the request keeps whatever state it was in — a provider that has let three days pass cannot buy its way back into compliance with a late filing."

        Design: Difficulty/priority_pair_validation_conflict/traceback_window_closure_outranks_call_detail_mismatch
        """
        setup, traceback, body = _build_mismatched_response(world)

        world.set_clock("2026-08-08T00:00:01Z")
        expect_error(
            world.client.respond_traceback_request(
                traceback["id"], body, world.officer_1
            ),
            ERR_RESPONSE_WINDOW_CLOSED,
        )

        stalled = world.read_traceback(traceback["id"])
        assert_equals(stalled, "state", "RECEIVED")
        assert_null(stalled, "responded_at")
        assert_provider_counters(
            world.read_provider(setup.provider_id), penalty_points=0
        )

    def test_rewinding_inside_the_window_exposes_the_masked_mismatch(self, world):
        """The identical body inside the window reports the call-detail refusal, 422.

        PRD: "The produced record must genuinely describe the traced call: its `provider_id` must equal the traceback's `provider_id`, its `customer_id` must equal the supplied `identified_customer_id`, its `calling_number` and `called_number` must equal the traceback's, and its `origination_time` must equal the traceback's `origination_time`."

        Design: Difficulty/priority_pair_validation_conflict/traceback_window_closure_outranks_call_detail_mismatch
        """
        setup, traceback, body = _build_mismatched_response(world)
        world.set_clock("2026-08-08T00:00:01Z")
        expect_error(
            world.client.respond_traceback_request(
                traceback["id"], body, world.officer_1
            ),
            ERR_RESPONSE_WINDOW_CLOSED,
        )

        world.set_clock("2026-08-06T00:00:00Z")
        expect_error(
            world.client.respond_traceback_request(
                traceback["id"], body, world.officer_1
            ),
            ERR_CALL_DETAIL_MISMATCH,
        )

        untouched = world.read_traceback(traceback["id"])
        assert_fields(untouched, state="RECEIVED", identified_customer_id=None)
        assert_null(untouched, "responded_at")
        assert_provider_counters(
            world.read_provider(setup.provider_id), penalty_points=0
        )
