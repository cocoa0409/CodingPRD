"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_fund_company(data):
    _assert_common_fields(data, "FundCompany")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["company_status"] in ("ACTIVE", "SUSPENDED", "OFFBOARDED")
    assert data["commercial_relationship"] in ("NONE", "LICENSED_CLIENT", "INDEX_LICENSEE")
    assert isinstance(data["open_dispute_count"], int)
    assert isinstance(data["quality_score_bp"], int)


def assert_fund(data):
    _assert_common_fields(data, "Fund")
    assert isinstance(data["ticker"], str) and len(data["ticker"]) > 0
    assert data["fund_status"] in ("ACTIVE", "SUSPENDED", "LIQUIDATED")
    assert isinstance(data["trailing_return_3y_bp"], int)
    assert isinstance(data["risk_score_bp"], int)
    assert isinstance(data["category_assignment_revision"], int)


def assert_category(data):
    _assert_common_fields(data, "Category")
    assert isinstance(data["category_code"], str)
    assert data["dominant_asset_class"] in ("EQUITY", "BOND", "MIXED")
    assert data["dominant_sector"] in (
        "TECH", "HEALTH", "FINANCE", "ENERGY", "CONSUMER", "INDUSTRIAL", "MIXED",
    )
    assert isinstance(data["min_weight_bp"], int)
    assert isinstance(data["active"], bool)


def assert_methodology(data):
    _assert_common_fields(data, "Methodology")
    assert isinstance(data["methodology_code"], str)
    assert data["methodology_kind"] in ("QUANTITATIVE", "ANALYST")
    assert isinstance(data["version_number"], int)
    assert data["methodology_status"] in ("DRAFT", "EFFECTIVE", "SUPERSEDED", "RETIRED")
    assert isinstance(data["weight_return_bp"], int)
    assert isinstance(data["weight_risk_bp"], int)
    assert isinstance(data["rating_ceilings"], list) and len(data["rating_ceilings"]) == 4


def assert_methodology_change(data):
    _assert_common_fields(data, "MethodologyChange")
    assert data["change_status"] in ("PROPOSED", "APPROVED", "EFFECTIVE", "WITHDRAWN")
    assert isinstance(data["restatement_required"], bool)
    assert isinstance(data["client_notice_sent"], bool)


def assert_rating(data):
    _assert_common_fields(data, "Rating")
    assert data["rating_kind"] in ("QUANTITATIVE", "ANALYST")
    assert data["rating_status"] in (
        "PROVISIONAL", "COMMITTEE_REVIEW", "PUBLISHED",
        "SUPERSEDED", "WITHDRAWN", "RESTATED",
    )
    assert data["suppression_reason"] in ("NONE", "CONFLICT_HOLD", "DISPUTE_HOLD")


def assert_proposal(data):
    _assert_common_fields(data, "RatingProposal")
    assert data["proposed_grade"] in ("GOLD", "SILVER", "BRONZE", "NEUTRAL", "NEGATIVE")
    assert data["proposal_status"] in ("OPEN", "QUORUM_MET", "APPROVED", "REJECTED", "WITHDRAWN")
    assert isinstance(data["approvals"], int)
    assert isinstance(data["rejections"], int)


def assert_licensee(data):
    _assert_common_fields(data, "Licensee")
    assert isinstance(data["licensee_name"], str)
    assert data["licensee_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["arrears_cents"], int)


def assert_license_agreement(data):
    _assert_common_fields(data, "LicenseAgreement")
    assert data["tier"] in ("DISPLAY", "REDISTRIBUTION", "DERIVED_WORKS")
    assert isinstance(data["seat_limit"], int)
    assert isinstance(data["seats_in_use"], int)
    assert isinstance(data["base_fee_cents"], int)
    assert data["agreement_status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_seat_entitlement(data):
    _assert_common_fields(data, "SeatEntitlement")
    assert isinstance(data["workstation_user_id"], str)
    assert data["seat_status"] in ("ACTIVE", "REVOKED")
    assert data["entitled_data_scope"] in ("DISPLAY", "REDISTRIBUTION", "DERIVED_WORKS")


def assert_license_audit(data):
    _assert_common_fields(data, "LicenseAudit")
    assert data["audit_status"] in (
        "OPEN", "FINDINGS_FILED", "CLOSED_NO_ACTION", "CLOSED_WITH_PENALTY",
    )
    assert isinstance(data["unlicensed_uses_found"], int)
    assert isinstance(data["penalty_cents"], int)


def assert_data_dispute(data):
    _assert_common_fields(data, "DataDispute")
    assert data["disputed_field"] in (
        "HOLDINGS", "TRAILING_RETURN_3Y", "TRAILING_RETURN_5Y", "RISK_SCORE", "CATEGORY",
    )
    assert data["dispute_status"] in (
        "OPEN", "UNDER_INVESTIGATION", "RESOLVED_ACCEPTED", "RESOLVED_REJECTED",
    )


def assert_index_definition(data):
    _assert_common_fields(data, "IndexDefinition")
    assert isinstance(data["index_code"], str)
    assert isinstance(data["max_constituents"], int)
    assert isinstance(data["single_constituent_cap_bp"], int)
    assert data["index_status"] in ("DRAFT", "LIVE", "SUSPENDED", "RETIRED")


def assert_conflict_flag(data):
    _assert_common_fields(data, "ConflictFlag")
    assert data["flag_kind"] in ("COMMERCIAL_RATING_CONFLICT", "INDEX_LICENSOR_CONFLICT")
    assert data["flag_status"] in ("OPEN", "WAIVED", "RESOLVED")
    assert isinstance(data["blocking"], bool)


def assert_holding(data):
    """Ledger-style row: id + created_at only; no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "Holding.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["weight_bp"], int)
    assert "version" not in data, "Holding must not carry a version field"
    assert "updated_at" not in data, "Holding must not carry updated_at"


def assert_committee_vote(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["vote"] in ("APPROVE", "REJECT", "ABSTAIN")
    assert "version" not in data, "CommitteeVote must not carry a version field"
    assert "updated_at" not in data, "CommitteeVote must not carry updated_at"


def assert_client_notice(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["notice_channel"] in ("EMAIL", "PORTAL", "API")
    assert "version" not in data, "ClientNotice must not carry a version field"
    assert "updated_at" not in data, "ClientNotice must not carry updated_at"
