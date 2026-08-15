"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PARTY_TYPES = ["CORPORATION", "INDIVIDUAL", "PARTNERSHIP", "TRUST", "GOVERNMENT"]
PRACTICE_GROUPS = ["LITIGATION", "CORPORATE", "TAX", "IP"]
HIRE_TYPES = ["INTERNAL", "LATERAL"]
ATTORNEY_STATUSES = ["ACTIVE", "LATERAL_PENDING"]
MATTER_LIFECYCLES = ["INTAKE", "OPEN", "CLOSED", "DECLINED"]
CLEARANCE_STATUSES = ["UNCHECKED", "HITS_PENDING", "CLEARED", "BLOCKED", "WAIVED"]
ROLES_IN_MATTER = ["ADVERSE", "WITNESS", "RELATED"]
CHECK_KINDS = ["INTAKE", "LATERAL_SWEEP"]
SEARCH_VARIANTS = ["STRICT", "PHONETIC"]
CHECK_STATUSES = ["COMPLETED", "SUPERSEDED"]
MATCHED_VIAS = ["DIRECT", "ALIAS", "AFFILIATE", "LATERAL"]
REVIEW_STATUSES = ["PENDING", "CONFIRMED", "DISMISSED", "WAIVED", "STALE"]
WALL_REASONS = ["CONFLICT_CONFIRMED", "LATERAL_IMPUTATION", "CLIENT_REQUEST"]
WALL_STATUSES = ["ACTIVE", "LIFTED"]
WAIVER_STATUSES = [
    "DRAFT",
    "SENT",
    "CONSENTED",
    "DECLINED",
    "APPROVED",
    "REVOKED",
    "EXPIRED",
]
LETTER_STATUSES = ["DRAFT", "ISSUED", "COUNTERSIGNED", "SUPERSEDED", "VOID"]
CREDIT_BANDS = ["PRIME", "STANDARD", "SUBPRIME"]
DEPOSIT_STATUSES = ["PENDING", "PARTIALLY_FUNDED", "FUNDED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def assert_party(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert data.get("party_type") in PARTY_TYPES
    assert isinstance(data.get("aliases"), list)
    for alias in data["aliases"]:
        assert isinstance(alias.get("alias_name"), str)
        assert isinstance(alias.get("normalized_alias"), str)
    assert isinstance(data.get("normalized_name"), str)
    phonetic = data.get("phonetic_key")
    assert isinstance(phonetic, str) and len(phonetic) == 4


def assert_attorney(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("bar_number"), str) and data["bar_number"]
    assert data.get("practice_group") in PRACTICE_GROUPS
    assert data.get("hire_type") in HIRE_TYPES
    assert data.get("status") in ATTORNEY_STATUSES
    assert isinstance(data.get("prior_client_names"), list)


def assert_matter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("matter_title"), str)
    assert is_valid_uuid(data.get("client_party_id", ""))
    assert is_valid_uuid(data.get("responsible_attorney_id", ""))
    assert data.get("practice_group") in PRACTICE_GROUPS
    assert data.get("lifecycle_status") in MATTER_LIFECYCLES
    assert data.get("clearance_status") in CLEARANCE_STATUSES
    matter_number = data.get("matter_number")
    if matter_number is not None:
        assert isinstance(matter_number, str) and matter_number.startswith("M")
    assert isinstance(data.get("decline_reason"), str)


def assert_matter_party(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("matter_id", ""))
    assert is_valid_uuid(data.get("party_id", ""))
    assert data.get("role_in_matter") in ROLES_IN_MATTER


def assert_conflict_check(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("matter_id", ""))
    assert data.get("check_kind") in CHECK_KINDS
    assert data.get("search_variant") in SEARCH_VARIANTS
    threshold = data.get("match_threshold")
    assert isinstance(threshold, int) and 0 <= threshold <= 100
    assert data.get("status") in CHECK_STATUSES
    assert isinstance(data.get("hit_count"), int) and data["hit_count"] >= 0


def assert_conflict_hit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("check_id", ""))
    assert is_valid_uuid(data.get("matched_party_id", ""))
    assert is_valid_uuid(data.get("matched_matter_id", ""))
    assert data.get("matched_via") in MATCHED_VIAS
    score = data.get("match_score")
    assert isinstance(score, int) and 0 <= score <= 100
    assert data.get("review_status") in REVIEW_STATUSES


def assert_ethical_wall(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("matter_id", ""))
    assert data.get("reason") in WALL_REASONS
    assert isinstance(data.get("memo"), str)
    excluded = data.get("excluded_attorney_ids")
    assert isinstance(excluded, list) and len(excluded) >= 1
    assert data.get("status") in WALL_STATUSES


def assert_waiver_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("matter_id", ""))
    assert is_valid_uuid(data.get("conflict_hit_id", ""))
    assert isinstance(data.get("requested_by_attorney_id"), str)
    assert isinstance(data.get("proposed_terms"), str)
    assert data.get("status") in WAIVER_STATUSES
    assert isinstance(data.get("decline_reason"), str)


def assert_engagement_letter(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("matter_id", ""))
    assert isinstance(data.get("scope_text"), str)
    fee_lines = data.get("fee_lines")
    assert isinstance(fee_lines, list) and len(fee_lines) >= 1
    for line in fee_lines:
        assert isinstance(line.get("description"), str)
        assert line.get("hours") > 0
        assert isinstance(line.get("rate_cents"), int) and line["rate_cents"] > 0
    assert isinstance(data.get("fee_estimate_cents"), int)
    assert data.get("status") in LETTER_STATUSES


def assert_credit_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("matter_id", ""))
    score = data.get("score")
    assert isinstance(score, int) and 300 <= score <= 850
    assert data.get("band") in CREDIT_BANDS
    assert is_iso8601_timestamp(data.get("assessed_at", ""))


def assert_retainer_deposit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("matter_id", ""))
    assert isinstance(data.get("required_cents"), int) and data["required_cents"] >= 0
    assert isinstance(data.get("funded_total_cents"), int)
    assert isinstance(data.get("refunded_total_cents"), int)
    assert isinstance(data.get("received_cents"), int)
    assert data.get("status") in DEPOSIT_STATUSES


def assert_deposit_conservation(data: dict):
    """Domain invariant: received_cents = funded_total_cents - refunded_total_cents."""
    assert_retainer_deposit(data)
    assert data["received_cents"] == (
        data["funded_total_cents"] - data["refunded_total_cents"]
    ), (
        f"received_cents {data['received_cents']} != "
        f"funded {data['funded_total_cents']} - refunded {data['refunded_total_cents']}"
    )
    assert data["received_cents"] >= 0
