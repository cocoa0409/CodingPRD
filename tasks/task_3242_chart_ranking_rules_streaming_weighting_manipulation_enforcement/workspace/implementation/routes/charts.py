"""Chart, methodology version, chart week, freeze, and clock routes."""

from flask import Blueprint

import errors
from db import db
from helpers import (
    auth_context,
    clock_now,
    clock_set,
    envelope_ok,
    get_json,
    iso3,
    new_id,
    now_ts,
    paginate,
    pagination_params,
    parse_dt,
    require_roles,
    touch,
)
from services import (
    activate_methodology,
    chart_has_active_freeze,
    check_occ,
    compute_points,
    get_chart,
    get_freeze,
    get_methodology,
    get_rule,
    get_week,
    invalidate_computed_weeks,
    new_entity,
    require_no_active_freeze,
    ser_chart,
    ser_entry,
    ser_freeze,
    ser_methodology,
    ser_week,
    title_eligible_for,
    title_has_prior_entry,
    prior_published_count,
    published_ranks,
)

bp = Blueprint("charts", __name__)

ALL_ROLES = ("PlatformAdmin", "ChartManager", "ChartOps", "DataProvider", "LabelRep", "Investigator")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    payload = get_json()
    to_iso = payload.get("to_iso8601")
    dt = parse_dt(to_iso)
    clock_set(dt)
    return envelope_ok({}, response_type="object", status=200)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

@bp.route("/charts", methods=["POST"])
def create_chart():
    require_roles("ChartManager")
    payload = get_json()

    chart_code = payload.get("chart_code")
    title = payload.get("title")
    chart_kind = payload.get("chart_kind")
    chart_scope = payload.get("chart_scope")
    genre_tag = payload.get("genre_tag")
    rule_id = payload.get("recurrent_rule_id")

    # existence: recurrent rule must resolve
    rule = db.recurrent_rules.get(rule_id)
    if rule is None:
        raise errors.not_found("RecurrentRule not found")

    # uniqueness of chart_code
    for c in db.charts.values():
        if c["chart_code"] == chart_code:
            raise errors.ApiError("ERR_VALIDATION", "chart_code must be unique", 422)

    # scope vs genre_tag
    if chart_scope == "GENRE" and not genre_tag:
        raise errors.ApiError("ERR_VALIDATION", "genre_tag required for GENRE chart", 422)
    if chart_scope == "MAIN" and genre_tag is not None:
        raise errors.ApiError("ERR_VALIDATION", "genre_tag forbidden for MAIN chart", 422)

    chart = new_entity()
    chart.update(
        chart_code=chart_code,
        title=title,
        chart_kind=chart_kind,
        chart_scope=chart_scope,
        genre_tag=genre_tag,
        current_methodology_version_id=None,
        recurrent_rule_id=rule_id,
    )
    db.charts[chart["id"]] = chart
    return envelope_ok(ser_chart(chart), response_type="object", status=201)


@bp.route("/charts", methods=["GET"])
def list_charts():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    filter_mv = None
    from flask import request
    filter_mv = request.args.get("current_methodology_version_id")
    items = sorted(db.charts.values(), key=lambda c: (c["created_at"], c["_seq"]))
    if filter_mv is not None:
        items = [c for c in items if c["current_methodology_version_id"] == filter_mv]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_chart(c) for c in page], response_type="array", pagination=page_meta)


@bp.route("/charts/<cid>", methods=["GET"])
def get_chart_route(cid):
    require_roles(*ALL_ROLES)
    chart = get_chart(cid)
    return envelope_ok(ser_chart(chart), response_type="object")


# ---------------------------------------------------------------------------
# Methodology versions
# ---------------------------------------------------------------------------

@bp.route("/charts/<cid>/methodology-versions", methods=["POST"])
def create_methodology(cid):
    require_roles("ChartManager")
    chart = get_chart(cid)
    payload = get_json()

    effective_from = payload.get("effective_from")
    if effective_from is not None:
        # validate parseable; store normalized
        effective_from = iso3(parse_dt(effective_from))

    m = new_entity()
    m.update(
        chart_id=chart["id"],
        version_label=payload.get("version_label"),
        w_sales=payload.get("w_sales"),
        w_on_demand=payload.get("w_on_demand"),
        w_programmed=payload.get("w_programmed"),
        w_airplay=payload.get("w_airplay"),
        paid_stream_divisor=payload.get("paid_stream_divisor"),
        ad_stream_divisor=payload.get("ad_stream_divisor"),
        prog_stream_divisor=payload.get("prog_stream_divisor"),
        tea_rate=payload.get("tea_rate"),
        effective_from=effective_from,
        status="DRAFT",
    )
    db.methodology_versions[m["id"]] = m
    return envelope_ok(ser_methodology(m), response_type="object", status=201)


@bp.route("/charts/<cid>/methodology-versions", methods=["GET"])
def list_methodologies(cid):
    require_roles(*ALL_ROLES)
    chart = get_chart(cid)
    limit, offset = pagination_params()
    items = sorted(
        [m for m in db.methodology_versions.values() if m["chart_id"] == chart["id"]],
        key=lambda m: (m["created_at"], m["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_methodology(m) for m in page], response_type="array", pagination=page_meta)


@bp.route("/charts/<cid>/methodology-versions/<mid>/activate", methods=["POST"])
def activate_methodology_route(cid, mid):
    require_roles("ChartManager")
    chart = get_chart(cid)
    m = db.methodology_versions.get(mid)
    if m is None or m["chart_id"] != chart["id"]:
        raise errors.not_found("MethodologyVersion not found")

    payload = get_json()
    # OCC
    check_occ(chart, payload)
    # freeze gate
    require_no_active_freeze(chart["id"])
    # state: DRAFT -> ACTIVE only via this endpoint (FROZEN handled via freeze resolve)
    if m["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT methodology version can be activated")
    if m["effective_from"] is None:
        raise errors.invalid_state("effective_from must be set before activation")

    activate_methodology(chart, m)
    return envelope_ok(ser_methodology(m), response_type="object", status=200)


# ---------------------------------------------------------------------------
# Freeze lifecycle
# ---------------------------------------------------------------------------

@bp.route("/charts/<cid>/freeze", methods=["POST"])
def freeze_chart(cid):
    require_roles("ChartManager")
    chart = get_chart(cid)
    payload = get_json()
    check_occ(chart, payload)

    reason = payload.get("reason")

    # move all methodology versions (DRAFT or ACTIVE) to FROZEN
    for m in db.methodology_versions.values():
        if m["chart_id"] == chart["id"] and m["status"] in ("DRAFT", "ACTIVE"):
            m["status"] = "FROZEN"
            touch(m)

    freeze = new_entity()
    freeze.update(
        chart_id=chart["id"],
        reason=reason,
        expected_chart_version=payload.get("expected_chart_version"),
        resolved_by_methodology_version_id=None,
        status="ACTIVE",
    )
    db.chart_freezes[freeze["id"]] = freeze
    touch(chart)
    return envelope_ok(ser_freeze(freeze), response_type="object", status=201)


@bp.route("/charts/<cid>/freeze/<fid>/resolve", methods=["POST"])
def resolve_freeze(cid, fid):
    require_roles("ChartManager")
    chart = get_chart(cid)
    freeze = db.chart_freezes.get(fid)
    if freeze is None or freeze["chart_id"] != chart["id"]:
        raise errors.not_found("ChartFreeze not found")

    if freeze["status"] != "ACTIVE":
        raise errors.invalid_state("Freeze is not ACTIVE")

    payload = get_json()
    mv_id = payload.get("resolved_by_methodology_version_id")
    m = db.methodology_versions.get(mv_id)
    if m is None or m["chart_id"] != chart["id"]:
        raise errors.not_found("MethodologyVersion not found")
    if m["status"] != "FROZEN":
        raise errors.invalid_state("Named methodology version must be FROZEN")

    # all other versions -> SUPERSEDED
    for other in db.methodology_versions.values():
        if other["chart_id"] == chart["id"] and other["id"] != m["id"] and other["status"] == "FROZEN":
            other["status"] = "SUPERSEDED"
            touch(other)

    m["status"] = "ACTIVE"
    touch(m)
    chart["current_methodology_version_id"] = m["id"]
    touch(chart)
    invalidate_computed_weeks(chart["id"])

    freeze["status"] = "RESOLVED"
    freeze["resolved_by_methodology_version_id"] = m["id"]
    touch(freeze)
    return envelope_ok(ser_freeze(freeze), response_type="object", status=200)


@bp.route("/charts/<cid>/freezes", methods=["GET"])
def list_freezes(cid):
    require_roles("PlatformAdmin", "ChartManager", "ChartOps", "Investigator")
    chart = get_chart(cid)
    limit, offset = pagination_params()
    from flask import request
    status_filter = request.args.get("status")
    items = sorted(
        [f for f in db.chart_freezes.values() if f["chart_id"] == chart["id"]],
        key=lambda f: (f["created_at"], f["_seq"]),
    )
    if status_filter:
        items = [f for f in items if f["status"] == status_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_freeze(f) for f in page], response_type="array", pagination=page_meta)


# ---------------------------------------------------------------------------
# Chart weeks
# ---------------------------------------------------------------------------

@bp.route("/charts/<cid>/weeks", methods=["POST"])
def create_week(cid):
    require_roles("ChartManager")
    chart = get_chart(cid)
    payload = get_json()

    week_index = payload.get("week_index")
    opens_at_s = payload.get("opens_at")
    closes_at_s = payload.get("closes_at")
    reporting_cutoff_s = payload.get("reporting_cutoff")

    opens_at = parse_dt(opens_at_s)
    closes_at = parse_dt(closes_at_s)
    reporting_cutoff = parse_dt(reporting_cutoff_s) if reporting_cutoff_s else closes_at

    # overlap check: half-open intervals of same chart
    for w in db.chart_weeks.values():
        if w["chart_id"] != chart["id"]:
            continue
        existing_open = parse_dt(w["opens_at"])
        existing_close = parse_dt(w["closes_at"])
        # strict overlap iff opens_at < existing_close AND existing_open < closes_at
        if opens_at < existing_close and existing_open < closes_at:
            raise errors.week_window_overlap()

    # uniqueness of week_index within chart
    for w in db.chart_weeks.values():
        if w["chart_id"] == chart["id"] and w["week_index"] == week_index:
            raise errors.ApiError("ERR_VALIDATION", "week_index must be unique per chart", 422)

    week = new_entity()
    week.update(
        chart_id=chart["id"],
        week_index=week_index,
        opens_at=iso3(opens_at),
        closes_at=iso3(closes_at),
        reporting_cutoff=iso3(reporting_cutoff),
        status="OPEN",
        computed_methodology_version_id=None,
        holiday_adjusted=False,
    )
    db.chart_weeks[week["id"]] = week
    return envelope_ok(ser_week(week), response_type="object", status=201)


@bp.route("/charts/<cid>/weeks", methods=["GET"])
def list_weeks(cid):
    require_roles(*ALL_ROLES)
    chart = get_chart(cid)
    limit, offset = pagination_params()
    items = sorted(
        [w for w in db.chart_weeks.values() if w["chart_id"] == chart["id"]],
        key=lambda w: (w["created_at"], w["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_week(w) for w in page], response_type="array", pagination=page_meta)


@bp.route("/chart-weeks/<wid>", methods=["GET"])
def get_week_route(wid):
    require_roles(*ALL_ROLES)
    week = get_week(wid)
    return envelope_ok(ser_week(week), response_type="object")


@bp.route("/chart-weeks/<wid>/lock", methods=["POST"])
def lock_week(wid):
    require_roles("ChartManager")
    week = get_week(wid)
    chart = get_chart(week["chart_id"])

    require_no_active_freeze(chart["id"])
    if week["status"] != "OPEN":
        raise errors.invalid_state("Week is not OPEN")
    if clock_now() < parse_dt(week["closes_at"]):
        raise errors.week_not_closed()

    # reject RECEIVED reports
    for r in db.consumption_reports.values():
        if r["chart_week_id"] == week["id"] and r["status"] == "RECEIVED":
            r["status"] = "REJECTED"
            r["review_reason"] = "late-arriving at lock"
            touch(r)

    week["status"] = "LOCKED"
    touch(week)
    return envelope_ok(ser_week(week), response_type="object", status=200)


@bp.route("/chart-weeks/<wid>/compute", methods=["POST"])
def compute_week(wid):
    require_roles("ChartManager")
    week = get_week(wid)
    chart = get_chart(week["chart_id"])

    require_no_active_freeze(chart["id"])
    if week["status"] != "LOCKED":
        raise errors.invalid_state("Week must be LOCKED to compute")

    mv_id = chart["current_methodology_version_id"]
    if mv_id is None:
        raise errors.no_active_methodology()
    m = db.methodology_versions.get(mv_id)
    if m is None or m["status"] != "ACTIVE":
        raise errors.no_active_methodology()
    if m["effective_from"] is None or parse_dt(m["effective_from"]) > parse_dt(week["opens_at"]):
        raise errors.no_active_methodology()

    week["computed_methodology_version_id"] = m["id"]

    # build or refresh entries for eligible titles
    existing_by_title = {
        e["title_product_id"]: e
        for e in db.chart_entries.values()
        if e["chart_week_id"] == week["id"]
    }

    for title in list(db.title_products.values()):
        first_entry = not title_has_prior_entry(chart["id"], title["id"])
        if not title_eligible_for(chart, title, week, first_entry):
            continue
        points = compute_points(chart, title, week, m)
        existing = existing_by_title.get(title["id"])
        if existing is not None:
            existing["points"] = points
            existing["rank"] = None
            touch(existing)
        else:
            entry = new_entity()
            entry.update(
                chart_week_id=week["id"],
                title_product_id=title["id"],
                points=points,
                rank=None,
                weeks_on_chart=0,
                peak_rank=None,
                entry_status="ACTIVE",
            )
            db.chart_entries[entry["id"]] = entry

    # provisional weeks_on_chart (excludes current week)
    for e in db.chart_entries.values():
        if e["chart_week_id"] != week["id"]:
            continue
        e["weeks_on_chart"] = prior_published_count(chart["id"], e["title_product_id"], week["week_index"])

    week["status"] = "COMPUTED"
    touch(week)

    entries = sorted(
        [e for e in db.chart_entries.values() if e["chart_week_id"] == week["id"]],
        key=lambda e: (e["created_at"], e["_seq"]),
    )
    return envelope_ok([ser_entry(e) for e in entries], response_type="array", status=200)


@bp.route("/chart-weeks/<wid>/publish", methods=["POST"])
def publish_week(wid):
    require_roles("ChartManager")
    week = get_week(wid)
    chart = get_chart(week["chart_id"])

    require_no_active_freeze(chart["id"])
    if week["status"] != "COMPUTED":
        raise errors.invalid_state("Week must be COMPUTED to publish")
    if week["computed_methodology_version_id"] != chart["current_methodology_version_id"]:
        raise errors.invalid_state("Computed methodology no longer matches current methodology")

    # reject if any entry's title is DISQUALIFIED
    week_entries = [e for e in db.chart_entries.values() if e["chart_week_id"] == week["id"]]
    for e in week_entries:
        t = db.title_products.get(e["title_product_id"])
        if t is not None and t["eligibility_posture"] == "DISQUALIFIED":
            raise errors.title_disqualified()

    # rank assignment: points DESC, tie-break title created_at ASC
    def title_key(e):
        t = db.title_products[e["title_product_id"]]
        return (t["created_at"], t["_seq"])

    ordered = sorted(week_entries, key=lambda e: (-e["points"], title_key(e)))
    for i, e in enumerate(ordered, start=1):
        e["rank"] = i

    # weeks_on_chart and peak_rank
    for e in ordered:
        prior = prior_published_count(chart["id"], e["title_product_id"], week["week_index"])
        e["weeks_on_chart"] = prior + 1
        ranks = published_ranks(chart["id"], e["title_product_id"])
        ranks.append(e["rank"])
        e["peak_rank"] = min(ranks)
        # record publish-time status for later weeks_on_chart counting
        e["publish_status"] = e["entry_status"]
        touch(e)

    # recurrent sweep
    rule = get_rule(chart["recurrent_rule_id"])
    for e in ordered:
        if (
            e["entry_status"] == "ACTIVE"
            and e["weeks_on_chart"] >= rule["max_weeks"]
            and e["rank"] > rule["min_rank"]
        ):
            e["entry_status"] = "RECURRENT_REMOVED"
            e["publish_status"] = "RECURRENT_REMOVED"
            touch(e)

    week["status"] = "PUBLISHED"
    touch(week)

    return envelope_ok([ser_entry(e) for e in ordered], response_type="array", status=200)


@bp.route("/chart-weeks/<wid>/holiday-adjust", methods=["POST"])
def holiday_adjust(wid):
    require_roles("ChartManager")
    week = get_week(wid)
    payload = get_json()

    if week["status"] != "OPEN":
        raise errors.holiday_window_invalid("Week is not OPEN")

    new_cutoff_s = payload.get("new_reporting_cutoff")
    new_cutoff = parse_dt(new_cutoff_s)
    current_cutoff = parse_dt(week["reporting_cutoff"])
    opens_at = parse_dt(week["opens_at"])

    if not (new_cutoff < current_cutoff and new_cutoff >= opens_at):
        raise errors.holiday_window_invalid()

    week["reporting_cutoff"] = iso3(new_cutoff)
    week["holiday_adjusted"] = True

    # reject affected reports
    for r in db.consumption_reports.values():
        if r["chart_week_id"] != week["id"]:
            continue
        if r["status"] not in ("RECEIVED", "ACCEPTED"):
            continue
        if parse_dt(r["event_time"]) >= new_cutoff:
            r["status"] = "REJECTED"
            r["review_reason"] = "outside adjusted cutoff"
            touch(r)

    touch(week)
    return envelope_ok(ser_week(week), response_type="object", status=200)


@bp.route("/chart-weeks/<wid>/entries", methods=["GET"])
def list_entries(wid):
    require_roles(*ALL_ROLES)
    week = get_week(wid)
    limit, offset = pagination_params()
    items = sorted(
        [e for e in db.chart_entries.values() if e["chart_week_id"] == week["id"]],
        key=lambda e: (e["created_at"], e["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_entry(e) for e in page], response_type="array", pagination=page_meta)


# ---------------------------------------------------------------------------
# Reverse reachability for methodology versions
# ---------------------------------------------------------------------------

@bp.route("/methodology-versions/<mid>/chart", methods=["GET"])
def methodology_chart(mid):
    require_roles(*ALL_ROLES)
    m = get_methodology(mid)
    chart = db.charts.get(m["chart_id"])
    items = [chart] if chart is not None else []
    return envelope_ok([ser_chart(c) for c in items], response_type="array")


@bp.route("/methodology-versions/<mid>/computed-weeks", methods=["GET"])
def methodology_computed_weeks(mid):
    require_roles("PlatformAdmin", "ChartManager", "ChartOps", "Investigator")
    m = get_methodology(mid)
    items = sorted(
        [w for w in db.chart_weeks.values() if w["computed_methodology_version_id"] == m["id"]],
        key=lambda w: (w["created_at"], w["_seq"]),
    )
    return envelope_ok([ser_week(w) for w in items], response_type="array")


@bp.route("/methodology-versions/<mid>/freeze-resolutions", methods=["GET"])
def methodology_freeze_resolutions(mid):
    require_roles("PlatformAdmin", "ChartManager", "ChartOps", "Investigator")
    m = get_methodology(mid)
    items = sorted(
        [f for f in db.chart_freezes.values() if f["resolved_by_methodology_version_id"] == m["id"]],
        key=lambda f: (f["created_at"], f["_seq"]),
    )
    return envelope_ok([ser_freeze(f) for f in items], response_type="array")


# ---------------------------------------------------------------------------
# Recurrent rules
# ---------------------------------------------------------------------------

@bp.route("/recurrent-rules", methods=["POST"])
def create_rule():
    require_roles("ChartManager")
    payload = get_json()
    rule_code = payload.get("rule_code")
    for r in db.recurrent_rules.values():
        if r["rule_code"] == rule_code:
            raise errors.ApiError("ERR_VALIDATION", "rule_code must be unique", 422)

    rule = new_entity()
    rule.update(
        rule_code=rule_code,
        max_weeks=payload.get("max_weeks"),
        min_rank=payload.get("min_rank"),
        reentry_min_rank=payload.get("reentry_min_rank"),
        description=payload.get("description"),
    )
    db.recurrent_rules[rule["id"]] = rule
    from services import ser_rule
    return envelope_ok(ser_rule(rule), response_type="object", status=201)


@bp.route("/recurrent-rules/<rid>", methods=["GET"])
def get_rule_route(rid):
    require_roles(*ALL_ROLES)
    rule = get_rule(rid)
    from services import ser_rule
    return envelope_ok(ser_rule(rule), response_type="object")


@bp.route("/recurrent-rules/<rid>/charts", methods=["GET"])
def rule_charts(rid):
    require_roles(*ALL_ROLES)
    rule = get_rule(rid)
    limit, offset = pagination_params()
    items = sorted(
        [c for c in db.charts.values() if c["recurrent_rule_id"] == rule["id"]],
        key=lambda c: (c["created_at"], c["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_chart(c) for c in page], response_type="array", pagination=page_meta)
