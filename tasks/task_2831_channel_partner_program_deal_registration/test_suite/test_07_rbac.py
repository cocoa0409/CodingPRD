"""Role mandates: the four exclusive operations that each role alone may perform, the
authorisation check that outranks existence, and the two segregated actor pairs."""

from prd_bench_local_runner.testing import build_user_headers

from test_helpers import (
    ANALYST,
    DIRECTOR,
    DIRECT_REP,
    NON_EXISTENT_UUID,
    ApiErrorId,
    OPS_ANALYST_USER_ID,
    add_certification,
    create_account,
    create_deal_registration_payload,
    create_partner_payload,
    decide_registration_payload,
    direct_pursuit_payload,
    prepare_review,
    read_account,
    read_allocation,
    read_claim,
    read_partner,
    read_registration,
    read_review,
    review_registration_payload,
    seed_validated_gold_claim,
    set_clock,
    settle_claim_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST_ACTING_AS_DIRECTOR = build_user_headers(OPS_ANALYST_USER_ID, "ChannelDirector")


class TestEachRoleActsWithinItsOwnMandate:
    def test_the_four_roles_each_complete_their_own_exclusive_operation(self, api):
        """PRD §2.1: "A `ChannelOpsAnalyst` is channel operations: it enrols partners, records
        certifications, maintains the account coverage map, proposes account mapping agreements,
        reviews deal registrations, prices and invoices orders, opens and closes market development
        fund periods, verifies proof documents, validates claims, and prepares performance reviews."
        PRD §2.1: "A `ChannelDirector` is the approval authority: it decides deal registrations,
        decides special pricing requests, resolves channel conflict cases, advances claim
        settlements, and decides performance reviews."
        PRD §2.1: "A `DirectSalesRep` is the vendor's own field seller, whose only write capability
        is declaring direct pursuit of an account and escalating a conflict case to the second rung."
        PRD §3.4: "The window length `protection_days` is read from the approving partner's `tier`
        as it stands at that moment: 30 days for `REGISTERED`, 60 for `SILVER`, 90 for `GOLD`, and
        120 for `PLATINUM`."

        Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
        """
        set_clock("2026-03-01T00:00:00.000Z")

        partner = validate_success(
            api.create_partner(
                create_partner_payload(
                    company_name="Ironwood Distribution",
                    partner_type="DISTRIBUTOR",
                    marketing_commitment_cents=0,
                ),
                ANALYST,
            ),
            201,
        )
        partner_id = partner["id"]
        add_certification(partner_id, engineer_name="Nils Berg", track="TECH_EXPERT")

        protected = create_account(account_name="Granite Health", region_code="NA")
        pursued = create_account(account_name="Beacon Medical", region_code="EMEA")

        registration = validate_success(
            api.create_deal_registration(
                create_deal_registration_payload(
                    partner_id,
                    protected["id"],
                    product_line="ANALYTICS_ADDON",
                    expected_amount_cents=600_000,
                    expected_close_date="2026-09-30T00:00:00.000Z",
                ),
                build_user_headers(partner_id, "Partner"),
            ),
            201,
        )
        registration_id = registration["id"]
        assert registration["status"] == "DRAFT"

        submitted = validate_success(
            api.submit_deal_registration(registration_id, build_user_headers(partner_id, "Partner"))
        )
        assert submitted["status"] == "SUBMITTED"

        under_review = validate_success(
            api.review_deal_registration(
                registration_id, review_registration_payload("START_REVIEW"), ANALYST
            )
        )
        assert under_review["status"] == "UNDER_REVIEW"

        approved = validate_success(
            api.decide_deal_registration(
                registration_id, decide_registration_payload("APPROVE"), DIRECTOR
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["protection_days"] == 30
        assert approved["exclusivity_start_at"] == "2026-03-01T00:00:00.000Z"
        assert approved["exclusivity_end_at"] == "2026-03-31T00:00:00.000Z"

        protected_account = read_account(protected["id"])
        assert protected_account["coverage_state"] == "CHANNEL_PROTECTED"
        assert protected_account["protected_partner_id"] == partner_id
        assert protected_account["protected_product_line"] == "ANALYTICS_ADDON"

        named = validate_success(
            api.declare_direct_pursuit(
                pursued["id"],
                direct_pursuit_payload(pursuit_note="field sales is working this account"),
                DIRECT_REP,
            )
        )
        assert named["coverage_state"] == "NAMED_DIRECT"
        assert named["direct_pursuit_owner_id"] == "u_dsr_1"
        assert named["direct_pursuit_declared_at"] == "2026-03-01T00:00:00.000Z"

    def test_no_role_may_reach_another_roles_exclusive_operation_even_on_a_fabricated_row(self, api):
        """PRD §2.1: "If both headers are well formed but the named role is not among the roles
        authorised for the requested endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §2.8: "Checks are evaluated in the ascending priority order below, and the first failing
        check wins."

        Design: Corner/rbac/roles_cannot_invoke_each_others_exclusive_operations
        """
        set_clock("2026-03-01T00:00:00.000Z")

        validate_error(
            api.decide_deal_registration(
                NON_EXISTENT_UUID,
                decide_registration_payload("APPROVE"),
                build_user_headers(NON_EXISTENT_UUID, "Partner"),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.settle_mdf_claim(
                NON_EXISTENT_UUID, settle_claim_payload("APPROVE_PAYMENT"), ANALYST
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.review_deal_registration(
                NON_EXISTENT_UUID, review_registration_payload("START_REVIEW"), DIRECTOR
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_partner(
                create_partner_payload(company_name="Rogue Reseller", partner_type="RESELLER"),
                DIRECT_REP,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        rows, meta = validate_paginated(api.list_partners(ANALYST))
        assert rows == []
        assert meta["total_count"] == 0


class TestSegregationOfDutiesIsCheckedOnTheUserId:
    def test_the_analyst_who_prepared_the_review_cannot_decide_it_even_as_a_director(self, api):
        """PRD §3.9: "Only the channel director decides a review, supplying a `decision` of
        `APPROVE` or `REJECT`, and in both cases the acting `X-User-ID` must differ from the review's
        `prepared_by_user_id` or the request is rejected with `ERR_SOD_SAME_ACTOR`."
        PRD §2.1: "Because these three identifiers are opaque, the segregation-of-duties comparisons
        in §2.8 are string comparisons between two recorded operator identifiers, not entity
        lookups."
        PRD §3.9: "Approval writes `approved_tier` from the final variant's gate ladder and copies
        it onto the partner's `tier` — the one and only writer of that field in the whole service."

        Design: Corner/rbac/preparer_cannot_decide_the_review_it_prepared
        """
        set_clock("2026-02-01T00:00:00.000Z")
        partner = validate_success(
            api.create_partner(
                create_partner_payload(
                    company_name="Halyard Systems",
                    partner_type="RESELLER",
                    marketing_commitment_cents=0,
                ),
                ANALYST,
            ),
            201,
        )
        partner_id = partner["id"]
        assert partner["cert_credit_total"] == 0

        review = prepare_review(
            partner_id,
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-01-31T23:59:59.999Z",
            findings_count=0,
        )
        review_id = review["id"]
        assert review["status"] == "PREPARED"
        assert review["prepared_by_user_id"] == OPS_ANALYST_USER_ID
        assert review["provisional_score"] == 25.0
        assert review["recommended_tier"] == "REGISTERED"
        assert review["decided_by_user_id"] is None
        assert review["final_score"] is None

        validate_error(
            api.decide_performance_review(
                review_id, {"decision": "APPROVE"}, ANALYST_ACTING_AS_DIRECTOR
            ),
            ApiErrorId.ERR_SOD_SAME_ACTOR.value,
            409,
        )
        refused = read_review(review_id)
        assert refused["status"] == "PREPARED"
        assert refused["decided_by_user_id"] is None
        assert refused["approved_tier"] is None
        assert refused["final_score"] is None

        decided = validate_success(
            api.decide_performance_review(review_id, {"decision": "APPROVE"}, DIRECTOR)
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "u_dir_1"
        assert decided["final_score"] == 25.0
        assert decided["approved_tier"] == "REGISTERED"

        settled = read_partner(partner_id)
        assert settled["tier"] == "REGISTERED"
        assert settled["tier_status"] == "COMPLIANT"
        assert settled["standing_reason"] is None

    def test_the_analyst_who_validated_the_claim_cannot_settle_it_and_no_cents_move(self, api):
        """PRD §3.8: "Every settlement action records the acting director's opaque identifier as
        `settled_by_user_id`, advances the claim's `version` by 1, and is barred to the operator who
        validated the claim: if the acting `X-User-ID` equals the claim's `validated_by_user_id` the
        action is rejected with `ERR_SOD_SAME_ACTOR`."
        PRD §3.8: "`APPROVE_PAYMENT` moves the claim `UNPAID → APPROVED_FOR_PAYMENT`."
        PRD §3.8: "No cents move: the claim's `approved_cents` was already sitting in
        `committed_cents`."

        Design: Corner/rbac/validator_cannot_settle_the_claim_it_validated
        """
        seed = seed_validated_gold_claim(
            requested_cents=20_000,
            spend_amount_cents=12_000,
            activity_type="EVENT",
            doc_type="INVOICE",
            audience_reach=400,
        )
        claim_id = seed["claim"]["id"]
        allocation_id = seed["allocation"]["id"]

        assert seed["claim"]["validated_by_user_id"] == OPS_ANALYST_USER_ID
        assert seed["claim"]["validation_state"] == "VALIDATED"
        assert seed["claim"]["approved_cents"] == 6000
        assert seed["claim"]["settlement_state"] == "UNPAID"

        before = read_allocation(allocation_id)
        assert before["allocated_cents"] == 273000
        assert before["committed_cents"] == 6000
        assert before["paid_cents"] == 0
        assert before["available_cents"] == 267000

        validate_error(
            api.settle_mdf_claim(
                claim_id, settle_claim_payload("APPROVE_PAYMENT"), ANALYST_ACTING_AS_DIRECTOR
            ),
            ApiErrorId.ERR_SOD_SAME_ACTOR.value,
            409,
        )
        refused = read_claim(claim_id)
        assert refused["settlement_state"] == "UNPAID"
        assert refused["settled_by_user_id"] is None

        after_refusal = read_allocation(allocation_id)
        assert after_refusal["committed_cents"] == 6000
        assert after_refusal["paid_cents"] == 0
        assert after_refusal["available_cents"] == 267000

        settled = validate_success(
            api.settle_mdf_claim(claim_id, settle_claim_payload("APPROVE_PAYMENT"), DIRECTOR)
        )
        assert settled["settlement_state"] == "APPROVED_FOR_PAYMENT"
        assert settled["settled_by_user_id"] == "u_dir_1"
        assert settled["validated_by_user_id"] == OPS_ANALYST_USER_ID

        final = read_allocation(allocation_id)
        assert final["committed_cents"] == 6000
        assert final["paid_cents"] == 0
        assert final["available_cents"] == 267000
