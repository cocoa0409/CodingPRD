"""Entity assertions and domain invariant checkers.

Field shapes and defaults asserted here are the ones the PRD states
verbatim (PRD sections 2.4, 3.2, 3.3, 3.6). The generic envelope
validators come from the shared runner package.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, with_version, label):
    assert isinstance(data, dict), "{0}: expected an object".format(label)
    assert is_valid_uuid(data.get("id", "")), "{0}: id must be a UUID".format(label)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "{0}: created_at must be an ISO 8601 timestamp".format(label)
    )
    if with_version:
        assert isinstance(data.get("version"), int), (
            "{0}: version must be an integer".format(label)
        )
        assert data["version"] >= 1, "{0}: version starts at 1".format(label)
    else:
        assert "version" not in data, (
            "{0}: append-style records expose no version".format(label)
        )


def assert_account(data):
    """PRD section 3.1: new accounts begin ACTIVE with an empty suspend_reason."""
    _assert_common_fields(data, True, "Account")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert data["plan_tier"] in ("STANDARD", "PREMIUM")
    assert data["country_code"] in ("US", "CA", "GB")


def assert_brand(data):
    """PRD section 3.2: brand fields and lifecycle enums."""
    _assert_common_fields(data, True, "Brand")
    assert data["status"] in (
        "DRAFT",
        "PENDING_VERIFICATION",
        "UNVERIFIED",
        "VERIFIED",
        "REVOKED",
    )
    assert isinstance(data["identity_score"], int)
    assert 0 <= data["identity_score"] <= 100
    assert isinstance(data["resubmission_count"], int)


def assert_campaign(data):
    """PRD section 3.3: campaign fields and lifecycle enums."""
    _assert_common_fields(data, True, "Campaign")
    assert data["status"] in (
        "DRAFT",
        "PENDING_REVIEW",
        "REJECTED",
        "APPROVED",
        "SUSPENDED",
        "DEACTIVATED",
    )
    assert data["path_kind"] in ("TEN_DLC", "TOLL_FREE", "SHORT_CODE")
    assert isinstance(data["trust_score"], int)
    assert 0 <= data["trust_score"] <= 100
    assert isinstance(data["allocated_mps"], int)
    assert isinstance(data["rejected_cycle_count"], int)


def assert_number(data):
    """PRD section 3.5: sender number fields and lifecycle enums."""
    _assert_common_fields(data, True, "SenderNumber")
    assert data["status"] in (
        "PENDING",
        "PORTING",
        "ACTIVE",
        "SUSPENDED",
        "FAILED",
        "RELEASED",
    )
    assert data["number_type"] in ("TEN_DLC", "TOLL_FREE", "SHORT_CODE")
    assert data["provisioning_source"] in (
        "NEW_PURCHASE",
        "PORT_IN",
        "SHORT_CODE_ORDER",
    )


def assert_consent_record(data):
    """PRD section 3.6: consent records are append-style (no version)."""
    _assert_common_fields(data, False, "ConsentRecord")
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert is_iso8601_timestamp(data.get("captured_at", ""))
    assert is_iso8601_timestamp(data.get("retention_expires_at", ""))


def assert_message(data):
    """PRD section 3.6: message fields and lifecycle enums."""
    _assert_common_fields(data, True, "Message")
    assert data["status"] in (
        "ACCEPTED",
        "QUEUED",
        "SENT",
        "DELIVERED",
        "UNDELIVERED",
        "FAILED",
        "FILTERED",
        "STALE_CANCELLED",
    )
    assert isinstance(data["segments"], int)
    assert data["segments"] >= 1
    assert isinstance(data["queued_run_index"], int)


def assert_feedback_event(data):
    """PRD section 3.8: feedback events are append-style records."""
    _assert_common_fields(data, False, "FeedbackEvent")
    assert data["kind"] in ("BLOCK", "SPAM_COMPLAINT", "STOP")
    assert data["status"] in ("RECORDED", "APPLIED")


def assert_charge(data):
    """PRD section 2.11: charges are immutable, non-negative integer cents."""
    _assert_common_fields(data, False, "Charge")
    assert data["kind"] in (
        "BRAND_VETTING",
        "CAMPAIGN_REGISTRATION",
        "CAMPAIGN_RECURRING",
        "MESSAGE",
        "CARRIER_PASSTHROUGH",
        "NUMBER_MONTHLY",
    )
    assert data["reference_type"] in ("BRAND", "CAMPAIGN", "MESSAGE", "NUMBER")
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0
    assert data["currency"] == "USD"
    assert data["status"] in ("RECORDED", "SETTLED")


def assert_snapshot(data):
    """PRD section 3.8: daily snapshot aggregate fields."""
    _assert_common_fields(data, False, "DailySnapshot")
    for field in ("attempted", "delivered", "blocked", "spam"):
        assert isinstance(data[field], int), "{0} must be an integer".format(field)
        assert data[field] >= 0
    assert isinstance(data["block_rate_bps"], int)
    assert isinstance(data["spam_rate_bps"], int)


def assert_ops_run(data):
    """PRD section 3.1: ops run counters."""
    _assert_common_fields(data, False, "OpsRun")
    assert isinstance(data["run_index"], int)
    assert data["run_index"] >= 1
    for field in (
        "messages_dequeued",
        "messages_stale_cancelled",
        "recurring_fees_charged",
        "number_fees_charged",
    ):
        assert isinstance(data[field], int), "{0} must be an integer".format(field)


def charges_of_kind(charges, kind):
    """Filter a charge list down to one kind."""
    return [c for c in charges if c.get("kind") == kind]


def charges_for(charges, reference_type=None, reference_id=None, kind=None):
    """Filter a charge list by reference (and optionally kind)."""
    out = charges
    if reference_type is not None:
        out = [c for c in out if c.get("reference_type") == reference_type]
    if reference_id is not None:
        out = [c for c in out if c.get("reference_id") == reference_id]
    if kind is not None:
        out = [c for c in out if c.get("kind") == kind]
    return out
