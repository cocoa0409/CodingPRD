"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            "version must be an integer >= 1"


def assert_association(data: dict):
    _assert_common(data)
    assert isinstance(data["association_code"], str) and data["association_code"]
    assert data["consolidation_state"] in ("ACTIVE", "MERGING", "MERGED")
    assert isinstance(data["membership_dues_cents"], int)
    assert isinstance(data["late_fee_tier1_cents"], int)
    assert isinstance(data["late_fee_tier2_cents"], int)
    assert isinstance(data["sanction_credit_cap_cents"], int)


def assert_member(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("association_id", "")), "association_id must be a UUID"
    assert data["membership_state"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["mls_access_state"] in ("ENABLED", "DISABLED")
    assert isinstance(data["sanction_credit_balance_cents"], int)
    assert data["sanction_credit_balance_cents"] >= 0
    assert isinstance(data["strikes_12m"], int) and data["strikes_12m"] >= 0


def assert_office(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert is_valid_uuid(data.get("broker_member_id", "")), "broker_member_id must be a UUID"


def assert_dues_period(data: dict):
    _assert_common(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("OPEN", "BILLED", "RECONCILED")


def assert_dues_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["status"] in ("PENDING", "PAID", "WAIVED")
    assert data["amount_due_cents"] == (
        data["base_amount_cents"] + data["late_fee_cents"] - data["credit_applied_cents"]
    ), "amount_due must equal base + late fee - credit applied"


def assert_listing(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "ACTIVE", "PENDING", "SOLD", "WITHDRAWN", "EXPIRED", "CANCELLED")
    assert data["accuracy_flag"] in ("CLEAN", "FLAGGED")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["offer_comp_cents"], int)


def assert_status_change(data: dict):
    _assert_common(data)
    assert isinstance(data["late_by_hours"], int) and data["late_by_hours"] >= 0
    assert data["to_status"] in (
        "DRAFT", "ACTIVE", "PENDING", "SOLD", "WITHDRAWN", "EXPIRED", "CANCELLED")


def assert_citation(data: dict):
    _assert_common(data)
    assert data["rule_code"] in (
        "LATE_LISTING", "LATE_STATUS", "INACCURACY", "CLEAR_COOP", "COMP_OFFER", "FEED_ABUSE")
    assert data["status"] in ("OPEN", "HEARING_PENDING", "PAID", "WAIVED", "ESCALATED")
    assert data["source"] in ("STAFF", "AUTO_LATE_LISTING", "AUTO_LATE_STATUS")
    assert isinstance(data["fine_amount_cents"], int) and data["fine_amount_cents"] > 0
    assert isinstance(data["hearing_requested"], bool)


def assert_fine_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["fine_amount_cents"], int) and data["fine_amount_cents"] > 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_ethics_case(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "FILED", "GRIEVANCE_SCREENING", "DISMISSED", "HEARING_SCHEDULED",
        "HEARD", "DECIDED", "APPEALED", "FINAL")
    assert data["complainant_member_id"] != data["respondent_member_id"]


def assert_arbitration_case(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "FILED", "MEDIATION_OFFERED", "MEDIATED", "ARBITRATION_SCHEDULED",
        "HEARD", "AWARDED")
    assert isinstance(data["claim_amount_cents"], int) and data["claim_amount_cents"] > 0
    assert isinstance(data["award_amount_cents"], int)
    assert 0 <= data["award_amount_cents"] <= data["claim_amount_cents"]


def assert_hearing_panel(data: dict):
    _assert_common(data)
    assert data["case_type"] in ("CITATION", "ETHICS", "ARBITRATION")
    assert data["status"] in ("CONVENED", "HEARING_HELD", "DECIDED")
    assert isinstance(data["selected_member_ids"], list)
    assert len(data["selected_member_ids"]) == 3


def assert_data_license(data: dict):
    _assert_common(data)
    assert data["scope"] in ("IDX", "VOW", "BACKOFFICE")
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["feed_sync_state"] in ("CURRENT", "STALE")


def assert_policy_revision(data: dict):
    _assert_common(data)
    assert data["comp_display_mode"] in ("COMP_DISPLAY_ON", "COMP_DISPLAY_OFF")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "SUPERSEDED")


def assert_consolidation_event(data: dict):
    """ConsolidationEvent carries only id + created_at among common fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ConsolidationEvent must not carry a version field"
    assert "updated_at" not in data, "ConsolidationEvent must not carry updated_at"
    assert data["status"] in ("SCHEDULED", "EXECUTED", "CANCELLED")
    assert data["survivor_association_id"] != data["absorbed_association_id"]
