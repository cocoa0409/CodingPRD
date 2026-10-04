"""Entity serializers. Every resource carries the common system fields
id / created_at / updated_at / version (PRD §2.5). Datetimes render as
ISO 8601 UTC with three fractional digits; private "_"-prefixed keys are
never serialized."""
from datetime import datetime

import db

_COMMON = ("id", "created_at", "updated_at", "version")

_FIELDS = {
    "office": ("state_code", "population", "harm_measure_cents", "appropriation_rule"),
    "investigation": (
        "title",
        "target_name",
        "summary",
        "phase",
        "opened_at",
        "settled_at",
        "active_settlement_id",
    ),
    "participation": (
        "investigation_id",
        "state_office_id",
        "status",
        "cia_status",
        "cia_tier",
        "committee_role",
        "invited_at",
        "cia_executed_at",
        "withdrawn_at",
    ),
    "demand": (
        "participation_id",
        "scope_text",
        "status",
        "issued_at",
        "consolidated_at",
        "consolidated_response_id",
    ),
    "response": (
        "investigation_id",
        "demand_ids",
        "coverage_summary",
        "status",
        "submitted_at",
        "accepted_at",
        "fulfilled_at",
    ),
    "settlement": (
        "investigation_id",
        "monetary_total_cents",
        "restitution_reserve_cents",
        "allocation_basis",
        "negotiated_shares",
        "injunctive_terms",
        "term_status",
        "fund_status",
        "negotiation_round",
        "counter_total_cents",
        "sign_on_opened_at",
        "sign_on_deadline",
        "executed_at",
        "sign_ons",
        "provisional_distributable_cents",
        "provisional_weight_bps_by_state",
        "distributable_cents",
        "lead_cost_cents",
        "compliance_hold",
        "deposited_cents",
        "released_cents",
        "reverted_cents",
        "restitution_reserve_balance_cents",
        "restitution_computed",
        "restitution_remainder_cents",
    ),
    "line": (
        "settlement_id",
        "state_office_id",
        "state_code",
        "basis_value_snapshot",
        "weight_bps",
        "share_cents",
        "lead_bonus_cents",
        "gross_share_cents",
        "disbursed_cents",
        "reverted_cents",
        "remaining_cents",
        "status",
    ),
    "disbursement": (
        "allocation_line_id",
        "amount_cents",
        "use_code",
        "status",
        "requested_at",
        "certified_at",
        "released_at",
    ),
    "claimant": (
        "settlement_id",
        "state_code",
        "contact_ref",
        "claimed_loss_cents",
        "validated_loss_cents",
        "estimated_payout_cents",
        "payout_cents",
        "status",
    ),
    "period": (
        "settlement_id",
        "period_index",
        "window_start",
        "window_end",
        "findings",
        "breach_count",
        "status",
        "closed_at",
    ),
}


def _render(value):
    if isinstance(value, datetime):
        return db.render_ts(value)
    if isinstance(value, list):
        return [_render(item) for item in value]
    if isinstance(value, dict):
        return {k: _render(v) for k, v in value.items() if not k.startswith("_")}
    return value


def serialize(kind, entity):
    out = {}
    for field in _COMMON + _FIELDS[kind]:
        out[field] = _render(entity.get(field))
    return out


def serialize_list(kind, entities):
    return [serialize(kind, e) for e in entities]
