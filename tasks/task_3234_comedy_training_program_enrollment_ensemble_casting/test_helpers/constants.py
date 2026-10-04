"""Domain thresholds and constant values from the PRD."""

# Placement evaluation (PRD §3.3)
PORTFOLIO_PASS_THRESHOLD = 70
RECOGNIZED_INSTITUTIONS = ["iO", "UCB", "Groundlings", "Second City (other campus)"]

# Venue turnover buffer, minutes (PRD §2.9)
MIN_TURNOVER_MINUTES = 30

# Audition composite score weights (PRD §3.7)
COMPOSITE_WEIGHTS = {
    "scene_work": 0.4,
    "characters": 0.25,
    "musicality": 0.2,
    "game": 0.15,
}

# Ensemble casting selector pipeline bonus (PRD §3.8)
PIPELINE_BONUS = 0.5

# Default logical clock at server boot (PRD §2.4)
BOOT_CLOCK = "2026-09-01T00:00:00Z"

# Shared term window used by fixtures (PRD §3.1 / §3.4 refund tiers)
TERM_START = "2027-01-05T00:00:00Z"
TERM_END = "2027-03-15T00:00:00Z"
TERM_DROP_DEADLINE = "2027-01-12T00:00:00Z"

TEST_DEFAULTS = {
    "TUITION_CENTS": 10000,
    "CAPACITY": 4,
    "WEEKLY_HOURS": 3,
    "MAX_WEEKLY_HOURS": 20,
}
