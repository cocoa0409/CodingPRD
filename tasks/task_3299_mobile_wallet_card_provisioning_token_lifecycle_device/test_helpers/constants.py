"""Domain thresholds — numeric constants from the PRD."""

# Logical clock
CLOCK_START = "2026-09-01T00:00:00Z"

# Provisioning session window (PRD: expires_at is exactly 24 hours after created_at)
SESSION_TTL_HOURS = 24

# Authorization gates
PER_AUTH_CAP_CENTS = 100000
DECLINE_STREAK_SUSPEND_THRESHOLD = 3

# Risk score constants
RISK_OPEN_DISPUTE_BONUS = 15
RISK_DEVICE_LOST_BONUS = 25
RISK_CAP = 100

# Verification codes: the implementation contract used by the design anchors is
# that these codes satisfy the challenge; "000000" is the canonical wrong code.
GOOD_CODE_1 = "111111"
GOOD_CODE_2 = "222222"
GOOD_CODE_3 = "333333"
BAD_CODE = "000000"

# Cryptogram literals that force a decline decision
CRYPTOGRAM_DECLINE = "DECLINE"
CRYPTOGRAM_DECLINE_FRAUD = "DECLINE_FRAUD"
