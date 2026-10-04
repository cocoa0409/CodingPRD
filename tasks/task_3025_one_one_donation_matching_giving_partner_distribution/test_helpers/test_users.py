"""Pre-built role headers for every operating capacity in the PRD (PRD §2.1).

Two shapes are emitted per role:

* a shared constant in ``TEST_USERS`` — safe for opaque roles, and for calls whose
  success does not depend on the caller owning the subject resource;
* a per-instance builder ``make_<role>_headers(user_id)`` — mandatory for any role
  whose identity is tied to a persisted entity (``GivingPartnerOrg`` is the only
  such role), so ownership-gated calls pass the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "coordinator_headers": build_user_headers("op-coordinator-1", "GivingPartnerCoordinator"),
    "provisioning_headers": build_user_headers("op-provisioning-1", "ProvisioningPartner"),
    "planner_headers": build_user_headers("op-planner-1", "AllocationPlanner"),
    "fulfillment_headers": build_user_headers("op-fulfillment-1", "FulfillmentOperator"),
    "customer_service_headers": build_user_headers("op-customer-service-1", "CustomerService"),
    "marketing_headers": build_user_headers("op-marketing-1", "MarketingManager"),
    "auditor_headers": build_user_headers("op-auditor-1", "ImpactAuditor"),
    # Product design is exercised through the ProvisioningPartner capacity, which is
    # the role the PRD declares for donation product design and activation.
    "designer_headers": build_user_headers("op-provisioning-1", "ProvisioningPartner"),
}


def make_giving_partner_org_headers(partner_id: str) -> dict:
    """For GivingPartnerOrg, whose X-User-ID is the acting GivingPartner's id.

    Pass the actual GivingPartner.id whenever the call is ownership-gated
    (receipt confirmation, partner-addressed roll-up reads).
    """
    return build_user_headers(partner_id, "GivingPartnerOrg")


def make_auditor_headers(user_id: str) -> dict:
    """Distinct auditor identifiers, for the four-eyes finalization rule."""
    return build_user_headers(user_id, "ImpactAuditor")


def make_coordinator_headers(user_id: str) -> dict:
    """Distinct coordinator identifiers, for ownership-sensitive partner work."""
    return build_user_headers(user_id, "GivingPartnerCoordinator")