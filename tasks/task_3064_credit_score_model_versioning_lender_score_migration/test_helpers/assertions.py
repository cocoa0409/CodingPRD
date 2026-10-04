"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict) -> None:
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data["created_at"]), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data["updated_at"]), "updated_at must be ISO 8601 UTC"
    assert isinstance(data["version"], int) and data["version"] >= 1


def _append_only(data: dict) -> None:
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data["created_at"]), "created_at must be ISO 8601 UTC"


def assert_bureau(data: dict) -> None:
    _common(data)
    assert data["bureau_code"] in ("TUC", "EXP", "EQF")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["is_active"], bool)


def assert_score_model(data: dict) -> None:
    _common(data)
    assert data["family_code"] in ("FICO_CORE", "VANTAGE_STYLE")
    assert data["status"] in ("DEVELOPMENT", "RELEASED", "DEPRECATED", "RETIRED", "SUPERSEDED")
    assert isinstance(data["min_input_count"], int) and data["min_input_count"] >= 1
    assert isinstance(data["score_floor"], int)
    assert isinstance(data["score_ceiling"], int)
    assert isinstance(data["active_variant_count"], int)
    assert isinstance(data["cascade_depth"], int)


def assert_score_variant(data: dict) -> None:
    _common(data)
    assert data["industry"] in ("AUTO", "BANKCARD", "MORTGAGE", "PERSONAL_LOAN")
    assert data["status"] in ("DRAFT", "RELEASED", "RECALLED")
    assert isinstance(data["segment_offsets"], list) and len(data["segment_offsets"]) == 3


def assert_consumer(data: dict) -> None:
    _common(data)
    assert isinstance(data["consumer_ref"], str) and data["consumer_ref"]
    assert 18 <= data["age_years"] <= 120
    assert isinstance(data["is_protected_class"], bool)
    assert isinstance(data["model_undecided_count"], int) and data["model_undecided_count"] >= 0


def assert_archive_sample(data: dict) -> None:
    _common(data)
    assert isinstance(data["record_count"], int) and data["record_count"] >= 1
    assert data["segment_name"] in ("PRIME", "NEAR_PRIME", "SUBPRIME", "THIN_FILE")
    assert data["sample_kind"] in ("DEVELOPMENT", "VALIDATION")
    assert isinstance(data["observation_window_months"], int)


def assert_validation_study(data: dict) -> None:
    _common(data)
    assert data["study_path"] in ("PROTECTED_CLASS", "CROSS_BUREAU")
    assert data["status"] in ("SCHEDULED", "VALIDATION_COMPLETE", "BLOCKED", "COMPENSATED")
    assert isinstance(data["touched_model_ids"], list)
    assert isinstance(data["required_reason_codes"], list)


def assert_reference_set(data: dict) -> None:
    _common(data)
    assert data["status"] in ("COMPILED", "BOUND", "RECONCILED")


def assert_score_result(data: dict) -> None:
    _common(data)
    assert isinstance(data["raw_posted_score"], int)
    assert isinstance(data["effective_score"], int)
    assert isinstance(data["odds_at_posted_score"], (int, float))
    assert data["decision"] in (None, "APPROVE", "DECLINE", "UNDECIDED")


def assert_reason_code(data: dict) -> None:
    _common(data)
    assert data["depth_tier"] in ("PRIMARY", "SECONDARY", "TERTIARY")
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert isinstance(data["composite_code"], str) and data["composite_code"]
    assert isinstance(data["weight_pct"], (int, float))
    assert isinstance(data["weight_received_pct"], (int, float))
    assert isinstance(data["weight_effective_pct"], (int, float))


def assert_license(data: dict) -> None:
    _common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["entitlement_status"] in ("NOT_SET", "WITHIN_ENTITLEMENT", "OVER_ENTITLED")
    assert data["volume_tier"] in ("VOLUME_TIER_1", "VOLUME_TIER_2", "VOLUME_TIER_3")
    assert isinstance(data["cumulative_score_count"], int) and data["cumulative_score_count"] >= 0
    assert isinstance(data["cumulative_fee_cents"], int)
    assert isinstance(data["entitled_count"], int) and data["entitled_count"] >= 0


def assert_model_documentation(data: dict) -> None:
    _common(data)
    assert data["doc_type"] in ("MODEL_RISK_REPORT", "FAIR_LENDING_REPORT",
                                "ADVERSE_ACTION_MAP", "BUREAU_DISCREPANCY_REPORT")
    assert data["status"] in ("DRAFT", "FILED", "SUPPLEMENTED")
    assert isinstance(data["checksum"], str) and data["checksum"]


def assert_discovery_request(data: dict) -> None:
    _common(data)
    assert data["status"] in ("REGISTERED", "CONSUMED", "EXPIRED")
    assert is_iso8601_timestamp(data["requested_at"])


def assert_fee_ledger_entry(data: dict) -> None:
    """Append-only row: id and created_at only — no updated_at, no version."""
    _append_only(data)
    assert "updated_at" not in data, "FeeLedgerEntry is append-only: no updated_at"
    assert "version" not in data, "FeeLedgerEntry is append-only: no version"
    assert data["kind"] in ("MARGINAL_PRICING", "VOID_REVERSAL")
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["cumulative_count_before"], int)


def assert_migration_event(data: dict) -> None:
    """Append-only row: id and created_at only — no updated_at, no version."""
    _append_only(data)
    assert "updated_at" not in data, "MigrationEvent is append-only: no updated_at"
    assert "version" not in data, "MigrationEvent is append-only: no version"
    assert data["event_type"] in ("RECALIBRATED", "SNAPSHOT_COMPILED", "MIGRATED")
    assert isinstance(data["credited_delta_bps"], int)


# ─── Domain invariants ────────────────────────────────

def assert_license_invariants(data: dict) -> None:
    """Conserved quantities that hold after any licence mutation."""
    assert data["cumulative_score_count"] >= 0
    assert data["cumulative_fee_cents"] >= 0
    if data["status"] == "SUSPENDED":
        assert data["cumulative_score_count"] >= 0


def assert_cutoff_shape(decision: str, effective_score: int, cutoff_score: int) -> None:
    """The strict cut-off comparison: above approves, below declines, equal is undecided."""
    if effective_score > cutoff_score:
        assert decision == "APPROVE"
    elif effective_score < cutoff_score:
        assert decision == "DECLINE"
    else:
        assert decision == "UNDECIDED"


def assert_invariant_a(lam: int, p_value: int, b_value: int) -> None:
    """Invariant A: the void must cancel the settled charge exactly."""
    assert lam * (p_value - b_value) == 0, (
        f"Invariant A violated: lambda={lam}, P={p_value}, B={b_value}"
    )


def assert_bubble_up_total(children_weights: list, parent_received: float) -> None:
    """One-hop routing: the parent receives exactly the sum of below-floor children."""
    expected = round(sum(w for w in children_weights if w < 0.05), 4)
    assert abs(parent_received - expected) < 1e-9, (
        f"Expected routed share {expected}, got {parent_received}"
    )