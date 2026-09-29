"""Conserved ledgers (PRD 2.9), the project roll-ups (PRD 3.7) and the three cascades.

Every helper here mutates records in place. A helper never invents a version
bump the PRD does not call for: the caller owns `touch()` unless the bump is
part of a cascade hop this module performs itself.
"""

from decimal import Decimal

import calc
from store import D, db, now, ordered, r2, touch

PRICED_INSTALL_STATES = ("TERMINATED", "TESTED_PASS", "TESTED_FAIL", "CERTIFIED")
REVERTIBLE_INSTALL_STATES = ("PULLED", "TERMINATED", "TESTED_PASS", "TESTED_FAIL",
                             "CERTIFIED")


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------
def by_field(collection, field, value):
    return [r for r in collection.values() if r.get(field) == value]


def project_links(project_id):
    return ordered(by_field(db.links, "project_id", project_id))


def project_registrations(project_id):
    return ordered(by_field(db.registrations, "project_id", project_id))


def project_tickets(project_id):
    return ordered(by_field(db.tickets, "project_id", project_id))


def project_coordinations(project_id):
    return ordered(by_field(db.coordinations, "project_id", project_id))


def segment_routes(segment_id):
    return ordered(by_field(db.routes, "pathway_segment_id", segment_id))


def link_routes(link_id):
    return ordered(by_field(db.routes, "link_id", link_id))


def link_test_results(link_id):
    return ordered(by_field(db.test_results, "link_id", link_id))


def latest_test_result(link_id):
    """The result with the greatest recorded_at, ties broken by insertion order."""
    results = link_test_results(link_id)
    if not results:
        return None
    best = results[0]
    for result in results[1:]:
        if result["recorded_at"] >= best["recorded_at"]:
            best = result
    return best


# --------------------------------------------------------------------------
# PRD 2.9 — pathway fill ledger
# --------------------------------------------------------------------------
def recompute_segment_fill(segment):
    """fill_area_used_sq_mm is always the sum over the currently OCCUPYING routes."""
    occupying = [r for r in segment_routes(segment["id"])
                 if r["route_state"] == "OCCUPYING"]
    total = Decimal("0")
    for route in occupying:
        total = total + D(route["consumed_area_sq_mm"])
    segment["occupying_route_count"] = len(occupying)
    segment["fill_area_used_sq_mm"] = r2(total)
    segment["allowed_fill_pct"] = calc.segment_allowed_fill_pct(segment)
    segment["fill_ratio"] = calc.fill_ratio(segment["fill_area_used_sq_mm"],
                                            segment["usable_area_sq_mm"])
    return segment


def recompute_link_routed_count(link):
    link["routed_segment_count"] = len(
        [r for r in link_routes(link["id"]) if r["route_state"] == "OCCUPYING"])
    return link


# --------------------------------------------------------------------------
# PRD 2.9 / 3.2 — rack and room ledgers
# --------------------------------------------------------------------------
def recompute_rack_ledger(rack):
    active = [a for a in by_field(db.assignments, "rack_id", rack["id"])
              if a["assignment_state"] == "ACTIVE"]
    rack["occupied_ru"] = sum(a["span_ru"] for a in active)
    rack["available_ru"] = rack["total_ru"] - rack["occupied_ru"]
    rack["power_draw_va"] = sum(a["power_va"] for a in active)
    return rack


def recompute_room_power(room):
    racks = by_field(db.racks, "telecom_room_id", room["id"])
    room["power_load_va"] = sum(r["power_draw_va"] for r in racks)
    room["power_headroom_va"] = room["ups_capacity_va"] - room["power_load_va"]
    return room


# --------------------------------------------------------------------------
# PRD 3.3 — the pathway tree
# --------------------------------------------------------------------------
def segment_depth(segment):
    """Hops walked up the upstream chain before reaching a root."""
    depth = 0
    cursor = segment
    seen = set()
    while cursor is not None and cursor.get("upstream_segment_id"):
        if cursor["id"] in seen:
            break
        seen.add(cursor["id"])
        cursor = db.segments.get(cursor["upstream_segment_id"])
        depth += 1
        if depth > 64:
            break
    return depth


def upstream_chain_ids(start_segment):
    """Ids visited walking upstream from (and including) start_segment."""
    ids = []
    cursor = start_segment
    while cursor is not None:
        if cursor["id"] in ids:
            break
        ids.append(cursor["id"])
        parent_id = cursor.get("upstream_segment_id")
        cursor = db.segments.get(parent_id) if parent_id else None
    return ids


def recompute_descendant_depths(segment):
    """Breadth-first renumbering outwards from the moved segment (PRD 3.3)."""
    frontier = [segment]
    touched = []
    while frontier:
        nxt = []
        for parent in frontier:
            children = [s for s in ordered(db.segments.values())
                        if s.get("upstream_segment_id") == parent["id"]]
            for child in children:
                new_depth = parent["pathway_depth"] + 1
                if child["pathway_depth"] != new_depth:
                    child["pathway_depth"] = new_depth
                    touched.append(child)
                nxt.append(child)
        frontier = nxt
    for child in touched:
        touch(child)
    return touched


# --------------------------------------------------------------------------
# PRD 3.7 — the project roll-ups
# --------------------------------------------------------------------------
def recompute_project_rollups(project):
    """total/certified/failed counts, both completeness variants, as-built cost."""
    links = project_links(project["id"])
    total = len(links)
    certified = len([l for l in links if l["install_state"] == "CERTIFIED"])
    failed = len([l for l in links if l["install_state"] == "TESTED_FAIL"])
    tested_pass = len([l for l in links if l["install_state"] == "TESTED_PASS"])
    project["total_link_count"] = total
    project["certified_link_count"] = certified
    project["failed_link_count"] = failed
    project["completeness_pct_strict"] = calc.completeness_pct(certified, total)
    project["completeness_pct_provisional"] = calc.completeness_pct(
        certified + tested_pass, total)
    cost = 0
    for link in links:
        cable_type = db.cable_types.get(link["cable_type_id"])
        if cable_type is None:
            continue
        material = calc.material_cost_cents(cable_type["cost_per_meter_cents"],
                                            link["channel_length_m"])
        link["material_cost_cents"] = material
        if link["install_state"] in PRICED_INSTALL_STATES:
            cost += material + calc.LINK_LABOR_CENTS
    project["as_built_cost_cents"] = cost
    return project


def recompute_consumed_mac_cents(project):
    """The reconciled MAC ledger of PRD 2.9 / 3.8."""
    total = 0
    for ticket in project_tickets(project["id"]):
        if ticket["ticket_state"] in ("SCHEDULED", "IN_PROGRESS"):
            total += ticket["estimated_billed_cents"] or 0
        elif ticket["ticket_state"] == "COMPLETED":
            total += ticket["final_billed_cents"] or 0
    project["consumed_mac_cents"] = total
    return project


def is_eligible(project):
    return (D(project["completeness_pct_strict"]) >= calc.WARRANTY_ELIGIBLE_PCT
            and project["total_link_count"] >= 1)


def promote_draft_registrations(project):
    """Cascade A hop 4: DRAFT -> READY pinned to the project's post-bump version."""
    for registration in project_registrations(project["id"]):
        if registration["registration_state"] == "DRAFT":
            registration["registration_state"] = "READY"
            registration["pinned_project_version"] = project["version"]
            touch(registration)


def demote_ready_registrations(project):
    for registration in project_registrations(project["id"]):
        if registration["registration_state"] == "READY":
            registration["registration_state"] = "DRAFT"
            registration["pinned_project_version"] = None
            touch(registration)


def revoke_registered_registrations(project):
    for registration in project_registrations(project["id"]):
        if registration["registration_state"] == "REGISTERED":
            registration["registration_state"] = "REVOKED"
            touch(registration)


def apply_warranty_consequence(project, allow_revoke=False):
    """PRD 3.7 eligibility edges; the REGISTERED -> REVOKED edge only in Cascades B and C.

    Must be called AFTER the project's own version bump so that a promotion pins
    the post-bump version, exactly as Cascade A hop 4 requires.
    """
    status = project["warranty_status"]
    if is_eligible(project):
        if status == "NOT_ELIGIBLE":
            project["warranty_status"] = "ELIGIBLE"
            promote_draft_registrations(project)
        return
    if status == "ELIGIBLE":
        project["warranty_status"] = "NOT_ELIGIBLE"
        demote_ready_registrations(project)
    elif status == "REGISTERED" and allow_revoke:
        project["warranty_status"] = "REVOKED"
        revoke_registered_registrations(project)


def recompute_warranty_status_from_scratch(project):
    """PRD 3.9 reopen: warranty_status recomputed against completeness_pct_strict."""
    project["warranty_status"] = "ELIGIBLE" if is_eligible(project) else "NOT_ELIGIBLE"
    return project


def refresh_project(project, allow_revoke=False):
    """Recompute the roll-ups, bump the project once, then apply the warranty edge."""
    recompute_project_rollups(project)
    touch(project)
    apply_warranty_consequence(project, allow_revoke=allow_revoke)
    return project


# --------------------------------------------------------------------------
# PRD 3.3 — Cascade B, condemnation of a pathway segment
# --------------------------------------------------------------------------
def cascade_b_condemn(segment, condemned_reason):
    # Hop 1
    segment["pathway_state"] = "CONDEMNED"
    segment["condemned_reason"] = condemned_reason

    # Hop 2 — caused by hop 1
    affected_link_ids = []
    for route in segment_routes(segment["id"]):
        if route["route_state"] == "OCCUPYING":
            route["route_state"] = "SUSPENDED"
            touch(route)
            if route["link_id"] not in affected_link_ids:
                affected_link_ids.append(route["link_id"])
    recompute_segment_fill(segment)
    touch(segment)

    # Hop 3 — caused by hop 2
    projects = []
    for link_id in affected_link_ids:
        link = db.links.get(link_id)
        if link is None:
            continue
        recompute_link_routed_count(link)
        if link["install_state"] in REVERTIBLE_INSTALL_STATES:
            link["install_state"] = "DESIGNED"
            link["record_state"] = "UNLABELED"
            link["applied_identifier"] = None
            link["installer_user_id"] = None
            link["certifier_user_id"] = None
        touch(link)
        if link["project_id"] not in projects:
            projects.append(link["project_id"])

    # Hop 4 — caused by hop 3
    project = db.projects.get(segment["project_id"])
    if project is not None:
        refresh_project(project, allow_revoke=True)
    for project_id in projects:
        if project_id != segment["project_id"]:
            other = db.projects.get(project_id)
            if other is not None:
                refresh_project(other, allow_revoke=True)
    return segment
