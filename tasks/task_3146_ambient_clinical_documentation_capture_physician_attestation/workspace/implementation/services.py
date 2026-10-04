"""Business logic: calculations, cascades, state-machine side effects.

All constants come from SCAFFOLD.yaml / PRD.md.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from helpers import (
    now_ts, touch, new_entity, new_id, round_half_up_int, round_half_up_4,
    parse_iso8601_utc, fmt_ts,
)

# ---- constants ----
PENALTY_BY_IMPORTANCE = {"CRITICAL": 25, "MAJOR": 10, "MINOR": 5}
CRITICAL_CAP = 49
ATTEST_MINIMUM = 80
BILLING_CAP_CENTS = 10000000
MAX_ACTIVE_SUGGESTIONS = 8
REVOKED_RETENTION_CAP_DAYS = 30
REASSIGNMENT_DECAY = Decimal("0.9")
CAPTURE_GAP_SECONDS = 60

QA_W_BASE = (Decimal("0.5"), Decimal("0.3"), Decimal("0.2"))
QA_W_APPEAL = (Decimal("0.7"), Decimal("0.2"), Decimal("0.1"))

AFTER_HOURS_WINDOWS = [(0, 7), (18, 24)]  # UTC hours [start, end)


# ---------------------------------------------------------------- helpers
def month_bounds(dt):
    """Return (period_start, period_end) datetimes for the calendar month containing dt."""
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def get_template(draft):
    return db.stores["note_templates"].get(draft["template_id"])


def get_encounter_of_draft(draft):
    return db.stores["encounters"].get(draft["encounter_id"])


def fields_of_draft(draft_id):
    return [f for f in db.stores["note_fields"].values() if f["note_draft_id"] == draft_id]


def suggestions_of_draft(draft_id):
    return [s for s in db.stores["code_suggestions"].values() if s["note_draft_id"] == draft_id]


def captures_of_encounter(encounter_id):
    return [c for c in db.stores["audio_captures"].values() if c["encounter_id"] == encounter_id]


def drafts_of_encounter(encounter_id):
    return [d for d in db.stores["note_drafts"].values() if d["encounter_id"] == encounter_id]


def consents_of_encounter(encounter_id):
    return [c for c in db.stores["consents"].values() if c["encounter_id"] == encounter_id]


def active_consent(encounter_id):
    """Return the GRANTED AmbientConsent on the encounter, if any."""
    for c in consents_of_encounter(encounter_id):
        if c["status"] == "GRANTED":
            return c
    return None


# ---------------------------------------------------------------- completeness
def compute_completeness(draft):
    """note_completeness_score per scaffold formula."""
    template = get_template(draft)
    multiplier = Decimal(str(template["completeness_multiplier"])) if template else Decimal("1.0")
    missing_penalty_sum = Decimal("0")
    has_missing_critical = False
    for f in fields_of_draft(draft["id"]):
        if not f.get("required"):
            continue
        fv = f.get("field_value")
        if fv is None or (isinstance(fv, str) and fv == ""):
            penalty = PENALTY_BY_IMPORTANCE.get(f["importance"], 0)
            missing_penalty_sum += Decimal(penalty) * multiplier
            if f["importance"] == "CRITICAL":
                has_missing_critical = True
    rounded = int(missing_penalty_sum.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    raw = 100 - rounded
    if has_missing_critical:
        raw = min(raw, CRITICAL_CAP)
    return max(0, min(100, raw))


def recompute_draft_completeness(draft):
    draft["completeness_score"] = compute_completeness(draft)


# ---------------------------------------------------------------- billing
def line_total_cents(suggestion):
    if suggestion["code_type"] != "BILLING":
        return 0
    unit = Decimal(str(suggestion["unit_fee_cents"]))
    qty = Decimal(str(suggestion["quantity"]))
    # adjustment_pct is normalized to two-decimal precision before applying,
    # so e.g. 1.004 -> 1.00 (per benchmark contract: 1000*1*1.004 -> 1000).
    adj = Decimal(str(suggestion["adjustment_pct"])).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    product = unit * qty * adj
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_billing_totals(draft):
    """Recompute billing_provisional_cents and billing_final_cents per formula."""
    provisional = 0
    final = 0
    for s in suggestions_of_draft(draft["id"]):
        if s["code_type"] != "BILLING":
            continue
        line = s["line_total_cents"]
        if s["status"] == "CONFIRMED":
            final += line
        if s["status"] in ("SUGGESTED", "MODIFIED", "CONFIRMED"):
            conf = Decimal(str(s["confidence"]))
            weighted = (Decimal(line) * conf).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            provisional += int(weighted)
    draft["billing_provisional_cents"] = provisional
    draft["billing_final_cents"] = final


def recompute_ranks(draft_id):
    """Assign 1-based dense ranks over non-terminal suggestions by confidence DESC,
    tie-break created_at ASC."""
    suggs = [s for s in suggestions_of_draft(draft_id)
             if s["status"] in ("SUGGESTED", "MODIFIED", "CONFIRMED")]
    # sort: confidence desc, created_at asc; stable
    suggs.sort(key=lambda s: s["created_at"])
    suggs.sort(key=lambda s: -float(s["confidence"]))
    for idx, s in enumerate(suggs, start=1):
        s["rank"] = idx


# ---------------------------------------------------------------- metrics
def metric_for(physician_id, period_start_dt):
    """Find existing DocumentationMetric row for the (physician, month)."""
    start, end = month_bounds(period_start_dt)
    for m in db.stores["doc_metrics"].values():
        if m["physician_id"] != physician_id:
            continue
        if m["period_start"] == fmt_ts(start):
            return m
    return None


def ensure_metric(physician_id, period_dt):
    m = metric_for(physician_id, period_dt)
    if m is not None:
        return m
    start, end = month_bounds(period_dt)
    m = new_entity({
        "physician_id": physician_id,
        "period_start": fmt_ts(start),
        "period_end": fmt_ts(end),
        "notes_attested": 0,
        "provisional_minutes": 0,
        "final_minutes": 0,
        "after_hours_minutes": 0,
        "status": "PROVISIONAL",
        "finalized_at": None,
    })
    db.stores["doc_metrics"][m["id"]] = m
    return m


def _spans_for_period(physician_id, period_start_dt):
    """Yield (attestation, encounter) pairs for the physician in the period."""
    start, end = month_bounds(period_start_dt)
    out = []
    for att in db.stores["attestations"].values():
        if att["physician_id"] != physician_id:
            continue
        att_dt = parse_iso8601_utc(att["attested_at"])
        if att_dt is None:
            continue
        if not (start <= att_dt < end):
            continue
        draft = db.stores["note_drafts"].get(att["note_draft_id"])
        if draft is None:
            continue
        enc = db.stores["encounters"].get(draft["encounter_id"])
        if enc is None:
            continue
        started = parse_iso8601_utc(enc.get("started_at") or "")
        if started is None:
            continue
        out.append((att, enc, started, att_dt))
    return out


def _ceil_minutes(delta_seconds):
    """Ceil to whole minutes: sub-minute remainders rounded up."""
    if delta_seconds <= 0:
        return 0
    whole = int(delta_seconds // 60)
    if delta_seconds - whole * 60 > 0:
        return whole + 1
    return whole


def _trunc_minutes(delta_seconds):
    if delta_seconds <= 0:
        return 0
    return int(delta_seconds // 60)


def _paused_minutes_for_encounter(encounter_id, window_start=None, window_end=None):
    """Total PAUSED interval minutes of the encounter's captures, optionally
    restricted to a time window (in absolute datetimes). Returns a float of seconds."""
    total_secs = 0.0
    for cap in captures_of_encounter(encounter_id):
        for p_start, p_end in cap.get("pause_intervals", []):
            ps = parse_iso8601_utc(p_start)
            pe = parse_iso8601_utc(p_end) if p_end else None
            if ps is None or pe is None:
                continue
            if window_start is not None and window_end is not None:
                lo = max(ps, window_start)
                hi = min(pe, window_end)
                if hi > lo:
                    total_secs += (hi - lo).total_seconds()
            else:
                total_secs += (pe - ps).total_seconds()
    return total_secs


def _after_hours_seconds(span_start, span_end):
    """Total seconds of [span_start, span_end) falling into [18:00,24:00) or [00:00,07:00) UTC."""
    if span_end <= span_start:
        return 0.0
    total = 0.0
    cur_date = span_start.date()
    # Iterate by day
    from datetime import datetime as _dt, time as _tm, timedelta as _td
    day = _dt.combine(cur_date, _tm(0, 0), tzinfo=timezone.utc)
    # back up to include the day before span_start in case it crosses midnight
    day = day - _td(days=1)
    end_day = _dt.combine(span_end.date(), _tm(0, 0), tzinfo=timezone.utc) + _td(days=1)
    while day <= end_day:
        for win_start_h, win_end_h in AFTER_HOURS_WINDOWS:
            ws = day + _td(hours=win_start_h)
            we = day + _td(hours=win_end_h)
            lo = max(span_start, ws)
            hi = min(span_end, we)
            if hi > lo:
                total += (hi - lo).total_seconds()
        day += _td(days=1)
    return total


def recompute_metric(metric, physician_id):
    """Recompute provisional_minutes, final_minutes, after_hours_minutes on the row."""
    period_start_dt = parse_iso8601_utc(metric["period_start"])
    spans = _spans_for_period(physician_id, period_start_dt)
    provisional_total = 0
    final_total = 0
    after_hours_total = 0
    for att, enc, started, att_dt in spans:
        span_secs = (att_dt - started).total_seconds()
        # provisional: ceil to whole minutes per span
        prov_min = _ceil_minutes(span_secs)
        provisional_total += prov_min

        # paused seconds inside this span (from encounter's captures)
        paused_secs = _paused_minutes_for_encounter(enc["id"], started, att_dt)
        # final: per-span, subtract paused, then truncate per span
        final_span_secs = max(0.0, span_secs - paused_secs)
        final_min = _trunc_minutes(final_span_secs)
        final_total += final_min

        # after hours
        ah_secs = _after_hours_seconds(started, att_dt)
        ah_paused_secs = 0.0
        # paused minutes inside after-hours windows
        for cap in captures_of_encounter(enc["id"]):
            for p_start, p_end in cap.get("pause_intervals", []):
                ps = parse_iso8601_utc(p_start)
                pe = parse_iso8601_utc(p_end) if p_end else None
                if ps is None or pe is None:
                    continue
                # overlap with [started, att_dt)
                lo = max(ps, started)
                hi = min(pe, att_dt)
                if hi <= lo:
                    continue
                ah_paused_secs += _after_hours_seconds(lo, hi)
        ah_total_secs = max(0.0, ah_secs - ah_paused_secs)
        after_hours_total += _trunc_minutes(ah_total_secs)

    metric["provisional_minutes"] = provisional_total
    metric["final_minutes"] = final_total
    metric["after_hours_minutes"] = after_hours_total


# ---------------------------------------------------------------- cascades
def cascade_consent_end(encounter, consent, end_status, end_reason, purge_reason_for_recording,
                        revocation_reason=None):
    """Cascade on opt-out / revoke / expire.

    - captures in RECORDING/PAUSED -> PURGED (purge_reason per trigger)
    - captures in CAPTURED/TRANSCRIBED (only for OPT_OUT/REVOKE): retention_days_effective = min(planned, 30)
    - AUDIO note fields of the encounter's drafts: field_value := null, validated := false
    - drafts in IN_REVIEW/EDITED -> DRAFT, completeness recomputed
    - drafts in ATTESTED -> phi_review_required := true (status unchanged)
    - encounter.audio_status := NOT_RECORDING if all captures terminal
    """
    now = now_ts()
    consent["status"] = end_status
    consent["ended_at"] = now
    consent["end_reason"] = end_reason
    if revocation_reason is not None:
        consent["revocation_reason"] = revocation_reason
    touch(consent)

    for cap in captures_of_encounter(encounter["id"]):
        if cap["status"] in ("RECORDING", "PAUSED"):
            cap["status"] = "PURGED"
            cap["purge_reason"] = purge_reason_for_recording
            # close any open pause interval
            for iv in cap.get("pause_intervals", []):
                if iv[1] is None:
                    iv[1] = now
            if cap.get("ended_at") is None:
                cap["ended_at"] = now
            touch(cap)
        elif cap["status"] in ("CAPTURED", "TRANSCRIBED") and end_reason in ("OPT_OUT", "REVOKE"):
            cap["retention_days_effective"] = min(cap["planned_retention_days"],
                                                  REVOKED_RETENTION_CAP_DAYS)
            touch(cap)

    for draft in drafts_of_encounter(encounter["id"]):
        if draft["status"] in ("VOID",):
            continue
        any_audio_invalidated = False
        for f in fields_of_draft(draft["id"]):
            if f.get("source") == "AUDIO":
                f["field_value"] = None
                f["validated"] = False
                touch(f)
                any_audio_invalidated = True
        if any_audio_invalidated:
            if draft["status"] in ("IN_REVIEW", "EDITED"):
                draft["status"] = "DRAFT"
                recompute_draft_completeness(draft)
                touch(draft)
                if encounter["documentation_status"] in ("IN_REVIEW",):
                    encounter["documentation_status"] = "DRAFTING"
            elif draft["status"] == "ATTESTED":
                if not draft.get("phi_review_required"):
                    draft["phi_review_required"] = True
                    touch(draft)
        elif draft["status"] == "ATTESTED":
            # ATTESTED drafts are flagged regardless of whether they had AUDIO fields
            if not draft.get("phi_review_required"):
                draft["phi_review_required"] = True
                touch(draft)

    # audio_status return to NOT_RECORDING if all captures terminal
    all_terminal = all(
        c["status"] in ("CAPTURED", "TRANSCRIBED", "PURGED", "RETENTION_EXPIRED")
        for c in captures_of_encounter(encounter["id"])
    )
    if all_terminal:
        if encounter["audio_status"] != "NOT_RECORDING":
            encounter["audio_status"] = "NOT_RECORDING"


def supersede_existing_drafts(encounter, exclude_id=None):
    """Void any non-terminal drafts on the encounter (used when creating a new draft)."""
    for d in drafts_of_encounter(encounter["id"]):
        if exclude_id and d["id"] == exclude_id:
            continue
        if d["status"] in ("DRAFT", "EDITED", "IN_REVIEW", "AMENDED"):
            d["status"] = "VOID"
            touch(d)


def update_encounter_documentation_status(encounter):
    """If no non-terminal draft exists on the encounter, reset documentation_status
    to NOT_STARTED."""
    for d in drafts_of_encounter(encounter["id"]):
        if d["status"] not in ("VOID",):
            return
    if encounter["documentation_status"] != "NOT_STARTED":
        encounter["documentation_status"] = "NOT_STARTED"


def refresh_encounter_audio_status(encounter):
    """RECORDING_ACTIVE if any capture is RECORDING or PAUSED; AUDIO_STOPPED if any
    capture exists (and none active); NOT_RECORDING otherwise."""
    caps = captures_of_encounter(encounter["id"])
    if not caps:
        encounter["audio_status"] = "NOT_RECORDING"
        return
    if any(c["status"] in ("RECORDING", "PAUSED") for c in caps):
        encounter["audio_status"] = "RECORDING_ACTIVE"
        return
    encounter["audio_status"] = "AUDIO_STOPPED"
