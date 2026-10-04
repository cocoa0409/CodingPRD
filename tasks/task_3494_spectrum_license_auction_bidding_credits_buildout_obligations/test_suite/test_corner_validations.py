"""Breadth tests over the validation-priority surface: the fixed tier order
of the PRD's global check pipeline (role before existence before ownership
before state) and the quiet-period anti-collusion freeze."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    begin_quiet_period,
    create_open_auction,
    get_applicant,
    make_bidder_headers,
    register_applicant,
    start_review,
    validate_error,
)


def test_role_denied_before_existence_returns_unauthorized(api):
    """PRD §2.7: "When a request could fail several checks, the server
    evaluates them in a fixed priority order and reports only the first
    failure; later checks are never consulted once an earlier one has fired."
    PRD §2.7: "2. **Role authorization** — the caller's role must appear in
    the endpoint's authorization list and, on action-multiplexed endpoints,
    must be permitted for the specific `action` value
    (`ERR_UNAUTHORIZED_ROLE`, 403)."
    PRD §2.7: "3. **Existence** — path identifiers are resolved strictly left
    to right, and the first identifier that does not resolve to an existing
    resource yields `ERR_NOT_FOUND` (404)"

    Design: Corner/validations/role_denied_before_existence_returns_unauthorized
    """
    # A Bidder publishing a band plan fails the role gate (tier 2), so the
    # bogus path id is never resolved — 403, not 404.
    resp = api.publish_band_plan(
        NON_EXISTENT_UUID, make_bidder_headers(NON_EXISTENT_UUID)
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.status_code == 403


def test_existence_precedes_state_returns_not_found(api, auction_admin_headers):
    """PRD §2.9: "Where a request path chains more than one identifier, the
    identifiers are validated in strict left-to-right order, and the request
    fails with `ERR_NOT_FOUND` at the first identifier that does not resolve,
    before any later identifier or business rule is examined."
    PRD §2.7: "5. **State gates** — the target entity must be in a from-state
    of the requested transition, surfaced through the machine-specific error
    id" — consulted only after existence.

    Design: Corner/validations/existence_precedes_state_returns_not_found
    """
    # An AuctionAdmin closing a round id that does not exist gets the 404
    # existence error, never a state-machine error.
    resp = api.close_round(NON_EXISTENT_UUID, auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_ownership_precedes_state_returns_forbidden(api, auction_admin_headers):
    """PRD §2.7: "4. **Ownership** — entity-backed callers must own the
    target resource per §2.1 (`ERR_FORBIDDEN_OWNERSHIP`, 403)."
    PRD §2.7: "5. **State gates** — the target entity must be in a from-state
    of the requested transition, surfaced through the machine-specific error
    id" — so a wrong-owner disclosure update against an UNDER_REVIEW
    applicant (also an illegal from-state for updates) reports ownership.

    Design: Corner/validations/ownership_precedes_state_returns_forbidden
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    r = register_applicant(
        ctx["auction"]["id"],
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    start_review(r["id"])  # SUBMITTED -> UNDER_REVIEW (no disclosure edge)
    x = register_applicant(ctx["auction"]["id"], legal_name="X Other")

    r_v = get_applicant(r["id"])["version"]
    resp = api.patch_disclosure(
        r["id"],
        {"expected_applicant_version": r_v, "legal_name": "Hijacked"},
        make_bidder_headers(x["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    assert resp.status_code == 403

    # The target record was not mutated.
    assert get_applicant(r["id"])["legal_name"] == "Rural Wireless Co"


def test_quiet_period_freeze_blocks_clean_disclosure_patch(api, auction_admin_headers):
    """PRD §3.4: "The quiet period starts the anti-collusion freeze: from
    that moment until the auction reaches `CLOSED`, disclosure updates and
    correction resubmissions are rejected with `ERR_QUIET_PERIOD_VIOLATION`."
    PRD §3.2: "An update attempted while the applicant is in any other status
    is rejected with `ERR_APPLICANT_INVALID_STATE`, and from the quiet period
    onward the anti-collusion freeze of §3.4 rejects it with
    `ERR_QUIET_PERIOD_VIOLATION` regardless of the applicant's status."

    Design: Corner/validations/quiet_period_freeze_blocks_clean_disclosure_patch
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
    s_v = s["version"]
    begin_quiet_period(ctx["auction"]["id"], ctx["auction"]["application_deadline"])

    # Correct version, ownership still summing to 100, applicant in a legal
    # from-state — the freeze alone is sufficient grounds for rejection.
    resp = api.patch_disclosure(
        s["id"],
        {"expected_applicant_version": s_v, "legal_name": "Sigma LLC (renamed)"},
        make_bidder_headers(s["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_QUIET_PERIOD_VIOLATION)
    assert resp.status_code == 409

    s_after = get_applicant(s["id"])
    assert s_after["version"] == s_v
    assert s_after["legal_name"] == "Sigma LLC"
