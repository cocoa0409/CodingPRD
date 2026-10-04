"""Domain thresholds and pinned constants used by the rate, cost-share and
payout arithmetic, plus the fixture defaults shared across tests."""

# ─── Rate resolution ──────────────────────────────────
NEW_CLINICIAN_DIFFERENTIAL_PCT = 0.90
NEW_CLINICIAN_DIFFERENTIAL_WINDOW_DAYS = 90
GEOGRAPHY_DIFFERENTIAL = 0.90
# The operative activation test is the session start instant, per the PRD; the
# differential fires at or after this instant and never before it.
GEOGRAPHY_DIFFERENTIAL_EFFECTIVE_FROM = "2026-07-01T00:00:00Z"
NON_ELIGIBLE_RATE_CENTS = 0
GEOGRAPHY_FLAT_BREAKPOINT_CENTS = 10_000
GEOGRAPHY_FLAT_REDUCTION_CENTS = 1_000

# ─── Cost share ───────────────────────────────────────
COPAY_OFFSET_CENTS = 500
COPAY_OFFSET_MIN_COINSURANCE_CENTS = 500

# ─── Claims ───────────────────────────────────────────
PAYER_ALLOWED_RATIO = 0.80

# ─── Payout lines ─────────────────────────────────────
PENDING_LINE_NET_FLOOR_CENTS = 0

# ─── Posture / caseload / temporal ────────────────────
BILLING_POSTURE_MIN_ENROLLMENTS = 1
WAITLIST_UTILIZATION_PCT = 90
CONTINUITY_GRACE_DAYS = 30
CONTINUITY_EXTENSION_DAYS = 7
ENROLLMENT_WINDOW_MIN_DAYS = 1
SESSION_HANDOVER_BUFFER_MINUTES = 15

# ─── Signing / documentation ──────────────────────────
NOTE_DURATION_MIN_MINUTES = 45
NOTE_DURATION_MAX_MINUTES = 120

# ─── Logical clock ────────────────────────────────────
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
CLOCK_EARLY = "2026-01-05T00:00:00Z"
CLOCK_ONBOARD = "2026-03-01T00:00:00Z"
CLOCK_DELIVERY = "2026-06-20T00:00:00Z"

# ─── Enumerations quoted from the PRD ─────────────────
LICENSE_TYPES = ["LCSW", "LMFT", "LPC", "LMHC", "PSY_D", "PHD"]
MODALITIES = ["VIDEO", "PHONE", "IN_PERSON"]
PAYOUT_SCHEDULES = ["WEEKLY", "BIWEEKLY", "SEMIMONTHLY"]
DENIAL_CODES = [
    "TIMELY_FILING",
    "NOT_COVERED",
    "MISSING_DOCUMENTATION",
    "AUTHORIZATION_REQUIRED",
    "DUPLICATE",
]

# ─── Shared fixture defaults ──────────────────────────
DEFAULTS = {
    "PAYER_NAME": "Pacific Assurance Exchange",
    "PAYER_CODE": "PAX",
    "MIN_MALPRACTICE_COVERAGE_CENTS": 100_000_000,
    "TIMELY_FILING_DAYS": 90,
    "CREDENTIALING_SLA_DAYS": 14,
    "ALLOWED_CPT_CODES": ["90837"],
    "CPT_CODE": "90837",
    "RATE_CENTS": 15_000,
    "RATE_SET_VERSION": 1,
    "CONTRACT_RATE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "CLINICIAN_NAME": "Dana Reyes",
    "CLINICIAN_STATE": "CA",
    "CASELOAD_TARGET": 8,
    "LICENSE_NUMBER": "LCSW-CA-77120",
    "LICENSE_EXPIRES_ON": "2027-06-30T00:00:00Z",
    "COVERAGE_CENTS": 500_000_000,
    "POLICY_EFFECTIVE_ON": "2026-01-01T00:00:00Z",
    "POLICY_EXPIRES_ON": "2027-01-01T00:00:00Z",
    "ENROLLMENT_EFFECTIVE_FROM": "2026-02-01T00:00:00Z",
    "PATIENT_NAME": "Priya Anand",
    "MEMBER_ID": "MBR-4410",
    "PLAN_CODE": "PPO-2000",
    "DEDUCTIBLE_CENTS": 100_000,
    "COINSURANCE_RATE": 0.20,
    "OOP_MAX_CENTS": 200_000,
    "VERIFICATION_DEDUCTIBLE_REMAINING_CENTS": 5_000,
    "VERIFICATION_COPAY_CENTS": 2_500,
    "VERIFICATION_OOP_REMAINING_CENTS": 200_000,
    "MODALITY": "VIDEO",
    "SESSION_MINUTES": 60,
    "NARRATIVE": "Patient reports reduced anxiety frequency since the prior course of care.",
    "DIAGNOSIS_CODE": "F41.1",
    # Availability: two whole-day blocks (Tue and Wed, 08:00–18:00 UTC). The
    # suite's canonical session instants fall on both a Tuesday and a Wednesday,
    # so a single-weekday block would leave half of them unavailable to a
    # default-created clinician — an artefact of the fixture, not of the design.
    "AVAILABILITY_BLOCKS": [
        {"weekday": 2, "start_minute": 480, "end_minute": 1080},
        {"weekday": 3, "start_minute": 480, "end_minute": 1080},
    ],
    "AVAILABILITY_WEEKDAY": 2,
    "AVAILABILITY_START_MINUTE": 480,
    "AVAILABILITY_END_MINUTE": 1080,
    "AVAILABILITY_TOTAL_MINUTES": 600,
}