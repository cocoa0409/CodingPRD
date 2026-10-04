"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

COMMON_FIELD_ENTITIES = (
    "Project",
    "BidItem",
    "Bond",
    "Surety",
    "SubcontractorQuote",
    "ProgressMeasurement",
    "QuantityReconciliation",
    "DifferingSiteCondition",
    "EngineerDetermination",
    "SuretyCommitment",
)


def assert_common_fields(data: dict, entity: str = "resource"):
    """Every resource in this system carries the full common field set."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_project(data: dict):
    assert_common_fields(data, "Project")
    assert isinstance(data["project_code"], str) and data["project_code"]
    assert isinstance(data["owner_agency_name"], str) and data["owner_agency_name"]
    assert data["contract_type"] in ("UNIT_PRICE", "LUMP_SUM")
    assert is_iso8601_timestamp(data["bid_deadline_at"])
    assert data["bid_status"] in ("DRAFT", "SEALED", "OPEN", "RECALLED")
    assert data["project_status"] in ("PRE_BID", "AWARDED", "ACTIVE", "COMPLETE")
    assert isinstance(data["claim_window_open"], bool)
    assert isinstance(data["total_bid_cents"], int)
    assert isinstance(data["contract_value_cents"], int)
    assert isinstance(data["retention_balance_cents"], int)


def assert_bid_item(data: dict):
    assert_common_fields(data, "BidItem")
    assert data["unit_of_measure"] in ("LF", "CY", "TON", "EA", "SY")
    assert data["item_status"] in (
        "DRAFT", "PRICED", "SUBMITTED", "AWARDED", "ACTIVE", "CLOSED"
    )
    assert isinstance(data["renegotiation_required"], bool)
    assert isinstance(data["balanced_unit_price_cents"], int)
    assert isinstance(data["measured_quantity"], (int, float))
    assert isinstance(data["variance_pct"], (int, float))


def assert_surety(data: dict):
    assert_common_fields(data, "Surety")
    assert isinstance(data["aggregate_capacity_cents"], int)
    assert isinstance(data["capacity_consumed_cents"], int)
    assert isinstance(data["available_capacity_cents"], int)
    assert data["surety_status"] in ("ACTIVE", "SUSPENDED")


def assert_surety_capacity_conserved(data: dict):
    """aggregate == consumed + available, with available floored at zero."""
    assert data["available_capacity_cents"] >= 0, "available capacity is floored at zero"
    assert (
        data["capacity_consumed_cents"] + data["available_capacity_cents"]
        == data["aggregate_capacity_cents"]
    ), (
        "consumed + available must equal the immutable aggregate capacity: "
        f"{data['capacity_consumed_cents']} + {data['available_capacity_cents']} "
        f"!= {data['aggregate_capacity_cents']}"
    )


def assert_bond(data: dict):
    assert_common_fields(data, "Bond")
    assert data["bond_type"] in ("BID", "PERFORMANCE", "PAYMENT", "MAINTENANCE")
    assert data["bond_status"] in ("PENDING", "ISSUED", "EXECUTED", "RELEASED")
    assert isinstance(data["required_bond_cents"], int)
    assert isinstance(data["capacity_consumed_cents"], int)


def assert_quote(data: dict):
    assert_common_fields(data, "SubcontractorQuote")
    assert data["quote_status"] in ("RECEIVED", "CARRIED", "REJECTED", "SELECTED")
    assert isinstance(data["version_round"], int)
    assert isinstance(data["carried_in_bid"], bool)
    assert isinstance(data["shopping_flagged"], bool)
    assert isinstance(data["dbe_credit_cents"], int)


def assert_measurement(data: dict):
    assert_common_fields(data, "ProgressMeasurement")
    assert data["measurement_status"] in ("DRAFT", "APPROVED", "PAYABLE", "VOIDED")
    assert isinstance(data["applied_unit_price_cents"], int)
    assert isinstance(data["payable_amount_cents"], int)


def assert_reconciliation(data: dict):
    assert_common_fields(data, "QuantityReconciliation")
    assert data["reconciliation_status"] in ("OPEN", "FINALIZED", "CLOSED")
    assert data["closeout_status"] in ("NONE", "PENDING_RETENTION", "CLOSED")
    for field in (
        "overrun_item_count",
        "underrun_item_count",
        "net_adjustment_cents",
        "final_contract_value_cents",
        "retention_held_cents",
        "pace_basis_retention_cents",
        "retention_released_cents",
    ):
        assert isinstance(data[field], int), f"reconciliation.{field} must be an integer"


def assert_condition(data: dict):
    assert_common_fields(data, "DifferingSiteCondition")
    assert data["condition_status"] in (
        "REPORTED", "DOCUMENTED", "UNDER_REVIEW", "DETERMINED", "DENIED"
    )
    assert isinstance(data["documentation_complete"], bool)
    assert isinstance(data["notice_days_elapsed"], int)
    assert isinstance(data["claim_window_engaged"], bool)


def assert_determination(data: dict):
    assert_common_fields(data, "EngineerDetermination")
    assert data["determination_type"] in (
        "TIME_EXTENSION", "COST_EQUITABLE_ADJUSTMENT", "QUANTITY_ADJUSTMENT", "REJECTED"
    )
    assert data["determination_status"] in ("PENDING", "ISSUED", "FINAL")
    assert isinstance(data["entitles_adjustment"], bool)


def assert_commitment(data: dict):
    assert_common_fields(data, "SuretyCommitment")
    assert data["commitment_status"] in ("RESERVED", "ACTIVE", "RELEASED")
    assert isinstance(data["committed_amount_cents"], int)
