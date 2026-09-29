"""Derived-field recomputes, ledger reconciliation and the service's cascades.

Every recompute here runs inside the request that triggered it: when a request
returns 2xx every downstream figure it touched has already been rewritten.
"""

from db import apply_changes, by_created, db, now, touch
from services import calc
from util import floor_div, rhu_div, whole_days

LIVE_LINE_STATUSES = ("PROPOSED", "ALLOCATED")
EDITABLE_PLAN_STATUSES = ("DRAFT", "COSTED")
ZERO_LINE_FIGURES = (
    "allocated_quantity",
    "holdout_quantity",
    "mailable_quantity",
    "forecast_demand_cents",
    "gross_margin_cents",
    "circulation_cost_cents",
    "contribution_cents",
)


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------


def season_of_plan(plan):
    return db.seasons[plan["season_id"]]


def plan_of_drop(drop):
    return db.plans[drop["circulation_plan_id"]]


def season_of_drop(drop):
    return season_of_plan(plan_of_drop(drop))


def drop_of_line(line):
    return db.drops[line["drop_id"]]


def lines_of_drop(drop_id):
    return by_created([l for l in db.lines.values() if l["drop_id"] == drop_id])


def drops_of_plan(plan_id):
    return by_created(
        [d for d in db.drops.values() if d["circulation_plan_id"] == plan_id]
    )


def lines_of_plan(plan_id):
    drop_ids = set(d["id"] for d in db.drops.values() if d["circulation_plan_id"] == plan_id)
    return by_created([l for l in db.lines.values() if l["drop_id"] in drop_ids])


def placements_of_drop(drop_id):
    return by_created([p for p in db.placements.values() if p["drop_id"] == drop_id])


def batches_of_drop(drop_id):
    return by_created([b for b in db.batches.values() if b["drop_id"] == drop_id])


def cells_of_line(line_id):
    return by_created(
        [c for c in db.test_cells.values() if c["circulation_line_id"] == line_id]
    )


def segments_of_season(season_id):
    return by_created([s for s in db.segments.values() if s["season_id"] == season_id])


def children_of_segment(segment_id):
    return [s for s in db.segments.values() if s["parent_segment_id"] == segment_id]


def line_response_and_aov(line, season):
    """Resolve effective response rate and average order value from the single
    non-null audience reference."""
    if line["housefile_segment_id"] is not None:
        segment = db.segments[line["housefile_segment_id"]]
        return segment["historical_response_rate_bps"], segment["avg_order_value_cents"]
    rental = db.rentals[line["prospect_list_rental_id"]]
    return rental["expected_response_rate_bps"], season["prospect_avg_order_value_cents"]


def line_per_name_extra(line):
    if line["prospect_list_rental_id"] is None:
        return 0
    return db.rentals[line["prospect_list_rental_id"]]["unit_cost_cents_per_name"]


# ---------------------------------------------------------------------------
# Segment tree
# ---------------------------------------------------------------------------


def _rollup_count(segment_id):
    segment = db.segments[segment_id]
    total = segment["housefile_count"]
    for child in children_of_segment(segment_id):
        total += _rollup_count(child["id"])
    return total


def refresh_segment_tree(skip_touch_ids=()):
    """Recompute is_leaf and rollup_housefile_count across the whole forest.

    Rows whose ids appear in `skip_touch_ids` are updated in place without an
    extra version bump because the caller already accounted for their mutation.
    """
    parented = set(
        s["parent_segment_id"]
        for s in db.segments.values()
        if s["parent_segment_id"] is not None
    )
    for segment in db.segments.values():
        updates = {
            "is_leaf": segment["id"] not in parented,
            "rollup_housefile_count": _rollup_count(segment["id"]),
        }
        changed = apply_changes(segment, updates)
        if changed and segment["id"] not in skip_touch_ids:
            touch(segment)


def score_segment(segment):
    score = calc.rfm_score(
        segment["recency_days"], segment["orders_12mo"], segment["ltv_cents"]
    )
    segment["rfm_score"] = score
    segment["segment_tier"] = calc.segment_tier(score)


def recompute_fatigue(segment, bump_version=True):
    """Rebuild fatigue_score from scratch and apply sticky suppression."""
    season = db.seasons[segment["season_id"]]
    clock = now()
    total = 0
    for event in db.contact_events.values():
        if event["housefile_segment_id"] != segment["id"]:
            continue
        days_ago = whole_days(event["contact_date"], clock)
        if days_ago > season["fatigue_window_days"]:
            continue
        total += calc.weighted_points(event["channel"], days_ago)
    segment["fatigue_score"] = total
    crossed = total >= season["fatigue_suppression_threshold"]
    if crossed:
        segment["contact_strategy"] = "SUPPRESS_ONLY"
        segment["suppressed_at"] = clock
    if bump_version:
        touch(segment)
    return crossed


# ---------------------------------------------------------------------------
# Drop derived fields
# ---------------------------------------------------------------------------


def recompute_drop_quantities(drop):
    lines = lines_of_drop(drop["id"])
    requested_total = sum(
        l["requested_quantity"] for l in lines if l["status"] in LIVE_LINE_STATUSES
    )
    planned = sum(l["allocated_quantity"] for l in lines if l["status"] == "ALLOCATED")
    return apply_changes(
        drop,
        {"requested_quantity_total": requested_total, "planned_quantity": planned},
    )


def recompute_drop_space(drop):
    allocated = sum(p["square_inches"] for p in placements_of_drop(drop["id"]))
    return apply_changes(
        drop,
        {
            "allocated_square_inches": allocated,
            "unallocated_square_inches": drop["square_inch_capacity"] - allocated,
        },
    )


def recompute_drop_cost(drop, variant=None):
    """Re-derive the three independently rounded cost-per-book components.

    `variant` of None means "the drop's current cost_basis".
    """
    season = season_of_drop(drop)
    if variant is None:
        variant = drop["cost_basis"]
    quantity = drop["planned_quantity"]
    rebate = calc.print_rebate_bps(quantity)
    printing = calc.printing_cents_per_book(
        drop["page_count"], season["print_cost_per_page_per_thousand_cents"], rebate
    )
    paper = calc.paper_cents_per_book(
        drop["page_count"],
        season["paper_oz_per_page_milli"],
        season["paper_cost_per_lb_cents"],
    )
    has_batch = len(batches_of_drop(drop["id"])) > 0
    if variant == "PRESORTED_ACTUAL" and has_batch:
        basis = "PRESORTED_ACTUAL"
        if quantity > 0:
            postage = rhu_div(drop["postage_total_cents"], quantity)
        else:
            postage = 0
    else:
        basis = "ESTIMATED_POSTAGE"
        postage = season["default_postage_estimate_cents_per_piece"]
    return apply_changes(
        drop,
        {
            "print_rebate_bps": rebate,
            "printing_cents_per_book": printing,
            "paper_cents_per_book": paper,
            "postage_cents_per_book": postage,
            "cost_per_book_cents": printing + paper + postage,
            "cost_basis": basis,
        },
    )


# ---------------------------------------------------------------------------
# Circulation-line derived fields
# ---------------------------------------------------------------------------


def recompute_line_gross_forecast(line, season):
    response_bps, aov = line_response_and_aov(line, season)
    orders = calc.forecast_orders(line["requested_quantity"], response_bps)
    return apply_changes(
        line,
        {
            "effective_response_bps": response_bps,
            "gross_forecast_demand_cents": orders * aov,
        },
    )


def recompute_line_net_forecast(line, season):
    response_bps, aov = line_response_and_aov(line, season)
    orders = calc.forecast_orders(line["mailable_quantity"], response_bps)
    return apply_changes(
        line,
        {
            "effective_response_bps": response_bps,
            "forecast_demand_cents": orders * aov,
        },
    )


def recompute_line_profitability(line, drop, season):
    extra = line_per_name_extra(line)
    margin = calc.gross_margin_cents(line["forecast_demand_cents"], season["cogs_rate_bps"])
    circulation_cost = line["mailable_quantity"] * (drop["cost_per_book_cents"] + extra)
    return apply_changes(
        line,
        {
            "gross_margin_cents": margin,
            "circulation_cost_cents": circulation_cost,
            "contribution_cents": margin - circulation_cost,
        },
    )


def recompute_allocated_lines_of_drop(drop, bump_version=False):
    """Re-derive per-line profitability after the drop's cost per book moved.

    The forecast figures are deliberately untouched: only allocation recomputes
    the committed demand view.
    """
    season = season_of_drop(drop)
    for line in lines_of_drop(drop["id"]):
        if line["status"] != "ALLOCATED":
            continue
        changed = recompute_line_profitability(line, drop, season)
        if changed and bump_version:
            touch(line)


# ---------------------------------------------------------------------------
# Plan ledgers and roll-up
# ---------------------------------------------------------------------------


def recompute_plan_budget(plan):
    return apply_changes(
        plan,
        {"uncommitted_budget_cents": plan["budget_cents"] - plan["committed_cost_cents"]},
    )


def recompute_plan_rollup(plan):
    """Sum already-rounded per-line figures over ALLOCATED lines of
    non-CANCELLED drops."""
    cost = 0
    demand = 0
    contribution = 0
    for drop in drops_of_plan(plan["id"]):
        if drop["production_status"] == "CANCELLED":
            continue
        for line in lines_of_drop(drop["id"]):
            if line["status"] != "ALLOCATED":
                continue
            cost += line["circulation_cost_cents"]
            demand += line["forecast_demand_cents"]
            contribution += line["contribution_cents"]
    return apply_changes(
        plan,
        {
            "planned_cost_cents": cost,
            "planned_demand_cents": demand,
            "planned_contribution_cents": contribution,
        },
    )


def plan_structural_recompute(plan):
    """Refresh the plan's ledgers after a structural mutation of its drops or
    lines, driving the automatic COSTED -> DRAFT invalidation edge."""
    changed = recompute_plan_budget(plan)
    if recompute_plan_rollup(plan):
        changed = True
    if plan["status"] == "COSTED":
        plan["status"] = "DRAFT"
        changed = True
    # §2.2: a version advances on every mutation, including one a cascade
    # reaching the row from another aggregate performed.
    if changed:
        touch(plan)


# ---------------------------------------------------------------------------
# Line retirement primitives (shared by void, plan cancel, and both cascades)
# ---------------------------------------------------------------------------


def _retire_line(line, plan, new_status):
    """Move a live line to a terminal status, crediting back exactly what it
    froze — never a recomputed approximation."""
    if line["status"] == "ALLOCATED":
        plan["committed_cost_cents"] = plan["committed_cost_cents"] - line["committed_cost_cents"]
    line["committed_cost_cents"] = 0
    line["status"] = new_status
    for field in ZERO_LINE_FIGURES:
        line[field] = 0
    touch(line)


def void_line(line, plan):
    _retire_line(line, plan, "VOIDED")


def suppress_line(line, plan):
    _retire_line(line, plan, "SUPPRESSED")


# ---------------------------------------------------------------------------
# Hop four / five of the mailing cascade
# ---------------------------------------------------------------------------


def cascade_suppress_segment_lines(segment_id):
    """A segment has flipped to SUPPRESS_ONLY: retire its live lines, but only
    on drops still in PLANNED — presorted books cannot be recalled."""
    affected_drops = []
    affected_plans = []
    for line in live_lines_for_segment(segment_id):
        drop = drop_of_line(line)
        if drop["production_status"] != "PLANNED":
            continue
        plan = plan_of_drop(drop)
        suppress_line(line, plan)
        if drop["id"] not in affected_drops:
            affected_drops.append(drop["id"])
        if plan["id"] not in affected_plans:
            affected_plans.append(plan["id"])
    for drop_id in affected_drops:
        drop = db.drops[drop_id]
        recompute_drop_quantities(drop)
        recompute_drop_cost(drop)
        recompute_allocated_lines_of_drop(drop)
        touch(drop)
    for plan_id in affected_plans:
        plan_structural_recompute(db.plans[plan_id])


def live_lines_for_segment(segment_id):
    return by_created(
        [
            l
            for l in db.lines.values()
            if l["housefile_segment_id"] == segment_id
            and l["status"] in LIVE_LINE_STATUSES
        ]
    )


# ---------------------------------------------------------------------------
# Contact events
# ---------------------------------------------------------------------------


def create_contact_event(segment_id, drop_id, channel, contact_date, source):
    from db import new_row

    clock = now()
    days_ago = whole_days(contact_date, clock)
    row = new_row(with_version=False)
    row.update(
        {
            "housefile_segment_id": segment_id,
            "drop_id": drop_id,
            "channel": channel,
            "contact_date": contact_date,
            "source": source,
            "channel_weight": calc.CHANNEL_WEIGHT[channel],
            "decay_factor_bps": calc.decay_factor_bps(days_ago),
            "weighted_points": calc.weighted_points(channel, days_ago),
        }
    )
    db.contact_events[row["id"]] = row
    return row


def applicable_suppression_rule(season_id, channel):
    rules = sorted(
        [
            r
            for r in db.suppression_rules.values()
            if r["season_id"] == season_id and r["is_enabled"]
        ],
        key=lambda r: (r["priority"], r["created_at"], r["_seq"]),
    )
    for rule in rules:
        if rule["channel_scope"] == "ALL" or rule["channel_scope"] == channel:
            return rule
    return None


def count_in_window(segment_id, rule):
    """Existing in-scope contact events inside the rule's trailing window."""
    clock = now()
    total = 0
    for event in db.contact_events.values():
        if event["housefile_segment_id"] != segment_id:
            continue
        if rule["channel_scope"] != "ALL" and event["channel"] != rule["channel_scope"]:
            continue
        if whole_days(event["contact_date"], clock) > rule["window_days"]:
            continue
        total += 1
    return total


# ---------------------------------------------------------------------------
# 3.3  Merge-purge
# ---------------------------------------------------------------------------


def compute_merge_purge(plan, rentals):
    """The deterministic merge-purge computation.

    Returns a dict of the six persisted computed figures.  `rentals` is the
    resolved input set; the pinned processing order is derived here.
    """
    leaves = [s for s in segments_of_season(plan["season_id"]) if s["is_leaf"]]
    housefile_gross = sum(s["housefile_count"] for s in leaves)
    suppressed_names = sum(
        s["housefile_count"] for s in leaves if s["contact_strategy"] == "SUPPRESS_ONLY"
    )
    gross_input_names = housefile_gross + sum(r["gross_names"] for r in rentals)

    ordered = sorted(
        rentals,
        key=lambda r: (-r["coop_model_score"], r["created_at"], r["_seq"]),
    )
    duplicates_removed = 0
    post_dedup = {}
    for index, rental in enumerate(ordered):
        housefile_dupes = floor_div(
            rental["gross_names"] * rental["housefile_overlap_bps"], 10000
        )
        if index == 0:
            inter_dupes = 0
        else:
            inter_dupes = floor_div(
                (rental["gross_names"] - housefile_dupes) * rental["inter_list_overlap_bps"],
                10000,
            )
        duplicates_removed += housefile_dupes + inter_dupes
        post_dedup[rental["id"]] = rental["gross_names"] - housefile_dupes - inter_dupes

    net_mailable_names = gross_input_names - suppressed_names - duplicates_removed
    return {
        "housefile_leaf_segment_count": len(leaves),
        "gross_input_names": gross_input_names,
        "suppressed_names": suppressed_names,
        "duplicates_removed": duplicates_removed,
        "net_mailable_names": net_mailable_names,
        "processing_order": [r["id"] for r in ordered],
        "_post_dedup": post_dedup,
    }


def plan_has_completed_merge_purge(plan_id):
    return any(
        r["circulation_plan_id"] == plan_id and r["status"] == "COMPLETED"
        for r in db.merge_purge_runs.values()
    )


# ---------------------------------------------------------------------------
# 3.5  The allocation waterfall
# ---------------------------------------------------------------------------


def waterfall_priority_key(line):
    """HOUSEFILE before RENTAL; then descending audience score; then created_at."""
    if line["audience_type"] == "HOUSEFILE":
        family = 0
        score = db.segments[line["housefile_segment_id"]]["rfm_score"]
    else:
        family = 1
        score = db.rentals[line["prospect_list_rental_id"]]["coop_model_score"]
    return (family, -score, line["created_at"], line["_seq"])


def compute_provisional_cost(drop):
    season = season_of_drop(drop)
    rebate = calc.print_rebate_bps(drop["requested_quantity_total"])
    printing = calc.printing_cents_per_book(
        drop["page_count"], season["print_cost_per_page_per_thousand_cents"], rebate
    )
    paper = calc.paper_cents_per_book(
        drop["page_count"],
        season["paper_oz_per_page_milli"],
        season["paper_cost_per_lb_cents"],
    )
    postage = season["default_postage_estimate_cents_per_piece"]
    return printing + paper + postage


def line_unit_cost(line, provisional):
    return provisional + line_per_name_extra(line)


def line_audience_cap(line):
    if line["audience_type"] == "HOUSEFILE":
        return db.segments[line["housefile_segment_id"]]["housefile_count"]
    return db.rentals[line["prospect_list_rental_id"]]["net_names_delivered"]


def run_allocation_waterfall(drop, plan, season, proposed_lines, provisional):
    """Walk the ordered PROPOSED lines, funding each to its own cap in turn."""
    remaining = plan["uncommitted_budget_cents"]
    next_rank = 1
    for line in proposed_lines:
        unit_cost = line_unit_cost(line, provisional)
        line["allocation_rank"] = next_rank
        next_rank += 1
        line["unit_cost_cents"] = unit_cost
        cap_budget = calc.budget_cap(remaining, unit_cost)
        candidates = [line["requested_quantity"], line_audience_cap(line)]
        if cap_budget is not None:
            candidates.append(cap_budget)
        allocated = min(candidates)
        if allocated <= 0:
            line["allocated_quantity"] = 0
            line["committed_cost_cents"] = 0
            touch(line)
            continue
        holdout = calc.holdout_quantity(allocated, line["holdout_pct_bps"])
        committed = allocated * unit_cost
        line["allocated_quantity"] = allocated
        line["holdout_quantity"] = holdout
        line["mailable_quantity"] = allocated - holdout
        line["committed_cost_cents"] = committed
        line["status"] = "ALLOCATED"
        plan["committed_cost_cents"] = plan["committed_cost_cents"] + committed
        remaining = remaining - committed
        touch(line)


# ---------------------------------------------------------------------------
# 3.7  The five-hop mailing cascade
# ---------------------------------------------------------------------------


def run_mail_cascade(drop):
    """Hops one through five, each caused by the hop before it."""
    # Hop one: synthesize a MAIL contact event per ALLOCATED housefile line.
    affected_segment_ids = []
    for line in lines_of_drop(drop["id"]):
        if line["status"] != "ALLOCATED":
            continue
        if line["housefile_segment_id"] is None:
            continue
        create_contact_event(
            line["housefile_segment_id"],
            drop["id"],
            "MAIL",
            drop["in_home_date"],
            "DROP_MAIL_CASCADE",
        )
        if line["housefile_segment_id"] not in affected_segment_ids:
            affected_segment_ids.append(line["housefile_segment_id"])

    # Hop two and three: re-aggregate contact pressure, applying suppression.
    flipped = []
    for segment_id in affected_segment_ids:
        segment = db.segments[segment_id]
        if recompute_fatigue(segment):
            flipped.append(segment_id)

    # Hops four and five: retire the newly suppressed segments' live lines.
    for segment_id in flipped:
        cascade_suppress_segment_lines(segment_id)


# ---------------------------------------------------------------------------
# 3.2  The rental-cancellation unwind
# ---------------------------------------------------------------------------


def run_rental_cancel_cascade(rental):
    """Five-step unwind; unlike the mailing cascade it does not spare lines on
    presorted drops, though it preserves those drops' cost_basis."""
    # Step one.
    rental["gross_names"] = 0
    rental["net_names_delivered"] = 0

    # Step two: every COMPLETED run holding this rental goes STALE and recomputes.
    for run in by_created(list(db.merge_purge_runs.values())):
        if run["status"] != "COMPLETED":
            continue
        if rental["id"] not in run["input_rental_ids"]:
            continue
        plan = db.plans[run["circulation_plan_id"]]
        remaining_ids = [
            rid for rid in run["processing_order"] if rid != rental["id"]
        ]
        remaining = [db.rentals[rid] for rid in remaining_ids if rid in db.rentals]
        figures = compute_merge_purge(plan, remaining)
        run["status"] = "STALE"
        run["housefile_leaf_segment_count"] = figures["housefile_leaf_segment_count"]
        run["gross_input_names"] = figures["gross_input_names"]
        run["suppressed_names"] = figures["suppressed_names"]
        run["duplicates_removed"] = figures["duplicates_removed"]
        run["net_mailable_names"] = figures["net_mailable_names"]
        run["processing_order"] = figures["processing_order"]
        touch(run)

    # Steps three and four: void every live line pointing at this rental.
    affected_drops = []
    affected_plans = []
    for line in by_created(list(db.lines.values())):
        if line["prospect_list_rental_id"] != rental["id"]:
            continue
        if line["status"] not in LIVE_LINE_STATUSES:
            continue
        drop = drop_of_line(line)
        plan = plan_of_drop(drop)
        void_line(line, plan)
        if drop["id"] not in affected_drops:
            affected_drops.append(drop["id"])
        if plan["id"] not in affected_plans:
            affected_plans.append(plan["id"])

    # Step five: reconcile every affected drop and plan.
    for drop_id in affected_drops:
        drop = db.drops[drop_id]
        recompute_drop_quantities(drop)
        recompute_drop_cost(drop)
        recompute_allocated_lines_of_drop(drop)
        touch(drop)
    for plan_id in affected_plans:
        plan_structural_recompute(db.plans[plan_id])


# ---------------------------------------------------------------------------
# 3.9  Test cell scoring
# ---------------------------------------------------------------------------


def score_test_cell(cell):
    """Re-derive one cell's lift and verdict against its line's measured control."""
    cell["response_rate_bps"] = calc.response_rate_bps(cell["responders"], cell["quantity"])
    control = None
    for sibling in cells_of_line(cell["circulation_line_id"]):
        if sibling["id"] == cell["id"]:
            continue
        if sibling["cell_role"] != "CONTROL":
            continue
        if sibling["status"] != "MEASURED":
            continue
        control = sibling
        break
    if cell["cell_role"] == "CONTROL" or control is None:
        cell["lift_bps"] = 0
        cell["significance"] = "INSUFFICIENT_CONTROL"
        return
    if control["response_rate_bps"] == 0:
        cell["lift_bps"] = 0
        cell["significance"] = "INSUFFICIENT_CONTROL"
        return
    cell["lift_bps"] = calc.lift_bps(
        cell["response_rate_bps"], control["response_rate_bps"]
    )
    if (
        cell["quantity"] < calc.MIN_SIGNIFICANT_SAMPLE
        or control["quantity"] < calc.MIN_SIGNIFICANT_SAMPLE
    ):
        cell["significance"] = "INSUFFICIENT_SAMPLE"
    elif abs(cell["lift_bps"]) >= calc.SIGNIFICANT_LIFT_BPS:
        cell["significance"] = "SIGNIFICANT"
    else:
        cell["significance"] = "NOT_SIGNIFICANT"


# ---------------------------------------------------------------------------
# 3.9  Matchback attribution
# ---------------------------------------------------------------------------


def _fresher(candidate, incumbent):
    if incumbent is None:
        return True
    if candidate["contact_date"] != incumbent["contact_date"]:
        return candidate["contact_date"] > incumbent["contact_date"]
    return (candidate["created_at"], candidate["_seq"]) < (
        incumbent["created_at"],
        incumbent["_seq"],
    )


def _earlier(candidate, incumbent):
    if incumbent is None:
        return True
    if candidate["contact_date"] != incumbent["contact_date"]:
        return candidate["contact_date"] < incumbent["contact_date"]
    return (candidate["created_at"], candidate["_seq"]) < (
        incumbent["created_at"],
        incumbent["_seq"],
    )


def compute_matchback(drop, variant, window_days):
    contacted_segments = set(
        e["housefile_segment_id"]
        for e in db.contact_events.values()
        if e["drop_id"] == drop["id"]
    )
    events = by_created(list(db.contact_events.values()))
    matched = 0
    attributed_orders = 0
    attributed_demand = 0

    for order in by_created(list(db.online_orders.values())):
        if order["housefile_segment_id"] in contacted_segments:
            matched += 1
        order_date = order["order_date"]
        qualifying = []
        for event in events:
            if event["housefile_segment_id"] != order["housefile_segment_id"]:
                continue
            # Half-open window: (order_date - window_days, order_date]
            age_days = whole_days(event["contact_date"], order_date)
            if event["contact_date"] > order_date:
                continue
            if age_days >= window_days:
                continue
            qualifying.append(event)
        if not qualifying:
            continue

        credits = {}
        if variant == "LAST_TOUCH_MAIL":
            mail_touches = [e for e in qualifying if e["channel"] == "MAIL"]
            if not mail_touches:
                continue
            winner = None
            for event in mail_touches:
                if _fresher(event, winner):
                    winner = event
            credits[winner["drop_id"]] = (
                credits.get(winner["drop_id"], 0) + order["demand_cents"]
            )
        else:
            count = len(qualifying)
            share = floor_div(order["demand_cents"], count)
            for event in qualifying:
                credits[event["drop_id"]] = credits.get(event["drop_id"], 0) + share
            remainder = order["demand_cents"] - share * count
            if remainder:
                earliest = None
                for event in qualifying:
                    if _earlier(event, earliest):
                        earliest = event
                credits[earliest["drop_id"]] = (
                    credits.get(earliest["drop_id"], 0) + remainder
                )

        this_drop = credits.get(drop["id"], 0)
        if this_drop >= 1:
            attributed_orders += 1
            attributed_demand += this_drop

    return {
        "matched_order_count": matched,
        "attributed_order_count": attributed_orders,
        "unmatched_order_count": matched - attributed_orders,
        "attributed_demand_cents": attributed_demand,
    }
