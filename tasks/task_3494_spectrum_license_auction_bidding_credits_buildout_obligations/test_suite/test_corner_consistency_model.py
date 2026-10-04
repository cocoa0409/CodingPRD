"""Breadth test for the immediate-consistency model: a mutating response
itself reflects the post-mutation state, and the very next read shows the
cascaded creations — no re-read delay anywhere."""
from test_helpers import (
    GRANT_DAY_ISO,
    assert_clock_timestamp,
    expected_milestone_due_date,
    expected_term_end,
    make_bidder_headers,
    set_clock,
    setup_closed_auction_with_licenses,
    validate_paginated,
    validate_success,
)


def test_settlement_response_immediately_reflects_grant(api, auction_admin_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.7: "On completion the license becomes `ACTIVE`: `grant_date` is
    stamped with the current logical instant, `term_end` is computed as the
    grant date plus 3650 days, and two buildout milestones are created in
    `PENDING` status, each stamped with its `milestone_type` — an `INTERIM`
    milestone due 1095 days after grant with `required_coverage_pct` 40, and
    a `FINAL` milestone due 2190 days after grant with `required_coverage_pct`
    70, the constants copied onto the milestone records at creation."
    PRD §3.7: "In milestone listings the pair created by a single grant reads
    in `created_at` ascending order, `INTERIM` before `FINAL`."

    Design: Corner/consistency_model/settlement_response_immediately_reflects_grant
    """
    ctx = setup_closed_auction_with_licenses(
        bids=[(0, "PEA002", "CATEGORY_A", 1)],
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {
                "legal_name": "Rural Wireless Co",
                "claims_rural_credit": True,
                "service_population": 200_000,
            }
        ],
    )
    r = ctx["applicants"][0]
    lic = ctx["licenses"][0]
    assert lic["status"] == "PENDING_PAYMENT"
    assert lic["net_price_cents"] == 212_500_000

    set_clock(GRANT_DAY_ISO)  # 2026-10-01: the completing payment lands here
    resp = api.add_settlement_payment(
        lic["id"], 212_500_000, make_bidder_headers(r["id"])
    )

    # The payment's own 200 response already shows the granted license.
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE"
    assert data["paid_cents"] == 212_500_000
    assert data["paid_cents"] == data["net_price_cents"]
    assert data["grant_date"] == GRANT_DAY_ISO
    assert_clock_timestamp(data["grant_date"], "License.grant_date")
    assert data["term_end"] == expected_term_end(GRANT_DAY_ISO)

    # The very next GET lists both milestones, already PENDING, INTERIM
    # before FINAL.
    ms_rows, _ = validate_paginated(
        api.list_buildout_milestones(lic["id"], auction_admin_headers)
    )
    assert len(ms_rows) == 2
    assert [m["milestone_type"] for m in ms_rows] == ["INTERIM", "FINAL"]
    assert all(m["status"] == "PENDING" for m in ms_rows)
    assert ms_rows[0]["due_date"] == expected_milestone_due_date(GRANT_DAY_ISO, "INTERIM")
    assert ms_rows[1]["due_date"] == expected_milestone_due_date(GRANT_DAY_ISO, "FINAL")
    assert ms_rows[0]["required_coverage_pct"] == 40
    assert ms_rows[1]["required_coverage_pct"] == 70
