"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_patron(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("email"), str) and len(data["email"]) > 0
    assert isinstance(data.get("full_name"), str)
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data.get("active_loan_count"), int)
    assert isinstance(data.get("strike_count"), int)
    assert isinstance(data.get("max_concurrent_loans"), int)


def assert_accessibility_credential(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("patron_id"), str)
    assert isinstance(data.get("certifier_reference"), str)
    assert data.get("status") in ("PENDING_REVIEW", "VERIFIED", "REJECTED", "REVOKED")
    assert "decided_by" in data, "decided_by must be present (null until decided)"
    assert "decided_at" in data, "decided_at must be present (null until decided)"


def assert_partner_library(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("library_code"), str)
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("storage_commitment_years"), int)
    assert data.get("status") in ("ACTIVE", "WITHDRAWN")


def assert_work(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("author"), str)
    assert isinstance(data.get("publication_year"), int)
    assert data.get("availability") in ("AVAILABLE", "EMBARGOED", "WITHDRAWN")


def assert_scan_batch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("operator_code"), str)
    assert data.get("status") in ("OPEN", "SEALED", "REJECTED")
    assert isinstance(data.get("item_count"), int)
    assert isinstance(data.get("page_count"), int)


def assert_scan_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("batch_id"), str)
    assert isinstance(data.get("work_id"), str)
    assert isinstance(data.get("owning_library_id"), str)
    assert isinstance(data.get("page_count"), int)
    assert data.get("condition_grade") in ("FINE", "GOOD", "FAIR", "FRAGILE")
    assert data.get("status") in ("DEPOSITED", "LENDABLE", "ON_LOAN", "RETIRED")
    assert isinstance(data.get("lendable"), bool)


def assert_loan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("item_id"), str)
    assert isinstance(data.get("patron_id"), str)
    assert data.get("loan_kind") in ("STANDARD", "SHORT_READ")
    assert data.get("status") in ("ACTIVE", "RETURNED", "EXPIRED", "REVOKED")
    assert is_iso8601_timestamp(data.get("checked_out_at", "")), "checked_out_at ISO 8601"
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at ISO 8601"
    assert isinstance(data.get("renewed"), bool)


def assert_waitlist_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("work_id"), str)
    assert isinstance(data.get("patron_id"), str)
    assert data.get("status") in ("OPEN", "OFFERED", "CLAIMED", "EXPIRED_OFFER", "CANCELLED")
    assert "offered_at" in data, "offered_at must be present (null while OPEN)"
    assert "offer_expires_at" in data, "offer_expires_at must be present (null while OPEN)"
    assert isinstance(data.get("version"), int)


def assert_crawl_job(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("seed_url"), str)
    assert isinstance(data.get("scheduled_at"), str)
    assert isinstance(data.get("requests_per_minute"), int)
    assert data.get("status") in ("SCHEDULED", "RUNNING", "COMPLETED", "BLOCKED", "CANCELLED")
    assert isinstance(data.get("captures_produced"), int)
    assert isinstance(data.get("duplicates_skipped"), int)
    assert isinstance(data.get("storage_cost_cents"), int)


def assert_capture(data: dict):
    """Capture is immutable: id + created_at only among common fields; no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Capture must not carry a version field"
    assert "updated_at" not in data, "Capture must not carry an updated_at field"
    assert isinstance(data.get("url"), str)
    assert isinstance(data.get("content_hash"), str)
    assert isinstance(data.get("has_dynamic_content"), bool)
    assert data.get("playback_status") in ("PLAYABLE", "SUPPRESSED")


def assert_exclusion_directive(data: dict):
    assert isinstance(data.get("url_prefix"), str)
    assert data.get("scope") in ("CRAWL_ONLY", "PLAYBACK_ONLY", "BOTH")
    assert data.get("status") in ("ACTIVE", "RETRACTED")


def assert_rights_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data.get("subject_kind") in ("WORK", "CAPTURE_URL_PREFIX")
    assert isinstance(data.get("claimant_name"), str)
    assert isinstance(data.get("filed_by"), str)
    assert data.get("status") in (
        "FILED", "UNDER_REVIEW", "LEGAL_HOLD", "UPHELD_REMOVED", "DISMISSED"
    )
    assert "reviewed_by" in data, "reviewed_by must be present (null until reviewed)"
    assert "decided_by" in data, "decided_by must be present (null until decided)"


def assert_funding_grant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("donor_name"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("reserved_cents"), int)
    assert isinstance(data.get("spent_cents"), int)
    assert data.get("status") in ("OPEN", "EXHAUSTED", "CLOSED")
    assert isinstance(data.get("version"), int)


def assert_budget_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("grant_id"), str)
    assert data.get("category") in ("STORAGE", "BANDWIDTH", "SCAN_LABOR", "PETABYTE_INSURANCE")
    assert isinstance(data.get("budget_reservation_cents"), int)
    assert data.get("status") in ("OPEN", "SETTLED", "RELEASED")


def assert_grant_counters_invariant(grant: dict):
    """reserved_cents >= 0, spent_cents >= 0, utilization <= amount_cents."""
    assert grant["reserved_cents"] >= 0, "reserved_cents must be non-negative"
    assert grant["spent_cents"] >= 0, "spent_cents must be non-negative"
    assert grant["reserved_cents"] + grant["spent_cents"] <= grant["amount_cents"], (
        "utilization must never exceed amount_cents"
    )
