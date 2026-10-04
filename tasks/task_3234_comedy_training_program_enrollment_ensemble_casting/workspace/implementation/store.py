"""In-memory data store. Fresh on every process boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock timestamp for created_at/updated_at metadata (ISO 8601 UTC, 3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.levels = {}            # id -> CurriculumLevel
        self.terms = {}             # id -> Term
        self.instructors = {}       # id -> Instructor
        self.sections = {}          # id -> CourseSection
        self.students = {}          # id -> Student
        self.placements = {}        # id -> PlacementEvaluation
        self.enrollments = {}       # id -> Enrollment
        self.showcases = {}         # id -> ShowcaseEvent
        self.venue_slots = {}       # id -> VenueSlot
        self.cohorts = {}           # id -> CohortProgram
        self.auditions = {}         # id -> Audition
        self.casts = {}             # id -> EnsembleCast
        self.tours = {}             # id -> TouringAssignment
        self.scholarships = {}      # id -> ScholarshipAward
        self.invoices = {}          # id -> TuitionInvoice
        # Logical clock — boots pinned to 2026-09-01T00:00:00Z
        self.clock_utc = "2026-09-01T00:00:00Z"


store = Store()


def parse_dt(s):
    """Parse an ISO 8601 datetime string into an aware datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    txt = str(s).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def logical_now():
    return parse_dt(store.clock_utc)


def stamp(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def fresh(entity):
    """Attach common fields to a new entity."""
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity
