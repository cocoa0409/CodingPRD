"""In-memory data store and the server-side logical clock.

Storage is plain dicts keyed by id. The store starts empty on every boot;
nothing is seeded. The logical clock starts at exactly 2026-09-01T00:00:00Z
and is only ever moved by POST /_clock/set_current_utc.
"""

import uuid

from constants import CLOCK_START_ISO
from timeutil import parse_iso, fmt


class Store:
    def __init__(self):
        # entity dicts, keyed by id
        self.cycles = {}        # CompetitionCycle
        self.programs = {}      # CountryProgram
        self.applicants = {}    # Applicant
        self.applications = {}  # Application
        self.scores = {}        # ReviewScore
        self.rounds = {}        # PlacementRound
        self.grants = {}        # Grant
        self.visas = {}         # VisaSponsorship
        self.ledgers = {}       # ResidencyLedger
        self.reports = {}       # Report
        self.incidents = {}     # EmergencyIncident
        self.alumni = {}        # AlumniProfile
        # logical clock (aware UTC datetime)
        self.clock = parse_iso(CLOCK_START_ISO)
        # global insertion sequence (tie-breaks created_at in sorts)
        self.seq = 0
        # EV sponsor program number counter (EV-000001, ...)
        self.visa_counter = 0


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    STORE.seq += 1
    return STORE.seq


def now():
    """The current logical-clock instant (aware UTC datetime)."""
    return STORE.clock


def now_iso():
    return fmt(STORE.clock)


def stamp_new(entity):
    """Populate the common system fields on a freshly created entity."""
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def bump(entity):
    """Refresh updated_at and increment version by exactly one (PRD 2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1
