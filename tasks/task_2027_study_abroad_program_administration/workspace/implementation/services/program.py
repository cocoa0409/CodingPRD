"""Program helpers: seats_taken aggregation, schedule buffer check, travel gate."""

from datetime import timedelta
import db
from utils import parse_dt
from errors import ApiError, ERR_PROGRAM_SCHEDULE_BUFFER


def recompute_seats(program):
    """seats_taken_aggregation: count applications in {COMMITTED, ABROAD}."""
    count = sum(
        1
        for a in db.applications.values()
        if a["program_id"] == program["id"] and a["status"] in ("COMMITTED", "ABROAD")
    )
    program["seats_taken"] = count


def check_schedule_buffer(host_institution, start_date, end_date, exclude_program_id=None):
    """Reject if another DRAFT/OPEN program at same host_institution is separated by < 7 days.

    Separation < 7 days in either direction -> ERR_PROGRAM_SCHEDULE_BUFFER; exactly 7 days allowed.
    SUSPENDED programs do not participate.
    """
    new_start = parse_dt(start_date, "start_date")
    new_end = parse_dt(end_date, "end_date")
    seven_days = timedelta(days=7)

    for p in db.programs.values():
        if p["id"] == exclude_program_id:
            continue
        if p["host_institution"] != host_institution:
            continue
        if p["status"] not in ("DRAFT", "OPEN"):
            continue
        p_start = parse_dt(p["start_date"], "start_date")
        p_end = parse_dt(p["end_date"], "end_date")

        # gap between intervals in either direction:
        # gap_after = new_start - p_end  (positive if new starts after existing ends)
        # gap_before = p_start - new_end (positive if new ends before existing starts)
        gap_after = (new_start - p_end)
        gap_before = (p_start - new_end)

        # If intervals overlap, both gaps are negative -> separation is 0 < 7 days -> reject
        # If new starts exactly 7 days after p ends, gap_after == 7 days -> allowed
        # If new ends exactly 7 days before p starts, gap_before == 7 days -> allowed
        if gap_after >= seven_days or gap_before >= seven_days:
            continue
        # otherwise separation < 7 days (including overlap)
        raise ApiError(
            ERR_PROGRAM_SCHEDULE_BUFFER,
            "Another program at the same host_institution is separated by fewer than 7 days",
            409,
        )


def active_blocking_advisory(country_code, clock_dt, prog_start, prog_end):
    """Travel-warning gate: return True if an ACTIVE DO_NOT_TRAVEL advisory for country_code
    is in effect at clock_dt and overlaps [prog_start, prog_end]."""
    for adv in db.travel_advisories.values():
        if adv["country_code"] != country_code:
            continue
        if adv["level"] != "DO_NOT_TRAVEL":
            continue
        if adv["status"] != "ACTIVE":
            continue
        af = parse_dt(adv["effective_from"], "effective_from")
        at = parse_dt(adv["effective_to"], "effective_to")
        # in effect at the logical clock: effective_from <= clock < effective_to
        if not (af <= clock_dt < at):
            continue
        # window overlapping [start, end]: af <= end AND at >= start
        if af <= prog_end and at >= prog_start:
            return True
    return False
