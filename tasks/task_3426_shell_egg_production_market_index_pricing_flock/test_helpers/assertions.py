"""Entity assertions and small domain invariant checkers.

Each ``assert_<entity>`` checks the fields the PRD's narrative documents for
that resource: uuid-shaped id, logical-clock timestamps, and enum membership.
``assert_market_quotation`` additionally pins the append-only exception of
PRD §2.5 (no ``updated_at``, no ``version``).
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_complex(data: dict):
    _assert_common(data, "Complex")
    assert data["region_code"] in (
        "MIDWEST", "SOUTHEAST", "SOUTHWEST", "WEST", "NORTHEAST"
    )
    assert data["biosecurity_posture"] in ("NORMAL", "ELEVATED", "QUARANTINE")
    for field in (
        "corn_inventory_tons", "corn_organic_inventory_tons",
        "soy_inventory_tons", "soy_organic_inventory_tons",
        "ungraded_conventional_dozen", "ungraded_cage_free_dozen",
        "ungraded_organic_dozen", "ops_run_index",
    ):
        assert isinstance(data[field], int), f"Complex.{field} must be an integer"


def assert_house(data: dict):
    _assert_common(data, "House")
    assert data["housing_style"] in ("CONVENTIONAL", "CAGE_FREE", "ORGANIC")
    assert isinstance(data["capacity_hens"], int) and data["capacity_hens"] > 0
    assert isinstance(data["hen_inventory"], int)
    assert "downtime_until" in data


def assert_certification(data: dict):
    _assert_common(data, "Certification")
    assert data["program"] in ("CAGE_FREE", "ORGANIC")
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "EXPIRED")


def assert_flock(data: dict):
    _assert_common(data, "Flock")
    assert data["program"] in ("CONVENTIONAL", "CAGE_FREE", "ORGANIC")
    assert data["ownership"] in ("OWNED", "CONTRACT")
    assert data["status"] in (
        "PLANNED", "GROWING", "LAYING", "MOLT",
        "DEPLETED", "DEPOPULATED", "CANCELLED",
    )
    assert isinstance(data["current_hen_count"], int)
    assert isinstance(data["age_weeks"], int)
    assert isinstance(data["molt_count"], int)


def assert_disease_event(data: dict):
    _assert_common(data, "DiseaseEvent")
    assert data["pathogen"] in ("HPAI", "LPAI", "NEWCASTLE", "SALMONELLA")
    assert data["status"] in ("SUSPECTED", "CONFIRMED", "DISMISSED", "CLEARED")
    assert isinstance(data["scope_house_ids"], list)


def assert_depopulation_order(data: dict):
    _assert_common(data, "DepopulationOrder")
    assert data["disposal_method"] in (
        "COMPOSTING", "BURIAL", "INCINERATION", "LANDFILL"
    )
    assert data["status"] in ("ISSUED", "COMPLETED")
    assert isinstance(data["downtime_days"], int)


def assert_market_quotation(data: dict):
    """Append-only quotation: id + created_at only among system fields."""
    assert is_valid_uuid(data.get("id", "")), "MarketQuotation.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "MarketQuotation.created_at must be an ISO 8601 timestamp"
    assert data["region_code"] in (
        "MIDWEST", "SOUTHEAST", "SOUTHWEST", "WEST", "NORTHEAST"
    )
    assert data["size_class"] in (
        "JUMBO", "EXTRA_LARGE", "LARGE", "MEDIUM", "SMALL", "PEEWEE"
    )
    assert data["source"] in ("URNER_BARRY", "USDA_AMS")
    # PRD §2.5: "both updated_at and version are absent from it".
    assert "version" not in data, "MarketQuotation must not carry version"
    assert "updated_at" not in data, "MarketQuotation must not carry updated_at"


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert data["segment"] in ("RETAIL", "FOODSERVICE", "PROCESSOR")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["outstanding_cents"], int)


def assert_commitment(data: dict):
    _assert_common(data, "CustomerCommitment")
    assert data["program"] in ("CONVENTIONAL", "CAGE_FREE", "ORGANIC")
    assert data["status"] in ("PENDING", "ACTIVE", "EXPIRED")
    assert isinstance(data["blocked_order_count"], int)


def assert_sales_order(data: dict):
    _assert_common(data, "SalesOrder")
    assert data["size_class"] in (
        "JUMBO", "EXTRA_LARGE", "LARGE", "MEDIUM", "SMALL", "PEEWEE"
    )
    assert data["status"] in (
        "BOOKED", "ALLOCATED", "BLOCKED", "SHIPPED", "SETTLED", "CANCELLED"
    )


def assert_settlement(data: dict):
    _assert_common(data, "Settlement")
    assert data["status"] in ("PROVISIONAL", "FINAL", "DISPUTED", "PAID")
    assert isinstance(data["dozen_shipped"], int)


def assert_feed_contract(data: dict):
    _assert_common(data, "FeedContract")
    assert data["commodity"] in ("CORN", "SOYBEAN_MEAL")
    assert data["status"] in ("OPEN", "PARTIALLY_RECEIVED", "FILLED")
    assert isinstance(data["received_tons"], int)
    assert isinstance(data["hedged_tons"], int)


def assert_feed_batch(data: dict):
    _assert_common(data, "FeedBatch")
    assert data["program"] in ("CONVENTIONAL", "CAGE_FREE", "ORGANIC")
    assert isinstance(data["tons_produced"], int)
    assert data["tons_produced"] == data["corn_tons"] + data["soybean_tons"]


def assert_packing_run(data: dict):
    _assert_common(data, "PackingRun")
    assert data["program"] in ("CONVENTIONAL", "CAGE_FREE", "ORGANIC")
    assert data["status"] in ("PACKED", "VERIFIED")
    assert isinstance(data["total_cases"], int)


def assert_capital_project(data: dict):
    _assert_common(data, "CapitalProject")
    assert data["target_style"] in ("CAGE_FREE", "ORGANIC")
    assert data["status"] in (
        "PROPOSED", "APPROVED", "IN_CONSTRUCTION", "COMMISSIONED"
    )


def assert_cases_reconcile(run: dict):
    """PRD §3.9: the six size keys are all present and sum to total_cases."""
    cases = run["cases_by_size"]
    assert set(cases.keys()) == {
        "JUMBO", "EXTRA_LARGE", "LARGE", "MEDIUM", "SMALL", "PEEWEE"
    }, f"cases_by_size must carry exactly the six size classes, got {sorted(cases)}"
    for size, count in cases.items():
        assert isinstance(count, int) and count >= 0, (
            f"cases_by_size[{size}] must be a non-negative integer"
        )
    assert sum(cases.values()) == run["total_cases"], (
        f"largest-remainder reconciliation: sum {sum(cases.values())} "
        f"!= total_cases {run['total_cases']}"
    )


def assert_instant_equal(actual, expected, label="instant"):
    """Compare two ISO 8601 instants at millisecond width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )
