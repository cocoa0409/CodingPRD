"""Domain thresholds — numeric constants from PRD §2.9 / §3 calculations."""

# PRD §3.2 utilization aggregation
WINDOW_DAYS = 7
P95_QUANTILE = 0.95
SUSTAINED_FLOOR_RATIO = 0.5

# PRD §2.9 channel arithmetic
QAM_CHANNEL_MHZ = 6
DOCSIS_CHANNEL_MBPS = 38

# PRD §2.9 upstream lookup
UPSTREAM_CAPACITY_MBPS = {
    "LEGACY": 27,
    "MID_SPLIT": 108,
    "HIGH_SPLIT": 204,
}

# PRD §3.5 wave spacing
WAVE_GAP_DAYS = 7

# PRD §3.9 recency boost
RECENCY_BOOST = 40
RECENCY_WEIGHT = 0.6

THRESHOLDS = {
    "WINDOW_DAYS": WINDOW_DAYS,
    "WAVE_GAP_DAYS": WAVE_GAP_DAYS,
    "UPSTREAM_LEGACY_MBPS": 27,
    "UPSTREAM_MID_SPLIT_MBPS": 108,
    "UPSTREAM_HIGH_SPLIT_MBPS": 204,
}
