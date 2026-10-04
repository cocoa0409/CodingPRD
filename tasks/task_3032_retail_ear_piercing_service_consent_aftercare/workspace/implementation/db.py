"""In-memory data store for the ear-piercing service API.

Storage is deliberately process-local: plain dicts keyed by id, no file, no
cache, no external persistence. Because every byte of state lives in this
process, re-invoking start.sh yields a guaranteed fresh boot with an empty
store. Nothing in this module is seeded or preloaded; every row is created
through a declared endpoint (PRD 2.5).
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

# =============================================================================
# Fixed constants (PRD 2.8, scaffold 1.3)
# =============================================================================
AFTERCARE_KIT_FEE_CENTS = 1200
AFTERCARE_RETAIN_FLOOR_CENTS = 500
MODERATE_RATE = 0.50
SEVERE_RATE = 0.75
TIER_1_FLOOR_CENTS = 4000
TIER_2_FLOOR_CENTS = 8000
TIER_1_RATE = 0.10
TIER_2_RATE = 0.15
RE_PIERCE_RATE = 0.20
SITE_MINIMUM_CENTS = 1500
MAX_SURCHARGE_CENTS = 2500
PER_CONTRAINDICATION_CENTS = 350
PER_EXTRA_SITE_CENTS = 200
DOWNGRADE_RATE = 0.25

RESTRICTION_INCIDENT_THRESHOLD = 3
RESTRICTION_FAILED_CYCLE_THRESHOLD = 1
FREEZE_FAILED_CYCLE_THRESHOLD = 2

BASE_SCORE = 100
FLOOR_SCORE = 0
CEILING_SCORE = 100
COMPLETION_BONUS = 8

RECERTIFICATION_LEAD_DAYS = 30
CERTIFICATION_VALIDITY_MONTHS = 12
CHECK_IN_LEAD_MINUTES = 30
SLOT_MIN_MINUTES = 15
CONSENT_VALIDITY_DAYS = 30
AFTERCARE_FOLLOW_UP_DAYS = 30
INCIDENT_REOPEN_DAYS = 30
ELIGIBILITY_WINDOW_DAYS = 365
HEALING_ASSESSMENT_MIN_DAYS = 42

SITE_FACTORS = {
    "LOBE": 1.0,
    "UPPER_LOBE": 1.2,
    "HELIX": 1.5,
    "TRAGUS": 1.6,
    "INDUSTRIAL": 2.2,
    "NOSTRIL": 1.4,
}

SITE_BASE_VALUE_CENTS = {
    "LOBE": 3000,
    "UPPER_LOBE": 3900,
    "HELIX": 5200,
    "TRAGUS": 4300,
    "INDUSTRIAL": 6400,
    "NOSTRIL": 4600,
}

SITES = ["LOBE", "UPPER_LOBE", "HELIX", "TRAGUS", "INDUSTRIAL", "NOSTRIL"]

CONTRAINDICATION_SEVERITY_RANK = {
    "KELOID_HISTORY": 5,
    "BLOOD_THINNER_THERAPY": 4,
    "ACTIVE_INFECTION": 3,
    "UNCONTROLLED_DIABETES": 2,
    "METAL_ALLERGY": 2,
    "PREGNANCY": 2,
    "HYPERTROPHIC_SCAR": 1,
}

ESCALATION_RANK_CODES = {"KELOID_HISTORY", "BLOOD_THINNER_THERAPY"}

CERTIFICATION_LEVEL_ORDER = {
    "APPRENTICE": 1,
    "STANDARD": 2,
    "SENIOR": 3,
    "INSTRUCTOR": 4,
}

CERTIFICATION_STATUS_ORDER = {
    "REVOKED": 1,
    "EXPIRED": 2,
    "RECERTIFICATION_PENDING": 3,
    "EXPIRING_SOON": 4,
    "VALID": 5,
}

SCREENING_OUTCOME_ORDER = {"REFUSED": 1, "ESCALATED": 2, "CLEARED": 3}
SCREENING_OUTCOME_RANKS = {"REFUSED": 1, "ESCALATED": 2, "CLEARED": 3, "PENDING": 0}

NON_TERMINAL_INCIDENT_STATES = {"LOGGED", "TRIAGED", "ESCALATED", "REOPENED"}

REQUIRED_IDENTIFICATION_BY_CONSENT_TYPE = {
    "SELF": "GOVERNMENT_PHOTO_ID",
    "GUARDIAN_PRESENT": "BIRTH_CERTIFICATE",
    "GUARDIAN_NOTARIZED": "BIRTH_CERTIFICATE",
    "COURT_ORDER": "PASSPORT",
}

SIGNED_AT_MARKER = "2222-01-01T00:00:00Z"

ALLOWED_SITES = set(SITES)
ALLOWED_CONTRAINDICATIONS = set(CONTRAINDICATION_SEVERITY_RANK)
ALLOWED_REACTIONS = {
    "REDNESS", "SWELLING", "DISCHARGE", "EMBEDDED_BACK",
    "INFECTION", "ALLERGIC_REACTION", "KELOID", "NERVE_DAMAGE",
}

# =============================================================================
# Time helpers (PRD 3.10): a logical clock, never wall clock.
# =============================================================================
ISO_RE = re.compile(r"Z$")


def parse_instant(value, default=None):
    """Parse an ISO 8601 instant. Naive input is read as UTC (Z)."""
    if value is None or value == "":
        return default
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        text = ISO_RE.sub("+00:00", text)
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return default
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_instant(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_now():
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def wall_instant():
    """Wall-clock instant, used only for row bookkeeping timestamps."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def floor_to_minute(dt):
    return dt.replace(second=0, microsecond=0)


def floor_to_second(dt):
    return dt.replace(microsecond=0)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_months(dt, months):
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                       else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.replace(year=year, month=month, day=day)


def age_in_whole_years(date_of_birth, at_instant):
    years = at_instant.year - date_of_birth.year
    try:
        anniversary = date_of_birth.replace(year=at_instant.year)
    except ValueError:
        anniversary = date_of_birth.replace(year=at_instant.year, day=28)
    if at_instant < anniversary:
        years -= 1
    return years


# =============================================================================
# Entity base class
# =============================================================================
class Entity:
    """Common properties carried by every row (PRD 2.5)."""

    FIELDS = ()

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.created_at = fmt_now()
        self.updated_at = self.created_at
        self.version = 1

    def to_dict(self):
        out = {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
        }
        for field in self.FIELDS:
            value = getattr(self, field, None)
            out[field] = self._serialize(field, value)
        return out

    def _serialize(self, field, value):
        if isinstance(value, datetime):
            return fmt_instant(value)
        if isinstance(value, list):
            return list(value)
        return value

    def touch(self):
        # While a compound mutation is in flight the row defers its bookkeeping
        # so the whole operation lands as exactly one version increment
        # (PRD 2.5: "increments by one on every mutation of the row").
        if getattr(self, "_defer_touch", False):
            self._deferred_touch = True
            return
        self.apply_touch()

    def apply_touch(self):
        self.updated_at = fmt_now()
        self.version += 1


class Jurisdiction(Entity):
    FIELDS = (
        "state_code", "min_age_self_consent", "min_age_with_guardian",
        "min_age_absolute", "permitted_sites", "requires_guardian_presence",
        "record_retention_years", "consent_form_version",
        "sterilization_protocol_code", "status",
    )

    def __init__(self):
        super().__init__()
        self.state_code = None
        self.min_age_self_consent = 0
        self.min_age_with_guardian = 0
        self.min_age_absolute = 0
        self.permitted_sites = []
        self.requires_guardian_presence = False
        self.record_retention_years = 0
        self.consent_form_version = None
        self.sterilization_protocol_code = None
        self.status = "ACTIVE"


class StoreLocation(Entity):
    FIELDS = (
        "name", "jurisdiction_id", "piercing_room_count", "compliance_posture",
        "open_incident_count", "status",
    )

    def __init__(self):
        super().__init__()
        self.name = None
        self.jurisdiction_id = None
        self.piercing_room_count = 0
        self.compliance_posture = "OPEN"
        self.open_incident_count = 0
        self.status = "OPEN"


class Piercer(Entity):
    FIELDS = (
        "full_name", "home_store_id", "eligibility_score",
        "active_certification_id", "assigned_session_count", "status",
    )

    def __init__(self):
        super().__init__()
        self.full_name = None
        self.home_store_id = None
        self.eligibility_score = 100
        self.active_certification_id = None
        self.assigned_session_count = 0
        self.status = "ACTIVE"


class CertificationRecord(Entity):
    FIELDS = (
        "piercer_id", "certification_level", "sterilization_protocol_code",
        "issued_at", "expires_at", "recertification_due_at",
        "attempted_practical_count", "status",
    )

    def __init__(self):
        super().__init__()
        self.piercer_id = None
        self.certification_level = None
        self.sterilization_protocol_code = None
        self.issued_at = None
        self.expires_at = None
        self.recertification_due_at = None
        self.attempted_practical_count = 0
        self.status = "VALID"


class SterilizationCycle(Entity):
    FIELDS = (
        "store_location_id", "autoclave_unit_id", "protocol_code",
        "cycle_start_at", "cycle_end_at", "temperature_celsius",
        "biological_indicator_passed", "quarantine_scope_units", "status",
    )

    def __init__(self):
        super().__init__()
        self.store_location_id = None
        self.autoclave_unit_id = None
        self.protocol_code = None
        self.cycle_start_at = None
        self.cycle_end_at = None
        self.temperature_celsius = None
        self.biological_indicator_passed = None
        self.quarantine_scope_units = 0
        self.status = "IN_PROGRESS"


class CartridgeLot(Entity):
    FIELDS = (
        "store_location_id", "sterilization_cycle_id", "lot_number", "site_type",
        "units_received", "units_available", "units_consumed", "units_quarantined",
        "expiration_date", "status",
    )

    def __init__(self):
        super().__init__()
        self.store_location_id = None
        self.sterilization_cycle_id = None
        self.lot_number = None
        self.site_type = None
        self.units_received = 0
        self.units_available = 0
        self.units_consumed = 0
        self.units_quarantined = 0
        self.expiration_date = None
        self.status = "AVAILABLE"


class Customer(Entity):
    FIELDS = (
        "full_name", "date_of_birth", "guardian_name", "guardian_contact",
        "aftercare_credit_cents", "refunded_cents", "retained_cents", "status",
    )

    def __init__(self):
        super().__init__()
        self.full_name = None
        self.date_of_birth = None
        self.guardian_name = None
        self.guardian_contact = None
        self.aftercare_credit_cents = 0
        self.refunded_cents = 0
        self.retained_cents = 0
        self.status = "ACTIVE"


class ConsentRecord(Entity):
    FIELDS = (
        "customer_id", "jurisdiction_id", "consent_type",
        "guardian_verification_status", "identification_type",
        "required_identification_type", "identification_number_masked",
        "signed_at", "expires_at", "consent_status",
    )

    def __init__(self):
        super().__init__()
        self.customer_id = None
        self.jurisdiction_id = None
        self.consent_type = None
        self.guardian_verification_status = "NOT_REQUIRED"
        self.identification_type = None
        self.required_identification_type = None
        self.identification_number_masked = None
        self.signed_at = None
        self.expires_at = None
        self.consent_status = "PENDING"


class Appointment(Entity):
    FIELDS = (
        "store_location_id", "customer_id", "piercer_id", "jurisdiction_id",
        "intake_type", "site_requested", "slot_start_at", "slot_end_at",
        "reschedule_count", "governing_screening_id", "status",
    )

    def __init__(self):
        super().__init__()
        self.store_location_id = None
        self.customer_id = None
        self.piercer_id = None
        self.jurisdiction_id = None
        self.intake_type = None
        self.site_requested = None
        self.slot_start_at = None
        self.slot_end_at = None
        self.reschedule_count = 0
        self.governing_screening_id = None
        self.status = "BOOKED"


class AnatomyScreening(Entity):
    FIELDS = (
        "appointment_id", "piercer_id", "anatomy_sites_examined",
        "contraindication_codes", "refusal_reason_code", "outcome",
    )

    def __init__(self):
        super().__init__()
        self.appointment_id = None
        self.piercer_id = None
        self.anatomy_sites_examined = []
        self.contraindication_codes = []
        self.refusal_reason_code = None
        self.outcome = "PENDING"


class PiercingSession(Entity):
    FIELDS = (
        "appointment_id", "piercer_id", "cartridge_lot_id", "site_pierced",
        "base_fee_cents", "aftercare_kit_included", "solution_lot_number",
        "follow_up_reminder_due_at", "follow_up_acknowledged", "net_fee_cents",
        "service_status", "healing_status",
    )

    def __init__(self):
        super().__init__()
        self.appointment_id = None
        self.piercer_id = None
        self.cartridge_lot_id = None
        self.site_pierced = None
        self.base_fee_cents = 0
        self.aftercare_kit_included = False
        self.solution_lot_number = None
        self.follow_up_reminder_due_at = None
        self.follow_up_acknowledged = False
        self.net_fee_cents = 0
        self.service_status = "IN_PROGRESS"
        self.healing_status = "HEALING"
        # Bookkeeping marker for the eligibility completion bonus: the instant
        # the session reached service_status COMPLETED.
        self.completed_at = None


class IncidentReport(Entity):
    FIELDS = (
        "session_id", "reported_at", "severity", "reaction_codes",
        "escalation_status", "refund_amount_cents", "refund_status",
    )

    def __init__(self):
        super().__init__()
        self.session_id = None
        self.reported_at = None
        self.severity = None
        self.reaction_codes = []
        self.escalation_status = "LOGGED"
        self.refund_amount_cents = 0
        self.refund_status = "NONE"


class HealingOutcome(Entity):
    FIELDS = (
        "session_id", "assessed_at", "healing_result", "downgrade_credited_cents",
        "re_pierce_eligible", "re_pierce_claim_count", "status",
    )

    def __init__(self):
        super().__init__()
        self.session_id = None
        self.assessed_at = None
        self.healing_result = "PENDING_ASSESSMENT"
        self.downgrade_credited_cents = 0
        self.re_pierce_eligible = False
        self.re_pierce_claim_count = 0
        self.status = "ASSESSED"


class atomic_mutation:
    """Bracket a compound mutation so the row's `version` lands once.

    The declared version-bearing operations (PRD 2.5) recompute derived
    fields as part of the same mutation; this keeps that recomputation from
    being observed as several increments.
    """

    def __init__(self, *rows):
        self.rows = [r for r in rows if r is not None]

    def __enter__(self):
        for row in self.rows:
            row._defer_touch = True
            row._deferred_touch = False
        return self

    def __exit__(self, exc_type, exc, tb):
        for row in self.rows:
            row._defer_touch = False
            if exc_type is not None:
                row._deferred_touch = False
                continue
            row.apply_touch()
        return False


class Store:
    """Process-local row store. Starts empty on every boot; never seeded."""

    def __init__(self):
        self.jurisdictions = {}
        self.stores = {}
        self.piercers = {}
        self.certifications = {}
        self.cycles = {}
        self.lots = {}
        self.customers = {}
        self.consents = {}
        self.appointments = {}
        self.screenings = {}
        self.sessions = {}
        self.incidents = {}
        self.outcomes = {}

        # Logical clock: reads exactly 2026-09-01T00:00:00Z before any call
        # and never falls back to wall-clock time (PRD 3.10).
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


DB = Store()