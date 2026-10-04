"""Escrow lifecycle: signing gates, funding exactness, OCC, and the close/cancel cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    attach_lease,
    close_escrow,
    create_offer_for,
    fund_escrow,
    get_offer_escrow,
    get_success_data,
    make_buyer_headers,
    make_seller_headers,
    send_docs,
    set_clock,
    setup_accepted_offer,
    setup_buyer,
    setup_certified_listing,
    setup_funded_escrow,
    setup_listed_listing,
    setup_signed_escrow,
    submit_offer,
    validate_error,
    validate_success,
)
from test_helpers import ESCROW_OFFICER_HEADERS


class TestEscrowRemoteSigning:
    def test_out_of_state_sign_without_notarization_rejected(self, api):
        """PRD §3.7: "When `remote_signing_required` is true, the payload must
        carry a present, non-empty `remote_notarization_ref`; an out-of-state
        buyer attempting to sign without it is rejected with
        `ERR_REMOTE_SIGNING_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/escrow_sign_depends_on_offer_ownership_and_remote_flag
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_accepted_offer(buyer_overrides={"buyer_state": "CA"})
        escrow = send_docs(ctx["escrow"])
        assert escrow["remote_signing_required"] is True
        resp = api.sign_escrow(
            escrow["id"],
            {"expected_escrow_version": escrow["version"]},
            make_buyer_headers(ctx["buyer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REMOTE_SIGNING_REQUIRED)
        current = get_offer_escrow(ctx["buyer"], ctx["offer"])
        assert current["status"] == "DOCS_SENT"

    def test_out_of_state_sign_with_notarization_succeeds(self, api):
        """PRD §3.7: "When `remote_signing_required` is true, the payload must
        carry a present, non-empty `remote_notarization_ref`; an out-of-state
        buyer attempting to sign without it is rejected with
        `ERR_REMOTE_SIGNING_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/escrow_sign_depends_on_offer_ownership_and_remote_flag
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_accepted_offer(buyer_overrides={"buyer_state": "CA"})
        ctx["escrow"] = send_docs(ctx["escrow"])
        signed = get_success_data(
            api.sign_escrow(
                ctx["escrow"]["id"],
                {
                    "expected_escrow_version": ctx["escrow"]["version"],
                    "remote_notarization_ref": "NOTARY-99",
                },
                make_buyer_headers(ctx["buyer"]["id"]),
            )
        )
        assert signed["status"] == "SIGNED"


class TestEscrowFunding:
    def test_funding_one_cent_short_rejected(self, api):
        """PRD §3.7: "Funding (`SIGNED` → `FUNDED`) is likewise the buyer's
        action: the payload's `funded_amount_cents` must equal the accepted
        offer's `amount_cents` exactly — any shortfall or overpayment is
        rejected with `ERR_INSUFFICIENT_FUNDS` — and the funded amount is
        recorded."

        Design: Corner/validations/escrow_fund_amount_mismatch_rejected
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_accepted_offer(offer_overrides={"amount_cents": 10_000_000})
        ctx = setup_signed_escrow(ctx)
        resp = api.fund_escrow(
            ctx["escrow"]["id"],
            {"funded_amount_cents": ctx["offer"]["amount_cents"] - 1},
            make_buyer_headers(ctx["buyer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS, expected_status=402)
        current = get_offer_escrow(ctx["buyer"], ctx["offer"])
        assert current["status"] == "SIGNED"

    def test_exact_funding_moves_escrow_to_funded(self, api):
        """PRD §3.7: "Funding (`SIGNED` → `FUNDED`) is likewise the buyer's
        action: the payload's `funded_amount_cents` must equal the accepted
        offer's `amount_cents` exactly — any shortfall or overpayment is
        rejected with `ERR_INSUFFICIENT_FUNDS` — and the funded amount is
        recorded."

        Design: Corner/validations/escrow_fund_amount_mismatch_rejected
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_accepted_offer(offer_overrides={"amount_cents": 10_000_000})
        ctx = setup_signed_escrow(ctx)
        funded = fund_escrow(ctx["buyer"], ctx["offer"], ctx["offer"]["amount_cents"])
        assert funded["status"] == "FUNDED"
        assert funded["funded_amount_cents"] == ctx["offer"]["amount_cents"]


class TestEscrowSignOcc:
    def test_sign_with_stale_version_rejected(self, api):
        """PRD §2.6: "Signing an escrow requires `expected_escrow_version` as a
        non-optional input carrying the signer's last observed `version` of the
        escrow. If the escrow's current `version` has advanced since the signer
        last observed it — for example because a prior sign attempt already
        advanced it — the sign is rejected with `ERR_STALE_ESCROW_VERSION`
        (HTTP 412); the signer must re-read the escrow before signing."

        Design: Corner/cross_cutting_layers/occ_escrow_sign_stale_version
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_accepted_offer()
        ctx["escrow"] = send_docs(ctx["escrow"])
        resp = api.sign_escrow(
            ctx["escrow"]["id"],
            {"expected_escrow_version": ctx["escrow"]["version"] - 1},
            make_buyer_headers(ctx["buyer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ESCROW_VERSION, expected_status=412)

    def test_sign_with_fresh_version_succeeds_and_bumps_version(self, api):
        """PRD §2.6: "A successful sign increments the escrow's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_escrow_sign_stale_version
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_accepted_offer()
        ctx["escrow"] = send_docs(ctx["escrow"])
        version_before = ctx["escrow"]["version"]
        signed = get_success_data(
            api.sign_escrow(
                ctx["escrow"]["id"],
                {"expected_escrow_version": version_before},
                make_buyer_headers(ctx["buyer"]["id"]),
            )
        )
        assert signed["status"] == "SIGNED"
        assert signed["version"] == version_before + 1


class TestEscrowCancelCompensation:
    def test_cancel_returns_listing_to_listed(self, api):
        """PRD §3.7: "An escrow may instead be cancelled by the `EscrowOfficer`
        from `OPENED`, `DOCS_SENT`, or `SIGNED`, which returns the listing from
        `UNDER_CONTRACT` to `LISTED` and voids any guarantee on the listing in
        `ISSUED` or `ACTIVE`."

        Design: Difficulty/compensating_invariant/escrow_cancel_compensates_listing_and_guarantee
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_accepted_offer()
        cancelled = get_success_data(
            api.transition_escrow(ctx["escrow"]["id"], {"action": "CANCEL"}, ESCROW_OFFICER_HEADERS)
        )
        assert cancelled["status"] == "CANCELLED"
        listing = get_success_data(
            api.get_listing(ctx["listing"]["id"], make_seller_headers(ctx["seller"]["id"]))
        )
        assert listing["status"] == "LISTED"

    def test_cancel_voids_issued_guarantee_and_listing_resellable(self, api):
        """PRD §3.7: "An escrow may instead be cancelled by the `EscrowOfficer`
        from `OPENED`, `DOCS_SENT`, or `SIGNED`, which returns the listing from
        `UNDER_CONTRACT` to `LISTED` and voids any guarantee on the listing in
        `ISSUED` or `ACTIVE`."

        Design: Difficulty/compensating_invariant/escrow_cancel_compensates_listing_and_guarantee
        """
        from test_helpers import create_guarantee_payload, setup_program
        from test_helpers import PLATFORM_ADMIN_HEADERS

        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_listed_listing()
        buyer1 = setup_buyer(legal_name="Buyer One")
        buyer2 = setup_buyer(legal_name="Buyer Two")
        guarantee = get_success_data(
            api.create_guarantee(
                ctx["listing"]["id"],
                create_guarantee_payload(guarantee_kind="VACANCY", coverage_months=3),
                PLATFORM_ADMIN_HEADERS,
            )
        )
        offer1 = create_offer_for(buyer1, ctx["listing"]["id"], ctx["listing"]["version"])
        offer1 = submit_offer(buyer1, offer1)
        seller_h = make_seller_headers(ctx["seller"]["id"])
        get_success_data(api.transition_offer(offer1["id"], {"action": "ACCEPT"}, seller_h))
        escrow = get_offer_escrow(buyer1, offer1)
        get_success_data(
            api.transition_escrow(escrow["id"], {"action": "CANCEL"}, ESCROW_OFFICER_HEADERS)
        )
        guarantees = get_success_data(
            api.list_guarantees(ctx["listing"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert guarantees[0]["status"] == "VOID"
        # Listing must be sellable again: a fresh offer submits cleanly.
        listing = get_success_data(api.get_listing(ctx["listing"]["id"], seller_h))
        assert listing["status"] == "LISTED"
        offer2 = create_offer_for(buyer2, ctx["listing"]["id"], listing["version"])
        offer2 = submit_offer(buyer2, offer2)
        assert offer2["status"] == "SUBMITTED"
