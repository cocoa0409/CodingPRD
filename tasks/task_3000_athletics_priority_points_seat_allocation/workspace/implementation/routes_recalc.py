"""Annual recalculations, the point ledger and certification (PRD 3.3, 3.4, 3.5)."""
from decimal import Decimal

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
from store import DB, by_created_at, check_version, get_path, new_row, touch

bp = Blueprint("recalculations", __name__)

OPEN_DISPUTE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")
RERUN_BLOCKING_STATUSES = ("UNDER_REVIEW", "INFO_REQUESTED")


def _disputes_on(recalc):
    return [d for d in DB.disputes.values() if d["recalculation_id"] == recalc["id"]]


@bp.post("/athletics/point-recalculations")
def create_recalculation():
    caller = auth.require(auth.OFFICE)
    body = v.body_dict()
    cycle_year = v.year_field(body, "cycle_year")
    cutoff = v.instant_field(body, "cutoff_date")
    window_end = v.instant_field(body, "dispute_window_end")
    if window_end <= cutoff:
        raise invalid("'dispute_window_end' must be strictly later than 'cutoff_date'")
    for existing in DB.recalculations.values():
        if int(existing["cycle_year"]) == cycle_year:
            raise invalid("a recalculation already exists for cycle_year %d" % cycle_year)
    row = new_row(
        cycle_year=cycle_year,
        cutoff_date=cutoff,
        dispute_window_end=window_end,
        status="DRAFT",
        initiated_by_user_id=caller.user_id,
        certified_by_user_id=None,
        donors_processed_count=0,
        communication_sent_count=0,
        certified_points_sum=Decimal("0.00"),
        certified_at=None,
    )
    DB.recalculations[row["id"]] = row
    return envelope.created(serial.recalculation(row))


@bp.get("/athletics/point-recalculations/<recalc_id>")
def get_recalculation(recalc_id):
    auth.require(auth.STAFF_ONLY)
    return envelope.ok(serial.recalculation(get_path("recalculation", recalc_id)))


# ---------------------------------------------------------------------------
# Running the cycle
# ---------------------------------------------------------------------------
def _write_ledger(donor, recalc, figures):
    points = calc.component_points(figures)
    notes = calc.basis_notes(figures)
    for entry_type in calc.LEDGER_ENTRY_TYPES:
        row = new_row(
            with_version=False,
            donor_id=donor["id"],
            recalculation_id=recalc["id"],
            entry_type=entry_type,
            variant=figures["variant"],
            points=num.round2(points[entry_type]),
            basis_note=notes[entry_type],
            computed_at=clock.now(),
        )
        DB.ledger_entries[row["id"]] = row


def _score_all(recalc):
    donors = by_created_at(list(DB.donors.values()))
    for donor in donors:
        provisional = calc.score_variant(donor, recalc, "PROVISIONAL")
        certified = calc.score_variant(donor, recalc, "CERTIFIED")
        donor["provisional_points"] = provisional["total"]
        donor["certified_base_points"] = certified["base"]
        donor["cumulative_giving_cents"] = certified["qualifying_cents"]
        donor["consecutive_giving_years"] = certified["streak"]
        donor["certified_points"] = calc.certified_points_value(donor)
        _write_ledger(donor, recalc, provisional)
        _write_ledger(donor, recalc, certified)
        touch(donor)
    recalc["donors_processed_count"] = len(donors)
    for donor in donors:
        derive.refresh_donor_eligibility(donor)
    for other in DB.recalculations.values():
        derive.recompute_recalculation_sum(other)
    return donors


@bp.post("/athletics/point-recalculations/<recalc_id>/run")
def run_recalculation(recalc_id):
    auth.require(auth.OFFICE)
    recalc = get_path("recalculation", recalc_id)
    v.body_dict()
    status = recalc["status"]
    if status not in ("DRAFT", "COMMUNICATED"):
        raise invalid_state(
            "a recalculation in '%s' may not be run" % status)
    if status == "COMMUNICATED":
        for dispute in _disputes_on(recalc):
            if dispute["status"] in RERUN_BLOCKING_STATUSES:
                raise invalid_state(
                    "a dispute on this recalculation is still in '%s'" % dispute["status"])
    _score_all(recalc)
    recalc["status"] = "COMPUTED"
    if status == "COMMUNICATED":
        recalc["communication_sent_count"] = 0
    touch(recalc)
    return envelope.ok(serial.recalculation(recalc))


@bp.post("/athletics/point-recalculations/<recalc_id>/send-communications")
def send_communications(recalc_id):
    auth.require(auth.OFFICE)
    recalc = get_path("recalculation", recalc_id)
    v.body_dict()
    if recalc["status"] != "COMPUTED":
        raise invalid_state("only a COMPUTED recalculation may be communicated")
    recalc["status"] = "COMMUNICATED"
    recalc["communication_sent_count"] = int(recalc["donors_processed_count"])
    touch(recalc)
    return envelope.ok(serial.recalculation(recalc))


# ---------------------------------------------------------------------------
# Certification and the staleness cascade (PRD section 3.5)
# ---------------------------------------------------------------------------
def _stamp_ranks():
    for position, donor in enumerate(calc.rank_pool_all(), start=1):
        donor["rank_position"] = position


def _certification_cascade():
    """Stale the slots a rank shift invalidated, then their events and requests."""
    touched_events = set()
    for slot in by_created_at(list(DB.slots.values())):
        if slot["slot_status"] != "SCHEDULED":
            continue
        donor = DB.donors.get(slot["donor_id"])
        current_rank = donor["rank_position"] if donor is not None else None
        if slot["rank_at_publish"] == current_rank:
            continue
        slot["slot_status"] = "STALE"
        touch(slot)
        touched_events.add(slot["selection_event_id"])
    newly_stale = set()
    for event_id in sorted(touched_events):
        event = DB.events.get(event_id)
        if event is None:
            continue
        derive.recompute_scheduled_slot_count(event)
        if event["status"] in ("SLOTS_PUBLISHED", "OPEN") and event["scheduled_slot_count"] == 0:
            event["status"] = "SLOTS_STALE"
            touch(event)
            newly_stale.add(event_id)
    for request in by_created_at(list(DB.requests.values())):
        if request["status"] != "AWAITING_SELECTION":
            continue
        if request["selection_event_id"] not in newly_stale:
            continue
        request["status"] = "BLOCKED"
        request["decision_note"] = (
            "blocked by the certification staleness cascade: the selection event's "
            "published slots no longer reflect the certified ranking")
        touch(request)
        donor = DB.donors.get(request["donor_id"])
        if donor is not None:
            derive.recompute_pending_request_count(donor)


@bp.post("/athletics/point-recalculations/<recalc_id>/certify")
def certify_recalculation(recalc_id):
    caller = auth.require(auth.CERTIFIER_ONLY)
    recalc = get_path("recalculation", recalc_id)
    auth.require_segregation(caller, recalc["initiated_by_user_id"],
                             "officer who initiated this recalculation")
    body = v.body_dict()
    expected = v.version_field(body, "expected_recalculation_version")
    check_version(recalc, expected, "recalculation")
    if recalc["status"] != "COMMUNICATED":
        raise invalid_state("only a COMMUNICATED recalculation may be certified")
    for dispute in _disputes_on(recalc):
        if dispute["status"] in OPEN_DISPUTE_STATUSES:
            raise invalid_state(
                "a dispute on this recalculation is still in '%s'" % dispute["status"])
    recalc["status"] = "CERTIFIED"
    recalc["certified_by_user_id"] = caller.user_id
    recalc["certified_at"] = clock.now()
    derive.recompute_recalculation_sum(recalc)
    touch(recalc)
    _stamp_ranks()
    _certification_cascade()
    return envelope.ok(serial.recalculation(recalc))


@bp.get("/athletics/point-recalculations/<recalc_id>/retention-analysis")
def retention_analysis(recalc_id):
    auth.require(auth.ANALYSIS_READERS)
    recalc = get_path("recalculation", recalc_id)
    if recalc["status"] != "CERTIFIED":
        raise err("ERR_RECALCULATION_NOT_CERTIFIED",
                  "the retention analysis is only available for a CERTIFIED recalculation")
    donors = derive.scored_donors(recalc)
    return envelope.ok(calc.retention_analysis(recalc, donors))


# ---------------------------------------------------------------------------
# The append-only point ledger
# ---------------------------------------------------------------------------
@bp.get("/athletics/point-ledger-entries")
def list_ledger_entries():
    auth.require(auth.STAFF_AND_DONOR)
    donor_id = v.q_str("donor_id")
    recalculation_id = v.q_str("recalculation_id")
    entry_type = v.q_enum("entry_type", enums.LEDGER_ENTRY_TYPES)
    variant = v.q_enum("variant", enums.LEDGER_VARIANTS)
    rows = list(DB.ledger_entries.values())
    if donor_id is not None:
        rows = [r for r in rows if r["donor_id"] == donor_id]
    if recalculation_id is not None:
        rows = [r for r in rows if r["recalculation_id"] == recalculation_id]
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    return envelope.paginated(by_created_at(rows), serial.ledger_entry)


@bp.get("/athletics/point-ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    auth.require(auth.STAFF_AND_DONOR)
    return envelope.ok(serial.ledger_entry(get_path("ledger_entry", entry_id)))
