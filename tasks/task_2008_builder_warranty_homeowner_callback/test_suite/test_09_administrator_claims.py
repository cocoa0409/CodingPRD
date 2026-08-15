"""Third-party administrator claims: program and tier gates, uniqueness, and the
accept/deny decision with its reserve recovery."""
from test_helpers import (
    ApiErrorId,
    create_approved_request,
    decide_claim,
    get_reserve_for_home,
    setup_admin_claim,
    setup_home,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_administrator_claim_payload
from test_helpers.test_users import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]
FINANCE = TEST_USERS["finance_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestClaimRequiresThirdPartyStructural:
    def _setup_both_programs(self, api):
        """A STANDARD home and a THIRD_PARTY_ADMINISTERED home, each with an
        APPROVED FOUNDATION (STRUCTURAL) request."""
        homeowner, h_std = setup_home(
            lot_number="L-602", warranty_program="STANDARD"
        )
        _same_owner, h_tp = setup_home(
            homeowner_overrides={},
            lot_number="L-603",
            sale_price_cents=50_000_000,
            warranty_program="THIRD_PARTY_ADMINISTERED",
        )
        sr_std = create_approved_request(
            h_std["id"], homeowner["id"],
            item_category="FOUNDATION", severity="URGENT",
            description="Foundation crack, garage wall",
        )
        sr_tp = create_approved_request(
            h_tp["id"], _same_owner["id"],
            item_category="FOUNDATION", severity="URGENT",
            description="Foundation settlement",
        )
        return h_std, h_tp, sr_std, sr_tp

    def test_standard_program_claim_rejected(self, api):
        """PRD §3.8: "Three gates guard filing, in order: one claim per service
        request, else `ERR_DUPLICATE_CLAIM`; the home's `warranty_program` must be
        `THIRD_PARTY_ADMINISTERED`, else `ERR_PROGRAM_MISMATCH`; and the request
        must be `APPROVED` with `determined_tier` `STRUCTURAL`, else
        `ERR_CLAIM_TIER_INELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_third_party_structural
        """
        _h_std, _h_tp, sr_std, _sr_tp = self._setup_both_programs(api)
        resp = api.create_administrator_claim(
            create_administrator_claim_payload(sr_std["id"]), REP
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_MISMATCH)

    def test_third_party_claim_submitted_with_denormalized_home(self, api):
        """PRD §3.8: "When a structural request is approved on such a home, the
        representative files a claim with the administrator, naming the
        `service_request_id` and a strictly positive `claimed_amount_cents`,
        optionally recording the administrator's `external_reference`; the claim's
        `home_id` is denormalized from the request at filing, and the claim is
        born `SUBMITTED`."
        PRD §3.8: "Three gates guard filing, in order: one claim per service
        request, else `ERR_DUPLICATE_CLAIM`; the home's `warranty_program` must be
        `THIRD_PARTY_ADMINISTERED`, else `ERR_PROGRAM_MISMATCH`; and the request
        must be `APPROVED` with `determined_tier` `STRUCTURAL`, else
        `ERR_CLAIM_TIER_INELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_third_party_structural
        """
        _h_std, h_tp, _sr_std, sr_tp = self._setup_both_programs(api)
        resp = api.create_administrator_claim(
            create_administrator_claim_payload(sr_tp["id"]), REP
        )
        claim = validate_success(resp, 201)
        assert claim["status"] == "SUBMITTED"
        assert claim["home_id"] == h_tp["id"], (
            "home_id denormalized from the service request at filing"
        )


def test_claim_tier_ineligible_rejected(api):
    """PRD §3.8: "Three gates guard filing, in order: one claim per service
    request, else `ERR_DUPLICATE_CLAIM`; the home's `warranty_program` must be
    `THIRD_PARTY_ADMINISTERED`, else `ERR_PROGRAM_MISMATCH`; and the request must
    be `APPROVED` with `determined_tier` `STRUCTURAL`, else
    `ERR_CLAIM_TIER_INELIGIBLE`."

    Design: Corner/validations/claim_tier_ineligible_rejected
    """
    homeowner, home = setup_home(
        sale_price_cents=50_000_000, warranty_program="THIRD_PARTY_ADMINISTERED"
    )
    request = create_approved_request(
        home["id"], homeowner["id"],
        item_category="PLUMBING", description="Repipe",  # SYSTEMS tier
    )
    resp = api.create_administrator_claim(
        create_administrator_claim_payload(request["id"]), REP
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_TIER_INELIGIBLE)


def test_duplicate_claim_rejected(api):
    """PRD §3.8: "Three gates guard filing, in order: one claim per service
    request, else `ERR_DUPLICATE_CLAIM`; the home's `warranty_program` must be
    `THIRD_PARTY_ADMINISTERED`, else `ERR_PROGRAM_MISMATCH`; and the request must
    be `APPROVED` with `determined_tier` `STRUCTURAL`, else
    `ERR_CLAIM_TIER_INELIGIBLE`."

    Design: Corner/validations/duplicate_claim_rejected
    """
    ctx = setup_admin_claim()
    resp = api.create_administrator_claim(
        create_administrator_claim_payload(
            ctx["request"]["id"], claimed_amount_cents=400_000
        ),
        REP,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)


def test_claim_deny_requires_reason_then_terminal(api):
    """PRD §3.8: "An `outcome` of `DENY` requires the administrator's
    `denial_reason`, stamps `decided_at`, and moves the claim to `DENIED`,
    posting nothing. Both outcomes are terminal."
    PRD §2.7: "If the target sits in a terminal state for its lifecycle — a
    `CLOSED` service request; an `ACCEPTED` or `CANCELLED` work order; a `PAID`,
    `WAIVED`, or `VOID` chargeback; a `PAID` or `DENIED` claim — the rejection is
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/claim_deny_requires_reason_then_terminal
    """
    ctx = setup_admin_claim()
    resp = api.decide_administrator_claim(ctx["claim"]["id"], {"outcome": "DENY"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    denied = decide_claim(
        ctx["claim"]["id"], "DENY",
        denial_reason="Pre-existing soil condition excluded",
    )
    assert denied["status"] == "DENIED"

    resp2 = api.decide_administrator_claim(
        ctx["claim"]["id"],
        {"outcome": "ACCEPT", "approved_amount_cents": 900_000},
        ADMIN,
    )
    validate_error(resp2, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_claim_accept_over_claimed_invalid(api):
    """PRD §3.8: "An `outcome` of `ACCEPT` carries `approved_amount_cents`,
    positive and no more than the claimed amount — an acceptance without a
    conforming amount fails request validation — stamps `decided_at`, moves the
    claim to `PAID`, and posts a `RECOVERY` entry for the approved amount to the
    home's reserve, `claim_ref` attached, recomputing the balance and recovered
    totals and re-evaluating the alert."

    Design: Corner/validations/claim_accept_over_claimed_invalid
    """
    ctx = setup_admin_claim(claimed_amount_cents=900_000)
    resp = api.decide_administrator_claim(
        ctx["claim"]["id"],
        {"outcome": "ACCEPT", "approved_amount_cents": 900_001},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    accepted = decide_claim(
        ctx["claim"]["id"], "ACCEPT", approved_amount_cents=800_000
    )
    assert accepted["status"] == "PAID"
    assert accepted["approved_amount_cents"] == 800_000

    reserve = get_reserve_for_home(ctx["home"]["id"])
    assert reserve["recovered_to_date_cents"] == 800_000
    assert reserve["balance_cents"] == 800_000, (
        "administrator reimbursement credited to the reserve"
    )
