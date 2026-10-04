"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            f"version must be a positive integer, got {data.get('version')!r}"


def assert_care_network(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["coordinator_org_name"], str) and data["coordinator_org_name"]
    for field in ("max_reassignment_count", "auto_accept_window_hours",
                  "unresolved_aging_days", "referral_expiry_days",
                  "network_escrow_cents", "network_escrow_reserved_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert_network_escrow_invariants(data)


def assert_network_escrow_invariants(data: dict):
    """Escrow invariants that hold on every CareNetwork read."""
    assert data["network_escrow_cents"] >= 0, "escrow never goes negative"
    assert data["network_escrow_reserved_cents"] >= 0


def assert_taxonomy_category(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_organization(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["org_type"] in ("CBO", "CLINIC", "FUNDER")
    assert data["funder_type"] in ("HEALTH_PLAN", "PUBLIC_AGENCY", "NONE")
    assert isinstance(data["ein"], str) and data["ein"]
    assert data["status"] in ("PENDING_REVIEW", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert_org_balance_invariants(data)


def assert_org_balance_invariants(data: dict):
    """Payable balance never goes negative."""
    assert isinstance(data["payable_balance_cents"], int)
    assert data["payable_balance_cents"] >= 0, "payable_balance_cents never goes negative"


def assert_offering(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("organization_id", ""))
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert isinstance(data["description"], str)
    assert isinstance(data["min_client_age"], int)
    assert isinstance(data["max_client_age"], int)
    assert isinstance(data["eligible_zip_codes"], list)
    assert isinstance(data["eligible_genders"], list)
    assert data["income_cap_annual_cents"] is None or \
        isinstance(data["income_cap_annual_cents"], int)
    assert data["status"] in ("ACTIVE", "PAUSED")
    assert_offering_capacity_invariants(data)


def assert_offering_capacity_invariants(data: dict):
    """capacity_available is capacity_total minus capacity_consumed and is
    never negative."""
    assert isinstance(data["capacity_total"], int) and data["capacity_total"] >= 1
    assert isinstance(data["capacity_consumed"], int) and data["capacity_consumed"] >= 0
    assert data["capacity_available"] == data["capacity_total"] - data["capacity_consumed"], \
        "capacity_available must equal capacity_total - capacity_consumed"
    assert data["capacity_available"] >= 0, "capacity_available never goes negative"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["zip_code"], str) and data["zip_code"]
    assert data["gender"] in ("FEMALE", "MALE", "NONBINARY", "UNDISCLOSED")
    assert data["annual_income_cents"] is None or isinstance(data["annual_income_cents"], int)
    assert data["race"] in ("AMERICAN_INDIAN", "ASIAN", "BLACK", "PACIFIC_ISLANDER",
                            "WHITE", "MULTIRACIAL", "UNDISCLOSED")
    assert data["ethnicity"] in ("HISPANIC", "NON_HISPANIC", "UNDISCLOSED")
    assert isinstance(data["language"], str) and data["language"]
    assert isinstance(data["veteran_status"], bool)
    assert isinstance(data["open_referral_count"], int) and data["open_referral_count"] >= 0


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("party_a_org_id", ""))
    assert is_valid_uuid(data.get("party_b_org_id", ""))
    assert data["party_a_org_id"] != data["party_b_org_id"]
    assert isinstance(data["effective_at"], str) and data["effective_at"]
    assert data["status"] in ("PENDING", "ACTIVE", "EXPIRED", "TERMINATED")


def assert_consent(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("sender_org_id", ""))
    assert is_valid_uuid(data.get("receiver_org_id", ""))
    assert data["scope"] in ("FULL", "MINIMUM_NECESSARY")
    assert data["status"] in ("ACTIVE", "REVOKED")
    if data["status"] == "REVOKED":
        assert isinstance(data.get("revoked_at"), str) and data["revoked_at"]
    else:
        assert data.get("revoked_at") is None


def assert_referral(data: dict):
    _assert_common(data)
    for field in ("client_id", "sender_org_id", "receiver_org_id",
                  "service_offering_id", "consent_id"):
        assert is_valid_uuid(data.get(field, "")), f"{field} must be a UUID"
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert data["urgency"] in ("STANDARD", "URGENT")
    assert data["status"] in ("DRAFT", "ROUTED", "ACCEPTED", "DECLINED", "IN_SERVICE",
                              "OUTCOME_RECORDED", "ESCALATED", "CANCELLED", "EXPIRED")
    assert isinstance(data["reassignment_count"], int) and data["reassignment_count"] >= 0
    assert isinstance(data["aging_days"], int) and data["aging_days"] >= 0
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert data.get("outcome_code") is None or data["outcome_code"] in (
        "DELIVERED", "NOT_REACHED", "CLIENT_DECLINED", "PARTIALLY_DELIVERED")
    assert isinstance(data["delivered_units"], int) and data["delivered_units"] >= 0


def assert_referral_note(data: dict):
    # Notes are lean: id + created_at only; updated_at and version are absent.
    _assert_common(data, with_version=False)
    assert "updated_at" not in data, "ReferralNote must not carry updated_at"
    assert "version" not in data, "ReferralNote must not carry version"
    assert is_valid_uuid(data.get("referral_id", ""))
    assert is_valid_uuid(data.get("author_org_id", ""))
    assert isinstance(data["body"], str)
    assert data["visibility"] in ("NETWORK", "SENDER_ONLY", "RECEIVER_ONLY")


def assert_outcome_record(data: dict):
    # Outcome records are lean: id + created_at only.
    _assert_common(data, with_version=False)
    assert "updated_at" not in data, "OutcomeRecord must not carry updated_at"
    assert "version" not in data, "OutcomeRecord must not carry version"
    assert is_valid_uuid(data.get("referral_id", ""))
    assert data["outcome_code"] in ("DELIVERED", "NOT_REACHED", "CLIENT_DECLINED",
                                    "PARTIALLY_DELIVERED")
    assert isinstance(data["delivered_units"], int) and data["delivered_units"] >= 0
    assert is_valid_uuid(data.get("reported_by_org_id", ""))
    assert isinstance(data["reported_at"], str) and data["reported_at"]
    assert isinstance(data["billable"], bool)


def assert_rate_card(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("funder_org_id", ""))
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert isinstance(data["rate_cents_per_unit"], int) and data["rate_cents_per_unit"] >= 1
    assert isinstance(data["min_units"], int) and data["min_units"] >= 1
    assert data["tier2_rate_cents_per_unit"] is None or \
        isinstance(data["tier2_rate_cents_per_unit"], int)
    assert data["monthly_cap_cents"] is None or isinstance(data["monthly_cap_cents"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("referral_id", ""))
    assert is_valid_uuid(data.get("funder_org_id", ""))
    assert is_valid_uuid(data.get("provider_org_id", ""))
    assert isinstance(data["claimed_units"], int) and data["claimed_units"] >= 1
    assert isinstance(data["provisional_amount_cents"], int)
    assert data["approved_amount_cents"] is None or \
        isinstance(data["approved_amount_cents"], int)
    assert isinstance(data["clawback_reserve_cents"], int)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED",
                              "VOIDED", "PAID")


def assert_disbursement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_org_id", ""))
    assert is_valid_uuid(data.get("funder_org_id", ""))
    assert isinstance(data["claim_ids"], list)
    assert isinstance(data["total_amount_cents"], int)
    assert data["status"] in ("SCHEDULED", "PAID", "FAILED")


def assert_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("funder_org_id", ""))
    assert isinstance(data["period_start"], str) and data["period_start"]
    assert isinstance(data["period_end"], str) and data["period_end"]
    for field in ("total_referrals", "delivered_count", "not_reached_count",
                  "unresolved_count", "aging_count", "total_reimbursed_cents",
                  "baseline_snapshot_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["demographic_breakdown"], dict)
    assert isinstance(data["closure_rate_percent"], (int, float))
    assert isinstance(data["resolution_rate_percent"], (int, float))
    assert data["status"] in ("DRAFT", "SEALED")
