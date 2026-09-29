"""Calculations, derived fields and ordered cascades (PRD SS2.8, SS2.10, SS3)."""
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    APPLIED_EDIT_CREDIT,
    BOARD_BASE_FEE_CENTS,
    BUG_OPEN_STATUSES,
    CERT_WINDOW_DAYS,
    CULTURAL_FLOOR_CENTS,
    CULTURAL_PCT,
    DESCRIPTOR_WEIGHT,
    EXPEDITE_DAY_THRESHOLD,
    EXPEDITE_PCT,
    LEGAL_BUG_PENALTY,
    PROPOSED_EDIT_PENALTY,
    RATING_BANDS,
    RATING_STRICTNESS,
    ROUND_SURCHARGE_CENTS,
    SCOPE_MULTIPLIER,
    SESSION_ACTIVE_STATUSES,
    SEVERITY_WEIGHT,
    SURFACE_UPLIFT,
    TEXT_RATE_CENTS_PER_UNIT,
    VOLUME_TIER_1_CENTS,
    VOLUME_TIER_1_PCT,
    VOLUME_TIER_2_CENTS,
    VOLUME_TIER_2_PCT,
    tm_factor,
)
from db import db, rows, touch

ZERO0 = Decimal("1")
ZERO1 = Decimal("0.1")
ZERO2 = Decimal("0.01")
ZERO4 = Decimal("0.0001")


def q0(value):
    return int(Decimal(value).quantize(ZERO0, rounding=ROUND_HALF_UP))


def q1(value):
    return Decimal(value).quantize(ZERO1, rounding=ROUND_HALF_UP)


def q2(value):
    return Decimal(value).quantize(ZERO2, rounding=ROUND_HALF_UP)


def q4(value):
    return Decimal(value).quantize(ZERO4, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------- child selectors
def title_keys(title_id):
    return [k for k in rows("string_keys") if k["title_id"] == title_id]


def title_plans(title_id):
    return [p for p in rows("market_plans") if p["title_id"] == title_id]


def plan_units(plan_id):
    return [u for u in rows("translation_units") if u["market_plan_id"] == plan_id]


def plan_passes(plan_id):
    return [q for q in rows("qa_passes") if q["market_plan_id"] == plan_id]


def pass_bugs(pass_id):
    return [b for b in rows("lqa_bugs") if b["qa_pass_id"] == pass_id]


def plan_bugs(plan_id):
    ids = set(q["id"] for q in plan_passes(plan_id))
    return [b for b in rows("lqa_bugs") if b["qa_pass_id"] in ids]


def unit_bugs(unit_id):
    return [b for b in rows("lqa_bugs") if b["translation_unit_id"] == unit_id]


def plan_sessions(plan_id):
    return [s for s in rows("voice_sessions") if s["market_plan_id"] == plan_id]


def contract_sessions(contract_id):
    return [s for s in rows("voice_sessions") if s["talent_contract_id"] == contract_id]


def booth_sessions(booth_id):
    return [s for s in rows("voice_sessions") if s["recording_booth_id"] == booth_id]


def talent_sessions(talent_id):
    return [s for s in rows("voice_sessions") if s["voice_talent_id"] == talent_id]


def plan_submissions(plan_id):
    return [s for s in rows("rating_submissions") if s["market_plan_id"] == plan_id]


def submission_edits(submission_id):
    return [e for e in rows("content_edits") if e["rating_submission_id"] == submission_id]


def by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


# ---------------------------------------------------------------- clock maths
def days_to_release(title):
    delta = title["target_release_utc"] - db.now()
    return int(delta.total_seconds() // 86400)


# -------------------------------------------------------- title derived state
def title_release_gate_state(title):
    plans = title_plans(title["id"])
    total = len(plans)
    ready = sum(1 for p in plans if p["status"] == "RELEASE_READY")
    blocked = sum(1 for p in plans if p["status"] == "BLOCKED")
    if blocked >= 1:
        return "BLOCKED"
    if total >= 1 and ready == total:
        return "CLEARED"
    if title["release_mode"] == "SIMULTANEOUS" and 1 <= ready < total:
        return "AT_RISK"
    if total >= 1 and ready < total and days_to_release(title) < CERT_WINDOW_DAYS:
        return "AT_RISK"
    return "OPEN"


def refresh_title(title):
    """Recompute the title's derived counters and gate posture."""
    keys = title_keys(title["id"])
    plans = title_plans(title["id"])
    updated = {
        "extracted_key_count": sum(
            1 for k in keys if k["status"] in ("EXTRACTED", "LOCKED")
        ),
        "market_plan_count": len(plans),
        "ready_market_count": sum(1 for p in plans if p["status"] == "RELEASE_READY"),
        "string_lock": title["localization_state"] != "PLANNING",
        "release_gate_state": title_release_gate_state(title),
    }
    changed = any(title.get(k) != v for k, v in updated.items())
    title.update(updated)
    if changed:
        touch(title)
    return title


# --------------------------------------------------- market plan derived state
def locked_key_count(plan):
    return sum(1 for k in title_keys(plan["title_id"]) if k["status"] == "LOCKED")


def nonretired_key_count(plan):
    return sum(1 for k in title_keys(plan["title_id"]) if k["status"] != "RETIRED")


def delivered_unit_count(plan):
    return sum(
        1 for u in plan_units(plan["id"]) if u["translation_status"] == "DELIVERED"
    )


def voice_recorded_line_count(plan):
    return sum(
        (s["recorded_line_count"] or 0)
        for s in plan_sessions(plan["id"])
        if s["status"] == "RECORDED"
    )


def _assign(row, field, value):
    if row.get(field) != value:
        row[field] = value
        touch(row)


def recompute_plan_required(plan, value=None):
    _assign(plan, "required_unit_count",
            locked_key_count(plan) if value is None else value)


def recompute_plan_delivered(plan):
    _assign(plan, "delivered_unit_count", delivered_unit_count(plan))


def recompute_plan_voice(plan):
    _assign(plan, "voice_recorded_line_count", voice_recorded_line_count(plan))


# -------------------------------------------------------------- effort (SS3.2)
def _effort_rows(plan, variant):
    """(sort_key, source_char_count, tm_match_pct, ui_surface) per contributing row."""
    out = []
    if variant == "SCOPE_ESTIMATE":
        for key in title_keys(plan["title_id"]):
            if key["status"] in ("EXTRACTED", "LOCKED"):
                out.append((
                    (key["created_at"], key["key_name"]),
                    key["source_char_count"],
                    key["tm_match_pct"],
                    key["ui_surface"],
                ))
    else:
        for unit in plan_units(plan["id"]):
            if unit["translation_status"] != "DELIVERED":
                continue
            key = db.string_keys.get(unit["string_key_id"])
            if key is None:
                continue
            out.append((
                (key["created_at"], key["key_name"]),
                key["source_char_count"],
                unit["applied_tm_match_pct"],
                key["ui_surface"],
            ))
    out.sort(key=lambda r: r[0])
    return out


def compute_effort(plan, variant):
    """Round each row to 1 dp FIRST, then sum, then round the sum to 2 dp."""
    total = Decimal("0")
    for _key, chars, tm_pct, surface in _effort_rows(plan, variant):
        raw = (Decimal(chars) / Decimal(100)) * tm_factor(tm_pct) * SURFACE_UPLIFT[surface]
        total += q1(raw)
    return q2(total)


def set_plan_effort(plan, variant):
    value = compute_effort(plan, variant)
    if plan.get("text_effort_units") != value or plan.get("text_effort_variant") != variant:
        plan["text_effort_units"] = value
        plan["text_effort_variant"] = variant
        touch(plan)
    recompute_plan_cost(plan)


# ---------------------------------------------------------------- cost (SS3.2)
def text_cost_cents(plan):
    tier = plan["scope_tier"]
    multiplier = SCOPE_MULTIPLIER.get(tier, Decimal("1.00"))
    effort = Decimal(plan["text_effort_units"] or 0)
    return q0(effort * TEXT_RATE_CENTS_PER_UNIT * multiplier)


def voice_cost_cents(plan):
    total = 0
    for session in plan_sessions(plan["id"]):
        if session["status"] != "RECORDED":
            continue
        contract = db.talent_contracts.get(session["talent_contract_id"])
        if contract is None:
            continue
        total += (session["recorded_line_count"] or 0) * contract["per_line_rate_cents"]
    return total


def recompute_plan_cost(plan):
    text = text_cost_cents(plan)
    voice = voice_cost_cents(plan)
    if plan["scope_tier"] == "FULL_CULTURAL":
        surcharge = max(
            CULTURAL_FLOOR_CENTS, q0(CULTURAL_PCT * Decimal(text + voice))
        )
    else:
        surcharge = 0
    subtotal = text + voice + surcharge
    cap = plan["budget_cap_cents"]
    _assign(plan, "localization_cost_cents", min(subtotal, cap))
    _assign(plan, "overage_cents", max(0, subtotal - cap))


# ------------------------------------------------------- booth / talent minutes
def booth_reserved_minutes(booth):
    """Duration plus the booth's turnaround buffer for every live session."""
    total = 0
    for session in booth_sessions(booth["id"]):
        if session["status"] in SESSION_ACTIVE_STATUSES:
            total += session["duration_minutes"] + booth["turnaround_buffer_minutes"]
    return total


def recompute_booth(booth):
    _assign(booth, "reserved_minutes_total", booth_reserved_minutes(booth))


def talent_reserved_minutes_on_date(talent_id, day):
    """Aggregate recording minutes for sessions STARTING on the given UTC date."""
    total = 0
    for session in talent_sessions(talent_id):
        if session["status"] not in SESSION_ACTIVE_STATUSES:
            continue
        if session["start_utc"].date() == day:
            total += session["duration_minutes"]
    return total


# ------------------------------------------------------ contract ledger (SS3.4)
def contract_committed_fee(contract):
    if contract["status"] == "DRAFT":
        return 0
    total = contract["buyout_fee_cents"]
    for session in contract_sessions(contract["id"]):
        if session["status"] == "RECORDED":
            total += (session["recorded_line_count"] or 0) * contract["per_line_rate_cents"]
    return total


def recompute_contract_ledger(contract):
    _assign(contract, "committed_fee_cents", contract_committed_fee(contract))


# ------------------------------------------------------- defect density (SS3.6)
def pass_weighted_points(qa_pass):
    return sum(
        SEVERITY_WEIGHT[b["severity"]]
        for b in pass_bugs(qa_pass["id"])
        if b["status"] in BUG_OPEN_STATUSES
    )


def recompute_pass_density(qa_pass):
    points = pass_weighted_points(qa_pass)
    density = q4(Decimal(points) / Decimal(qa_pass["inspected_unit_count"]))
    changed = (
        qa_pass.get("weighted_defect_points") != points
        or qa_pass.get("defect_density") != density
    )
    qa_pass["weighted_defect_points"] = points
    qa_pass["defect_density"] = density
    if changed:
        touch(qa_pass)


def recompute_unit_open_bugs(unit):
    count = sum(1 for b in unit_bugs(unit["id"]) if b["status"] in BUG_OPEN_STATUSES)
    _assign(unit, "open_bug_count", count)


def apply_unit_text(unit, target_text):
    """Store target text and re-derive target_char_count / overflow_chars."""
    key = db.string_keys.get(unit["string_key_id"])
    limit = key["display_char_limit"] if key else 0
    char_count = len(target_text) if target_text is not None else 0
    overflow = max(0, char_count - limit)
    changed = (
        unit.get("target_text") != target_text
        or unit.get("target_char_count") != char_count
        or unit.get("overflow_chars") != overflow
    )
    unit["target_text"] = target_text
    unit["target_char_count"] = char_count
    unit["overflow_chars"] = overflow
    return changed


def flag_unit_for_bug(unit, axis):
    """LINGUISTIC findings overwrite more states than FUNCTIONAL ones do."""
    current = unit["qa_status"]
    if axis == "LINGUISTIC":
        if current in ("NOT_CHECKED", "PASSED", "FUNC_FLAGGED"):
            unit["qa_status"] = "LING_FLAGGED"
    else:
        if current in ("NOT_CHECKED", "PASSED"):
            unit["qa_status"] = "FUNC_FLAGGED"
    touch(unit)


# ------------------------------------------------- rating risk / fee (SS3.7)
def effective_disclosure_set(submission):
    """Disclosed codes minus every code removed by an APPLIED content edit."""
    removed = set()
    for edit in submission_edits(submission["id"]):
        if edit["status"] == "APPLIED":
            removed.update(edit["removed_content_codes"])
    return [c for c in submission["disclosed_content_codes"] if c not in removed]


def _clamp(score):
    return max(0, min(100, score))


def descriptor_base(submission):
    return sum(DESCRIPTOR_WEIGHT[c] for c in effective_disclosure_set(submission))


def unresolved_legal_defect_count(plan_id):
    return sum(
        1
        for b in plan_bugs(plan_id)
        if b["bug_class"] == "LEGAL_TEXT" and b["status"] in BUG_OPEN_STATUSES
    )


def proposed_edit_count(submission):
    return sum(1 for e in submission_edits(submission["id"]) if e["status"] == "PROPOSED")


def applied_edit_count(submission):
    return sum(1 for e in submission_edits(submission["id"]) if e["status"] == "APPLIED")


def self_assessed_risk_score(submission):
    return _clamp(descriptor_base(submission))


def board_adjusted_risk_score(submission):
    base = descriptor_base(submission)
    legal = unresolved_legal_defect_count(submission["market_plan_id"])
    proposed = proposed_edit_count(submission)
    applied = applied_edit_count(submission)
    return _clamp(
        base
        + LEGAL_BUG_PENALTY * legal
        + PROPOSED_EDIT_PENALTY * proposed
        - APPLIED_EDIT_CREDIT * applied
    )


def band_for_score(score):
    if score <= 20:
        return "ALL_AGES"
    if score <= 40:
        return "TEEN_12"
    if score <= 60:
        return "MATURE_15"
    if score <= 80:
        return "MATURE_17"
    return "ADULTS_ONLY_18"


def compute_fee_cents(submission, title):
    pre = (
        BOARD_BASE_FEE_CENTS[submission["rating_board"]]
        + (submission["submission_round"] - 1) * ROUND_SURCHARGE_CENTS
    )
    days = days_to_release(title)
    expedite = q0(Decimal(pre) * EXPEDITE_PCT) if days < EXPEDITE_DAY_THRESHOLD else 0
    if pre >= VOLUME_TIER_2_CENTS:
        pct = VOLUME_TIER_2_PCT
    elif pre >= VOLUME_TIER_1_CENTS:
        pct = VOLUME_TIER_1_PCT
    else:
        pct = Decimal("0")
    discount = q0(Decimal(pre) * pct)
    return pre + expedite - discount


def governing_submission(plan_id):
    subs = plan_submissions(plan_id)
    if not subs:
        return None
    return max(subs, key=lambda s: s["submission_round"])


def stricter(band_a, band_b):
    """True when band_a is strictly stricter than band_b."""
    return RATING_STRICTNESS[band_a] > RATING_STRICTNESS[band_b]


def refresh_submission_board_view(submission):
    score = board_adjusted_risk_score(submission)
    submission["board_adjusted_risk_score"] = score
    submission["projected_rating_band"] = band_for_score(score)


# ------------------------------------------------------------ cascades (SS2.10)
def bubble_title_to_cert(title):
    plans = title_plans(title["id"])
    if (
        title["localization_state"] == "STRINGS_LOCKED"
        and len(plans) >= 1
        and all(p["status"] in ("LQA", "RELEASE_READY") for p in plans)
    ):
        title["localization_state"] = "CERT_WINDOW"
        touch(title)
    refresh_title(title)


def bubble_title_to_shipped(title):
    plans = title_plans(title["id"])
    ready = sum(1 for p in plans if p["status"] == "RELEASE_READY")
    if (
        title["localization_state"] == "CERT_WINDOW"
        and len(plans) >= 1
        and ready == len(plans)
    ):
        title["localization_state"] = "SHIPPED"
        touch(title)
    # release_gate_state resolves to CLEARED via clause 2 of the gate chain
    refresh_title(title)


def revert_title_from_cert(title):
    if title["localization_state"] == "CERT_WINDOW" and any(
        p["status"] in ("DRAFT", "SCOPED", "IN_LOCALIZATION")
        for p in title_plans(title["id"])
    ):
        title["localization_state"] = "STRINGS_LOCKED"
        touch(title)
    refresh_title(title)


def plan_lqa_deficient(plan):
    return (
        plan["delivered_unit_count"] < plan["required_unit_count"]
        or plan["voice_recorded_line_count"] < plan["required_voice_line_count"]
    )


def revert_plan_from_lqa(plan):
    """LQA -> IN_LOCALIZATION, reopening every CLOSED pass; returns those passes."""
    plan["status"] = "IN_LOCALIZATION"
    touch(plan)
    set_plan_effort(plan, "DELIVERED_ACTUAL")
    reopened = []
    for qa_pass in by_created(plan_passes(plan["id"])):
        if qa_pass["status"] == "CLOSED":
            qa_pass["status"] = "OPEN"
            qa_pass["reopen_count"] = qa_pass["reopen_count"] + 1
            qa_pass["closed_at_utc"] = None
            touch(qa_pass)
            reopened.append(qa_pass)
    title = db.titles.get(plan["title_id"])
    if title is not None:
        revert_title_from_cert(title)
    return reopened


def release_session(session):
    """Cancel a session and release its booth reservation."""
    session["status"] = "CANCELLED"
    session["line_fee_cents"] = 0
    touch(session)
    booth = db.booths.get(session["recording_booth_id"])
    if booth is not None:
        recompute_booth(booth)


def cancel_session_cascade(session):
    """Ordered cancellation cascade for a session in any live status (SS3.5)."""
    was_recorded = session["status"] == "RECORDED"
    release_session(session)
    if not was_recorded:
        return
    contract = db.talent_contracts.get(session["talent_contract_id"])
    if contract is not None:
        contract["committed_fee_cents"] = contract_committed_fee(contract)
        touch(contract)
    plan = db.market_plans.get(session["market_plan_id"])
    if plan is None:
        return
    plan["voice_recorded_line_count"] = voice_recorded_line_count(plan)
    touch(plan)
    recompute_plan_cost(plan)
    # hop four is scoped to the voice quota specifically (SS3.5)
    if (
        plan["status"] == "LQA"
        and plan["voice_recorded_line_count"] < plan["required_voice_line_count"]
    ):
        revert_plan_from_lqa(plan)


def expire_contract_if_lapsed(contract):
    """Lazy expiry: SIGNED contracts whose rights window has closed."""
    if contract["status"] == "SIGNED" and db.now() >= contract["rights_end_utc"]:
        contract["status"] = "EXPIRED"
        touch(contract)
    return contract


def cancel_scheduled_sessions(sessions):
    affected_plans = []
    for session in by_created(sessions):
        if session["status"] == "SCHEDULED":
            release_session(session)
            plan = db.market_plans.get(session["market_plan_id"])
            if plan is not None and plan not in affected_plans:
                affected_plans.append(plan)
    return affected_plans
