"""Domain thresholds and defaults for the Multimodal Shipment Visibility API.

Every number here comes from the contract's own rules: the per-mode confidence
bases, the mode delay tolerances, the per-mode free-time allowances, the grace
minutes, the escalation SLA, the quality weights and the neutral quality input
for never-scored connections.
"""

# The instant the logical clock reports on a fresh deployment.
BASE_CLOCK = "2026-09-01T00:00:00Z"

# § Channel cadence: required heartbeat cadence per channel, in minutes.
CADENCE_MINUTES = {
    "TELEMATICS": 15,
    "TMS": 240,
    "MANUAL": 1440,
}

# § Arrival confidence: per-mode base halfwidth in minutes.
CI_BASE_HALFWIDTH_MINUTES = {
    "OCEAN": 720,
    "RAIL": 360,
    "PARCEL": 60,
    "TRUCKLOAD": 120,
}

# A never-scored connection contributes a neutral quality input of 50.
UNSET_QUALITY_NEUTRAL = 50

# STALE shipments carry a widened confidence interval.
STALE_CI_MULTIPLIER = 1.5

# § Delay risk: per-mode tolerance in minutes; the boundary is strict.
TOLERANCE_MINUTES = {
    "OCEAN": 720,
    "RAIL": 360,
    "PARCEL": 30,
    "TRUCKLOAD": 60,
}

# An OPEN HIGH alert escalates once its age exceeds this many minutes.
ESCALATION_SLA_MINUTES = 240

# § Detention: per-mode free-time allowance in minutes plus the adherent grace.
FREE_TIME_MINUTES = {
    "OCEAN": 240,
    "RAIL": 360,
    "PARCEL": 0,
    "TRUCKLOAD": 120,
}
GRACE_MINUTES = 15

# § Quality gate: activation requires the authoritative score to reach this.
QUALITY_GATE_MINIMUM = 70

# § Health bands: authoritative score thresholds.
HEALTHY_MINIMUM = 70
DEGRADED_MINIMUM = 40

# § Identity match: component weights and the strict confirm gate.
W_PO_NUMBER = 0.5
W_BOOKING_REFERENCE = 0.4
W_DESTINATION = 0.1
CONFIRM_THRESHOLD = 0.90

# Authoritative epoch quality weights.
W_TIMELINESS = 0.40
W_COMPLETENESS = 0.35
W_CADENCE = 0.25

# Instantaneous quality weights (latest heartbeat only).
W_INSTANT_TIMELINESS = 0.60
W_INSTANT_COMPLETENESS = 0.40

# Alert queue names per severity.
QUEUE_FOR_HIGH = "CS_TIER2"
QUEUE_FOR_MEDIUM = "CS_TIER1"
