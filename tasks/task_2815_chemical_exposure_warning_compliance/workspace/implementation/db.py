"""In-memory store and the logical clock.

The store starts empty on every boot: no entity is ever seeded, preloaded or
hardcoded here.  Every row is created through a declared endpoint.
"""
import itertools
import uuid
from datetime import datetime, timezone

from util import D, fmt_dt, out_num

KINDS = (
    "listed_chemicals",
    "suppliers",
    "materials",
    "material_chemicals",
    "products",
    "product_components",
    "exposure_assessments",
    "warning_determinations",
    "warning_placements",
    "notices",
    "settlements",
    "reformulation_projects",
)

STORE = {kind: {} for kind in KINDS}
_SEQ = itertools.count(1)

# The logical clock: never the host wall clock.  Before it has ever been set it
# reads exactly 2026-08-01T00:00:00Z (PRD 2.4).
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}


def now():
    return CLOCK["now"]


def set_clock(instant):
    previous = CLOCK["now"]
    CLOCK["now"] = instant
    return instant, previous


FIELDS = {
    "listed_chemicals": [
        "id", "chemical_name", "cas_number", "endpoint_type", "harm_class",
        "safe_harbor_basis", "safe_harbor_level_ug_per_day",
        "listing_effective_date", "warning_required_from", "status",
        "revision_count", "created_at", "updated_at", "version",
    ],
    "suppliers": [
        "id", "legal_name", "contact_email", "warranty_status", "warranty_scope",
        "pass_through_warning_obligation", "indemnity_cap_cents",
        "warranty_effective_from", "warranty_effective_to",
        "created_at", "updated_at", "version",
    ],
    "materials": [
        "id", "material_code", "material_class", "supplier_id",
        "parent_material_id", "parent_mass_fraction", "bom_depth",
        "disclosure_status", "data_request_sent_at", "data_received_at",
        "naturally_occurring_claim", "created_at", "updated_at", "version",
    ],
    "material_chemicals": [
        "id", "material_id", "chemical_id", "declared_concentration_ppm",
        "measurement_basis", "status", "lab_name", "lab_result_ppm",
        "lab_loq_ppm", "lab_reported_at", "dispute_note",
        "created_at", "updated_at", "version",
    ],
    "products": [
        "id", "sku", "product_name", "product_category", "occupancy_type",
        "distribution_channels", "label_area_sq_in", "annual_units",
        "lifecycle_state", "compliance_posture", "open_notice_count",
        "accrued_penalty_cents", "total_listed_chemical_load_ug",
        "created_at", "updated_at", "version",
    ],
    "product_components": [
        "id", "product_id", "material_id", "quantity_grams_per_unit",
        "contact_factor", "status", "created_at", "updated_at", "version",
    ],
    "exposure_assessments": [
        "id", "product_id", "chemical_id", "method", "route", "uses_per_day",
        "daily_exposure_ug", "margin_ratio", "result", "contribution_count",
        "status", "submitted_by_user_id", "reviewed_by_user_id", "finalized_at",
        "rejection_count", "review_note", "created_at", "updated_at", "version",
    ],
    "warning_determinations": [
        "id", "product_id", "assessment_id", "decision", "warning_type",
        "symbol_required", "named_chemicals", "website_url", "warning_text",
        "required_channels", "covered_channel_count", "status",
        "prepared_by_user_id", "approved_by_user_id", "review_note",
        "created_at", "updated_at", "version",
    ],
    "warning_placements": [
        "id", "determination_id", "channel", "effective_from", "effective_to",
        "placement_detail", "catalog_page_ref", "internet_display_position",
        "status", "implemented_by_user_id", "remediation_count",
        "created_at", "updated_at", "version",
    ],
    "notices": [
        "id", "product_id", "chemical_id", "noticing_party_name",
        "noticing_party_type", "alleged_violation_type", "alleged_units",
        "earliest_violation_date", "served_at", "cure_deadline_at",
        "cure_eligible", "cure_completed_at", "cure_attempted", "status",
        "evaluation_note", "created_at", "updated_at", "version",
    ],
    "settlements": [
        "id", "notice_id", "requested_attorney_fees_cents",
        "reformulation_commitment", "violation_days", "base_penalty_cents",
        "mitigation_factor", "adjusted_penalty_cents", "fee_cap_cents",
        "allowed_fees_cents", "state_share_cents", "noticing_party_share_cents",
        "total_settlement_cents", "round_count", "status",
        "proposed_by_user_id", "executed_by_user_id", "executed_at",
        "created_at", "updated_at", "version",
    ],
    "reformulation_projects": [
        "id", "product_id", "chemical_id", "material_chemical_id",
        "target_concentration_ppm", "planned_start_date", "planned_end_date",
        "baseline_daily_exposure_ug", "verified_daily_exposure_ug",
        "reduction_pct", "status", "created_at", "updated_at", "version",
    ],
}

# Every field the server computes or stamps: supplying one in a request body is
# ERR_FIELD_NOT_WRITABLE (validation ladder layer 4 rule 4).
NON_WRITABLE = {
    "id", "created_at", "updated_at", "version",
    "harm_class", "warning_required_from", "status", "revision_count",
    "warranty_status", "bom_depth", "disclosure_status",
    "data_request_sent_at", "data_received_at",
    "measurement_basis", "lab_reported_at",
    "lifecycle_state", "compliance_posture", "open_notice_count",
    "accrued_penalty_cents", "total_listed_chemical_load_ug",
    "daily_exposure_ug", "margin_ratio", "result", "contribution_count",
    "submitted_by_user_id", "reviewed_by_user_id", "finalized_at",
    "rejection_count",
    "warning_type", "symbol_required", "named_chemicals", "website_url",
    "warning_text", "required_channels", "covered_channel_count",
    "prepared_by_user_id", "approved_by_user_id",
    "implemented_by_user_id", "remediation_count",
    "cure_deadline_at", "cure_eligible", "cure_completed_at", "cure_attempted",
    "violation_days", "base_penalty_cents", "mitigation_factor",
    "adjusted_penalty_cents", "fee_cap_cents", "allowed_fees_cents",
    "state_share_cents", "noticing_party_share_cents",
    "total_settlement_cents", "round_count",
    "proposed_by_user_id", "executed_by_user_id", "executed_at",
    "baseline_daily_exposure_ug", "verified_daily_exposure_ug", "reduction_pct",
}


def insert(kind, row):
    row["id"] = str(uuid.uuid4())
    row["created_at"] = now()
    row["updated_at"] = now()
    row["version"] = 1
    row["_seq"] = next(_SEQ)
    STORE[kind][row["id"]] = row
    return row


def touch(row, bump=True):
    row["updated_at"] = now()
    if bump:
        row["version"] = row["version"] + 1
    return row


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return STORE[kind].get(row_id)


def rows(kind):
    """Every row of a kind in creation order (created_at ascending, stable)."""
    return sorted(STORE[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))


def serialize(kind, row):
    out = {}
    for field in FIELDS[kind]:
        value = row.get(field)
        if isinstance(value, datetime):
            out[field] = fmt_dt(value)
        elif isinstance(value, list):
            out[field] = list(value)
        else:
            out[field] = out_num(value)
    return out
