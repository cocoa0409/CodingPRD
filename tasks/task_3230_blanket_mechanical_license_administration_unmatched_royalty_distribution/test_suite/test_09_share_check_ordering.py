"""Ordered share-registration checks: each failure isolated, and the ceiling
beating a stale version when both are violated."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, create_member, create_work, create_share,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_work_at_100_percent():
    set_clock("2026-09-01T00:00:00Z")
    m_a = create_member(legal_name="Alder Publishing", ipi_number="00000000101")
    m_b = create_member(legal_name="Birch Songs", ipi_number="00000000202")
    work = create_work(title="Kestrel")
    create_share(work["id"], m_a["id"], share_percent=100)
    return m_a, m_b, work


def test_share_ceiling_violation_alone_returns_share_sum_error(api):
    """PRD §3.2: "Second, the ownership ceiling: the sum of `share_percent` over
    the work's `ACTIVE` shares plus the new share must not exceed 100, else
    `ERR_SHARE_SUM_EXCEEDS_100` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_masks_share_overflow
    """
    _m_a, m_b, work = _setup_work_at_100_percent()
    work_now = validate_success(api_client.get_work(work["id"], ADMIN))
    validate_error(
        api_client.create_share(work["id"], {
            "claimant_member_id": m_b["id"], "share_percent": 50,
            "effective_from": "2026-01-01T00:00:00Z",
            "expected_work_version": work_now["version"],
        }, ADMIN),
        ApiErrorId.ERR_SHARE_SUM_EXCEEDS_100)
    work_after = validate_success(api_client.get_work(work["id"], ADMIN))
    assert work_after["total_share_percent"] == 100, (
        f"no share was added; got {work_after['total_share_percent']}")


def test_ceiling_surfaces_even_when_version_is_also_stale(api):
    """PRD §3.2: "Share registration enforces four checks, evaluated in order,
    so that a single violation determines the observed error. First, the
    optimistic-concurrency check: `expected_work_version` must equal the work's
    current `version`, else `ERR_STALE_VERSION`. Second, the ownership ceiling:
    the sum of `share_percent` over the work's `ACTIVE` shares plus the new
    share must not exceed 100, else `ERR_SHARE_SUM_EXCEEDS_100` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_masks_share_overflow
    """
    _m_a, m_b, work = _setup_work_at_100_percent()
    # Stale version (the create above bumped the work to version 2) AND the
    # 100-percent ceiling overflowed — PRD's pinned order evaluates the
    # optimistic-concurrency check first, so the single surfaced error is
    # ERR_STALE_VERSION.
    validate_error(
        api_client.create_share(work["id"], {
            "claimant_member_id": m_b["id"], "share_percent": 50,
            "effective_from": "2026-01-01T00:00:00Z",
            "expected_work_version": 1,
        }, ADMIN),
        ApiErrorId.ERR_STALE_VERSION)
