"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

COMMON_MUTABLE_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_FIELDS = ("id", "created_at")


def assert_common_fields(data: dict, entity: str = "record"):
    """id / created_at / updated_at / version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer starting at 1"


def assert_append_only_shape(data: dict, entity: str = "record"):
    """An append-only record carries id and created_at and neither of the two
    mutation-tracking fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, f"{entity} must not echo updated_at"
    assert "version" not in data, f"{entity} must not echo version"


def assert_prescription(data: dict):
    assert_common_fields(data, "Prescription")
    assert data["voltage_class"] in (
        "DISTRIBUTION_4KV", "DISTRIBUTION_12KV", "DISTRIBUTION_35KV",
        "SUBTRANSMISSION_69KV", "TRANSMISSION_115KV")
    assert data["growth_zone"] in ("SLOW", "MODERATE", "RAPID")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    assert isinstance(data["ground_to_sky"], bool)
    assert isinstance(data["herbicide_allowed"], bool)


def assert_circuit(data: dict):
    assert_common_fields(data, "Circuit")
    assert isinstance(data["circuit_code"], str) and data["circuit_code"]
    assert data["trim_status"] in (
        "NOT_SCHEDULED", "SCHEDULED", "ACTIVE_CYCLE", "CYCLE_AT_RISK", "CYCLE_COMPLETE")
    assert data["reliability_tier"] in ("TIER_NORMAL", "TIER_ELEVATED", "TIER_CRITICAL")
    assert isinstance(data["cycle_months"], int)
    assert isinstance(data["tree_caused_outage_count_36mo"], int)


def assert_work_plan(data: dict):
    assert_common_fields(data, "WorkPlan")
    assert data["status"] in (
        "DRAFT", "RELEASED", "IN_PROGRESS", "SUSPENDED", "COMPLETED", "CANCELLED")
    assert isinstance(data["planned_unit_count"], int)
    assert isinstance(data["completed_unit_count"], int)
    assert isinstance(data["committed_cents"], int)


def assert_work_order(data: dict):
    assert_common_fields(data, "WorkOrder")
    assert data["execution_status"] in (
        "PLANNED", "MAPPED", "RELEASED", "IN_PROGRESS", "STORM_PREEMPTED",
        "COMPLETED", "CANCELLED")
    assert data["billing_status"] in (
        "NOT_BILLABLE", "BILLABLE", "LINE_DRAFTED", "SUBMITTED", "APPROVED",
        "DISPUTED", "SETTLED")
    assert data["billing_method"] in ("UNIT_PRICE", "TIME_AND_MATERIALS")
    assert isinstance(data["actual_units_completed"], int)
    assert isinstance(data["refusal_blocked_unit_count"], int)


def assert_crew(data: dict):
    assert_common_fields(data, "Crew")
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "STORM_DEPLOYED")
    assert data["crew_type"] in ("BUCKET", "CLIMBING", "MANUAL", "HERBICIDE", "STORM")


def assert_crew_assignment(data: dict):
    assert_common_fields(data, "CrewAssignment")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "RELEASED", "PREEMPTED")


def assert_production_entry(data: dict):
    assert_append_only_shape(data, "ProductionEntry")
    assert isinstance(data["units_trimmed"], int)
    assert isinstance(data["entry_cents"], int)


def assert_outage_record(data: dict):
    assert_append_only_shape(data, "OutageRecord")
    assert data["cause_code"] in ("TREE_GROWN_IN", "TREE_FELL_ON", "NON_TREE")


def assert_customer_notification(data: dict):
    assert_common_fields(data, "CustomerNotification")
    assert data["status"] in (
        "PENDING", "NOTIFIED", "ACKNOWLEDGED", "REFUSED", "ESCALATED", "FINAL_REFUSAL")
    assert isinstance(data["refusal_round"], int)


def assert_hazard_tree(data: dict):
    assert_common_fields(data, "HazardTree")
    assert data["status"] in (
        "IDENTIFIED", "ASSESSED", "APPROVED_REMOVAL", "DECLINED", "DEFERRED", "REMOVED")
    assert isinstance(data["strike_potential"], bool)
    assert isinstance(data["removal_required"], bool)


def assert_herbicide_permit(data: dict):
    assert_common_fields(data, "HerbicidePermit")
    assert data["status"] in (
        "REQUESTED", "APPROVED", "ACTIVE", "DENIED", "REVOKED", "EXPIRED")


def assert_storm_event(data: dict):
    assert_common_fields(data, "StormEvent")
    assert data["status"] in ("DECLARED", "ACTIVE", "DEMOBILIZING", "CLOSED")
    assert isinstance(data["reassigned_crew_count"], int)
    assert isinstance(data["preempted_assignment_count"], int)


def assert_billing_line(data: dict):
    assert_common_fields(data, "BillingLine")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "DISPUTED", "PAID", "VOID")
    for money in ("gross_cents", "retainage_cents", "storm_premium_cents",
                  "net_payable_cents", "mobilization_credit_cents", "final_payable_cents"):
        assert isinstance(data[money], int), f"BillingLine.{money} must be whole cents"


def assert_settlement_waterfall(line: dict):
    """The six-step waterfall must be internally consistent (PRD §3.9)."""
    assert line["net_payable_cents"] == (
        line["gross_cents"] - line["retainage_cents"] + line["storm_premium_cents"]), \
        "net_payable_cents must equal gross - retainage + storm premium"
    assert line["final_payable_cents"] == (
        line["net_payable_cents"] - line["mobilization_credit_cents"]), \
        "final_payable_cents must equal net_payable_cents - mobilization_credit_cents"
    expected_credit = 25_000 if line["net_payable_cents"] >= 1_000_000 else 0
    assert line["mobilization_credit_cents"] == expected_credit, \
        "mobilization credit is keyed on the net tier"


def assert_no_version_echo(data: dict, entity: str = "record"):
    assert "version" not in data, f"{entity} must not echo version"
