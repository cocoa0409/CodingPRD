"""Audited financial filings: computation, OCC guards, supersede, decisions."""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    advance_lender,
    create_lender,
    decide_filing,
    filing_payload,
    get_lender,
    lender_version,
    submit_filing,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    TEST_USERS,
    make_admin_headers,
    make_lender_officer_headers,
    make_reviewer_headers,
)


def test_filing_computes_adjusted_net_worth(api):
    """PRD §3.1: "The system derives `adjusted_net_worth_cents` as total assets minus
    total liabilities. A new filing lands in `SUBMITTED`."

    Design: Corner/entities/filing_computes_adjusted_net_worth
    """
    lender = create_lender(legal_name="NW Test Co")
    response = api_client.create_financial_filing(
        lender["id"],
        filing_payload(
            lender["version"],
            fiscal_year_end="2025-12-31",
            total_assets_cents=50_000_000_000,
            total_liabilities_cents=49_000_000_000,
            liquid_assets_cents=5_000_000_000,
        ),
        make_lender_officer_headers(lender["id"]),
    )
    data = validate_success(response, expected_status=201)
    # 50,000,000,000 - 49,000,000,000 = 1,000,000,000.
    assert data["adjusted_net_worth_cents"] == 1_000_000_000
    assert data["status"] == "SUBMITTED"


def test_filing_creation_with_unknown_lender_returns_not_found(api):
    """PRD §2.7: "Existence: every id in the path and body references an existing
    resource (`ERR_NOT_FOUND`)."

    Design: Corner/entities/filing_creation_with_unknown_lender_returns_not_found
    """
    decoy = create_lender(legal_name="Decoy Co")
    # X-User-ID equals the (non-existent) path lender id, so ownership is trivially
    # satisfied and the existence check is the one that fires.
    response = api_client.create_financial_filing(
        UNKNOWN_UUID,
        filing_payload(decoy["version"], fiscal_year_end="2025-12-31"),
        make_lender_officer_headers(UNKNOWN_UUID),
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_filing_reject_lands_rejected(api):
    """PRD §3.1: "rejecting a filing records the reviewer and likewise increments the
    lender's `version` by 1."

    Design: Corner/state_machines/filing_reject_lands_rejected
    """
    lender = create_lender(legal_name="Reject Co")
    filing = submit_filing(lender["id"])
    version_before = lender_version(lender["id"])
    response = api_client.decide_financial_filing(
        filing["id"],
        {
            "decision": "REJECT",
            "expected_lender_version": version_before,
        },
        make_reviewer_headers("rev-1"),
    )
    data = validate_success(response)
    assert data["status"] == "REJECTED"
    assert data["decided_by_user_id"] == "rev-1"
    assert lender_version(lender["id"]) == version_before + 1


def test_filing_decide_from_rejected_terminal_lockdown(api):
    """PRD §3.1: "`ACCEPTED`, `REJECTED`, and `SUPERSEDED` are all terminal for a
    filing."
    PRD §2.7: "State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/filing_decide_from_rejected_terminal_lockdown
    """
    lender = create_lender(legal_name="Filing Lock Co")
    filing = submit_filing(lender["id"])
    decide_filing(filing["id"], lender["id"], "REJECT")
    response = api_client.decide_financial_filing(
        filing["id"],
        {
            "decision": "ACCEPT",
            "expected_lender_version": lender_version(lender["id"]),
        },
        make_reviewer_headers("rev-1"),
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_filing_accept_supersedes_prior_accepted_same_fiscal_year(api):
    """PRD §3.1: "Accepting a filing records the reviewer in `decided_by_user_id`,
    supersedes any previously accepted filing of the same lender with the same
    `fiscal_year_end` (that older filing moves from `ACCEPTED` to `SUPERSEDED`, an
    accept-with-supersede rule driven by the system), updates the lender's
    `last_accepted_filing_id`, recomputes the lender's net worth requirement and
    variant, and increments the lender's `version` by 1"

    Design: Corner/state_machines/filing_accept_supersedes_prior_accepted_same_fiscal_year
    """
    lender = create_lender(legal_name="Supersede Co")
    filing_1 = submit_filing(lender["id"], fiscal_year_end="2025-12-31")
    decide_filing(filing_1["id"], lender["id"], "ACCEPT")
    filing_2 = submit_filing(
        lender["id"],
        fiscal_year_end="2025-12-31",
        total_assets_cents=51_000_000_000,
        liquid_assets_cents=6_000_000_000,
    )
    decide_filing(filing_2["id"], lender["id"], "ACCEPT")

    data, meta = validate_paginated(
        api_client.list_financial_filings(lender["id"], make_admin_headers())
    )
    by_id = {f["id"]: f for f in data}
    assert by_id[filing_1["id"]]["status"] == "SUPERSEDED"
    assert by_id[filing_2["id"]]["status"] == "ACCEPTED"
    assert get_lender(lender["id"])["last_accepted_filing_id"] == filing_2["id"]


def test_occ_mismatch_returns_412_stale_version(api):
    """PRD §2.5: "Both require the non-optional input field `expected_lender_version`
    carrying the client's last observed `version` of the parent `Lender`, and both
    reject with `ERR_STALE_VERSION` (HTTP 412) when that value does not match the
    lender's current `version`."

    Design: Corner/validations/occ_mismatch_returns_412_stale_version
    """
    lender = create_lender(legal_name="OCC Co")
    stale_version = lender["version"]
    submit_filing(lender["id"])
    filing = validate_success(
        api_client.list_financial_filings(lender["id"], make_admin_headers())
    )[0]
    # Advance the lender's version via an unrelated status change so the version the
    # client holds is genuinely stale.
    advance_lender(lender["id"], reviewer="rev-1")
    assert lender_version(lender["id"]) != stale_version
    response = api_client.decide_financial_filing(
        filing["id"],
        {"decision": "ACCEPT", "expected_lender_version": stale_version},
        make_reviewer_headers("rev-1"),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)


def test_filings_list_reverse_reachable_from_lender(api):
    """PRD §4: "| GET | /mi/lenders/{lenderId}/financial-filings | List a lender's
    filings | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover,
    ClaimsExaminer |"
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/filings_list_reverse_reachable_from_lender
    """
    lender = create_lender(legal_name="List Filing Co")
    filing_1 = submit_filing(lender["id"], fiscal_year_end="2024-12-31")
    filing_2 = submit_filing(lender["id"], fiscal_year_end="2025-12-31")
    data, meta = validate_paginated(
        api_client.list_financial_filings(lender["id"], make_admin_headers())
    )
    assert meta["total_count"] == 2
    ids = {f["id"] for f in data}
    assert filing_1["id"] in ids and filing_2["id"] in ids


def test_platform_admin_cannot_decide_filings(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the endpoint
    — or, on the lender lifecycle endpoint, not permitted for the requested action — is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mi/financial-filings/{filingId}/decide | Accept (with supersede)
    or reject a filing (OCC-guarded) | FhaReviewer |"

    Design: Corner/rbac/platform_admin_cannot_decide_filings
    """
    lender = create_lender(legal_name="RBAC Filing Co")
    filing = submit_filing(lender["id"])
    response = api_client.decide_financial_filing(
        filing["id"],
        {
            "decision": "ACCEPT",
            "expected_lender_version": lender_version(lender["id"]),
        },
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
