"""Domain thresholds — numeric constants quoted verbatim from PRD prose.

Only constants actually referenced by the test suite live here. Sources:
- §2.9  "cases convert to dozens at exactly 30 dozen per case"
- §3.6  grade thresholds 95.0 / 70.0 (inclusive lower bounds)
- §3.8  "The fill threshold is the `committed_dozens` multiplied by 0.85"
"""

# §2.9 — physical conversion at collection
DOZENS_PER_CASE = 30

# §3.6 — grading thresholds (inclusive lower bounds)
GRADE_AA_MIN = 95.0
GRADE_B_MIN = 70.0

# §3.8 — commitment fill threshold
MIN_FILL_RATE = 0.85
