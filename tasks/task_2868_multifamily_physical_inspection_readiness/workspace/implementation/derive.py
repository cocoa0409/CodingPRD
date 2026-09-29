"""Derived counters, the readiness posture and the cross-cutting cascades.

Counters are always recomputed from the rows that currently satisfy their
stated predicate, never incrementally adjusted (PRD 2.9).
"""

import auth
import calc
import store

# --- reachability ----------------------------------------------------------
def deficiency_property_id(row):
    return auth.property_of_deficiency(row)


def property_deficiencies(property_id):
    return [
        row
        for row in store.deficiencies.values()
        if deficiency_property_id(row) == property_id
    ]


def property_work_orders(property_id):
    return [
        row
        for row in store.work_orders.values()
        if auth.property_of_work_order(row) == property_id
    ]


def sweep_work_orders(sweep_id):
    return [row for row in store.work_orders.values() if row["sweep_id"] == sweep_id]


def deficiency_work_orders(deficiency_id):
    return [
        row for row in store.work_orders.values() if row["deficiency_id"] == deficiency_id
    ]


def inspection_deficiencies(inspection_id):
    return [
        row
        for row in store.deficiencies.values()
        if row.get("inspection_id") == inspection_id
    ]


def inspection_selections(inspection_id):
    return [
        row for row in store.selections.values() if row["inspection_id"] == inspection_id
    ]


def property_units(property_id):
    return [row for row in store.units.values() if row["property_id"] == property_id]


def property_inspections(property_id):
    return [
        row for row in store.inspections.values() if row["property_id"] == property_id
    ]


def property_sweeps(property_id):
    return [row for row in store.sweeps.values() if row["property_id"] == property_id]


def property_capital_items(property_id):
    return [
        row for row in store.capital_items.values() if row["property_id"] == property_id
    ]


def inspection_appeals(inspection_id):
    return [
        row for row in store.appeals.values() if row["inspection_id"] == inspection_id
    ]


def inspection_plans(inspection_id):
    return [row for row in store.plans.values() if row["inspection_id"] == inspection_id]


# --- unit counters --------------------------------------------------------
def recompute_unit_open_count(unit):
    count = 0
    for row in store.deficiencies.values():
        if row.get("unit_id") != unit["id"]:
            continue
        if row["status"] in ("OPEN", "OVERDUE"):
            count += 1
    unit["open_deficiency_count"] = count
    store.touch(unit, bump_version=False)


def recompute_unit_prior_count(unit):
    count = 0
    for row in store.deficiencies.values():
        if row.get("unit_id") != unit["id"]:
            continue
        if row["source"] != "INSPECTION":
            continue
        if row["status"] == "VOIDED":
            continue
        insp = store.inspections.get(row.get("inspection_id"))
        if insp is None:
            continue
        if insp["status"] not in ("CLOSED", "FOLLOW_UP_SCHEDULED"):
            continue
        count += 1
    unit["prior_deficiency_count"] = count
    store.touch(unit, bump_version=False)


def refresh_unit_history(inspection_id):
    """Every Unit carrying a non-VOIDED deficiency of this inspection."""
    seen = set()
    for row in inspection_deficiencies(inspection_id):
        if row["status"] == "VOIDED":
            continue
        unit_id = row.get("unit_id")
        if unit_id and unit_id not in seen:
            seen.add(unit_id)
            unit = store.units.get(unit_id)
            if unit is not None:
                recompute_unit_prior_count(unit)


# --- inspection counters --------------------------------------------------
def recompute_inspection_sums(insp):
    rows = [r for r in inspection_deficiencies(insp["id"]) if r["status"] != "VOIDED"]
    sums = calc.area_raw_sums(rows)
    insp["unit_area_points"] = calc.r2(sums["UNIT"])
    insp["inside_area_points"] = calc.r2(sums["INSIDE"])
    insp["outside_area_points"] = calc.r2(sums["OUTSIDE"])
    insp["total_points_deducted"] = calc.r2(
        sums["UNIT"] + sums["INSIDE"] + sums["OUTSIDE"]
    )
    insp["life_threatening_count"] = len(
        [r for r in rows if r["severity"] == "LIFE_THREATENING"]
    )


def recompute_slot_counters(insp):
    slots = inspection_selections(insp["id"])
    active = [s for s in slots if s["selection_status"] == "ACTIVE"]
    insp["sample_size"] = len(active)
    insp["inspected_unit_count"] = len(
        [s for s in active if s["access_status"] == "GRANTED"]
    )
    insp["refused_unit_count"] = len(
        [s for s in active if s["access_status"] == "REFUSED"]
    )


def compute_inspection_scores(insp):
    """Returns (provisional_score, final_score) from the pinned standard."""
    standard = store.standards[insp["standard_id"]]
    rows = [r for r in inspection_deficiencies(insp["id"]) if r["status"] != "VOIDED"]
    sums = calc.area_raw_sums(rows)
    provisional = calc.composite_score(
        sums,
        standard,
        "PROVISIONAL",
        insp["inspected_unit_count"],
        insp["refused_unit_count"],
        insp["sample_size"],
    )
    final = calc.composite_score(
        sums,
        standard,
        "FINAL",
        insp["inspected_unit_count"],
        insp["refused_unit_count"],
        insp["sample_size"],
    )
    return provisional, final


# --- sweep counters -------------------------------------------------------
def recompute_sweep_counters(sweep):
    rows = sweep_work_orders(sweep["id"])
    sweep["generated_work_order_count"] = len(rows)
    sweep["open_work_order_count"] = len(
        [r for r in rows if r["repair_status"] == "OPEN"]
    )
    sweep["verified_work_order_count"] = len(
        [r for r in rows if r["verification_status"] == "VERIFIED"]
    )
    sweep["void_work_order_count"] = len([r for r in rows if r["repair_status"] == "VOID"])
    sweep["urgent_work_order_count"] = len(
        [r for r in rows if r["priority_tier"] == "URGENT"]
    )
    sweep["closure_verified_rate"] = calc.closure_verified_rate(rows)


# --- standard counters ----------------------------------------------------
def recompute_standard_counters(standard):
    rows = [
        r for r in store.definitions.values() if r["standard_id"] == standard["id"]
    ]
    standard["defect_definition_count"] = len(rows)
    standard["life_threatening_definition_count"] = len(
        [r for r in rows if r["severity"] == "LIFE_THREATENING"]
    )


# --- property derived fields and the readiness posture --------------------
def recompute_property_fields(prop):
    rows = property_deficiencies(prop["id"])
    prop["open_life_threatening_count"] = len(
        [
            r
            for r in rows
            if r["severity"] == "LIFE_THREATENING" and r["status"] in ("OPEN", "OVERDUE")
        ]
    )
    prop["overdue_life_threatening_count"] = len(
        [
            r
            for r in rows
            if r["severity"] == "LIFE_THREATENING" and r["status"] == "OVERDUE"
        ]
    )
    prop["open_severe_count"] = len(
        [r for r in rows if r["severity"] == "SEVERE" and r["status"] in ("OPEN", "OVERDUE")]
    )

    scored = [
        i
        for i in property_inspections(prop["id"])
        if i.get("scored_at") and i.get("final_score") is not None
    ]
    if scored:
        scored.sort(key=lambda i: (store.parse_instant(i["scored_at"]), -i["_seq"]),
                    reverse=True)
        prop["last_final_score"] = scored[0]["final_score"]

    closed = [
        s for s in property_sweeps(prop["id"]) if s["status"] == "CLOSED" and s["closed_at"]
    ]
    if closed:
        closed.sort(key=lambda s: (store.parse_instant(s["closed_at"]), s["_seq"]))
        prop["last_sweep_closed_at"] = closed[-1]["closed_at"]

    prop["allocated_reserve_total_cents"] = sum(
        item["allocated_reserve_cents"]
        for item in property_capital_items(prop["id"])
        if item["status"] == "ACTIVE"
    )


def derive_posture(prop):
    if prop["overdue_life_threatening_count"] >= 1:
        return "FROZEN"
    if prop["open_life_threatening_count"] >= 1:
        return "RESTRICTED"
    if prop["open_severe_count"] >= calc.WATCH_SEVERE_FLOOR:
        return "WATCH"
    score = prop.get("last_final_score")
    if score is not None and calc.d(score) < calc.WATCH_SCORE_FLOOR:
        return "WATCH"
    return "READY"


def rederive_property(prop, bump_version=True):
    """Recompute the property's derived fields, re-derive the posture and run
    the symmetric work-order escalation sweep. Returns the posture."""
    recompute_property_fields(prop)
    posture = derive_posture(prop)
    prop["readiness_posture"] = posture
    store.touch(prop, bump_version=bump_version)
    apply_posture_escalation(prop["id"], posture)
    return posture


def apply_posture_escalation(property_id, posture):
    """PRD 2.9: symmetric escalation / de-escalation of OPEN work orders."""
    touched = set()
    escalate = posture in ("RESTRICTED", "FROZEN")
    for work_order in property_work_orders(property_id):
        if work_order["repair_status"] != "OPEN":
            continue
        if escalate:
            if work_order["priority_tier"] == "URGENT":
                continue
            work_order["priority_tier"] = "URGENT"
            work_order["due_at"] = calc.add_hours(
                work_order["due_at"], -calc.URGENT_DUE_PULL_IN_HOURS
            )
        else:
            if work_order["priority_tier"] != "URGENT":
                continue
            work_order["priority_tier"] = "ROUTINE"
            work_order["due_at"] = calc.add_hours(
                work_order["due_at"], calc.URGENT_DUE_PULL_IN_HOURS
            )
        # priority_tier and due_at were just written, and PRD 2.4 makes version
        # "a system-managed counter that increments by exactly 1 on every mutation
        # of the row", with no resource exempt.
        store.touch(work_order, bump_version=True)
        touched.add(work_order["sweep_id"])
    for sweep_id in touched:
        sweep = store.sweeps.get(sweep_id)
        if sweep is not None:
            recompute_sweep_counters(sweep)
            store.touch(sweep, bump_version=True)


# --- clock advance --------------------------------------------------------
def advance_clock(new_now):
    """Flip OPEN deficiencies past their correction deadline to OVERDUE."""
    store.set_logical_now(new_now)
    touched_properties = set()
    for row in store.by_seq(list(store.deficiencies.values())):
        if row["status"] != "OPEN":
            continue
        due = store.parse_instant(row.get("correction_due_at"))
        if due is None:
            continue
        if due < new_now:
            row["status"] = "OVERDUE"
            store.touch(row, bump_version=True)
            property_id = deficiency_property_id(row)
            if property_id:
                touched_properties.add(property_id)
    for property_id in touched_properties:
        prop = store.properties.get(property_id)
        if prop is not None:
            rederive_property(prop, bump_version=True)


# --- sampling ------------------------------------------------------------
def eligible_candidates(inspection):
    """PRD 3.4 step two: the candidate pool for a draw or a replacement."""
    held = set()
    for slot in inspection_selections(inspection["id"]):
        held.add(slot["unit_id"])
    pool = []
    for unit in property_units(inspection["property_id"]):
        if unit["occupancy_status"] not in ("OCCUPIED", "VACANT"):
            continue
        if unit["id"] in held:
            continue
        pool.append(unit)
    return calc.rank_candidates(pool)
