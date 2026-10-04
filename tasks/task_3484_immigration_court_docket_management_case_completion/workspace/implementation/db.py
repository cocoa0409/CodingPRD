# db.py — in-memory store and the server-side logical clock.
#
# Storage is plain dicts keyed by id. The store starts EMPTY on every boot:
# no seeding, no preloading — every entity is constructed via the API.
# start.sh re-invocation therefore boots a pristine server.
import itertools
from datetime import datetime, timezone

courts = {}
judges = {}
interpreters = {}
programs = {}           # LegalOrientationProgram
cases = {}
hearings = {}
notices = {}            # HearingNotice
continuances = {}       # ContinuanceRequest
venue_motions = {}      # ChangeOfVenueMotion
reassignments = {}      # CaseReassignment (immutable: id + created_at only)
decisions = {}
appeals = {}
motions = {}            # MotionToReopen
docket_reviews = {}     # DocketReview (immutable: id + created_at only)

# Monotonic insertion counter. created_at values derive from the logical
# clock and therefore tie freely; "_seq" is the stable secondary order used
# wherever the PRD tie-breaks by created_at ASC or sorts lists by created_at.
_seq = itertools.count(1)

# The logical clock (PRD §2.4): exactly 2026-09-01T00:00:00Z before any set
# call; never falls back to wall-clock time.
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_seq():
    return next(_seq)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def stamp_new(record):
    """Populate the system-managed fields of a freshly created record."""
    now = get_clock()
    record["created_at"] = now
    record["_seq"] = next_seq()
    return record


def stamp_common(record):
    """Common-fields resources (PRD §2.5): created_at/updated_at/version."""
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on a common-fields mutation."""
    record["updated_at"] = get_clock()
    record["version"] = record.get("version", 1) + 1
    return record
