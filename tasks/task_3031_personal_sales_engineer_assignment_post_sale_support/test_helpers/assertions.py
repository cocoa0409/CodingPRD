"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Every entity carries id + created_at + updated_at + version (PRD 2.10)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_engineer(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "OFFBOARDED"]
    assert data["region"] in ["MIDWEST", "SOUTH", "WEST", "EAST"]
    assert data["seniority_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert isinstance(data["max_book_size"], int) and data["max_book_size"] >= 0
    assert isinstance(data["active_book_size"], int) and data["active_book_size"] >= 0
    assert isinstance(data["certified_family_count"], int)
    assert isinstance(data["lifetime_commission_cents"], int)


def assert_customer(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "ACTIVE", "CLOSED"]
    assert data["account_tier"] in ["STANDARD", "PREMIUM", "STUDIO"]
    assert data["tech_support_entitlement"] in ["NONE", "BASIC", "EXTENDED"]
    assert len(data["home_state"]) == 2
    assert isinstance(data["purchased_instrument_count"], int)
    assert isinstance(data["lifetime_gear_credit_cents"], int)
    assert data["assigned_engineer_id"] is None or is_valid_uuid(data["assigned_engineer_id"])


def assert_assignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING_ACCEPT", "ACTIVE", "ENDED"]
    assert data["reason_code"] in [
        "NEW_ACCOUNT", "PERMANENT_TRANSFER", "REGION_CHANGE", "TEMPORARY_COVERAGE",
    ]
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["commission_share_bps"], int)
    if data["status"] == "PENDING_ACCEPT":
        assert data.get("assigned_at") is None
    if data["reason_code"] == "TEMPORARY_COVERAGE":
        assert data.get("effective_until") is not None
    else:
        assert data.get("effective_until") is None


def assert_quote(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "RESERVED", "REJECTED", "CANCELLED"]
    assert data["package_type"] in ["SYSTEM_PACKAGE", "INSTRUMENT_ONLY", "ACCESSORY_ONLY"]
    assert isinstance(data["bundle_ready"], bool)
    assert isinstance(data["dependency_closure_size"], int) and data["dependency_closure_size"] >= 0
    assert isinstance(data["gross_subtotal_cents"], int) and data["gross_subtotal_cents"] >= 0
    if data["status"] == "RESERVED":
        assert data.get("reserved_at") is not None
    else:
        assert data.get("reserved_at") is None


def assert_quote_line(data: dict):
    assert_common_fields(data)
    assert data["product_family"] in [
        "GUITAR", "AMPLIFIER", "INTERFACE", "MICROPHONE", "EFFECT_PEDAL", "ACCESSORY",
    ]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["is_anchor"], bool)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["bundle_discount_bps"], int)
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0


def assert_instrument_unit(data: dict):
    assert_common_fields(data)
    assert data["setup_status"] in [
        "PENDING_SETUP", "IN_SETUP", "SETUP_COMPLETE", "INSPECTED", "SHIPPED",
    ]
    assert data["inspection_overall"] in ["PASS", "CONDITIONAL", "FAIL"]
    assert isinstance(data["modified_since_setup"], bool)
    if data["setup_status"] == "SHIPPED":
        assert data.get("shipped_at") is not None


def assert_warranty_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "PENDING", "ACTIVE", "CLAIM_OPEN", "REPAIR_IN_PROGRESS", "EXPIRED", "VOIDED",
    ]
    assert data["term_months"] in [12, 24, 36]
    assert isinstance(data["repair_rounds_used"], int) and data["repair_rounds_used"] >= 0
    assert isinstance(data["remaining_repair_rounds"], int)
    assert data["remaining_repair_rounds"] == max(0, 3 - data["repair_rounds_used"])


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING_ROUTING", "ROUTED", "CLOSED"]
    assert isinstance(data["reported_fault"], str) and len(data["reported_fault"]) > 0
    if data["status"] == "PENDING_ROUTING":
        assert data.get("routed_at") is None


def assert_service_center(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "SUSPENDED"]
    assert data["region"] in ["MIDWEST", "SOUTH", "WEST", "EAST"]
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 0
    assert isinstance(data["open_ticket_count"], int) and data["open_ticket_count"] >= 0
    assert data["open_ticket_count"] <= data["capacity_slots"], (
        "open_ticket_count must never exceed capacity_slots"
    )
    assert isinstance(data["accepted_families"], list)


def assert_support_ticket(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "IN_TRIAGE", "ESCALATED", "RESOLVED"]
    assert data["channel"] in ["PHONE", "EMAIL", "CHAT"]
    assert data["required_entitlement"] in ["NONE", "BASIC", "EXTENDED"]
    assert isinstance(data["escalation_seq"], int) and data["escalation_seq"] >= 0
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0


def assert_product(data: dict):
    assert_common_fields(data)
    assert data["product_family"] in [
        "GUITAR", "AMPLIFIER", "INTERFACE", "MICROPHONE", "EFFECT_PEDAL", "ACCESSORY",
    ]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["requires_certification"], bool)
    assert isinstance(data["in_catalog"], bool)


def assert_backorder(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "PREORDER_PENDING", "ALLOCATION_SWEEP", "PARTIALLY_FILLED",
        "BOARD_FILLED", "RECEIVING", "SHIPPED", "CANCELLED",
    ]
    assert isinstance(data["units_requested"], int) and data["units_requested"] >= 0
    assert isinstance(data["units_filled"], int) and data["units_filled"] >= 0
    assert isinstance(data["overcommit_estimate_units"], int)
    assert isinstance(data["alloc_sequence"], int) and data["alloc_sequence"] >= 1
    assert data["eta_deadline"] is not None


def assert_gear_exchange(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "TRIAL_ACTIVE", "RETURN_REQUESTED", "EXCHANGED", "DENIED", "CANCELLED",
    ]
    assert data["reason"] in ["TONE_MISMATCH", "DEFECT_DOA", "WRONG_MODEL", "CHANGED_MIND"]
    assert isinstance(data["restocking_fee_bps"], int)
    assert isinstance(data["restocking_fee_cents"], int)
    assert isinstance(data["refund_credit_cents"], int)


def assert_certification_attempt(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED", "EXPIRED"]
    assert data["product_family"] in [
        "GUITAR", "AMPLIFIER", "INTERFACE", "MICROPHONE", "EFFECT_PEDAL", "ACCESSORY",
    ]
    assert isinstance(data["attempt_index"], int) and data["attempt_index"] >= 1
    assert isinstance(data["eligible_to_retake"], bool)
    if data["status"] == "PASSED":
        assert data["certified"] is True
        assert data.get("assessed_at") is not None
        assert data.get("expires_at") is not None
    if data["status"] == "SCHEDULED":
        assert data.get("score_pct") is None


def assert_escalation_ledger_entry(data: dict):
    assert_common_fields(data)
    assert data["event_type"] in ["SERVICE_DEPARTMENT_ESCALATION", "ESCALATION_WITHDRAWN"]
    assert isinstance(data["escalation_seq"], int) and data["escalation_seq"] >= 1
    assert data.get("posted_at") is not None


def assert_book_occupancy_reconciles(engineer: dict, active_assignment_count: int):
    """The occupancy counter must equal the number of ACTIVE rows (PRD 2.8)."""
    assert engineer["active_book_size"] == active_assignment_count, (
        f"active_book_size {engineer['active_book_size']} != "
        f"ACTIVE assignment rows {active_assignment_count}"
    )


def assert_coverage_conserved(credit_balance_cents: int, line_total_cents: int):
    """A completed exchange leaves the gear-credit balance at the full line
    total: the refund credit is added and the restocking fee is credited back as
    a fee offset in the same mutation (PRD 3.8)."""
    assert credit_balance_cents == line_total_cents, (
        f"gear-credit balance {credit_balance_cents} != line total "
        f"{line_total_cents}"
    )


def assert_pool_conserved(granted_units, pool_units: int):
    """The final allocation walk depletes the pool exactly (PRD 3.5).

    ``granted_units`` is the grant the final walk made to the claim being
    finalized; it can never exceed the shared pool, and it never overdraws it.
    """
    assert granted_units <= pool_units, (
        f"allocated {granted_units} units from a pool of {pool_units}"
    )