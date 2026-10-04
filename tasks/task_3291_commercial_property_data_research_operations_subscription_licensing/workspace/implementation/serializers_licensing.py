"""JSON serializers for licensing-side entities."""


def contract(c):
    return {
        "id": c["id"],
        "subscriber_organization_id": c["subscriber_organization_id"],
        "product": c["product"],
        "licensed_markets": c["licensed_markets"],
        "seat_count": c["seat_count"],
        "annual_fee_cents": c["annual_fee_cents"],
        "monthly_index_fee_cents": c["monthly_index_fee_cents"],
        "auto_renew": c["auto_renew"],
        "renewal_notice_days": c["renewal_notice_days"],
        "term_start": c["term_start"],
        "term_end": c["term_end"],
        "renewal_decision": c["renewal_decision"],
        "renewal_due_at": c["renewal_due_at"],
        "status": c["status"],
        "audit_intensity": c["audit_intensity"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def seat(s):
    return {
        "id": s["id"],
        "contract_id": s["contract_id"],
        "occupant_user_id": s["occupant_user_id"],
        "market": s["market"],
        "index_tier": s["index_tier"],
        "monthly_active_days": s["monthly_active_days"],
        "monthly_unauthorized_markets": s["monthly_unauthorized_markets"],
        "distinctive_ip_count": s["distinctive_ip_count"],
        "shared_flag": s["shared_flag"],
        "overage_fee_cents": s["overage_fee_cents"],
        "owner_user_id": s["owner_user_id"],
        "owner_share_pct": s["owner_share_pct"],
        "billed_owner_share_pct": s["billed_owner_share_pct"],
        "access_revoked": s["access_revoked"],
        "last_usage_cycle": s["last_usage_cycle"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def usage_event(e):
    # UsageEvent carries only id and created_at (common_fields: false).
    return {
        "id": e["id"],
        "seat_id": e["seat_id"],
        "user_id": e["user_id"],
        "market": e["market"],
        "event_type": e["event_type"],
        "record_count": e["record_count"],
        "distinguishing_ip": e["distinguishing_ip"],
        "occurred_at": e["occurred_at"],
        "created_at": e["created_at"],
    }