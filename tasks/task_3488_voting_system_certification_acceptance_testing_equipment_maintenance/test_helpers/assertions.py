"""Entity assertions and domain invariant checkers.

AcceptanceTest and CustodyTransfer are immutable records that carry only
``id`` and ``created_at`` of the standard system fields (PRD §2.5), so their
assertions verify that ``updated_at`` and ``version`` are ABSENT.

The ``compute_*`` helpers re-derive PRD-calculated values (conformity
variants, deficiency index, print estimate, modification lead time, L&A
verdict) from PRD-pinned constants so tests can assert exact expected values
without re-embedding the arithmetic inline.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ACCEPTANCE_INDEX_CLAMP,
    ACCEPTANCE_INDEX_MAX,
    ACCEPTANCE_WEIGHTS,
    CONFORMITY_PASS_BP,
    FINAL_AGING_BP_PER_WEEK,
    FINAL_CRITICAL_WEIGHT,
    FINAL_MAJOR_WEIGHT,
    FINAL_MINOR_WEIGHT,
    FINAL_RESUBMISSION_PENALTY,
    LA_DISCREPANCY_MAX_BP,
    MOD_BASE_LEAD_DAYS,
    MOD_FEDERAL_CERT_ADD_DAYS,
    MOD_SCOPE_TOUCHING_ADD_DAYS,
    REAM_SHEETS,
    SCOPE_TOUCHING_COMPONENTS,
    SCREEN_CRITICAL_WEIGHT,
    SCREEN_MAJOR_WEIGHT,
    SCREEN_MINOR_WEIGHT,
    SCREEN_RESUBMISSION_PENALTY,
    TIER1_MAX_REAMS,
    TIER1_PRICE_CENTS,
    TIER2_MAX_REAMS,
    TIER2_PRICE_CENTS,
    TIER3_PRICE_CENTS,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_immutable_record_fields(data: dict):
    """AcceptanceTest / CustodyTransfer: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "immutable records must not carry updated_at"
    assert "version" not in data, "immutable records must not carry version"


def assert_voting_system(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["model_name"], str) and data["model_name"]
    assert isinstance(data["software_baseline_version"], str)
    assert data["hardware_class"] in [
        "OPTICAL_SCANNER",
        "BALLOT_MARKING_DEVICE",
        "CENTRAL_TABULATOR",
    ]
    assert data["status"] in ["REGISTERED", "FIELDED", "RETIRED"]


def assert_test_laboratory(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lab_code"], str) and data["lab_code"]
    assert isinstance(data["lab_name"], str) and data["lab_name"]
    assert data["accreditation_scope"] in ["FEDERAL", "STATE", "DUAL"]
    assert isinstance(data["max_concurrent_campaigns"], int)
    assert 1 <= data["max_concurrent_campaigns"] <= 10
    assert data["status"] in ["ACCREDITED", "SUSPENDED"]


def assert_certification_campaign(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["voting_system_id"])
    assert is_valid_uuid(data["lab_id"])
    assert data["guidelines_baseline"] in ["VVSG_1_1", "VVSG_2_0"]
    assert data.get("state_code") is None or (
        isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    )
    assert data["status"] in [
        "SUBMITTED",
        "IN_TEST",
        "DEFICIENCIES_FILED",
        "CERTIFIED",
        "DENIED",
        "WITHDRAWN",
    ]
    for counter in (
        "resubmission_count",
        "open_critical_count",
        "open_major_count",
        "open_minor_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    for score in ("conformity_screen_bp", "conformity_final_bp"):
        assert isinstance(data[score], int) and 0 <= data[score] <= 10000
    assert is_iso8601_timestamp(data["last_submitted_at"])
    assert data.get("completed_at") is None or is_iso8601_timestamp(data["completed_at"])


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["voting_system_id"])
    assert is_valid_uuid(data["campaign_id"])
    assert data["scope"] in ["FEDERAL", "STATE"]
    assert data.get("state_code") is None or len(data["state_code"]) == 2
    assert data["guidelines_baseline"] in ["VVSG_1_1", "VVSG_2_0"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ["ACTIVE", "SUSPENDED", "REVOKED", "EXPIRED"]


def assert_jurisdiction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    for field in ("budget_total_cents", "available_cents", "encumbered_cents", "spent_cents"):
        assert isinstance(data[field], int)


def assert_jurisdiction_ledger_invariant(data: dict):
    """PRD §2.8 conserved ledger: total == available + encumbered + spent."""
    assert data["budget_total_cents"] == (
        data["available_cents"] + data["encumbered_cents"] + data["spent_cents"]
    ), (
        f"ledger invariant violated: total {data['budget_total_cents']} != "
        f"{data['available_cents']} + {data['encumbered_cents']} + {data['spent_cents']}"
    )


def assert_election_official(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["badge_no"], str) and data["badge_no"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_procurement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_valid_uuid(data["voting_system_id"])
    assert is_valid_uuid(data["certificate_id"])
    assert isinstance(data["certificate_version_pinned"], int)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["total_price_cents"], int)
    assert data["total_price_cents"] == data["quantity"] * data["unit_price_cents"]
    assert isinstance(data["cert_hold"], bool)
    assert data["status"] in [
        "PLACED",
        "DELIVERED",
        "ACCEPTANCE_TESTING",
        "ACCEPTED",
        "REJECTED",
        "CANCELLED",
    ]
    assert data.get("status_reason") is None or isinstance(data["status_reason"], str)


def assert_acceptance_test(data: dict):
    _assert_immutable_record_fields(data)
    assert is_valid_uuid(data["procurement_id"])
    assert data["test_type"] in [
        "HARDWARE_DIAGNOSTIC",
        "BALLOT_SCAN_CALIBRATION",
        "LOGIC_VERIFICATION",
    ]
    for field in ("critical_defects", "major_defects", "minor_defects"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["deficiency_index"], int)
    assert 0 <= data["deficiency_index"] <= ACCEPTANCE_INDEX_CLAMP
    assert data["result"] in ["PASS", "FAIL"]


def assert_election_definition(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_valid_uuid(data["procurement_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["election_date"], str) and len(data["election_date"]) == 10
    assert isinstance(data["precinct_count"], int) and data["precinct_count"] >= 1
    assert "ballot_layout" in data
    assert isinstance(data["layout_revision"], int) and data["layout_revision"] >= 0
    assert data.get("paper_weight_gsm") is None or isinstance(data["paper_weight_gsm"], int)
    assert data.get("paper_thickness_microns") is None or isinstance(
        data["paper_thickness_microns"], int
    )
    assert data.get("paper_coating") is None or data["paper_coating"] in ["UNCOATED", "COATED"]
    assert data["status"] in [
        "DRAFT",
        "PROGRAMMED",
        "LA_PASSED",
        "LOCKED",
        "CANVASSING",
        "CLOSED",
        "CANCELLED",
    ]
    assert data.get("status_reason") is None or isinstance(data["status_reason"], str)


def assert_logic_accuracy_test(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["election_definition_id"])
    assert is_valid_uuid(data["conducted_by"])
    assert data.get("certified_by") is None or is_valid_uuid(data["certified_by"])
    assert isinstance(data["expected_tallies"], dict)
    assert isinstance(data["scanned_tallies"], dict)
    assert set(data["expected_tallies"].keys()) == set(data["scanned_tallies"].keys())
    assert isinstance(data["total_expected"], int) and data["total_expected"] >= 1
    assert isinstance(data["total_discrepancy"], int) and data["total_discrepancy"] >= 0
    assert isinstance(data["discrepancy_bp"], int) and data["discrepancy_bp"] >= 0
    assert data["result"] in ["PASS", "FAIL"]
    assert data["status"] in ["CONDUCTED", "CERTIFIED", "CHALLENGED"]


def assert_equipment_unit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_valid_uuid(data["voting_system_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["operational_status"] in [
        "IN_STORAGE",
        "IN_SERVICE",
        "IN_MAINTENANCE",
        "QUARANTINED",
        "RETIRED",
    ]
    assert data["custody_status"] in ["SECURED", "UNSEALED"]
    assert is_valid_uuid(data["current_custodian_id"])
    assert isinstance(data["battery_cycles"], int) and data["battery_cycles"] >= 0
    assert isinstance(data["storage_excursion_count"], int)
    assert data["storage_excursion_count"] >= 0
    assert data.get("pre_maintenance_status") is None or data["pre_maintenance_status"] in [
        "IN_STORAGE",
        "IN_SERVICE",
    ]
    assert data.get("calibrated_paper_weight_gsm") is None or isinstance(
        data["calibrated_paper_weight_gsm"], int
    )
    assert data.get("calibrated_paper_thickness_microns") is None or isinstance(
        data["calibrated_paper_thickness_microns"], int
    )


def assert_maintenance_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["equipment_unit_id"])
    assert data["work_type"] in [
        "PREVENTIVE",
        "BATTERY_REPLACEMENT",
        "REPAIR",
        "CALIBRATION",
        "RESEAL",
    ]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["scheduled_end"] > data["scheduled_start"]
    assert data.get("resolution_note") is None or isinstance(data["resolution_note"], str)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED"]


def assert_custody_transfer(data: dict):
    _assert_immutable_record_fields(data)
    assert is_valid_uuid(data["equipment_unit_id"])
    assert is_valid_uuid(data["from_official_id"])
    assert is_valid_uuid(data["to_official_id"])
    assert data["from_official_id"] != data["to_official_id"]
    assert isinstance(data["seal_number"], str) and data["seal_number"]
    assert isinstance(data["seal_intact"], bool)
    assert is_iso8601_timestamp(data["transferred_at"])


def assert_software_modification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["voting_system_id"])
    assert isinstance(data["description"], str)
    assert isinstance(data["component_codes"], list) and len(data["component_codes"]) >= 1
    for code in data["component_codes"]:
        assert code in [
            "BALLOT_LAYOUT_ENGINE",
            "TABULATION_FIRMWARE",
            "ELECTION_MANAGEMENT_UI",
            "AUDIT_LOG_SERVICE",
            "SECURITY_MODULE",
        ]
    assert data.get("classification") is None or data["classification"] in [
        "DE_MINIMIS",
        "RECERTIFICATION_REQUIRED",
    ]
    assert data.get("lead_time_days") is None or isinstance(data["lead_time_days"], int)
    assert is_iso8601_timestamp(data["submitted_at"])
    assert data.get("classified_at") is None or is_iso8601_timestamp(data["classified_at"])
    assert data.get("effective_at") is None or is_iso8601_timestamp(data["effective_at"])
    assert data.get("new_baseline_version") is None or isinstance(
        data["new_baseline_version"], str
    )
    assert data["status"] in [
        "PROPOSED",
        "DE_MINIMIS_APPROVED",
        "RECERTIFICATION_PENDING",
        "EFFECTIVE",
        "REJECTED",
        "WITHDRAWN",
    ]


def assert_post_election_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["election_definition_id"])
    assert data["audit_type"] in ["RISK_LIMITING", "COMPLIANCE", "FULL_RECOUNT"]
    for field in ("critical_findings", "major_findings", "minor_findings"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["report_public"], bool)
    assert data.get("published_at") is None or is_iso8601_timestamp(data["published_at"])
    assert data["status"] in [
        "INITIATED",
        "FINDINGS_FILED",
        "CLOSED_CONFIRMED",
        "CLOSED_ESCALATED",
    ]


# ---------------------------------------------------------------------------
# PRD calculation re-derivations (expected-value helpers for tests)
# ---------------------------------------------------------------------------
def compute_conformity_screen_bp(
    open_critical_count: int,
    open_major_count: int,
    open_minor_count: int,
    resubmission_count: int,
) -> int:
    """PRD §3.2 screening variant: 10000 - 1200c - 300M - 75m - 250r, floored
    at zero. Forward-looking; ignores calendar aging."""
    score = (
        10000
        - SCREEN_CRITICAL_WEIGHT * open_critical_count
        - SCREEN_MAJOR_WEIGHT * open_major_count
        - SCREEN_MINOR_WEIGHT * open_minor_count
        - SCREEN_RESUBMISSION_PENALTY * resubmission_count
    )
    return max(0, score)


def compute_conformity_final_bp(
    open_critical_count: int,
    open_major_count: int,
    open_minor_count: int,
    resubmission_count: int,
    last_submitted_at: str,
    now_iso: str,
) -> int:
    """PRD §3.2 final-audit variant: 10000 - 1500c - 250M - 50m - 400r
    - 10 * (full weeks elapsed since last_submitted_at), floored at zero."""
    last = _parse_instant(last_submitted_at)
    now = _parse_instant(now_iso)
    days_open = int((now - last).total_seconds() // 86400)
    score = (
        10000
        - FINAL_CRITICAL_WEIGHT * open_critical_count
        - FINAL_MAJOR_WEIGHT * open_major_count
        - FINAL_MINOR_WEIGHT * open_minor_count
        - FINAL_RESUBMISSION_PENALTY * resubmission_count
        - FINAL_AGING_BP_PER_WEEK * (days_open // 7)
    )
    return max(0, score)


def compute_deficiency_index(
    test_type: str, critical_defects: int, major_defects: int, minor_defects: int
) -> int:
    """PRD §3.4: min(100, wc*critical + wm*major + wn*minor), weights selected
    by test_type."""
    wc, wm, wn = ACCEPTANCE_WEIGHTS[test_type]
    return min(
        ACCEPTANCE_INDEX_CLAMP,
        wc * critical_defects + wm * major_defects + wn * minor_defects,
    )


def compute_acceptance_result(
    test_type: str, critical_defects: int, major_defects: int, minor_defects: int
) -> str:
    """PRD §3.4: PASS iff critical_defects == 0 and deficiency_index <= 20."""
    index = compute_deficiency_index(
        test_type, critical_defects, major_defects, minor_defects
    )
    return "PASS" if critical_defects == 0 and index <= ACCEPTANCE_INDEX_MAX else "FAIL"


def compute_la_result(total_discrepancy: int, total_expected: int) -> str:
    """PRD §3.6: PASS iff 10000 * total_discrepancy <= 50 * total_expected
    (exact integer comparison; the floored discrepancy_bp never decides)."""
    return (
        "PASS"
        if 10000 * total_discrepancy <= LA_DISCREPANCY_MAX_BP * total_expected
        else "FAIL"
    )


def compute_print_estimate(ballots_per_precinct: int, precinct_count: int) -> dict:
    """PRD §3.5 pinned order: per-precinct ceil BEFORE aggregation; tier
    selected on the aggregate ream count."""
    reams_per_precinct = -(-ballots_per_precinct // REAM_SHEETS)  # ceil division
    total_reams = reams_per_precinct * precinct_count
    if total_reams <= TIER1_MAX_REAMS:
        tier_price_cents = TIER1_PRICE_CENTS
    elif total_reams <= TIER2_MAX_REAMS:
        tier_price_cents = TIER2_PRICE_CENTS
    else:
        tier_price_cents = TIER3_PRICE_CENTS
    return {
        "precinct_count": precinct_count,
        "ballots_per_precinct": ballots_per_precinct,
        "reams_per_precinct": reams_per_precinct,
        "total_reams": total_reams,
        "tier_price_cents": tier_price_cents,
        "total_cost_cents": total_reams * tier_price_cents,
    }


def compute_lead_time_days(component_codes, has_active_or_suspended_federal_cert) -> int:
    """PRD §3.9: base 30; +60 when component_codes touches TABULATION_FIRMWARE
    or BALLOT_LAYOUT_ENGINE; +45 when a FEDERAL certificate is ACTIVE or
    SUSPENDED — evaluated strictly before any classification cascade."""
    lead = MOD_BASE_LEAD_DAYS
    if any(code in SCOPE_TOUCHING_COMPONENTS for code in component_codes):
        lead += MOD_SCOPE_TOUCHING_ADD_DAYS
    if has_active_or_suspended_federal_cert:
        lead += MOD_FEDERAL_CERT_ADD_DAYS
    return lead


def _parse_instant(iso: str) -> datetime:
    """Parse an ISO 8601 UTC instant (accepts trailing Z)."""
    text = iso.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# Re-exported for convenience so test modules can cite the certification gate.
__all_conformity_gate__ = CONFORMITY_PASS_BP
