"""In-memory data store + logical clock (PRD 2.4 / 2.5).

The store starts EMPTY on every boot — no seeding of any kind. The logical
clock starts at exactly 2026-09-01T00:00:00Z and is moved only via
POST /_clock/set_current_utc. All deadline/window/attestation semantics read
this clock, never the host wall clock.
"""
import itertools
import uuid
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = CLOCK_START
        self.seq = itertools.count(1)
        self.cycles = {}          # ElectionCycle
        self.jurisdictions = {}   # Jurisdiction
        self.contests = {}        # Contest
        self.filings = {}         # CandidateFiling
        self.questionnaires = {}  # Questionnaire
        self.responses = {}       # CandidateResponse (shells)
        self.measures = {}        # BallotMeasure
        self.arguments = {}       # MeasureArgument
        self.reviews = {}         # NeutralityReview
        self.editions = {}        # GuideEdition
        self.forums = {}          # Forum
        self.questions = {}       # ForumQuestion
        self.volunteers = {}      # Volunteer
        self.incidents = {}       # PolicyIncident

    def next_seq(self):
        return next(self.seq)

    def new_id(self):
        return str(uuid.uuid4())


store = Store()
