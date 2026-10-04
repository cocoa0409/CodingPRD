"""Domain logic: serialization, recomputation, clock-driven transitions, cascades."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db import db
import calc
from util import iso_format, touch, new_id, iso_now_wall


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _money(value):
    """Revenue-share values may carry fractional cents (PRD §2.6: rounded to
    2 decimal places round-half-up, never truncated to integers). Emit an int
    when the rounded value is whole, else a float."""
    if not isinstance(value, Decimal):
        return value
    v = calc.round2(value)
    if v == v.to_integral_value():
        return int(v)
    return float(v)


PUBLIC_FIELD_ORDER = {
    "market": ["id", "market_name", "country_code", "screen_capacity_cap", "target_format_mix",
               "opened_screen_count", "status", "created_at", "updated_at", "version"],
    "agreement": ["id", "exhibitor_legal_name", "market_id", "agreement_type", "committed_screen_count",
                  "revenue_share_tier1_pct", "revenue_share_tier2_pct", "revenue_share_tier3_pct",
                  "annual_lease_fee_cents", "term_start_date", "term_end_date",
                  "total_slots_committed_count", "status", "created_at", "updated_at", "version"],
    "auditorium": ["id", "agreement_id", "auditorium_label", "screen_geometry", "seating_capacity",
                   "supported_formats", "sound_calibration_profile", "last_calibration_at",
                   "calibration_overdue", "current_week_admissions",
                   "quality_score_arithmetic", "quality_score_recency",
                   "status", "created_at", "updated_at", "version"],
    "studio": ["id", "studio_legal_name", "contact_email", "status", "created_at", "updated_at", "version"],
    "film": ["id", "studio_id", "title", "runtime_minutes", "worldwide_release_date", "format_targets",
             "status", "created_at", "updated_at", "version"],
    "conversion_order": ["id", "studio_film_id", "target_format",
                         "scheduled_post_start_date", "scheduled_post_end_date",
                         "filmmaker_approval_required", "filmmaker_signoff",
                         "delivered_master_url", "post_cost_estimate_cents",
                         "status", "created_at", "updated_at", "version"],
    "release_window": ["id", "window_label", "window_start_date", "window_end_date",
                       "total_premium_screen_seconds_pool", "committed_premium_screen_seconds",
                       "status", "created_at", "updated_at", "version"],
    "screen_slot": ["id", "window_id", "auditorium_id", "studio_film_id", "conversion_order_id",
                    "slot_start_date", "slot_end_date", "showings_per_day", "priority_tier",
                    "committed_screen_seconds", "weekly_gross_cents", "weekly_admissions",
                    "per_screen_attendance_ratio",
                    "status", "created_at", "updated_at", "version"],
    "box_office_report": ["id", "screen_slot_id", "reported_date", "gross_receipts_cents",
                          "admissions", "submission_channel", "status", "created_at"],
    "revenue_share_statement": ["id", "agreement_id", "window_id", "statement_lines",
                                "provisional_total_cents", "final_total_cents",
                                "status", "created_at", "updated_at", "version"],
    "qa_alert": ["id", "auditorium_id", "alert_code", "severity", "raised_at", "notes",
                 "status", "created_at", "updated_at", "version"],
    "tech_dispatch": ["id", "qa_alert_id", "auditorium_id", "scheduled_visit_date",
                      "tech_specialty", "resolution_notes",
                      "status", "created_at", "updated_at", "version"],
}


def _public(entity: dict, kind: str) -> dict:
    out = {}
    for k in PUBLIC_FIELD_ORDER[kind]:
        if k in entity:
            out[k] = entity[k]
    return out


def serialize_market(m):
    recompute_market_opened_screen_count(m)
    return _public(m, "market")


def serialize_agreement(a):
    recompute_agreement_total_slots(a)
    return _public(a, "agreement")


def serialize_auditorium(a):
    recompute_auditorium_derived(a)
    return _public(a, "auditorium")


def serialize_studio(s):
    return _public(s, "studio")


def serialize_film(f):
    return _public(f, "film")


def serialize_conversion_order(o):
    return _public(o, "conversion_order")


def serialize_release_window(w):
    return _public(w, "release_window")


def serialize_screen_slot(s):
    return _public(s, "screen_slot")


def serialize_box_office_report(r):
    return _public(r, "box_office_report")


def serialize_revenue_share_statement(s):
    recompute_statement(s)
    return _public(s, "revenue_share_statement")


def serialize_qa_alert(a):
    return _public(a, "qa_alert")


def serialize_tech_dispatch(d):
    return _public(d, "tech_dispatch")


# ---------------------------------------------------------------------------
# Derived recomputation
# ---------------------------------------------------------------------------

def recompute_market_opened_screen_count(market):
    count = 0
    for aud in db.auditoriums.values():
        if aud.get("status") != "OPERATING":
            continue
        agr = db.agreements.get(aud.get("agreement_id"))
        if agr and agr.get("market_id") == market["id"]:
            count += 1
    market["opened_screen_count"] = count


def recompute_agreement_total_slots(agreement):
    count = 0
    for aud in db.auditoriums.values():
        if aud.get("agreement_id") != agreement["id"]:
            continue
        for slot in db.screen_slots.values():
            if slot.get("auditorium_id") == aud["id"] and slot.get("status") in ("CONFIRMED", "HELD_OVER"):
                count += 1
    agreement["total_slots_committed_count"] = count


def recompute_auditorium_derived(aud):
    """Recompute calibration_overdue, current_week_admissions, quality scores."""
    clock = db.logical_clock
    last_cal = aud.get("_last_calibration_at_dt")
    if last_cal is None:
        aud["calibration_overdue"] = False
    else:
        aud["calibration_overdue"] = clock > last_cal + timedelta(days=90)
    # current week: ISO week Mon-Sun containing clock
    clock_day = clock.date()
    week_start = clock_day - timedelta(days=clock_day.weekday())
    week_end = week_start + timedelta(days=7)
    admissions = 0
    for slot in db.screen_slots.values():
        if slot.get("auditorium_id") != aud["id"]:
            continue
        for rpt in db.box_office_reports.values():
            if rpt.get("screen_slot_id") != slot["id"]:
                continue
            if rpt.get("status") != "VALIDATED":
                continue
            rd = rpt.get("_reported_date_dt")
            if rd is None:
                continue
            d = rd.date()
            if week_start <= d < week_end:
                admissions += rpt.get("admissions", 0)
    aud["current_week_admissions"] = admissions
    # Quality scores: alerts raised within trailing 30 days of clock
    cutoff = clock - timedelta(days=30)
    alerts = [a for a in db.qa_alerts.values()
              if a.get("auditorium_id") == aud["id"]
              and a.get("_raised_at_dt") is not None
              and a["_raised_at_dt"] >= cutoff and a["_raised_at_dt"] <= clock]
    score_a = calc.quality_score_arithmetic(alerts)
    score_b = calc.quality_score_recency(alerts, clock)
    aud["quality_score_arithmetic"] = float(calc.round4(score_a))
    aud["quality_score_recency"] = float(calc.round4(score_b))


def recompute_slot_derived(slot):
    """Recompute committed_screen_seconds and per_screen_attendance_ratio."""
    start = slot["_slot_start_dt"]
    end = slot["_slot_end_dt"]
    days = (end - start).days
    film = db.films.get(slot.get("studio_film_id"))
    runtime = film["runtime_minutes"] if film else 0
    slot["committed_screen_seconds"] = calc.committed_screen_seconds(
        days, slot.get("showings_per_day", 1), runtime)
    # per_screen_attendance_ratio
    aud = db.auditoriums.get(slot.get("auditorium_id"))
    clock = db.logical_clock
    today_midnight = clock.replace(hour=0, minute=0, second=0, microsecond=0)
    effective_end = min(today_midnight, end)
    days_elapsed = (effective_end - start).days
    if days_elapsed < 0:
        days_elapsed = 0
    if aud is None:
        ratio = Decimal("0")
    else:
        ratio = calc.per_screen_attendance_ratio(
            slot.get("weekly_admissions", 0), aud.get("seating_capacity", 0),
            slot.get("showings_per_day", 1), days_elapsed)
    slot["per_screen_attendance_ratio"] = float(calc.round4(ratio))


def recompute_window_committed(window):
    total = 0
    for slot in db.screen_slots.values():
        if slot.get("window_id") == window["id"] and slot.get("status") in ("CONFIRMED", "HELD_OVER"):
            total += slot.get("committed_screen_seconds", 0)
    window["committed_premium_screen_seconds"] = total


def _slot_statements(slot):
    out = []
    for st in db.revenue_share_statements.values():
        if st.get("window_id") == slot.get("window_id"):
            out.append(st)
    return out


def recompute_statements_for_slot(slot):
    for st in _slot_statements(slot):
        recompute_statement(st)


def recompute_statement(stmt):
    """Recompute statement_lines, provisional_total_cents, final_total_cents."""
    agreement = db.agreements.get(stmt.get("agreement_id"))
    window_id = stmt.get("window_id")
    if agreement and agreement.get("agreement_type") == "REVENUE_SHARE":
        t1 = agreement.get("revenue_share_tier1_pct") or 0
        t2 = agreement.get("revenue_share_tier2_pct") or 0
        t3 = agreement.get("revenue_share_tier3_pct") or 0
    else:
        t1 = t2 = t3 = 0

    # Preserve adjustments across recomputes: gather existing adjustments by slot
    existing_adjustments = {}
    for line in stmt.get("statement_lines", []) or []:
        sid = line.get("screen_slot_id")
        if sid and line.get("adjustments"):
            existing_adjustments[sid] = list(line["adjustments"])

    lines = []
    provisional_total = Decimal("0")
    final_total = Decimal("0")

    for slot in db.screen_slots.values():
        if slot.get("window_id") != window_id:
            continue
        if slot.get("status") not in ("CONFIRMED", "HELD_OVER", "PULLED", "SUSPENDED"):
            continue
        # Gather validated reports sorted by reported_date, then created_at
        reports = [r for r in db.box_office_reports.values()
                   if r.get("screen_slot_id") == slot["id"] and r.get("status") == "VALIDATED"]
        reports.sort(key=lambda r: (r.get("_reported_date_dt") or datetime.min.replace(tzinfo=timezone.utc),
                                    r.get("created_at", "")))
        validated_gross_sum = sum(r.get("gross_receipts_cents", 0) for r in reports)
        reported_days = len(reports)
        total_slot_days = (slot["_slot_end_dt"] - slot["_slot_start_dt"]).days
        unreported_days = total_slot_days - reported_days
        if unreported_days < 0:
            unreported_days = 0
        # Provisional share (per-line rounded)
        if reported_days > 0:
            mean_reported = Decimal(validated_gross_sum) / Decimal(reported_days)
            forecast = Decimal(unreported_days) * mean_reported * calc.FORECAST_DAILY_FRACTION
        else:
            forecast = Decimal("0")
        provisional_gross = Decimal(validated_gross_sum) + forecast
        line_prov_share = calc.round2(calc.tiered_marginal_share(provisional_gross, t1, t2, t3))

        # Final share: chronological per-day marginal with per-day rounding
        running = 0
        line_final = Decimal("0")
        for r in reports:
            day_share = calc.tiered_marginal_share_per_day(running, r.get("gross_receipts_cents", 0), t1, t2, t3)
            line_final += calc.round2(day_share)
            running += r.get("gross_receipts_cents", 0)

        adjustments = existing_adjustments.get(slot["id"], [])
        adj_sum = sum(a.get("adjustment_cents", 0) for a in adjustments)
        agreed_share = line_final + Decimal(adj_sum)
        gross_reported = running
        exhibitor_retained = Decimal(gross_reported) - agreed_share

        # Only slots in {CONFIRMED, HELD_OVER, PULLED} contribute a statement line
        # for the final calculation and for the statement_lines surface.
        if slot.get("status") in ("CONFIRMED", "HELD_OVER", "PULLED"):
            lines.append({
                "screen_slot_id": slot["id"],
                "gross_reported_cents": int(gross_reported),
                "exhibitor_retained_cents": _money(exhibitor_retained),
                "agreed_share_cents": _money(agreed_share),
                "day_count": reported_days,
                "adjustments": adjustments,
            })
            final_total += agreed_share

        # Provisional: include SUSPENDED too
        provisional_total += line_prov_share

    stmt["statement_lines"] = lines
    stmt["provisional_total_cents"] = _money(provisional_total)
    stmt["final_total_cents"] = _money(final_total)


# ---------------------------------------------------------------------------
# Clock-driven transitions
# ---------------------------------------------------------------------------

def fire_clock_transitions():
    """Fire automatic transitions based on db.logical_clock.

    Order: films (release date), films (out of window), agreements (expiry),
    windows (close at end date), then recompute calibration_overdue flags.
    """
    clock = db.logical_clock

    # StudioFilm ANNOUNCED -> IN_DISTRIBUTION when clock >= worldwide_release_date
    for film in db.films.values():
        if film.get("status") == "ANNOUNCED":
            wrd = film.get("_worldwide_release_date_dt")
            if wrd is not None and clock >= wrd:
                film["status"] = "IN_DISTRIBUTION"
                touch(film)

    # StudioFilm IN_DISTRIBUTION -> OUT_OF_WINDOW when clock >= release + 84 days
    for film in db.films.values():
        if film.get("status") == "IN_DISTRIBUTION":
            wrd = film.get("_worldwide_release_date_dt")
            if wrd is not None and clock >= wrd + timedelta(days=84):
                film["status"] = "OUT_OF_WINDOW"
                touch(film)
                # Cancel all non-terminal conversion orders for this film
                for co in db.conversion_orders.values():
                    if co.get("studio_film_id") == film["id"] and co.get("status") not in ("DELIVERED", "CANCELLED"):
                        co["status"] = "CANCELLED"
                        touch(co)

    # ExhibitorAgreement ACTIVE -> EXPIRED at term_end_date
    for agr in db.agreements.values():
        if agr.get("status") == "ACTIVE":
            ted = agr.get("_term_end_date_dt")
            if ted is not None and clock >= ted:
                agr["status"] = "EXPIRED"
                touch(agr)
                for aud in db.auditoriums.values():
                    if aud.get("agreement_id") != agr["id"]:
                        continue
                    for slot in db.screen_slots.values():
                        if slot.get("auditorium_id") == aud["id"] and slot.get("status") == "PROPOSED":
                            slot["status"] = "REJECTED"
                            touch(slot)

    # ReleaseWindow LOCKED -> CLOSED at window_end_date
    for win in db.release_windows.values():
        if win.get("status") == "LOCKED":
            wed = win.get("_window_end_date_dt")
            if wed is not None and clock >= wed:
                _close_window(win)


def _close_window(win):
    """LOCKED -> CLOSED: hold-over scoring, follow-on slot creation, statement issuance."""
    clock = db.logical_clock

    confirmed_slots = [s for s in db.screen_slots.values()
                       if s.get("window_id") == win["id"] and s.get("status") == "CONFIRMED"]

    # Snapshot of confirmed slots at start of evaluation (for uplift calc)
    confirmed_at_start = list(confirmed_slots)

    for slot in confirmed_slots:
        recompute_slot_derived(slot)
        ratio = Decimal(str(slot.get("per_screen_attendance_ratio", 0)))

        # format_premium_uplift based on slots CONFIRMED at start of evaluation
        same_film_count = sum(1 for s in confirmed_at_start
                              if s.get("studio_film_id") == slot.get("studio_film_id"))
        if same_film_count == 1:
            uplift = Decimal("0.10")
        elif same_film_count == 2:
            uplift = Decimal("0.05")
        else:
            uplift = Decimal("0.00")

        # week_over_week_growth: this week's gross vs same film's prior-week gross (prior windows)
        this_week_gross = slot.get("weekly_gross_cents", 0)
        prev_gross = 0
        for other in db.screen_slots.values():
            if other.get("window_id") == win["id"]:
                continue
            if other.get("studio_film_id") != slot.get("studio_film_id"):
                continue
            for rpt in db.box_office_reports.values():
                if rpt.get("screen_slot_id") == other["id"] and rpt.get("status") == "VALIDATED":
                    prev_gross += rpt.get("gross_receipts_cents", 0)
        denom = max(prev_gross, 1)
        growth = Decimal(this_week_gross - prev_gross) / Decimal(denom)

        score = calc.holdover_score(ratio, uplift, growth)
        # Hold-over fires iff score >= threshold (inclusive). Also the independent
        # per_screen_attendance_ratio check uses the same threshold.
        if score >= calc.HOLD_OVER_ADMISSION_THRESHOLD or ratio >= calc.HOLD_OVER_ADMISSION_THRESHOLD:
            slot["status"] = "HELD_OVER"
            touch(slot)
            # Auto-create follow-on slot in next window (chronological by window_start_date)
            next_windows = [w for w in db.release_windows.values()
                            if w.get("_window_start_date_dt") is not None
                            and w["_window_start_date_dt"] > win["_window_start_date_dt"]]
            next_windows.sort(key=lambda w: w["_window_start_date_dt"])
            if next_windows:
                nxt = next_windows[0]
                new_slot_start = nxt["_window_start_date_dt"]
                new_slot_end = new_slot_start + timedelta(days=7)
                now = iso_now_wall()
                follow = {
                    "id": new_id(),
                    "window_id": nxt["id"],
                    "auditorium_id": slot["auditorium_id"],
                    "studio_film_id": slot["studio_film_id"],
                    "conversion_order_id": slot["conversion_order_id"],
                    "slot_start_date": iso_format(new_slot_start),
                    "slot_end_date": iso_format(new_slot_end),
                    "_slot_start_dt": new_slot_start,
                    "_slot_end_dt": new_slot_end,
                    "showings_per_day": slot.get("showings_per_day", 1),
                    "priority_tier": slot.get("priority_tier", "STANDARD"),
                    "weekly_gross_cents": 0,
                    "weekly_admissions": 0,
                    "per_screen_attendance_ratio": 0,
                    "status": "PROPOSED",
                    "created_at": now,
                    "updated_at": now,
                    "version": 1,
                }
                recompute_slot_derived(follow)
                db.screen_slots[follow["id"]] = follow

    win["status"] = "CLOSED"
    touch(win)

    # Issue all DRAFT statements for this window
    for st in db.revenue_share_statements.values():
        if st.get("window_id") == win["id"] and st.get("status") == "DRAFT":
            recompute_statement(st)
            st["status"] = "ISSUED"
            touch(st)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def degrade_auditorium(aud):
    """OPERATING -> DEGRADED cascade (CRITICAL QAAlert creation)."""
    if aud.get("status") != "OPERATING":
        return
    aud["status"] = "DEGRADED"
    touch(aud)
    clock = db.logical_clock
    for slot in db.screen_slots.values():
        if slot.get("auditorium_id") != aud["id"]:
            continue
        if slot.get("status") != "CONFIRMED":
            continue
        if slot["_slot_start_dt"] <= clock < slot["_slot_end_dt"]:
            slot["status"] = "SUSPENDED"
            touch(slot)
            win = db.release_windows.get(slot.get("window_id"))
            if win is not None:
                recompute_window_committed(win)
                touch(win)
            recompute_statements_for_slot(slot)


def restore_auditorium(aud):
    """DEGRADED -> OPERATING: restore SUSPENDED slots."""
    for slot in db.screen_slots.values():
        if slot.get("auditorium_id") != aud["id"]:
            continue
        if slot.get("status") == "SUSPENDED":
            slot["status"] = "CONFIRMED"
            touch(slot)
            win = db.release_windows.get(slot.get("window_id"))
            if win is not None:
                recompute_window_committed(win)
                touch(win)
            recompute_statements_for_slot(slot)


def decommission_auditorium(aud):
    """Decommission cascade; aud already set to DECOMMISSIONED by caller."""
    was_operating = aud.pop("_was_operating_for_decommission", False)
    if was_operating:
        agr = db.agreements.get(aud.get("agreement_id"))
        if agr:
            market = db.markets.get(agr.get("market_id"))
            if market is not None:
                market["opened_screen_count"] = max(0, market.get("opened_screen_count", 0) - 1)
                touch(market)
    for slot in db.screen_slots.values():
        if slot.get("auditorium_id") != aud["id"]:
            continue
        if slot.get("status") == "PROPOSED":
            slot["status"] = "REJECTED"
            touch(slot)
        elif slot.get("status") == "CONFIRMED":
            slot["status"] = "PULLED"
            touch(slot)
            win = db.release_windows.get(slot.get("window_id"))
            if win is not None:
                recompute_window_committed(win)
                touch(win)
            recompute_statements_for_slot(slot)
        elif slot.get("status") == "SUSPENDED":
            slot["status"] = "PULLED"
            touch(slot)
            recompute_statements_for_slot(slot)


def terminate_agreement(agr, prior_status):
    """Cascade on agreement termination (SIGNED or ACTIVE)."""
    if prior_status in ("SIGNED", "ACTIVE"):
        for aud in db.auditoriums.values():
            if aud.get("agreement_id") != agr["id"]:
                continue
            if aud.get("status") == "DECOMMISSIONED":
                continue
            prev_aud_status = aud["status"]
            aud["status"] = "DECOMMISSIONED"
            touch(aud)
            if prev_aud_status == "OPERATING":
                market = db.markets.get(agr.get("market_id"))
                if market is not None:
                    market["opened_screen_count"] = max(0, market.get("opened_screen_count", 0) - 1)
                    touch(market)
            if prior_status == "ACTIVE":
                for slot in db.screen_slots.values():
                    if slot.get("auditorium_id") != aud["id"]:
                        continue
                    if slot.get("status") == "PROPOSED":
                        slot["status"] = "REJECTED"
                        touch(slot)
                    elif slot.get("status") == "CONFIRMED":
                        slot["status"] = "PULLED"
                        touch(slot)
                        win = db.release_windows.get(slot.get("window_id"))
                        if win is not None:
                            recompute_window_committed(win)
                            touch(win)
                        recompute_statements_for_slot(slot)


def cancel_conversion_order_cascade(order):
    """APPROVED_FOR_RELEASE -> CANCELLED: reject PROPOSED slots referencing it."""
    for slot in db.screen_slots.values():
        if slot.get("conversion_order_id") == order["id"] and slot.get("status") == "PROPOSED":
            slot["status"] = "REJECTED"
            touch(slot)
