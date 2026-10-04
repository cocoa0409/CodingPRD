"""Breadth tests over the cross-cutting complexity layers: optimistic
concurrency on the two OCC-guarded write endpoints, and filter-plus-
pagination composition on the license registry."""
from test_helpers import (
    GRANT_DAY_ISO,
    ApiErrorId,
    MilestoneDecision,
    create_file_notice_payload,
    create_open_auction,
    file_milestone_notice,
    get_applicant,
    make_bidder_headers,
    milestones_by_type,
    patch_disclosure,
    register_applicant,
    review_milestone,
    setup_active_license,
    setup_closed_auction_with_licenses,
    validate_error,
    validate_paginated,
)


def test_occ_disclosure_stale_version_returns_412(api, auction_admin_headers):
    """PRD §2.8: "Updating an applicant's disclosure
    (`PATCH /spectrum-auctions/applicants/{id}/disclosure`) requires the
    request to carry `expected_applicant_version`, holding the applicant's
    `version` as the client last observed it; if the record has been mutated
    since — for example by an earlier disclosure update or by a resubmission —
    the versions disagree and the update is rejected with
    `ERR_STALE_VERSION` (412), because the client's edit base is stale."

    Design: Corner/cross_cutting_complexity_layers/occ_disclosure_stale_version_returns_412
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    s = register_applicant(
        ctx["auction"]["id"],
        legal_name="Sigma LLC",
        ownership_interests=[
            {"holder_name": "A", "stake_pct": 60, "holder_annual_revenue_cents": 0},
            {"holder_name": "B", "stake_pct": 40, "holder_annual_revenue_cents": 0},
        ],
    )

    # A legitimate edit first, so the stale probe below carries a version
    # the record once genuinely held.
    s = patch_disclosure(s["id"], s["version"], legal_name="Sigma Mid")
    v_mid = s["version"]

    stale = api.patch_disclosure(
        s["id"],
        {"expected_applicant_version": v_mid - 1, "legal_name": "Sigma Stale"},
        make_bidder_headers(s["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    # The stale attempt did not mutate the record.
    assert get_applicant(s["id"])["legal_name"] == "Sigma Mid"

    # Replayed with the fresh version, the identical edit succeeds.
    fresh = patch_disclosure(s["id"], v_mid, legal_name="Sigma Fresh")
    assert fresh["legal_name"] == "Sigma Fresh"
    assert fresh["version"] == v_mid + 1


def test_occ_milestone_filing_stale_version_returns_412(api, auction_admin_headers):
    """PRD §2.8: "Filing a buildout coverage notice
    (`POST /spectrum-auctions/buildout-milestones/{id}/file-notice`)
    likewise requires `expected_milestone_version` matching the milestone's
    current `version`; because each filing supersedes the previous filing's
    content, any intervening mutation — an earlier filing, a review decision,
    or a due-date acceleration — invalidates a stale base, and the filing is
    rejected with `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/occ_milestone_filing_stale_version_returns_412
    """
    ctx = setup_active_license(
        bids=[(0, "PEA001", "CATEGORY_A", 1)],
        area_codes=("PEA001",),
        block_categories=("CATEGORY_A",),
        grant_day_iso=GRANT_DAY_ISO,
    )
    lic = ctx["license"]
    w1_id = lic["holder_applicant_id"]
    interim = ctx["milestones"]["INTERIM"]
    assert interim["status"] == "PENDING"
    assert interim["covered_population"] is None

    # A legitimate first filing, so the stale probe carries a version the
    # milestone once genuinely held.
    filed = file_milestone_notice(interim["id"], w1_id, 400_000, interim["version"])
    assert filed["status"] == "FILED"
    assert filed["covered_population"] == 400_000
    v_filed = filed["version"]

    # The intervening mutation is a review decision, one of §2.8's enumerated
    # invalidators: REJECT moves FILED -> REJECTED and, being a mutation
    # (§2.5), increments the version. REJECTED is a from-state for re-filing
    # (§3.8's re-filing loop, "overwriting any earlier filing"), so the state
    # gate passes and OCC is the check that must fire below.
    rejected = review_milestone(filed["id"], MilestoneDecision.REJECT)
    assert rejected["status"] == "REJECTED"
    v_rejected = rejected["version"]
    assert v_rejected == v_filed + 1

    stale = api.file_milestone_notice(
        interim["id"],
        create_file_notice_payload(450_000, v_filed),
        make_bidder_headers(w1_id),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    # The stale filing did not supersede the recorded content.
    after_stale = milestones_by_type(lic["id"])["INTERIM"]
    assert after_stale["status"] == "REJECTED"
    assert after_stale["covered_population"] == 400_000

    # The same filing with the observed version lands.
    fresh = file_milestone_notice(interim["id"], w1_id, 450_000, v_rejected)
    assert fresh["status"] == "FILED"
    assert fresh["covered_population"] == 450_000
    assert fresh["version"] == v_rejected + 1


def test_licenses_list_filters_and_paginates(api, auction_admin_headers):
    """PRD §2.9: "List endpoints double as reverse-reach views over those
    foreign keys, and several accept filters: the applicant roster of an
    auction can be filtered by `status`; the bids of a round by
    `bidder_applicant_id`; the bids of an applicant by `round_id`; the
    license registry by `auction_id`, `area_id`, `holder_applicant_id`, or
    `status`; and the incumbent registry by `band_plan_id`, `area_id`, or
    `status`."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/cross_cutting_complexity_layers/licenses_list_filters_and_paginates
    """
    # W1 wins both units of CATEGORY_A @ PEA002: two licenses, neither paid.
    ctx = setup_closed_auction_with_licenses(
        bids=[(0, "PEA002", "CATEGORY_A", 2)],
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[{"legal_name": "Winner One LLC"}],
    )
    auction_id = ctx["auction"]["id"]
    assert len(ctx["licenses"]) == 2
    assert all(lic["status"] == "PENDING_PAYMENT" for lic in ctx["licenses"])

    page1, meta1 = validate_paginated(
        api.list_licenses(
            auction_admin_headers,
            params={
                "auction_id": auction_id,
                "status": "PENDING_PAYMENT",
                "limit": 1,
                "offset": 0,
            },
        )
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_licenses(
            auction_admin_headers,
            params={
                "auction_id": auction_id,
                "status": "PENDING_PAYMENT",
                "limit": 1,
                "offset": 1,
            },
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert page2[0]["id"] != page1[0]["id"]

    # The status filter excludes both PENDING_PAYMENT rows.
    page3, meta3 = validate_paginated(
        api.list_licenses(
            auction_admin_headers,
            params={"auction_id": auction_id, "status": "ACTIVE"},
        )
    )
    assert page3 == []
    assert meta3["total_count"] == 0
