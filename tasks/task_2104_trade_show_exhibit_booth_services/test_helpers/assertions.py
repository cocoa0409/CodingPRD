"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

BOOTH_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
POSTURE_REASONS = [
    "EXHIBITOR_SUSPENDED", "CREDIT_LIMIT_BREACHED", "SHOW_CLOSED", "SHOW_CANCELLED",
    "LABOR_NO_SHOW", "FREIGHT_HOLD", "CHANGE_ORDER_APPROVED",
]


def assert_audit_triple(data: dict, entity: str = "resource"):
    """Every resource but the service order line carries id plus the full audit
    triple: created_at, updated_at and an integer version starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601: {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601: {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer >= 1, got {data.get('version')}"


def assert_venue(data: dict):
    assert_audit_triple(data, "Venue")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["straight_time_start_hhmm"], str)
    assert isinstance(data["straight_time_end_hhmm"], str)
    assert isinstance(data["max_forklift_capacity_lbs"], int)
    assert isinstance(data["hanging_sign_booth_types"], list)
    assert isinstance(data["dock_count"], int)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_jurisdiction(data: dict):
    assert_audit_triple(data, "UnionJurisdiction")
    assert data["trade"] in ["RIGGING", "ELECTRICAL", "CARPENTRY",
                            "MATERIAL_HANDLING", "CLEANING"]
    assert isinstance(data["straight_time_rate_cents_per_hour"], int)
    assert isinstance(data["crew_max_size"], int)
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert isinstance(data["exhibitor_self_install_allowed"], bool)


def assert_warehouse(data: dict):
    assert_audit_triple(data, "Warehouse")
    assert isinstance(data["capacity_cwt"], int)
    assert isinstance(data["committed_cwt"], int)
    assert data["committed_cwt"] >= 0, "committed_cwt may never go negative"
    assert data["status"] in ["ACCEPTING", "CLOSED"]


def assert_show(data: dict):
    assert_audit_triple(data, "Show")
    assert data["status"] in ["DRAFT", "OPEN_FOR_ORDERS", "ADVANCE_CLOSED", "MOVE_IN",
                             "ON_SITE", "MOVE_OUT", "CLOSED", "CANCELLED"]
    for field in ("discount_deadline", "advance_warehouse_deadline", "move_in_start",
                  "move_in_end", "show_open", "show_close", "move_out_end"):
        assert isinstance(data[field], str) and data[field], f"Show.{field} must be present"
    assert data["committed_labor_hours"] >= 0
    assert isinstance(data["cancelled_labor_call_count"], int)
    assert data["cancelled_labor_call_count"] >= 0


def assert_exhibitor(data: dict):
    assert_audit_triple(data, "Exhibitor")
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["account_balance_cents"], int)


def assert_booth(data: dict):
    assert_audit_triple(data, "Booth")
    assert data["booth_type"] in ["INLINE", "CORNER", "PENINSULA", "ISLAND"]
    assert data["posture"] in BOOTH_POSTURES
    if data["posture"] == "OPEN":
        assert data["posture_reason"] is None, \
            "An OPEN booth carries a null posture_reason"
    else:
        assert data["posture_reason"] in POSTURE_REASONS, \
            f"Unexpected posture_reason {data['posture_reason']}"


def assert_exhibit_asset(data: dict):
    assert_audit_triple(data, "ExhibitAsset")
    assert data["acquisition_mode"] in ["RENTAL", "PURCHASE"]
    assert data["condition_grade"] in ["A", "B", "C", "D"]
    assert data["status"] in ["IN_DESIGN", "FABRICATED", "IN_STORAGE", "STAGED",
                              "ON_SHOW_FLOOR", "IN_REFURB", "RETIRED", "WRITTEN_OFF"]
    assert isinstance(data["refurb_cycles_count"], int)
    assert isinstance(data["list_value_cents"], int)
    assert isinstance(data["shipping_weight_lbs"], int)


def assert_exhibit_design(data: dict):
    assert_audit_triple(data, "ExhibitDesign")
    assert data["status"] in ["DRAFT", "QUOTED", "APPROVED", "RELEASED_TO_FAB", "CANCELLED"]
    assert data["selected_acquisition_mode"] in ["RENTAL", "PURCHASE"]
    assert isinstance(data["revision_count"], int)


def assert_service_order(data: dict):
    assert_audit_triple(data, "ServiceOrder")
    assert data["service_type"] in ["ELECTRICAL", "RIGGING", "MATERIAL_HANDLING",
                                    "CLEANING", "INSTALL_DISMANTLE"]
    assert data["deadline_tier"] in ["ADVANCE", "STANDARD", "ONSITE"]
    assert data["fulfillment_status"] in ["PENDING", "CONFIRMED", "SCHEDULED",
                                          "DELIVERED", "HELD", "CANCELLED"]
    assert data["billing_status"] in ["UNBILLED", "INVOICED", "REBILL_PENDING",
                                      "SETTLED", "CREDITED"]
    for field in ("subtotal_cents", "volume_discount_cents", "discounted_base_cents",
                  "service_fee_cents", "total_cents"):
        assert isinstance(data[field], int), f"ServiceOrder.{field} must be integer cents"


def assert_service_order_line(data: dict):
    """A line is immutable: it carries id and created_at but neither updated_at
    nor version."""
    assert is_valid_uuid(data.get("id", "")), "ServiceOrderLine.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "ServiceOrderLine.created_at must be ISO 8601"
    assert "updated_at" not in data, \
        "ServiceOrderLine has no updated_at field and it must not appear"
    assert "version" not in data, \
        "ServiceOrderLine has no version field and it must not appear"
    assert isinstance(data["line_seq"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_crate(data: dict):
    assert_audit_triple(data, "Crate")
    assert data["crate_type"] in ["WOOD_CRATE", "FIBER_CASE", "LOOSE_UNCRATED"]
    assert data["status"] in ["REGISTERED", "AT_ADVANCE_WAREHOUSE", "IN_TRANSIT_TO_SHOW",
                              "ON_SHOW_FLOOR", "EMPTY_STORED", "OUTBOUND_STAGED",
                              "RETURNED_TO_WAREHOUSE", "RELEASED_TO_CARRIER", "LOST"]
    assert isinstance(data["weight_lbs"], int)
    assert isinstance(data["storage_charge_cents"], int)


def assert_drayage_shipment(data: dict):
    assert_audit_triple(data, "DrayageShipment")
    assert data["channel"] in ["ADVANCE_WAREHOUSE", "DIRECT_TO_SHOW"]
    assert data["status"] in ["RECEIVED", "IN_TRANSIT", "DELIVERED_TO_BOOTH", "CLOSED"]
    assert isinstance(data["gross_weight_lbs"], int)
    assert isinstance(data["billable_cwt"], int)
    assert data["billable_cwt"] >= 2, "A two-hundredweight minimum applies to every shipment"
    assert isinstance(data["drayage_charge_cents"], int)
    assert isinstance(data["hold_flag"], bool)


def assert_labor_call(data: dict):
    assert_audit_triple(data, "LaborCall")
    assert data["status"] in ["REQUESTED", "DISPATCHED", "ON_SITE", "COMPLETED",
                              "NO_SHOW", "CANCELLED"]
    assert data["trade"] in ["RIGGING", "ELECTRICAL", "CARPENTRY",
                             "MATERIAL_HANDLING", "CLEANING"]
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert data["scheduled_hours"] >= 0


def assert_change_order(data: dict):
    assert_audit_triple(data, "ChangeOrder")
    assert data["target_type"] in ["SERVICE_ORDER", "LABOR_CALL", "EXHIBIT_DESIGN"]
    assert data["delta_kind"] in ["QTY_INCREASE", "QTY_DECREASE",
                                  "CREW_INCREASE", "SCOPE_UPGRADE"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED",
                              "RETURNED", "REJECTED", "APPLIED"]
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_invoice(data: dict):
    assert_audit_triple(data, "Invoice")
    assert data["status"] in ["DRAFT", "ISSUED", "PARTIALLY_SETTLED", "SETTLED", "VOID"]
    for field in ("subtotal_cents", "adjustments_cents", "total_cents", "settled_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents"
    assert data["settled_cents"] >= 0
    assert data["total_cents"] == data["subtotal_cents"] + data["adjustments_cents"], \
        "total_cents is subtotal_cents plus adjustments_cents"


def assert_damage_claim(data: dict):
    assert_audit_triple(data, "DamageClaim")
    assert data["claim_type"] in ["DAMAGE", "LOSS"]
    assert data["coverage_basis"] in ["TARIFF_LIABILITY", "DECLARED_VALUE"]
    assert data["status"] in ["FILED", "UNDER_INVESTIGATION", "APPROVED",
                              "DENIED", "SETTLED"]
    assert isinstance(data["appeal_count"], int)


def assert_refurb_work_order(data: dict):
    assert_audit_triple(data, "RefurbWorkOrder")
    assert data["scope"] in ["GRAPHICS_REFRESH", "STRUCTURAL_REPAIR", "FULL_REBUILD"]
    assert data["status"] in ["OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    assert isinstance(data["estimate_cents"], int)


def assert_lead_capture_license(data: dict):
    assert_audit_triple(data, "LeadCaptureLicense")
    assert data["status"] in ["PROVISIONED", "ACTIVE", "CLOSED"]
    assert isinstance(data["ingested_badge_ids"], list)
    assert data["leads_ingested_count"] == len(data["ingested_badge_ids"]), \
        "leads_ingested_count is the number of entries in ingested_badge_ids"
    assert data["billable_overage_leads"] >= 0


def assert_service_order_waterfall(order: dict):
    """The pinned waterfall: discounted base is subtotal minus volume discount,
    and the total is that base plus the service fee, both exact integer steps."""
    assert order["discounted_base_cents"] == \
        order["subtotal_cents"] - order["volume_discount_cents"], \
        "discounted_base_cents is subtotal_cents minus volume_discount_cents"
    assert order["total_cents"] == \
        order["discounted_base_cents"] + order["service_fee_cents"], \
        "total_cents is discounted_base_cents plus service_fee_cents"


def assert_posture(booth: dict, expected_posture: str, expected_reason=None):
    assert booth["posture"] == expected_posture, \
        f"Expected posture {expected_posture}, got {booth['posture']} " \
        f"(reason {booth.get('posture_reason')})"
    assert booth["posture_reason"] == expected_reason, \
        f"Expected posture_reason {expected_reason}, got {booth.get('posture_reason')}"
