"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_region(data: dict):
    _assert_common(data)
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_source(data: dict):
    _assert_common(data)
    assert data["source_type"] in ("DEALER", "AUCTION", "LENDER")
    assert isinstance(data["region_id"], str) and data["region_id"]
    assert data["status"] in ("PROBATION", "ACTIVE", "SUSPENDED")
    assert isinstance(data["consecutive_rejections"], int)
    assert data["consecutive_rejections"] >= 0
    assert isinstance(data["external_key"], str) and data["external_key"]
    assert isinstance(data["name"], str) and data["name"]


def assert_configuration(data: dict):
    _assert_common(data)
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["year"], int) and 1990 <= data["year"] <= 2030
    assert isinstance(data["trim"], str) and data["trim"]
    assert data["segment"] in ("SEDAN", "SUV", "TRUCK", "VAN", "COUPE")
    assert isinstance(data["annual_expected_miles"], int)
    assert data["annual_expected_miles"] >= 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["external_key"], str) and data["external_key"]


def assert_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["source_id"], str) and data["source_id"]
    assert isinstance(data["submission_ref"], str) and data["submission_ref"]
    assert data["status"] in ("RECEIVED", "VALIDATED", "ACCEPTED", "REJECTED")
    assert isinstance(data["accepted_count"], int) and data["accepted_count"] >= 0


def assert_series(data: dict):
    _assert_common(data)
    assert isinstance(data["configuration_id"], str) and data["configuration_id"]
    assert isinstance(data["region_id"], str) and data["region_id"]
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "SUPERSEDED")
    assert isinstance(data["confidence_score"], (int, float))
    assert 0 <= data["confidence_score"] <= 1


def assert_edition(data: dict):
    _assert_common(data)
    assert isinstance(data["series_id"], str) and data["series_id"]
    assert data["status"] in ("PENDING", "PUBLISHED", "WITHDRAWN")
    assert isinstance(data["reference_price_cents"], int)
    assert isinstance(data["trade_in_cents"], int)
    assert isinstance(data["private_party_cents"], int)
    assert isinstance(data["retail_cents"], int)


def assert_market_shift(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "RESCINDED")
    pct = data["pct_adjustment"]
    assert isinstance(pct, (int, float)) and -0.50 <= pct <= 0.50


def assert_cash_offer(data: dict):
    _assert_common(data)
    assert isinstance(data["edition_id"], str) and data["edition_id"]
    assert isinstance(data["funding_dealer_id"], str) and data["funding_dealer_id"]
    assert isinstance(data["consumer_id"], str) and data["consumer_id"]
    assert data["status"] in ("QUOTED", "INSPECTED", "REDEEMED", "EXPIRED", "VOID")
    assert data["declared_condition_tier"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")
    assert isinstance(data["offer_amount_cents"], int)
    assert isinstance(data["mileage"], int) and data["mileage"] >= 0
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0
    assert isinstance(data["option_ids"], list)
    assert is_iso8601_timestamp(data["expires_at"])


def assert_license_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["licensee_ref"], str) and data["licensee_ref"]
    assert isinstance(data["permitted_uses"], list) and len(data["permitted_uses"]) >= 1
    for use in data["permitted_uses"]:
        assert use in ("UNDERWRITING", "SETTLEMENT", "DISPLAY")
    assert isinstance(data["monthly_event_quota"], int)
    assert 1 <= data["monthly_event_quota"] <= 100000
    assert data["fee_per_event_cents"] == 4
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["activation_version"], int)


def assert_dispute(data: dict):
    _assert_common(data)
    assert isinstance(data["offer_id"], str) and data["offer_id"]
    assert data["reason_code"] in ("WRONG_CONDITION", "STALE_DATA", "MISSING_OPTIONS")
    assert data["status"] in ("OPEN", "RESOLVED_UPHELD", "RESOLVED_ADJUSTED", "WITHDRAWN")


def assert_methodology(data: dict):
    _assert_common(data)
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert isinstance(data["formula_hash"], str) and data["formula_hash"]
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_condition_standard(data: dict):
    _assert_common(data)
    assert data["tier"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["multiplier"], (int, float))


def assert_option_package(data: dict):
    _assert_common(data)
    assert isinstance(data["configuration_id"], str) and data["configuration_id"]
    assert isinstance(data["option_code"], str) and data["option_code"]
    assert isinstance(data["credit_cents"], int)
    assert 1 <= data["credit_cents"] <= 1000000
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_consumer_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_license_event(data: dict):
    """Append-only row: id + created_at only from the common set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "LicenseEvent must not carry updated_at"
    assert "version" not in data, "LicenseEvent must not carry version"
    assert isinstance(data["agreement_id"], str) and data["agreement_id"]
    assert data["event_type"] in ("EDITION_READ", "OFFER_CREATED")
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_data_correction(data: dict):
    """Append-only row: id + created_at only from the common set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DataCorrection must not carry updated_at"
    assert "version" not in data, "DataCorrection must not carry version"
    assert isinstance(data["batch_id"], str) and data["batch_id"]
    assert isinstance(data["corrected_price_cents"], int)
    assert 100 <= data["corrected_price_cents"] <= 100000000
    assert isinstance(data["delta_applied"], bool)


def assert_snapshot(data: dict):
    """Append-only row: id + created_at only from the common set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Snapshot must not carry updated_at"
    assert "version" not in data, "Snapshot must not carry version"
    assert isinstance(data["agreement_id"], str) and data["agreement_id"]
    assert isinstance(data["methodology_version_label"], str)
    assert isinstance(data["snapshot_version"], int)


def assert_edition_invariants(data: dict):
    """Tier-value invariants that must hold on every edition."""
    ref = data["reference_price_cents"]
    assert data["trade_in_cents"] <= ref <= data["retail_cents"]
    assert data["private_party_cents"] <= data["retail_cents"]


def assert_offer_invariants(data: dict):
    """Dealer-liability floor invariant on inspected offers."""
    if data.get("final_amount_cents") is not None:
        from prd_bench_local_runner.testing import is_valid_uuid  # noqa: F401
        floor = int(data["offer_amount_cents"] * 0.90 + 0.5)
        assert data["final_amount_cents"] >= floor, (
            f"final_amount_cents {data['final_amount_cents']} below the 90% floor {floor}"
        )
