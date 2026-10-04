"""Every constant named in the PRD / scaffold, in one place."""

# --- retention (PRD 3.4) ----------------------------------------------------
BASE_RETENTION_DAYS = 30
EXTENDED_RETENTION_DAYS = 365

# --- byte arithmetic (PRD 2.8) ----------------------------------------------
GB_BYTES = 1073741824.0

# --- egress volume (PRD 3.6) ------------------------------------------------
FREE_EGRESS_GB = 1.0
OVERSIZE_THRESHOLD_GB = 500
OPERATOR_SURCHARGE_RATE = 0.25
RANSOMWARE_PROTECTED_GB = 100

# --- restore egress fee (PRD 3.6) -------------------------------------------
DISCOUNT_LOW_MIN_CENTS = 10000
DISCOUNT_HIGH_MIN_CENTS = 20000
PER_RESTORE_TRANSACTION_CENTS = 5

# --- billing (PRD 3.6) ------------------------------------------------------
DAYS_PER_MONTH = 30
STORAGE_TIER_RATE_CENTS_PER_GB_MONTH = {"BASIC": 6, "PLUS": 5, "PRO": 4}
EGRESS_TIER_RATES_CENTS_PER_GB = {"BASIC": 1, "PLUS": 1, "PRO": 1}
PER_TRANSACTION_CENTS = 1
CREDIT_CAP_CENTS = 20000
DELINQUENCY_THRESHOLD_CENTS = 5000

# --- durability (PRD 2.7) ---------------------------------------------------
ANNUAL_SHARD_FAILURE_RATE = 0.01

# --- shipments (PRD 3.7) ----------------------------------------------------
RETURN_WINDOW_DAYS = 30
LATE_RETURN_PENALTY_CENTS_PER_DRIVE = 2500

# --- retention change / deletion cooling-off (PRD 3.4, 3.8) -----------------
COOLING_OFF_DAYS = 7
COOLING_OFF_EXPIRY_DAYS = 7
DELETION_COOLING_OFF_DAYS = 30

# --- collection cadence (PRD 3.2) -------------------------------------------
INCREMENTS_PER_DAY = {"STANDARD": 24, "HIGH_FREQUENCY": 96}

# --- enums ------------------------------------------------------------------
ACCOUNT_TYPES = ("PERSONAL", "BUSINESS", "ENTERPRISE")
REGIONS = ("US_WEST", "US_EAST", "EU_CENTRAL")
STORAGE_TIERS = ("BASIC", "PLUS", "PRO")
ACCOUNT_STATUSES = ("ACTIVE", "DELINQUENT", "CLOSED")
LICENSE_TYPES = ("PERSONAL", "BUSINESS", "ENTERPRISE")
OS_TYPES = ("WINDOWS", "MACOS", "LINUX")
GROUP_TIERS = ("STANDARD", "HIGH_FREQUENCY")
GROUP_STATUSES = ("ACTIVE", "SUSPENDED")
POLICY_KINDS = ("RETENTION", "VERSIONING", "RANSOMWARE")
POLICY_STATUSES = ("ACTIVE", "SUPERSEDED")
AGENT_STATUSES = ("PENDING_AUTH", "ACTIVE", "RETIRED", "BLOCKED")
SET_STATES = ("PROVISIONING", "INITIAL_RUNNING", "ACTIVE", "SUSPENDED", "DELETED")
DURABILITY_CLASSES = ("STANDARD", "DEEP_ARCHIVE")
OPERATIONS = ("CREATE", "MODIFY", "DELETE")
RESTORE_TYPES = ("FILE_DOWNLOAD", "ZIP_ARCHIVE", "DRIVE_SHIPMENT")
RESTORE_STATES = ("REQUESTED", "VALIDATING", "IN_PROGRESS", "READY",
                  "COMPLETED", "FAILED", "CANCELLED", "REVERSED")
SHIPMENT_STATES = ("PREPARING", "SHIPPED", "DELIVERED", "AWAITING_RETURN",
                   "RETURNED", "CLOSED", "DELINQUENT")
PERIOD_STATES = ("OPEN", "CLOSED")
POD_STATUSES = ("HEALTHY", "DEGRADED", "REPAIRING", "FAILED")
RETENTION_REASONS = ("UPGRADE", "DOWNGRADE", "LITIGATION_HOLD", "POLICY_ALIGNMENT")
RETENTION_STATES = ("SUBMITTED", "COOLING_OFF", "APPLIED", "REJECTED", "EXPIRED")
DELETION_SCOPES = ("DELETED_FILES", "ACCOUNT_CLOSURE")
DELETION_STATES = ("SUBMITTED", "APPROVED", "EXECUTING", "COMPLETED", "REJECTED")

# --- role ceilings (PRD 3.2) ------------------------------------------------
LICENSE_CEILING = {
    "PERSONAL": ("PERSONAL",),
    "BUSINESS": ("PERSONAL", "BUSINESS"),
    "ENTERPRISE": ("PERSONAL", "BUSINESS", "ENTERPRISE"),
}

# --- RBAC (PRD 2.1 / 3) -----------------------------------------------------
ROLES = ("AccountOwner", "BackupOperator", "RetentionOfficer",
         "ComplianceOfficer", "SystemOperator")

# Two clearance ladders.  CAPS (capability) answers "may this role drive a
# write operation at all", and closes the AccountOwner holes left by the
# exhaustive `exclusive_operations` lists -- PRD 2.1 states that role
# exclusivity is strict.  LEASE (lease/read) gates read operations, which PRD
# 3.3 / 3.2 explicitly open to AccountOwner for file versions, sets, agents
# and groups, and to AccountOwner for its own billing periods (PRD 3.1).
RANK = {
    "AccountOwner": 0,
    "BackupOperator": 1,
    "RetentionOfficer": 2,
    "SystemOperator": 3,
    "ComplianceOfficer": 4,
}
CAPS = {
    "AccountOwner": 0,
    "BackupOperator": 1,
    "RetentionOfficer": 2,
    "SystemOperator": 3,
    "ComplianceOfficer": 4,
}
LEASE = {
    "AccountOwner": 1,
    "BackupOperator": 2,
    "RetentionOfficer": 3,
    "SystemOperator": 4,
    "ComplianceOfficer": 4,
}