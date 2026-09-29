"""Resource representations.  Field sets follow the entity tables verbatim."""
import derive

COMMON = ("id",)
COMMON_TAIL = ("created_at", "updated_at", "version")

FIELDS = {
    "members": (
        "legal_name", "membership_tier", "status", "home_jurisdiction_code",
        "home_district_code", "annual_dues_cents", "dues_year", "restricted_class_size",
        "advocacy_optout", "engagement_score", "recorded_dissent_count", "notice_method",
        "pac_solicitable",
    ),
    "committees": (
        "name", "jurisdiction_scope", "quorum_threshold_pct", "consensus_threshold_pct",
        "seat_count", "total_voting_weight", "roster_state",
    ),
    "seats": ("committee_id", "member_id", "seat_role", "voting_weight", "status", "dissent_strikes"),
    "positions": (
        "committee_id", "title", "jurisdiction_code", "summary", "status", "round_number",
        "ballot_deadline_date", "support_weight", "oppose_weight", "abstain_weight",
        "quorum_pct", "consensus_pct", "last_tally_outcome", "dissent_register_count",
        "adopted_at",
    ),
    "votes": (
        "position_id", "member_id", "ballot", "dissent_statement", "round_number",
        "weight_snapshot", "ballot_status", "dissent_status",
    ),
    "registrations": (
        "jurisdiction_code", "registrant_name", "coverage_start_date", "coverage_end_date",
        "status", "filed_at", "amendment_round", "ytd_reportable_cents",
        "ytd_reportable_hours", "terminated_at",
    ),
    "activities": (
        "registration_id", "position_id", "activity_kind", "coalition_partner_name",
        "third_party_disclosure_required", "activity_date", "hours", "expenditure_cents",
        "staff_cost_cents", "logged_at", "status", "void_reason",
    ),
    "reports": (
        "registration_id", "period_code", "period_start_date", "period_end_date", "due_date",
        "basis", "method_a_total_cents", "method_b_total_cents", "filed_total_cents",
        "included_activity_count", "status", "created_by_user_id", "certified_by_user_id",
        "certified_at", "late",
    ),
    "campaigns": (
        "position_id", "name", "target_jurisdiction_code", "status", "alert_count",
        "matched_member_total", "unmatched_alert_count", "cumulative_cost_cents",
        "disclosure_required", "last_alert_at",
    ),
    "alerts": (
        "campaign_id", "target_district_code", "target_chamber", "message_subject",
        "unit_cost_cents", "matched_member_ids", "matched_member_count", "cost_cents",
        "status", "dispatched_at",
    ),
    "approvals": (
        "member_id", "calendar_year", "solicitable_class_size", "effective_date",
        "expires_at_date", "status", "authorized_by_name", "granted_at",
        "granted_by_user_id", "revoked_at",
    ),
    "candidates": (
        "name", "office", "jurisdiction_code", "district_code", "election_cycle",
        "incumbency", "voting_alignment_pct", "committee_relevance_score",
        "latest_support_score", "pending_support_cents", "committed_support_cents",
        "disbursed_support_cents",
    ),
    "funds": (
        "name", "fund_year", "jurisdiction_code", "min_reserve_cents", "receipts_total_cents",
        "committed_balance_cents", "disbursed_total_cents", "filing_fee_accrued_cents",
        "available_balance_cents", "posture", "filings_completed_count",
        "last_filed_period_code",
    ),
    "contributions": (
        "fund_id", "candidate_id", "amount_cents", "memo", "support_score",
        "max_allowed_cents", "status", "proposed_by_user_id", "board_approved_by_user_id",
        "disbursed_at", "voided_at", "void_reason",
    ),
}

# An action alert is an immutable dispatch record: id + created_at only (PRD 2.4).
NO_COMMON_TAIL = ("alerts",)


def dump(kind, row):
    out = {"id": row["id"]}
    for field in FIELDS[kind]:
        out[field] = row.get(field)
    if kind == "members":
        out["pac_solicitable"] = derive.member_pac_solicitable(row)
    if kind == "alerts":
        out["matched_member_ids"] = list(row.get("matched_member_ids") or [])
    out["created_at"] = row["created_at"]
    if kind not in NO_COMMON_TAIL:
        out["updated_at"] = row.get("updated_at")
        out["version"] = row.get("version")
    return out


def dump_all(kind, rows):
    return [dump(kind, row) for row in rows]


def listing(kind, rows):
    """Paginated array envelope for a list endpoint (PRD 2.2, 2.3)."""
    from core import paginate, respond_list
    page, meta = paginate(rows)
    return respond_list(dump_all(kind, page), meta)
