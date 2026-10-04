"""In-memory data store and the network's single logical clock.

Storage is process-local and intentionally ephemeral: a fresh `start.sh`
invocation starts from empty maps and the fixed clock default. Nothing is
seeded, preloaded or persisted.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

ENTITY_TYPES = [
    "Facility",
    "Bed",
    "Clinician",
    "ClinicianFacilityCredential",
    "ServiceOffering",
    "Payer",
    "TreatmentEpisode",
    "ClinicalAssessment",
    "LevelOfCareAuthorization",
    "MedicalClearance",
    "WithdrawalManagementPlan",
    "TreatmentPlan",
    "SessionAttendance",
    "LevelOfCareChange",
    "ContinuingCarePlan",
    "RecoveryHousing",
    "AlumniContact",
    "Accreditation",
]


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.tables = {name: {} for name in ENTITY_TYPES}
        self.current_utc = CLOCK_DEFAULT
        self._seq = 0
        self.seq_by_episode = {}
        self.ops_runs = {}
        self.so_consumed = {}
        self.dos_log = {}
        self.idem = {}

    # -- identity / ordering -------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_episode_seq(self, episode_id):
        value = self.seq_by_episode.get(episode_id, 0) + 1
        self.seq_by_episode[episode_id] = value
        return value

    # -- logical clock -------------------------------------------------------
    def now(self):
        return self.current_utc

    def set_now(self, moment):
        self.current_utc = moment

    # -- generic table access ------------------------------------------------
    def put(self, entity, record):
        self.tables[entity][record["id"]] = record
        return record

    def get(self, entity, record_id):
        return self.tables[entity].get(record_id)

    def all(self, entity):
        return list(self.tables[entity].values())

    def where(self, entity, predicate):
        return [row for row in self.tables[entity].values() if predicate(row)]

    def first(self, entity, predicate):
        for row in self.tables[entity].values():
            if predicate(row):
                return row
        return None


STORE = Store()


def plus_days(moment, days):
    return moment + timedelta(days=days)


def plus_hours(moment, hours):
    return moment + timedelta(hours=hours)


def new_request_id():
    return "req_" + uuid.uuid4().hex[:20].upper()