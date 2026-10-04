"""The acceptance-gap engine (PRD §3.2, §3.8).

Declined attempts and upheld complaints both feed the same regional,
industry-scoped gap; a gap in turn feeds the merchant acceptance cycle.
"""

from clock import format_iso, parse_iso
from errors import (
    ERR_COMPLAINT_ALREADY_ENROLLED,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ApiError,
)

ACCEPTANCE_GAP_DECLINE_MIN = 3
MIN_DECLINED_CENTS = 50
GAP_WINDOW_DAYS = (30, 60, 90)


def count_declines(store, region_code, industry_category_id, window_start, window_end):
    """Count MERCHANT_NOT_ACCEPTED declines for a region + industry in a half-open window."""
    counted = []
    for attempt in store.declined_attempts.values():
        if attempt["decline_reason"] != "MERCHANT_NOT_ACCEPTED":
            continue
        merchant = store.merchants.get(attempt["merchant_id"])
        if merchant is None:
            continue
        if merchant["region_code"] != region_code:
            continue
        if merchant["industry_category_id"] != industry_category_id:
            continue
        occurred = parse_iso(attempt["occurred_at"])
        if occurred is None:
            continue
        if window_start <= occurred < window_end:
            counted.append(attempt)
    return counted


def apply_gap_counters(gap, counted):
    gap["decline_count"] = len(counted)
    volume = sum(item["attempted_amount_cents"] for item in counted)
    floor = gap["decline_count"] * MIN_DECLINED_CENTS
    gap["declined_volume_cents"] = max(volume, floor)
    if gap["decline_count"] >= ACCEPTANCE_GAP_DECLINE_MIN:
        gap["qualified_status"] = "PROSPECTING"
    elif gap["decline_count"] >= 1:
        gap["qualified_status"] = "BELOW_THRESHOLD"
    else:
        gap["qualified_status"] = "DORMANT"


def find_gap(store, region_code, industry_category_id):
    for gap in store.acceptance_gaps.values():
        if (
            gap["region_code"] == region_code
            and gap["industry_category_id"] == industry_category_id
        ):
            return gap
    return None


def open_window(store, region_code, industry_category_id):
    """An AcceptanceGap row for the merchant's region and industry.

    The uphold path opens the gap "through the same gap engine that consumes
    declined attempts", so this is the gap the declined-attempt re-enrolment hop
    reads as its "open window covering the merchant's region and industry".
    """
    return find_gap(store, region_code, industry_category_id)


def new_gap_row(store, region_code, industry_category_id, window_start, window_end,
                window_days):
    gap_id = store.new_id()
    now = store.clock.now()
    return {
        "id": gap_id,
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "_seq": store.next_created_seq(),
        "region_code": region_code,
        "industry_category_id": industry_category_id,
        "window_start": window_start,
        "window_end": window_end,
        "window_days": window_days,
        "decline_count": 0,
        "declined_volume_cents": 0,
        "qualified_status": "DORMANT",
        "sweep_index": 0,
    }


def windows_merge(existing, window_start, window_end, window_days):
    """Type-dependent interval merge (PRD §3.2)."""
    existing_start = parse_iso(existing["window_start"])
    existing_end = parse_iso(existing["window_end"])
    if existing_start is None or existing_end is None:
        return False
    if window_days == 30:
        # Overlap by at least one day: the new start precedes the existing end
        # and the new end follows the existing start.
        return window_start < existing_end and window_end > existing_start
    if window_days == 60:
        # Edge-adjacent exactly.
        return window_start == existing_end
    # A ninety-day window is a standalone measurement and never merges.
    return False


def rollup_gap(store, region_code, industry_category_id, window_start, window_end,
               window_days):
    """Roll up (and, under the merge rules, fold into) a region+industry gap."""
    counted = count_declines(store, region_code, industry_category_id, window_start,
                             window_end)

    target = None
    for gap in store.acceptance_gaps.values():
        if (
            gap["region_code"] == region_code
            and gap["industry_category_id"] == industry_category_id
        ):
            if windows_merge(gap, window_start, window_end, window_days):
                target = gap
                break

    if target is None:
        target = new_gap_row(store, region_code, industry_category_id, window_start,
                             window_end, window_days)
        store.acceptance_gaps[target["id"]] = target
    else:
        merged_start = min(parse_iso(target["window_start"]), window_start)
        merged_end = max(parse_iso(target["window_end"]), window_end)
        target["window_start"] = merged_start
        target["window_end"] = merged_end
        target["window_days"] = window_days
        target["updated_at"] = store.clock.now()
        target["version"] = target["version"] + 1

    apply_gap_counters(target, counted)
    target["sweep_index"] = store.latest_sweep_index
    target["updated_at"] = store.clock.now()

    requalify_dormant_merchants(store, target)
    return target


def requalify_dormant_merchants(store, gap):
    """A gap with qualified_status PROSPECTING re-enters covered dormant outlets."""
    if gap["qualified_status"] != "PROSPECTING":
        return
    for merchant in store.merchants.values():
        if merchant["acceptance_status"] != "DORMANT":
            continue
        if merchant["region_code"] != gap["region_code"]:
            continue
        if merchant["industry_category_id"] != gap["industry_category_id"]:
            continue
        merchant["acceptance_status"] = "PROSPECT"
        merchant["updated_at"] = store.clock.now()
        merchant["version"] = merchant["version"] + 1


def maybe_reenter_from_decline(store, merchant):
    """The cycle-closing hop: DORMANT -> PROSPECT on a MERCHANT_NOT_ACCEPTED decline."""
    if merchant["acceptance_status"] != "DORMANT":
        return False
    gap = find_gap(store, merchant["region_code"], merchant["industry_category_id"])
    if gap is None:
        return False
    if gap["qualified_status"] != "PROSPECTING":
        return False
    if store.latest_sweep_index != merchant["status_version"]:
        return False
    merchant["acceptance_status"] = "PROSPECT"
    merchant["updated_at"] = store.clock.now()
    merchant["version"] = merchant["version"] + 1
    return True


def uphold_complaint_gap(store, complaint):
    """Upholding opens a fresh gap keyed on the merchant's region + industry."""
    merchant = store.merchants.get(complaint["merchant_id"])
    if merchant is None:
        raise ApiError(ERR_NOT_FOUND)
    if merchant["acceptance_status"] == "PROSPECT":
        raise ApiError(ERR_COMPLAINT_ALREADY_ENROLLED)

    window_start = store.clock.now()
    window_end = window_start + _days(30)
    existing = find_gap(store, merchant["region_code"], merchant["industry_category_id"])
    if existing is not None:
        existing["window_start"] = min(parse_iso(existing["window_start"]), window_start)
        existing["window_end"] = max(parse_iso(existing["window_end"]), window_end)
        existing["window_days"] = 30
        existing["updated_at"] = store.clock.now()
        existing["version"] = existing["version"] + 1
        gap = existing
    else:
        gap = new_gap_row(store, merchant["region_code"],
                          merchant["industry_category_id"], window_start, window_end, 30)
        store.acceptance_gaps[gap["id"]] = gap

    counted = count_declines(store, gap["region_code"], gap["industry_category_id"],
                             parse_iso(gap["window_start"]), parse_iso(gap["window_end"]))
    apply_gap_counters(gap, counted)
    gap["sweep_index"] = store.latest_sweep_index

    # The covered dormant merchant re-enters prospecting through that gap.  It
    # may never be moved out of an already-enrolled state -- only a DORMANT
    # outlet is re-entered.
    for candidate in store.merchants.values():
        if candidate["acceptance_status"] != "DORMANT":
            continue
        if candidate["region_code"] != gap["region_code"]:
            continue
        if candidate["industry_category_id"] != gap["industry_category_id"]:
            continue
        candidate["acceptance_status"] = "PROSPECT"
        candidate["updated_at"] = store.clock.now()
        candidate["version"] = candidate["version"] + 1


def _days(count):
    from datetime import timedelta

    return timedelta(days=count)


__all__ = [
    "ACCEPTANCE_GAP_DECLINE_MIN",
    "MIN_DECLINED_CENTS",
    "GAP_WINDOW_DAYS",
    "apply_gap_counters",
    "count_declines",
    "find_gap",
    "format_iso",
    "maybe_reenter_from_decline",
    "new_gap_row",
    "open_window",
    "requalify_dormant_merchants",
    "rollup_gap",
    "uphold_complaint_gap",
    "windows_merge",
    "ApiError",
    "ERR_INVALID_STATE",
]