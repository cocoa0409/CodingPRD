"""Entity assertions, text normalization and domain invariant checkers."""
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)

from .constants import PRODUCT_CLASS_DURABILITY_FACTOR

_SECOND_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MILLI_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def normalize(text: str) -> str:
    """The PRD normalization procedure: trim, collapse internal whitespace runs
    to a single space, then uppercase."""
    return re.sub(r"\s+", " ", (text or "").strip()).upper()


def assert_second_precision_instant(value: str, field: str = "instant"):
    assert isinstance(value, str) and _SECOND_INSTANT.match(value), (
        f"{field} must be an ISO 8601 UTC instant with second precision and a "
        f"trailing Z, got {value!r}"
    )


def assert_millisecond_instant(value: str, field: str = "timestamp"):
    assert isinstance(value, str) and _MILLI_INSTANT.match(value), (
        f"{field} must be an ISO 8601 UTC instant with three fractional digits, "
        f"got {value!r}"
    )


def parse_instant(value: str) -> datetime:
    return datetime.strptime(value.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")


def shift_instant(value: str, days: int = 0, hours: int = 0, seconds: int = 0) -> str:
    moved = parse_instant(value) + timedelta(days=days, hours=hours, seconds=seconds)
    return moved.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def round_half_up(value, places: int = 2) -> float:
    from decimal import Decimal, ROUND_HALF_UP
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def expected_durability_floor(min_cycles_by_market, market_codes, product_class) -> int:
    """The PRD durability floor: greatest min_durability_cycles over the given
    markets, scaled by the product-class factor, rounded up."""
    base = max(min_cycles_by_market[m] for m in market_codes)
    return math.ceil(base * PRODUCT_CLASS_DURABILITY_FACTOR[product_class])


def expected_content_hash(fiber_content_text, origin_text, wash_temp_c, bleach_code,
                          dry_code, iron_code, dryclean_code, identity_display_mode,
                          languages, rn_number=None, legal_name=None) -> str:
    """The PRD canonical content fingerprint."""
    care = "/".join([str(wash_temp_c), bleach_code, dry_code, iron_code, dryclean_code])
    identity = rn_number if identity_display_mode == "RN" else normalize(legal_name or "")
    joined = "|".join([
        normalize(fiber_content_text),
        normalize(origin_text),
        care,
        identity or "",
        ",".join(sorted(languages)),
    ])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# --- common field assertions -------------------------------------------


def assert_common_fields(data: dict, entity: str = "resource"):
    """id, created_at, updated_at and version for a versioned resource."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID with no prefix"
    assert_millisecond_instant(data.get("created_at", ""), f"{entity}.created_at")
    assert_millisecond_instant(data.get("updated_at", ""), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_brand(data: dict):
    assert_common_fields(data, "brand")
    assert isinstance(data["legal_name"], str) and data["legal_name"].strip()
    assert data["party_type"] in ("BRAND_OWNER", "PRIVATE_LABEL_RETAILER", "LICENSEE")
    assert data["responsibility_mode"] in ("SELF_OF_RECORD", "LICENSOR_OF_RECORD")
    assert data["posture"] in ("OPEN", "RESTRICTED", "SUSPENDED")
    assert data["outstanding_penalty_usd"] >= 0
    assert_cost_precision(data["outstanding_penalty_usd"])
    assert isinstance(data["critical_audit_finding_count"], int)
    if data["responsibility_mode"] == "LICENSOR_OF_RECORD":
        assert data["responsible_brand_id"] == data["licensor_brand_id"]
    else:
        assert data["responsible_brand_id"] == data["id"]


def assert_market_requirement(data: dict):
    """A market regime carries only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "market requirement id must be a UUID"
    assert_millisecond_instant(data.get("created_at", ""), "created_at")
    assert "updated_at" not in data, "a market regime never emits updated_at"
    assert "version" not in data, "a market regime never emits version"
    assert re.match(r"^[A-Z_]{2,8}$", data["market_code"])
    assert isinstance(data["required_languages"], list) and data["required_languages"]
    assert 0.0 <= data["fiber_tolerance_pp"] <= 5.0
    assert 0.0 <= data["absolute_claim_tolerance_pp"] <= 1.0
    assert isinstance(data["min_durability_cycles"], int) and data["min_durability_cycles"] >= 0
    assert 0.0 <= data["marking_duty_rate"] <= 0.5
    assert isinstance(data["requires_identity_disclosure"], bool)
    assert isinstance(data["requires_origin_statement"], bool)


def assert_style(data: dict):
    assert_common_fields(data, "style")
    assert is_valid_uuid(data["brand_id"])
    assert isinstance(data["style_code"], str) and 1 <= len(data["style_code"]) <= 32
    assert data["product_class"] in (
        "WOVEN_OUTERWEAR", "KNIT_TOP", "HOSIERY", "HOME_TEXTILE")
    assert isinstance(data["target_market_codes"], list) and data["target_market_codes"]
    assert data["net_weight_grams"] > 0
    assert isinstance(data["declared_fibers"], list)
    assert data["substantiation_state"] in (
        "FIBER_DECLARED", "FIBER_TEST_PENDING", "FIBER_SUBSTANTIATED", "FIBER_MISSTATED")
    assert data["origin_state"] in (
        "ORIGIN_UNDETERMINED", "ORIGIN_DRAFTED", "ORIGIN_ISSUED")
    assert data["label_readiness"] in ("READY", "BLOCKED")
    assert isinstance(data["effective_fiber_content_text"], str)
    assert_style_readiness_invariant(data)


def assert_style_readiness_invariant(data: dict):
    """label_readiness reads READY only when both dimensions are satisfied."""
    ready = (data["substantiation_state"] == "FIBER_SUBSTANTIATED"
             and data["origin_state"] == "ORIGIN_ISSUED")
    expected = "READY" if ready else "BLOCKED"
    assert data["label_readiness"] == expected, (
        f"Expected label_readiness {expected} for substantiation_state="
        f"{data['substantiation_state']} and origin_state={data['origin_state']}, "
        f"got {data['label_readiness']}"
    )


def assert_material_input(data: dict):
    assert_common_fields(data, "material input")
    assert is_valid_uuid(data["style_id"])
    assert data["stage"] in ("FIBER", "YARN", "FABRIC", "CUT_AND_SEW", "TRIM")
    assert re.match(r"^[A-Z]{2}$", data["country_code"])
    assert data["value_added_usd"] >= 0
    assert data["weight_grams"] >= 0
    assert isinstance(data["is_ornamentation"], bool)
    assert isinstance(data["depth"], int) and data["depth"] >= 0
    if data["parent_input_id"] is None:
        assert data["depth"] == 0, "a graph root has depth 0"


def assert_lab_test(data: dict):
    assert_common_fields(data, "lab test")
    assert is_valid_uuid(data["style_id"])
    assert data["test_type"] in ("FIBER_CONTENT", "CARE_PERFORMANCE")
    assert data["method"] in ("AATCC_20A", "ISO_1833", "AATCC_135", "ISO_6330")
    assert data["state"] in ("BENCH_RESERVED", "PASSED", "FAILED", "SUPERSEDED")
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert_second_precision_instant(data["specimen_received_at"], "specimen_received_at")
    assert_second_precision_instant(data["results_due_at"], "results_due_at")
    if data.get("valid_until") is not None:
        assert_second_precision_instant(data["valid_until"], "valid_until")
    if data["test_type"] == "FIBER_CONTENT":
        assert data["wash_temp_c"] is None
    else:
        assert data["wash_temp_c"] in (20, 30, 40, 60, 95)
        assert data["result_delta_pp_max"] is None


def assert_origin_determination(data: dict):
    assert_common_fields(data, "origin determination")
    assert is_valid_uuid(data["style_id"])
    assert data["state"] in ("DRAFT", "ISSUED", "SUPERSEDED", "VOID")
    assert re.match(r"^[A-Z]{2}$", data["st_country"])
    assert re.match(r"^[A-Z]{2}$", data["yf_country"])
    assert data["divergent"] == (data["st_country"] != data["yf_country"])
    assert isinstance(data["graph_node_count"], int)
    if data["state"] == "DRAFT":
        assert data["method_pinned"] is None
        assert data["determined_country"] is None
    if data.get("issued_at") is not None:
        assert_second_precision_instant(data["issued_at"], "issued_at")


def assert_label_spec(data: dict):
    assert_common_fields(data, "label spec")
    assert is_valid_uuid(data["style_id"])
    assert data["artifact_type"] in ("PERMANENT_LABEL", "HANGTAG")
    assert data["state"] in ("DRAFT", "PENDING_APPROVAL", "REVISION_REQUESTED",
                            "APPROVED", "PUBLISHED", "WITHDRAWN")
    assert isinstance(data["market_codes"], list) and data["market_codes"]
    assert isinstance(data["languages"], list) and data["languages"]
    assert data["placement_code"] in ("NECK_CENTER_INSIDE", "SIDE_SEAM_INSIDE",
                                     "WAISTBAND_INSIDE", "NOT_PERMANENT")
    assert isinstance(data["durability_cycles_rating"], int)
    assert data["identity_display_mode"] in ("RN", "COMPANY_NAME")
    assert 1 <= len(data["fiber_content_text"]) <= 200
    assert 1 <= len(data["origin_text"]) <= 64
    assert isinstance(data["marketing_claims"], list)
    assert re.match(r"^[0-9a-f]{64}$", data["content_hash"]), (
        "content_hash must be lowercase hexadecimal SHA-256"
    )
    if data["artifact_type"] == "PERMANENT_LABEL":
        assert data["parent_label_spec_id"] is None
        assert data["consistency_state"] == "NOT_APPLICABLE"
        assert data["marketing_claims"] == []
    else:
        assert data["consistency_state"] in ("CONSISTENT", "INCONSISTENT")
        assert data["origin_determination_id"] is None
        assert data["care_test_id"] is None
        assert data["placement_code"] == "NOT_PERMANENT"


def assert_import_shipment(data: dict):
    assert_common_fields(data, "import shipment")
    assert is_valid_uuid(data["importer_brand_id"])
    assert is_valid_uuid(data["style_id"])
    assert data["marking_state"] in ("ENTRY_FILED", "MARKING_COMPLIANT",
                                    "REDELIVERY_ORDERED", "MARKING_CORRECTED")
    assert data["quantity_units"] > 0
    assert data["declared_value_usd"] > 0
    assert_cost_precision(data["declared_value_usd"])
    assert_cost_precision(data["penalty_assessed_usd"])
    assert_cost_precision(data["penalty_mitigated_usd"])
    assert isinstance(data["corrected_units"], int) and data["corrected_units"] >= 0
    if data.get("review_decided_at") is not None:
        assert_second_precision_instant(data["review_decided_at"], "review_decided_at")
    if data.get("redelivery_deadline_at") is not None:
        assert_second_precision_instant(data["redelivery_deadline_at"],
                                        "redelivery_deadline_at")


def assert_compliance_audit(data: dict):
    assert_common_fields(data, "compliance audit")
    assert is_valid_uuid(data["brand_id"])
    assert data["scope"] in ("STYLE_DOSSIER", "MARKET_LABELING", "IMPORT_MARKING")
    assert data["state"] in ("OPEN", "IN_REVIEW", "PENDING_CLOSURE", "CLOSED")
    for field in ("open_finding_count", "critical_finding_count", "units_in_scope"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["critical_finding_count"] <= data["open_finding_count"]
    assert_second_precision_instant(data["audit_window_from"], "audit_window_from")
    assert_second_precision_instant(data["audit_window_to"], "audit_window_to")
    if data.get("closed_at") is not None:
        assert_second_precision_instant(data["closed_at"], "closed_at")


def assert_audit_finding(data: dict):
    assert_common_fields(data, "audit finding")
    assert is_valid_uuid(data["audit_id"])
    assert is_valid_uuid(data["style_id"])
    assert data["state"] in ("OPEN", "REMEDIATED", "CLOSED")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["units_affected"] > 0
    assert_finding_unit_conservation(data)
    if data.get("disposition_recorded_at") is not None:
        assert_second_precision_instant(data["disposition_recorded_at"],
                                        "disposition_recorded_at")
    if data.get("verified_at") is not None:
        assert_second_precision_instant(data["verified_at"], "verified_at")


def assert_finding_unit_conservation(data: dict):
    """The four buckets must add back up to the affected total, and the
    unresolved remainder may never be negative."""
    total = (data["units_relabeled"] + data["units_destroyed"]
             + data["units_released"] + data["units_unresolved"])
    assert data["units_unresolved"] >= 0, "units_unresolved must never be negative"
    assert total == data["units_affected"], (
        f"Expected the four buckets to sum to units_affected="
        f"{data['units_affected']}, got {total}"
    )
