"""Derived counters and cascades, recomputed inside the same request (PRD 2.9).

Nothing in this module advances a `version` or rewrites `updated_at`: every such
bump is named explicitly by the PRD at the transition that causes it, and the
route modules do them by hand.
"""
import num
import calc
from store import DB, by_created_at

LIVE_OCCUPANCY = ("HELD", "ASSIGNED")


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------
def section_of_seat(seat):
    return DB.sections.get(seat["section_id"])


def seat_of_assignment(assignment):
    return DB.seats.get(assignment["seat_id"])


def section_of_assignment(assignment):
    seat = seat_of_assignment(assignment)
    return section_of_seat(seat) if seat is not None else None


def section_seats(section):
    return by_created_at([s for s in DB.seats.values()
                          if s["section_id"] == section["id"]])


def section_assignments(section, statuses=LIVE_OCCUPANCY):
    seat_ids = set(s["id"] for s in DB.seats.values()
                   if s["section_id"] == section["id"])
    rows = [a for a in DB.assignments.values()
            if a["seat_id"] in seat_ids
            and (statuses is None or a["occupancy_status"] in statuses)]
    return by_created_at(rows)


def donor_assignments(donor_id, statuses=LIVE_OCCUPANCY):
    rows = [a for a in DB.assignments.values()
            if a["donor_id"] == donor_id
            and (statuses is None or a["occupancy_status"] in statuses)]
    return by_created_at(rows)


def scored_donor_ids(recalc):
    """Donors the recalculation scored, evidenced by a CERTIFIED ledger row."""
    ids = set()
    for entry in DB.ledger_entries.values():
        if entry["recalculation_id"] == recalc["id"] and entry["variant"] == "CERTIFIED":
            ids.add(entry["donor_id"])
    return ids


def scored_donors(recalc):
    ids = scored_donor_ids(recalc)
    return by_created_at([DB.donors[i] for i in ids if i in DB.donors])


# ---------------------------------------------------------------------------
# Section inventory and posture
# ---------------------------------------------------------------------------
def recompute_section(section):
    if section is None:
        return
    seats = section_seats(section)
    section["seat_row_count"] = len(seats)
    section["seats_available"] = sum(1 for s in seats if s["seat_status"] == "AVAILABLE")
    section["seats_committed_count"] = sum(
        1 for s in seats if s["seat_status"] in ("HELD", "ASSIGNED"))
    section["decommissioned_seat_count"] = sum(
        1 for s in seats if s["seat_status"] == "DECOMMISSIONED")
    live = section_assignments(section)
    section["assigned_seat_count"] = len(live)
    section["underwater_seat_count"] = sum(
        1 for a in live if a["eligibility_status"] == "UNDERWATER")
    section["pricing_posture"] = calc.pricing_posture(
        section["underwater_seat_count"],
        section["assigned_seat_count"],
        section["seats_available"])


def recompute_sections(sections):
    seen = set()
    for section in sections:
        if section is None or section["id"] in seen:
            continue
        seen.add(section["id"])
        recompute_section(section)


# ---------------------------------------------------------------------------
# Seat-assignment eligibility (judged against the donor's live figure)
# ---------------------------------------------------------------------------
def refresh_eligibility(assignment):
    if assignment["occupancy_status"] not in LIVE_OCCUPANCY:
        return False
    donor = DB.donors.get(assignment["donor_id"])
    if donor is None:
        return False
    live = num.dec(donor["certified_points"])
    required = num.dec(assignment["required_points"])
    wanted = "UNDERWATER" if live < required else "ELIGIBLE"
    if assignment["eligibility_status"] != wanted:
        assignment["eligibility_status"] = wanted
        return True
    return False


def refresh_donor_eligibility(donor):
    """Re-judge every live assignment of one donor, then its sections."""
    touched = []
    for assignment in donor_assignments(donor["id"]):
        refresh_eligibility(assignment)
        touched.append(section_of_assignment(assignment))
    recompute_sections(touched)


# ---------------------------------------------------------------------------
# Donor-level derived figures
# ---------------------------------------------------------------------------
def recompute_certified_points(donor):
    """certified_points and everything downstream of it (PRD 2.9, 3.3)."""
    donor["certified_points"] = calc.certified_points_value(donor)
    refresh_donor_eligibility(donor)
    refresh_recalculation_sums(donor)


def recompute_pending_request_count(donor):
    donor["pending_request_count"] = sum(
        1 for r in DB.requests.values()
        if r["donor_id"] == donor["id"] and r["status"] == "AWAITING_SELECTION")


def refresh_recalculation_sums(donor):
    """certified_points_sum tracks the certified_points of the donors scored."""
    for recalc in DB.recalculations.values():
        ids = scored_donor_ids(recalc)
        if donor["id"] not in ids:
            continue
        recalc["certified_points_sum"] = num.round2(sum(
            (num.dec(DB.donors[i]["certified_points"]) for i in ids if i in DB.donors),
            num.dec(0)))


def recompute_recalculation_sum(recalc):
    ids = scored_donor_ids(recalc)
    recalc["certified_points_sum"] = num.round2(sum(
        (num.dec(DB.donors[i]["certified_points"]) for i in ids if i in DB.donors),
        num.dec(0)))


# ---------------------------------------------------------------------------
# Event slot counters
# ---------------------------------------------------------------------------
def event_slots(event):
    rows = [s for s in DB.slots.values() if s["selection_event_id"] == event["id"]]
    return sorted(rows, key=lambda r: (r["slot_index"], r["_seq"]))


def recompute_scheduled_slot_count(event):
    event["scheduled_slot_count"] = sum(
        1 for s in DB.slots.values()
        if s["selection_event_id"] == event["id"] and s["slot_status"] == "SCHEDULED")
