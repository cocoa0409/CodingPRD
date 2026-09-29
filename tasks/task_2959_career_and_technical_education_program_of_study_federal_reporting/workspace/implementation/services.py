"""Lazy clock-driven transitions, evidence lookups and the two cascade chains."""
import calc
from store import (CAPITAL_REVIEW_WINDOW_DAYS, CLNA_STAKEHOLDER_MEETINGS_MIN,
                   add_days, clock_date, clock_instant, db, parse_date,
                   parse_instant, touch)

FILED_MINUTES = ("FINALIZED", "AMENDED")


# ------------------------------------------------------------- lazy re-evaluation
def refresh_clna(program):
    """CERTIFIED -> EXPIRED once the clock's date is strictly past clna_expires_on.
    Runs as the first step of the affected request (PRD sec 2.12)."""
    if program["clna_phase"] != "CERTIFIED":
        return program
    expires = parse_date(program["clna_expires_on"])
    if expires is None or clock_date() <= expires:
        return program
    program["clna_phase"] = "EXPIRED"
    touch(program)
    return program


def refresh_educator(educator):
    """PROVISIONAL/ELIGIBLE -> LAPSED once the clock passes credential_expires_on."""
    if educator["status"] == "LAPSED":
        return educator
    expires = parse_date(educator["credential_expires_on"])
    if expires is None or clock_date() <= expires:
        return educator
    educator["status"] = "LAPSED"
    touch(educator)
    return educator


def refresh_program_educators(pos_id):
    for educator in list(db.educators.values()):
        if educator["pos_id"] == pos_id:
            refresh_educator(educator)


# ------------------------------------------------------------- lookups
def program_committees(pos_id):
    rows = [c for c in db.committees.values() if c["pos_id"] == pos_id]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def active_committee(pos_id):
    """Only the newest committee is the program's ACTIVE one (PRD sec 3.3)."""
    newest = None
    for committee in program_committees(pos_id):
        if committee["status"] == "ACTIVE":
            newest = committee
    return newest


def committee_meetings(committee_id):
    rows = [m for m in db.meetings.values() if m["committee_id"] == committee_id]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def clna_stakeholder_evidence(pos_id):
    committee = active_committee(pos_id)
    if committee is None:
        return False
    qualifying = 0
    for meeting in committee_meetings(committee["id"]):
        if meeting["agenda_kind"] != "CLNA_STAKEHOLDER":
            continue
        if meeting["minutes_status"] not in FILED_MINUTES:
            continue
        if not meeting["quorum_met"]:
            continue
        qualifying += 1
    return qualifying >= CLNA_STAKEHOLDER_MEETINGS_MIN


def endorsement_on_file(pos_id):
    committee = active_committee(pos_id)
    if committee is None:
        return False
    for meeting in committee_meetings(committee["id"]):
        if meeting["agenda_kind"] != "POS_ENDORSEMENT":
            continue
        if meeting["minutes_status"] not in FILED_MINUTES:
            continue
        if meeting["endorsement_passed"]:
            return True
    return False


def capital_review_on_file(pos_id):
    committee = active_committee(pos_id)
    if committee is None:
        return False
    horizon = clock_instant()
    for meeting in committee_meetings(committee["id"]):
        if meeting["agenda_kind"] != "EQUIPMENT_REVIEW":
            continue
        if meeting["minutes_status"] not in FILED_MINUTES:
            continue
        if not meeting["quorum_met"]:
            continue
        held = parse_instant(meeting["held_at"]) if meeting["held_at"] else None
        if held is None:
            continue
        if (horizon - held).days > CAPITAL_REVIEW_WINDOW_DAYS:
            continue
        return True
    return False


def program_expenditures(pos_id):
    rows = [e for e in db.expenditures.values() if e["pos_id"] == pos_id]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def eligible_instructor_exists(pos_id):
    for educator in db.educators.values():
        if educator["pos_id"] == pos_id and educator["status"] == "ELIGIBLE":
            return True
    return False


# ------------------------------------------------------------- cascade chains
def suspend_program(program):
    """Sanction cascade link 3, and link 4 which it causes."""
    if program["approval_status"] != "STATE_APPROVED":
        return False
    program["approval_status"] = "SUSPENDED"
    program["open_finding_codes"].append("PERF_SUSPENSION")
    touch(program)
    for expenditure in program_expenditures(program["id"]):
        if expenditure["status"] == "REQUESTED":
            expenditure["status"] = "BLOCKED"
            touch(expenditure)
    return True


def unsuspend_program(program):
    """Acceptance cascade link 3, and link 4 which it causes."""
    if program["approval_status"] != "SUSPENDED":
        return False
    program["approval_status"] = "CHANGES_REQUESTED"
    program["open_finding_codes"].append("PERF_IMPROVEMENT_ACCEPTED")
    touch(program)
    for expenditure in program_expenditures(program["id"]):
        if expenditure["status"] == "BLOCKED":
            expenditure["status"] = "REQUESTED"
            touch(expenditure)
    return True


def escalate_indicator(indicator):
    """Sanction cascade link 2: the miss counter reaching tolerance fires this."""
    indicator["status"] = "IMPROVEMENT_REQUIRED"
    touch(indicator)
    program = db.programs.get(indicator["pos_id"])
    if program is not None:
        suspend_program(program)


def accept_plan_cascade(indicator):
    """Acceptance cascade link 2, which causes link 3."""
    indicator["status"] = "MONITORING"
    indicator["consecutive_miss_count"] = 0
    touch(indicator)
    program = db.programs.get(indicator["pos_id"])
    if program is not None:
        unsuspend_program(program)


def sanction_indicator(indicator):
    """Terminal return branch: the plan is rejected and the indicator sanctioned."""
    indicator["status"] = "SANCTIONED"
    touch(indicator)
    program = db.programs.get(indicator["pos_id"])
    if program is not None:
        program["open_finding_codes"].append("PERF_SANCTION")
        touch(program)


# ------------------------------------------------------------- committee status
def maybe_activate_committee(committee):
    active, employers, chair_id = calc.committee_counts(committee["id"])
    committee["active_member_count"] = active
    committee["employer_member_count"] = employers
    committee["chair_member_id"] = chair_id
    if committee["status"] != "FORMING":
        return
    if (active >= int(committee["quorum_min_members"])
            and employers >= int(committee["employer_seat_min"])
            and chair_id is not None):
        committee["status"] = "ACTIVE"


# ------------------------------------------------------------- grant helpers
def award_window_open(award):
    start = parse_date(award["obligation_window_start"])
    end = parse_date(award["obligation_window_end"])
    today = clock_date()
    return start is not None and end is not None and start <= today <= end


def rebuild_award(award):
    calc.commit_ledger(award)
    touch(award)
    return award


def asset_conflict(award_id, asset_tag, start, end, skip_id=None):
    """Closed service periods with a 14-day mobilisation buffer (PRD sec 3.7)."""
    blocking = ("REQUESTED", "CERTIFIED", "OBLIGATED", "BLOCKED")
    for expenditure in db.expenditures.values():
        if expenditure["grant_award_id"] != award_id:
            continue
        if skip_id is not None and expenditure["id"] == skip_id:
            continue
        if expenditure["asset_tag"] != asset_tag:
            continue
        if expenditure["status"] not in blocking:
            continue
        other_start = parse_date(expenditure["service_period_start"])
        other_end = parse_date(expenditure["service_period_end"])
        if other_start is None or other_end is None:
            continue
        if start <= add_days(other_end, 14) and end >= add_days(other_start, -14):
            return True
    return False
