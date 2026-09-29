"""Cross-entity lookups, rollup recomputation, state helpers and cascades."""

import calc
from errors import ApiError
from store import db, now_dt, now_iso, sort_by_created, touch

# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------


def _find(table, key, error_id):
    rec = table.get(key)
    if rec is None:
        raise ApiError(error_id)
    return rec


def get_route(route_id):
    return _find(db.routes, route_id, "ERR_ROUTE_NOT_FOUND")


def get_segment(segment_id):
    return _find(db.segments, segment_id, "ERR_SEGMENT_NOT_FOUND")


def get_walkout(walkout_id):
    return _find(db.walkouts, walkout_id, "ERR_WALKOUT_NOT_FOUND")


def get_pole_app(app_id):
    return _find(db.pole_apps, app_id, "ERR_POLE_APPLICATION_NOT_FOUND")


def get_permit(permit_id):
    return _find(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")


def get_design(design_id):
    return _find(db.designs, design_id, "ERR_DESIGN_NOT_FOUND")


def get_splice_point(splice_id):
    return _find(db.splice_points, splice_id, "ERR_SPLICE_POINT_NOT_FOUND")


def get_as_built(as_built_id):
    return _find(db.as_builts, as_built_id, "ERR_AS_BUILT_NOT_FOUND")


def route_of_segment(segment):
    return db.routes[segment["route_id"]]


def segments_of_route(route_id):
    return sort_by_created([s for s in db.segments.values() if s["route_id"] == route_id])


def walkouts_of_segment(segment_id):
    return sort_by_created([w for w in db.walkouts.values() if w["segment_id"] == segment_id])


def observations_of_walkout(walkout_id):
    return sort_by_created([o for o in db.observations.values() if o["walkout_id"] == walkout_id])


def pole_apps_of_segment(segment_id):
    return sort_by_created([a for a in db.pole_apps.values() if a["segment_id"] == segment_id])


def mr_items_of_app(app_id):
    return sort_by_created([i for i in db.mr_items.values() if i["application_id"] == app_id])


def permits_of_segment(segment_id):
    return sort_by_created([p for p in db.permits.values() if p["segment_id"] == segment_id])


def permits_of_route(route_id):
    segment_ids = set(s["id"] for s in db.segments.values() if s["route_id"] == route_id)
    return sort_by_created([p for p in db.permits.values() if p["segment_id"] in segment_ids])


def designs_of_route(route_id):
    return sort_by_created([d for d in db.designs.values() if d["route_id"] == route_id])


def splice_points_of_design(design_id):
    return sort_by_created([s for s in db.splice_points.values() if s["design_id"] == design_id])


def splice_points_of_segment(segment_id):
    return sort_by_created([s for s in db.splice_points.values() if s["segment_id"] == segment_id])


def as_builts_of_route(route_id):
    return sort_by_created([a for a in db.as_builts.values() if a["route_id"] == route_id])


def downstream_segments(segment_id):
    return sort_by_created(
        [s for s in db.segments.values() if s["predecessor_segment_id"] == segment_id]
    )


# ---------------------------------------------------------------------------
# route rollups
# ---------------------------------------------------------------------------


def recompute_route_cost_rollups(route):
    """Sum the segment cost variants, counting a null child value as zero."""
    total_prelim = 0
    total_bid = 0
    for seg in segments_of_route(route["id"]):
        if seg["preliminary_cost_cents"] is not None:
            total_prelim += seg["preliminary_cost_cents"]
        if seg["bid_ready_cost_cents"] is not None:
            total_bid += seg["bid_ready_cost_cents"]
    changed = (
        route["total_preliminary_cost_cents"] != total_prelim
        or route["total_bid_ready_cost_cents"] != total_bid
    )
    route["total_preliminary_cost_cents"] = total_prelim
    route["total_bid_ready_cost_cents"] = total_bid
    return changed


def recompute_route_bid_ready_rollup(route):
    total_bid = 0
    for seg in segments_of_route(route["id"]):
        if seg["bid_ready_cost_cents"] is not None:
            total_bid += seg["bid_ready_cost_cents"]
    changed = route["total_bid_ready_cost_cents"] != total_bid
    route["total_bid_ready_cost_cents"] = total_bid
    return changed


def recompute_route_segment_rollups(route):
    segments = segments_of_route(route["id"])
    route["segment_count"] = len(segments)
    route["design_total_length_feet"] = sum(s["length_feet"] for s in segments)


def recompute_route_budget(route):
    """Committed budget is *defined* as the sum over GRANTED applications."""
    segment_ids = set(s["id"] for s in db.segments.values() if s["route_id"] == route["id"])
    committed = 0
    for app in db.pole_apps.values():
        if app["segment_id"] in segment_ids and app["status"] == "GRANTED":
            if app["make_ready_cost_cents"] is not None:
                committed += app["make_ready_cost_cents"]
    route["budget_committed_cents"] = committed
    route["budget_available_cents"] = route["budget_authorized_cents"] - committed


# ---------------------------------------------------------------------------
# complexity indices
# ---------------------------------------------------------------------------


def compute_planned_complexity_index(route):
    segments = segments_of_route(route["id"])
    if not segments or route["segment_count"] == 0:
        return None
    return calc.planned_complexity_index(
        [s["terrain_class"] for s in segments], route["segment_count"]
    )


def recompute_live_complexity_index(route):
    rows = []
    for permit in permits_of_route(route["id"]):
        if permit["status"] in calc.LIVE_INDEX_STATUSES:
            rows.append((permit["authority_type"], permit["status"]))
    segment_count = route["segment_count"]
    if not rows:
        route["live_complexity_index"] = 0
        return
    if segment_count == 0:
        route["live_complexity_index"] = 0
        return
    route["live_complexity_index"] = calc.live_complexity_index(rows, segment_count)


# ---------------------------------------------------------------------------
# walkout rollups
# ---------------------------------------------------------------------------


def recompute_walkout_rollups(walkout):
    observations = observations_of_walkout(walkout["id"])
    flagged = 0
    worst = "NONE"
    for obs in observations:
        if obs["requires_make_ready"]:
            flagged += 1
        if calc.GRADE_SEVERITY[obs["condition_grade"]] > calc.GRADE_SEVERITY[worst]:
            worst = obs["condition_grade"]
    walkout["make_ready_flagged_pole_count"] = flagged
    walkout["worst_pole_condition_grade"] = worst


def newest_accepted_walkout(segment_id):
    accepted = [w for w in walkouts_of_segment(segment_id) if w["status"] == "ACCEPTED"]
    if not accepted:
        return None
    return accepted[-1]


def recompute_segment_walkout_fields(segment):
    """accepted_obstruction_count follows the newest ACCEPTED walkout."""
    walkout = newest_accepted_walkout(segment["id"])
    if walkout is None:
        segment["accepted_obstruction_count"] = 0
        return
    segment["accepted_obstruction_count"] = walkout["obstruction_count"]
    segment["existing_conduit_available"] = walkout["conduit_available_confirmed"]


def segment_has_grade_d_pole(segment_id):
    for walkout in walkouts_of_segment(segment_id):
        if walkout["status"] != "ACCEPTED":
            continue
        for obs in observations_of_walkout(walkout["id"]):
            if obs["condition_grade"] == "D":
                return True
    return False


# ---------------------------------------------------------------------------
# segment costs
# ---------------------------------------------------------------------------


def granted_make_ready_cents(segment_id):
    total = 0
    for app in pole_apps_of_segment(segment_id):
        if app["status"] == "GRANTED" and app["make_ready_cost_cents"] is not None:
            total += app["make_ready_cost_cents"]
    return total


def compute_segment_bid_ready(segment):
    return calc.bid_ready_cost_cents(
        segment["length_feet"],
        segment["construction_method"],
        segment["terrain_class"],
        segment["accepted_obstruction_count"],
        segment["restoration_cost_cents"],
        granted_make_ready_cents(segment["id"]),
    )


def rederive_bid_ready_if_design_locked(segment):
    """Re-derive the bid-ready figure, but only while DESIGN_LOCKED."""
    if segment["engineering_status"] != "DESIGN_LOCKED":
        return False
    if segment["construction_method"] is None:
        return False
    value = compute_segment_bid_ready(segment)
    if segment["bid_ready_cost_cents"] == value:
        return False
    segment["bid_ready_cost_cents"] = value
    return True


# ---------------------------------------------------------------------------
# moratoria
# ---------------------------------------------------------------------------


def resolve_moratorium_class(segment):
    probe = segment["planned_work_start_on"]
    candidates = []
    for window in sort_by_created(list(db.moratoria.values())):
        if window["municipality_code"] != segment["municipality_code"]:
            continue
        if window["street_name"] != segment["street_name"]:
            continue
        if window["starts_on"] <= probe <= window["ends_on"]:
            candidates.append(window)
    if not candidates:
        return "NONE"
    best = candidates[0]
    for window in candidates[1:]:
        if calc.MORATORIUM_SEVERITY[window["moratorium_class"]] > calc.MORATORIUM_SEVERITY[best["moratorium_class"]]:
            best = window
    return best["moratorium_class"]


def moratorium_intersects_window(municipality_code, street_name, start_on, end_on, exclude_id=None):
    for window in db.moratoria.values():
        if exclude_id is not None and window["id"] == exclude_id:
            continue
        if window["municipality_code"] != municipality_code:
            continue
        if window["street_name"] != street_name:
            continue
        if window["starts_on"] <= end_on and start_on <= window["ends_on"]:
            return window
    return None


# ---------------------------------------------------------------------------
# design rollups
# ---------------------------------------------------------------------------


def recompute_design_rollups(design):
    placed = [s for s in splice_points_of_design(design["id"]) if s["status"] == "PLACED"]
    assigned = sum(s["fiber_count_dropped"] for s in placed)
    design["assigned_drop_fiber_count"] = assigned
    design["reserve_fiber_count"] = (
        design["fiber_count_allocated"] - design["express_fiber_count"] - assigned
    )
    design["spare_ratio_bp"] = calc.spare_ratio_bp(
        design["reserve_fiber_count"], design["fiber_count_allocated"]
    )
    design["splice_point_count"] = len(placed)
    design["handhole_count"] = len([s for s in placed if s["enclosure_type"] == "HANDHOLE"])


def stamped_design_with_revision(route_id, revision):
    for design in designs_of_route(route_id):
        if design["revision"] == revision and design["status"] == "STAMPED":
            return design
    return None


def design_with_revision(route_id, revision):
    for design in designs_of_route(route_id):
        if design["revision"] == revision:
            return design
    return None


# ---------------------------------------------------------------------------
# permit dimension helpers
# ---------------------------------------------------------------------------


def try_clear_segment_permit(segment):
    """PENDING -> CLEARED under the two-part test."""
    if segment["permit_status"] != "PENDING":
        return False
    rows = permits_of_segment(segment["id"])
    has_approved = any(p["status"] == "APPROVED" for p in rows)
    outstanding = any(p["status"] in ("UNDER_REVIEW", "REVISION_REQUESTED") for p in rows)
    if has_approved and not outstanding:
        segment["permit_status"] = "CLEARED"
        touch(segment)
        return True
    return False


def try_advance_route_to_construction_ready(route):
    if route["status"] != "PERMITTING":
        return False
    segments = segments_of_route(route["id"])
    if not segments:
        return False
    if any(s["permit_status"] != "CLEARED" for s in segments):
        return False
    if not any(d["status"] == "STAMPED" for d in designs_of_route(route["id"])):
        return False
    route["status"] = "CONSTRUCTION_READY"
    return True


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------


def rewalk_rejection_cascade(walkout):
    """Depth 5.  Hop 1 is applied by the caller (the walkout itself)."""
    segment = db.segments.get(walkout["segment_id"])
    if segment is None:
        return
    if segment["engineering_status"] not in ("WALKED", "METHOD_SELECTED", "DESIGN_LOCKED"):
        return

    # hop 2: the walked segment returns to DRAFT
    segment["engineering_status"] = "DRAFT"
    # hop 3: every engineering derivation on that segment is erased
    segment["construction_method"] = None
    segment["moratorium_class"] = "NONE"
    segment["restoration_cost_cents"] = 0
    segment["preliminary_cost_cents"] = None
    segment["bid_ready_cost_cents"] = None
    touch(segment)

    route = route_of_segment(segment)
    # hop 4: the owning route's two cost rollups are recomputed
    recompute_route_cost_rollups(route)
    touch(route)
    # hop 5: the route returns to PLANNING (live_complexity_index is NOT reset)
    if route["status"] in ("SCOPE_LOCKED", "PERMITTING", "CONSTRUCTION_READY"):
        route["status"] = "PLANNING"
        route["scope_locked_at"] = None
        route["planned_complexity_index"] = None


def permit_denial_cascade(permit):
    """Depth 5.  Hop 1 is applied by the caller (the permit itself)."""
    segment = db.segments.get(permit["segment_id"])
    if segment is None:
        return
    route = route_of_segment(segment)

    # hop 2: the segment's permit dimension is blocked
    if segment["permit_status"] in ("PENDING", "CLEARED"):
        segment["permit_status"] = "BLOCKED"
        touch(segment)

    # hop 3: release the engineering dimension, but only from DESIGN_LOCKED
    released = False
    if segment["engineering_status"] == "DESIGN_LOCKED":
        segment["engineering_status"] = "METHOD_SELECTED"
        segment["bid_ready_cost_cents"] = None
        touch(segment)
        recompute_route_bid_ready_rollup(route)
        released = True

    # hop 4: void the stamp on every stamped package with placed work there
    demoted = 0
    if released:
        for design in designs_of_route(route["id"]):
            if design["status"] != "STAMPED":
                continue
            owns_placed_work = any(
                sp["segment_id"] == segment["id"] and sp["status"] == "PLACED"
                for sp in splice_points_of_design(design["id"])
            )
            if not owns_placed_work:
                continue
            design["status"] = "DRAFT"
            design["stamp_voided_at"] = now_iso()
            touch(design)
            demoted += 1

    # hop 5: the route falls back from CONSTRUCTION_READY to PERMITTING
    if demoted > 0 and route["status"] == "CONSTRUCTION_READY":
        route["status"] = "PERMITTING"


def attachment_withdrawal_cascade(app):
    """Depth 4.  Hop 1 is applied by the caller (the application itself)."""
    segment = db.segments.get(app["segment_id"])
    if segment is None:
        return
    route = route_of_segment(segment)
    # hop 2: the committed budget is released (committed is a sum over GRANTED)
    recompute_route_budget(route)
    # hop 3: the segment's bid-ready cost loses this make-ready contribution
    if rederive_bid_ready_if_design_locked(segment):
        touch(segment)
    # hop 4: the route's bid-ready rollup is recomputed
    recompute_route_bid_ready_rollup(route)
    touch(route)
