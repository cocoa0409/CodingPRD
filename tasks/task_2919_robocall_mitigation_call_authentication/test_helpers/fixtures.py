"""Composite setup fixtures.

The harness restarts the service before every test, so each test begins with an
empty store and a logical clock at its startup default.  Everything a test
needs beyond that is built here.

Setup steps go through ``get_success_data`` so that a broken precondition is
reported as a setup failure rather than as a failed assertion, and every
ownership-gated call is issued with headers built from the identity that
actually owns the row.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import RmdApiClient
from .constants import CLOCK_DEFAULT, NUMBER_1, NUMBER_CALLED
from .test_users import (
    CO_1,
    CO_2,
    FRAUD_1,
    FRAUD_2,
    KYC_1,
    KYC_2,
    OFFICER_1,
    OFFICER_2,
    make_caller_headers,
    make_compliance_officer_headers,
    make_fraud_analyst_headers,
    make_kyc_analyst_headers,
    make_policy_admin_headers,
    make_provider_admin_headers,
    make_regulator_headers,
)
from .types import Entity


class ComplianceWorld:
    """A task-oriented facade over the API used to build test preconditions."""

    def __init__(self, client: RmdApiClient):
        self.client = client
        self.regulator = make_regulator_headers()
        self.policy_admin = make_policy_admin_headers()
        self.officer_1 = make_compliance_officer_headers(OFFICER_1)
        self.officer_2 = make_compliance_officer_headers(OFFICER_2)
        self.co_1 = make_compliance_officer_headers(CO_1)
        self.co_2 = make_compliance_officer_headers(CO_2)
        self.kyc_1 = make_kyc_analyst_headers(KYC_1)
        self.kyc_2 = make_kyc_analyst_headers(KYC_2)
        self.fraud_1 = make_fraud_analyst_headers(FRAUD_1)
        self.fraud_2 = make_fraud_analyst_headers(FRAUD_2)

    # --- identities --------------------------------------------------------

    def officer(self, user_id: str = OFFICER_1) -> Dict[str, str]:
        return make_compliance_officer_headers(user_id)

    def kyc(self, user_id: str = KYC_1) -> Dict[str, str]:
        return make_kyc_analyst_headers(user_id)

    def fraud(self, user_id: str = FRAUD_1) -> Dict[str, str]:
        return make_fraud_analyst_headers(user_id)

    def provider_admin(self, provider_id: str) -> Dict[str, str]:
        return make_provider_admin_headers(provider_id)

    def caller(self, customer_id: str) -> Dict[str, str]:
        return make_caller_headers(customer_id)

    # --- logical clock -----------------------------------------------------

    def set_clock(self, current_utc: str) -> Entity:
        return get_success_data(self.client.set_clock(current_utc, self.regulator))

    # --- providers ---------------------------------------------------------

    def register_provider(self, **kwargs: Any) -> Entity:
        return get_success_data(
            self.client.create_provider(f.provider_payload(**kwargs), self.regulator)
        )

    def read_provider(self, provider_id: str) -> Entity:
        return get_success_data(self.client.get_provider(provider_id, self.regulator))

    def provider_version(self, provider_id: str) -> int:
        return int(self.read_provider(provider_id)["version"])

    def run_sweep(self, provider_id: str) -> Entity:
        return get_success_data(self.client.run_sweep(provider_id, self.regulator))

    # --- certificates ------------------------------------------------------

    def request_certificate(self, provider_id: str, **kwargs: Any) -> Entity:
        return get_success_data(
            self.client.create_certificate(
                f.certificate_payload(provider_id, **kwargs), self.policy_admin
            )
        )

    def issue_certificate(self, certificate_id: str) -> Entity:
        return get_success_data(
            self.client.issue_certificate(certificate_id, self.policy_admin)
        )

    def activate_certificate(self, certificate_id: str, provider_id: str) -> Entity:
        return get_success_data(
            self.client.activate_certificate(
                certificate_id, self.provider_admin(provider_id)
            )
        )

    def issued_certificate(self, provider_id: str, **kwargs: Any) -> Entity:
        certificate = self.request_certificate(provider_id, **kwargs)
        return self.issue_certificate(certificate["id"])

    def active_certificate(self, provider_id: str, **kwargs: Any) -> Entity:
        certificate = self.issued_certificate(provider_id, **kwargs)
        return self.activate_certificate(certificate["id"], provider_id)

    def read_certificate(self, certificate_id: str) -> Entity:
        return get_success_data(
            self.client.get_certificate(certificate_id, self.regulator)
        )

    # --- mitigation plans --------------------------------------------------

    def draft_plan(
        self,
        provider_id: str,
        practices: Optional[List[str]] = None,
        officer_id: str = OFFICER_1,
        expected_provider_version: Optional[int] = None,
    ) -> Entity:
        version = (
            self.provider_version(provider_id)
            if expected_provider_version is None
            else expected_provider_version
        )
        payload = f.mitigation_plan_payload(
            provider_id, version, prevention_practices=practices
        )
        return get_success_data(
            self.client.create_mitigation_plan(payload, self.officer(officer_id))
        )

    def submit_plan(self, plan_id: str, officer_id: str = OFFICER_1) -> Entity:
        return get_success_data(
            self.client.submit_mitigation_plan(plan_id, self.officer(officer_id))
        )

    def decide_plan(
        self,
        plan_id: str,
        decision: str = "ACCEPT",
        deficiency_reasons: Optional[List[str]] = None,
    ) -> Entity:
        payload = f.plan_decision_payload(decision, deficiency_reasons)
        return get_success_data(
            self.client.decide_mitigation_plan(plan_id, payload, self.regulator)
        )

    def submitted_plan(
        self,
        provider_id: str,
        officer_id: str = OFFICER_1,
        practices: Optional[List[str]] = None,
    ) -> Entity:
        plan = self.draft_plan(provider_id, practices=practices, officer_id=officer_id)
        return self.submit_plan(plan["id"], officer_id)

    def accepted_plan(
        self,
        provider_id: str,
        officer_id: str = OFFICER_1,
        practices: Optional[List[str]] = None,
    ) -> Entity:
        plan = self.submitted_plan(provider_id, officer_id, practices)
        return self.decide_plan(plan["id"], "ACCEPT")

    def read_plan(self, plan_id: str) -> Entity:
        return get_success_data(
            self.client.get_mitigation_plan(plan_id, self.regulator)
        )

    # --- customers ---------------------------------------------------------

    def onboard_customer(self, provider_id: str, **kwargs: Any) -> Entity:
        return get_success_data(
            self.client.create_customer(
                f.customer_payload(provider_id, **kwargs),
                self.provider_admin(provider_id),
            )
        )

    def kyc_submit(self, customer_id: str, submitter_id: str = KYC_1) -> Entity:
        return get_success_data(
            self.client.kyc_submit(customer_id, self.kyc(submitter_id))
        )

    def kyc_decide(
        self, customer_id: str, decision: str = "VERIFY", decider_id: str = KYC_2
    ) -> Entity:
        return get_success_data(
            self.client.kyc_decision(
                customer_id, f.kyc_decision_payload(decision), self.kyc(decider_id)
            )
        )

    def kyc_verified(
        self, customer_id: str, submitter_id: str = KYC_1, decider_id: str = KYC_2
    ) -> Entity:
        self.kyc_submit(customer_id, submitter_id)
        return self.kyc_decide(customer_id, "VERIFY", decider_id)

    def origination_action(
        self,
        customer_id: str,
        provider_id: str,
        action: str,
        suspension_cause: Optional[str] = None,
        as_regulator: bool = False,
    ) -> Entity:
        headers = self.regulator if as_regulator else self.provider_admin(provider_id)
        payload = f.origination_action_payload(action, suspension_cause)
        return get_success_data(
            self.client.origination_action(customer_id, payload, headers)
        )

    def enable_origination(self, customer_id: str, provider_id: str) -> Entity:
        return self.origination_action(customer_id, provider_id, "ENABLE")

    def verified_enabled_customer(self, provider_id: str, **kwargs: Any) -> Entity:
        """A customer whose package is verified and whose origination is enabled."""
        customer = self.onboard_customer(provider_id, **kwargs)
        self.kyc_verified(customer["id"])
        return self.enable_origination(customer["id"], provider_id)

    def read_customer(self, customer_id: str) -> Entity:
        return get_success_data(self.client.get_customer(customer_id, self.regulator))

    # --- number assignments ------------------------------------------------

    def assign_number(
        self,
        provider_id: str,
        customer_id: str,
        telephone_number: str = NUMBER_1,
        **kwargs: Any,
    ) -> Entity:
        payload = f.number_assignment_payload(
            provider_id, customer_id, telephone_number, **kwargs
        )
        return get_success_data(
            self.client.create_number_assignment(
                payload, self.provider_admin(provider_id)
            )
        )

    def revoke_assignment(self, assignment_id: str, provider_id: str) -> Entity:
        return get_success_data(
            self.client.revoke_number_assignment(
                assignment_id, self.provider_admin(provider_id)
            )
        )

    def read_assignment(self, assignment_id: str) -> Entity:
        return get_success_data(
            self.client.get_number_assignment(assignment_id, self.regulator)
        )

    # --- call attestations -------------------------------------------------

    def sign_call(
        self,
        provider_id: str,
        customer_id: str,
        calling_number: str = NUMBER_1,
        called_number: str = NUMBER_CALLED,
        origination_time: str = CLOCK_DEFAULT,
        **kwargs: Any,
    ) -> Entity:
        payload = f.call_attestation_payload(
            provider_id,
            customer_id,
            calling_number,
            called_number,
            origination_time,
            **kwargs,
        )
        return get_success_data(
            self.client.create_call_attestation(
                payload, self.provider_admin(provider_id)
            )
        )

    def read_attestation(self, attestation_id: str) -> Entity:
        return get_success_data(
            self.client.get_call_attestation(attestation_id, self.regulator)
        )

    # --- traffic observations ----------------------------------------------

    def record_observation(
        self, provider_id: str, customer_id: str, **kwargs: Any
    ) -> Entity:
        payload = f.traffic_observation_payload(provider_id, customer_id, **kwargs)
        return get_success_data(
            self.client.create_traffic_observation(
                payload, self.provider_admin(provider_id)
            )
        )

    def read_observation(self, observation_id: str) -> Entity:
        return get_success_data(
            self.client.get_traffic_observation(observation_id, self.regulator)
        )

    # --- traceback requests ------------------------------------------------

    def open_traceback(self, provider_id: str, **kwargs: Any) -> Entity:
        payload = f.traceback_request_payload(provider_id, **kwargs)
        return get_success_data(
            self.client.create_traceback_request(payload, self.regulator)
        )

    def respond_traceback(
        self,
        traceback_id: str,
        identified_customer_id: str,
        produced_attestation_id: str,
        officer_id: str = OFFICER_1,
    ) -> Entity:
        payload = f.traceback_response_payload(
            identified_customer_id, produced_attestation_id
        )
        return get_success_data(
            self.client.respond_traceback_request(
                traceback_id, payload, self.officer(officer_id)
            )
        )

    def read_traceback(self, traceback_id: str) -> Entity:
        return get_success_data(
            self.client.get_traceback_request(traceback_id, self.regulator)
        )

    # --- illegal traffic notices -------------------------------------------

    def serve_notice(self, provider_id: str, **kwargs: Any) -> Entity:
        payload = f.illegal_traffic_notice_payload(provider_id, **kwargs)
        return get_success_data(
            self.client.create_illegal_traffic_notice(payload, self.regulator)
        )

    def investigate_notice(
        self, notice_id: str, customer_id: str, officer_id: str = OFFICER_1
    ) -> Entity:
        payload = f.notice_investigation_payload(customer_id)
        return get_success_data(
            self.client.investigate_notice(notice_id, payload, self.officer(officer_id))
        )

    def mitigate_notice(
        self, notice_id: str, mitigation_action: str, officer_id: str = OFFICER_1
    ) -> Entity:
        payload = f.notice_mitigation_payload(mitigation_action)
        return get_success_data(
            self.client.mitigate_notice(notice_id, payload, self.officer(officer_id))
        )

    def investigated_notice(
        self, provider_id: str, customer_id: str, officer_id: str = OFFICER_1, **kwargs: Any
    ) -> Entity:
        notice = self.serve_notice(provider_id, **kwargs)
        return self.investigate_notice(notice["id"], customer_id, officer_id)

    def read_notice(self, notice_id: str) -> Entity:
        return get_success_data(
            self.client.get_illegal_traffic_notice(notice_id, self.regulator)
        )

    # --- blocking events and disputes --------------------------------------

    def block_calls(
        self, provider_id: str, customer_id: str, analyst_id: str = FRAUD_1, **kwargs: Any
    ) -> Entity:
        payload = f.blocking_event_payload(provider_id, customer_id, **kwargs)
        return get_success_data(
            self.client.create_blocking_event(payload, self.fraud(analyst_id))
        )

    def read_blocking_event(self, event_id: str) -> Entity:
        return get_success_data(
            self.client.get_blocking_event(event_id, self.regulator)
        )

    def file_dispute(self, event_id: str, customer_id: str, **kwargs: Any) -> Entity:
        payload = f.blocking_dispute_payload(event_id, **kwargs)
        return get_success_data(
            self.client.create_blocking_dispute(payload, self.caller(customer_id))
        )

    def review_dispute(self, dispute_id: str, analyst_id: str = FRAUD_2) -> Entity:
        return get_success_data(
            self.client.review_blocking_dispute(dispute_id, self.fraud(analyst_id))
        )

    def resolve_dispute(
        self, dispute_id: str, outcome: str, analyst_id: str = FRAUD_2, **kwargs: Any
    ) -> Entity:
        payload = f.dispute_resolution_payload(outcome, **kwargs)
        return get_success_data(
            self.client.resolve_blocking_dispute(
                dispute_id, payload, self.fraud(analyst_id)
            )
        )

    def withdraw_dispute(self, dispute_id: str, customer_id: str) -> Entity:
        return get_success_data(
            self.client.withdraw_blocking_dispute(dispute_id, self.caller(customer_id))
        )

    def read_dispute(self, dispute_id: str) -> Entity:
        return get_success_data(
            self.client.get_blocking_dispute(dispute_id, self.regulator)
        )

    # --- enforcement actions -----------------------------------------------

    def assess_forfeiture(self, provider_id: str, **kwargs: Any) -> Entity:
        payload = f.enforcement_action_payload(provider_id, **kwargs)
        return get_success_data(
            self.client.create_enforcement_action(payload, self.regulator)
        )

    def contest_forfeiture(self, action_id: str, officer_id: str = OFFICER_1) -> Entity:
        return get_success_data(
            self.client.contest_enforcement_action(action_id, self.officer(officer_id))
        )

    def adjudicate_forfeiture(self, action_id: str, outcome: str) -> Entity:
        return get_success_data(
            self.client.adjudicate_enforcement_action(
                action_id, f.adjudication_payload(outcome), self.regulator
            )
        )

    def pay_forfeiture(
        self, action_id: str, provider_id: str, amount_cents: int
    ) -> Entity:
        return get_success_data(
            self.client.pay_enforcement_action(
                action_id,
                f.payment_payload(amount_cents),
                self.provider_admin(provider_id),
            )
        )

    def read_enforcement_action(self, action_id: str) -> Entity:
        return get_success_data(
            self.client.get_enforcement_action(action_id, self.regulator)
        )

    # --- effectiveness reports ---------------------------------------------

    def generate_report(
        self,
        provider_id: str,
        variant: str = "PROVISIONAL",
        officer_id: str = OFFICER_2,
        expected_provider_version: Optional[int] = None,
        **kwargs: Any,
    ) -> Entity:
        version = (
            self.provider_version(provider_id)
            if expected_provider_version is None
            else expected_provider_version
        )
        payload = f.effectiveness_report_payload(
            provider_id, version, variant=variant, **kwargs
        )
        return get_success_data(
            self.client.create_effectiveness_report(payload, self.officer(officer_id))
        )

    def certify_report(self, report_id: str, officer_id: str = OFFICER_2) -> Entity:
        return get_success_data(
            self.client.certify_effectiveness_report(report_id, self.officer(officer_id))
        )

    def file_report(self, report_id: str, officer_id: str = OFFICER_2) -> Entity:
        return get_success_data(
            self.client.file_effectiveness_report(report_id, self.officer(officer_id))
        )

    def signed_off_report(
        self,
        provider_id: str,
        variant: str = "PROVISIONAL",
        generating_officer_id: str = OFFICER_2,
        **kwargs: Any,
    ) -> Entity:
        """A report taken all the way to sign-off.

        The plan is filed by one officer and the report signed off by another so
        that the sign-off duty gate is satisfied.
        """
        report = self.generate_report(
            provider_id, variant=variant, officer_id=generating_officer_id, **kwargs
        )
        return self.certify_report(report["id"], generating_officer_id)


class ProviderSetup:
    """The rows produced by one composite provider build."""

    def __init__(
        self,
        provider: Entity,
        certificate: Optional[Entity] = None,
        plan: Optional[Entity] = None,
        customer: Optional[Entity] = None,
        assignment: Optional[Entity] = None,
    ):
        self.provider = provider
        self.certificate = certificate
        self.plan = plan
        self.customer = customer
        self.assignment = assignment

    @property
    def provider_id(self) -> str:
        return self.provider["id"]

    @property
    def certificate_id(self) -> str:
        assert self.certificate is not None, "this setup has no certificate"
        return self.certificate["id"]

    @property
    def plan_id(self) -> str:
        assert self.plan is not None, "this setup has no mitigation plan"
        return self.plan["id"]

    @property
    def customer_id(self) -> str:
        assert self.customer is not None, "this setup has no customer"
        return self.customer["id"]

    @property
    def assignment_id(self) -> str:
        assert self.assignment is not None, "this setup has no number assignment"
        return self.assignment["id"]


def build_signing_ready_provider(
    world: ComplianceWorld,
    provider_type: str = "FACILITIES_BASED",
    kyc_evidence_level: str = "BUSINESS_REGISTRY_VERIFIED",
    ownership_evidence: str = "DIRECT_ALLOCATION",
    telephone_number: str = NUMBER_1,
    effective_from: str = CLOCK_DEFAULT,
    plan_officer_id: str = OFFICER_1,
    **provider_kwargs: Any,
) -> ProviderSetup:
    """A provider that can sign calls: active certificate, accepted plan,
    verified and enabled customer, and one number assignment."""
    provider = world.register_provider(provider_type=provider_type, **provider_kwargs)
    certificate = world.active_certificate(provider["id"])
    plan = world.accepted_plan(provider["id"], officer_id=plan_officer_id)
    customer = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level=kyc_evidence_level
    )
    assignment = world.assign_number(
        provider["id"],
        customer["id"],
        telephone_number,
        ownership_evidence=ownership_evidence,
        effective_from=effective_from,
    )
    return ProviderSetup(provider, certificate, plan, customer, assignment)


def build_provider_with_customer(
    world: ComplianceWorld,
    provider_type: str = "FACILITIES_BASED",
    kyc_evidence_level: str = "CONTRACT_ONLY",
    **provider_kwargs: Any,
) -> ProviderSetup:
    """A provider with no certificate and one verified, enabled customer."""
    provider = world.register_provider(provider_type=provider_type, **provider_kwargs)
    customer = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level=kyc_evidence_level
    )
    return ProviderSetup(provider, customer=customer)


# --- pytest fixtures --------------------------------------------------------


@pytest.fixture
def api_client() -> RmdApiClient:
    """A client bound to the service under test."""
    return RmdApiClient()


@pytest.fixture
def world(api_client: RmdApiClient) -> ComplianceWorld:
    """The setup facade, one per test."""
    return ComplianceWorld(api_client)


@pytest.fixture
def regulator_headers() -> Dict[str, str]:
    return make_regulator_headers()


@pytest.fixture
def policy_admin_headers() -> Dict[str, str]:
    return make_policy_admin_headers()


@pytest.fixture
def officer_headers() -> Dict[str, str]:
    return make_compliance_officer_headers(OFFICER_1)


@pytest.fixture
def kyc_analyst_headers() -> Dict[str, str]:
    return make_kyc_analyst_headers(KYC_1)


@pytest.fixture
def fraud_analyst_headers() -> Dict[str, str]:
    return make_fraud_analyst_headers(FRAUD_1)


@pytest.fixture
def signing_ready(world: ComplianceWorld) -> ProviderSetup:
    """A provider whose posture permits signing, with one owned number."""
    return build_signing_ready_provider(world)


@pytest.fixture
def provider_with_customer(world: ComplianceWorld) -> ProviderSetup:
    """A provider with a verified, enabled customer and no certificate."""
    return build_provider_with_customer(world)
