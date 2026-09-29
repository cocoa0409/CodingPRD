"""Standard response envelope (PRD section 2.2) and resource serialisers."""
import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty():
    return ok({}, 200)


def listing(rows, limit, offset, total_count):
    has_more = (offset + len(rows)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Serialisers: every field the entity declares, and nothing internal.
# ---------------------------------------------------------------------------

COMMON = ("id", "created_at", "updated_at", "version")
EVENT_COMMON = ("id", "created_at")

FIELDS = {
    "state_rule": COMMON + (
        "state_code",
        "household_sharps_classification",
        "mail_back_permitted",
        "max_container_volume_liters",
        "requires_state_manifest",
        "certificate_retention_years",
        "notification_deadline_hours",
    ),
    "packaging_spec": COMMON + (
        "spec_code",
        "un_specification_code",
        "postal_service",
        "hazard_class",
        "max_gross_weight_grams",
        "allowed_container_sizes",
        "requires_absorbent",
        "status",
    ),
    "treatment_facility": COMMON + (
        "name",
        "state_rule_id",
        "permit_number",
        "accepted_hazard_classes",
        "daily_intake_capacity_units",
        "pending_intake_units",
        "destroyed_units_total",
        "certificates_issued_count",
        "status",
    ),
    "sponsor": COMMON + ("legal_name", "sponsor_type", "contact_email", "status"),
    "program": COMMON + (
        "sponsor_id",
        "program_code",
        "funding_ceiling_cents",
        "per_kit_allowance_cents",
        "reserved_cents",
        "committed_cents",
        "available_cents",
        "kits_issued_count",
        "kits_settled_count",
        "provisional_total_cents",
        "final_total_cents",
        "status",
    ),
    "patient": COMMON + (
        "full_name",
        "state_rule_id",
        "therapy_type",
        "weekly_sharps_count",
        "contact_email",
        "screening_risk_score",
        "audit_risk_score",
        "suspended_at",
        "status",
    ),
    "enrollment": COMMON + (
        "patient_id",
        "sponsorship_program_id",
        "cadence_days",
        "kits_authorized",
        "requested_container_size",
        "kits_issued",
        "next_autoship_due_date",
        "activated_at",
        "sponsor_decision_note",
        "status",
    ),
    "kit": COMMON + (
        "enrollment_id",
        "supersedes_kit_id",
        "auto_ship_run_id",
        "container_size",
        "capacity_units",
        "volume_liters",
        "required_units",
        "fill_units",
        "sealed_gross_weight_grams",
        "provisional_cost_cents",
        "issued_at",
        "seal_deadline_date",
        "acknowledged_at",
        "status",
        "void_reason",
    ),
    "return_label": COMMON + (
        "kit_id",
        "packaging_spec_id",
        "postal_service",
        "tracking_number",
        "valid_from",
        "valid_until",
        "voided_at",
        "activated_at",
        "status",
    ),
    "shipment": COMMON + (
        "kit_id",
        "return_label_id",
        "treatment_facility_id",
        "scheduled_intake_date",
        "declared_gross_weight_grams",
        "observed_gross_weight_grams",
        "custody_units",
        "state_manifest_number",
        "tendered_at",
        "delivered_at",
        "screened_by_user_id",
        "transport_status",
        "conformance_status",
    ),
    "nonconformance_event": COMMON + (
        "shipment_id",
        "reason_code",
        "notification_deadline_at",
        "notified_at",
        "notification_channel",
        "remediation_action",
        "status",
    ),
    "certificate": COMMON + (
        "shipment_id",
        "kit_id",
        "treatment_facility_id",
        "certificate_number",
        "destroyed_units",
        "destruction_date",
        "retention_until_date",
        "issued_by_user_id",
        "final_kit_cost_cents",
        "rebate_pct_applied",
        "voided_at",
        "void_reason",
        "status",
    ),
    "ledger_entry": EVENT_COMMON + (
        "sponsorship_program_id",
        "kit_id",
        "entry_type",
        "amount_cents",
        "sequence_no",
        "reserved_after_cents",
        "committed_after_cents",
        "available_after_cents",
        "memo",
    ),
    "autoship_run": EVENT_COMMON + (
        "as_of_date",
        "run_at",
        "enrollments_evaluated",
        "kits_created",
        "kits_skipped_not_due",
        "kits_skipped_unfilled",
        "kits_skipped_risk",
        "kits_skipped_funding",
        "created_kit_ids",
    ),
}


def view(kind, row):
    if row is None:
        return None
    out = {}
    for name in FIELDS[kind]:
        out[name] = row.get(name)
    return out


def view_all(kind, rows):
    return [view(kind, r) for r in rows]
