"""Domain thresholds — numeric constants from the PRD's calculations."""

THRESHOLDS = {
    # Kitchen admission: the number of orders in PREPARING must be fewer than
    # eight; exactly eight rejects the ninth.
    "MAX_PREPARING": 8,
    # Rush-window draft expiry: a DRAFT whose check-in is older than two rush
    # windows is cancelled when the rush advances.
    "DRAFT_EXPIRY_RUSH_WINDOWS": 2,
    # Congestion: lane is CONGESTED when stalls_available <= ceil(capacity * 0.20).
    "CONGESTION_FRACTION": 0.20,
}

TEST_DEFAULTS = {
    "TARGET_SECONDS": 600,
    "DRIVE_THRU_TARGET_SECONDS": 300,
    "STALL_CAPACITY_SMALL": 2,
    "STALL_CAPACITY": 4,
    "STALL_CAPACITY_KITCHEN": 20,
    "MAX_TRAYS": 3,
    # Startup default of the logical clock.
    "CLOCK_START": "2026-09-01T00:00:00Z",
    # 13:00Z == 08:00 local in America/Chicago on 2026-09-01 (outside the
    # 14:00-16:00 happy-hour window).
    "CLOCK_0800_LOCAL": "2026-09-01T13:00:00Z",
    # 19:00Z == 14:00 local (window start, inclusive).
    "CLOCK_1400_LOCAL": "2026-09-01T19:00:00Z",
    # 07:00Z == 02:00 local (exclusive end of a 22:00-02:00 midnight-wrapping window).
    "CLOCK_0200_LOCAL": "2026-09-01T07:00:00Z",
}
