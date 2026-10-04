"""Entity assertions and domain invariant helpers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_supplier(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROSPECT", "APPROVED", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["ingredient_category"] in [
        "DAIRY", "COCOA", "SUGAR", "VANILLA", "NUTS", "FRUIT", "CHUNK_INCLUSION",
    ]


def assert_commitment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "LAPSED"]
    assert "supplier_id" in data


def assert_certification(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "VERIFIED", "EXPIRED", "REVOKED"]
    assert data["scheme"] in ["FAIR_TRADE", "ORGANIC", "NON_GMO", "B_CORP", "RAINFOREST_ALLIANCE"]


def assert_audit(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "VERIFIED"]


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ENROLLED", "ASSESSED"]
    assert isinstance(data["total_approved_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ["CALCULATED", "APPROVED", "PAID", "VOIDED"]
    assert data["calc_variant"] in ["PROVISIONAL", "FINAL"]


def assert_flavor(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DEVELOPMENT", "TEST_BATCH", "LIMITED_RUN", "CORE_LINE", "RETIRED", "REVIVED",
    ]
    assert data["claim_status"] in [
        "UNCLAIMED", "SUBSTANTIATED", "PUBLISHED", "CHALLENGED", "RETRACTED",
    ]


def assert_revival_request(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "QUALIFIED", "ADOPTED", "DECLINED"]
    assert isinstance(data["signature_count"], int)


def assert_production_slot(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLANNED", "CONFIRMED", "COMPLETED", "CANCELLED"]
    assert data["plant_code"] in ["VT_WATERBURY", "VT_ST_ALBANS", "NL_HELLENDOORN"]


def assert_campaign(data: dict):
    _assert_common(data)
    assert data["approval_status"] in [
        "BOARD_REVIEW", "BOARD_APPROVED", "BOARD_REJECTED",
        "OPS_SCHEDULED", "LAUNCHED", "WITHDRAWN",
    ]
    assert data["retail_notice_status"] in ["NOT_REQUIRED", "PENDING", "DISPATCHED"]


def assert_scoop_shop(data: dict):
    _assert_common(data)
    assert data["status"] in ["SITE_REVIEW", "SITE_APPROVED", "OPERATING", "SUSPENDED", "CLOSED"]
    assert data["operator_type"] in ["FRANCHISEE", "NONPROFIT_PARTNER"]


def assert_supply_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLACED", "CONFIRMED", "ALLOCATED", "DELIVERED", "CANCELLED"]
    assert isinstance(data["lines"], list)


def assert_error_envelope(response, error_id: str):
    """PRD §2.2 error envelope: response_type error, data.error_id, non-empty message."""
    body = response.json()
    assert body.get("response_type") == "error", f"expected error envelope, got {body!r}"
    data = body.get("data") or {}
    assert data.get("error_id") == error_id, f"expected {error_id}, got {data.get('error_id')!r}"
    assert isinstance(data.get("message"), str) and data["message"], "error message must be non-empty"
    return data
