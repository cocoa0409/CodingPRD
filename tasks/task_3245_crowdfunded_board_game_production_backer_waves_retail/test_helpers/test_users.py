"""Pre-built role headers for every role in the PRD (§2.1).

All nine roles use an opaque identity model: X-User-ID is an operator
identifier not tied to the id of any persisted entity. Ownership comparisons
are against designated owner fields recorded on resources (backer_user_id on
pledges, distributor_user_id on allocations), so the helper builders below let
tests construct headers whose X-User-ID equals the owner field value.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "campaign_owner_headers": build_user_headers("test-owner-1", "CampaignOwner"),
    "backer_headers": build_user_headers("test-backer-1", "Backer"),
    "factory_coordinator_headers": build_user_headers(
        "test-factory-1", "FactoryCoordinator"
    ),
    "freight_broker_headers": build_user_headers("test-freight-1", "FreightBroker"),
    "customs_agent_headers": build_user_headers("test-customs-1", "CustomsAgent"),
    "fulfillment_operator_headers": build_user_headers(
        "test-fulfillment-1", "FulfillmentOperator"
    ),
    "distributor_headers": build_user_headers("test-distributor-1", "Distributor"),
    "localization_partner_headers": build_user_headers(
        "test-localization-1", "LocalizationPartner"
    ),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_backer_headers(backer_user_id: str) -> dict:
    """For Backer ownership-gated calls (address ops, replacement filing):
    X-User-ID must equal pledge.backer_user_id."""
    return build_user_headers(backer_user_id, "Backer")


def make_distributor_headers(distributor_user_id: str) -> dict:
    """For Distributor ownership-gated calls (confirm, release): X-User-ID must
    equal allocation.distributor_user_id."""
    return build_user_headers(distributor_user_id, "Distributor")


def make_campaign_owner_headers(owner_user_id: str) -> dict:
    """CampaignOwner headers with a specific X-User-ID."""
    return build_user_headers(owner_user_id, "CampaignOwner")
