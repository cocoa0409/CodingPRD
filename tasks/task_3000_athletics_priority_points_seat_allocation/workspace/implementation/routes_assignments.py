"""Seat assignments, the pick, the two status axes and relocations (PRD 3.8-3.9)."""
from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import enums
import num
import serial
import validation as v
from errors import err, invalid, invalid_state
from store import DB, by_created_at, check_version, get_body_ref, get_path, new_row, touch

bp = Blueprint("assignments", __name__)

DEAD_SEAT_STATUSES = ("ASSIGNED", "DECOMMISSIONED")


def _event_of_slot(slot):
    return DB.events.get(slot["selection_event_id"])


def _cycle_year_of_event(event):
    recalc = DB.recalculations.get(event["recalculation_id"]) if event else None
    return int(recalc["cycle_year"]) if recalc is not None else clock.utc_year(clock.now())


def _hold_contains(assignment, instant):
    """A hold interval is CLOSED at both ends -- the deliberate opposite of a slot."""
    return assignment["hold_start"] <= instant <= assignment["hold_end"]


def _live_holds_on_seat(seat, instant):
    return [a for a in DB.assignments.values()
            if a["seat_id"] == seat["id"]
            and a["occupancy_status"] in ("HELD", "ASSIGNED")
            and _hold_contains(a, instant)]


def _release_assignment(assignment, reason):
    """The shared release path: seat back to the pool, slot to FORFEITED."""
    was_held = assignment["occupancy_status"] == "HELD"
    assignment["occupancy_status"] = "RELEASED"
    assignment["release_reason"] = reason
    seat = derive.seat_of_assignment(assignment)
    section = derive.section_of_seat(seat) if seat is not None else None
    if seat is not None and seat["seat_status"] in ("HELD", "ASSIGNED"):
        seat["seat_status"] = "AVAILABLE"
        touch(seat)
    touch(assignment)
    if was_held:
        slot = DB.slots.get(assignment["selection_slot_id"])
        if slot is not None and slot["slot_status"] == "CONSUMED":
            slot["slot_status"] = "FORFEITED"
            touch(slot)
    if section is not None:
        derive.recompute_section(section)
        touch(section)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/athletics/seat-assignments")
def list_assignments():
    auth.require(auth.NO_ANALYST)
    donor_id = v.q_str("donor_id")
    seat_id = v.q_str("seat_id")
    slot_id = v.q_str("selection_slot_id")
    occupancy = v.q_enum("occupancy_status", enums.OCCUPANCY_STATUSES)
    payment = v.q_enum("payment_status", enums.PAYMENT_STATUSES)
    eligibility = v.q_enum("eligibility_status", enums.ELIGIBILITY_STATUSES)
    pricing_mode = v.q_enum("pricing_mode", enums.PRICING_MODES)
    rows = list(DB.assignments.values())
    if donor_id is not None:
        rows = [r for r in rows if r["donor_id"] == donor_id]
    if seat_id is not None:
        rows = [r for r in rows if r["seat_id"] == seat_id]
    if slot_id is not None:
        rows = [r for r in rows if r["selection_slot_id"] == slot_id]
    if occupancy is not None:
        rows = [r for r in rows if r["occupancy_status"] == occupancy]
    if payment is not None:
        rows = [r for r in rows if r["payment_status"] == payment]
    if eligibility is not None:
        rows = [r for r in rows if r["eligibility_status"] == eligibility]
    if pricing_mode is not None:
        rows = [r for r in rows if r["pricing_mode"] == pricing_mode]
    return envelope.paginated(by_created_at(rows), serial.assignment)


@bp.get("/athletics/seat-assignments/<assignment_id>")
def get_assignment(assignment_id):
    auth.require(auth.NO_ANALYST)
    assignment = get_path("assignment", assignment_id)
    return envelope.ok(serial.assignment(assignment))


@bp.get("/athletics/relocation-requests")
def list_requests():
    auth.require(auth.NO_ANALYST)
    donor_id = v.q_str("donor_id")
    current_id = v.q_str("current_seat_assignment_id")
    section_id = v.q_str("target_section_id")
    event_id = v.q_str("selection_event_id")
    granted_id = v.q_str("granted_seat_assignment_id")
    request_type = v.q_enum("request_type", enums.REQUEST_TYPES)
    status = v.q_enum("status", enums.REQUEST_STATUSES)
    rows = list(DB.requests.values())
    if donor_id is not None:
        rows = [r for r in rows if r["donor_id"] == donor_id]
    if current_id is not None:
        rows = [r for r in rows if r["current_seat_assignment_id"] == current_id]
    if section_id is not None:
        rows = [r for r in rows if r["target_section_id"] == section_id]
    if event_id is not None:
        rows = [r for r in rows if r["selection_event_id"] == event_id]
    if granted_id is not None:
        rows = [r for r in rows if r["granted_seat_assignment_id"] == granted_id]
    if request_type is not None:
        rows = [r for r in rows if r["request_type"] == request_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.paginated(by_created_at(rows), serial.relocation_request)


@bp.get("/athletics/relocation-requests/<request_id>")
def get_request(request_id):
    auth.require(auth.NO_ANALYST)
    row = get_path("request", request_id)
    return envelope.ok(serial.relocation_request(row))


# ---------------------------------------------------------------------------
# The pick (PRD section 3.8)
# ---------------------------------------------------------------------------
def _prior_tenure(donor_id, section, cycle_year):
    """The donor's earliest ASSIGNED row in this section from an earlier cycle."""
    seat_ids = set(s["id"] for s in DB.seats.values() if s["section_id"] == section["id"])
    candidates = [a for a in DB.assignments.values()
                  if a["donor_id"] == donor_id
                  and a["seat_id"] in seat_ids
                  and a["occupancy_status"] == "ASSIGNED"
                  and int(a["first_occupied_cycle_year"]) < int(cycle_year)]
    if not candidates:
        return None
    return sorted(candidates,
                  key=lambda a: (int(a["first_occupied_cycle_year"]),
                                 a["created_at"], a["_seq"]))[0]


def _price_row(section, donor_id, cycle_year, event_type):
    """Resolve pricing_mode, the grandfathered rate, requirement and fee."""
    prior = _prior_tenure(donor_id, section, cycle_year)
    if prior is not None:
        pricing_mode = "RENEWAL"
        first_year = int(prior["first_occupied_cycle_year"])
    else:
        pricing_mode = "MARKET"
        first_year = int(cycle_year)
    grandfathered = calc.grandfathered_rate(section, first_year)
    if grandfathered is None:
        grandfathered = int(section["per_seat_requirement_cents"])
        pricing_mode = "MARKET"
    requirement = calc.seat_requirement_cents(
        section, pricing_mode, grandfathered, cycle_year, first_year)
    fee = calc.handling_fee_cents(requirement, event_type)
    return {
        "pricing_mode": pricing_mode,
        "first_occupied_cycle_year": first_year,
        "grandfathered_requirement_cents": grandfathered,
        "requirement_cents": requirement,
        "handling_fee_cents": fee,
        "total_due_cents": requirement + fee,
    }


@bp.post("/athletics/selection-slots/<slot_id>/pick")
def pick_seat(slot_id):
    caller = auth.require(auth.DONOR_ONLY)
    slot = get_path("slot", slot_id)
    auth.require_owner(caller, slot["donor_id"])
    body = v.body_dict()
    seat_id = v.id_field(body, "seat_id")
    expected = v.version_field(body, "expected_seat_version")
    seat = get_body_ref("seat", seat_id)
    check_version(seat, expected, "seat")
    event = _event_of_slot(slot)
    if slot["slot_status"] != "SCHEDULED":
        if slot["slot_status"] == "STALE" and event is not None \
                and event["status"] == "SLOTS_STALE":
            raise err("ERR_EVENT_SLOTS_STALE",
                      "this slot went stale when the ranking shifted; the event "
                      "must republish its slots")
        raise invalid_state("only a SCHEDULED slot may be consumed by a pick")
    section = derive.section_of_seat(seat)
    if section is None or section["status"] != "OPEN":
        raise err("ERR_SECTION_UNDER_RENOVATION",
                  "the section holding this seat is not OPEN for picks")
    if event is None or event["status"] != "OPEN":
        if event is not None and event["status"] == "SLOTS_STALE":
            raise err("ERR_EVENT_SLOTS_STALE",
                      "the selection event's published slots are stale")
        raise invalid_state("the selection event is not OPEN for picks")
    now = clock.now()
    if not (slot["slot_start"] <= now < slot["slot_end"]):
        raise err("ERR_OUTSIDE_SLOT_WINDOW",
                  "the current instant lies outside this slot's half-open window")
    if seat["seat_status"] in DEAD_SEAT_STATUSES:
        raise err("ERR_SEAT_NOT_AVAILABLE",
                  "seat '%s' is %s" % (seat["id"], seat["seat_status"]))
    if len(_live_holds_on_seat(seat, now)) >= int(seat["max_concurrent_holds"]):
        raise err("ERR_SEAT_HOLD_CONFLICT",
                  "this seat already carries its maximum concurrent holds")
    donor = DB.donors.get(slot["donor_id"])
    if donor is None:
        raise err("ERR_DONOR_NOT_FOUND", "the slot's donor no longer exists")
    if num.dec(donor["certified_points"]) < num.dec(section["required_points_per_seat"]):
        raise err("ERR_SEAT_POINTS_SHORTFALL",
                  "the donor's certified_points are below the section's requirement")
    # An expired earlier hold is superseded; the seat stays HELD for the newcomer.
    for prior in by_created_at([a for a in DB.assignments.values()
                                if a["seat_id"] == seat["id"]
                                and a["occupancy_status"] == "HELD"
                                and a["hold_end"] < now]):
        prior["occupancy_status"] = "RELEASED"
        prior["release_reason"] = "SUPERSEDED_BY_NEW_HOLD"
        touch(prior)
    cycle_year = _cycle_year_of_event(event)
    pricing = _price_row(section, donor["id"], cycle_year, event["event_type"])
    row = new_row(
        seat_id=seat["id"],
        donor_id=donor["id"],
        selection_slot_id=slot["id"],
        occupancy_status="HELD",
        payment_status="UNBILLED",
        hold_start=now,
        hold_end=clock.plus_minutes(now, calc.HOLD_MINUTES),
        amount_paid_cents=0,
        required_points=num.round2(section["required_points_per_seat"]),
        points_at_pick=num.round2(donor["certified_points"]),
        eligibility_status="ELIGIBLE",
        release_reason="NONE",
        **pricing
    )
    DB.assignments[row["id"]] = row
    slot["slot_status"] = "CONSUMED"
    touch(slot)
    if seat["seat_status"] == "AVAILABLE":
        seat["seat_status"] = "HELD"
    touch(seat)
    derive.recompute_section(section)
    touch(section)
    derive.recompute_scheduled_slot_count(event)
    return envelope.created(serial.assignment(row))


# ---------------------------------------------------------------------------
# The occupancy axis
# ---------------------------------------------------------------------------
def _grant_matching_request(assignment, section):
    """A confirmed hold satisfies the donor's outstanding move into this section."""
    for request in by_created_at(list(DB.requests.values())):
        if request["status"] != "AWAITING_SELECTION":
            continue
        if request["donor_id"] != assignment["donor_id"]:
            continue
        if request["target_section_id"] != section["id"]:
            continue
        request["status"] = "GRANTED"
        request["granted_seat_assignment_id"] = assignment["id"]
        touch(request)
        donor = DB.donors.get(request["donor_id"])
        if donor is not None:
            derive.recompute_pending_request_count(donor)
        return


@bp.post("/athletics/seat-assignments/<assignment_id>/occupancy")
def change_occupancy(assignment_id):
    auth.require(auth.OFFICE)
    assignment = get_path("assignment", assignment_id)
    body = v.body_dict()
    to_status = v.enum_field(body, "to_status", enums.OCCUPANCY_STATUSES)
    reason = v.enum_field(body, "release_reason", enums.RELEASE_REASONS, required=False)
    expected = v.version_field(body, "expected_seat_assignment_version")
    check_version(assignment, expected, "seat assignment")
    current = assignment["occupancy_status"]
    if to_status == "ASSIGNED":
        if current != "HELD":
            raise invalid_state("only a HELD assignment may be confirmed as ASSIGNED")
        if int(assignment["amount_paid_cents"]) < int(assignment["total_due_cents"]):
            raise err("ERR_SEAT_DONATION_SHORTFALL",
                      "amount_paid_cents does not yet cover total_due_cents")
        if assignment["eligibility_status"] != "ELIGIBLE":
            raise invalid_state("an UNDERWATER assignment may not be confirmed")
        assignment["occupancy_status"] = "ASSIGNED"
        seat = derive.seat_of_assignment(assignment)
        section = derive.section_of_seat(seat) if seat is not None else None
        if seat is not None:
            seat["seat_status"] = "ASSIGNED"
            touch(seat)
        touch(assignment)
        if section is not None:
            derive.recompute_section(section)
            _grant_matching_request(assignment, section)
    elif to_status == "RELEASED":
        if current not in ("HELD", "ASSIGNED"):
            raise invalid_state("only a HELD or ASSIGNED assignment may be released")
        _release_assignment(assignment, reason or "DONOR_RELEASE")
    else:
        raise invalid_state("an assignment may only move to ASSIGNED or RELEASED")
    return envelope.ok(serial.assignment(assignment))


# ---------------------------------------------------------------------------
# The payment axis
# ---------------------------------------------------------------------------
@bp.post("/athletics/seat-assignments/<assignment_id>/billing")
def change_billing(assignment_id):
    caller = auth.require(auth.OFFICE)
    assignment = get_path("assignment", assignment_id)
    body = v.body_dict()
    to_status = v.enum_field(body, "to_status", enums.PAYMENT_STATUSES)
    amount = v.int_field(body, "amount_cents", required=False, minimum=0)
    current = assignment["payment_status"]
    if to_status == "INVOICED":
        if current != "UNBILLED":
            raise invalid_state("only an UNBILLED assignment may be invoiced")
        assignment["payment_status"] = "INVOICED"
    elif to_status == "PAID":
        if current not in ("INVOICED", "DELINQUENT"):
            raise invalid_state("only an INVOICED or DELINQUENT assignment may be paid")
        if amount is None or amount < int(assignment["total_due_cents"]):
            raise err("ERR_SEAT_DONATION_SHORTFALL",
                      "the tendered amount_cents does not cover total_due_cents")
        assignment["payment_status"] = "PAID"
        assignment["amount_paid_cents"] = amount
    elif to_status == "DELINQUENT":
        if current != "INVOICED":
            raise invalid_state("only an INVOICED assignment may be marked delinquent")
        assignment["payment_status"] = "DELINQUENT"
    elif to_status == "WRITTEN_OFF":
        if caller.role != auth.PLATFORM_ADMIN:
            raise err("ERR_FORBIDDEN_ROLE",
                      "only a PlatformAdmin may write an assignment off")
        if current != "DELINQUENT":
            raise invalid_state("only a DELINQUENT assignment may be written off")
        assignment["payment_status"] = "WRITTEN_OFF"
    else:
        raise invalid_state("an assignment may not be moved back to UNBILLED")
    touch(assignment)
    return envelope.ok(serial.assignment(assignment))


# ---------------------------------------------------------------------------
# Relocation and upgrade requests (PRD section 3.9)
# ---------------------------------------------------------------------------
@bp.post("/athletics/relocation-requests")
def create_relocation_request():
    caller = auth.require(auth.DONOR_AND_OFFICER)
    body = v.body_dict()
    claimed_owner = body.get("donor_id") if isinstance(body, dict) else None
    if caller.is_donor and isinstance(claimed_owner, str) and claimed_owner != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "a donor may only file a relocation request for themselves")
    donor_id = v.id_field(body, "donor_id")
    current_id = v.id_field(body, "current_seat_assignment_id")
    target_section_id = v.id_field(body, "target_section_id")
    event_id = v.id_field(body, "selection_event_id")
    request_type = v.enum_field(body, "request_type", enums.REQUEST_TYPES)
    expected = v.version_field(body, "expected_donor_version")
    donor = get_body_ref("donor", donor_id)
    current = get_body_ref("assignment", current_id)
    target_section = get_body_ref("section", target_section_id)
    event = get_body_ref("event", event_id)
    check_version(donor, expected, "donor")
    if event["status"] not in ("SLOTS_PUBLISHED", "OPEN"):
        raise err("ERR_EVENT_NOT_OPEN_FOR_REQUESTS",
                  "the named selection event is %s and takes no requests"
                  % event["status"])
    if int(current["amount_paid_cents"]) < int(current["total_due_cents"]):
        raise err("ERR_SEAT_DONATION_SHORTFALL",
                  "the donor's current assignment is not fully paid")
    for prior in by_created_at(list(DB.requests.values())):
        if prior["donor_id"] != donor["id"] or prior["status"] != "AWAITING_SELECTION":
            continue
        prior["status"] = "SUPERSEDED"
        prior["decision_note"] = (
            "superseded by a newer relocation request from the same donor")
        touch(prior)
    row = new_row(
        donor_id=donor["id"],
        current_seat_assignment_id=current["id"],
        target_section_id=target_section["id"],
        selection_event_id=event["id"],
        request_type=request_type,
        status="AWAITING_SELECTION",
        granted_seat_assignment_id=None,
        decision_note=None,
    )
    DB.requests[row["id"]] = row
    derive.recompute_pending_request_count(donor)
    touch(donor)
    return envelope.created(serial.relocation_request(row))


@bp.post("/athletics/relocation-requests/<request_id>/decide")
def decide_relocation_request(request_id):
    auth.require(auth.OFFICE)
    request = get_path("request", request_id)
    body = v.body_dict()
    decision = v.enum_field(body, "decision", enums.RELOCATION_DECISIONS)
    target_seat_id = v.id_field(body, "target_seat_id", required=False)
    note = v.str_field(body, "decision_note", required=False, max_len=None)
    target_seat = get_body_ref("seat", target_seat_id) if target_seat_id else None
    donor = DB.donors.get(request["donor_id"])
    if decision == "DENY":
        if request["status"] not in ("AWAITING_SELECTION", "BLOCKED"):
            raise invalid_state(
                "only an AWAITING_SELECTION or BLOCKED request may be denied")
        request["status"] = "DENIED"
        request["decision_note"] = note
        touch(request)
        if donor is not None:
            derive.recompute_pending_request_count(donor)
        return envelope.ok(serial.relocation_request(request))
    if request["status"] != "AWAITING_SELECTION":
        raise invalid_state("only an AWAITING_SELECTION request may be granted")
    section = DB.sections.get(request["target_section_id"])
    if section is None or section["status"] != "OPEN":
        raise err("ERR_SECTION_UNDER_RENOVATION",
                  "the target section is not OPEN")
    if target_seat is not None and target_seat["seat_status"] in DEAD_SEAT_STATUSES:
        raise err("ERR_SEAT_NOT_AVAILABLE",
                  "the target seat is %s" % target_seat["seat_status"])
    if target_seat is None or target_seat["section_id"] != section["id"]:
        raise err("ERR_RELOCATION_TARGET_INVALID",
                  "'target_seat_id' must name a seat in the request's target section")
    if donor is None:
        raise err("ERR_DONOR_NOT_FOUND", "the requesting donor no longer exists")
    if num.dec(donor["certified_points"]) < num.dec(section["required_points_per_seat"]):
        raise err("ERR_SEAT_POINTS_SHORTFALL",
                  "the donor's certified_points are below the target requirement")
    event = DB.events.get(request["selection_event_id"])
    cycle_year = _cycle_year_of_event(event)
    grandfathered = calc.grandfathered_rate(section, cycle_year)
    if grandfathered is None:
        grandfathered = int(section["per_seat_requirement_cents"])
    requirement = int(section["per_seat_requirement_cents"])
    now = clock.now()
    row = new_row(
        seat_id=target_seat["id"],
        donor_id=donor["id"],
        selection_slot_id=None,
        occupancy_status="HELD",
        payment_status="UNBILLED",
        hold_start=now,
        hold_end=clock.plus_minutes(now, calc.HOLD_MINUTES),
        first_occupied_cycle_year=cycle_year,
        pricing_mode="MARKET",
        grandfathered_requirement_cents=grandfathered,
        requirement_cents=requirement,
        handling_fee_cents=0,
        total_due_cents=requirement,
        amount_paid_cents=0,
        required_points=num.round2(section["required_points_per_seat"]),
        points_at_pick=num.round2(donor["certified_points"]),
        eligibility_status="ELIGIBLE",
        release_reason="NONE",
    )
    DB.assignments[row["id"]] = row
    if target_seat["seat_status"] == "AVAILABLE":
        target_seat["seat_status"] = "HELD"
    touch(target_seat)
    derive.recompute_section(section)
    touch(section)
    old = DB.assignments.get(request["current_seat_assignment_id"])
    if old is not None and old["occupancy_status"] in ("HELD", "ASSIGNED"):
        _release_assignment(old, "DONOR_RELEASE")
    request["status"] = "GRANTED"
    request["granted_seat_assignment_id"] = row["id"]
    request["decision_note"] = note
    touch(request)
    derive.recompute_pending_request_count(donor)
    return envelope.ok(serial.relocation_request(request))
