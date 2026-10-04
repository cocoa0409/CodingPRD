"""Entity assertions and domain invariant checkers.

Every entity carries the common system fields (PRD section 2.5): id (UUID),
created_at / updated_at (ISO 8601), and an integer version. Fields the PRD
describes as "null until <event>" are validated only when present and not
None — a faithful implementation may omit or null them before that event.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Shared field checkers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def _assert_optional_str(data: dict, field: str, entity: str):
    if data.get(field) is not None:
        assert isinstance(data[field], str), f"{entity}.{field} must be a string when set"


def _assert_optional_int(data: dict, field: str, entity: str):
    if data.get(field) is not None:
        assert isinstance(data[field], int) and not isinstance(data[field], bool), \
            f"{entity}.{field} must be an integer when set"


def _assert_optional_timestamp(data: dict, field: str, entity: str):
    if data.get(field) is not None:
        assert is_iso8601_timestamp(data[field]), \
            f"{entity}.{field} must be an ISO 8601 timestamp when set"


def _assert_enum(data: dict, field: str, allowed: list, entity: str):
    assert data.get(field) in allowed, \
        f"{entity}.{field} must be one of {allowed}, got {data.get(field)!r}"


# ---------------------------------------------------------------------------
# Dealer domain
# ---------------------------------------------------------------------------
DEALER_STATUSES = ["PENDING", "AUTHORIZED", "PROBATION", "SUSPENDED", "TERMINATED"]
APPLICATION_STATUSES = ["SUBMITTED", "VETTING", "APPROVED", "REJECTED"]
INSPECTION_STATUSES = ["UNSCHEDULED", "SCHEDULED", "PASSED", "FAILED"]
DOCS_STATUSES = ["PENDING", "VERIFIED", "REJECTED"]


def assert_dealer(data: dict):
    _assert_common_fields(data, "Dealer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["storefront_address"], str) and data["storefront_address"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    _assert_enum(data, "tier", ["STANDARD", "PREMIER"], "Dealer")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert 0 <= data["sell_through_pct"] <= 100, "sell_through_pct must be within 0..100"
    assert isinstance(data["tenure_years"], int) and data["tenure_years"] >= 0
    _assert_enum(data, "status", DEALER_STATUSES, "Dealer")
    assert isinstance(data["storefront_verified"], bool)
    assert isinstance(data["brand_presentation_score"], int)
    # Standing fields recomputed on every read (PRD section 3.1).
    assert isinstance(data["infraction_points"], int) and data["infraction_points"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int) \
        and data["outstanding_balance_cents"] >= 0
    assert isinstance(data["allocation_score"], (int, float)) \
        and not isinstance(data["allocation_score"], bool)


def assert_dealer_application(data: dict):
    _assert_common_fields(data, "DealerApplication")
    assert is_valid_uuid(data.get("dealer_id", "")), "dealer_id must be a valid UUID"
    assert isinstance(data["has_physical_storefront"], bool)
    assert isinstance(data["storefront_sqft"], int) and data["storefront_sqft"] > 0
    assert isinstance(data["document_refs"], list)
    _assert_enum(data, "status", APPLICATION_STATUSES, "DealerApplication")
    _assert_enum(data, "inspection_status", INSPECTION_STATUSES, "DealerApplication")
    _assert_enum(data, "docs_status", DOCS_STATUSES, "DealerApplication")
    _assert_optional_str(data, "inspector_user_id", "DealerApplication")
    _assert_optional_timestamp(data, "inspection_window_start", "DealerApplication")
    _assert_optional_timestamp(data, "inspection_window_end", "DealerApplication")
    _assert_optional_int(data, "brand_presentation_score", "DealerApplication")
    _assert_optional_str(data, "inspection_recorded_by", "DealerApplication")
    _assert_optional_str(data, "docs_reviewed_by", "DealerApplication")
    _assert_optional_str(data, "decision_reason", "DealerApplication")


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------
CASE_STATUSES = ["UNDER_REVIEW", "ESCALATED_LEGAL", "CONFIRMED_VIOLATION",
                 "DISMISSED", "OVERTURNED"]
INFRACTION_STATES = ["NONE", "ACTIVE", "EXPIRED", "OVERTURNED"]


def assert_enforcement_case(data: dict):
    _assert_common_fields(data, "EnforcementCase")
    _assert_enum(data, "marketplace", ["AMAZON", "EBAY", "WALMART", "OTHER"],
                 "EnforcementCase")
    assert isinstance(data["seller_handle"], str) and data["seller_handle"]
    assert isinstance(data["listing_url"], str) and data["listing_url"]
    if data.get("matched_dealer_id") is not None:
        assert is_valid_uuid(data["matched_dealer_id"]), \
            "matched_dealer_id must be a valid UUID when set"
    _assert_enum(data, "status", CASE_STATUSES, "EnforcementCase")
    if data.get("infraction_category") is not None:
        _assert_enum(data, "infraction_category",
                     ["MAP_VIOLATION", "UNAUTHORIZED_MARKETPLACE",
                      "BRAND_STANDARD", "CHANNEL_DIVERSION"], "EnforcementCase")
    assert isinstance(data["infraction_points"], int) and data["infraction_points"] >= 0
    _assert_optional_timestamp(data, "infraction_issued_at", "EnforcementCase")
    _assert_optional_timestamp(data, "infraction_expires_at", "EnforcementCase")
    _assert_enum(data, "infraction_state", INFRACTION_STATES, "EnforcementCase")
    _assert_optional_str(data, "resolution_notes", "EnforcementCase")


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
def assert_product_line(data: dict):
    _assert_common_fields(data, "ProductLine")
    assert isinstance(data["name"], str) and data["name"]
    _assert_enum(data, "category", ["HARD_COOLER", "SOFT_GOOD", "DRINKWARE"], "ProductLine")
    assert isinstance(data["base_sku"], str) and data["base_sku"]
    assert isinstance(data["base_custom_price_cents"], int) \
        and data["base_custom_price_cents"] > 0
    assert isinstance(data["map_price_cents"], int) and data["map_price_cents"] > 0
    assert isinstance(data["min_custom_quantity"], int) \
        and data["min_custom_quantity"] >= 1
    for field in ("warranty_months_lid", "warranty_months_insulation",
                  "warranty_months_hardware"):
        assert isinstance(data[field], int) and data[field] > 0, \
            f"ProductLine.{field} must be a positive integer"
    _assert_enum(data, "status", ["ACTIVE", "DISCONTINUED"], "ProductLine")


DROP_STATUSES = ["ANNOUNCED", "ALLOCATION_OPEN", "ALLOCATION_LOCKED", "LIVE", "CLOSED"]


def assert_colorway_drop(data: dict):
    _assert_common_fields(data, "ColorwayDrop")
    assert is_valid_uuid(data.get("product_line_id", "")), \
        "product_line_id must be a valid UUID"
    assert isinstance(data["color_name"], str) and data["color_name"]
    assert isinstance(data["pantone_code"], str) and data["pantone_code"]
    _assert_enum(data, "drop_type", ["STANDARD", "LIMITED_EDITION"], "ColorwayDrop")
    assert isinstance(data["total_units"], int) and data["total_units"] > 0
    assert isinstance(data["dtc_reserved_units"], int) \
        and 0 <= data["dtc_reserved_units"] <= data["total_units"]
    assert isinstance(data["dealer_unit_price_cents"], int) \
        and data["dealer_unit_price_cents"] > 0
    for field in ("allocation_opens_at", "allocation_closes_at", "go_live_at",
                  "sales_end_at"):
        assert is_iso8601_timestamp(data.get(field, "")), \
            f"ColorwayDrop.{field} must be an ISO 8601 timestamp"
    _assert_enum(data, "status", DROP_STATUSES, "ColorwayDrop")
    for field in ("dealer_committed_units", "warranty_reserved_units",
                  "unallocated_units"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"ColorwayDrop.{field} must be a non-negative integer"


def assert_drop_unit_ledger_invariant(data: dict):
    """PRD section 2.10: total_units == dealer_committed_units +
    dtc_reserved_units + warranty_reserved_units + unallocated_units."""
    assert data["total_units"] == (
        data["dealer_committed_units"]
        + data["dtc_reserved_units"]
        + data["warranty_reserved_units"]
        + data["unallocated_units"]
    ), (
        f"drop unit ledger broken: total {data['total_units']} != "
        f"committed {data['dealer_committed_units']} + dtc {data['dtc_reserved_units']} "
        f"+ warranty {data['warranty_reserved_units']} + unallocated {data['unallocated_units']}"
    )


ALLOCATION_STATUSES = ["REQUESTED", "ALLOCATED", "EXPIRED", "FORFEITED"]


def assert_launch_allocation(data: dict):
    _assert_common_fields(data, "LaunchAllocation")
    assert is_valid_uuid(data.get("dealer_id", "")), "dealer_id must be a valid UUID"
    assert is_valid_uuid(data.get("drop_id", "")), "drop_id must be a valid UUID"
    assert isinstance(data["requested_units"], int) and data["requested_units"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0
    _assert_enum(data, "status", ALLOCATION_STATUSES, "LaunchAllocation")
    if data.get("forfeit_reason") is not None:
        _assert_enum(data, "forfeit_reason",
                     ["DEALER_CHOICE", "DEALER_SUSPENDED", "DEALER_TERMINATED"],
                     "LaunchAllocation")


# ---------------------------------------------------------------------------
# Customization orders and artwork proofs
# ---------------------------------------------------------------------------
ARTWORK_STATUSES = ["NO_ART", "PROOF_SUBMITTED", "CHANGES_REQUESTED",
                    "ART_APPROVED", "PROOF_EXHAUSTED"]
SCHEDULE_STATUSES = ["UNSCHEDULED", "RESERVED", "CONFIRMED", "IN_PRODUCTION", "COMPLETE"]
PAYMENT_STATUSES = ["UNPAID", "AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED"]
RETURN_STATUSES = ["NONE", "RETURN_REQUESTED", "RETURN_DENIED", "RETURN_SETTLED"]
RESERVATION_STATUSES = ["NONE", "HELD", "WAITLISTED", "CONFIRMED", "CONSUMED", "RELEASED"]


def assert_customization_order(data: dict):
    _assert_common_fields(data, "CustomizationOrder")
    _assert_enum(data, "buyer_type", ["CORPORATE", "INDIVIDUAL"], "CustomizationOrder")
    assert isinstance(data["buyer_ref"], str) and data["buyer_ref"]
    assert is_valid_uuid(data.get("product_line_id", "")), \
        "product_line_id must be a valid UUID"
    assert is_valid_uuid(data.get("colorway_drop_id", "")), \
        "colorway_drop_id must be a valid UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["declared_color_count"], int) \
        and 1 <= data["declared_color_count"] <= 8
    assert isinstance(data["declared_placement_count"], int) \
        and 1 <= data["declared_placement_count"] <= 4
    _assert_enum(data, "print_technology", ["LASER", "PAD"], "CustomizationOrder")
    assert is_iso8601_timestamp(data.get("requested_ship_date", "")), \
        "requested_ship_date must be an ISO 8601 timestamp"
    _assert_enum(data, "order_state", ["ACTIVE", "CANCELLED"], "CustomizationOrder")
    _assert_enum(data, "artwork_status", ARTWORK_STATUSES, "CustomizationOrder")
    assert isinstance(data["proof_round"], int) and 0 <= data["proof_round"] <= 3
    _assert_enum(data, "schedule_status", SCHEDULE_STATUSES, "CustomizationOrder")
    _assert_enum(data, "payment_status", PAYMENT_STATUSES, "CustomizationOrder")
    _assert_enum(data, "return_status", RETURN_STATUSES, "CustomizationOrder")
    if data.get("return_reason") is not None:
        _assert_enum(data, "return_reason",
                     ["DEFECT", "ARTWORK_MISMATCH", "BUYERS_REMORSE"],
                     "CustomizationOrder")
    if data.get("return_resolution") is not None:
        _assert_enum(data, "return_resolution",
                     ["REMAKE", "PARTIAL_CREDIT", "FULL_REFUND"], "CustomizationOrder")
    _assert_optional_int(data, "affected_unit_count", "CustomizationOrder")
    if data.get("slot_id") is not None:
        assert is_valid_uuid(data["slot_id"]), "slot_id must be a valid UUID when set"
    _assert_enum(data, "reservation_status", RESERVATION_STATUSES, "CustomizationOrder")
    _assert_optional_int(data, "reserved_minutes", "CustomizationOrder")
    _assert_enum(data, "quote_variant", ["NONE", "PROVISIONAL", "FINAL"],
                 "CustomizationOrder")
    if data.get("peak_applied") is not None:
        assert isinstance(data["peak_applied"], bool)
    _assert_optional_int(data, "provisional_quote_cents", "CustomizationOrder")
    _assert_optional_int(data, "final_quote_cents", "CustomizationOrder")
    _assert_optional_int(data, "cancellation_fee_cents", "CustomizationOrder")
    _assert_optional_int(data, "refund_cents", "CustomizationOrder")
    assert isinstance(data["qc_fail_count"], int) and data["qc_fail_count"] >= 0
    _assert_optional_timestamp(data, "completed_at", "CustomizationOrder")


PROOF_STATUSES = ["SUBMITTED", "APPROVED", "CHANGES_REQUESTED", "SUPERSEDED"]


def assert_artwork_proof(data: dict):
    _assert_common_fields(data, "ArtworkProof")
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a valid UUID"
    assert isinstance(data["artwork_file_ref"], str) and data["artwork_file_ref"]
    assert isinstance(data["color_count"], int) and 1 <= data["color_count"] <= 8
    assert isinstance(data["placement_count"], int) and 1 <= data["placement_count"] <= 4
    assert isinstance(data["pantone_codes"], list)
    assert isinstance(data["round_number"], int) and 1 <= data["round_number"] <= 3
    _assert_enum(data, "status", PROOF_STATUSES, "ArtworkProof")
    _assert_optional_str(data, "review_notes", "ArtworkProof")
    assert isinstance(data["submitted_by"], str) and data["submitted_by"]


# ---------------------------------------------------------------------------
# Print slots
# ---------------------------------------------------------------------------
SLOT_STATUSES = ["OPEN", "LOCKED", "CLOSED"]


def assert_print_slot(data: dict):
    _assert_common_fields(data, "PrintSlot")
    assert isinstance(data["station_code"], str) and data["station_code"]
    _assert_enum(data, "technology", ["LASER", "PAD"], "PrintSlot")
    assert is_iso8601_timestamp(data.get("window_start", "")), \
        "window_start must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("window_end", "")), \
        "window_end must be an ISO 8601 timestamp"
    assert isinstance(data["capacity_minutes"], int) and data["capacity_minutes"] > 0
    assert isinstance(data["peak_overlap"], bool)
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0
    assert isinstance(data["available_minutes"], int) and data["available_minutes"] >= 0
    _assert_enum(data, "status", SLOT_STATUSES, "PrintSlot")


def assert_slot_capacity_invariant(data: dict):
    """PRD section 2.10: capacity_minutes == booked_minutes + available_minutes
    at all times."""
    assert data["capacity_minutes"] == data["booked_minutes"] + data["available_minutes"], (
        f"slot capacity ledger broken: capacity {data['capacity_minutes']} != "
        f"booked {data['booked_minutes']} + available {data['available_minutes']}"
    )


# ---------------------------------------------------------------------------
# Warranty claims
# ---------------------------------------------------------------------------
CLAIM_STATUSES = ["FILED", "UNDER_REVIEW", "APPROVED_REPAIR",
                  "APPROVED_REPLACEMENT", "DENIED"]


def assert_warranty_claim(data: dict):
    _assert_common_fields(data, "WarrantyClaim")
    _assert_enum(data, "claim_source", ["DTC", "DEALER"], "WarrantyClaim")
    if data.get("dealer_id") is not None:
        assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a valid UUID when set"
    _assert_optional_str(data, "buyer_ref", "WarrantyClaim")
    if data.get("order_id") is not None:
        assert is_valid_uuid(data["order_id"]), "order_id must be a valid UUID when set"
    if data.get("product_line_id") is not None:
        assert is_valid_uuid(data["product_line_id"]), \
            "product_line_id must be a valid UUID when set"
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    _assert_enum(data, "component", ["LID", "INSULATION", "HARDWARE"], "WarrantyClaim")
    assert isinstance(data["failure_description"], str)
    _assert_optional_timestamp(data, "purchase_date", "WarrantyClaim")
    assert is_iso8601_timestamp(data.get("filed_at", "")), \
        "filed_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("warranty_anchor_at", "")), \
        "warranty_anchor_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("warranty_expires_at", "")), \
        "warranty_expires_at must be an ISO 8601 timestamp"
    assert isinstance(data["fraud_flag"], bool)
    if data.get("replacement_colorway_resolution") is not None:
        _assert_enum(data, "replacement_colorway_resolution",
                     ["SAME_COLORWAY", "NEAREST_AVAILABLE", "CREDIT_EQUIVALENT"],
                     "WarrantyClaim")
    _assert_optional_int(data, "credit_equivalent_cents", "WarrantyClaim")
    _assert_enum(data, "status", CLAIM_STATUSES, "WarrantyClaim")
    _assert_optional_str(data, "decision_reason", "WarrantyClaim")
