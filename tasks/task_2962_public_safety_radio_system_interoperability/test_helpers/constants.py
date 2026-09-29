"""Domain constants for the Public Safety Radio Interoperability API.

Every literal here is taken from the PRD: enum member sets, numeric rate and
threshold constants, endpoint paths, and the fixed startup instant of the
logical clock.
"""

# ---------------------------------------------------------------------------
# Base mount point and endpoint paths
# ---------------------------------------------------------------------------

BASE = "/radio-system"

PATH_CLOCK = f"{BASE}/_clock/set_current_utc"
PATH_AGENCIES = f"{BASE}/agencies"
PATH_SITES = f"{BASE}/sites"
PATH_TEMPLATES = f"{BASE}/templates"
PATH_CHANGE_REQUESTS = f"{BASE}/change-requests"
PATH_UNITS = f"{BASE}/units"
PATH_KEYSETS = f"{BASE}/keysets"
PATH_OTAR_CAMPAIGNS = f"{BASE}/otar-campaigns"
PATH_TALKGROUPS = f"{BASE}/talkgroups"
PATH_INTEROP_PATCHES = f"{BASE}/interop-patches"
PATH_SITE_EVENTS = f"{BASE}/site-events"
PATH_TALKPATH_REQUESTS = f"{BASE}/talkpath-requests"
PATH_MIGRATION_READINESS = f"{BASE}/migration-readiness"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# PRD 2.5: "At server start the logical clock reads exactly
# `2026-08-01T00:00:00Z`".
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT_CANONICAL = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Roles (PRD 2.1 — exactly eight, spelled exactly as follows)
# ---------------------------------------------------------------------------

ROLE_SYSTEM_ADMIN = "SystemAdmin"
ROLE_RF_ENGINEER = "RFEngineer"
ROLE_FLEET_ENGINEER = "FleetEngineer"
ROLE_CHANGE_CONTROL_BOARD = "ChangeControlBoard"
ROLE_KEY_CUSTODIAN = "KeyCustodian"
ROLE_SECURITY_OFFICER = "SecurityOfficer"
ROLE_AGENCY_RADIO_MANAGER = "AgencyRadioManager"
ROLE_DISPATCHER = "Dispatcher"

ALL_ROLES = [
    ROLE_SYSTEM_ADMIN,
    ROLE_RF_ENGINEER,
    ROLE_FLEET_ENGINEER,
    ROLE_CHANGE_CONTROL_BOARD,
    ROLE_KEY_CUSTODIAN,
    ROLE_SECURITY_OFFICER,
    ROLE_AGENCY_RADIO_MANAGER,
    ROLE_DISPATCHER,
]

OPERATOR_ROLES = [
    ROLE_SYSTEM_ADMIN,
    ROLE_RF_ENGINEER,
    ROLE_FLEET_ENGINEER,
    ROLE_CHANGE_CONTROL_BOARD,
    ROLE_KEY_CUSTODIAN,
    ROLE_SECURITY_OFFICER,
]

AGENCY_BACKED_ROLES = [ROLE_AGENCY_RADIO_MANAGER, ROLE_DISPATCHER]

# A role string that is deliberately NOT one of the eight declared roles.
UNDECLARED_ROLE = "RegionalIntern"

# ---------------------------------------------------------------------------
# MemberAgency enums
# ---------------------------------------------------------------------------

AGENCY_TYPE_LAW = "LAW"
AGENCY_TYPE_FIRE = "FIRE"
AGENCY_TYPE_EMS = "EMS"
AGENCY_TYPE_PUBLIC_WORKS = "PUBLIC_WORKS"
AGENCY_TYPE_REGIONAL_AUTHORITY = "REGIONAL_AUTHORITY"

FEE_BASIS_SNAPSHOT = "SNAPSHOT"
FEE_BASIS_PRORATED = "PRORATED"

INTEROP_NONE = "NONE"
INTEROP_MONITOR = "MONITOR"
INTEROP_PATCH_AUTHORITY = "PATCH_AUTHORITY"

BILLING_CURRENT = "CURRENT"
BILLING_DELINQUENT = "DELINQUENT"
BILLING_SUSPENDED_FROM_VOTING = "SUSPENDED_FROM_VOTING"

# ---------------------------------------------------------------------------
# Site enums
# ---------------------------------------------------------------------------

SITE_IN_SERVICE = "IN_SERVICE"
SITE_MAINTENANCE = "MAINTENANCE"
SITE_DEGRADED = "DEGRADED"
SITE_OFF_AIR = "OFF_AIR"

CAPACITY_NORMAL = "NORMAL"
CAPACITY_PRIORITY_ONLY = "PRIORITY_ONLY"
CAPACITY_EMERGENCY_ONLY = "EMERGENCY_ONLY"

BACKUP_GENERATOR = "GENERATOR"
BACKUP_BATTERY_ONLY = "BATTERY_ONLY"

COVERAGE_UNRATED = "UNRATED"
COVERAGE_MARGINAL = "MARGINAL"
COVERAGE_GENERAL = "GENERAL"
COVERAGE_MISSION_CRITICAL = "MISSION_CRITICAL"

DERATE_NONE = "NONE"
DERATE_A = "A"
DERATE_B = "B"
DERATE_C = "C"

STANDARD_P25_PHASE1 = "P25_PHASE1"
STANDARD_P25_PHASE2 = "P25_PHASE2"
STANDARD_NG_LMR = "NG_LMR"

# ---------------------------------------------------------------------------
# RadioTemplate / ProgrammingChangeRequest enums
# ---------------------------------------------------------------------------

TEMPLATE_DRAFT = "DRAFT"
TEMPLATE_PUBLISHED = "PUBLISHED"
TEMPLATE_RETIRED = "RETIRED"

CR_DRAFT = "DRAFT"
CR_SUBMITTED = "SUBMITTED"
CR_CHANGES_REQUESTED = "CHANGES_REQUESTED"
CR_APPROVED = "APPROVED"
CR_REJECTED = "REJECTED"
CR_DEPLOYING = "DEPLOYING"
CR_DEPLOYED = "DEPLOYED"

DECISION_APPROVE = "APPROVE"
DECISION_REQUEST_CHANGES = "REQUEST_CHANGES"
DECISION_REJECT = "REJECT"

# ---------------------------------------------------------------------------
# SubscriberUnit enums
# ---------------------------------------------------------------------------

PROVISION_INVENTORY = "INVENTORY"
PROVISION_ASSIGNED = "ASSIGNED"
PROVISION_SUSPENDED = "SUSPENDED"
PROVISION_RETIRED = "RETIRED"

KEY_KEYLESS = "KEYLESS"
KEY_KEYED = "KEYED"
KEY_STALE = "KEY_STALE"
KEY_ZEROIZED = "ZEROIZED"

MODEL_PORTABLE = "PORTABLE"
MODEL_MOBILE = "MOBILE"
MODEL_CONTROL_STATION = "CONTROL_STATION"

ACTION_ASSIGN = "ASSIGN"
ACTION_SUSPEND = "SUSPEND"
ACTION_REINSTATE = "REINSTATE"
ACTION_RETIRE = "RETIRE"
ACTION_ZEROIZE = "ZEROIZE"

# ---------------------------------------------------------------------------
# Keyset / OtarCampaign enums
# ---------------------------------------------------------------------------

KEYSET_PENDING_APPROVAL = "PENDING_APPROVAL"
KEYSET_ACTIVE = "ACTIVE"
KEYSET_REJECTED = "REJECTED"
KEYSET_SUPERSEDED = "SUPERSEDED"
KEYSET_COMPROMISED = "COMPROMISED"

ALGO_AES256 = "AES256"
ALGO_DES_OFB = "DES_OFB"

KEYSET_DECISION_APPROVE = "APPROVE"
KEYSET_DECISION_REJECT = "REJECT"

CAMPAIGN_SCHEDULED = "SCHEDULED"
CAMPAIGN_COMPLETED = "COMPLETED"
CAMPAIGN_ABORTED = "ABORTED"

# ---------------------------------------------------------------------------
# Talkgroup / InteropPatch enums
# ---------------------------------------------------------------------------

TG_ACTIVE = "ACTIVE"
TG_LOCKED = "LOCKED"
TG_DECOMMISSIONED = "DECOMMISSIONED"

LOCK_REASON_NONE = "NONE"
LOCK_REASON_MANUAL = "MANUAL"
LOCK_REASON_KEY_COMPROMISE = "KEY_COMPROMISE"

TG_KIND_DISPATCH = "DISPATCH"
TG_KIND_TACTICAL = "TACTICAL"
TG_KIND_INTEROP = "INTEROP"
TG_KIND_ANNOUNCEMENT = "ANNOUNCEMENT"

ENC_CLEAR = "CLEAR"
ENC_ENCRYPTED = "ENCRYPTED"
ENC_SELECTABLE = "SELECTABLE"

TG_ACTION_LOCK = "LOCK"
TG_ACTION_UNLOCK = "UNLOCK"
TG_ACTION_DECOMMISSION = "DECOMMISSION"

PATCH_REQUESTED = "REQUESTED"
PATCH_ACTIVE = "ACTIVE"
PATCH_DENIED = "DENIED"
PATCH_RELEASED = "RELEASED"

PATCH_DECISION_ACTIVATE = "ACTIVATE"
PATCH_DECISION_DENY = "DENY"

RELEASE_REASON_NONE = "NONE"
RELEASE_REASON_OPERATOR = "OPERATOR"
RELEASE_REASON_KEY_COMPROMISE = "KEY_COMPROMISE"
RELEASE_REASON_PRIVILEGE_REVOKED = "PRIVILEGE_REVOKED"
RELEASE_REASON_SITE_ESCALATION = "SITE_ESCALATION"

# ---------------------------------------------------------------------------
# SiteEvent enums
# ---------------------------------------------------------------------------

EVENT_PLANNED_MAINTENANCE = "PLANNED_MAINTENANCE"
EVENT_UNPLANNED_OUTAGE = "UNPLANNED_OUTAGE"
EVENT_MAJOR_INCIDENT = "MAJOR_INCIDENT"

CAUSE_COMMERCIAL_POWER_LOSS = "COMMERCIAL_POWER_LOSS"
CAUSE_LINK_FAILURE = "LINK_FAILURE"
CAUSE_RF_FAULT = "RF_FAULT"
CAUSE_SCHEDULED_WORK = "SCHEDULED_WORK"
CAUSE_INCIDENT_SURGE = "INCIDENT_SURGE"

EVENT_OPEN = "OPEN"
EVENT_IN_PROGRESS = "IN_PROGRESS"
EVENT_ON_BACKUP_POWER = "ON_BACKUP_POWER"
EVENT_ESCALATED = "ESCALATED"
EVENT_SURGE_ACTIVE = "SURGE_ACTIVE"
EVENT_RESTORED = "RESTORED"
EVENT_CLOSED = "CLOSED"
EVENT_CANCELLED = "CANCELLED"

EV_ACTION_START = "START"
EV_ACTION_BACKUP_ENGAGED = "BACKUP_ENGAGED"
EV_ACTION_DECLARE_SURGE = "DECLARE_SURGE"
EV_ACTION_ESCALATE = "ESCALATE"
EV_ACTION_RESTORE = "RESTORE"
EV_ACTION_CLOSE = "CLOSE"
EV_ACTION_CANCEL = "CANCEL"

# ---------------------------------------------------------------------------
# TalkpathRequest enums
# ---------------------------------------------------------------------------

KIND_NORMAL = "NORMAL"
KIND_PRIORITY = "PRIORITY"
KIND_EMERGENCY = "EMERGENCY"

OUTCOME_GRANTED = "GRANTED"
OUTCOME_BUSIED = "BUSIED"
OUTCOME_PREEMPTED = "PREEMPTED"
OUTCOME_RELEASED = "RELEASED"

# ---------------------------------------------------------------------------
# Migration readiness
# ---------------------------------------------------------------------------

BASIS_STRICT = "STRICT"
BASIS_PLANNED = "PLANNED"

# ---------------------------------------------------------------------------
# Numeric constants (PRD 2.3, 2.10, 3.2, 3.3, 3.7, 3.8, 3.9)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# Fee ladder
TIER_1_MAX_UNITS = 50
TIER_2_MAX_UNITS = 200
TIER_1_RATE_CENTS = 4200
TIER_2_RATE_CENTS = 3600
TIER_3_RATE_CENTS = 3100
PATCH_AUTHORITY_SURCHARGE_BP = 800
LATE_FEE_BP = 150
PAYMENT_GRACE_DAYS = 30
VOTING_SUSPENSION_GRACE_DAYS = 60
MAX_FEE_PERIOD_DAYS = 366

# Governance
VOTE_WEIGHT_CAP = 5
UNITS_PER_EXTRA_VOTE = 250
QUORUM_NUMERATOR = 3
QUORUM_DENOMINATOR = 5

# Coverage
TIER_A_MIN_PCT = 97.00
TIER_B_MIN_PCT = 90.00
TIER_A_DERATE_PP = 0.5
TIER_B_DERATE_PP = 1.5
TIER_C_DERATE_PP = 3.0
BATTERY_ONLY_PENALTY_PP = 2.0
MISSION_CRITICAL_MIN_PCT = 97.0
GENERAL_MIN_PCT = 90.0

# Backup power escalation tiers
TIER_1_MINUTES = 120
TIER_2_MINUTES = 60
TIER_3_MINUTES = 30

# Channel capacity
CONTROL_CHANNELS_RESERVED = 1
SURGE_RESERVE_PCT = 25
MAX_RESERVED_TALKPATHS = 4
PRIORITY_CLASS_MAX = 3

# Change control
MAX_REVISIONS = 2

# Maintenance scheduling
MAINTENANCE_BUFFER_MINUTES = 45
MAX_CONCURRENT_MAINTENANCE_SITES = 2

# Recorder retention statutory floors, by agency_type (PRD 2.10)
RETENTION_FLOOR_BY_AGENCY_TYPE = {
    AGENCY_TYPE_LAW: 180,
    AGENCY_TYPE_FIRE: 90,
    AGENCY_TYPE_EMS: 90,
    AGENCY_TYPE_PUBLIC_WORKS: 30,
    AGENCY_TYPE_REGIONAL_AUTHORITY: 365,
}
PATCH_RETENTION_MIN_DAYS = 180

# Declared field defaults (PRD 3.1, 3.2, 3.3, 3.4, 3.6, 2.10)
DEFAULT_FEE_BASIS = FEE_BASIS_SNAPSHOT
DEFAULT_INTEROP_PRIVILEGE = INTEROP_MONITOR
DEFAULT_CONSOLE_POSITION_COUNT = 1
DEFAULT_RECORDER_RETENTION_DAYS = 90
DEFAULT_BATTERY_RUNTIME_MINUTES = 240
DEFAULT_GENERATOR_FUEL_HOURS = 0
DEFAULT_MIGRATION_STANDARD = STANDARD_P25_PHASE1
DEFAULT_PRIORITY_CLASS = 5
DEFAULT_EMERGENCY_BUTTON_ENABLED = False
DEFAULT_ENCRYPTION_REQUIRED = False
DEFAULT_TALKGROUP_PRIORITY_LEVEL = 5

# The never-minted identifier used for not-found probes.
NONEXISTENT_ID = "00000000-0000-4000-8000-000000000000"
