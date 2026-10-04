"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Account.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["account_type"] in ("FAMILY", "BUSINESS")
    assert data["account_status"] in ("OPEN", "SUSPENDED", "CLOSED")
    assert isinstance(data["tax_id_last4"], str) and len(data["tax_id_last4"]) == 4
    assert data["credit_class"] in (
        "CLASS_A",
        "CLASS_B",
        "CLASS_C",
        "CLASS_D",
        "BLOCKED",
    )
    assert 0 <= data["payment_history_score"] <= 1000
    assert isinstance(data["active_line_count"], int) and data["active_line_count"] >= 0
    assert isinstance(data["reserved_mdn_count"], int) and data["reserved_mdn_count"] >= 0
    assert isinstance(data["deposit_required_cents"], int)
    assert isinstance(data["promo_credited_cents"], int)
    assert isinstance(data["promo_clawed_back_cents"], int)
    assert isinstance(data["net_promo_credit_cents"], int)


def assert_account_ledger_invariant(data: dict):
    """The promotional ledger is conserved: credited minus clawed-back."""
    assert (
        data["net_promo_credit_cents"]
        == data["promo_credited_cents"] - data["promo_clawed_back_cents"]
    ), "net_promo_credit_cents must equal promo_credited_cents minus promo_clawed_back_cents"


def assert_subscriber_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "SubscriberLine.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data["account_id"]), "account_id must be a valid UUID"
    assert isinstance(data["mdn"], str) and len(data["mdn"]) == 10
    assert data["billing_mode"] in ("PREPAID", "POSTPAID")
    assert data["service_status"] in (
        "PROVISIONED",
        "ACTIVE",
        "SUSPENDED",
        "CANCELLED",
    )
    assert data["number_status"] in (
        "UNASSIGNED",
        "RESERVED",
        "PORTED_IN",
        "ASSIGNED",
        "RECLAIMED",
    )
    assert data["port_protection_status"] in ("UNPROTECTED", "PROTECTED")
    assert data["promo_eligibility_state"] in (
        "INELIGIBLE",
        "PROVISIONAL_ELIGIBLE",
        "VESTED",
        "CLAWED_BACK",
    )
    assert isinstance(data["loyalty_tenure_months"], int)
    assert isinstance(data["retention_cycle_count"], int)


def assert_port_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "PortRequest.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["request_state"] in (
        "DRAFT",
        "PENDING",
        "REJECTED",
        "RESUBMITTED",
        "ACCEPTED_PENDING_CUTOVER",
        "PORTED",
        "CANCELLED",
    )
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0
    assert isinstance(data["rejections"], list)
    assert data["rejection_count"] == len(data["rejections"]), (
        "rejection_count must equal the number of entries in rejections"
    )
    assert data["transfer_pin"] == str(data["transfer_pin"])


def assert_promo_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "PromoCreditSchedule.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["schedule_state"] in ("PROVISIONAL", "ACTIVE", "VESTED", "CLAWED_BACK")
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["vested_total_cents"], int)
    assert isinstance(data["cycles_elapsed"], int)
    assert isinstance(data["installment_months"], int)
    assert isinstance(data["retention_requirement_cycles"], int)


def assert_promo_schedule_invariants(data: dict):
    """Provisional total is the base credit plus 1000 per billable month."""
    billable = min(data["installment_months"], data["retention_requirement_cycles"])
    assert data["provisional_total_cents"] == 20000 + 1000 * billable
    assert data["vested_total_cents"] == 1000 * data["cycles_elapsed"]


def assert_device_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "DeviceInstallmentPlan.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["plan_state"] in ("QUOTED", "ACTIVE", "UPGRADE_ELIGIBLE", "CONVERTED")
    assert isinstance(data["device_price_cents"], int)
    assert isinstance(data["down_payment_cents"], int)
    assert isinstance(data["monthly_installment_cents"], int)
    assert isinstance(data["remaining_balance_cents"], int)
    assert isinstance(data["trade_in_credit_cents"], int)
    assert isinstance(data["installment_months"], int)


def assert_device_plan_invariants(data: dict):
    """Financed balance floors at zero; the recurring installment is floored."""
    financed = max(data["device_price_cents"] - data["down_payment_cents"], 0)
    assert data["remaining_balance_cents"] >= 0
    if data["installment_months"] > 0:
        assert (
            data["monthly_installment_cents"] == financed // data["installment_months"]
        ), "monthly_installment_cents must be the floor of financed balance over months"


def assert_trade_in_assessment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "TradeInAssessment.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["assessment_state"] in ("SUBMITTED", "GRADED")
    if data["declared_condition"] is not None:
        assert data["declared_condition"] in (
            "FLAWLESS",
            "GOOD",
            "FAIR",
            "POOR",
            "BROKEN",
        )
    assert isinstance(data["estimated_credit_cents"], int)
    assert isinstance(data["final_credit_cents"], int)
    assert isinstance(data["grade_delta_cents"], int)
    assert data["parent_plan_id"] == data["installment_plan_id"], (
        "parent_plan_id must mirror installment_plan_id"
    )


def assert_number_reservation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "NumberReservation.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["reservation_state"] in ("HELD", "COMMITTED", "EXPIRED")
    assert isinstance(data["mdn"], str) and len(data["mdn"]) == 10
    assert isinstance(data["pool_code"], str) and len(data["pool_code"]) > 0
    assert is_iso8601_timestamp(data["reserved_at"])
    assert is_iso8601_timestamp(data["reserved_until"])


def assert_migration_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "MigrationRequest.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["migration_state"] in (
        "DRAFT",
        "ELIGIBILITY_CHECK",
        "BLOCKED",
        "APPROVED",
        "CUTOVER_SCHEDULED",
        "CUTOVER_COMPLETE",
    )
    assert data["source_billing_mode"] in ("PREPAID",)
    assert data["target_billing_mode"] in ("POSTPAID",)
    assert isinstance(data["prepaid_balance_cents"], int)
    assert isinstance(data["device_balance_cents"], int)
    assert isinstance(data["proration_credit_cents"], int)
    assert data["proration_credit_cents"] >= 0


def assert_line_addition_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "LineAdditionRequest.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["request_state"] in ("SUBMITTED", "APPROVED", "DECLINED")
    assert 1 <= data["line_count"] <= 10
    assert isinstance(data["required_deposit_cents"], int)
    assert data["parent_account_id"] == data["account_id"], (
        "parent_account_id must mirror account_id"
    )


def assert_port_protection_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "PortProtectionCase.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["case_state"] in ("REQUESTED", "ACTIVE", "CLEARED", "DENIED")
    assert data["protection_type"] in ("ACCOUNT_PIN", "PORT_FREEZE", "FRAUD_HOLD")
    assert isinstance(data["verified_identity"], bool)
    assert isinstance(data["reason_code"], str)


def assert_rejection_code_catalog(data: dict):
    """Static reference table: only id and created_at, no updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), "RejectionCodeCatalog.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["rejection_code"], str) and len(data["rejection_code"]) > 0
    assert isinstance(data["guidance_text"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["resubmission_allowed"], bool)
    assert isinstance(data["retry_after_hours"], int)
    assert data["requires_action_by"] in (
        "CUSTOMER",
        "LOSING_CARRIER",
        "GAINING_CARRIER",
    )


def assert_system_config(data: dict):
    assert isinstance(data["ops_run_epoch"], int)
    assert is_iso8601_timestamp(data["last_ops_run_at"])
    assert is_iso8601_timestamp(data["last_line_cancellation_deadline"])
    assert isinstance(data["line_cancellation_grace_hours"], int)
    assert isinstance(data["promo_window_buffer_days"], int)