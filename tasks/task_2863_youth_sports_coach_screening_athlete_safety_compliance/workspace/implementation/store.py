"""In-memory data store. Starts completely empty on every boot: no entity is
ever seeded, preloaded or hardcoded - tests build all state through the API.
"""

import uuid

import clock

CLUBS = {}
MEMBERS = {}
SCREENING_ORDERS = {}
TRAINING_COURSES = {}
TRAINING_ASSIGNMENTS = {}
COACH_ASSIGNMENTS = {}
INVESTIGATING_BODIES = {}
CASES = {}
INTERIM_MEASURES = {}
CLUB_AUDITS = {}
AUDIT_FINDINGS = {}
ROOM_STAYS = {}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def new_row(**fields):
    """Mint a row with the four common properties of PRD section 2.4."""
    stamp = clock.now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at without advancing version (used by the lazily
    evaluated clock transitions and by pure derived-counter recomputation)."""
    row["updated_at"] = clock.now()


def bump(row):
    """A mutation of the row: refresh updated_at and advance version by one."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1


def ordered(rows):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def orders_of(member_id):
    return [o for o in SCREENING_ORDERS.values() if o["member_id"] == member_id]


def assignments_of(member_id):
    return [a for a in TRAINING_ASSIGNMENTS.values() if a["member_id"] == member_id]


def coach_assignments_of_member(member_id):
    return [a for a in COACH_ASSIGNMENTS.values() if a["member_id"] == member_id]


def coach_assignments_of_club(club_id):
    return [a for a in COACH_ASSIGNMENTS.values() if a["club_id"] == club_id]


def measures_of(member_id):
    return [m for m in INTERIM_MEASURES.values() if m["member_id"] == member_id]


def measures_of_case(case_id):
    return [m for m in INTERIM_MEASURES.values() if m["case_id"] == case_id]


def findings_of_audit(audit_id):
    return [f for f in AUDIT_FINDINGS.values() if f["audit_id"] == audit_id]


def findings_of_member(member_id):
    return [f for f in AUDIT_FINDINGS.values() if f.get("member_id") == member_id]


def audits_of_club(club_id):
    return [a for a in CLUB_AUDITS.values() if a["club_id"] == club_id]


def course_by_code(code):
    for c in TRAINING_COURSES.values():
        if c["code"] == code:
            return c
    return None


def cases_of_member(member_id):
    return [c for c in CASES.values() if c["reported_member_id"] == member_id]


def reset_all():
    for table in (CLUBS, MEMBERS, SCREENING_ORDERS, TRAINING_COURSES,
                  TRAINING_ASSIGNMENTS, COACH_ASSIGNMENTS, INVESTIGATING_BODIES,
                  CASES, INTERIM_MEASURES, CLUB_AUDITS, AUDIT_FINDINGS, ROOM_STAYS):
        table.clear()
    _seq["n"] = 0
    clock.reset()
