"""Half-open interval semantics on work shares: overlap vs adjacency."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, create_member, create_work, create_share,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_first_share():
    """Work 'Kestrel' with share S1: member A, 50%, [2026-01-01, 2026-07-01)."""
    set_clock("2026-09-01T00:00:00Z")
    m_a = create_member()
    work = create_work(title="Kestrel")
    s1 = create_share(work["id"], m_a["id"], share_percent=50,
                      effective_from="2026-01-01T00:00:00Z",
                      effective_to="2026-07-01T00:00:00Z")
    work = validate_success(api_client.get_work(work["id"], ADMIN))
    return m_a, work, s1


def test_overlapping_same_claimant_share_needs_supersede(api):
    """PRD §3.2: "Third, same-claimant overlap: when the new share's
    effectiveness window overlaps the window of an existing `ACTIVE` share of
    the same `claimant_member_id` on the same work — overlap judged half-open,
    two intervals overlapping exactly when each one's start precedes the
    other's end — the payload must declare `supersedes_share_id` pointing at
    that share, else `ERR_SHARE_OVERLAP_NEEDS_SUPERSEDE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/share_overlap_half_open_supersede
    """
    m_a, work, _s1 = _setup_first_share()
    validate_error(
        api_client.create_share(work["id"], {
            "claimant_member_id": m_a["id"], "share_percent": 40,
            "effective_from": "2026-06-01T00:00:00Z",
            "effective_to": "2026-08-01T00:00:00Z",
            "expected_work_version": work["version"],
        }, ADMIN),
        ApiErrorId.ERR_SHARE_OVERLAP_NEEDS_SUPERSEDE)


def test_adjacent_share_is_not_an_overlap(api):
    """PRD §3.2: "Third, same-claimant overlap: when the new share's
    effectiveness window overlaps the window of an existing `ACTIVE` share of
    the same `claimant_member_id` on the same work — overlap judged half-open,
    two intervals overlapping exactly when each one's start precedes the
    other's end — the payload must declare `supersedes_share_id` pointing at
    that share, else `ERR_SHARE_OVERLAP_NEEDS_SUPERSEDE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/share_overlap_half_open_supersede
    """
    m_a, work, _s1 = _setup_first_share()
    # new.effective_from == old.effective_to: [2026-07-01, null) touches but
    # does not overlap [2026-01-01, 2026-07-01).
    s2 = validate_success(api_client.create_share(work["id"], {
        "claimant_member_id": m_a["id"], "share_percent": 40,
        "effective_from": "2026-07-01T00:00:00Z",
        "expected_work_version": work["version"],
    }, ADMIN), expected_status=201)
    assert s2["status"] == "ACTIVE"
    work_after = validate_success(api_client.get_work(work["id"], ADMIN))
    assert work_after["total_share_percent"] == 90, (
        f"both shares active: 50 + 40; got {work_after['total_share_percent']}")
