"""Domain constants shared by the helpers: the service prefix and the logical clock."""

API_PREFIX = "/backup-provider"

# The logical clock instant every process starts at; never the host wall clock.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"