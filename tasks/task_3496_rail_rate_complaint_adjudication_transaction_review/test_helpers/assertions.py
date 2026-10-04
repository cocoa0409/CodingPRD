"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3)."""
import re

from prd_bench_local_runner.testing import is_valid_uuid

# created_at / updated_at / api_request_timestamp render with exactly three
# fractional digits (PRD §2.4, §2.2).
_ISO8601_3DP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_identity_block(data: dict):
    """Common identity block: dashed UUID id, 3-fractional-digit timestamps, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a dashed UUID, got {data.get('id')!r}"
    assert _ISO8601_3DP_RE.match(data.get("created_at", "") or ""), (
        f"created_at must be ISO 8601 UTC with 3 fractional digits, got {data.get('created_at')!r}")
    assert _ISO8601_3DP_RE.match(data.get("updated_at", "") or ""), (
        f"updated_at must be ISO 8601 UTC with 3 fractional digits, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}")


def _assert_domain_timestamp(value):
    """Domain timestamps render exactly as the logical clock read (PRD §2.4);
    assert only that a present value is a non-empty string."""
    assert isinstance(value, str) and len(value) > 0, (
        f"domain timestamp must be a non-empty string, got {value!r}")


def assert_carrier(data: dict):
    assert_identity_block(data)
    assert isinstance(data["carrier_code"], str) and data["carrier_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["carrier_class"] in ("I", "II", "III")
    assert isinstance(data["base_route_miles"], int) and data["base_route_miles"] >= 1
    assert isinstance(data["active_route_miles"], int)
    assert isinstance(data["abandoned_route_miles"], int)
    assert isinstance(data["trail_use_route_miles"], int)
    assert data["revenue_adequacy_status"] in ("UNDETERMINED", "ADEQUATE", "INADEQUATE")
    assert data["compliance_standing"] in ("GOOD", "PROBATION")
    assert isinstance(data["reparation_exposure_cents"], int)


def assert_finding(data: dict):
    assert_identity_block(data)
    assert isinstance(data["carrier_id"], str) and data["carrier_id"]
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["operating_revenue_cents"], int)
    assert isinstance(data["operating_expense_cents"], int)
    assert isinstance(data["net_investment_cents"], int)
    assert isinstance(data["current_year_roi_bps"], int)
    assert isinstance(data["five_year_avg_roi_bps"], int)
    assert data["finding"] in ("ADEQUATE", "INADEQUATE")


def assert_rate_complaint(data: dict):
    assert_identity_block(data)
    assert isinstance(data["shipper_id"], str) and data["shipper_id"]
    assert isinstance(data["carrier_id"], str) and data["carrier_id"]
    assert isinstance(data["commodity"], str)
    assert isinstance(data["challenged_rate_cents_per_ton"], int)
    assert isinstance(data["alleged_variable_cost_cents_per_ton"], int)
    assert isinstance(data["annual_tons"], int)
    assert isinstance(data["relief_sought_cents"], int)
    assert isinstance(data["contested_fiscal_year"], int)
    assert data["track"] in ("THREE_BENCHMARK", "SIMPLIFIED_SAC", "FULL_SAC")
    assert isinstance(data["alleged_rvc_ratio"], (int, float))
    assert data["adjudicated_rvc_ratio"] is None or isinstance(
        data["adjudicated_rvc_ratio"], (int, float))
    assert data["market_dominance"] in ("UNDETERMINED", "PRESENT", "ABSENT")
    assert data["status"] in (
        "FILED", "EVIDENTIARY_PHASE", "DECIDED", "REOPENED", "DISMISSED", "CLOSED")
    assert data["decision_outcome"] in (None, "UPHELD", "REJECTED", "DISMISSED")
    assert data["prescribed_rate_cents_per_ton"] is None or isinstance(
        data["prescribed_rate_cents_per_ton"], int)
    assert data["relief_granted_cents"] is None or isinstance(
        data["relief_granted_cents"], int)
    assert isinstance(data["award_granted_cents"], int)
    assert isinstance(data["award_paid_cents"], int)
    assert isinstance(data["award_outstanding_cents"], int)
    assert data["award_status"] in (
        "NONE", "GRANTED", "PARTIALLY_PAID", "PAID", "REVERSED")


def assert_evidence_submission(data: dict):
    assert_identity_block(data)
    assert isinstance(data["rate_complaint_id"], str) and data["rate_complaint_id"]
    assert data["submission_type"] in ("SAC_STUDY", "THREE_BENCHMARK_PACKET", "REBUTTAL")
    assert data["submitted_by_party"] in ("SHIPPER", "CARRIER")
    assert isinstance(data["reference_rate_cents_per_ton"], int)
    assert isinstance(data["verified_variable_cost_cents_per_ton"], int)
    assert data["review_status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "SUPERSEDED")


def assert_service_complaint(data: dict):
    assert_identity_block(data)
    assert isinstance(data["shipper_id"], str) and data["shipper_id"]
    assert isinstance(data["carrier_id"], str) and data["carrier_id"]
    assert data["issue_type"] in ("DELAY", "EMBARGO", "CAR_SUPPLY", "FAILURE_TO_DELIVER")
    assert isinstance(data["territory_code"], str)
    assert data["status"] in ("OPEN", "ESCALATED", "RESOLVED")


def assert_eso(data: dict):
    assert_identity_block(data)
    assert isinstance(data["carrier_id"], str) and data["carrier_id"]
    assert isinstance(data["service_complaint_id"], str) and data["service_complaint_id"]
    assert isinstance(data["directive"], str)
    _assert_domain_timestamp(data["issued_at"])
    _assert_domain_timestamp(data["expires_at"])
    assert data["status"] in ("ACTIVE", "EXPIRED", "LIFTED")


def assert_merger_application(data: dict):
    assert_identity_block(data)
    assert isinstance(data["acquiring_carrier_id"], str) and data["acquiring_carrier_id"]
    assert isinstance(data["target_carrier_id"], str) and data["target_carrier_id"]
    assert isinstance(data["transaction_value_cents"], int)
    assert isinstance(data["competition_preservation_score"], int)
    assert isinstance(data["service_reliability_score"], int)
    assert isinstance(data["shipper_impact_score"], int)
    assert isinstance(data["public_interest_score"], (int, float))
    _assert_domain_timestamp(data["comment_close_at"])
    assert isinstance(data["service_review_hold"], bool)
    assert data["status"] in (
        "COMMENT_PERIOD", "APPROVED", "APPROVED_WITH_CONDITIONS", "REJECTED")
    assert isinstance(data["conditions_imposed"], list)


def assert_service_assurance_plan(data: dict):
    assert_identity_block(data)
    assert isinstance(data["merger_application_id"], str) and data["merger_application_id"]
    assert isinstance(data["plan_name"], str)
    assert isinstance(data["commitments"], list)
    assert data["status"] in ("DRAFT", "MONITORING", "MOOT")


def assert_abandonment_application(data: dict):
    assert_identity_block(data)
    assert isinstance(data["carrier_id"], str) and data["carrier_id"]
    assert isinstance(data["line_segment_ref"], str) and data["line_segment_ref"]
    assert isinstance(data["segment_miles"], int) and data["segment_miles"] >= 1
    assert data["public_convenience_finding"] in (None, "SERVED", "NOT_SERVED")
    assert data["status"] in (
        "UNDER_REVIEW", "GRANTED", "DENIED", "TRAIL_PENDING",
        "TRAIL_CONVERTED", "CONSUMMATED")
    assert data["nitu_expires_at"] is None or isinstance(data["nitu_expires_at"], str)


def assert_petition(data: dict):
    assert_identity_block(data)
    assert isinstance(data["shipper_id"], str) and data["shipper_id"]
    assert isinstance(data["incumbent_carrier_id"], str) and data["incumbent_carrier_id"]
    assert isinstance(data["interchange_code"], str) and data["interchange_code"]
    assert isinstance(data["facility_distance_miles"], int)
    assert isinstance(data["evidence_service_complaint_id"], str)
    assert isinstance(data["service_start_date"], str)
    assert isinstance(data["service_end_date"], str)
    assert data["status"] in ("FILED", "GRANTED", "DENIED", "TERMINATED")


def assert_award_ledger_invariant(complaint: dict):
    """Pinned ledger identity: outstanding == granted - paid (PRD §3.4)."""
    assert complaint["award_outstanding_cents"] == (
        complaint["award_granted_cents"] - complaint["award_paid_cents"]), (
        "award_outstanding_cents must equal award_granted_cents - award_paid_cents: "
        f"{complaint['award_outstanding_cents']} != "
        f"{complaint['award_granted_cents']} - {complaint['award_paid_cents']}")


def assert_mileage_conserved(carrier: dict):
    """Mileage ledger: active + abandoned + trail_use == base (PRD §2.9)."""
    total = (carrier["active_route_miles"] + carrier["abandoned_route_miles"]
             + carrier["trail_use_route_miles"])
    assert total == carrier["base_route_miles"], (
        f"mileage not conserved: {total} != base {carrier['base_route_miles']}")
