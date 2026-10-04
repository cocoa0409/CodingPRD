"""Domain constants — only what the test suite actually references.

All numeric thresholds (royalty percentages, defect bands, slow-mover floor,
dormancy days, descale factors) are asserted as PRD-stated literals directly
at the call sites that exercise them, so they are not duplicated here.
"""

# Logical clock (PRD §2.4): fixed startup default, never wall-clock.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
