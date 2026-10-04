"""Domain thresholds — numeric constants from PRD calculations."""

# plasma volume bands (PRD §3.4)
BAND_T1_MAX_KG = 68.0
BAND_T2_MAX_KG = 79.0
BAND_T3_MAX_KG = 110.0
VOL_T1_ML = 625
VOL_T2_ML = 690
VOL_T3_ML = 825
VOL_T4_ML = 880

# abort payout floor (PRD §3.8)
MIN_ABORT_PAYOUT_CENTS = 500

# tax reporting threshold (PRD §2.6)
TAX_REPORTING_THRESHOLD_CENTS = 60000

# frequency / gap (PRD §3.4)
ROLLING_FREQUENCY_DAYS = 7
FREQUENCY_MAX_PER_WINDOW = 2
MIN_INTER_DONATION_HOURS = 48

# applicant window (PRD §3.7)
APPLICANT_WINDOW_DAYS = 180

# look-back horizon (PRD §3.6)
LOOKBACK_WINDOW_DAYS = 180

# observation dwell (PRD §3.5)
OBSERVATION_MINUTES = 15

# severe-reaction auto-deferral (PRD §3.9)
SEVERE_REACTION_DEFERRAL_DAYS = 7

# screening expiry (PRD §3.3)
SCREENING_EXPIRY_HOURS = 24

# donation no-show (PRD §3.5)
NO_SHOW_HOURS = 6

# logical clock default (PRD §2.4)
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
