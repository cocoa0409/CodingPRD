"""Domain assertions for the Federal Water Allocation API.

These wrap the shared structural helpers with the vocabulary of this
contract: instants compare on their canonical form rather than on raw
strings, megawatt-hours compare at the two-decimal precision the contract
fixes (PRD §2.6), money compares as integer cents, and each entity's shape is
checked once here instead of in every test.
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .types import (
    AgreementStatus,
    AllocationBasis,
    AnnouncementStatus,
    CompliancePosture,
    ComplianceStatus,
    ContractStatus,
    FulfillmentStatus,
    IncidentResolution,
    IncidentStatus,
    ObservationType,
    PriorityClass,
    ReleasePurpose,
    ReleaseStatus,
    RequirementType,
    RevenuePeriodStatus,
    ReviewBasis,
    ShortageTier,
    Species,
    TransferStatus,
    WaterYearStatus,
)


# ── Instants ───────────────────────────────────────────────────────────────

def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment.

    Sub-second precision is not part of the comparison: both sides are reduced
    to a canonical three-digit form first, so a value rendered without a
    fractional part still matches the same moment rendered with one.
    """
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_format(value: str, label: str = "instant") -> None:
    """Assert a value is an ISO 8601 UTC instant in the rendering the contract uses."""
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"{label}: must be rendered in UTC with a Z suffix: {value!r}"


# ── Numbers ────────────────────────────────────────────────────────────────

def assert_quantity(actual: Any, expected: float, places: int = 2, label: str = "value") -> None:
    """Assert a fixed-precision quantity equals the expected figure at that precision."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert round(float(actual), places) == round(float(expected), places), (
        f"{label}: expected {expected} at {places} decimal places, got {actual}"
    )


def assert_two_dp(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a megawatt-hour figure, which the contract carries to exactly two
    decimal places (PRD §2.6)."""
    assert_quantity(actual, expected, 2, label)


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money amount, which the contract carries as an integer number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_acre_feet(actual: Any, expected: int, label: str = "volume") -> None:
    """Assert a water volume, which the contract carries as whole acre-feet."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: volumes must be whole acre-feet, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} af, got {actual}"


# ── Envelope and common fields (PRD §2.2, §2.5) ────────────────────────────

def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the meta block carries a prefixed request id and a UTC instant."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "meta.api_request_timestamp")


def assert_identity_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert a resource carries a server-minted UUID and a UTC creation instant."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data["created_at"], f"{label}.created_at")


def assert_mutable_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert the full identity quartet on a resource that can be mutated."""
    assert_identity_fields(data, label)
    assert_instant_format(data["updated_at"], f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and not isinstance(data["version"], bool), (
        f"{label}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_append_only_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert an immutable measurement record carries only an identifier and a
    creation instant - the contract's sole exception to the common quartet."""
    assert_identity_fields(data, label)
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_list_page(meta: Dict[str, Any], total_count: int, has_more: bool, limit: int, offset: int) -> None:
    """Assert the pagination block of a list response (PRD §2.3)."""
    assert meta["total_count"] == total_count, f"total_count: expected {total_count}, got {meta['total_count']}"
    assert meta["has_more"] is has_more, f"has_more: expected {has_more}, got {meta['has_more']}"
    assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"


def assert_ids_in_order(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Assert a list page returns exactly the expected ids in order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"ids: expected {list(expected_ids)}, got {actual}"


# ── Per-entity shapes ──────────────────────────────────────────────────────

def assert_district(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "District")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["service_area_acres"], int) and data["service_area_acres"] > 0
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_water_contract(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "WaterContract")
    assert is_valid_uuid(data["district_id"])
    assert isinstance(data["contract_number"], str) and data["contract_number"]
    assert data["priority_class"] in {c.value for c in PriorityClass}
    assert isinstance(data["max_annual_quantity_af"], int) and data["max_annual_quantity_af"] > 0
    assert isinstance(data["repayment_obligation_cents"], int) and data["repayment_obligation_cents"] >= 0
    assert isinstance(data["repaid_credits_cents"], int) and data["repaid_credits_cents"] >= 0
    assert data["status"] in {s.value for s in ContractStatus}


def assert_water_year(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "WaterYear")
    assert isinstance(data["label"], int)
    assert_instant_format(data["season_start"], "WaterYear.season_start")
    assert_instant_format(data["season_end"], "WaterYear.season_end")
    assert data["status"] in {s.value for s in WaterYearStatus}
    assert "current_announcement_id" in data


def assert_hydrology_observation(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "HydrologyObservation")
    assert is_valid_uuid(data["water_year_id"])
    assert data["observation_type"] in {t.value for t in ObservationType}
    assert isinstance(data["value"], int) and data["value"] >= 0
    assert_instant_format(data["observed_on"], "HydrologyObservation.observed_on")


def assert_allocation_announcement(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "AllocationAnnouncement")
    assert is_valid_uuid(data["water_year_id"])
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert data["status"] in {s.value for s in AnnouncementStatus}
    if data["status"] == AnnouncementStatus.DRAFT.value:
        # While DRAFT, the computed fields are null (PRD §3.3).
        assert data["declared_supply_af"] is None
        assert data["shortage_tier"] is None
        assert data["published_at"] is None
    else:
        assert_acre_feet(data["declared_supply_af"], data["declared_supply_af"], "declared_supply_af")
        assert data["shortage_tier"] in {t.value for t in ShortageTier}
        assert data["allocation_basis"] in {b.value for b in AllocationBasis}
        assert_instant_format(data["published_at"], "AllocationAnnouncement.published_at")


def assert_allocation_line(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "AllocationLine")
    assert is_valid_uuid(data["announcement_id"])
    assert is_valid_uuid(data["contract_id"])
    for field in ("allocated_af", "delivered_af", "transfer_in_af", "transfer_out_af", "remaining_af"):
        assert isinstance(data[field], int) and not isinstance(data[field], bool), (
            f"AllocationLine.{field} must be integer acre-feet, got {data[field]!r}"
        )


def assert_reservoir(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "Reservoir")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_af"], int) and data["capacity_af"] > 0
    assert isinstance(data["dead_pool_af"], int) and 0 <= data["dead_pool_af"] < data["capacity_af"]
    assert isinstance(data["flood_control_max_storage_af"], int) and data["flood_control_max_storage_af"] > 0
    assert isinstance(data["initial_storage_af"], int) and 0 <= data["initial_storage_af"] <= data["capacity_af"]
    assert isinstance(data["current_storage_af"], int)
    assert isinstance(data["outlet_capacity_cfs"], int) and data["outlet_capacity_cfs"] > 0
    assert float(data["power_conversion_mwh_per_af"]) > 0
    assert data["compliance_posture"] in {p.value for p in CompliancePosture}
    assert isinstance(data["open_incident_count"], int) and data["open_incident_count"] >= 0
    assert isinstance(data["total_repayment_obligation_cents"], int)
    assert isinstance(data["unrecovered_balance_cents"], int)


def assert_release_order(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "ReleaseOrder")
    assert is_valid_uuid(data["reservoir_id"])
    assert data["purpose"] in {p.value for p in ReleasePurpose}
    assert isinstance(data["release_cfs"], int) and data["release_cfs"] > 0
    assert isinstance(data["duration_days"], int) and data["duration_days"] > 0
    assert_instant_format(data["scheduled_start"], "ReleaseOrder.scheduled_start")
    assert_instant_format(data["scheduled_end"], "ReleaseOrder.scheduled_end")
    assert isinstance(data["volume_af"], int) and data["volume_af"] > 0
    assert data["status"] in {s.value for s in ReleaseStatus}
    if data["status"] == ReleaseStatus.EXECUTED.value:
        assert_instant_format(data["executed_at"], "ReleaseOrder.executed_at")
    else:
        assert data["executed_at"] is None


def assert_environmental_constraint(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "EnvironmentalConstraint")
    assert is_valid_uuid(data["reservoir_id"])
    assert data["species"] in {s.value for s in Species}
    assert data["requirement_type"] in {t.value for t in RequirementType}
    assert_instant_format(data["enforce_start"], "EnvironmentalConstraint.enforce_start")
    assert_instant_format(data["enforce_end"], "EnvironmentalConstraint.enforce_end")


def assert_compliance_incident(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "ComplianceIncident")
    assert is_valid_uuid(data["reservoir_id"])
    assert is_valid_uuid(data["constraint_id"])
    assert is_valid_uuid(data["release_order_id"])
    assert isinstance(data["deficit_cfs"], int) and data["deficit_cfs"] > 0
    assert data["status"] in {s.value for s in IncidentStatus}
    if data["status"] == IncidentStatus.OPEN.value:
        assert data["resolution"] is None
    else:
        assert data["resolution"] in {r.value for r in IncidentResolution}


def assert_delivery_order(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "DeliveryOrder")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["water_year_id"])
    assert is_valid_uuid(data["allocation_line_id"])
    assert isinstance(data["ordered_af"], int) and data["ordered_af"] > 0
    assert isinstance(data["delivered_af"], int) and data["delivered_af"] >= 0
    assert data["fulfillment_status"] in {s.value for s in FulfillmentStatus}
    assert data["compliance_status"] in {s.value for s in ComplianceStatus}


def assert_revenue_period(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "RevenuePeriod")
    assert is_valid_uuid(data["reservoir_id"])
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert isinstance(data["rate_cents_per_mwh"], int) and data["rate_cents_per_mwh"] > 0
    assert float(data["projected_mwh"]) >= 0
    assert isinstance(data["projected_revenue_cents"], int) and data["projected_revenue_cents"] >= 0
    assert data["status"] in {s.value for s in RevenuePeriodStatus}
    if data["status"] == RevenuePeriodStatus.SETTLED.value:
        assert data["settled_mwh"] is not None
        assert data["settled_revenue_cents"] is not None
    else:
        assert data["settled_mwh"] is None
        assert data["settled_revenue_cents"] is None


def assert_transfer_request(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "TransferRequest")
    assert is_valid_uuid(data["from_contract_id"])
    assert is_valid_uuid(data["to_contract_id"])
    assert data["from_contract_id"] != data["to_contract_id"]
    assert is_valid_uuid(data["water_year_id"])
    assert isinstance(data["quantity_af"], int) and data["quantity_af"] > 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in {s.value for s in TransferStatus}
    assert isinstance(data["revision_count"], int) and 0 <= data["revision_count"] <= 3
    assert "objection_window_end" in data
    assert "executed_at" in data


def assert_impact_review(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "ImpactReview")
    assert is_valid_uuid(data["transfer_request_id"])
    assert is_valid_uuid(data["reviewer_district_id"])
    assert isinstance(data["claimed_impact_af"], int) and data["claimed_impact_af"] > 0
    assert data["basis"] in {b.value for b in ReviewBasis}
    assert data["status"] in {"FILED", "SUSTAINED", "DISMISSED"}
    assert "resolution_rationale" in data


def assert_shortage_agreement(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "ShortageAgreement")
    assert isinstance(data["name"], str) and data["name"]
    for field in ("tier_1_senior_pct", "tier_1_junior_pct", "tier_2_senior_pct", "tier_2_junior_pct"):
        assert isinstance(data[field], int) and 0 <= data[field] <= 100, (
            f"ShortageAgreement.{field} must be an integer percent 0..100, got {data[field]!r}"
        )
    assert isinstance(data["quorum_district_count"], int) and data["quorum_district_count"] >= 1
    assert isinstance(data["signatory_district_ids"], list)
    assert data["status"] in {s.value for s in AgreementStatus}
    assert "activated_water_year_label" in data


# ── Standing invariants (PRD §2.10, §3.6) ──────────────────────────────────

def assert_repayment_invariant(reservoir: Dict[str, Any], contracts: Iterable[Dict[str, Any]]) -> None:
    """The fiscal invariant: summed repaid credits plus the unrecovered balance
    exactly equals the total repayment obligation, at all times."""
    repaid_sum = sum(c["repaid_credits_cents"] for c in contracts)
    total = reservoir["total_repayment_obligation_cents"]
    unrecovered = reservoir["unrecovered_balance_cents"]
    assert repaid_sum + unrecovered == total, (
        f"repayment invariant broken: repaid {repaid_sum} + unrecovered {unrecovered} != total {total}"
    )


def assert_line_remaining(line: Dict[str, Any], active_orders: Iterable[Dict[str, Any]]) -> None:
    """Recompute a line's remaining balance from first principles (PRD §3.6):
    allocation plus transfers in, minus transfers out, minus deliveries, minus
    the outstanding commitments of orders still CONFIRMED or PARTIALLY_DELIVERED."""
    outstanding = sum(
        o["ordered_af"] - o["delivered_af"]
        for o in active_orders
        if o["fulfillment_status"] in ("CONFIRMED", "PARTIALLY_DELIVERED")
    )
    expected = (
        line["allocated_af"]
        + line["transfer_in_af"]
        - line["transfer_out_af"]
        - line["delivered_af"]
        - outstanding
    )
    assert line["remaining_af"] == expected, (
        f"remaining_af: expected {expected} from the balance formula, got {line['remaining_af']}"
    )
