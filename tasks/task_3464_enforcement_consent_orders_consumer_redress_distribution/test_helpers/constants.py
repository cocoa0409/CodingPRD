"""Domain constants — every value cross-checked against PRD prose.

Sources:
- PRD section 2.5: logical clock epoch and sweep rules.
- PRD section 3.1: complaint velocity thresholds (10 / 50, inclusive upward).
- PRD section 2.7 / 3.4: per-day civil penalty rates and 30-day projection.
- PRD section 3.6: loss cap 2,500,000; reserve ten percent, cap 500,000.
- PRD section 3.5: fund opening minimum 1,000,000; suspension ratio one-tenth.
- PRD section 3.7: check stale 90 days; reissue window 180 days; fraud text.
- PRD section 3.3: comment period closes exactly 30 days after opening.
- PRD section 3.8: cy pres minimum claim rate 0.60 (inclusive).
"""

# --- Logical clock (PRD section 2.5) ---------------------------------------
CLOCK_EPOCH_ISO = "2026-09-01T00:00:00Z"
# Canonical "comment period has closed" instant used by the standard pipeline:
# a period opened at the epoch closes exactly COMMENT_PERIOD_DAYS later.
DATE_COMMENT_CLOSE_ISO = "2026-10-01T00:00:00Z"

# --- Complaint velocity risk tier (PRD section 3.1) -------------------------
ELEVATED_MIN_COMPLAINTS = 10   # >= 10 and < 50 -> ELEVATED (exactly 10 qualifies)
CRITICAL_MIN_COMPLAINTS = 50   # >= 50 -> CRITICAL (exactly 50 qualifies)

# --- Civil penalty accrual (PRD sections 2.7 and 3.4) ------------------------
RATE_STANDARD_PER_DAY_CENTS = 1_000_000
RATE_AGGRAVATED_PER_DAY_CENTS = 4_353_000
RATE_EGREGIOUS_PER_DAY_CENTS = 5_000_000
PENALTY_RATES_PER_DAY_CENTS = {
    "STANDARD": RATE_STANDARD_PER_DAY_CENTS,
    "AGGRAVATED": RATE_AGGRAVATED_PER_DAY_CENTS,
    "EGREGIOUS": RATE_EGREGIOUS_PER_DAY_CENTS,
}
PROVISIONAL_PROJECTION_DAYS = 30  # provisional_days is fixed at 30

# --- Redress waterfall (PRD section 3.6) ------------------------------------
LOSS_CAP_CENTS = 2_500_000
ADMIN_RESERVE_RATE = 0.10
ADMIN_RESERVE_CAP_CENTS = 500_000

# --- Fund opening minimum (PRD section 3.5) ----------------------------------
FUND_OPEN_MINIMUM_CENTS = 1_000_000

# --- Residual disposition (PRD section 3.8) ----------------------------------
CY_PRES_MIN_CLAIM_RATE = 0.60  # exactly 0.60 qualifies as CY_PRES (>=)

# --- Check / comment timing (PRD sections 3.3, 3.7) --------------------------
CHECK_STALE_DAYS = 90
CHECK_REISSUE_WINDOW_DAYS = 180
COMMENT_PERIOD_DAYS = 30

# --- Inability-to-pay suspension (PRD section 3.5) ---------------------------
SUSPENSION_MAX_ASSET_RATIO = 0.10  # sworn assets must be strictly below 10%

# --- Fraud warning stamped on every issued check (PRD section 3.7, verbatim) -
FRAUD_WARNING_TEXT = (
    "WARNING: The FTC never requires payment or personal information to cash a "
    "refund check. Anyone who demands money or information in exchange for your "
    "refund is a scammer."
)

# --- Test-data defaults (not PRD rules; shared fixture defaults) -------------
TEST_DEFAULTS = {
    "COMPANY_LEGAL_NAME": "Acme Gadgets Inc",
    "COMPANY_COMPLAINT_COUNT": 60,  # -> CRITICAL tier, keeps MARKET_MONITORING open
    "INVESTIGATION_SUMMARY": "Deceptive billing practices",
    "ORDER_MONETARY_RELIEF_CENTS": 3_000_000,
    "ORDER_MAX_PENALTY_CENTS": 500_000_000,
    "ORDER_REPORTING_FREQUENCY_MONTHS": 6,
    "ORDER_MONITORING_TERM_YEARS": 5,
    "ORDER_CONDUCT_PROHIBITIONS": ["NO_UNSUBSTANTIATED_CLAIMS"],
    "CID_SUBJECT_MATTER": "All pricing spreadsheets 2024-2026",
    "CID_RESPONSE_DUE_DATE": "2026-09-15T00:00:00Z",
    "REPORT_DOCUMENT_REF": "doc-report-1",
    "CLAIMANT_FULL_NAME": "Ann Apple",
    "CLAIMANT_EMAIL": "ann@example.com",
    "RESIDUAL_RECIPIENT_NAME": "Consumer Education Trust",
    "VOIDED_REASON": "uncashed and undeliverable",
    "DENIAL_REASON": "Insufficient documentation of loss",
    "DEFICIENCY_NOTES": "Section 4 omits refund ledgers",
}

# A syntactically valid but never-allocated UUID for 404 probes
# (the framework's NON_EXISTENT_UUID is re-exported via __init__ as well).
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
