"""Entity serialisers.  Evidence and PerformanceSnapshot carry id and created_at
only -- no updated_at and no version at all (PRD section 2.4)."""

from timeutil import fmt, fmt_date


def _common(row, out):
    out["created_at"] = fmt(row["created_at"])
    out["updated_at"] = fmt(row["updated_at"])
    out["version"] = row["version"]
    return out


def campaign(row):
    return _common(row, {
        "id": row["id"],
        "code": row["code"],
        "persona": row["persona"],
        "primary_funnel_stage": row["primary_funnel_stage"],
        "quarter_code": row["quarter_code"],
        "status": row["status"],
        "governance_posture": row["governance_posture"],
        "breached_gate_count": row["breached_gate_count"],
        "expired_usage_count": row["expired_usage_count"],
        "unsubstantiated_published_claim_count":
            row["unsubstantiated_published_claim_count"],
        "committed_points_total": row["committed_points_total"],
    })


def slot(row):
    return _common(row, {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "week_start_date": fmt_date(row["week_start_date"]),
        "funnel_stage": row["funnel_stage"],
        "capacity_points": row["capacity_points"],
        "committed_points": row["committed_points"],
        "utilization_pct": row["utilization_pct"],
        "status": row["status"],
    })


def expert(row):
    return _common(row, {
        "id": row["id"],
        "full_name": row["full_name"],
        "expertise_tags": list(row["expertise_tags"]),
        "weekly_capacity_hours": row["weekly_capacity_hours"],
        "status": row["status"],
        "committed_hours_total": row["committed_hours_total"],
    })


def brief(row):
    return _common(row, {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "funnel_stage": row["funnel_stage"],
        "search_intent": row["search_intent"],
        "primary_keyword": row["primary_keyword"],
        "secondary_keywords": list(row["secondary_keywords"]),
        "target_word_count": row["target_word_count"],
        "required_expertise_tag": row["required_expertise_tag"],
        "requires_regulated_review": row["requires_regulated_review"],
        "review_window_start": fmt(row["review_window_start"]),
        "review_window_end": fmt(row["review_window_end"]),
        "sme_expert_id": row["sme_expert_id"],
        "effort_points": row["effort_points"],
        "sme_reserved_hours": row["sme_reserved_hours"],
        "state": row["state"],
    })


def item(row):
    return _common(row, {
        "id": row["id"],
        "brief_id": row["brief_id"],
        "slot_id": row["slot_id"],
        "campaign_id": row["campaign_id"],
        "title": row["title"],
        "planned_publish_at": fmt(row["planned_publish_at"]),
        "promotion_window_days": row["promotion_window_days"],
        "effort_points": row["effort_points"],
        "commit_points": row["commit_points"],
        "capacity_tier_at_commit": row["capacity_tier_at_commit"],
        "workflow_state": row["workflow_state"],
        "revision_number": row["revision_number"],
        "created_by_user_id": row["created_by_user_id"],
        "published_by_user_id": row["published_by_user_id"],
        "published_at": fmt(row["published_at"]),
        "retracted_at": fmt(row["retracted_at"]),
        "meta_description": row["meta_description"],
        "url_slug": row["url_slug"],
        "tags": list(row["tags"]) if row["tags"] is not None else None,
        "accuracy_status": row["accuracy_status"],
        "last_audit_type": row["last_audit_type"],
        "last_audit_verdict": row["last_audit_verdict"],
        "last_audit_at": fmt(row["last_audit_at"]),
        "engaged_sessions_total": row["engaged_sessions_total"],
        "conversions_total": row["conversions_total"],
        "last_touch_pipeline_cents": row["last_touch_pipeline_cents"],
        "assisted_pipeline_cents": row["assisted_pipeline_cents"],
        "decay_pct": row["decay_pct"],
        "refresh_required": row["refresh_required"],
    })


def gate(row):
    return _common(row, {
        "id": row["id"],
        "content_item_id": row["content_item_id"],
        "gate_type": row["gate_type"],
        "state": row["state"],
        "opened_at": fmt(row["opened_at"]),
        "due_at": fmt(row["due_at"]),
        "sla_hours": row["sla_hours"],
        "decided_at": fmt(row["decided_at"]),
        "decided_by_user_id": row["decided_by_user_id"],
        "decision_notes": row["decision_notes"],
        "turnaround_hours": row["turnaround_hours"],
        "sla_breached": row["sla_breached"],
    })


def claim(row):
    return _common(row, {
        "id": row["id"],
        "content_item_id": row["content_item_id"],
        "claim_text": row["claim_text"],
        "claim_type": row["claim_type"],
        "substantiation_state": row["substantiation_state"],
        "scoring_variant": row["scoring_variant"],
        "required_score": row["required_score"],
        "evidence_score": row["evidence_score"],
        "evidence_valid_until": fmt(row["evidence_valid_until"]),
        "decided_by_user_id": row["decided_by_user_id"],
        "decided_at": fmt(row["decided_at"]),
    })


def evidence(row):
    return {
        "id": row["id"],
        "claim_id": row["claim_id"],
        "source_type": row["source_type"],
        "citation": row["citation"],
        "collected_at": fmt(row["collected_at"]),
        "valid_until": fmt(row["valid_until"]),
        "weight": row["weight"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "created_at": fmt(row["created_at"]),
    }


def asset(row):
    return _common(row, {
        "id": row["id"],
        "name": row["name"],
        "asset_type": row["asset_type"],
        "license_start": fmt(row["license_start"]),
        "license_end": fmt(row["license_end"]),
        "licensed_channels": list(row["licensed_channels"]),
        "max_licensed_uses": row["max_licensed_uses"],
        "active_use_count": row["active_use_count"],
        "remaining_licensed_uses": row["remaining_licensed_uses"],
        "status": row["status"],
    })


def usage(row):
    return _common(row, {
        "id": row["id"],
        "content_item_id": row["content_item_id"],
        "asset_id": row["asset_id"],
        "channel": row["channel"],
        "usage_state": row["usage_state"],
        "attached_at": fmt(row["attached_at"]),
        "released_at": fmt(row["released_at"]),
    })


def distribution(row):
    return _common(row, {
        "id": row["id"],
        "content_item_id": row["content_item_id"],
        "channel": row["channel"],
        "scheduled_at": fmt(row["scheduled_at"]),
        "state": row["state"],
        "went_live_at": fmt(row["went_live_at"]),
        "suppression_reason": row["suppression_reason"],
        "suppressed_at": fmt(row["suppressed_at"]),
    })


def snapshot(row):
    return {
        "id": row["id"],
        "content_item_id": row["content_item_id"],
        "period_start": fmt(row["period_start"]),
        "period_end": fmt(row["period_end"]),
        "engaged_sessions": row["engaged_sessions"],
        "conversions": row["conversions"],
        "influenced_opportunity_amount_cents":
            row["influenced_opportunity_amount_cents"],
        "touch_position": row["touch_position"],
        "created_at": fmt(row["created_at"]),
    }
