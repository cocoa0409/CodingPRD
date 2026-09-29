"""Pytest fixtures and the setup helper that builds programme state through the API.

The server is restarted before every test, so every fixture here builds the state it
needs from scratch by calling public endpoints in the order the PRD prescribes:

    clock -> product -> version -> promote -> developer -> onboarding acknowledgement
    -> [ecosystem participation] -> access application -> submit -> claim -> decide
    -> read product version -> provision entitlement -> activate

Setup calls use ``get_success_data`` so a fixture never asserts a specific creation
status; the tests own the status assertions.
"""
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient, canonical_instant
from .constants import (
    ADMIN_ID,
    CANONICAL_SAMPLE_APP_SLUG,
    CANONICAL_SCOPE,
    CLOCK_DEFAULT,
    CURRENT_DOCS_REVISION,
    DEFAULT_REQUIRED_TOS_VERSION,
)
from .test_users import (
    DEV_REL_MANAGER,
    DEV_REL_MANAGER_ALT,
    PLATFORM_ADMIN,
    SUPPORT_AGENT,
    TRUST_OFFICER,
    make_developer_headers,
)


class Programme:
    """Builds programme state through the API and hands back the entity payloads."""

    def __init__(self, api: ApiClient):
        self.api = api

    # ---------------------------------------------------------------------- clock
    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(current_utc, PLATFORM_ADMIN))

    def read_clock(self) -> str:
        return get_success_data(self.api.get_clock())["current_utc"]

    # ------------------------------------------------------------------- products
    def create_product(self, **kwargs: Any) -> Dict[str, Any]:
        payload = f.api_product_payload(**kwargs)
        return get_success_data(self.api.create_api_product(payload, PLATFORM_ADMIN))

    def read_product(self, product_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_api_product(product_id, PLATFORM_ADMIN))

    def product_version_counter(self, product_id: str) -> int:
        """The product's optimistic-concurrency counter, as a provisioning caller reads it."""
        return self.read_product(product_id)["version"]

    def adjust_product(self, product_id: str, **kwargs: Any) -> Dict[str, Any]:
        payload = f.program_adjustment_payload(**kwargs)
        return get_success_data(self.api.adjust_program(product_id, payload, PLATFORM_ADMIN))

    # ------------------------------------------------------------------- versions
    def create_version(self, product_id: str, **kwargs: Any) -> Dict[str, Any]:
        payload = f.api_version_payload(**kwargs)
        return get_success_data(self.api.create_api_version(product_id, payload, PLATFORM_ADMIN))

    def promote_version(self, version_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.promote_api_version(version_id, {}, PLATFORM_ADMIN))

    def grantable_version(self, product_id: str, **kwargs: Any) -> Dict[str, Any]:
        """A version promoted to general availability, which is what applications target."""
        version = self.create_version(product_id, **kwargs)
        return self.promote_version(version["id"])

    def read_version(self, version_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_api_version(version_id, PLATFORM_ADMIN))

    def publish_migration_guide(self, version_id: str, **kwargs: Any) -> Dict[str, Any]:
        payload = f.migration_guide_payload(**kwargs)
        return get_success_data(
            self.api.publish_migration_guide(version_id, payload, PLATFORM_ADMIN)
        )

    def announce_deprecation(self, version_id: str, notice_days: int) -> Dict[str, Any]:
        payload = f.announce_deprecation_payload(notice_days)
        return get_success_data(self.api.announce_deprecation(version_id, payload, PLATFORM_ADMIN))

    # ----------------------------------------------------------------- developers
    def register_developer(self, **kwargs: Any) -> Dict[str, Any]:
        payload = f.developer_payload(**kwargs)
        return get_success_data(self.api.register_developer(payload, DEV_REL_MANAGER))

    def headers_for(self, developer: Dict[str, Any]) -> Dict[str, str]:
        return make_developer_headers(developer["id"])

    def read_developer(self, developer_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_developer(developer_id, PLATFORM_ADMIN))

    def acknowledge(
        self,
        developer: Dict[str, Any],
        docs_version: int = CURRENT_DOCS_REVISION,
        tos_version: int = DEFAULT_REQUIRED_TOS_VERSION,
    ) -> Dict[str, Any]:
        payload = f.onboarding_acknowledgement_payload(docs_version, tos_version)
        return get_success_data(
            self.api.acknowledge_onboarding(
                developer["id"], payload, self.headers_for(developer)
            )
        )

    def record_participation(self, developer: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.ecosystem_participation_payload(**kwargs)
        return get_success_data(
            self.api.record_ecosystem_participation(developer["id"], payload, DEV_REL_MANAGER)
        )

    def certify(
        self,
        developer: Dict[str, Any],
        certification_level: str = "PROFESSIONAL",
        certification_expires_at: str = "2027-08-01T00:00:00Z",
    ) -> Dict[str, Any]:
        return self.record_participation(
            developer,
            certification_level=certification_level,
            certification_expires_at=certification_expires_at,
        )

    def onboarded_developer(self, certified: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """A registered developer that has acknowledged the current docs and terms."""
        developer = self.register_developer(**kwargs)
        self.acknowledge(developer)
        if certified:
            self.certify(developer)
        return self.read_developer(developer["id"])

    def submit_directory(self, developer: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.directory_submission_payload(**kwargs)
        return get_success_data(
            self.api.submit_directory_listing(
                developer["id"], payload, self.headers_for(developer)
            )
        )

    def review_directory(self, developer: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.directory_review_payload(**kwargs)
        return get_success_data(
            self.api.review_directory_listing(developer["id"], payload, DEV_REL_MANAGER)
        )

    def revoke_access(self, developer: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.revoke_access_payload(**kwargs)
        return get_success_data(
            self.api.revoke_developer_access(developer["id"], payload, PLATFORM_ADMIN)
        )

    # -------------------------------------------------------------- applications
    def draft_application(
        self, developer: Dict[str, Any], version: Dict[str, Any], **kwargs: Any
    ) -> Dict[str, Any]:
        payload = f.access_application_payload(developer["id"], version["id"], **kwargs)
        return get_success_data(
            self.api.create_access_application(payload, self.headers_for(developer))
        )

    def submit_application(
        self, application: Dict[str, Any], developer: Dict[str, Any], **kwargs: Any
    ) -> Dict[str, Any]:
        payload = f.submit_application_payload(**kwargs)
        return get_success_data(
            self.api.submit_access_application(
                application["id"], payload, self.headers_for(developer)
            )
        )

    def claim_application(
        self, application: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.claim_application_review(
                application["id"], {}, headers or DEV_REL_MANAGER
            )
        )

    def request_changes(
        self, application: Dict[str, Any], headers: Optional[Dict[str, str]] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        payload = f.request_changes_payload(**kwargs)
        return get_success_data(
            self.api.request_application_changes(
                application["id"], payload, headers or DEV_REL_MANAGER
            )
        )

    def decide_application(
        self, application: Dict[str, Any], headers: Optional[Dict[str, str]] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        payload = f.decide_application_payload(**kwargs)
        return get_success_data(
            self.api.decide_access_application(
                application["id"], payload, headers or PLATFORM_ADMIN
            )
        )

    def approved_application(
        self,
        developer: Dict[str, Any],
        version: Dict[str, Any],
        requested_tier: str = "PARTNER",
        approved_tier: Optional[str] = None,
        requested_scopes: Optional[List[str]] = None,
        granted_scopes: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Draft, submit, claim as one manager and approve as a different operator."""
        scopes = requested_scopes if requested_scopes is not None else [CANONICAL_SCOPE]
        application = self.draft_application(
            developer,
            version,
            requested_tier=requested_tier,
            requested_scopes=scopes,
            **kwargs,
        )
        self.submit_application(application, developer)
        self.claim_application(application)
        return self.decide_application(
            application,
            decision="APPROVE",
            approved_tier=approved_tier or requested_tier,
            granted_scopes=granted_scopes if granted_scopes is not None else list(scopes),
        )

    def read_application(self, application_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_access_application(application_id, PLATFORM_ADMIN)
        )

    # ---------------------------------------------------------------- entitlements
    def provision_entitlement(
        self,
        application: Dict[str, Any],
        product_id: str,
        expected_api_product_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Provision against the product version the caller has just observed."""
        if expected_api_product_version is None:
            expected_api_product_version = self.product_version_counter(product_id)
        payload = f.quota_assignment_payload(application["id"], expected_api_product_version)
        return get_success_data(self.api.create_quota_assignment(payload, PLATFORM_ADMIN))

    def activate_entitlement(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        return get_success_data(
            self.api.activate_quota_assignment(assignment["id"], {}, PLATFORM_ADMIN)
        )

    def suspend_entitlement(self, assignment: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.suspend_payload(**kwargs)
        return get_success_data(
            self.api.suspend_quota_assignment(assignment["id"], payload, PLATFORM_ADMIN)
        )

    def reinstate_entitlement(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        return get_success_data(
            self.api.reinstate_quota_assignment(assignment["id"], {}, PLATFORM_ADMIN)
        )

    def read_entitlement(self, assignment_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_quota_assignment(assignment_id, PLATFORM_ADMIN))

    def record_window(
        self,
        assignment: Dict[str, Any],
        window_start: str,
        total_calls: int,
        burst_calls: int = 0,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        payload = f.usage_window_payload(window_start, total_calls, burst_calls)
        return get_success_data(
            self.api.create_usage_window(assignment["id"], payload, headers or PLATFORM_ADMIN)
        )

    def request_upgrade(
        self,
        assignment: Dict[str, Any],
        developer: Dict[str, Any],
        requested_sustained_rpm: int,
        expected_quota_assignment_version: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if expected_quota_assignment_version is None:
            expected_quota_assignment_version = self.read_entitlement(assignment["id"])["version"]
        payload = f.upgrade_request_payload(
            requested_sustained_rpm, expected_quota_assignment_version, **kwargs
        )
        return get_success_data(
            self.api.create_upgrade_request(
                assignment["id"], payload, self.headers_for(developer)
            )
        )

    def read_upgrade_request(self, request_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_upgrade_request(request_id, PLATFORM_ADMIN))

    def run_allocation(self, product_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.run_upgrade_allocation(product_id, {}, DEV_REL_MANAGER)
        )

    # ------------------------------------------------------------- sandbox leases
    def take_lease(
        self,
        developer: Dict[str, Any],
        product_id: str,
        starts_at: str,
        lease_days: int = 7,
        sample_app_slug: str = CANONICAL_SAMPLE_APP_SLUG,
    ) -> Dict[str, Any]:
        payload = f.sandbox_lease_payload(
            developer["id"], product_id, starts_at, lease_days, sample_app_slug
        )
        return get_success_data(
            self.api.create_sandbox_lease(payload, self.headers_for(developer))
        )

    def validate_lease(self, lease: Dict[str, Any], developer: Dict[str, Any]) -> Dict[str, Any]:
        return get_success_data(
            self.api.validate_sandbox_lease(lease["id"], {}, self.headers_for(developer))
        )

    def release_lease(self, lease: Dict[str, Any], developer: Dict[str, Any]) -> Dict[str, Any]:
        return get_success_data(
            self.api.release_sandbox_lease(lease["id"], {}, self.headers_for(developer))
        )

    def read_lease(self, lease_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_sandbox_lease(lease_id, PLATFORM_ADMIN))

    # ----------------------------------------------------------- violation cases
    def open_case(self, developer: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.violation_case_payload(developer["id"], **kwargs)
        return get_success_data(self.api.create_violation_case(payload, TRUST_OFFICER))

    def investigate_case(
        self, case: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.investigate_violation_case(case["id"], {}, headers or TRUST_OFFICER)
        )

    def adjudicate_case(
        self, case: Dict[str, Any], headers: Optional[Dict[str, str]] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        payload = f.adjudicate_payload(**kwargs)
        return get_success_data(
            self.api.adjudicate_violation_case(case["id"], payload, headers or PLATFORM_ADMIN)
        )

    def appeal_case(
        self, case: Dict[str, Any], developer: Dict[str, Any], **kwargs: Any
    ) -> Dict[str, Any]:
        payload = f.appeal_payload(**kwargs)
        return get_success_data(
            self.api.appeal_violation_case(case["id"], payload, self.headers_for(developer))
        )

    def upheld_case(
        self, developer: Dict[str, Any], **kwargs: Any
    ) -> Dict[str, Any]:
        """Open, investigate as one officer, and uphold as a different operator."""
        case = self.open_case(developer, **kwargs)
        self.investigate_case(case)
        return self.adjudicate_case(case, outcome="UPHELD")

    def read_case(self, case_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_violation_case(case_id, PLATFORM_ADMIN))

    # ------------------------------------------------------------- support cases
    def open_ticket(
        self, product_id: str, developer: Dict[str, Any], severity: str = "S2", **kwargs: Any
    ) -> Dict[str, Any]:
        payload = f.support_case_payload(
            product_id, kind="PARTNER_TICKET", severity=severity,
            developer_id=developer["id"], **kwargs
        )
        return get_success_data(self.api.create_support_case(payload, SUPPORT_AGENT))

    def open_incident(self, product_id: str, severity: str = "S1", **kwargs: Any) -> Dict[str, Any]:
        payload = f.support_case_payload(
            product_id, kind="PLATFORM_INCIDENT", severity=severity, **kwargs
        )
        return get_success_data(self.api.create_support_case(payload, SUPPORT_AGENT))

    def add_communication(self, case: Dict[str, Any], sent_at: str, **kwargs: Any) -> Dict[str, Any]:
        payload = f.communication_payload(sent_at, **kwargs)
        return get_success_data(
            self.api.create_support_communication(case["id"], payload, SUPPORT_AGENT)
        )

    def escalate_case(self, case: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.escalate_payload(**kwargs)
        return get_success_data(self.api.escalate_support_case(case["id"], payload, SUPPORT_AGENT))

    def resolve_case(self, case: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.resolve_support_payload(**kwargs)
        return get_success_data(self.api.resolve_support_case(case["id"], payload, SUPPORT_AGENT))

    def read_support_case(self, case_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_support_case(case_id, PLATFORM_ADMIN))

    # ------------------------------------------------------------ feedback items
    def submit_feedback(
        self, developer: Dict[str, Any], product_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        payload = f.feedback_item_payload(developer["id"], product_id, **kwargs)
        return get_success_data(
            self.api.create_feedback_item(payload, self.headers_for(developer))
        )

    def triage_feedback(self, item: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.triage_payload(**kwargs)
        return get_success_data(self.api.triage_feedback_item(item["id"], payload, DEV_REL_MANAGER))

    def decide_roadmap(self, item: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        payload = f.roadmap_decision_payload(**kwargs)
        return get_success_data(
            self.api.decide_feedback_roadmap(item["id"], payload, DEV_REL_MANAGER)
        )

    def read_feedback(self, item_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_feedback_item(item_id, PLATFORM_ADMIN))

    # ------------------------------------------------------------------ checkpoint
    def run_checkpoint(self) -> Dict[str, Any]:
        return get_success_data(self.api.run_program_checkpoint({}, PLATFORM_ADMIN))

    # ------------------------------------------------------- composite entitlement
    def entitlement_chain(
        self,
        certified: bool = False,
        requested_tier: str = "PARTNER",
        approved_tier: Optional[str] = None,
        requested_scopes: Optional[List[str]] = None,
        granted_scopes: Optional[List[str]] = None,
        activate: bool = True,
        product: Optional[Dict[str, Any]] = None,
        product_kwargs: Optional[Dict[str, Any]] = None,
        application_kwargs: Optional[Dict[str, Any]] = None,
        developer_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """The whole chain from product to live entitlement, as one reusable bundle.

        Returns a dict with the product, the promoted version, the developer, the
        approved application, the entitlement and the developer's headers.
        """
        if product is None:
            product = self.create_product(**(product_kwargs or {}))
        version = self.grantable_version(product["id"])
        developer = self.onboarded_developer(certified=certified, **(developer_kwargs or {}))
        application = self.approved_application(
            developer,
            version,
            requested_tier=requested_tier,
            approved_tier=approved_tier,
            requested_scopes=requested_scopes,
            granted_scopes=granted_scopes,
            **(application_kwargs or {}),
        )
        assignment = self.provision_entitlement(application, product["id"])
        if activate:
            assignment = self.activate_entitlement(assignment)
        return {
            "product": self.read_product(product["id"]),
            "version": version,
            "developer": self.read_developer(developer["id"]),
            "application": application,
            "assignment": assignment,
            "developer_headers": self.headers_for(developer),
        }


# ----------------------------------------------------------------------- fixtures
@pytest.fixture
def api() -> ApiClient:
    """Client bound to the server under test."""
    return ApiClient()


@pytest.fixture
def programme(api: ApiClient) -> Programme:
    """Setup helper that drives the API to build programme state."""
    return Programme(api)


@pytest.fixture
def clock_at_default(programme: Programme) -> str:
    """The clock as the server starts it, asserted to be the documented default."""
    assert canonical_instant(programme.read_clock()) == canonical_instant(CLOCK_DEFAULT)
    return CLOCK_DEFAULT


@pytest.fixture
def product(programme: Programme) -> Dict[str, Any]:
    """A public product with the canonical scope catalogue and both finite pools."""
    return programme.create_product()


@pytest.fixture
def grantable_version(programme: Programme, product: Dict[str, Any]) -> Dict[str, Any]:
    """A version of that product promoted to general availability."""
    return programme.grantable_version(product["id"])


@pytest.fixture
def developer(programme: Programme) -> Dict[str, Any]:
    """A freshly registered developer, before any acknowledgement."""
    return programme.register_developer()


@pytest.fixture
def developer_headers(programme: Programme, developer: Dict[str, Any]) -> Dict[str, str]:
    return programme.headers_for(developer)


@pytest.fixture
def onboarded_developer(programme: Programme) -> Dict[str, Any]:
    """A developer that has acknowledged the current documentation revision and terms."""
    return programme.onboarded_developer()


@pytest.fixture
def partner_entitlement(programme: Programme) -> Dict[str, Any]:
    """An uncertified partner-tier entitlement, activated: the workhorse bundle."""
    return programme.entitlement_chain()


@pytest.fixture
def certified_partner_entitlement(programme: Programme) -> Dict[str, Any]:
    """A professionally certified partner-tier entitlement, activated."""
    return programme.entitlement_chain(certified=True)


@pytest.fixture
def provisioned_partner_entitlement(programme: Programme) -> Dict[str, Any]:
    """A partner-tier entitlement left in PROVISIONED, not yet activated."""
    return programme.entitlement_chain(activate=False)


@pytest.fixture
def standard_entitlement(programme: Programme) -> Dict[str, Any]:
    """An activated standard-tier entitlement, which carries no partner privileges."""
    return programme.entitlement_chain(requested_tier="STANDARD")


OPERATOR_ADMIN_ID = ADMIN_ID
ALT_MANAGER_HEADERS = DEV_REL_MANAGER_ALT
