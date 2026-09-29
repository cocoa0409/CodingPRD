"""Entity output shapes and natural-key sort helpers (PRD SS2.3, SS2.4)."""
from decimal import Decimal

from db import db, fmt_instant


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, payload):
    payload["id"] = row["id"]
    payload["created_at"] = fmt_instant(row["created_at"])
    payload["updated_at"] = fmt_instant(row["updated_at"])
    payload["version"] = row["version"]
    return payload


def title_out(t):
    return _common(t, {
        "title_code": t["title_code"],
        "name": t["name"],
        "source_language": t["source_language"],
        "target_release_utc": fmt_instant(t["target_release_utc"]),
        "release_mode": t["release_mode"],
        "localization_state": t["localization_state"],
        "string_lock": t["string_lock"],
        "extracted_key_count": t["extracted_key_count"],
        "market_plan_count": t["market_plan_count"],
        "ready_market_count": t["ready_market_count"],
        "release_gate_state": t["release_gate_state"],
    })


def market_plan_out(p):
    return _common(p, {
        "title_id": p["title_id"],
        "market_code": p["market_code"],
        "rating_board": p["rating_board"],
        "target_rating": p["target_rating"],
        "scope_tier": p["scope_tier"],
        "cultural_adaptation_required": p["cultural_adaptation_required"],
        "budget_cap_cents": p["budget_cap_cents"],
        "status": p["status"],
        "blocked_reason": p["blocked_reason"],
        "required_unit_count": p["required_unit_count"],
        "delivered_unit_count": p["delivered_unit_count"],
        "required_voice_line_count": p["required_voice_line_count"],
        "voice_recorded_line_count": p["voice_recorded_line_count"],
        "text_effort_units": _num(p["text_effort_units"]),
        "text_effort_variant": p["text_effort_variant"],
        "localization_cost_cents": p["localization_cost_cents"],
        "overage_cents": p["overage_cents"],
    })


def string_key_out(k):
    return _common(k, {
        "title_id": k["title_id"],
        "key_name": k["key_name"],
        "source_text": k["source_text"],
        "source_char_count": k["source_char_count"],
        "ui_surface": k["ui_surface"],
        "display_char_limit": k["display_char_limit"],
        "tm_match_pct": k["tm_match_pct"],
        "context_note": k["context_note"],
        "status": k["status"],
    })


def translation_unit_out(u):
    return _common(u, {
        "string_key_id": u["string_key_id"],
        "market_plan_id": u["market_plan_id"],
        "target_text": u["target_text"],
        "target_char_count": u["target_char_count"],
        "applied_tm_match_pct": u["applied_tm_match_pct"],
        "overflow_chars": u["overflow_chars"],
        "translation_status": u["translation_status"],
        "qa_status": u["qa_status"],
        "open_bug_count": u["open_bug_count"],
    })


def booth_out(b):
    return _common(b, {
        "booth_code": b["booth_code"],
        "studio_city": b["studio_city"],
        "turnaround_buffer_minutes": b["turnaround_buffer_minutes"],
        "reserved_minutes_total": b["reserved_minutes_total"],
    })


def voice_talent_out(v):
    from derive import talent_reserved_minutes_on_date
    return _common(v, {
        "talent_name": v["talent_name"],
        "language_code": v["language_code"],
        "union_flag": v["union_flag"],
        "max_daily_recording_minutes": v["max_daily_recording_minutes"],
        "reserved_minutes_on_clock_date": talent_reserved_minutes_on_date(
            v["id"], db.now().date()
        ),
    })


def talent_contract_out(c):
    return _common(c, {
        "voice_talent_id": c["voice_talent_id"],
        "title_id": c["title_id"],
        "territory_scope": list(c["territory_scope"]),
        "media_scope": c["media_scope"],
        "buyout_fee_cents": c["buyout_fee_cents"],
        "per_line_rate_cents": c["per_line_rate_cents"],
        "rights_start_utc": fmt_instant(c["rights_start_utc"]),
        "rights_end_utc": fmt_instant(c["rights_end_utc"]),
        "status": c["status"],
        "signed_at_utc": fmt_instant(c["signed_at_utc"]),
        "committed_fee_cents": c["committed_fee_cents"],
    })


def voice_session_out(s):
    return _common(s, {
        "market_plan_id": s["market_plan_id"],
        "voice_talent_id": s["voice_talent_id"],
        "recording_booth_id": s["recording_booth_id"],
        "talent_contract_id": s["talent_contract_id"],
        "start_utc": fmt_instant(s["start_utc"]),
        "end_utc": fmt_instant(s["end_utc"]),
        "duration_minutes": s["duration_minutes"],
        "occupied_end_utc": fmt_instant(s["occupied_end_utc"]),
        "planned_line_count": s["planned_line_count"],
        "recorded_line_count": s["recorded_line_count"],
        "status": s["status"],
        "line_fee_cents": s["line_fee_cents"],
    })


def qa_pass_out(q):
    return _common(q, {
        "market_plan_id": q["market_plan_id"],
        "pass_type": q["pass_type"],
        "pass_index": q["pass_index"],
        "inspected_unit_count": q["inspected_unit_count"],
        "opened_by_user_id": q["opened_by_user_id"],
        "status": q["status"],
        "reopen_count": q["reopen_count"],
        "weighted_defect_points": q["weighted_defect_points"],
        "defect_density": _num(q["defect_density"]),
        "closed_at_utc": fmt_instant(q["closed_at_utc"]),
    })


def lqa_bug_out(b):
    return _common(b, {
        "qa_pass_id": b["qa_pass_id"],
        "translation_unit_id": b["translation_unit_id"],
        "duplicate_of_bug_id": b["duplicate_of_bug_id"],
        "bug_class": b["bug_class"],
        "severity": b["severity"],
        "summary": b["summary"],
        "status": b["status"],
        "logged_by_user_id": b["logged_by_user_id"],
        "verified_by_user_id": b["verified_by_user_id"],
        "severity_weight": b["severity_weight"],
        "axis": b["axis"],
    })


def rating_submission_out(s):
    return _common(s, {
        "market_plan_id": s["market_plan_id"],
        "submission_round": s["submission_round"],
        "rating_board": s["rating_board"],
        "disclosed_content_codes": list(s["disclosed_content_codes"]),
        "footage_asset_count": s["footage_asset_count"],
        "target_rating": s["target_rating"],
        "assigned_rating": s["assigned_rating"],
        "self_assessed_risk_score": s["self_assessed_risk_score"],
        "board_adjusted_risk_score": s["board_adjusted_risk_score"],
        "projected_rating_band": s["projected_rating_band"],
        "fee_cents": s["fee_cents"],
        "status": s["status"],
        "submitted_by_user_id": s["submitted_by_user_id"],
        "reviewed_by_user_id": s["reviewed_by_user_id"],
        "appeal_count": s["appeal_count"],
        "submitted_at_utc": fmt_instant(s["submitted_at_utc"]),
    })


def content_edit_out(e):
    return _common(e, {
        "rating_submission_id": e["rating_submission_id"],
        "edit_kind": e["edit_kind"],
        "affected_string_key_ids": list(e["affected_string_key_ids"]),
        "removed_content_codes": list(e["removed_content_codes"]),
        "rationale": e["rationale"],
        "status": e["status"],
        "invalidated_unit_count": e["invalidated_unit_count"],
        "applied_at_utc": fmt_instant(e["applied_at_utc"]),
    })


# ------------------------------------------------------------- natural keys
def nk_title(t):
    return t["title_code"]


def nk_market_plan(p):
    return p["market_code"]


def nk_string_key(k):
    return k["key_name"]


def nk_translation_unit(u):
    key = db.string_keys.get(u["string_key_id"])
    return key["key_name"] if key else ""


def nk_booth(b):
    return b["booth_code"]


def nk_voice_talent(v):
    return v["talent_name"]


def nk_talent_contract(c):
    return c["rights_start_utc"]


def nk_voice_session(s):
    return s["start_utc"]


def nk_qa_pass(q):
    return q["pass_index"]


def nk_lqa_bug(b):
    return b["summary"]


def nk_rating_submission(s):
    return s["submission_round"]


def nk_content_edit(e):
    return e["edit_kind"]
