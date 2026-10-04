"""Domain thresholds and test defaults from the PRD's numeric rules."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

CLOCK_START = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Fee and fine constants (PRD §3.5, §3.6)
    "SEVERITY_MULTIPLIER_MINOR": 1,
    "SEVERITY_MULTIPLIER_MAJOR": 2,
    "SEVERITY_MULTIPLIER_CRITICAL": 3,
    "DISPUTE_FEE_CENTS": 1500,
    "CASE_PROCESSING_FEE_CENTS": 500,
    "ARBITRATION_FEE_CENTS": 25000,
    # Fraud monitoring (PRD §3.8)
    "MERCHANT_FRAUD_THRESHOLD_BPS": 100,
    "ACQUIRER_FRAUD_THRESHOLD_BPS": 50,
    # Temporal windows in days (PRD §3.6, §3.8)
    "EVIDENCE_WINDOW_DAYS": 30,
    "ARBITRATION_WINDOW_DAYS": 45,
    "REMEDIATION_WINDOW_DAYS": 60,
}

TEST_DEFAULTS = {
    "LEGAL_NAME": "Test Bank",
    "PARTICIPANT_NAME": "Participant Co",
    "PROGRAM_NAME": "Test Program",
    "MCC": "5411",
    "REGION": "NA",
    "CURRENCY": "USD",
    "DECLARED_VOLUME_CENTS": 10_000_000,
    "REASON_CODE": "10.4",
    "SUSPENSION_REASON": "COMPLIANCE_HOLD",
    # Window covering the default logical clock at server startup
    # (2026-09-01T00:00:00Z): opens before, closes after.
    "WINDOW_DATE": "2026-09-01",
    "WINDOW_OPENS_AT": "2026-08-31T23:00:00Z",
    "WINDOW_CLOSES_AT": "2026-09-02T00:00:00Z",
}
