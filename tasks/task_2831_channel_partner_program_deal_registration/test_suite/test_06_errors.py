"""Reachability and envelope shape for the error catalogue: authentication, the not-found
envelope, two guards on one fund claim, the renewal pointer, the margin ceiling, partner
scoping, and the suspension freeze."""

import pytest
from test_helpers import (
    ANALYST,
    DIRECTOR,
    DIRECTOR_USER_ID,
    NON_EXISTENT_UUID,
    OPS_ANALYST_USER_ID,
    ApiErrorId,
    attach_proof,
    create_claim,
    create_order,
    create_partner,
    create_spr,
    draft_registration,
    make_partner_headers,
    prepare_review,
    read_account,
    read_allocation,
    read_claim,
    read_partner,
    read_proof,
    read_registration,
    seed_gold_distributor_with_allocation,
    seed_protected_account,
    seed_two_resellers_with_accounts,
    set_clock,
    submit_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEnvelopeAndAuthentication:
    def test_an_omitted_user_id_header_is_refused_before_any_row_is_read(self, api):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` carries any string other than
        those four, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything
        else is examined."

        Design: Corner/errors/request_with_missing_x_user_id_header_returns_4xx
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")

        response = api.list_partners({"X-User-Role": "ChannelOpsAnalyst"})
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}, "no partner rows leak"

        rows, meta = validate_paginated(api.list_partners(ANALYST))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [partner["id"]], (
            "the same GET succeeds once both identity headers are present"
        )

    def test_the_not_found_envelope_carries_only_the_two_meta_fields_and_two_data_fields(
        self, api
    ):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
        error."

        Design: Corner/errors/not_found_envelope_shape_on_an_unknown_partner
        """
        set_clock("2026-03-01T00:00:00.000Z")

        response = api.get_partner(NON_EXISTENT_UUID, ANALYST)
        validate_error(response, ApiErrorId.ERR_PARTNER_NOT_FOUND.value, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
        assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
        assert (
            isinstance(body["meta"]["api_request_timestamp"], str)
            and body["meta"]["api_request_timestamp"]
        )
        assert body["data"]["error_id"] == ApiErrorId.ERR_PARTNER_NOT_FOUND.value
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert "http_status" not in body["data"], "the status lives in the transport, not the body"

    def test_settlement_before_validation_and_a_second_verification_are_both_refused(self, api):
        """PRD §3.7: "The two evolve separately and are stored and reported separately; the only
        coupling is that `settlement_state` may only advance while `validation_state` is
        `VALIDATED`."
        PRD §2.8: "The proof document being verified currently has `verified` set to false —
        otherwise `ERR_PROOF_ALREADY_VERIFIED` (409), on proof verification. A second verification
        would double-count the document's spend into the partner's qualified marketing spend."

        Design: Corner/errors/claim_settlement_before_validation_and_repeat_proof_verification_rejected
        """
        seed = seed_gold_distributor_with_allocation()
        partner_id = seed["partner"]["id"]
        allocation = seed["allocation"]
        assert allocation["allocated_cents"] == 273000
        assert allocation["available_cents"] == 273000

        claim = create_claim(allocation["id"], partner_id, activity_type="EVENT", requested_cents=20_000)
        proof = attach_proof(claim["id"], partner_id, spend_amount_cents=12_000)
        assert proof["verified"] is False

        validate_error(
            api.settle_mdf_claim(claim["id"], {"action": "APPROVE_PAYMENT"}, DIRECTOR),
            ApiErrorId.ERR_CLAIM_NOT_VALIDATED.value,
            409,
        )
        held = read_claim(claim["id"])
        assert held["settlement_state"] == "UNPAID"
        assert held["validation_state"] == "SUBMITTED"
        assert held["approved_cents"] is None
        assert held["settled_by_user_id"] is None

        verified = validate_success(api.verify_proof(claim["id"], proof["id"], ANALYST))
        assert verified["verified"] is True
        assert verified["verified_by_user_id"] == OPS_ANALYST_USER_ID
        assert verified["verified_at"] == "2026-02-10T00:00:00.000Z"

        validate_error(
            api.verify_proof(claim["id"], proof["id"], ANALYST),
            ApiErrorId.ERR_PROOF_ALREADY_VERIFIED.value,
            409,
        )
        assert read_proof(proof["id"])["verified"] is True

        assert read_partner(partner_id)["marketing_qualified_spend_cents"] == 0, (
            "the document's claim is not VALIDATED, so its spend is never counted, let alone twice"
        )
        settled_pool = read_allocation(allocation["id"])
        assert settled_pool["allocated_cents"] == 273000
        assert settled_pool["committed_cents"] == 20000
        assert settled_pool["paid_cents"] == 0
        assert settled_pool["available_cents"] == 253000


class TestGuardsOnRenewalsMarginsAndStanding:
    def test_a_renewal_pointer_across_product_lines_is_refused_and_the_matching_one_is_taken(
        self, api
    ):
        """PRD §3.3: "The single referential check applied at draft time is on the renewal pointer:
        when `supersedes_registration_id` is supplied it must name a registration of the same
        `partner_id`, the same `account_id` and the same `product_line`, whose `status` is
        `APPROVED`, or the draft is rejected with `ERR_SUPERSEDE_TARGET_INVALID`."

        Design: Corner/errors/supersede_target_on_a_different_product_line_is_rejected
        """
        seed = seed_protected_account(clock="2026-04-01T00:00:00.000Z")
        partner_id = seed["incumbent"]["id"]
        account_id = seed["account"]["id"]
        target_id = seed["incumbent_registration"]["id"]

        validate_error(
            api.create_deal_registration(
                {
                    "partner_id": partner_id,
                    "account_id": account_id,
                    "product_line": "SUPPORT_SERVICES",
                    "expected_amount_cents": 600000,
                    "expected_close_date": "2026-10-31T00:00:00.000Z",
                    "supersedes_registration_id": target_id,
                },
                make_partner_headers(partner_id),
            ),
            ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID.value,
            422,
        )
        rows, meta = validate_paginated(
            api.list_deal_registrations(ANALYST, params={"partner_id": partner_id})
        )
        assert meta["total_count"] == 1, "the refused draft wrote no row"
        assert [row["id"] for row in rows] == [target_id]

        renewal = validate_success(
            api.create_deal_registration(
                {
                    "partner_id": partner_id,
                    "account_id": account_id,
                    "product_line": "ANALYTICS_ADDON",
                    "expected_amount_cents": 700000,
                    "expected_close_date": "2026-10-31T00:00:00.000Z",
                    "supersedes_registration_id": target_id,
                },
                make_partner_headers(partner_id),
            ),
            201,
        )
        assert renewal["status"] == "DRAFT"
        assert renewal["supersedes_registration_id"] == target_id

        predecessor = read_registration(target_id)
        assert predecessor["status"] == "APPROVED"
        assert predecessor["closure_reason"] is None, "drafting a renewal supersedes nothing yet"
        assert read_account(account_id)["protected_until"] == "2026-05-01T00:00:00.000Z"

    def test_a_full_grant_breaches_the_tier_ceiling_while_a_partial_grant_lands_on_it(self, api):
        """PRD §3.6: "`PARTIAL` moves the request `SUBMITTED → PARTIALLY_APPROVED`, requires the
        same strictly-before-`expires_at` condition, requires a supplied `approved_extra_margin_pct`
        that is present, strictly greater than 0.0 and strictly less than
        `requested_extra_margin_pct` (otherwise `ERR_INVALID_REQUEST`), requires that the base margin
        for the tier plus 0.06 plus that supplied value stays at or below the tier's ceiling
        (otherwise `ERR_MARGIN_CEILING_EXCEEDED`), and stores the supplied value as
        `approved_extra_margin_pct`."
        PRD §3.6: "Add the volume uplift to the preliminary margin, raise the result to the program
        margin floor of 0.05 if it fell below it, then cap it at the ceiling for the partner's `tier`
        — 0.18 for `REGISTERED`, 0.24 for `SILVER`, 0.30 for `GOLD`, 0.36 for `PLATINUM` — and round
        the outcome half-up to four decimal places."

        Design: Corner/errors/special_pricing_grant_above_the_tier_ceiling_is_rejected
        """
        seed = seed_protected_account(clock="2026-04-01T00:00:00.000Z")
        partner_id = seed["incumbent"]["id"]
        registration_id = seed["incumbent_registration"]["id"]

        request = create_spr(registration_id, partner_id, requested_extra_margin_pct=0.05)
        assert request["status"] == "SUBMITTED"

        validate_error(
            api.decide_special_pricing_request(
                request["id"], {"decision": "APPROVE"}, DIRECTOR
            ),
            ApiErrorId.ERR_MARGIN_CEILING_EXCEEDED.value,
            422,
        )
        refused = validate_success(api.get_special_pricing_request(request["id"], ANALYST))
        assert refused["status"] == "SUBMITTED"
        assert refused["approved_extra_margin_pct"] is None

        granted = validate_success(
            api.decide_special_pricing_request(
                request["id"],
                {"decision": "PARTIAL", "approved_extra_margin_pct": 0.02},
                DIRECTOR,
            )
        )
        assert granted["status"] == "PARTIALLY_APPROVED"
        assert granted["approved_extra_margin_pct"] == pytest.approx(0.02, abs=1e-9)
        assert granted["decided_by_user_id"] == DIRECTOR_USER_ID

        order = create_order(
            partner_id,
            order_type="DROP_SHIP",
            list_amount_cents=4_000_000,
            registration_id=registration_id,
        )
        assert order["volume_band"] == "NONE"
        assert order["margin_pct"] == pytest.approx(0.1800, abs=1e-9), (
            "0.10 base plus 0.06 in-window uplift plus the 0.02 grant sits exactly on the ceiling"
        )
        assert order["invoice_amount_cents"] == 3280000
        assert order["margin_value_cents"] == 720000

    def test_a_foreign_partner_is_scope_refused_where_the_owner_succeeds(self, api):
        """PRD §2.1: "For a deal registration the compared field is the registration's own
        `partner_id`; for an account mapping agreement it is the mapping's `partner_id`; for a
        performance review it is the review's `partner_id`; for a market development fund claim it is
        the `partner_id` of the fund period the claim draws from; for a conflict escalation it is the
        `partner_id` of the case's subject registration; and for a create request it is the
        `partner_id` supplied in the body. A mismatch is rejected with `ERR_PARTNER_SCOPE_VIOLATION`
        (HTTP 403)."

        Design: Corner/errors/partner_cannot_submit_another_partners_registration
        """
        seed = seed_two_resellers_with_accounts(clock="2026-03-01T00:00:00.000Z")
        owner_id = seed["incumbent"]["id"]
        stranger_id = seed["challenger"]["id"]
        account_id = seed["accounts"][0]["id"]

        registration = draft_registration(
            owner_id, account_id, product_line="ANALYTICS_ADDON"
        )

        validate_error(
            api.submit_deal_registration(registration["id"], make_partner_headers(stranger_id)),
            ApiErrorId.ERR_PARTNER_SCOPE_VIOLATION.value,
            403,
        )
        untouched = read_registration(registration["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["submitted_at"] is None

        submitted = submit_registration(registration["id"], owner_id)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] == "2026-03-01T00:00:00.000Z"

    def test_a_rejected_review_suspends_the_partner_and_freezes_order_pricing(self, api):
        """PRD §3.9: "Rejection leaves `approved_tier` null and leaves the partner's `tier`
        untouched, but sets the partner's `tier_status` to `SUSPENDED` with `standing_reason`
        `PROGRAM_REVIEW_REJECTED` and recomputes `portal_entitlement_level`, which for a suspended
        partner short-circuits to `BASIC`."
        PRD §2.8: "The partner's `tier_status` is not `SUSPENDED` — otherwise `ERR_PARTNER_SUSPENDED`
        (403). This guards seven operations: registration submit, an approving registration decision,
        order pricing, order invoicing, fund-period creation, claim creation, and
        special-pricing-request creation."

        Design: Corner/errors/suspended_partner_is_frozen_out_of_order_pricing
        """
        set_clock("2026-02-01T00:00:00.000Z")
        partner = create_partner(
            company_name="Aster Systems", partner_type="RESELLER", marketing_commitment_cents=0
        )
        review = prepare_review(partner["id"], findings_count=0)
        assert review["provisional_score"] == pytest.approx(25.0, abs=1e-9), (
            "no credits and no revenue leaves only the vacuous marketing component"
        )
        assert review["recommended_tier"] == "REGISTERED"

        rejected = validate_success(
            api.decide_performance_review(review["id"], {"decision": "REJECT"}, DIRECTOR)
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["approved_tier"] is None
        assert rejected["decided_by_user_id"] == DIRECTOR_USER_ID

        suspended = read_partner(partner["id"])
        assert suspended["tier_status"] == "SUSPENDED"
        assert suspended["standing_reason"] == "PROGRAM_REVIEW_REJECTED"
        assert suspended["portal_entitlement_level"] == "BASIC"
        assert suspended["tier"] == "REGISTERED", "a rejection never writes the tier"

        validate_error(
            api.create_order_invoice(
                {
                    "partner_id": partner["id"],
                    "order_type": "DROP_SHIP",
                    "list_amount_cents": 1000000,
                },
                ANALYST,
            ),
            ApiErrorId.ERR_PARTNER_SUSPENDED.value,
            403,
        )
        rows, meta = validate_paginated(
            api.list_order_invoices(ANALYST, params={"partner_id": partner["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0
