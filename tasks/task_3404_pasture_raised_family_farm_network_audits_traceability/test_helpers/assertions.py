"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    """Common fields of mutable resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer, got {data.get('version')}"
    )


def _assert_immutable_common_fields(data: dict, label: str):
    """Cartons and forecasts carry only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_farm(data: dict):
    _assert_common_fields(data, "farm")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region"], str) and len(data["region"]) > 0
    assert data["pasture_sqft"] > 0
    assert data["barn_sqft"] > 0
    assert isinstance(data["nest_box_count"], int) and data["nest_box_count"] >= 0
    assert isinstance(data["declared_bird_count"], int) and data["declared_bird_count"] > 0
    assert data["status"] in ["ONBOARDING", "ACTIVE", "PROBATION", "SUSPENDED", "REMOVED"]
    assert data["certification_status"] in [
        "CERTIFICATION_PENDING", "CERTIFIED", "CERT_LAPSED", "DECERTIFIED",
    ]
    assert isinstance(data["effective_bird_capacity"], int) and data["effective_bird_capacity"] >= 0
    assert data.get("last_passed_audit_at") is None or is_iso8601_timestamp(data["last_passed_audit_at"])
    assert data.get("removal_reason") is None or isinstance(data["removal_reason"], str)


def assert_contract(data: dict):
    _assert_common_fields(data, "contract")
    assert is_valid_uuid(data.get("farm_id", "")), "contract.farm_id must be a UUID"
    assert isinstance(data["commodity_base_cents_per_dozen"], int)
    assert data["commodity_base_cents_per_dozen"] >= 0
    assert isinstance(data["premium_cents_per_dozen"], int)
    assert data["premium_cents_per_dozen"] >= 0
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "TERMINATED"]


def assert_audit(data: dict):
    _assert_common_fields(data, "audit")
    assert is_valid_uuid(data.get("farm_id", "")), "audit.farm_id must be a UUID"
    assert data["audit_type"] in ["INITIAL", "ANNUAL", "FOR_CAUSE", "RE_AUDIT"]
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert data["status"] in [
        "SCHEDULED", "PASSED", "FAILED", "CORRECTIVE_ACTION_REQUIRED", "EXPIRED", "CANCELLED",
    ]
    assert data.get("auditor_user_id") is None or isinstance(data["auditor_user_id"], str)
    assert isinstance(data["non_conformities_count"], int) and data["non_conformities_count"] >= 0
    assert data.get("completed_at") is None or is_iso8601_timestamp(data["completed_at"])


def assert_corrective_action(data: dict):
    _assert_common_fields(data, "corrective_action")
    assert is_valid_uuid(data.get("audit_id", "")), "corrective_action.audit_id must be a UUID"
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert data["status"] in ["OPEN", "SUBMITTED", "VERIFIED_CLOSED", "OVERDUE", "CANCELLED"]
    assert is_iso8601_timestamp(data["due_at"])
    assert data.get("evidence_notes") is None or isinstance(data["evidence_notes"], str)
    assert data.get("verified_by_user_id") is None or isinstance(data["verified_by_user_id"], str)
    assert data.get("closed_at") is None or is_iso8601_timestamp(data["closed_at"])


def assert_incident(data: dict):
    _assert_common_fields(data, "incident")
    assert is_valid_uuid(data.get("farm_id", "")), "incident.farm_id must be a UUID"
    assert data["severity"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    assert isinstance(data["incident_type"], str) and len(data["incident_type"]) > 0
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert data["status"] in ["REPORTED", "RESOLVED"]
    assert data.get("disposition") is None or data["disposition"] in [
        "NONE", "PROBATION", "SUSPENSION", "REMOVAL",
    ]
    assert data.get("resolved_at") is None or is_iso8601_timestamp(data["resolved_at"])


def assert_route(data: dict):
    _assert_common_fields(data, "route")
    assert isinstance(data["route_date"], str)
    assert isinstance(data["driver_name"], str) and len(data["driver_name"]) > 0
    assert isinstance(data["capacity_cases"], int) and data["capacity_cases"] > 0
    assert data["status"] in ["PLANNED", "COMPLETED"]
    assert isinstance(data["stops"], list)
    for stop in data["stops"]:
        assert isinstance(stop["stop_sequence"], int)
        assert is_valid_uuid(stop.get("farm_id", "")), "stop.farm_id must be a UUID"
        assert isinstance(stop["planned_cases"], int) and stop["planned_cases"] > 0
        assert stop.get("collected_cases") is None or isinstance(stop["collected_cases"], int)
        assert stop["status"] in ["SCHEDULED", "COLLECTED", "SKIPPED"]
    assert isinstance(data["committed_cases"], int) and data["committed_cases"] >= 0
    assert isinstance(data["available_cases"], int)


def assert_lot(data: dict):
    _assert_common_fields(data, "lot")
    assert is_valid_uuid(data.get("farm_id", "")), "lot.farm_id must be a UUID"
    assert is_valid_uuid(data.get("route_id", "")), "lot.route_id must be a UUID"
    assert isinstance(data["stop_sequence"], int)
    assert isinstance(data["lot_code"], str) and data["lot_code"].startswith("LOT-")
    assert isinstance(data["laid_start_date"], str)
    assert isinstance(data["laid_end_date"], str)
    assert isinstance(data["received_cases"], int) and data["received_cases"] > 0
    assert isinstance(data["received_dozens"], int) and data["received_dozens"] > 0
    assert data.get("quality_score") is None or isinstance(data["quality_score"], (int, float))
    assert data["grade"] in ["AA", "A", "B", "NONE"]
    assert data["status"] in ["RECEIVED", "GRADED", "ON_HOLD", "RELEASED", "REJECTED", "PACKED"]
    assert isinstance(data["remaining_dozens"], int) and data["remaining_dozens"] >= 0
    assert isinstance(data["packed_dozens"], int) and data["packed_dozens"] >= 0
    assert isinstance(data["destroyed_dozens"], int) and data["destroyed_dozens"] >= 0
    assert data.get("graded_at") is None or is_iso8601_timestamp(data["graded_at"])


def assert_carton(data: dict):
    _assert_immutable_common_fields(data, "carton")
    assert isinstance(data["carton_code"], str) and "-C" in data["carton_code"]
    assert is_valid_uuid(data.get("lot_id", "")), "carton.lot_id must be a UUID"
    assert data["pack_size"] in ["MEDIUM", "LARGE", "EXTRA_LARGE"]
    assert data["dozens"] == 1
    assert is_valid_uuid(data.get("source_farm_id", "")), "carton.source_farm_id must be a UUID"
    assert isinstance(data["source_farm_name"], str) and len(data["source_farm_name"]) > 0
    assert is_iso8601_timestamp(data["packed_at"])


def assert_retailer(data: dict):
    _assert_common_fields(data, "retailer")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["banner"], str) and len(data["banner"]) > 0
    assert isinstance(data["terms_net_days"], int) and data["terms_net_days"] > 0


def assert_commitment(data: dict):
    _assert_common_fields(data, "commitment")
    assert is_valid_uuid(data.get("farm_id", "")), "commitment.farm_id must be a UUID"
    assert is_valid_uuid(data.get("retailer_id", "")), "commitment.retailer_id must be a UUID"
    assert isinstance(data["week_start"], str)
    assert isinstance(data["committed_dozens"], int) and data["committed_dozens"] > 0
    assert data["status"] in ["ACTIVE", "FILLED", "SHORTFALL", "CANCELLED"]
    assert data.get("delivered_dozens") is None or isinstance(data["delivered_dozens"], int)
    assert data.get("fill_rate") is None or isinstance(data["fill_rate"], (int, float))


def assert_forecast(data: dict):
    _assert_immutable_common_fields(data, "forecast")
    assert is_valid_uuid(data.get("farm_id", "")), "forecast.farm_id must be a UUID"
    assert isinstance(data["week_start"], str)
    assert data["season"] in ["SPRING", "SUMMER", "AUTUMN", "WINTER"]
    assert data["weather_severity"] in ["NONE", "MODERATE", "SEVERE"]
    assert isinstance(data["optimistic_dozens"], int) and data["optimistic_dozens"] >= 0
    assert isinstance(data["conservative_dozens"], int) and data["conservative_dozens"] >= 0


def assert_settlement(data: dict):
    _assert_common_fields(data, "settlement")
    assert isinstance(data["week_start"], str)
    assert data["status"] in ["CALCULATED", "FINALIZED"]
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert is_valid_uuid(line.get("farm_id", "")), "line.farm_id must be a UUID"
        assert is_valid_uuid(line.get("contract_id", "")), "line.contract_id must be a UUID"
        assert isinstance(line["dozens_aa"], int) and line["dozens_aa"] >= 0
        assert isinstance(line["dozens_a"], int) and line["dozens_a"] >= 0
        assert isinstance(line["dozens_b"], int) and line["dozens_b"] >= 0
        assert line["total_dozens"] == line["dozens_aa"] + line["dozens_a"] + line["dozens_b"]
        assert isinstance(line["provisional_cents"], int)
        assert line.get("final_cents") is None or isinstance(line["final_cents"], int)
    assert isinstance(data["provisional_total_cents"], int)
    assert data.get("final_total_cents") is None or isinstance(data["final_total_cents"], int)
    assert data.get("actual_commodity_base_cents_per_dozen") is None or isinstance(
        data["actual_commodity_base_cents_per_dozen"], int
    )
    assert data.get("finalized_at") is None or is_iso8601_timestamp(data["finalized_at"])


def assert_lot_conservation(lot: dict):
    """PRD §2.9: received_dozens == remaining_dozens + packed_dozens + destroyed_dozens."""
    assert (
        lot["received_dozens"]
        == lot["remaining_dozens"] + lot["packed_dozens"] + lot["destroyed_dozens"]
    ), (
        f"lot conservation violated: received {lot['received_dozens']} != "
        f"remaining {lot['remaining_dozens']} + packed {lot['packed_dozens']} "
        f"+ destroyed {lot['destroyed_dozens']}"
    )


def assert_route_conservation(route: dict):
    """PRD §2.9: capacity_cases == committed_cases + available_cases."""
    assert route["capacity_cases"] == route["committed_cases"] + route["available_cases"], (
        f"route conservation violated: capacity {route['capacity_cases']} != "
        f"committed {route['committed_cases']} + available {route['available_cases']}"
    )
