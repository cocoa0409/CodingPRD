"""Row -> JSON projections. Field sets follow SCAFFOLD entity definitions."""


def _pick(row, keys, versioned=True):
    out = {"id": row["id"]}
    for key in keys:
        out[key] = row.get(key)
    out["created_at"] = row["created_at"]
    if versioned:
        out["updated_at"] = row.get("updated_at")
        out["version"] = row.get("version")
    return out


SELLER_FIELDS = (
    "legal_name",
    "email",
    "email_domain",
    "tax_id_hash",
    "payout_bank_token",
    "address_fingerprint",
    "device_fingerprint",
    "root_seller_id",
    "registration_risk_flag",
    "enforcement_state",
    "disbursement_state",
    "ban_reason",
    "severity_points_balance",
    "health_score",
    "metric_tier",
    "available_balance_cents",
    "held_balance_cents",
    "lifetime_credited_cents",
    "lifetime_debited_cents",
    "open_defect_claim_units",
    "reinstated_count",
)

SNAPSHOT_FIELDS = (
    "seller_id",
    "window_start",
    "window_end",
    "order_volume",
    "delivered_or_refunded_volume",
    "defect_claims_pending",
    "defect_claims_substantiated",
    "late_shipments",
    "pre_fulfillment_cancellations",
    "shipments_total",
    "shipments_with_valid_tracking",
    "source",
)

EVALUATION_FIELDS = (
    "seller_id",
    "auto_violation_id",
    "input_snapshot_count",
    "input_window_start",
    "input_window_end",
    "odr_provisional",
    "odr_final",
    "odr_variant_delta",
    "late_shipment_rate",
    "cancellation_rate",
    "valid_tracking_rate",
    "order_volume_final",
    "health_score",
    "metric_tier",
    "breached_metrics",
    "evaluated_at",
)

POLICY_RULE_FIELDS = (
    "code",
    "category",
    "base_severity_weight",
    "removal_scope",
    "requires_poa",
    "decay_exempt",
)

LISTING_FIELDS = (
    "seller_id",
    "sku",
    "title",
    "category_code",
    "restricted_flag",
    "state",
    "removal_policy_category",
    "suppressed_by_suspension",
)

VIOLATION_FIELDS = (
    "seller_id",
    "policy_rule_id",
    "listing_id",
    "reporter_type",
    "evidence_reference",
    "state",
    "auto_generated",
    "detected_at",
    "adjudicated_at",
    "decision_note",
)

ACTION_FIELDS = (
    "seller_id",
    "violation_id",
    "policy_category",
    "policy_rule_code",
    "decay_exempt",
    "severity_points_applied",
    "ladder_rung_computed",
    "action_type",
    "override_applied",
    "issued_by_user_id",
    "issued_at",
    "appeal_deadline_at",
    "state",
    "acknowledged_at",
    "resolution_reason",
    "removed_listing_count",
)

PLAN_FIELDS = (
    "enforcement_action_id",
    "root_cause",
    "corrective_measures",
    "preventive_measures",
    "state",
    "revision_count",
    "submitted_at",
    "deadline_at",
    "reviewed_by_user_id",
    "review_notes",
)

APPEAL_FIELDS = (
    "enforcement_action_id",
    "plan_of_action_id",
    "grounds",
    "state",
    "decided_by_user_id",
    "decided_at",
    "denial_reason",
    "rationale",
    "escalation_deadline_at",
    "escalation_requested_at",
    "escalation_grounds",
    "escalation_decided_by_user_id",
    "reinstatement_granted",
)

HOLD_FIELDS = (
    "seller_id",
    "enforcement_action_id",
    "hold_type",
    "reserve_basis",
    "risk_tier",
    "held_amount_cents",
    "coverage_start",
    "coverage_end",
    "state",
    "auto_created",
    "created_by_user_id",
    "released_at",
    "release_reason",
    "forfeited_amount_cents",
)

NOTIFICATION_FIELDS = (
    "seller_id",
    "template_code",
    "related_entity_type",
    "related_entity_id",
    "policy_rule_code",
    "severity_points_disclosed",
    "appeal_deadline_at",
    "escalation_deadline_at",
    "amount_cents",
    "decision_rationale",
    "evidence_reference",
    "state",
    "sent_at",
)

LINK_FIELDS = (
    "candidate_seller_id",
    "matched_seller_id",
    "matched_signals",
    "confidence_score",
    "matched_seller_state_at_detection",
    "state",
    "detected_at",
    "adjudicated_by_user_id",
    "adjudication_note",
)


def seller(row):
    return _pick(row, SELLER_FIELDS)


def snapshot(row):
    return _pick(row, SNAPSHOT_FIELDS, versioned=False)


def evaluation(row):
    return _pick(row, EVALUATION_FIELDS, versioned=False)


def policy_rule(row):
    return _pick(row, POLICY_RULE_FIELDS)


def listing(row):
    return _pick(row, LISTING_FIELDS)


def violation(row):
    return _pick(row, VIOLATION_FIELDS)


def action(row):
    return _pick(row, ACTION_FIELDS)


def plan(row):
    return _pick(row, PLAN_FIELDS)


def appeal(row):
    return _pick(row, APPEAL_FIELDS)


def hold(row):
    return _pick(row, HOLD_FIELDS)


def notification(row):
    return _pick(row, NOTIFICATION_FIELDS)


def link(row):
    return _pick(row, LINK_FIELDS)
