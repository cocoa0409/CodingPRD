"""Response projections for the fourteen entities."""

BASE_MUTABLE = ("id", "created_at", "updated_at", "version")
BASE_IMMUTABLE = ("id", "created_at")

CUSTOMER = ("full_name", "phone", "email", "preferred_alternate_parts_ok")

INSURER = ("insurer_code", "name", "aftermarket_allowed", "recycled_allowed",
           "reconditioned_allowed", "alternate_parts_min_vehicle_age_years",
           "rate_ceiling_cents", "parts_price_ceiling_pct", "supplement_round_limit")

PARTS_VENDOR = ("name", "vendor_type", "part_types_offered", "status", "discount_pct",
                "core_charge_cents", "restocking_fee_pct", "max_qty_per_line",
                "order_seq_counter", "fulfillment_score_rolling", "fulfillment_score_lifetime")

STALL = ("name", "stall_type", "cleanup_buffer_minutes", "status", "booked_minutes")

CALIBRATION_BAY = ("name", "concurrent_capacity", "supported_types", "scheduled_window_count")

REPAIR_ORDER = ("customer_id", "insurer_id", "claim_number", "vehicle_vin",
                "vehicle_model_year", "vehicle_make_model", "initial_authorized_cents",
                "deductible_cents", "checkin_at", "delivered_at", "stage",
                "authorization_posture", "blueprint_by_user_id", "total_loss_note",
                "teardown_finding_count", "refinish_hours_provisional",
                "refinish_hours_final", "approved_labor_hours", "labor_subtotal_cents",
                "parts_gross_cents", "parts_discount_cents", "parts_subtotal_cents",
                "betterment_cents", "supplies_fee_cents", "pre_tax_total_cents",
                "insurer_authorized_cents", "customer_pay_cents", "consent_state",
                "consent_basis_cents", "consent_alternate_parts",
                "parts_ordered_gross_cents", "parts_committed_cents",
                "parts_return_credit_cents", "parts_restocking_loss_cents",
                "open_parts_delay_count", "qc_inspection_count")

DAMAGE_LINE = ("repair_order_id", "panel_code", "severity", "requires_blend",
               "adas_component_touched", "structural", "discovered_at_stage")

ESTIMATE_LINE = ("repair_order_id", "damage_line_id", "supplement_id", "operation_code",
                 "labor_type", "guide_hours", "not_included_operation",
                 "justification_note", "is_blend", "is_adjacent_panel", "two_stage",
                 "pay_type", "allocated_hours", "effective_rate_cents",
                 "line_amount_cents", "line_status")

SUPPLEMENT = ("repair_order_id", "reason_code", "requested_amount_cents",
              "approved_amount_cents", "status", "round_count", "submitted_at",
              "decided_at", "info_request_note", "adjuster_note")

PARTS_LINE = ("estimate_line_id", "vendor_id", "part_number", "part_description",
              "part_type", "list_price_cents", "qty", "oem_upgrade",
              "quoted_unit_price_cents", "counter_unit_price_cents", "unit_price_cents",
              "quote_round", "unit_extended_cents", "extended_price_cents",
              "restocking_fee_cents", "procurement_status", "authorization_status",
              "vendor_order_seq", "promised_eta", "received_at", "received_qty",
              "returned_qty", "return_reason", "on_time")

PROCEDURE_RECORD = ("repair_order_id", "bay_id", "procedure_code", "source",
                    "operation_scope", "requires_calibration", "calibration_type",
                    "adherence_documented", "adherence_doc_ref", "calibration_status",
                    "window_start", "window_end", "post_scan_dtc_count", "scan_report_ref")

STAGE_ASSIGNMENT = ("repair_order_id", "stall_id", "stage", "window_start", "window_end",
                    "status", "occupied_minutes")

PARTS_DELAY_EVENT = ("repair_order_id", "parts_line_id", "reason", "opened_at",
                     "closed_at", "delay_minutes")

QC_INSPECTION = ("repair_order_id", "inspector_user_id", "sequence_number",
                 "checklist_passed", "post_scan_dtc_count", "scan_report_ref", "result",
                 "failure_reason", "warranty_certificate_number", "warranty_expires_at")


def _pick(row, names, base):
    out = {}
    for name in base:
        out[name] = row.get(name)
    for name in names:
        out[name] = row.get(name)
    return out


def customer(row):
    return _pick(row, CUSTOMER, BASE_IMMUTABLE)


def insurer(row):
    return _pick(row, INSURER, BASE_MUTABLE)


def parts_vendor(row):
    return _pick(row, PARTS_VENDOR, BASE_MUTABLE)


def stall(row):
    return _pick(row, STALL, BASE_MUTABLE)


def calibration_bay(row):
    return _pick(row, CALIBRATION_BAY, BASE_MUTABLE)


def repair_order(row):
    return _pick(row, REPAIR_ORDER, BASE_MUTABLE)


def damage_line(row):
    return _pick(row, DAMAGE_LINE, BASE_IMMUTABLE)


def estimate_line(row):
    return _pick(row, ESTIMATE_LINE, BASE_MUTABLE)


def supplement(row):
    return _pick(row, SUPPLEMENT, BASE_MUTABLE)


def parts_line(row):
    return _pick(row, PARTS_LINE, BASE_MUTABLE)


def procedure_record(row):
    return _pick(row, PROCEDURE_RECORD, BASE_MUTABLE)


def stage_assignment(row):
    return _pick(row, STAGE_ASSIGNMENT, BASE_MUTABLE)


def parts_delay_event(row):
    return _pick(row, PARTS_DELAY_EVENT, BASE_IMMUTABLE)


def qc_inspection(row):
    return _pick(row, QC_INSPECTION, BASE_MUTABLE)
