"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ActivationStatus,
    AddOnStatus,
    AllocationStatus,
    AgreementStatus,
    CaseStatus,
    CycleStatus,
    InventoryStatus,
    PartnerStatus,
    PlanStatus,
    PortStatus,
    SubscriberStatus,
    TermStatus,
)


def assert_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "agreement id must be a valid UUID"
    assert isinstance(data["host_network_name"], str) and data["host_network_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["agreement_status"] in AgreementStatus.ALL
    assert isinstance(data["allocated_data_mb"], int)
    assert isinstance(data["remaining_data_mb"], int)
    assert isinstance(data["congestion_index"], int)
    assert isinstance(data["congestion_active"], bool)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "plan id must be a valid UUID"
    assert data["plan_status"] in PlanStatus.ALL
    assert data["term_months"] in [3, 6, 12]
    assert data["renewal_price_cents"] > data["intro_price_cents"]
    assert data["data_allotment_mb"] >= 1
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_subscriber(data: dict):
    assert is_valid_uuid(data.get("id", "")), "subscriber id must be a valid UUID"
    assert data["subscriber_status"] in SubscriberStatus.ALL
    assert data["allocation_status"] in AllocationStatus.ALL
    assert isinstance(data["data_used_mb_cycle"], int) and data["data_used_mb_cycle"] >= 0
    assert isinstance(data["deprioritized_this_cycle"], bool)
    assert isinstance(data["support_seconds_used"], int) and data["support_seconds_used"] >= 0
    assert isinstance(data["support_seconds_budget"], int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_term(data: dict):
    assert is_valid_uuid(data.get("id", "")), "term id must be a valid UUID"
    assert data["term_status"] in TermStatus.ALL
    assert isinstance(data["term_price_cents"], int)
    assert isinstance(data["deferred_revenue_cents"], int)
    assert isinstance(data["earned_revenue_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_activation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "activation id must be a valid UUID"
    assert data["activation_status"] in ActivationStatus.ALL
    assert data["port_status"] in PortStatus.ALL
    assert isinstance(data["held_data_mb"], int) and data["held_data_mb"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_partner(data: dict):
    assert is_valid_uuid(data.get("id", "")), "partner id must be a valid UUID"
    assert data["partner_status"] in PartnerStatus.ALL
    assert isinstance(data["partner_state_codes"], list) and data["partner_state_codes"]
    assert isinstance(data["shipment_sla_days"], int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_inventory(data: dict):
    assert is_valid_uuid(data.get("id", "")), "inventory id must be a valid UUID"
    assert data["inventory_status"] in InventoryStatus.ALL
    assert data["unit_count"] >= 1
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["units_shipped"], int) and data["units_shipped"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "case id must be a valid UUID"
    assert data["case_status"] in CaseStatus.ALL
    assert isinstance(data["handling_seconds"], int) and data["handling_seconds"] >= 0
    assert is_iso8601_timestamp(data.get("sla_due_at", "")), "sla_due_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_addon(data: dict):
    assert is_valid_uuid(data.get("id", "")), "add-on id must be a valid UUID"
    assert data["addon_status"] in AddOnStatus.ALL
    assert isinstance(data["addon_price_cents"], int)
    assert data["addon_days"] in [1, 7, 30]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_cycle_record(data: dict):
    """CycleRecord is immutable: it carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "cycle id must be a valid UUID"
    assert data["cycle_status"] in CycleStatus.ALL
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert "updated_at" not in data, "a cycle record is immutable and carries no updated_at"
    assert "version" not in data, "a cycle record is immutable and carries no version"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


# --- Domain invariants ---

def assert_agreement_balance_invariant(summary: dict):
    """allocated_data_mb plus remaining_data_mb equals committed_data_mb."""
    data = summary
    assert (
        data["allocated_data_mb"] + data["remaining_data_mb"] == data["committed_data_mb"]
    ), (
        "the megabyte balance must be conserved: "
        f"{data['allocated_data_mb']} + {data['remaining_data_mb']} "
        f"!= {data['committed_data_mb']}"
    )


def assert_revenue_complement(term: dict):
    """earned plus deferred equals the term price, with deferred never above it."""
    assert (
        term["earned_revenue_cents"] + term["deferred_revenue_cents"]
        == term["term_price_cents"]
    ), (
        "earned and deferred revenue must sum to the term price: "
        f"{term['earned_revenue_cents']} + {term['deferred_revenue_cents']} "
        f"!= {term['term_price_cents']}"
    )
    assert term["deferred_revenue_cents"] <= term["term_price_cents"]


def assert_earned_never_exceeds_price(term: dict):
    assert term["earned_revenue_cents"] <= term["term_price_cents"]
    assert term["deferred_revenue_cents"] >= 0