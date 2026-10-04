"""Rounding helpers and the deterministic ordering keys.

PRD §2.6: every monetary quantity is an integer count of cents and every
fractional product is rounded half-up (a value exactly halfway rounds to the
larger one). Percentages are produced the same way. There is no other rounding:
sums are exact integer addition and no intermediate value is truncated.
"""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value) -> int:
    """Round a Decimal-friendly value to the nearest integer, halves up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate(numerator: int, denominator: int) -> int:
    """round_half_up(100 * numerator / denominator); caller handles denom == 0."""
    return round_half_up(Decimal(100) * Decimal(numerator) / Decimal(denominator))


def sort_key_created(row: dict):
    """Default list ordering (PRD §2.3): created_at ascending."""
    return (row.get("created_at") or "", row.get("id") or "")


def sort_key_exam_attempt(row: dict):
    """Scored attempts for a worker: sequence ascending."""
    return (row.get("sequence") or 0, row.get("created_at") or "")


def sort_key_worker_qualification(row: dict):
    return (row.get("created_at") or "", row.get("id") or "")


def sort_key_approved(row: dict):
    """Chronological spend / earning replay: approved_at ASC, sequence ASC."""
    return (row.get("approved_at") or "", row.get("sequence") or 0)


def sort_key_provisional(row: dict):
    """Provisional spend replay: deadline_at ASC, sequence ASC."""
    return (row.get("deadline_at") or "", row.get("sequence") or 0)


def sort_key_review_window(row: dict):
    """Auto-approval replay: review_expires_at ASC, sequence ASC."""
    return (row.get("review_expires_at") or "", row.get("sequence") or 0)


def sort_key_review_created(row: dict):
    """Read-back order for a review collection.

    PRD §2.3 pins list ordering to ``created_at`` ascending. Review rows
    appended by a single logical instant share that ``created_at`` (the clock
    is frozen between requests), and the append-only ledger's own narrative is
    chronological — §3.8 replays spend "in the order `approved_at` ascending",
    §3.9 lists the kinds as "approvals, rejections, and bonuses". A tie on the
    timestamp is therefore resolved by a fixed kind order so a collection never
    reports a later-created decision ahead of an earlier one.
    """
    kind_rank = {"APPROVAL": 0, "REJECTION": 1, "BONUS": 2}
    return (
        row.get("created_at") or "",
        kind_rank.get(row.get("kind"), 3),
        row.get("id") or "",
    )