"""Sponsor agreements: half-open effective windows, OCC-guarded amendment,
the fiscal pool floor, and sponsor ownership — PRD §2.1, §2.7, §2.8, §3.6.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    amend_sponsor_agreement,
    create_amendment_payload,
    create_corporate_sponsor,
    create_cycle,
    create_sponsor_agreement,
    create_sponsor_agreement_payload,
    get_agreement,
    list_sponsor_agreements,
    make_sponsor_admin_headers,
    setup_matching_run,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]


def _cycle_and_sponsor():
    cycle = create_cycle(name="CYC-OVL")
    sponsor = create_corporate_sponsor(legal_name="Acme Corp", sponsor_code="ACME")
    return cycle, sponsor


def test_agreement_window_adjacency_is_not_overlap(api):
    """PRD §3.6: the window is "a half-open interval that includes the start date
    and excludes the end date, with the end strictly after the start", and
    "Because windows are half-open, adjacency — one agreement's end date equal
    to another's start date — is allowed".
    
    Design: Difficulty/resource_temporal_overlap/agreement_window_half_open_adjacency
    """
    cycle, sponsor = _cycle_and_sponsor()
    a1 = create_sponsor_agreement(
        sponsor["id"], cycle["id"],
        effective_start_date="2027-01-01", effective_end_date="2027-06-30",
    )
    a2 = create_sponsor_agreement(
        sponsor["id"], cycle["id"],
        award_amount_cents=100000, max_awards=1, pool_total_cents=100000,
        effective_start_date="2027-06-30",  # == A1's end: adjacent, legal
        effective_end_date="2027-12-31",
    )
    assert a2["status"] == "ACTIVE"
    assert a2["supersedes_agreement_id"] is None
    assert get_agreement(a1["id"])["status"] == "ACTIVE"


def test_agreement_window_overlap_rejected_and_persists_nothing(api):
    """PRD §3.6: "Effective windows of the same sponsor for the same cycle must
    not overlap ... A violation is `ERR_AGREEMENT_WINDOW_OVERLAP` (HTTP 409)".
    
    Design: Difficulty/resource_temporal_overlap/agreement_window_half_open_adjacency
    """
    cycle, sponsor = _cycle_and_sponsor()
    a1 = create_sponsor_agreement(
        sponsor["id"], cycle["id"],
        effective_start_date="2027-01-01", effective_end_date="2027-06-30",
    )
    a2 = create_sponsor_agreement(
        sponsor["id"], cycle["id"],
        award_amount_cents=100000, max_awards=1, pool_total_cents=100000,
        effective_start_date="2027-06-30", effective_end_date="2027-12-31",
    )
    resp = api.create_sponsor_agreement(
        sponsor["id"],
        create_sponsor_agreement_payload(
            cycle["id"],
            award_amount_cents=50000, max_awards=1, pool_total_cents=50000,
            effective_start_date="2027-06-29",  # one day into A1's window
            effective_end_date="2027-09-30",
        ),
        make_sponsor_admin_headers(sponsor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)
    rows = list_sponsor_agreements(sponsor_id=sponsor["id"])
    assert {r["id"] for r in rows} == {a1["id"], a2["id"]}
    assert all(r["status"] == "ACTIVE" for r in rows)


def _committed_cycle_with_two_windows():
    """One committed agreement A1 [2027-01-01, 2027-06-30) carrying a 250000
    obligation, plus a disjoint sibling A2 [2027-07-01, 2027-12-31)."""
    ctx = setup_matching_run(
        student_specs=[{"parent_sponsor": True}],
        agreement_overrides={
            "award_amount_cents": 250000,
            "max_awards": 2,
            "pool_total_cents": 250000,
            "effective_start_date": "2027-01-01",
            "effective_end_date": "2027-06-30",
        },
    )
    a2 = create_sponsor_agreement(
        ctx["sponsor"]["id"], ctx["cycle"]["id"],
        award_amount_cents=100000, max_awards=1, pool_total_cents=100000,
        effective_start_date="2027-07-01", effective_end_date="2027-12-31",
    )
    return ctx, a2


def test_amend_conflict_temporal_error_beats_fiscal_floor(api):
    """PRD §3.6: "A violation is `ERR_AGREEMENT_WINDOW_OVERLAP` (HTTP 409), and
    on amendment this temporal check runs before the pool-floor check." PRD
    §2.8: "8. Temporal rules — `ERR_APPLICATION_WINDOW_CLOSED`,
    `ERR_AGREEMENT_WINDOW_OVERLAP`, `ERR_DISBURSEMENT_NOT_DUE`,
    `ERR_NOTIFICATION_EMBARGOED`, `ERR_PUBLICITY_WINDOW_TOO_EARLY`, and
    `ERR_CLOCK_REGRESSION`." come before "9. The fiscal guard —
    `ERR_POOL_BELOW_COMMITTED` on agreement amendment."
    
    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_amend
    """
    ctx, _a2 = _committed_cycle_with_two_windows()
    sponsor_id = ctx["sponsor"]["id"]
    a1 = get_agreement(ctx["agreement"]["id"])  # EXHAUSTED, committed 250000
    assert a1["status"] == "EXHAUSTED"
    resp = api.amend_sponsor_agreement(
        a1["id"],
        # Overlaps A2's window AND prices the pool below committed obligations.
        create_amendment_payload(
            a1["version"],
            effective_start_date="2027-06-01",
            effective_end_date="2027-08-31",
            pool_total_cents=100000,
        ),
        make_sponsor_admin_headers(sponsor_id),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)
    unchanged = get_agreement(a1["id"])
    assert unchanged["status"] == "EXHAUSTED"
    assert unchanged["pool_total_cents"] == 250000
    assert unchanged["version"] == a1["version"]  # a failed amend supersedes nothing


def test_amend_fiscal_floor_surfaces_once_temporal_passes(api):
    """PRD §3.6: "Amendment may not set `pool_total_cents` below the agreement's
    current `pool_committed_cents` plus `pool_paid_cents`: obligations are
    preserved across amendment, and a violating payload is rejected with
    `ERR_POOL_BELOW_COMMITTED` (HTTP 422)."
    
    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_amend
    """
    ctx, _a2 = _committed_cycle_with_two_windows()
    sponsor_id = ctx["sponsor"]["id"]
    a1 = get_agreement(ctx["agreement"]["id"])
    resp = api.amend_sponsor_agreement(
        a1["id"],
        # Window disjoint from both siblings; only the floor is violated.
        create_amendment_payload(
            a1["version"],
            effective_start_date="2028-01-01",
            effective_end_date="2028-12-31",
            pool_total_cents=100000,  # < committed 250000
        ),
        make_sponsor_admin_headers(sponsor_id),
    )
    validate_error(resp, ApiErrorId.ERR_POOL_BELOW_COMMITTED)
    assert len(list_sponsor_agreements(sponsor_id=sponsor_id)) == 2


def test_amend_below_committed_rejected(api):
    """PRD §3.6: "Amendment may not set `pool_total_cents` below the agreement's
    current `pool_committed_cents` plus `pool_paid_cents`: obligations are
    preserved across amendment, and a violating payload is rejected with
    `ERR_POOL_BELOW_COMMITTED` (HTTP 422)."
    
    Design: Corner/validations/amend_below_committed_rejected
    """
    ctx = setup_matching_run(
        student_specs=[{"parent_sponsor": True}],
        agreement_overrides={"pool_total_cents": 250000},  # matching commits all
    )
    sponsor_id = ctx["sponsor"]["id"]
    a1 = get_agreement(ctx["agreement"]["id"])
    assert a1["pool_committed_cents"] == 250000
    resp = api.amend_sponsor_agreement(
        a1["id"],
        create_amendment_payload(a1["version"], pool_total_cents=100000),
        make_sponsor_admin_headers(sponsor_id),
    )
    validate_error(resp, ApiErrorId.ERR_POOL_BELOW_COMMITTED)
    unchanged = get_agreement(a1["id"])
    assert unchanged["status"] == "EXHAUSTED"
    assert unchanged["pool_total_cents"] == 250000
    assert unchanged["version"] == a1["version"]


def test_amend_with_stale_version_rejected(api):
    """PRD §2.7: "Amending a sponsor agreement requires the request to carry
    `expected_sponsor_agreement_version`, holding the agreement's `version` as
    the client last observed it. If the agreement's current `version` has
    advanced since that read — for example because another amendment already
    superseded the agreement under the sponsor's administration of its own
    awards, or a matching or pool cascade mutated it — the amendment is
    rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from
    overwriting an agreement state it has not observed." PRD §3.6: "A
    successful amendment creates a new `ACTIVE` agreement whose
    `supersedes_agreement_id` points at the old one and whose
    `pool_committed_cents` and `pool_paid_cents` start at 0".
    
    Design: Corner/cross_cutting_layers/amend_with_stale_version_rejected
    """
    ctx = setup_matching_run(
        student_specs=[{"parent_sponsor": True}],
        agreement_overrides={"pool_total_cents": 250000},
    )
    sponsor_id = ctx["sponsor"]["id"]
    stale_version = ctx["agreement"]["version"]  # captured at creation (1)
    assert stale_version == 1

    resp = api.amend_sponsor_agreement(
        ctx["agreement"]["id"],
        create_amendment_payload(stale_version, pool_total_cents=500000),
        make_sponsor_admin_headers(sponsor_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)  # matching bumped it to 2

    fresh = get_agreement(ctx["agreement"]["id"])
    assert fresh["version"] == 2
    new = amend_sponsor_agreement(
        fresh["id"], sponsor_id, fresh["version"], pool_total_cents=500000
    )
    assert new["status"] == "ACTIVE"
    assert new["supersedes_agreement_id"] == fresh["id"]
    assert new["pool_total_cents"] == 500000
    assert new["pool_committed_cents"] == 0
    assert new["pool_paid_cents"] == 0
    assert get_agreement(fresh["id"])["status"] == "SUPERSEDED"


def test_sponsor_admin_cannot_amend_others_agreement_forbidden(api):
    """PRD §3.6: "the sponsor amends its own agreement (the same ownership rule,
    `X-User-ID` against the agreement's `sponsor_id`)"; PRD §2.1: "it is
    compared to an agreement's `sponsor_id` or to the sponsor identifier in
    the request path, and a mismatch is rejected with
    `ERR_FORBIDDEN_OWNERSHIP`." PRD §2.8: ownership (3) precedes optimistic
    concurrency (5).
    
    Design: Corner/rbac/sponsor_admin_cannot_amend_others_agreement_forbidden
    """
    cycle, sponsor_a = _cycle_and_sponsor()
    sponsor_b = create_corporate_sponsor(legal_name="Beta Inc", sponsor_code="BETA")
    a1 = create_sponsor_agreement(sponsor_a["id"], cycle["id"])
    resp = api.amend_sponsor_agreement(
        a1["id"],
        create_amendment_payload(a1["version"], pool_total_cents=600000),
        make_sponsor_admin_headers(sponsor_b["id"]),  # wrong sponsor identity
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    unchanged = get_agreement(a1["id"])
    assert unchanged["version"] == a1["version"]
    assert unchanged["status"] == "ACTIVE"
