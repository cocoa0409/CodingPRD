"""In-memory store and entity plumbing.

The store is module-level and starts empty on every process boot — the harness
relaunches the server per test, so no persistence layer is used or needed.
All domain timestamps read the logical clock (PRD §2.5), never wall-clock time.
"""

import uuid
from datetime import date, datetime, time

from util import UTC, add_months, fmt_dt

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

ATTEMPT_HARD_CAP = 6
REMEDIAL_GATE = 3
RETAKE_WAIT_DAYS = 15
MIN_ITEMS = 6
MAX_ITEMS = 12
Z_SCORE = 1.645
AUDIT_SEQ_MOD = 3
SINGLE_PROVIDER_FLAG_HOURS = 20
PRIOR_FAIL_LOOKBACK_MONTHS = 60
TIER1_MAX_LAPSE_MONTHS = 12
TIER2_MAX_LAPSE_MONTHS = 24
ATT_VALID_DAYS = 90
RESPONSE_WINDOW_DAYS = 30
APPEAL_WINDOW_DAYS = 30
SUSPENSION_MONTHS = 12


class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.levels = {}                # LevelDefinition (config: id + created_at only)
        self.policies = {}              # StateAdoptionPolicy (config)
        self.candidates = {}            # Candidate
        self.programs = {}              # EducationProgram
        self.completions = {}           # ProgramCompletionRecord
        self.exam_apps = {}             # ExamApplication
        self.atts = {}                  # AuthorizationToTest
        self.attempts = {}              # CognitiveExamAttempt
        self.remedials = {}             # RemedialEducationRecord
        self.psychomotors = {}          # PsychomotorVerification
        self.certifications = {}        # Certification
        self.recerts = {}               # RecertApplication
        self.ce_entries = {}            # CECreditEntry
        self.reentries = {}             # ReentryApplication
        self.licenses = {}              # LicenseApplication
        self.state_exams = {}           # StateExamRecord
        self.cases = {}                 # DisciplinaryCase


STORE = Store()


def now_dt():
    return STORE.clock


def new_id():
    return str(uuid.uuid4())


def next_seq():
    STORE.seq += 1
    return STORE.seq


def base_entity(common=True):
    ts = now_dt()
    e = {"id": new_id(), "created_at": ts, "_seq": next_seq()}
    if common:
        e["updated_at"] = ts
        e["version"] = 1
    return e


def touch(e):
    """Refresh updated_at and bump version on entities that carry them."""
    if "version" in e:
        e["version"] += 1
        e["updated_at"] = now_dt()


def _serialize_value(v):
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, list):
        return [_serialize_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _serialize_value(x) for k, x in v.items()}
    return v


def serialize(e):
    """Shallow-serialize an entity dict; underscore-prefixed keys are internal
    bookkeeping and never leave the process."""
    return {k: _serialize_value(v) for k, v in e.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Live-computed fields (PRD §2.4 / §3 narratives)
# ---------------------------------------------------------------------------

def disciplinary_hold(candidate_id):
    """True while any non-FINAL DisciplinaryCase on the candidate carries
    interim_action HOLD_NEW_APPLICATIONS."""
    for c in STORE.cases.values():
        if (c["subject_candidate_id"] == candidate_id
                and c["interim_action"] == "HOLD_NEW_APPLICATIONS"
                and c["status"] != "FINAL"):
            return True
    return False


def attempts_consumed(basis_id):
    """SCORED_PASS | SCORED_FAIL attempts booked against the basis; NO_SHOW and
    VOIDED never count."""
    return sum(
        1 for a in STORE.attempts.values()
        if a["basis_completion_record_id"] == basis_id
        and a["status"] in ("SCORED_PASS", "SCORED_FAIL")
    )


def attempts_remaining(basis_id):
    return ATTEMPT_HARD_CAP - attempts_consumed(basis_id)


def within_validity_window(record):
    """completion_date <= now <= add_months(completion_date, 24), both ends
    inclusive; completion_date is day-precision (midnight), now is second-precision."""
    start = datetime.combine(record["completion_date"], time.min, tzinfo=UTC)
    end = add_months(start, 24)
    return start <= now_dt() <= end


def accreditation_at(program, completion_date):
    """Accreditation status effective at completion_date, read from
    accreditation_history by effective_date (day precision). Entry 0 records
    the initial accreditation; a completion date earlier than every recorded
    effective_date falls back to the earliest entry (the program stood
    accredited from its creation)."""
    entries = program["accreditation_history"]
    best = None
    for entry in entries:
        if entry["effective_date"].date() <= completion_date:
            if best is None or entry["effective_date"] >= best["effective_date"]:
                best = entry
    if best is None and entries:
        best = min(entries, key=lambda e: e["effective_date"])
    return best["to_status"] if best else None


def program_accredited_at_completion(record):
    program = STORE.programs.get(record["program_id"])
    if not program:
        return False
    return accreditation_at(program, record["completion_date"]) in ("ACCREDITED", "PROVISIONAL")


def educationally_valid(record):
    """Full educational validity: VERIFIED, inside the window, accredited at
    completion (education_validity_window)."""
    return (record["status"] == "VERIFIED"
            and within_validity_window(record)
            and program_accredited_at_completion(record))


def get_level_of_record(level_id):
    return STORE.levels.get(level_id)
