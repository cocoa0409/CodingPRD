"""Entity shape assertions, instant comparison and domain invariant checks."""
import math

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    ASSESSMENT_STATUSES,
    ASSIGNMENT_STATUSES,
    CLINIC_POSTURES,
    COMPLAINT_CODES,
    CREDENTIALS,
    QUEUE_STATUSES,
    REVIEW_STATUSES,
    SERVICE_PRICES_CENTS,
    SUMMARY_STATUSES,
    THERAPY_CLASSES,
    VISIT_BILLING_STATUSES,
    VISIT_CLINICAL_STATUSES,
)


# ---------------------------------------------------------------------------
# Instants and identity
# ---------------------------------------------------------------------------

def assert_instant_equal(actual, expected):
    """Compare two ISO 8601 UTC instants by value, not by string width."""
    assert actual is not None, f"expected instant {expected!r}, got None"
    assert is_iso8601_timestamp(actual), f"{actual!r} is not an ISO 8601 UTC instant"
    assert canonical_instant(actual) == canonical_instant(expected), \
        f"{actual!r} != {expected!r} as instants"


def assert_common_fields(data: dict, expected_version: int = None):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"
    if expected_version is not None:
        assert data["version"] == expected_version, \
            f"expected version {expected_version}, got {data['version']}"


def assert_freshly_created(data: dict):
    """A fresh row starts at version 1 with updated_at equal to created_at."""
    assert_common_fields(data, expected_version=1)
    assert canonical_instant(data["updated_at"]) == canonical_instant(data["created_at"]), \
        "updated_at must equal created_at on a freshly created row"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------

def assert_state_rule(data: dict):
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"] == data["state_code"].upper()
    assert 0 <= data["chart_review_sample_pct"] <= 100
    assert data["review_deadline_hours"] >= 1
    assert isinstance(data["collaborating_physician_required"], bool)
    assert data["min_independent_practice_age_months"] >= 0
    assert isinstance(data["controlled_rx_allowed"], bool)
    assert data["max_supervised_clinicians_per_physician"] >= 1


def assert_protocol(data: dict):
    assert_common_fields(data)
    assert data["complaint_code"] in COMPLAINT_CODES
    assert data["max_age_months"] > data["min_age_months"]
    assert data["base_price_cents"] > 0
    assert data["acuity_tier"] in (1, 2, 3)
    assert isinstance(data["red_flag_codes"], list)
    assert isinstance(data["requires_cosign"], bool)
    assert isinstance(data["allowed_state_codes"], list) and data["allowed_state_codes"]


def assert_clinic(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["open_status"] in CLINIC_POSTURES
    for counter in ("min_clinicians_required", "appointment_slots_per_hour",
                    "walk_in_queue_capacity", "on_duty_clinician_count",
                    "waiting_count", "posted_wait_minutes"):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    assert "last_realized_wait_minutes" in data


def assert_physician(data: dict):
    assert_common_fields(data)
    assert isinstance(data["licensed_state_codes"], list) and data["licensed_state_codes"]
    assert data["max_supervised_clinicians"] >= 1
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["current_supervised_count"], int)


def assert_clinician(data: dict):
    assert_common_fields(data)
    assert data["credential"] in CREDENTIALS
    assert isinstance(data["license_state_code"], str)
    assert isinstance(data["float_eligible"], bool)
    assert isinstance(data["scope_hold"], bool)
    assert isinstance(data["active_assignment_count"], int)


def assert_patient(data: dict):
    assert_common_fields(data)
    assert isinstance(data["date_of_birth"], str) and "T" not in data["date_of_birth"], \
        "date_of_birth is an ISO calendar date with no time component"
    assert isinstance(data["pcp_accepts_electronic_summary"], bool)
    assert isinstance(data["pcp_consent_on_file"], bool)
    assert isinstance(data["active_therapy_classes"], list)
    assert data["active_therapy_class_count"] == len(data["active_therapy_classes"])
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_staffing_assignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ASSIGNMENT_STATUSES
    assert data["role_kind"] in ("PRIMARY", "FLOAT")
    assert canonical_instant(data["ends_at"]) > canonical_instant(data["starts_at"])


def assert_queue_entry(data: dict):
    assert_common_fields(data)
    assert data["status"] in QUEUE_STATUSES
    assert data["kind"] in ("WALK_IN", "APPOINTMENT")
    assert data["complaint_code"] in COMPLAINT_CODES
    assert data["acuity_tier"] in (1, 2, 3)
    assert isinstance(data["priority_score"], int)


def assert_visit(data: dict):
    assert_common_fields(data)
    assert data["clinical_status"] in VISIT_CLINICAL_STATUSES
    assert data["billing_status"] in VISIT_BILLING_STATUSES
    assert data["coverage_status"] in ("UNVERIFIED", "ACTIVE", "INACTIVE", "UNKNOWN")
    assert isinstance(data["self_pay"], bool)
    assert isinstance(data["referral_required"], bool)
    assert isinstance(data["patient_age_months_at_visit"], int)
    assert isinstance(data["services_rendered"], list)


def assert_assessment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ASSESSMENT_STATUSES
    assert 30.0 <= data["temp_c"] <= 43.0
    assert 20 <= data["heart_rate_bpm"] <= 250
    assert 50 <= data["spo2_pct"] <= 100
    assert isinstance(data["red_flag_codes"], list)


def assert_prescription(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ROUTED", "CANCELLED")
    assert data["therapy_class"] in THERAPY_CLASSES
    assert 1 <= data["days_supply"] <= 90
    assert len(data["pharmacy_npi"]) == 10 and data["pharmacy_npi"].isdigit()


def assert_chart_review(data: dict):
    assert_common_fields(data)
    assert data["status"] in REVIEW_STATUSES
    assert data["sampled_reason"] in ("RANDOM_SAMPLE", "MANDATORY_REFERRAL",
                                      "CONTROLLED_RX")
    assert is_iso8601_timestamp(data["due_at"])
    assert isinstance(data["changes_requested_count"], int)


def assert_visit_summary(data: dict):
    assert_common_fields(data)
    assert data["status"] in SUMMARY_STATUSES
    assert data["destination_kind"] in ("DIRECT_MESSAGE", "FAX", "PATIENT_PORTAL")
    assert isinstance(data["attempt_count"], int)
    assert isinstance(data["includes_referral"], bool)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def validate_unpaginated(response, expected_status: int = 200) -> dict:
    """For endpoints whose data is a single object rather than a page of rows.

    The clock advance and the sampling run both answer with an object payload,
    so they must not be read through the paginated-list validator.
    """
    assert response.status_code == expected_status, \
        f"Expected {expected_status}, got {response.status_code}: {response.text}"
    body = response.json()
    assert body["response_type"] == "object", \
        f"expected response_type 'object', got {body.get('response_type')!r}"
    assert isinstance(body["data"], dict), "data must be an object"
    return body["data"]


def error_id(response) -> str:
    """The machine-readable error identifier out of an error envelope's data."""
    body = response.json()
    assert body["response_type"] == "error", \
        f"expected an error envelope, got {body.get('response_type')!r}"
    return body["data"]["error_id"]


def assert_response_type(response, expected: str):
    body = response.json()
    assert body.get("response_type") == expected, \
        f"expected response_type {expected!r}, got {body.get('response_type')!r}"


def assert_page(meta: dict, total_count: int, has_more: bool,
                limit: int = None, offset: int = None):
    assert meta["total_count"] == total_count, \
        f"expected total_count {total_count}, got {meta['total_count']}"
    assert meta["has_more"] is has_more, \
        f"expected has_more {has_more}, got {meta['has_more']}"
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_sorted_by_created_at(rows: list):
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "list rows must be sorted by created_at ascending"


# ---------------------------------------------------------------------------
# Domain calculations, recomputed independently of the server
# ---------------------------------------------------------------------------

def round_half_up(value) -> int:
    """Round to whole cents half up, as the PRD's monetary rule requires."""
    return int(math.floor(float(value) + 0.5))


def insured_patient_share(line_prices, copay_cents, coinsurance_pct,
                         total_allowed) -> int:
    """Round each line's coinsurance share on its own, sum, add the copay, cap."""
    share = sum(round_half_up(price * coinsurance_pct / 100) for price in line_prices)
    return min(share + copay_cents, total_allowed)


def self_pay_discount_pct(subtotal_cents: int) -> int:
    if subtotal_cents < 10000:
        return 0
    if subtotal_cents < 20000:
        return 10
    return 15


def self_pay_price(subtotal_cents: int) -> int:
    """One aggregate discount, with the tier taken from the pre-discount subtotal."""
    pct = self_pay_discount_pct(subtotal_cents)
    return subtotal_cents - round_half_up(subtotal_cents * pct / 100)


def service_line_prices(base_price_cents: int, services) -> list:
    return [base_price_cents] + [SERVICE_PRICES_CENTS[s] for s in services]


def posted_wait_minutes(waiting_count: int, on_duty_clinician_count: int,
                       upcoming_appointments: int = 0) -> int:
    blocks = math.ceil(waiting_count / max(1, on_duty_clinician_count))
    return min(120, blocks * 20 + 10 * upcoming_appointments)


def assert_money_conserved(visit: dict):
    """patient share plus payer share must equal final_price_cents exactly."""
    assert (visit["patient_responsibility_cents"] + visit["payer_responsibility_cents"]
            == visit["final_price_cents"]), (
        f"{visit['patient_responsibility_cents']} + "
        f"{visit['payer_responsibility_cents']} != {visit['final_price_cents']}")


def assert_version_bumped(before: dict, after: dict, by: int = 1):
    assert after["version"] == before["version"] + by, \
        f"expected version {before['version'] + by}, got {after['version']}"
    assert canonical_instant(after["updated_at"]) >= canonical_instant(before["updated_at"]), \
        "updated_at must not move backwards"
