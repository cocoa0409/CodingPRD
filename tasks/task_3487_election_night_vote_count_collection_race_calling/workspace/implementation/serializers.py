"""Entity serializers. Common fields per PRD §2.4: every resource has id +
created_at; events, counties, contests, stringers, assignments, reports,
calls, recounts, coverages and customers additionally carry updated_at +
version; links, candidates, feeds, deliveries and invoices do NOT."""
from util import fmt_dt
import services_rollup as rollup
import services_rules as rules


def _common(rec):
    return {"id": rec["id"], "created_at": fmt_dt(rec["created_at"])}


def _versioned(rec):
    out = _common(rec)
    out["updated_at"] = fmt_dt(rec["updated_at"])
    out["version"] = rec["version"]
    return out


def event_json(e):
    out = {
        "event_name": e["event_name"],
        "event_date": e["event_date"],
        "event_type": e["event_type"],
        "total_stringer_hour_budget": e["total_stringer_hour_budget"],
        "stringer_selection_mode": e["stringer_selection_mode"],
        "posture": e["posture"],
    }
    out.update(_versioned(e))
    return out


def county_json(c):
    reported, status = rollup.county_computed(c)
    out = {
        "event_id": c["event_id"],
        "county_fips": c["county_fips"],
        "county_name": c["county_name"],
        "state_code": c["state_code"],
        "expected_precincts": c["expected_precincts"],
        "expected_vote_total": c["expected_vote_total"],
        "survey_turnout_estimate": c["survey_turnout_estimate"],
        "historical_dem_share": c["historical_dem_share"],
        "reported_precincts": reported,
        "status": status,
    }
    out.update(_versioned(c))
    return out


def contest_json(c, refresh=True):
    if refresh:
        rollup.refresh_contest(c, bump=False)
    out = {
        "event_id": c["event_id"],
        "office_name": c["office_name"],
        "state_code": c["state_code"],
        "contest_type": c["contest_type"],
        "seats": c["seats"],
        "tabulation_status": c["tabulation_status"],
        "call_status": c["call_status"],
        "called_candidate_id": c["called_candidate_id"],
        "reported_precincts": c["reported_precincts"],
        "total_votes": c["total_votes"],
        "margin_pct": c["margin_pct"],
        "outstanding_estimate": c["outstanding_estimate"],
    }
    out.update(_versioned(c))
    return out


def link_json(l):
    out = {"contest_id": l["contest_id"], "county_id": l["county_id"]}
    out.update(_common(l))
    return out


def candidate_json(c):
    out = {
        "contest_id": c["contest_id"],
        "candidate_name": c["candidate_name"],
        "party": c["party"],
        "is_incumbent": c["is_incumbent"],
    }
    out.update(_common(c))
    return out


def feed_json(f):
    out = {
        "event_id": f["event_id"],
        "feed_name": f["feed_name"],
        "state_codes": list(f["state_codes"]),
        "priority_tier": f["priority_tier"],
    }
    out.update(_common(f))
    return out


def stringer_json(s):
    career, recent = rules.stringer_scores_for_read(s)
    out = {
        "stringer_name": s["stringer_name"],
        "home_state": s["home_state"],
        "no_show_count": s["no_show_count"],
        "accepted_report_count": s["accepted_report_count"],
        "voided_report_count": s["voided_report_count"],
        "reliability_career": career,
        "reliability_recent_form": recent,
    }
    out.update(_versioned(s))
    return out


def assignment_json(a):
    out = {
        "event_id": a["event_id"],
        "county_id": a["county_id"],
        "stringer_id": a["stringer_id"],
        "window_start": fmt_dt(a["window_start"]),
        "window_end": fmt_dt(a["window_end"]),
        "status": a["status"],
        "auto_selected": a["auto_selected"],
    }
    out.update(_versioned(a))
    return out


def report_json(r):
    out = {
        "contest_id": r["contest_id"],
        "county_id": r["county_id"],
        "source": r["source"],
        "submitted_by_stringer_id": r["submitted_by_stringer_id"],
        "precincts_reporting": r["precincts_reporting"],
        "candidate_votes": [
            {"candidate_id": e["candidate_id"], "votes": e["votes"]}
            for e in r["candidate_votes"]
        ],
        "reported_total": r["reported_total"],
        "deviation_ratio": r["deviation_ratio"],
        "swing_deviation": r["swing_deviation"],
        "status": r["status"],
        "accepted_at": fmt_dt(r["accepted_at"]) if r["accepted_at"] else None,
    }
    out.update(_versioned(r))
    return out


def call_json(c):
    out = {
        "contest_id": c["contest_id"],
        "winner_candidate_id": c["winner_candidate_id"],
        "proposed_by": c["proposed_by"],
        "published_by": c["published_by"],
        "status": c["status"],
        "published_at": fmt_dt(c["published_at"]) if c["published_at"] else None,
        "retract_reason": c["retract_reason"],
    }
    out.update(_versioned(c))
    return out


def recount_json(r):
    out = {
        "contest_id": r["contest_id"],
        "status": r["status"],
        "filed_margin_pct": r["filed_margin_pct"],
        "resolution_note": r["resolution_note"],
    }
    out.update(_versioned(r))
    return out


def coverage_json(c):
    out = {
        "event_id": c["event_id"],
        "contest_id": c["contest_id"],
        "allocated_stringer_hours": c["allocated_stringer_hours"],
        "coverage_start": c["coverage_start"],
        "coverage_end": c["coverage_end"],
        "rationale": c["rationale"],
        "status": c["status"],
    }
    out.update(_versioned(c))
    return out


def customer_json(c):
    out = {
        "customer_name": c["customer_name"],
        "license_tier": c["license_tier"],
        "licensed_states": list(c["licensed_states"]),
    }
    out.update(_versioned(c))
    return out


def delivery_json(d):
    out = {
        "customer_id": d["customer_id"],
        "contest_id": d["contest_id"],
        "content_type": d["content_type"],
        "fee_cents": d["fee_cents"],
        "status": d["status"],
        "delivered_at": fmt_dt(d["delivered_at"]),
    }
    out.update(_common(d))
    return out


def invoice_json(i):
    out = {
        "customer_id": i["customer_id"],
        "period": i["period"],
        "delivery_count": i["delivery_count"],
        "total_fee_cents": i["total_fee_cents"],
    }
    out.update(_common(i))
    return out
