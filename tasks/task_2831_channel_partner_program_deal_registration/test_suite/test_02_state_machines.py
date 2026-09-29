"""Lifecycle vocabulary: the state a create lands in, the transitions that are not declared,
the terminal states that refuse a replay, the loop caps, and the sweeps a transition fires."""

import pytest
from test_helpers import (
    ANALYST,
    DIRECTOR,
    DIRECTOR_2,
    DIRECTOR_USER_ID,
    DIRECT_REP,
    ApiErrorId,
    add_certification,
    assert_deal_registration,
    create_account,
    create_approved_registration,
    create_order,
    create_partner,
    draft_registration,
    escalate_conflict_payload,
    make_partner_headers,
    prepare_review,
    propose_mapping,
    read_account,
    read_allocation,
    read_claim,
    read_conflict_case,
    read_invoice,
    read_partner,
    read_registration,
    read_review,
    resolve_conflict_payload,
    respond_mapping,
    seed_gold_claim_with_verified_proof,
    seed_partner_vs_direct_conflict,
    seed_partner_vs_partner_conflict,
    set_clock,
    submit_registration,
    validate_claim,
    validate_error,
    validate_success,
)


class TestInitialStates:
    def test_a_fresh_draft_lands_in_draft_with_every_lifecycle_field_still_null(self, api):
        """PRD §3.3: "A new registration is stored with `status` `DRAFT`, `revision_round` 0,
        `registration_margin_uplift_pct` 0.0, and `submitted_at`, `approved_at`,
        `exclusivity_start_at`, `exclusivity_end_at`, `protection_days` and `closure_reason` all
        null."
        PRD §3.3: "Drafting validates almost nothing about the world."

        Design: Corner/state_machines/deal_registration_initial_state_is_draft
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        add_certification(partner["id"], engineer_name="Iva Sorel", track="TECH_ASSOCIATE")
        account = create_account(account_name="Granite Health", region_code="NA")

        registration = validate_success(
            api.create_deal_registration(
                {
                    "partner_id": partner["id"],
                    "account_id": account["id"],
                    "product_line": "SUPPORT_SERVICES",
                    "expected_amount_cents": 400000,
                    "expected_close_date": "2026-08-31T00:00:00.000Z",
                },
                make_partner_headers(partner["id"]),
            ),
            201,
        )
        assert_deal_registration(registration)

        assert registration["status"] == "DRAFT"
        assert registration["submitted_at"] is None
        assert registration["approved_at"] is None
        assert registration["exclusivity_start_at"] is None
        assert registration["exclusivity_end_at"] is None
        assert registration["protection_days"] is None
        assert registration["closure_reason"] is None
        assert registration["revision_round"] == 0
        assert registration["supersedes_registration_id"] is None
        assert registration["registration_margin_uplift_pct"] == pytest.approx(0.0, abs=1e-9)

        assert read_account(account["id"])["coverage_state"] == "OPEN_CHANNEL", (
            "creating a registration protects nothing"
        )


class TestUndeclaredTransitions:
    def test_a_decision_before_the_review_started_is_refused_and_writes_no_window(self, api):
        """PRD §3.4: "Approval moves the registration `UNDER_REVIEW → APPROVED` and is gated on
        four things: the registration is in `UNDER_REVIEW`; the partner's `tier_status` is not
        `SUSPENDED` (otherwise `ERR_PARTNER_SUSPENDED`); no other registration on the same
        account-and-product-line pair is in `APPROVED` holding a live exclusivity window at the
        current logical instant, unless that incumbent is precisely the registration this one
        supersedes (otherwise `ERR_EXCLUSIVITY_CONFLICT`); and, when `supersedes_registration_id`
        is set, the predecessor belongs to the same partner, matches on account and product line,
        and is itself in `APPROVED` (otherwise `ERR_SUPERSEDE_TARGET_INVALID`, or
        `ERR_INVALID_REQUEST` where the pointer is structurally unusable)."
        PRD §2.8: "The target row is in a state from which the requested transition is declared in
        §3, including the three loop caps: at most two completed revision rounds on a registration,
        at most two counter rounds on a mapping, and at most two proof rounds on a claim."

        Design: Corner/state_machines/registration_decision_before_review_start_rejected
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        add_certification(partner["id"], engineer_name="Iva Sorel", track="TECH_ASSOCIATE")
        account = create_account(account_name="Granite Health", region_code="NA")
        registration = draft_registration(
            partner["id"],
            account["id"],
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=400_000,
        )
        submit_registration(registration["id"], partner["id"])

        validate_error(
            api.decide_deal_registration(registration["id"], {"decision": "APPROVE"}, DIRECTOR),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        refused = read_registration(registration["id"])
        assert refused["status"] == "SUBMITTED"
        assert refused["approved_at"] is None
        assert refused["exclusivity_end_at"] is None
        assert refused["registration_margin_uplift_pct"] == pytest.approx(0.0, abs=1e-9)

        account_after = read_account(account["id"])
        assert account_after["coverage_state"] == "OPEN_CHANNEL"
        assert account_after["protected_partner_id"] is None

    def test_a_split_resolution_is_unavailable_on_a_partner_versus_direct_case(self, api):
        """PRD §3.5: "Resolving by splitting the account drives the case to `RESOLVED_SPLIT` and is
        available only on a `PARTNER_VS_PARTNER` case; a direct-sales conflict cannot be split, and
        attempting it is `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.2: "Second, because that case now exists, the protecting registration's
        `closure_reason` is set to `DIRECT_PURSUIT_CONTESTED` while its `status` remains `APPROVED`
        and its exclusivity window remains intact until the case resolves; that registration's
        `version` advances by 1."

        Design: Corner/state_machines/split_resolution_on_partner_versus_direct_case_rejected
        """
        seed = seed_partner_vs_direct_conflict()
        case_id = seed["case"]["id"]
        registration_id = seed["incumbent_registration"]["id"]

        validate_error(
            api.resolve_conflict_case(
                case_id,
                resolve_conflict_payload("SPLIT", resolution_note="share the account"),
                DIRECTOR,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        case = read_conflict_case(case_id)
        assert case["status"] == "OPEN"
        assert case["conflict_type"] == "PARTNER_VS_DIRECT"
        assert case["resolved_by_user_id"] is None

        registration = read_registration(registration_id)
        assert registration["status"] == "APPROVED"
        assert registration["protection_days"] == 30
        assert registration["exclusivity_end_at"] == "2026-05-01T00:00:00.000Z", (
            "no halving happened"
        )
        assert registration["closure_reason"] == "DIRECT_PURSUIT_CONTESTED"

        account = read_account(seed["account"]["id"])
        assert account["coverage_state"] == "CHANNEL_PROTECTED"
        assert account["protected_until"] == "2026-05-01T00:00:00.000Z"

    def test_paying_a_claim_that_never_reached_payment_approval_is_refused(self, api):
        """PRD §3.8: "`PAY` moves the claim `APPROVED_FOR_PAYMENT → PAID`. It requires
        `settlement_state` to be `APPROVED_FOR_PAYMENT` and the period to be `OPEN`."
        PRD §3.7: "The two evolve separately and are stored and reported separately; the only
        coupling is that `settlement_state` may only advance while `validation_state` is
        `VALIDATED`."

        Design: Corner/state_machines/claim_settlement_pay_before_payment_approval_rejected
        """
        seed = seed_gold_claim_with_verified_proof()
        claim_id = seed["claim"]["id"]
        allocation_id = seed["allocation"]["id"]

        validated = validate_claim(claim_id, "VALIDATE")
        assert validated["validation_state"] == "VALIDATED"
        assert validated["matched_total_cents"] == 6000
        assert validated["approved_cents"] == 6000
        assert validated["settlement_state"] == "UNPAID"

        validate_error(
            api.settle_mdf_claim(claim_id, {"action": "PAY"}, DIRECTOR),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        claim = read_claim(claim_id)
        assert claim["settlement_state"] == "UNPAID"
        assert claim["settled_by_user_id"] is None
        assert claim["validation_state"] == "VALIDATED"
        assert claim["approved_cents"] == 6000

        allocation = read_allocation(allocation_id)
        assert allocation["committed_cents"] == 6000
        assert allocation["paid_cents"] == 0
        assert allocation["expired_cents"] == 0
        assert allocation["available_cents"] == 267000


class TestTerminalStatesAndLoopCaps:
    def test_replaying_an_approved_review_decision_is_refused_and_rescores_nothing(self, api):
        """PRD §3.9: "Review lifecycle states are `PREPARED`, `FINDINGS_OPEN`, `REMEDIATED`, and
        the terminal `APPROVED` and `REJECTED`."
        PRD §3.9: "Approval writes `approved_tier` from the final variant's gate ladder and copies
        it onto the partner's `tier` — the one and only writer of that field in the whole service."

        Design: Corner/state_machines/performance_review_decided_twice_second_attempt_rejected
        """
        set_clock("2026-02-01T00:00:00.000Z")
        partner = create_partner(
            company_name="Aster Systems", partner_type="RESELLER", marketing_commitment_cents=0
        )
        add_certification(partner["id"], engineer_name="Iva Sorel", track="TECH_ASSOCIATE")
        review = prepare_review(partner["id"], findings_count=0)

        decided = validate_success(
            api.decide_performance_review(review["id"], {"decision": "APPROVE"}, DIRECTOR)
        )
        assert decided["status"] == "APPROVED"
        assert decided["final_cert_credit"] == 2
        assert decided["final_revenue_cents"] == 0
        assert decided["final_score"] == pytest.approx(31.67, abs=0.001)
        assert decided["approved_tier"] == "REGISTERED"

        validate_error(
            api.decide_performance_review(review["id"], {"decision": "APPROVE"}, DIRECTOR_2),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        replayed = read_review(review["id"])
        assert replayed["version"] == decided["version"], (
            "a refused replay of a terminal transition bumps no version"
        )
        assert replayed["decided_by_user_id"] == DIRECTOR_USER_ID
        assert replayed["final_score"] == pytest.approx(31.67, abs=0.001)

        reloaded = read_partner(partner["id"])
        assert reloaded["tier"] == "REGISTERED"
        assert reloaded["tier_status"] == "COMPLIANT"

    def test_the_third_counter_on_a_mapping_is_refused_and_leaves_the_second_window_stored(
        self, api
    ):
        """PRD §3.2: "The cycle alternates sides: the partner counters an agreement sitting in
        `PROPOSED`, moving it `PROPOSED → COUNTERED`, and the vendor's channel operations counters
        an agreement sitting in `COUNTERED`, moving it `COUNTERED → PROPOSED`."
        PRD §3.2: "Both sides share the same `counter_round` counter, and at most two counters may
        ever be applied — a third is rejected with `ERR_INVALID_STATE_TRANSITION` and writes
        nothing."

        Design: Corner/state_machines/account_mapping_third_counter_blocked_by_round_cap
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        account = create_account(account_name="Granite Health", region_code="NA")

        mapping = propose_mapping(
            partner["id"],
            account["id"],
            read_account(account["id"])["version"],
            effective_from="2026-05-01T00:00:00.000Z",
            effective_until="2026-05-31T23:59:59.999Z",
        )
        assert mapping["mapping_status"] == "PROPOSED"
        assert mapping["counter_round"] == 0

        first = respond_mapping(
            mapping["id"],
            "COUNTER",
            make_partner_headers(partner["id"]),
            effective_from="2026-06-01T00:00:00.000Z",
            effective_until="2026-06-30T23:59:59.999Z",
        )
        assert first["mapping_status"] == "COUNTERED"
        assert first["counter_round"] == 1

        second = respond_mapping(
            mapping["id"],
            "COUNTER",
            ANALYST,
            effective_from="2026-07-01T00:00:00.000Z",
            effective_until="2026-07-31T23:59:59.999Z",
        )
        assert second["mapping_status"] == "PROPOSED"
        assert second["counter_round"] == 2

        validate_error(
            api.respond_account_mapping(
                mapping["id"],
                {
                    "action": "COUNTER",
                    "effective_from": "2026-08-01T00:00:00.000Z",
                    "effective_until": "2026-08-31T23:59:59.999Z",
                },
                make_partner_headers(partner["id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        refused = validate_success(api.get_account_mapping(mapping["id"], ANALYST))
        assert refused["counter_round"] == 2
        assert refused["effective_from"] == "2026-07-01T00:00:00.000Z"
        assert refused["effective_until"] == "2026-07-31T23:59:59.999Z"
        assert refused["mapping_status"] == "PROPOSED"

    def test_a_third_escalation_is_refused_and_writes_nothing_whatsoever(self, api):
        """PRD §3.5: "A direct sales representative escalates a case sitting in `ESCALATED_TIER1`,
        moving it `ESCALATED_TIER1 → ESCALATED_TIER2` and setting `escalation_level` to 2."
        PRD §3.5: "Escalating a case whose `escalation_level` is already 2 is rejected with
        `ERR_CONFLICT_ESCALATION_LIMIT` and writes nothing whatsoever."

        Design: Corner/state_machines/conflict_case_escalation_beyond_tier_two_rejected
        """
        seed = seed_partner_vs_partner_conflict()
        case_id = seed["case"]["id"]
        subject = read_registration(seed["case"]["subject_registration_id"])
        subject_partner_id = subject["partner_id"]

        tier_one = validate_success(
            api.escalate_conflict_case(
                case_id,
                escalate_conflict_payload(
                    escalation_note="partner registered first, requesting review"
                ),
                make_partner_headers(subject_partner_id),
            )
        )
        assert tier_one["status"] == "ESCALATED_TIER1"
        assert tier_one["escalation_level"] == 1

        tier_two = validate_success(
            api.escalate_conflict_case(
                case_id,
                escalate_conflict_payload(
                    escalation_note="direct sales requests tier 2 arbitration"
                ),
                DIRECT_REP,
            )
        )
        assert tier_two["status"] == "ESCALATED_TIER2"
        assert tier_two["escalation_level"] == 2

        validate_error(
            api.escalate_conflict_case(
                case_id,
                escalate_conflict_payload(escalation_note="third escalation attempt"),
                DIRECT_REP,
            ),
            ApiErrorId.ERR_CONFLICT_ESCALATION_LIMIT.value,
            409,
        )

        refused = read_conflict_case(case_id)
        assert refused["escalation_level"] == 2
        assert refused["resolution_note"] == "direct sales requests tier 2 arbitration"
        assert refused["status"] == "ESCALATED_TIER2"
        assert refused["resolved_by_user_id"] is None
        assert refused["version"] == tier_two["version"]


class TestTransitionSideEffects:
    def test_preparing_a_review_is_the_only_producer_of_an_expired_certification(self, api):
        """PRD §3.9: "Before anything is scored, cascade E sweeps the partner's certifications:
        every certification record of that partner whose `status` is `ACTIVE` and whose `expires_at`
        is at or before the current logical instant moves `ACTIVE → EXPIRED` with its `version`
        advanced by 1, and then — because those records left `ACTIVE` — the partner's
        `cert_credit_total` is recomputed by the full rollup of §3.1 and `portal_entitlement_level`
        is recomputed from the result."
        PRD §3.9: "Preparing a review is the **only** producer of a certification record in
        `EXPIRED`; certifications never lapse on their own."

        Design: Corner/state_machines/certification_expiry_sweep_fires_on_review_preparation
        """
        set_clock("2026-01-05T00:00:00.000Z")
        partner = create_partner(
            company_name="Aster Systems", partner_type="RESELLER", marketing_commitment_cents=0
        )
        record = add_certification(
            partner["id"],
            engineer_name="Iva Sorel",
            track="TECH_EXPERT",
            issued_at="2025-06-01T00:00:00.000Z",
            expires_at="2026-01-15T00:00:00.000Z",
        )
        assert read_partner(partner["id"])["cert_credit_total"] == 4
        assert validate_success(api.get_certification(record["id"], ANALYST))["status"] == "ACTIVE"

        set_clock("2026-02-01T00:00:00.000Z")
        review = validate_success(
            api.create_performance_review(
                {
                    "partner_id": partner["id"],
                    "period_start": "2026-01-01T00:00:00.000Z",
                    "period_end": "2026-01-31T23:59:59.999Z",
                    "findings_count": 0,
                },
                ANALYST,
            ),
            201,
        )

        swept = validate_success(api.get_certification(record["id"], ANALYST))
        assert swept["status"] == "EXPIRED"
        assert swept["credit_weight"] == 4, "the weight is fixed at creation and forever after"

        reloaded = read_partner(partner["id"])
        assert reloaded["cert_credit_total"] == 0
        assert reloaded["portal_entitlement_level"] == "BASIC"

        assert review["provisional_cert_credit"] == 0
        assert review["provisional_revenue_cents"] == 0
        assert review["provisional_score"] == pytest.approx(25.0, abs=0.001)
        assert review["recommended_tier"] == "REGISTERED"
        assert review["status"] == "PREPARED"
        assert review["remediation_due_at"] is None

    def test_conversion_waits_for_an_order_to_reach_invoiced(self, api):
        """PRD §3.4: "Once at least one order priced against an approved registration has reached
        `INVOICED` or `CREDITED`, channel operations marks the registration `APPROVED → CONVERTED`
        with `closure_reason` `CONVERTED` and the `version` advanced by 1."
        PRD §3.4: "Attempting conversion while no such order exists is
        `ERR_INVALID_STATE_TRANSITION`, as is attempting it from any state other than `APPROVED`."

        Design: Corner/state_machines/registration_convert_requires_an_invoiced_order
        """
        set_clock("2026-04-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        add_certification(partner["id"], engineer_name="Iva Sorel", track="TECH_ASSOCIATE")
        account = create_account(account_name="Granite Health", region_code="NA")
        registration = create_approved_registration(partner["id"], account["id"])
        assert registration["exclusivity_end_at"] == "2026-05-01T00:00:00.000Z"

        order = create_order(
            partner["id"],
            order_type="DROP_SHIP",
            list_amount_cents=4_000_000,
            registration_id=registration["id"],
        )
        assert order["margin_pct"] == pytest.approx(0.1600, abs=1e-9)
        assert order["invoice_amount_cents"] == 3360000
        assert order["margin_value_cents"] == 640000
        assert order["status"] == "PENDING"

        validate_error(
            api.convert_deal_registration(registration["id"], ANALYST),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )
        assert read_registration(registration["id"])["status"] == "APPROVED"

        validate_success(api.invoice_order(order["id"], ANALYST))
        invoiced = read_invoice(order["id"])
        assert invoiced["status"] == "INVOICED"
        assert invoiced["invoiced_at"] == "2026-04-01T00:00:00.000Z"
        assert read_partner(partner["id"])["trailing_revenue_cents"] == 3360000

        converted = validate_success(api.convert_deal_registration(registration["id"], ANALYST))
        assert converted["status"] == "CONVERTED"
        assert converted["closure_reason"] == "CONVERTED"
        assert converted["exclusivity_end_at"] == "2026-05-01T00:00:00.000Z"
