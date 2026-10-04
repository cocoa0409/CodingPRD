"""Entity assertions and domain invariant checkers.

Each assert_* checks the system-managed fields (PRD §2.6) and the status
membership for the resource; tests assert domain values themselves.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}")
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_agency(data: dict):
    _assert_common(data)
    assert data["status"] == "ACTIVE"
    assert isinstance(data["bureau_code"], str) and data["bureau_code"]
    assert isinstance(data["name"], str) and data["name"]


def assert_building(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "UNDER_CONSTRUCTION")
    assert data["ownership_type"] in ("FEDERALLY_OWNED", "LEASED_STOCK")
    assert isinstance(data["total_sf"], int) and data["total_sf"] > 0
    assert isinstance(data["available_sf"], int)


def assert_space_requirement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "NEEDS_REVISION",
                              "VALIDATED", "SOLICITING", "AWARDED")
    assert data["delivery_method"] in ("STANDARD", "NEW_CONSTRUCTION")


def assert_lease_offer(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "UNDER_EVALUATION", "SELECTED",
                              "REJECTED", "WITHDRAWN")
    assert data["escalation_method"] in ("BASE_YEAR_STOP", "CPI_INDEXED")


def assert_lease(data: dict):
    _assert_common(data)
    assert data["status"] in ("AWARDED", "COMMENCED", "EXPIRING",
                              "EXPIRED", "SUCCEEDED")
    assert data["escalation_method"] in ("BASE_YEAR_STOP", "CPI_INDEXED")
    assert isinstance(data["term_months"], int) and data["term_months"] > 0
    assert isinstance(data["leased_sf"], int) and data["leased_sf"] > 0


def assert_expiration_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "OPTION_SELECTED", "EXECUTED", "CANCELLED")


def assert_oa(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
    assert data["pricing_source"] in ("LEASE_PASS_THROUGH", "OWNED_MARKET")
    assert isinstance(data["assigned_sf"], int) and data["assigned_sf"] > 0


def assert_rent_bill(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID")
    for field in ("shell_cents", "operating_cents", "tax_escalation_cents",
                  "ti_amortization_cents", "alteration_amortization_cents",
                  "lump_sum_charges_cents", "abatement_credit_cents",
                  "fee_cents", "service_credit_applied_cents", "total_cents",
                  "amount_paid_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert data[field] >= 0, f"{field} must be non-negative"


def assert_alteration(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "ESTIMATED", "APPROVED",
                              "COMPLETED", "CANCELLED")
    assert data["lump_charge_status"] in ("NONE", "PENDING", "BILLED", "REVERSED")


def assert_service_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED", "VERIFIED")
    assert data["category"] in ("MAINTENANCE", "SECURITY", "CLEANING")
    assert data["severity"] in ("CRITICAL", "ROUTINE")
    assert data["sla_hours"] in (24, 72)


def assert_survey(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECORDED", "FINALIZED")
    assert data["method"] in ("SPACE_BASED", "HEADCOUNT_BASED")


def assert_reduction_action(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "APPROVED", "EXECUTED")
