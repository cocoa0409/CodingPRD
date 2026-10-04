"""Business logic: serializers, cascades, and calculations."""

import itertools
from decimal import Decimal, ROUND_HALF_UP

from db import db
from helpers import new_common, now_ts, touch, parse_dt
import errors

_creation_seq = itertools.count(1)

MAX_ALBUM_UNITS_PER_BUYER_PER_WEEK = 4
PRICE_FLOOR_CENTS = 300

POINTS_QUANT = Decimal("0.0001")


def new_entity():
    """Common fields plus a monotonic creation sequence (internal, never serialized)."""
    base = new_common()
    base["_seq"] = next(_creation_seq)
    return base

FEED_KIND_COMPONENTS = {
    "SALES": {"SALES"},
    "STREAM_ON_DEMAND": {"STREAM_ON_DEMAND_PAID", "STREAM_ON_DEMAND_AD"},
    "STREAM_PROGRAMMED": {"STREAM_PROGRAMMED"},
    "AIRPLAY": {"AIRPLAY"},
}

COUNTABLE_CHANNELS = {"D2C", "RETAIL"}
BUNDLE_CHANNELS = {"TICKET_BUNDLE", "MERCH_BUNDLE"}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_chart(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "chart_code": c["chart_code"],
        "title": c["title"],
        "chart_kind": c["chart_kind"],
        "chart_scope": c["chart_scope"],
        "genre_tag": c["genre_tag"],
        "current_methodology_version_id": c["current_methodology_version_id"],
        "recurrent_rule_id": c["recurrent_rule_id"],
    }


def ser_methodology(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "chart_id": m["chart_id"],
        "version_label": m["version_label"],
        "w_sales": m["w_sales"],
        "w_on_demand": m["w_on_demand"],
        "w_programmed": m["w_programmed"],
        "w_airplay": m["w_airplay"],
        "paid_stream_divisor": m["paid_stream_divisor"],
        "ad_stream_divisor": m["ad_stream_divisor"],
        "prog_stream_divisor": m["prog_stream_divisor"],
        "tea_rate": m["tea_rate"],
        "effective_from": m["effective_from"],
        "status": m["status"],
    }


def ser_week(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
        "chart_id": w["chart_id"],
        "week_index": w["week_index"],
        "opens_at": w["opens_at"],
        "closes_at": w["closes_at"],
        "reporting_cutoff": w["reporting_cutoff"],
        "status": w["status"],
        "computed_methodology_version_id": w["computed_methodology_version_id"],
        "holiday_adjusted": w["holiday_adjusted"],
    }


def ser_provider(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "provider_code": p["provider_code"],
        "display_name": p["display_name"],
        "feed_kind": p["feed_kind"],
        "territory": p["territory"],
        "status": p["status"],
    }


def ser_title(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "upc": t["upc"],
        "title": t["title"],
        "artist_name": t["artist_name"],
        "product_kind": t["product_kind"],
        "genre_tag": t["genre_tag"],
        "release_date": t["release_date"],
        "base_price_cents": t["base_price_cents"],
        "label_account_id": t["label_account_id"],
        "availability_policy": t["availability_policy"],
        "eligibility_posture": t["eligibility_posture"],
    }


def ser_label(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "legal_name": l["legal_name"],
        "account_code": l["account_code"],
        "strike_count": l["strike_count"],
        "account_status": l["account_status"],
    }


def ser_rule(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "rule_code": r["rule_code"],
        "max_weeks": r["max_weeks"],
        "min_rank": r["min_rank"],
        "reentry_min_rank": r["reentry_min_rank"],
        "description": r["description"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "provider_id": r["provider_id"],
        "title_product_id": r["title_product_id"],
        "chart_week_id": r["chart_week_id"],
        "component_kind": r["component_kind"],
        "quantity": r["quantity"],
        "event_time": r["event_time"],
        "file_fingerprint": r["file_fingerprint"],
        "status": r["status"],
        "review_reason": r["review_reason"],
    }


def ser_batch(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "title_product_id": b["title_product_id"],
        "channel": b["channel"],
        "quantity": b["quantity"],
        "buyer_key": b["buyer_key"],
        "chart_week_id": b["chart_week_id"],
        "countable_units": b["countable_units"],
        "review_status": b["review_status"],
    }


def ser_signal(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "title_product_id": s["title_product_id"],
        "chart_week_id": s["chart_week_id"],
        "signal_kind": s["signal_kind"],
        "evidence": s["evidence"],
        "status": s["status"],
    }


def ser_investigation(i):
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "signal_id": i["signal_id"],
        "assigned_to": i["assigned_to"],
        "finding": i["finding"],
        "notes": i["notes"],
        "status": i["status"],
    }


def ser_entry(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "chart_week_id": e["chart_week_id"],
        "title_product_id": e["title_product_id"],
        "points": e["points"],
        "rank": e["rank"],
        "weeks_on_chart": e["weeks_on_chart"],
        "peak_rank": e["peak_rank"],
        "entry_status": e["entry_status"],
    }


def ser_dispute(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "title_product_id": d["title_product_id"],
        "chart_id": d["chart_id"],
        "filed_by_label_id": d["filed_by_label_id"],
        "claimed_genre": d["claimed_genre"],
        "resolution": d["resolution"],
        "status": d["status"],
        "reentries_processed": d["reentries_processed"],
    }


def ser_freeze(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "chart_id": f["chart_id"],
        "reason": f["reason"],
        "expected_chart_version": f["expected_chart_version"],
        "resolved_by_methodology_version_id": f["resolved_by_methodology_version_id"],
        "status": f["status"],
    }


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_chart(cid):
    c = db.charts.get(cid)
    if c is None:
        raise errors.not_found("Chart not found")
    return c


def get_methodology(mid):
    m = db.methodology_versions.get(mid)
    if m is None:
        raise errors.not_found("MethodologyVersion not found")
    return m


def get_week(wid):
    w = db.chart_weeks.get(wid)
    if w is None:
        raise errors.not_found("ChartWeek not found")
    return w


def get_provider(pid):
    p = db.providers.get(pid)
    if p is None:
        raise errors.not_found("Provider not found")
    return p


def get_title(tid):
    t = db.title_products.get(tid)
    if t is None:
        raise errors.not_found("TitleProduct not found")
    return t


def get_label(lid):
    l = db.label_accounts.get(lid)
    if l is None:
        raise errors.not_found("LabelAccount not found")
    return l


def get_rule(rid):
    r = db.recurrent_rules.get(rid)
    if r is None:
        raise errors.not_found("RecurrentRule not found")
    return r


def get_report(rid):
    r = db.consumption_reports.get(rid)
    if r is None:
        raise errors.not_found("ConsumptionReport not found")
    return r


def get_signal(sid):
    s = db.manipulation_signals.get(sid)
    if s is None:
        raise errors.not_found("ManipulationSignal not found")
    return s


def get_investigation(iid):
    i = db.investigations.get(iid)
    if i is None:
        raise errors.not_found("Investigation not found")
    return i


def get_dispute(did):
    d = db.genre_disputes.get(did)
    if d is None:
        raise errors.not_found("GenreDispute not found")
    return d


def get_freeze(fid):
    f = db.chart_freezes.get(fid)
    if f is None:
        raise errors.not_found("ChartFreeze not found")
    return f


def chart_has_active_freeze(chart_id):
    return any(
        f["chart_id"] == chart_id and f["status"] == "ACTIVE"
        for f in db.chart_freezes.values()
    )


def require_no_active_freeze(chart_id):
    if chart_has_active_freeze(chart_id):
        raise errors.chart_frozen()


def check_occ(chart, payload):
    """OCC: expected_chart_version is required; must equal chart.version."""
    expected = payload.get("expected_chart_version")
    if expected is None:
        raise errors.stale_version("expected_chart_version is required")
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        raise errors.stale_version("expected_chart_version must be an integer")
    if expected != chart["version"]:
        raise errors.stale_version()


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def invalidate_computed_weeks(chart_id):
    """COMPUTED weeks of the chart go back to LOCKED; entries reset."""
    for w in db.chart_weeks.values():
        if w["chart_id"] == chart_id and w["status"] == "COMPUTED":
            w["status"] = "LOCKED"
            w["computed_methodology_version_id"] = None
            touch(w)
            for e in db.chart_entries.values():
                if e["chart_week_id"] == w["id"]:
                    e["points"] = 0
                    e["rank"] = None
                    touch(e)


def supersede_prior_active(chart_id):
    """Prior ACTIVE methodology of chart transitions to SUPERSEDED."""
    for m in db.methodology_versions.values():
        if m["chart_id"] == chart_id and m["status"] == "ACTIVE":
            m["status"] = "SUPERSEDED"
            touch(m)


def activate_methodology(chart, methodology):
    """Shared cascade for activation (DRAFT->ACTIVE or FROZEN->ACTIVE)."""
    supersede_prior_active(chart["id"])
    methodology["status"] = "ACTIVE"
    touch(methodology)
    chart["current_methodology_version_id"] = methodology["id"]
    touch(chart)
    invalidate_computed_weeks(chart["id"])


# ---------------------------------------------------------------------------
# Sale batch allocation
# ---------------------------------------------------------------------------

def allocate_buyer_group(buyer_key, title_id, week_id):
    """Re-run per-buyer cap allocation for one (buyer_key, title, week) group."""
    eligible = [
        b
        for b in db.sale_batches.values()
        if b["buyer_key"] == buyer_key
        and b["title_product_id"] == title_id
        and b["chart_week_id"] == week_id
        and b["review_status"] == "CLEARED"
        and b["channel"] in COUNTABLE_CHANNELS
    ]
    # created_at ASC, tie-break quantity ASC
    eligible.sort(key=lambda b: (b["created_at"], b["_seq"], b["quantity"]))
    headroom = MAX_ALBUM_UNITS_PER_BUYER_PER_WEEK
    for b in eligible:
        alloc = min(b["quantity"], headroom)
        if b["countable_units"] != alloc:
            b["countable_units"] = alloc
            touch(b)
        headroom -= alloc


# ---------------------------------------------------------------------------
# Points calculation
# ---------------------------------------------------------------------------

def accepted_reports_for(title_id, week_id):
    return [
        r
        for r in db.consumption_reports.values()
        if r["title_product_id"] == title_id
        and r["chart_week_id"] == week_id
        and r["status"] == "ACCEPTED"
    ]


def compute_points(chart, title, week, methodology):
    reports = [
        r
        for r in accepted_reports_for(title["id"], week["id"])
        if db.providers[r["provider_id"]]["territory"] == "DOMESTIC"
    ]

    def qty(kind):
        return sum(r["quantity"] for r in reports if r["component_kind"] == kind)

    sea_paid = qty("STREAM_ON_DEMAND_PAID") // methodology["paid_stream_divisor"]
    sea_ad = qty("STREAM_ON_DEMAND_AD") // methodology["ad_stream_divisor"]
    sea_prog = qty("STREAM_PROGRAMMED") // methodology["prog_stream_divisor"]
    airplay = qty("AIRPLAY")

    batch_units = sum(
        b["countable_units"]
        for b in db.sale_batches.values()
        if b["title_product_id"] == title["id"]
        and b["chart_week_id"] == week["id"]
        and b["review_status"] == "CLEARED"
    )
    sales_units = batch_units + qty("SALES")

    w_sales = Decimal(str(methodology["w_sales"]))
    w_on_demand = Decimal(str(methodology["w_on_demand"]))
    w_programmed = Decimal(str(methodology["w_programmed"]))
    w_airplay = Decimal(str(methodology["w_airplay"]))

    if chart["chart_kind"] == "ALBUMS" and title["product_kind"] == "ALBUM":
        tea_units = sea_paid // methodology["tea_rate"]
        points = (
            w_sales * sales_units
            + w_on_demand * tea_units
            + w_programmed * sea_prog
            + w_airplay * airplay
        )
    else:
        points = (
            w_sales * sales_units
            + w_on_demand * (sea_paid + sea_ad)
            + w_programmed * sea_prog
            + w_airplay * airplay
        )

    points = points.quantize(POINTS_QUANT, rounding=ROUND_HALF_UP)
    return float(points)


# ---------------------------------------------------------------------------
# Title eligibility at compute
# ---------------------------------------------------------------------------

def title_eligible_for(chart, title, week, first_entry):
    """Returns True when the title can receive an entry on this week."""
    if title["eligibility_posture"] != "ELIGIBLE":
        return False
    if title["base_price_cents"] < PRICE_FLOOR_CENTS:
        return False
    opens_at = parse_dt(week["opens_at"])
    if first_entry and opens_at < parse_dt(title["release_date"]):
        return False
    policy = title.get("availability_policy") or {}
    af = policy.get("available_from")
    au = policy.get("available_until")
    if af is not None and parse_dt(af) > opens_at:
        return False
    if au is not None and not (opens_at < parse_dt(au)):
        return False
    # chart kind admission
    if chart["chart_kind"] == "ALBUMS" and title["product_kind"] != "ALBUM":
        return False
    if chart["chart_kind"] == "SINGLES" and title["product_kind"] != "TRACK":
        return False
    # genre admission
    if chart["chart_scope"] == "GENRE" and title["genre_tag"] != chart["genre_tag"]:
        return False
    return True


def title_has_prior_entry(chart_id, title_id):
    return any(
        db.chart_weeks[e["chart_week_id"]]["chart_id"] == chart_id
        for e in db.chart_entries.values()
        if e["title_product_id"] == title_id
    )


# ---------------------------------------------------------------------------
# weeks_on_chart / peak_rank helpers
# ---------------------------------------------------------------------------

def prior_published_count(chart_id, title_id, week_index):
    """Count published entries for (chart, title) with week_index < given,
    whose publish-time entry_status was not RECURRENT_REMOVED."""
    count = 0
    for e in db.chart_entries.values():
        if e["title_product_id"] != title_id:
            continue
        w = db.chart_weeks[e["chart_week_id"]]
        if w["chart_id"] != chart_id:
            continue
        if w["status"] != "PUBLISHED":
            continue
        if w["week_index"] >= week_index:
            continue
        if e.get("publish_status") == "RECURRENT_REMOVED":
            continue
        count += 1
    return count


def published_ranks(chart_id, title_id):
    """Ranks across published entries of (chart, title)."""
    ranks = []
    for e in db.chart_entries.values():
        if e["title_product_id"] != title_id:
            continue
        w = db.chart_weeks[e["chart_week_id"]]
        if w["chart_id"] != chart_id:
            continue
        if w["status"] != "PUBLISHED":
            continue
        if e["rank"] is not None:
            ranks.append(e["rank"])
    return ranks
