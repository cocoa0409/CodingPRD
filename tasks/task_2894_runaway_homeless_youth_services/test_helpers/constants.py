"""Domain thresholds and numeric constants drawn from the PRD's computations.

Every value here is stated in the PRD prose; nothing is invented. Money is an
integer count of cents and every ratio is an integer count of basis points,
where 10000 basis points is the whole.
"""

# The logical clock starts here and only ever moves forward (PRD 2.5).
CLOCK_START = "2026-08-01T00:00:00.000Z"

BASIS_POINTS_WHOLE = 10000

THRESHOLDS = {
    # Trafficking risk scoring and tiering (PRD 3.1, 3.2)
    "TIER_ELEVATED_SCORE": 30,
    "TIER_CRITICAL_SCORE": 60,
    "RISK_SCORE_CAP": 100,
    "DECAY_PCT_PER_WEEK": 10,
    "DAYS_PER_WEEK": 7,
    # Admission priority score (PRD 3.3)
    "PRIORITY_ADULT_AGE": 18,
    "PRIORITY_AGE_WEIGHT": 4,
    "PRIORITY_RISK_CAP": 40,
    "PRIORITY_ENGAGEMENT_STEP": 5,
    "PRIORITY_ENGAGEMENT_CAP": 20,
    "PRIORITY_EXPOSURE_BASE": 15,
    "PRIORITY_CRITICAL_BUMP": 10,
    "PRIORITY_SCORE_CAP": 100,
    "RESTRICTED_PRIORITY_FLOOR": 60,
    # Program posture (PRD 2.6)
    "RESTRICTED_UTILIZATION_BP": 9000,
    "FROZEN_OVERDUE_COUNT": 2,
    "RESTRICTED_OVERDUE_COUNT": 1,
    # Billable nights (PRD 3.5)
    "NOON_CUTOFF_UTC_HOUR": 12,
    "MAX_EXTENSIONS": 2,
    # Guardian notification (PRD 3.3, 3.4)
    "NOTIFICATION_DUE_HOURS": 24,
    # Reunification (PRD 3.6)
    "MAX_MEDIATION_ROUNDS": 3,
    "MEDIATION_COOLDOWN_HOURS": 72,
    "AFTERCARE_WINDOW_HOURS": 72,
    "REQUIRED_AFTERCARE_CONTACTS": 3,
    "DECLINED_CASE_CLOSE_HOURS": 168,
    # Admission abandonment during the census (PRD 3.3, 3.10)
    "PENDING_SCREENING_DENY_HOURS": 72,
    # Transitional living duration allowance (PRD 3.7)
    "HAIRCUT_RATIO_BP": 7500,
    "NOTICE_LEAD_DAYS": 30,
    "LIFE_SKILLS_HOURS_MIN": 1,
    "LIFE_SKILLS_HOURS_MAX": 40,
    # Savings (PRD 3.8)
    "MATCH_CAP_CENTS": 50000,
    "DAYS_PER_SAVINGS_MONTH": 30,
    "PROBATION_NOTICE_REVIEWS": 2,
    # Governance (PRD 3.9)
    "ADOPTION_RATIO_BP": 5000,
    "ADOPTION_MIN_SUPPORT": 2,
    # Pagination (PRD 2.3)
    "PAGE_LIMIT_DEFAULT": 10,
    "PAGE_LIMIT_MIN": 1,
    "PAGE_LIMIT_MAX": 100,
    "PAGE_OFFSET_MIN": 0,
}

# Indicator weights shared by the screening snapshot and the decaying history
# score (PRD 3.1).
INDICATOR_WEIGHTS = {
    "THIRD_PARTY_CONTROL": 30,
    "QUOTA_DEBT": 25,
    "COMMERCIAL_SEX": 40,
    "DOCUMENT_WITHHELD": 20,
    "RECRUITER_PRESENT": 15,
    "CURFEW_ENFORCED": 10,
}

# Life-skills milestone bonus in days, keyed by the credited-hours floor
# (PRD 3.7).
LIFE_SKILLS_MILESTONES = ((60, 90), (40, 60), (20, 30), (0, 0))

TEST_DEFAULTS = {
    "PROGRAM_NAME": "Harbor House Emergency Shelter",
    "TLP_PROGRAM_NAME": "Beacon Transitional Living",
    "BED_CAPACITY": 4,
    "MIN_AGE_YEARS": 12,
    "MAX_AGE_YEARS": 17,
    "TLP_MIN_AGE_YEARS": 16,
    "TLP_MAX_AGE_YEARS": 21,
    "MAX_STAY_NIGHTS": 21,
    "MAX_PLACEMENT_DAYS": 540,
    "SAVINGS_MATCH_RATE_BP": 2500,
    "REQUIRED_SAVINGS_RATE_BP": 2000,
    "FIRST_NAME": "Ava",
    "LAST_NAME": "Nguyen",
    "DATE_OF_BIRTH": "2012-05-04",
    "SCHOOL_NAME": "Riverbend High School",
    "HOUSEHOLD_LABEL": "Nguyen maternal household",
    "PROPOSAL_TITLE": "Later weekend curfew for the house",
    "MONTHLY_INCOME_CENTS": 120000,
}
