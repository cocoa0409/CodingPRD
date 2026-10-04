"""Resource creation defaults, derived fields, listing and reverse reachability."""
from test_helpers import (
    api_client, get_success_data, validate_paginated,
    create_branch, create_advisor, create_loan, enroll_advisor, affiliate_advisor,
    create_advisor_link, enroll_supervisor, make_advisor_ops_headers,
    PLATFORM_ADMIN, COMPLIANCE_OFFICER, NON_EXISTENT_UUID,
)


def _activate(advisor_code, branch_code="SUP-1"):
    """A fully ACTIVE advisor on the supervised default branch."""
    supervisor = create_advisor(f"{advisor_code}-SUP", f"9{advisor_code[-4:]}",
                                "Branch Supervisor",
                                primary_branch_code=branch_code,
                                ingested_book_total_cents=800_000_000,
                                book_transferred_cents=640_000_000)
    enroll_supervisor(branch_code, supervisor["advisor_code"])
    create_advisor_link(supervisor, branch_code, is_supervisor=True)
    advisor = create_advisor(advisor_code, f"1{advisor_code[-6:]}", "Active Advisor",
                             primary_branch_code=branch_code,
                             ingested_book_total_cents=500_000_000,
                             book_transferred_cents=400_000_000)
    create_loan(advisor)
    enroll_advisor(advisor)
    return affiliate_advisor(advisor)


# ─── corner: entities ─────────────────────────────────

def test_advisor_creation_derives_the_book_portability_ratio():
    """PRD §2.5: "Their ratio is exposed as `book_portability_pct`, expressed in basis
    points: it is the transferred value multiplied by 10000 and divided by the ingested
    value using integer floor division, and it is 0 whenever `ingested_book_total_cents`
    is 0."
    PRD §3.1: "A newly created advisor sits at `status` `PROSPECT` with `retention_status`
    `NOT_AT_RISK`".

    Design: Corner/entities/advisor_create_derives_book_portability_ratio
    """
    create_branch()
    advisor = create_advisor("A-11001", "1234567", "Iris Calloway",
                             ingested_book_total_cents=500_000_000,
                             book_transferred_cents=300_000_000,
                             protocol_eligible=False)
    assert advisor["book_portability_pct"] == 6000
    assert advisor["status"] == "PROSPECT"
    assert advisor["retention_status"] == "NOT_AT_RISK"
    assert advisor["t12_production_cents"] == 0
    assert advisor["outstanding_loan_balance_cents"] == 0
    assert advisor["annual_payout_cap_hit"] is False
    assert advisor["ytd_payout_paid_cents"] == 0


def test_advisor_creation_reports_a_zero_portability_ratio_for_an_empty_book():
    """PRD §2.5: "it is 0 whenever `ingested_book_total_cents` is 0."
    PRD §2.5: "`protocol_eligible`, which defaults to false."

    Design: Corner/entities/advisor_create_derives_book_portability_ratio
    """
    create_branch()
    advisor = create_advisor("A-11002", "1234568", "Empty Book",
                             ingested_book_total_cents=0,
                             book_transferred_cents=0,
                             protocol_eligible=False)
    assert advisor["book_portability_pct"] == 0
    assert advisor["protocol_eligible"] is False


def test_account_creation_defaults_balance_and_fee_and_starts_open():
    """PRD §3.6: "An account is opened at `status` `OPEN` with `fee_levelized` false."
    PRD §3.6: "its `balance_cents`, and — for advisory accounts — its `annual_fee_cents`."

    Design: Corner/entities/account_create_defaults_balance_and_fee_and_starts_open
    """
    create_branch()
    advisor = _activate("A-11003")
    account = get_success_data(api_client.create_account(
        {"advisor_code": advisor["advisor_code"], "account_number": "A-11003-EQ",
         "account_type": "BROKERAGE"},
        make_advisor_ops_headers(advisor["id"])))
    assert account["balance_cents"] == 0
    assert account["annual_fee_cents"] == 0
    assert account["held_away"] is False
    assert account["status"] == "OPEN"
    assert account["fee_levelized"] is False
    assert account["rafee_effective_bps"] is None
    assert account["pending_transfer_at"] is None


def test_branch_advisor_links_reverse_reachability_returns_only_the_branchs_links():
    """PRD §2.5: "Advisors are attached to branches through link records that carry
    `advisor_code`, `branch_code`, `assignment_type` (either `PRIMARY` or `SECONDARY`), and
    an `is_supervisor` flag that defaults to false."

    Design: Corner/entities/branch_advisor_links_reverse_reachability_returns_the_branchs_links
    """
    branch_a = create_branch(branch_code="SUP-1")
    branch_b = create_branch(branch_code="MID-1", name="Midtown Practice",
                             transmittal_account="TA-2210", osj_name="Midtown OSJ")
    advisor = create_advisor("A-11005", "1234571", "Iris Calloway")
    create_advisor_link(advisor, "SUP-1", is_supervisor=True,
                        assignment_type="PRIMARY")
    create_advisor_link(advisor, "MID-1", is_supervisor=False,
                        assignment_type="SECONDARY")

    links, meta = validate_paginated(api_client.list_branch_advisor_links(
        branch_a["id"], COMPLIANCE_OFFICER))
    assert len(links) == 1
    assert links[0]["branch_code"] == "SUP-1"
    assert links[0]["is_supervisor"] is True

    other, _ = validate_paginated(api_client.list_branch_advisor_links(
        branch_b["id"], COMPLIANCE_OFFICER))
    assert len(other) == 1
    assert other[0]["branch_code"] == "MID-1"
    assert other[0]["is_supervisor"] is False


# ─── corner: entities (listing) ───────────────────────

def test_branch_listing_paginates_and_reports_total_count():
    """PRD §2.3: "List responses carry four pagination fields inside the `meta` object of
    the envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "If omitted, `limit` defaults to 10".

    Design: Corner/entities/branches_list_paginates_and_reports_total_count
    """
    create_branch(branch_code="SUP-1")
    create_branch(branch_code="MID-1", name="Midtown Practice",
                  transmittal_account="TA-2210", osj_name="Midtown OSJ")
    create_branch(branch_code="COA-1", name="Coastal Practice",
                  transmittal_account="TA-7788", osj_name="Coastal OSJ")

    page, meta = validate_paginated(api_client.list_branches(
        PLATFORM_ADMIN, {"limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    second, meta2 = validate_paginated(api_client.list_branches(
        PLATFORM_ADMIN, {"limit": 2, "offset": 2}))
    assert len(second) == 1
    assert meta2["has_more"] is False

    default_page, default_meta = validate_paginated(api_client.list_branches(
        PLATFORM_ADMIN))
    assert len(default_page) == 3
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0


# ─── corner: entities (not found) ─────────────────────

def test_an_unknown_branch_identifier_is_reported_as_branch_not_found():
    """PRD §2.9: "A `branch_code` that does not resolve to a branch yields
    `ERR_BRANCH_NOT_FOUND` at HTTP 404."
    PRD §2.10: "Existence of a path-resolved server-minted identifier, otherwise
    `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/branch_get_with_unknown_id_returns_branch_not_found
    """
    create_branch(branch_code="SUP-1")

    listing, _meta = validate_paginated(api_client.list_branches(PLATFORM_ADMIN))
    known_ids = {row["id"] for row in listing}
    assert len(known_ids) == 1

    unknown = NON_EXISTENT_UUID
    while unknown in known_ids:
        unknown = unknown[:-1] + "1"
    response = api_client.get_branch(unknown, PLATFORM_ADMIN)
    error_id = response.json()["data"]["error_id"]
    assert error_id == "ERR_BRANCH_NOT_FOUND", (
        f"an unallocated branch id must surface the branch-specific 404, got {error_id}")