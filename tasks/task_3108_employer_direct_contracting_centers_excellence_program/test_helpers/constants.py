"""Domain thresholds and shared defaults used across the test suite."""
import itertools

# Logical clock instant pinned at the start of every scenario (PRD §2.7).
CLOCK_START = "2026-09-01T00:00:00Z"

# Quiet-tail days added beyond the warranty end before auto-closure (PRD §3.5).
QUIET_TAIL_DAYS = 7

# 30-day reprice prior-notice rule (PRD §3.4).
REPRICE_NOTICE_DAYS = 30

# Baseline rates used by the shared rate book.
RATES = {
    "ORTHO_JOINT": 2500000,
    "CARDIAC": 9000000,
    "BARIATRIC": 4000000,
    "SPINE": 6000000,
}

# Unique-key generator so parallel test processes never collide on
# uniqueness-constrained fields (ein, book_code, member_id, intake_request_id).
_counter = itertools.count(1)


def unique_token(prefix: str) -> str:
    """Return a process-unique token, e.g. unique_token('E') -> 'E-000123'."""
    return f"{prefix}-{next(_counter):06d}"
