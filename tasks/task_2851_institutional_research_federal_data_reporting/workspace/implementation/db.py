"""In-memory data store. Starts completely empty on every boot: nothing is seeded."""
from util import CLOCK_START, iso, new_id

ROLES = ("IRAnalyst", "IRDirector", "RegistrarOfficer", "DataSteward", "DisclosureOfficer")
ANY_ROLE = ROLES
READ_ROLES = ROLES
DISCLOSURE_READ_ROLES = ("IRDirector", "DisclosureOfficer")

SURVEY_DOMAINS = ("ENROLLMENT", "COMPLETIONS", "FINANCE", "HR")
LOCAL_SYSTEMS = ("SIS", "HR", "FIN", "ADV")
COHORT_TYPES = ("GRAD_RATE_150", "RETENTION_FT")
ENTRY_STATUSES = ("FULL_TIME", "PART_TIME")
OUTCOMES = ("COMPLETED_150", "STILL_ENROLLED", "TRANSFERRED_OUT", "NO_LONGER_ENROLLED")
EXCLUSION_CODES = ("DECEASED", "PERMANENTLY_DISABLED", "ARMED_FORCES",
                   "FOREIGN_AID_SERVICE", "CHURCH_MISSION")
TARGET_TYPES = ("STATE", "CONSORTIUM", "RANKING")
REQUESTER_TYPES = ("INTERNAL", "EXTERNAL", "MEDIA")
AVOIDANCE_METHODS = ("SMALL_CELL_SUPPRESSION", "CONTROLLED_ROUNDING")

METRIC_DOMAINS = {
    "ENROLLMENT": ("TOTAL_HEADCOUNT", "FTE_ENROLLMENT"),
    "COMPLETIONS": ("TOTAL_COMPLETIONS", "CIP_PROGRAM_COUNT"),
    "FINANCE": ("INSTRUCTION_EXPENSES_CENTS", "ACADEMIC_SUPPORT_EXPENSES_CENTS",
                "STUDENT_SERVICES_EXPENSES_CENTS", "FTE_ENROLLMENT"),
    "HR": ("INSTRUCTIONAL_STAFF_HEADCOUNT", "INSTRUCTIONAL_CONTRACT_MONTHS"),
}
ALL_METRIC_KEYS = tuple(sorted({k for keys in METRIC_DOMAINS.values() for k in keys}))

TOLERANCE_BY_TARGET = {"STATE": "0.50", "CONSORTIUM": "1.00", "RANKING": "3.00"}

PY_VARIANCE_WARNING_PCT = "10.0"
PY_VARIANCE_FATAL_PCT = "25.0"
FULL_COVERAGE_PCT = "100.0"
MATERIALITY_PCT = "2.00"
ROUNDING_BASE = 5
CASCADE_JUSTIFICATION = "Cascade restatement: cohort exclusion decision applied"
SYSTEM_ACTOR = "SYSTEM"


class Store(object):
    """Every collection is a dict keyed by the row's server-minted id."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.cycles = {}
        self.frozen_files = {}
        self.components = {}
        self.metrics = {}
        self.edit_checks = {}
        self.cohorts = {}
        self.members = {}
        self.definitions = {}
        self.mappings = {}
        self.submissions = {}
        self.publications = {}
        self.restatements = {}
        self.data_requests = {}
        self.cells = {}
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return iso(self.clock)


store = Store()


def stamp_new(row):
    """Attach the four system-managed properties (PRD 2.4) to a brand-new row."""
    row["id"] = new_id()
    row["created_at"] = store.now_iso()
    row["updated_at"] = store.now_iso()
    row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def stamp_config(row):
    """Immutable configuration rows carry only id and created_at (PRD 2.4)."""
    row["id"] = new_id()
    row["created_at"] = store.now_iso()
    row["_seq"] = store.next_seq()
    return row


def touch(row):
    """Recording a mutation: refresh updated_at and advance version by exactly 1."""
    row["updated_at"] = store.now_iso()
    row["version"] = row.get("version", 0) + 1
    return row


def order_key(row):
    """Deterministic `created_at` ascending order with a stable insertion tie-break."""
    return (row.get("created_at") or "", row.get("_seq") or 0)


def public(row):
    """Strip internal bookkeeping keys from a row before serialisation."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}
