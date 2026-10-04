"""In-memory data store.

Storage is strictly process-local Python dicts. Nothing is seeded, preloaded or
persisted; the store starts empty on every boot and all state is constructed by
callers through the declared API surface.
"""

import uuid
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Constants pinned by PRD.md / SCAFFOLD.yaml
# --------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

CERTIFICATION_VALIDITY_DAYS = 365
HANDOFF_BUFFER_MINUTES = 30
RETEST_COOLDOWN_HOURS = 24
PASSING_SCORE = 80
CERT_MIN_HOURS = 40
PROFICIENCY_GATE_PCT = 80.00
CUTOVER_READY_SCORE = 85.00
MAX_REJECTIONS = 3
MAX_REOPEN_ATTEMPTS = 3
MAX_VARIANCE_PCT = 2.00
MIN_PASS_RATE = 95.00
EPOCH_CAPACITY_POINTS = 30
STABILIZATION_TARGET = 80.00
MIN_RECONCILED_ORDER_COUNT = 350
BASE_SLA_MINUTES = 60
COMMAND_CENTER_ESCALATION_MINUTES = 30

SEV1_PENALTY = 40
SEV2_PENALTY = 25
SEV3_PENALTY = 10
SEV4_PENALTY = 3
INTERCHANNEL_PENALTY = 15
INTERCHANNEL_REJECT_THRESHOLD = 25
OPEN_POSTURE_MIN = 60.00
RESTRICTED_POSTURE_MIN = 40.00
BUILD_REJECTED_OPTIMISTIC_CAP = 5

CLASS_WEIGHT = {
    "FOUNDATION_ADOPTED": 1.0,
    "FOUNDATION_ADAPTED": 1.5,
    "LOCAL_CUSTOM": 2.0,
}

# Minimum observation hours per certification level (floor not pinned by the
# PRD; see README-style notes in the final report).
MIN_OBSERVATION_HOURS = {"STANDARD": 8.0, "ADVANCED": 16.0}

# Floor on Staff.accumulated_training_hours required to waive an assignment,
# keyed by the supplied waiver_reason (not pinned by the PRD).
WAIVER_REASON_MIN_HOURS = {"MEDICAL_LEAVE": 0.0, "PRIOR_EXPERIENCE": 0.0}

# Valid message codes per channel type (membership pinned by the channels'
# domain semantics; the explicit code list is given in PRD §3.6).
VALID_MESSAGE_CODES = {
    "LAB": ["ORM_O01", "ORU_R01"],
    "IMAGING": ["ORM_O01", "DICOM_STOW"],
    "PHARMACY": ["RDE_O11"],
    "DEVICE": ["ORU_R01"],
}

PAYLOAD_MAX_PCT = {
    "PATIENT_DEMOGRAPHICS": 1.00,
    "APPOINTMENTS": 1.50,
    "ORDERS": 2.00,
    "BALANCES": 0.50,
}

SCENARIO_MIN_CYCLES = {
    "UNIT": 3,
    "INTEGRATED": 2,
    "CHARGE_CAPTURE_TO_CLAIM": 1,
}

ROLES = [
    "ImplementationDirector",
    "ImplementationAnalyst",
    "BuildAnalyst",
    "TestLead",
    "TrainingCoordinator",
    "CredentialedTrainer",
    "ConversionAnalyst",
    "OrderReconciler",
    "RevenueCycleAnalyst",
    "InterfaceEngineer",
    "CutoverLead",
    "CommandCenterLead",
    "TriageCommander",
    "OptimizationLead",
]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self._now = parse_iso(CLOCK_DEFAULT)

    def get(self):
        return self._now

    def set(self, dt):
        self._now = dt


def parse_iso(value):
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_iso():
    return fmt_iso(datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.clock = Clock()

        self.ehr_implementations = {}
        self.facilities = {}
        self.departments = {}
        self.system_build_items = {}
        self.staffs = {}
        self.training_assignments = {}
        self.credentialed_trainers = {}
        self.proficiency_exams = {}
        self.test_scenarios = {}
        self.test_defects = {}
        self.data_conversion_batches = {}
        self.patient_orders = {}
        self.interface_channels = {}
        self.interface_messages = {}
        self.cutover_tasks = {}
        self.command_center_tickets = {}
        self.staffing_shifts = {}
        self.optimization_backlog_items = {}

        # segregation-of-duties audit trail: actor id -> set of marks
        self.actor_marks = {}
        # polymorphic target_ref resolution registry: id -> entity kind
        self.target_refs = {}
        # child creation order, used to order lists by creation timestamp
        self.creation_sequence = {}
        self._seq = 0

    # -- identity / common fields -----------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def _next_seq(self):
        self._seq += 1
        return self._seq

    def register_created(self, row):
        self.creation_sequence[row["id"]] = self._next_seq()

    def touch(self, row, common=False):
        """Refresh updated_at/version. InterfaceMessage opts out (PRD §2.4)."""
        if common:
            row["updated_at"] = now_iso()
            row["version"] = int(row.get("version", 1)) + 1

    def mark(self, actor, key):
        self.actor_marks.setdefault(actor, set()).add(key)

    def acted(self, actor, key):
        return key in self.actor_marks.get(actor, set())

    def register_ref(self, entity_id, kind):
        if entity_id:
            self.target_refs[entity_id] = kind

    def resolve_ref(self, ref):
        return self.target_refs.get(ref)


DB = Store()


def march_clock_to(dt):
    """Move the logical clock forward if dt is later; never move it backwards.

    Returns True when the clock actually advanced.
    """
    if dt is None:
        return False
    if dt > DB.clock.get():
        DB.clock.set(dt)
        return True
    return False


def clock_minus(delta):
    return DB.clock.get() - delta


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_days(dt, days):
    return dt + timedelta(days=days)