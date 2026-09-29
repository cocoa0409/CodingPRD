"""Domain vocabulary and numeric constants declared by the PRD.

Enumerations mirror the PRD's field definitions exactly; numeric constants are the
literals the PRD's derivation rules name (weights, caps, buffers, grid width and
the labour allocation added under the ACTUAL_COST reimbursement basis).
"""

API_PREFIX = "/crr"
CLOCK_SET_PATH = "/_clock/set_current_utc"

# The logical program clock starts at this instant in every fresh process.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"


class Role:
    PROGRAM_ADMIN = "ProgramAdmin"
    RISK_ANALYST = "RiskAnalyst"
    CANVASS_COORDINATOR = "CanvassCoordinator"
    CRR_TECHNICIAN = "CrrTechnician"
    GRANT_OFFICER = "GrantOfficer"
    PARTNER_LIAISON = "PartnerLiaison"


ALL_ROLES = [
    Role.PROGRAM_ADMIN,
    Role.RISK_ANALYST,
    Role.CANVASS_COORDINATOR,
    Role.CRR_TECHNICIAN,
    Role.GRANT_OFFICER,
    Role.PARTNER_LIAISON,
]


class ZoneKind:
    LEAF = "LEAF"
    DISTRICT = "DISTRICT"


class AssessmentStatus:
    UNASSESSED = "UNASSESSED"
    ASSESSED = "ASSESSED"
    TARGETED = "TARGETED"
    SERVICE_ACTIVE = "SERVICE_ACTIVE"
    SERVICE_COMPLETE = "SERVICE_COMPLETE"


class RiskTier:
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class AssessmentBasis:
    PROVISIONAL = "PROVISIONAL"
    VALIDATED = "VALIDATED"


class HouseholdStatus:
    INTAKE_QUEUED = "INTAKE_QUEUED"
    APPOINTMENT_SCHEDULED = "APPOINTMENT_SCHEDULED"
    VISIT_COMPLETED = "VISIT_COMPLETED"
    REVISIT_REQUIRED = "REVISIT_REQUIRED"
    REFUSED = "REFUSED"
    NO_CONTACT = "NO_CONTACT"


class PriorityBand:
    P1_HIGH_RISK = "P1_HIGH_RISK"
    P2_ELEVATED = "P2_ELEVATED"
    P3_STANDARD = "P3_STANDARD"


class CertificationLevel:
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"


class CrewStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RouteStatus:
    PLANNED = "PLANNED"
    PUBLISHED = "PUBLISHED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class VisitStatus:
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_EDUCATION = "AWAITING_EDUCATION"
    AWAITING_INSTALL_OUTCOME = "AWAITING_INSTALL_OUTCOME"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InstallStatus:
    NOT_STARTED = "NOT_STARTED"
    SURVEYED = "SURVEYED"
    INSTALL_COMPLETE = "INSTALL_COMPLETE"
    INSTALL_DEFERRED = "INSTALL_DEFERRED"


class EducationStatus:
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    DECLINED = "DECLINED"


class AppointmentOption:
    SCHEDULED_APPOINTMENT = "SCHEDULED_APPOINTMENT"
    CANVASS_WALKUP = "CANVASS_WALKUP"
    VIRTUAL_ASSESSMENT = "VIRTUAL_ASSESSMENT"


class ContactChannel:
    PHONE = "PHONE"
    DOOR_KNOCK = "DOOR_KNOCK"
    EMAIL = "EMAIL"
    PARTNER_REFERRAL = "PARTNER_REFERRAL"


class CancelReason:
    OCCUPANT_REFUSED = "OCCUPANT_REFUSED"
    OCCUPANT_UNREACHABLE = "OCCUPANT_UNREACHABLE"
    ROUTE_CLOSED = "ROUTE_CLOSED"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"


class InstallOutcome:
    COMPLETE = "COMPLETE"
    DEFERRED = "DEFERRED"


class DeferralReason:
    OCCUPANT_DECLINED_INSTALL = "OCCUPANT_DECLINED_INSTALL"
    STRUCTURAL_BARRIER = "STRUCTURAL_BARRIER"
    STOCK_UNAVAILABLE = "STOCK_UNAVAILABLE"
    LANDLORD_APPROVAL_REQUIRED = "LANDLORD_APPROVAL_REQUIRED"


class DeviceType:
    SMOKE_10YR = "SMOKE_10YR"
    CO_ALARM = "CO_ALARM"
    COMBO_SMOKE_CO = "COMBO_SMOKE_CO"
    STROBE_HOH = "STROBE_HOH"


class PlacementLocation:
    SLEEPING_AREA = "SLEEPING_AREA"
    HALLWAY_OUTSIDE_SLEEPING = "HALLWAY_OUTSIDE_SLEEPING"
    LIVING_LEVEL = "LIVING_LEVEL"
    BASEMENT_STAIR_TOP = "BASEMENT_STAIR_TOP"
    KITCHEN = "KITCHEN"
    BATHROOM = "BATHROOM"
    GARAGE = "GARAGE"


FORBIDDEN_PLACEMENT_LOCATIONS = [
    PlacementLocation.KITCHEN,
    PlacementLocation.BATHROOM,
    PlacementLocation.GARAGE,
]

# Device type -> permitted placement locations.
ALLOWED_PLACEMENTS = {
    DeviceType.SMOKE_10YR: [
        PlacementLocation.SLEEPING_AREA,
        PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        PlacementLocation.LIVING_LEVEL,
        PlacementLocation.BASEMENT_STAIR_TOP,
    ],
    DeviceType.CO_ALARM: [
        PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        PlacementLocation.LIVING_LEVEL,
        PlacementLocation.BASEMENT_STAIR_TOP,
    ],
    DeviceType.COMBO_SMOKE_CO: [
        PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        PlacementLocation.LIVING_LEVEL,
    ],
    DeviceType.STROBE_HOH: [PlacementLocation.SLEEPING_AREA],
}


class InstallationStatus:
    RESERVED = "RESERVED"
    INSTALLED = "INSTALLED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class VoidedReason:
    DEVICE_DEFECT = "DEVICE_DEFECT"
    WRONG_PLACEMENT = "WRONG_PLACEMENT"
    OCCUPANT_REMOVED = "OCCUPANT_REMOVED"
    DATA_ENTRY_ERROR = "DATA_ENTRY_ERROR"


class LotStatus:
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class OrgType:
    NONPROFIT = "NONPROFIT"
    UTILITY = "UTILITY"
    GOVERNMENT = "GOVERNMENT"
    FAITH_BASED = "FAITH_BASED"


class GrantStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ReimbursementBasis:
    UNIT_RATE = "UNIT_RATE"
    ACTUAL_COST = "ACTUAL_COST"


class ReportStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class ReportDecision:
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class PlanStatus:
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VERIFIED = "VERIFIED"
    LAPSED = "LAPSED"
    SUPERSEDED = "SUPERSEDED"


class IssuedChannel:
    IN_PERSON = "IN_PERSON"
    MAIL = "MAIL"
    EMAIL = "EMAIL"


class LapseReason:
    ALARM_MISSING_AT_FOLLOW_UP = "ALARM_MISSING_AT_FOLLOW_UP"
    DRILL_NOT_PRACTICED = "DRILL_NOT_PRACTICED"


class ContactMethod:
    PHONE = "PHONE"
    DOOR_KNOCK = "DOOR_KNOCK"
    MAIL = "MAIL"
    PARTNER_VISIT = "PARTNER_VISIT"


class FollowUpOutcome:
    REACHED_ALARM_PRESENT = "REACHED_ALARM_PRESENT"
    REACHED_ALARM_MISSING = "REACHED_ALARM_MISSING"
    NO_ANSWER = "NO_ANSWER"
    REFUSED = "REFUSED"


# --- Risk scoring -----------------------------------------------------------
INCIDENT_POINTS_PER_UNIT_DENSITY = 4.0
INCIDENT_POINTS_CAP = 40.00
INJURY_POINTS_PER_UNIT_DENSITY = 10.0
INJURY_POINTS_CAP = 15.00
BUILDING_POINTS_WEIGHT = 0.15
SENIOR_WEIGHT = 0.12
UNDER5_WEIGHT = 0.10
DISABILITY_WEIGHT = 0.08
VULNERABILITY_POINTS_CAP = 20.00
ALARM_POINTS_WEIGHT = 0.10
ALARM_POINTS_CAP = 10.00
TIER_1_MIN_SCORE = 70.00
TIER_2_MIN_SCORE = 45.00

# --- Visit demand minutes ---------------------------------------------------
BASE_VISIT_MINUTES = 30
SLEEPING_AREA_MINUTES = 5
STOREY_MINUTES = 5
ACCESSIBILITY_MINUTES = 15
CHILD_MINUTES = 10
SENIOR_MINUTES = 10
TIER_1_MULTIPLIER = 1.25
TIER_2_MULTIPLIER = 1.10
GRID_MINUTES = 5
VISIT_MIN_MINUTES = 30
VISIT_MAX_MINUTES = 120

# --- Crew calendar buffers --------------------------------------------------
TRAVEL_BUFFER_SAME_ROUTE_MINUTES = 5
TRAVEL_BUFFER_CROSS_ROUTE_MINUTES = 15

# --- Device lot eligibility -------------------------------------------------
LOT_MIN_SHELF_DAYS = 90

# --- Reimbursement ----------------------------------------------------------
LABOR_ALLOCATION_CENTS_PER_DEVICE = 740

# --- Outcome measurement ----------------------------------------------------
OUTCOME_WINDOW_DAYS = 365
FOLLOW_UP_MIN_DAYS_SINCE_VISIT = 30
NO_CONTACT_MIN_ATTEMPTS = 3
