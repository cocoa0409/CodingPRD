"""Domain enumerations, constants and serialization field lists."""

# ------------------------------------------------------------------- constants
STATUTORY_TIMELINE_DAYS = 45
TRANSITION_WINDOW_DAYS = 180
TRANSITION_WINDOW_OPEN_DAYS = 270
TRANSITION_NOTIFICATION_MIN_LEAD_DAYS = 90
FPL_BASE_CENTS = 1580000
FPL_PER_ADDITIONAL_MEMBER_CENTS = 555000
INSURANCE_OFFSET_RATE = "0.60"
MAKEUP_WINDOW_DAYS = 30
MAKEUP_AT_RISK_THRESHOLD_UNITS = 4
CROSS_SETTING_BUFFER_MINUTES = 30
MINUTES_PER_UNIT = 15
MAX_VISIT_MINUTES = 240
AGE_EXPECTED_RATING = 6
COMPARABLE_SERVICE_DAYS = 180
EI_AGE_LIMIT_YEARS = 3

# ------------------------------------------------------------------ enumerations
REFERRAL_SOURCES = (
    "PHYSICIAN", "HOSPITAL", "PARENT", "CHILD_CARE", "SOCIAL_SERVICES",
    "PUBLIC_HEALTH", "EARLY_HEAD_START", "OTHER",
)
REFERRAL_STATUSES = (
    "INTAKE", "EVALUATION_PENDING", "ELIGIBILITY_DETERMINED", "IFSP_PENDING",
    "ACTIVE_SERVICES", "NOT_ELIGIBLE", "EXITED",
)
REFERRAL_TERMINAL = ("NOT_ELIGIBLE", "EXITED")
ELIGIBILITY_STATUSES = ("PENDING", "ELIGIBLE", "NOT_ELIGIBLE")
TIMELINE_STATUSES = ("IN_PROGRESS", "MET", "MISSED")
EXIT_REASONS = (
    "REACHED_AGE_THREE", "FAMILY_WITHDREW", "MOVED_OUT_OF_STATE",
    "NO_LONGER_ELIGIBLE",
)
PROGRESS_CATEGORIES = ("a", "b", "c", "d", "e", "NOT_COMPARABLE")
CONTACT_STATUSES = ("NOT_APPLICABLE", "COMPLIANT", "DUE", "DELINQUENT")

COORDINATOR_STATUSES = ("ACTIVE", "INACTIVE")
CASELOAD_POSTURES = ("OPEN", "NEAR_CAP", "AT_CAP", "OVER")

ASSESSMENT_TYPES = (
    "INITIAL_EVALUATION", "FAMILY_ASSESSMENT", "SUPPLEMENTAL_EVALUATION",
)
ASSESSMENT_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
DOMAINS = (
    "PHYSICAL", "COGNITIVE", "COMMUNICATION", "SOCIAL_EMOTIONAL", "ADAPTIVE",
)
ELIGIBILITY_RECOMMENDATIONS = ("ELIGIBLE", "NOT_ELIGIBLE", "INCONCLUSIVE")

IFSP_TYPES = ("INITIAL", "ANNUAL")
IFSP_STATUSES = (
    "DRAFT", "PENDING_CONSENT", "ACTIVE", "AMENDMENT_PENDING", "SUPERSEDED",
    "CLOSED", "WITHDRAWN",
)
IFSP_STOP_CLOCK_STATUSES = (
    "PENDING_CONSENT", "ACTIVE", "AMENDMENT_PENDING", "SUPERSEDED", "CLOSED",
)
IFSP_MEETING_DATE_STATUSES = (
    "DRAFT", "PENDING_CONSENT", "ACTIVE", "AMENDMENT_PENDING", "SUPERSEDED",
    "CLOSED",
)
IFSP_AMENDABLE = ("DRAFT", "PENDING_CONSENT", "ACTIVE", "AMENDMENT_PENDING")
CONSENT_SCOPES = ("FULL", "PARTIAL")

SERVICE_TYPES = (
    "SPEECH_THERAPY", "OCCUPATIONAL_THERAPY", "PHYSICAL_THERAPY",
    "DEVELOPMENTAL_INSTRUCTION", "SOCIAL_WORK", "SERVICE_COORDINATION",
    "EVALUATION_ASSESSMENT",
)
FEE_EXEMPT_SERVICE_TYPES = ("SERVICE_COORDINATION", "EVALUATION_ASSESSMENT")
SERVICE_STATUSES = (
    "PLANNED", "AUTHORIZED", "IN_DELIVERY", "AT_RISK", "COMPLETED",
    "DISCONTINUED",
)
SERVICE_LIVE_STATUSES = ("PLANNED", "AUTHORIZED", "IN_DELIVERY", "AT_RISK")
SETTING_CODES = (
    "HOME", "COMMUNITY_CHILDCARE", "COMMUNITY_OTHER", "CLINIC",
    "PROGRAM_OFFICE",
)
NON_NATURAL_SETTINGS = ("CLINIC", "PROGRAM_OFFICE")

PROVIDER_STATUSES = ("ACTIVE", "SUSPENDED", "TERMINATED")
SUSPENSION_REASONS = (
    "CREDENTIAL_LAPSE", "QUALITY_CONCERN", "BILLING_AUDIT",
    "VOLUNTARY_WITHDRAWAL", "CONTRACT_ENDED",
)

AUTHORIZATION_STATUSES = (
    "ACTIVE", "EXHAUSTED", "SUSPENDED", "REVOKED", "EXPIRED",
)
AUTHORIZATION_REVOCABLE = ("ACTIVE", "EXHAUSTED", "SUSPENDED")
AUTHORIZATION_COMMITTED = ("ACTIVE", "EXHAUSTED", "SUSPENDED")
REVOCATION_REASONS = (
    "PROVIDER_SUSPENDED", "PROVIDER_TERMINATED", "PLAN_SUPERSEDED",
    "CASE_EXITED", "ADMIN_CORRECTION", "FAMILY_REQUEST", "WINDOW_EXPIRED",
)

VISIT_STATUSES = (
    "SCHEDULED", "DELIVERED", "FAMILY_CANCELLED", "NO_SHOW",
    "CANCELLED_PROVIDER", "CANCELLED_PROGRAM", "VOIDED",
)
VISIT_DOCUMENT_OUTCOMES = (
    "DELIVERED", "FAMILY_CANCELLED", "NO_SHOW", "CANCELLED_PROVIDER",
)
BILLING_STATUSES = (
    "PENDING", "ACCRUED", "EXEMPT", "CAPPED", "REVERSED", "CANCELLED_NO_CHARGE",
)
VOID_REASONS = ("DOCUMENTATION_ERROR", "DUPLICATE_ENTRY", "AUDIT_REVERSAL")

COST_SHARE_STATUSES = ("PROVISIONAL", "VERIFIED", "SUPERSEDED", "CLOSED")
COST_SHARE_LIVE = ("PROVISIONAL", "VERIFIED")
WAIVER_REASONS = ("HARDSHIP", "ADMIN_ERROR", "PROGRAM_POLICY")
TIER_CODES = ("TIER_0", "TIER_1", "TIER_2", "TIER_3")

CONTACT_METHODS = ("HOME_VISIT", "PHONE", "VIDEO", "EMAIL", "LETTER")
QUALIFYING_CONTACT_METHODS = ("HOME_VISIT", "PHONE", "VIDEO")
CONTACT_TYPES = (
    "MONTHLY_CHECK_IN", "SERVICE_REVIEW", "CRISIS", "TRANSITION_PLANNING",
)

TRANSITION_PLAN_STATUSES = (
    "DRAFT", "NOTIFIED", "OPT_OUT", "COMPLETE", "CANCELLED",
)
NOTIFICATION_COMPLIANCE = ("TIMELY", "LATE", "EARLY", "WAIVED_OPT_OUT")

# --------------------------------------------------------- serializer field sets
CHILD_FIELDS = (
    "id", "first_name", "last_name", "date_of_birth", "county_code",
    "primary_language", "third_birthday_date", "active_referral_count",
    "created_at", "updated_at", "version",
)

COORDINATOR_FIELDS = (
    "id", "full_name", "county_code", "language_codes",
    "max_weighted_caseload_points", "weighted_caseload_points",
    "active_case_count", "utilization_ratio", "status",
    "created_at", "updated_at", "version",
)

REFERRAL_FIELDS = (
    "id", "child_id", "primary_referral_source", "referral_received_date",
    "county_code", "presenting_concern", "interpreter_required",
    "coordinator_id", "assignment_date", "statutory_deadline_date", "status",
    "eligibility_status", "eligibility_determination_date",
    "initial_ifsp_meeting_date", "excluded_delay_days", "gross_elapsed_days",
    "net_elapsed_days", "initial_timeline_status", "case_weight_points",
    "entry_rating_social", "entry_rating_knowledge", "entry_rating_needs",
    "entry_outcomes_date", "exit_rating_social", "exit_rating_knowledge",
    "exit_rating_needs", "services_start_date", "exit_date", "exit_reason",
    "service_duration_days", "progress_category_social",
    "progress_category_knowledge", "progress_category_needs",
    "last_qualifying_contact_date", "monthly_contact_status",
    "service_gap_flag", "created_at", "updated_at", "version",
)

ASSESSMENT_FIELDS = (
    "id", "referral_id", "assessment_type", "scheduled_date", "setting_code",
    "natural_environment_justification", "domains_assessed",
    "evaluator_user_id", "status", "completion_date", "family_unavailable_days",
    "eligibility_recommendation", "created_at", "updated_at", "version",
)

IFSP_FIELDS = (
    "id", "referral_id", "ifsp_type", "meeting_date", "supersedes_ifsp_id",
    "authoring_coordinator_id", "natural_environment_justification", "status",
    "consent_scope", "consent_signed_date", "consent_user_id", "activated_date",
    "service_line_count", "non_natural_setting_line_count",
    "created_at", "updated_at", "version",
)

IFSP_SERVICE_FIELDS = (
    "id", "ifsp_id", "service_type", "setting_code",
    "natural_environment_justification", "frequency_per_month",
    "units_per_session", "unit_rate_cents", "planned_units_total",
    "family_fee_exempt", "declined_by_family", "units_committed",
    "units_pool_remaining", "units_delivered", "makeup_owed_units", "status",
    "created_at", "updated_at", "version",
)

PROVIDER_FIELDS = (
    "id", "agency_name", "qualified_service_types", "credential_expiry_date",
    "status", "suspension_reason_code", "suspended_date",
    "active_authorization_count", "created_at", "updated_at", "version",
)

AUTHORIZATION_FIELDS = (
    "id", "ifsp_service_id", "provider_id", "start_date", "end_date",
    "authorized_units", "unit_rate_cents", "units_consumed", "units_released",
    "units_remaining", "status", "revoked_date", "revocation_reason_code",
    "created_at", "updated_at", "version",
)

VISIT_FIELDS = (
    "id", "provider_authorization_id", "makeup_for_visit_id",
    "scheduled_start", "scheduled_end", "scheduled_units", "setting_code",
    "actual_units", "actual_start", "actual_end", "session_note",
    "documented_by_user_id", "documented_at_utc", "visit_status",
    "billing_status", "family_share_cents", "void_reason_code",
    "created_at", "updated_at", "version",
)

COST_SHARE_FIELDS = (
    "id", "referral_id", "effective_month", "household_size",
    "declared_annual_gross_income_cents", "verified_annual_gross_income_cents",
    "insurance_use_consent", "insurance_policy_id", "determined_by_user_id",
    "verification_date", "status", "waiver_reason_code",
    "fpl_threshold_cents", "fpl_percent", "tier_code", "coinsurance_rate",
    "monthly_cap_cents", "assessed_monthly_fee_cents", "insurance_offset_cents",
    "final_monthly_fee_cents", "effective_coinsurance_rate",
    "total_assessed_cents", "family_balance_cents", "family_waived_cents",
    "month_accrued_cents", "created_at", "updated_at", "version",
)

CONTACT_LOG_FIELDS = (
    "id", "referral_id", "contact_date", "contact_month", "contact_method",
    "contact_type", "summary", "qualifies_for_monthly_requirement",
    "created_at",
)

TRANSITION_PLAN_FIELDS = (
    "id", "ifsp_id", "target_conference_date", "conference_held_date",
    "transition_steps_count", "lea_code", "notification_date",
    "notification_lead_days", "notification_compliance", "family_opt_out",
    "opt_out_signed_date", "status", "created_at", "updated_at", "version",
)
