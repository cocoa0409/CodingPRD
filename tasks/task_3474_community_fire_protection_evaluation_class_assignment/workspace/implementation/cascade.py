"""Data windows, scoring gates, and cascade side effects (PRD §2.8, §2.10)."""
from decimal import Decimal

import db
from db import STORE, touch
from errors import fail
from scoring import MODIFIER_TABLE, compute_scores
from util import parse_date, add_calendar_months

DATA_WINDOW_STATES = ("DATA_COLLECTION", "FIELD_VERIFICATION", "SCORING")


def window_or_fail(community_id, allowed_states):
    """PRD §2.8: the community's non-terminal cycle must be in an accepting state."""
    cycle = db.active_cycle_of_community(community_id)
    if cycle is None or cycle["status"] not in allowed_states:
        fail("ERR_DATA_WINDOW_CLOSED", "the community's data window is not open for this operation")
    return cycle


def scoring_gate_ok(community_id):
    """FIELD_VERIFICATION -> SCORING gate (PRD §3.2), re-checked at sheet create."""
    community = STORE["communities"][community_id]
    dept = db.dept_of_community(community_id)
    system = db.system_of_community(community_id)
    pending = any(
        ft for ft in STORE["flow_tests"].values()
        if ft["system_id"] == system["id"] and ft["status"] in ("SUBMITTED", "WITNESSED")
    )
    return (not pending) and community["comms_attested"] and dept["data_submitted"]


def sheet_values(cycle):
    community = STORE["communities"][cycle["community_id"]]
    dept = db.dept_of_community(cycle["community_id"])
    system = db.system_of_community(cycle["community_id"])
    apparatus = [a for a in db.all_of("apparatus") if a["department_id"] == dept["id"]]
    hydrants = [h for h in db.all_of("hydrants") if h["system_id"] == system["id"]]
    credits = [c for c in db.all_of("credits") if c["cycle_id"] == cycle["id"]]
    return compute_scores(community, dept, apparatus, system, hydrants, credits, cycle)


def recompute_draft_if_scoring(community_id):
    """PRD §2.8/§3.6: an accepted scored-input change while the cycle is in
    SCORING recomputes the cycle's DRAFT score sheet in place."""
    cycle = db.active_cycle_of_community(community_id)
    if not cycle or cycle["status"] != "SCORING":
        return
    sheet = next(
        (s for s in db.all_of("sheets") if s["cycle_id"] == cycle["id"] and s["status"] == "DRAFT"),
        None,
    )
    if not sheet:
        return
    sheet.update(sheet_values(cycle))
    touch(sheet)


def recompute_hydrant(hydrant):
    """Hydrant certified values come from its latest CERTIFIED non-SUPERSEDED test."""
    tests = [
        t for t in db.all_of("flow_tests")
        if t["hydrant_id"] == hydrant["id"] and t["status"] == "CERTIFIED"
    ]
    if not tests:
        hydrant["max_flow_gpm"] = None
        hydrant["last_certified_test_date"] = None
    else:
        latest = max(tests, key=lambda t: (t["test_date"], t["_seq"]))
        hydrant["max_flow_gpm"] = latest["flow_at_20psi_gpm"]
        hydrant["last_certified_test_date"] = latest["test_date"]


def recompute_system_aggregates(system):
    """Aggregates over ACTIVE hydrants holding a certified flow test (PRD §3.4)."""
    total = 0
    count = 0
    for h in db.all_of("hydrants"):
        if h["system_id"] == system["id"] and h["status"] == "ACTIVE" and h["max_flow_gpm"] is not None:
            total += h["max_flow_gpm"]
            if h["max_flow_gpm"] >= 1000:
                count += 1
    system["active_certified_flow_gpm"] = total
    system["creditworthy_hydrant_count"] = count
    touch(system)


def apply_classification(prop, classification):
    """applicable_class_for_property (PRD §3.8); boundaries inclusive toward base."""
    if Decimal(str(prop["distance_to_nearest_station_road_miles"])) > Decimal("5.0"):
        cls = 10
    elif prop["distance_to_nearest_hydrant_ft"] > 1000:
        cls = classification["split_class_beyond_hydrant"]
    else:
        cls = classification["base_class"]
    prop["applicable_class"] = cls
    prop["applicable_premium_modifier"] = MODIFIER_TABLE[cls]


def activate_classification(classification, effective_from_str):
    """PRD §3.7 activation cascade; every touched resource is genuinely mutated."""
    community = STORE["communities"][classification["community_id"]]

    for other in db.all_of("classifications"):
        if (other["community_id"] == community["id"] and other["status"] == "EFFECTIVE"
                and other["id"] != classification["id"]):
            other["status"] = "SUPERSEDED"
            other["effective_until"] = effective_from_str
            touch(other)

    classification["status"] = "EFFECTIVE"
    classification["effective_from"] = effective_from_str
    touch(classification)

    community["status"] = "CLASSIFIED"
    community["current_class_number"] = classification["base_class"]
    community["current_split_class"] = classification["split_class_beyond_hydrant"]
    community["current_premium_modifier"] = classification["premium_modifier"]
    community["next_evaluation_due_date"] = add_calendar_months(
        parse_date(effective_from_str), 60).isoformat()
    touch(community)

    for prop in db.all_of("properties"):
        if prop["community_id"] != community["id"]:
            continue
        apply_classification(prop, classification)
        touch(prop)
        for quote in db.all_of("quotes"):
            if quote["property_id"] == prop["id"] and quote["status"] == "QUOTED":
                quote["status"] = "EXPIRED"
                touch(quote)

    cycle = STORE["cycles"][classification["cycle_id"]]
    cycle["status"] = "EFFECTIVE"
    touch(cycle)
