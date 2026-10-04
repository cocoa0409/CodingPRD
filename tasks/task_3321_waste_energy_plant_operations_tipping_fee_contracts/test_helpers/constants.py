"""Domain thresholds — numeric constants from the PRD calculations."""

# Tip-floor daily allocation (PRD §3.3)
DAILY_CAPACITY_TONNES = 1000

# Steam and ash (PRD §3.6)
STEAM_EFFICIENCY_TPH_PER_MW = 0.32
ASH_FRACTION = 0.25
SECONDS_PER_HOUR = 3600
KG_PER_TONNE = 1000
SECONDS_PER_DAY = 86400

# Put-or-pay (PRD §3.11)
MONTHS_PER_YEAR = 12

# Logical clock startup default (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"
