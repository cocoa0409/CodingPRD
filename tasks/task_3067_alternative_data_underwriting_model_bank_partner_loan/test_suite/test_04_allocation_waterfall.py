"""The allocation waterfall: channel priority, eligibility criteria, reason
codes, pool boundaries, the monthly volume cap, and allocation side effects."""
from test_helpers import (
    ApiErrorId,
    attach_active_credit_box,
    create_active_model,
    create_applicant,
    create_credit_box_payload,
    create_partner,
    create_securitization_pool_payload,
    get_success_data,
    pass_all_instant_checks,
    setup_underwritten_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAllocationPreconditions:

    def test_allocate_on_verification_pending_application_is_invalid_state(
        self, api, platform_admin_headers, auditor_headers
    ):
        """PRD 3.9: "Allocation is triggered by a `PlatformAdmin` against an `UNDERWRITTEN` application"
        PRD 3.4: "a withdrawal attempt in any other state fails with `ERR_APPLICATION_INVALID_STATE`."
        PRD 5: "`ERR_APPLICATION_INVALID_STATE` | 409"

        Design: Corner/endpoints/allocate_on_submitted_application_is_invalid_state
        """
        create_active_model(model_code="ADU-N-2")
        applicant = create_applicant(full_name="Early Earl")
        app = submit_application(applicant["id"])
        assert app["status"] == "VERIFICATION_PENDING"

        resp = api.allocate_application(app["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)

        data, meta = validate_paginated(
            api.list_allocation_decisions(auditor_headers, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 0
        data, meta = validate_paginated(
            api.list_loans(auditor_headers, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 0


class TestFirstFailureReasonOrder:

    def test_referral_state_failure_records_state_not_allowed_and_falls_through(
        self, api, platform_admin_headers, auditor_headers
    ):
        """PRD 3.9: "Rejection reasons are recorded in the order the checks first fail: `PARTNER_INACTIVE`, `NO_ACTIVE_CREDIT_BOX`, `STATE_NOT_ALLOWED`, `SCORE_BELOW_BOX`, `SCORE_ABOVE_BOX`, `AMOUNT_BELOW_BOX`, `AMOUNT_ABOVE_BOX`, then `VOLUME_CAP_REACHED`."
        PRD 3.9: "If eligible, the loan is placed there and the walk stops; if not, the rejection reasons are recorded and the walk continues - a referral failure never blocks the remaining channels."

        Design: Difficulty/combinatorial_formula/allocation_selector_multi_input_first_failure_reason_order
        """
        create_active_model(model_code="ADU-B-2")
        # Referral bank R accepts TX only.
        bank_r = create_partner(legal_name="Referral Bank R")
        attach_active_credit_box(bank_r["id"], allowed_states=["TX"], monthly_volume_cap_count=1)
        # Whole-loan buyer W covers TX and CA.
        buyer = create_partner(
            legal_name="Whole Buyer W", partner_type="LOAN_BUYER", home_state="DE"
        )
        attach_active_credit_box(buyer["id"], allowed_states=["TX", "CA"])

        applicant = create_applicant(full_name="Cali Carol", state_code="CA")
        app = submit_application(
            applicant["id"], channel="PARTNER_REFERRAL", referral_partner_id=bank_r["id"]
        )
        app = pass_all_instant_checks(app["id"])
        assert app["status"] == "UNDERWRITTEN"

        decision = validate_success(api.allocate_application(app["id"], platform_admin_headers))
        assert decision["channel"] == "WHOLE_LOAN_SALE"
        assert decision["chosen_partner_id"] == buyer["id"]
        assert "STATE_NOT_ALLOWED" in decision["reason_codes"]
        # The score checks never ran for R: the state check failed first.
        assert "SCORE_BELOW_BOX" not in decision["reason_codes"]
        assert "SCORE_ABOVE_BOX" not in decision["reason_codes"]

        app = get_success_data(api.get_application(app["id"], platform_admin_headers))
        assert app["status"] == "APPROVED"
        data, meta = validate_paginated(
            api.list_loans(auditor_headers, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 1
        loan = data[0]
        assert loan["holder_partner_id"] == buyer["id"]
        assert loan["allocation_channel"] == "WHOLE_LOAN_SALE"
        assert loan["principal_cents"] == 5000000
        assert loan["apr"] == 12.0

    def test_referral_cap_failure_records_volume_cap_reached_and_falls_through(
        self, api, platform_admin_headers
    ):
        """PRD 3.9: "Rejection reasons are recorded in the order the checks first fail: `PARTNER_INACTIVE`, `NO_ACTIVE_CREDIT_BOX`, `STATE_NOT_ALLOWED`, `SCORE_BELOW_BOX`, `SCORE_ABOVE_BOX`, `AMOUNT_BELOW_BOX`, `AMOUNT_ABOVE_BOX`, then `VOLUME_CAP_REACHED`."
        PRD 3.9: "if not, the rejection reasons are recorded and the walk continues - a referral failure never blocks the remaining channels."

        Design: Difficulty/combinatorial_formula/allocation_selector_multi_input_first_failure_reason_order
        """
        create_active_model(model_code="ADU-B-2C")
        # Referral bank R: TX, cap 1.
        bank_r = create_partner(legal_name="Referral Bank R Cap")
        attach_active_credit_box(bank_r["id"], allowed_states=["TX"], monthly_volume_cap_count=1)
        buyer = create_partner(
            legal_name="Whole Buyer W Cap", partner_type="LOAN_BUYER", home_state="DE"
        )
        attach_active_credit_box(buyer["id"], allowed_states=["TX", "CA"])

        # First referral application fills R's monthly cap.
        applicant_one = create_applicant(full_name="Cap One", state_code="TX")
        app_one = submit_application(
            applicant_one["id"], channel="PARTNER_REFERRAL", referral_partner_id=bank_r["id"]
        )
        app_one = pass_all_instant_checks(app_one["id"])
        decision_one = validate_success(
            api.allocate_application(app_one["id"], platform_admin_headers)
        )
        assert decision_one["channel"] == "REFERRAL_RETAINED"

        # Second referral application: R is now capped; the waterfall continues.
        applicant_two = create_applicant(full_name="Cap Two", state_code="TX")
        app_two = submit_application(
            applicant_two["id"], channel="PARTNER_REFERRAL", referral_partner_id=bank_r["id"]
        )
        app_two = pass_all_instant_checks(app_two["id"])
        decision_two = validate_success(
            api.allocate_application(app_two["id"], platform_admin_headers)
        )
        assert decision_two["channel"] == "WHOLE_LOAN_SALE"
        assert decision_two["chosen_partner_id"] == buyer["id"]
        assert "VOLUME_CAP_REACHED" in decision_two["reason_codes"]
        # Earlier checks passed for R, so no earlier reason codes appear for it
        # beyond the first failure recorded.
        assert "STATE_NOT_ALLOWED" not in decision_two["reason_codes"]


class TestScoreBoundary:

    def test_score_at_min_score_is_accepted_inclusively(
        self, api, platform_admin_headers
    ):
        """PRD 3.9: "the application's `risk_score` lies within the box's inclusive band from `min_score` to `max_score`"
        PRD 2.6: "Comparisons against bounds are inclusive on both ends unless a rule says otherwise."

        Design: Difficulty/boundary_precision_check/score_boundary_min_score_inclusive_vs_below
        """
        create_active_model(model_code="ADU-B-6A")
        bank = create_partner(legal_name="Boundary Bank")
        attach_active_credit_box(bank["id"], min_score=300, max_score=1000)

        # bureau 575 -> score exactly 300, equal to the box's min_score.
        applicant = create_applicant(full_name="Edge Ed")
        app = submit_application(applicant["id"])
        assert app["risk_score"] == 300
        app = pass_all_instant_checks(app["id"])

        decision = validate_success(api.allocate_application(app["id"], platform_admin_headers))
        assert decision["channel"] == "PARTNER_RETAINED"
        assert decision["chosen_partner_id"] == bank["id"]
        app = get_success_data(api.get_application(app["id"], platform_admin_headers))
        assert app["status"] == "APPROVED"

    def test_score_one_below_min_score_rejected_and_unallocated(
        self, api, platform_admin_headers
    ):
        """PRD 3.9: "the application's `risk_score` lies within the box's inclusive band from `min_score` to `max_score`"
        PRD 3.9: "When no candidate in any channel is eligible, the decision records channel `UNALLOCATED` with the full rejection trail and the application moves to `DECLINED`."

        Design: Difficulty/boundary_precision_check/score_boundary_min_score_inclusive_vs_below
        """
        create_active_model(model_code="ADU-B-6B")
        bank = create_partner(legal_name="Boundary Bank Below")
        attach_active_credit_box(bank["id"], min_score=301, max_score=1000)

        # bureau 575 -> score exactly 300, one below the box's min_score of
        # 301 (a score below 300 would take the PRD 3.4 floor-reject branch at
        # submission and never reach allocation).
        applicant = create_applicant(full_name="Below Beth")
        app = submit_application(applicant["id"])
        assert app["risk_score"] == 300
        app = pass_all_instant_checks(app["id"])

        decision = validate_success(api.allocate_application(app["id"], platform_admin_headers))
        assert decision["channel"] == "UNALLOCATED"
        assert "SCORE_BELOW_BOX" in decision["reason_codes"]
        app = get_success_data(api.get_application(app["id"], platform_admin_headers))
        assert app["status"] == "DECLINED"


class TestPoolCapacityBoundary:

    def test_exact_fit_fills_pool_and_next_loan_overflows(
        self, api, platform_admin_headers, partner_admin_headers
    ):
        """PRD 3.9: "A pool is eligible when the loan's `principal_cents` does not exceed the pool's `max_single_loan_cents` - recorded as `POOL_SINGLE_LOAN_EXCEEDED` when it does - and when the pool's `allocated_principal_cents` plus the loan's principal does not exceed the pool's `target_principal_cents` - recorded as `POOL_CAPACITY_EXCEEDED` when it does."

        Design: Difficulty/boundary_precision_check/pool_capacity_exact_fit_vs_one_cent_over
        """
        create_active_model(model_code="ADU-B-7")
        trust = create_partner(
            legal_name="Exact Fit Trust", partner_type="SECURITIZATION_TRUST", home_state="DE"
        )
        resp = api.create_securitization_pool(
            create_securitization_pool_payload(
                trust["id"], pool_label="TR-FIT",
                target_principal_cents=5000000, max_single_loan_cents=10000000,
            ),
            partner_admin_headers,
        )
        pool = validate_success(resp, expected_status=201)

        app1 = pass_all_instant_checks(
            submit_application(create_applicant(full_name="Fit Fran")["id"])["id"]
        )
        app2 = pass_all_instant_checks(
            submit_application(create_applicant(full_name="Overflow Ollie")["id"])["id"]
        )

        decision1 = validate_success(api.allocate_application(app1["id"], platform_admin_headers))
        assert decision1["channel"] == "SECURITIZATION"
        pool = get_success_data(api.get_securitization_pool(pool["id"], partner_admin_headers))
        assert pool["allocated_principal_cents"] == 5000000
        assert pool["allocated_principal_cents"] == pool["target_principal_cents"]

        decision2 = validate_success(api.allocate_application(app2["id"], platform_admin_headers))
        assert decision2["channel"] == "UNALLOCATED"
        assert "POOL_CAPACITY_EXCEEDED" in decision2["reason_codes"]

        app1 = get_success_data(api.get_application(app1["id"], platform_admin_headers))
        app2 = get_success_data(api.get_application(app2["id"], platform_admin_headers))
        assert app1["status"] == "APPROVED"
        assert app2["status"] == "DECLINED"

    def test_loan_above_single_loan_max_rejected_with_single_loan_code(
        self, api, platform_admin_headers, partner_admin_headers
    ):
        """PRD 3.9: "A pool is eligible when the loan's `principal_cents` does not exceed the pool's `max_single_loan_cents` - recorded as `POOL_SINGLE_LOAN_EXCEEDED` when it does"

        Design: Difficulty/boundary_precision_check/pool_capacity_exact_fit_vs_one_cent_over
        """
        create_active_model(model_code="ADU-B-7B")
        trust = create_partner(
            legal_name="Single Loan Trust", partner_type="SECURITIZATION_TRUST", home_state="DE"
        )
        resp = api.create_securitization_pool(
            create_securitization_pool_payload(
                trust["id"], pool_label="TR-SINGLE",
                target_principal_cents=100000000, max_single_loan_cents=4000000,
            ),
            partner_admin_headers,
        )
        validate_success(resp, expected_status=201)

        # Approved 5000000 exceeds the pool's max_single_loan_cents 4000000.
        app = pass_all_instant_checks(
            submit_application(create_applicant(full_name="Too Big Tessa")["id"])["id"]
        )
        assert app["approved_amount_cents"] == 5000000
        decision = validate_success(api.allocate_application(app["id"], platform_admin_headers))
        assert decision["channel"] == "UNALLOCATED"
        assert "POOL_SINGLE_LOAN_EXCEEDED" in decision["reason_codes"]


class TestVolumeCapWindow:

    def test_volume_cap_rejects_within_month_and_resets_next_month(
        self, api, platform_admin_headers, partner_admin_headers
    ):
        """PRD 3.3: "The platform also tracks each partner's `originated_this_month_count`, the number of loans the partner holds through the `PARTNER_RETAINED` or `REFERRAL_RETAINED` channels whose funding month equals the logical clock's current calendar month"
        PRD 3.9: "the partner's `originated_this_month_count` is still below the box's `monthly_volume_cap_count`"

        Design: Difficulty/resource_temporal_overlap/volume_cap_counts_per_calendar_month_window
        """
        validate_success(
            api.set_clock({"to_iso8601": "2026-09-15T00:00:00Z"}, platform_admin_headers)
        )
        create_active_model(model_code="ADU-B-9")
        bank = create_partner(legal_name="Cap Bank")
        attach_active_credit_box(bank["id"], monthly_volume_cap_count=1)

        apps = []
        for name in ("September Sam", "September Sid", "October Opal"):
            applicant = create_applicant(full_name=name)
            app = pass_all_instant_checks(submit_application(applicant["id"])["id"])
            apps.append(app)

        # First September allocation fits under the cap.
        decision1 = validate_success(api.allocate_application(apps[0]["id"], platform_admin_headers))
        assert decision1["channel"] == "PARTNER_RETAINED"

        # Second September allocation exceeds the monthly cap.
        decision2 = validate_success(api.allocate_application(apps[1]["id"], platform_admin_headers))
        assert decision2["channel"] == "UNALLOCATED"
        assert "VOLUME_CAP_REACHED" in decision2["reason_codes"]
        app2 = get_success_data(api.get_application(apps[1]["id"], platform_admin_headers))
        assert app2["status"] == "DECLINED"

        # After the clock crosses into October the count resets.
        validate_success(
            api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, platform_admin_headers)
        )
        decision3 = validate_success(api.allocate_application(apps[2]["id"], platform_admin_headers))
        assert decision3["channel"] == "PARTNER_RETAINED"

        partner = get_success_data(api.get_partner(bank["id"], partner_admin_headers))
        assert partner["originated_this_month_count"] == 1

    def test_second_same_month_allocation_declines_and_records_cap_reason(
        self, api, platform_admin_headers
    ):
        """PRD 3.9: "the partner's `originated_this_month_count` is still below the box's `monthly_volume_cap_count`"
        PRD 3.9: "When no candidate in any channel is eligible, the decision records channel `UNALLOCATED` with the full rejection trail and the application moves to `DECLINED`."

        Design: Difficulty/resource_temporal_overlap/volume_cap_counts_per_calendar_month_window
        """
        create_active_model(model_code="ADU-B-9B")
        bank = create_partner(legal_name="Cap Bank Two")
        attach_active_credit_box(bank["id"], monthly_volume_cap_count=1)

        app1 = pass_all_instant_checks(
            submit_application(create_applicant(full_name="One Ollie")["id"])["id"]
        )
        app2 = pass_all_instant_checks(
            submit_application(create_applicant(full_name="Two Tina")["id"])["id"]
        )

        decision1 = validate_success(api.allocate_application(app1["id"], platform_admin_headers))
        assert decision1["channel"] == "PARTNER_RETAINED"
        decision2 = validate_success(api.allocate_application(app2["id"], platform_admin_headers))
        assert decision2["channel"] == "UNALLOCATED"
        assert "VOLUME_CAP_REACHED" in decision2["reason_codes"]
        app2 = get_success_data(api.get_application(app2["id"], platform_admin_headers))
        assert app2["status"] == "DECLINED"


class TestSuspendedPartnerExclusion:

    def test_suspension_excludes_box_from_allocation_without_state_change(
        self, api, platform_admin_headers, partner_admin_headers
    ):
        """PRD 3.3: "suspension takes effect immediately for allocation purposes - the partner's active credit box is excluded from eligibility while the partner is `SUSPENDED`, without any state change to the box itself."
        PRD 3.9: "Rejection reasons are recorded in the order the checks first fail: `PARTNER_INACTIVE`, `NO_ACTIVE_CREDIT_BOX`, `STATE_NOT_ALLOWED`, `SCORE_BELOW_BOX`, `SCORE_ABOVE_BOX`, `AMOUNT_BELOW_BOX`, `AMOUNT_ABOVE_BOX`, then `VOLUME_CAP_REACHED`."

        Design: Corner/cross_cutting_layers/suspended_partner_box_excluded_from_allocation
        """
        create_active_model(model_code="ADU-X-2")
        bank = create_partner(legal_name="Susp Bank")
        box_b = attach_active_credit_box(bank["id"], allowed_states=["TX"])
        buyer = create_partner(
            legal_name="Susp Buyer", partner_type="LOAN_BUYER", home_state="DE"
        )
        attach_active_credit_box(buyer["id"], allowed_states=["TX"])

        applicant = create_applicant(full_name="Susp Sue")
        app = pass_all_instant_checks(submit_application(applicant["id"])["id"])

        validate_success(api.suspend_partner(bank["id"], partner_admin_headers))

        decision = validate_success(api.allocate_application(app["id"], platform_admin_headers))
        assert decision["channel"] == "WHOLE_LOAN_SALE"
        assert decision["chosen_partner_id"] == buyer["id"]
        assert "PARTNER_INACTIVE" in decision["reason_codes"]

        box_b = get_success_data(api.get_credit_box(box_b["id"], partner_admin_headers))
        assert box_b["status"] == "ACTIVE", "suspension must not touch the box's own state"


class TestAllocationCascade:

    def test_allocation_into_pool_cascades_loan_pool_and_partner_balances(
        self, api, platform_admin_headers, partner_admin_headers, auditor_headers
    ):
        """PRD 3.9: "Placement into a pool names the pool's `trust_partner_id` as holder and immediately adds the loan's principal to the pool's `allocated_principal_cents`."
        PRD 3.9: "When a holder is chosen, the application moves from `UNDERWRITTEN` to `APPROVED` and a `Loan` is created"
        PRD 3.3: "the partner's `funded_balance_cents` - the sum of `principal_cents` across all loans the partner currently holds in `CURRENT`, `DELINQUENT`, or `CHARGED_OFF` status"

        Design: Difficulty/transitive_cascade/allocation_cascades_application_to_loan_to_pool_balance
        """
        create_active_model(model_code="ADU-B-5")
        trust = create_partner(
            legal_name="Pool Trust", partner_type="SECURITIZATION_TRUST", home_state="DE"
        )
        resp = api.create_securitization_pool(
            create_securitization_pool_payload(trust["id"], pool_label="TR-2026-B"),
            partner_admin_headers,
        )
        pool = validate_success(resp, expected_status=201)

        applicant = create_applicant(full_name="Pool Paula")
        app = pass_all_instant_checks(submit_application(applicant["id"])["id"])

        decision = validate_success(api.allocate_application(app["id"], platform_admin_headers))
        assert decision["channel"] == "SECURITIZATION"
        assert decision["chosen_partner_id"] == trust["id"]

        app = get_success_data(api.get_application(app["id"], platform_admin_headers))
        assert app["status"] == "APPROVED"

        data, meta = validate_paginated(
            api.list_loans(auditor_headers, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 1
        loan = data[0]
        assert loan["holder_partner_id"] == trust["id"]
        assert loan["allocation_channel"] == "SECURITIZATION"
        assert loan["principal_cents"] == 5000000
        # The default logical clock starts on 2026-09-01, so the loan enters
        # CURRENT immediately at funding (PRD 3.10 first-of-month rule).
        assert loan["status"] == "CURRENT"

        pool = get_success_data(api.get_securitization_pool(pool["id"], partner_admin_headers))
        assert pool["allocated_principal_cents"] == 5000000

        trust = get_success_data(api.get_partner(trust["id"], partner_admin_headers))
        assert trust["funded_balance_cents"] == 5000000
        # PRD 3.3: originated_this_month_count covers only loans held through
        # the PARTNER_RETAINED or REFERRAL_RETAINED channels, so a
        # SECURITIZATION placement does not move the trust's counter.
        assert trust["originated_this_month_count"] == 0

    def test_retained_allocation_creates_loan_and_bumps_partner_counters(
        self, api, platform_admin_headers, partner_admin_headers, auditor_headers
    ):
        """PRD 3.9: "When a holder is chosen, the application moves from `UNDERWRITTEN` to `APPROVED` and a `Loan` is created: its `application_id` points back to the source, `holder_partner_id` and `allocation_channel` come from the decision, `principal_cents` copies the approved principal, `apr` copies the allocating credit box's rate, and `term_months` is fixed at thirty-six."

        Design: Difficulty/transitive_cascade/allocation_cascades_application_to_loan_to_pool_balance
        """
        from test_helpers import setup_funded_loan

        bundle = setup_funded_loan()
        loan = bundle["loan"]
        partner = bundle["partner"]

        assert loan["application_id"] == bundle["application"]["id"]
        assert loan["holder_partner_id"] == partner["id"]
        assert loan["allocation_channel"] == "PARTNER_RETAINED"
        assert loan["principal_cents"] == 5000000
        assert loan["apr"] == 12.0
        assert loan["term_months"] == 36
        # Funded on the first of the month: CURRENT immediately (PRD 3.10).
        assert loan["status"] == "CURRENT"

        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        assert partner["funded_balance_cents"] == 5000000
        assert partner["originated_this_month_count"] == 1


class TestImmediateConsistency:

    def test_allocation_effects_visible_in_same_response_and_immediate_reads(
        self, api, platform_admin_headers, partner_admin_headers, auditor_headers
    ):
        """PRD 3.9: "When a holder is chosen, the application moves from `UNDERWRITTEN` to `APPROVED` and a `Loan` is created"
        PRD 3.9: "Every evaluation - each rejection and the final choice - is recorded on an `AllocationDecision` row with the ordered `candidate_partner_ids` as evaluated, the `chosen_partner_id` (null when unallocated), the resulting `channel`, the ordered machine `reason_codes` explaining each rejection or the final choice, and the logical-clock `decided_at` instant."

        Design: Corner/consistency_model/allocation_effects_visible_in_same_response_and_immediate_reads
        """
        create_active_model(model_code="ADU-Y-1")
        bank = create_partner(legal_name="Imm Bank")
        attach_active_credit_box(bank["id"])
        applicant = create_applicant(full_name="Imm Ian")
        app = pass_all_instant_checks(submit_application(applicant["id"])["id"])

        decision = validate_success(api.allocate_application(app["id"], platform_admin_headers))
        assert decision["channel"] == "PARTNER_RETAINED"
        assert decision["chosen_partner_id"] == bank["id"]

        app = get_success_data(api.get_application(app["id"], platform_admin_headers))
        assert app["status"] == "APPROVED"

        data, meta = validate_paginated(
            api.list_loans(auditor_headers, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 1
        # Funded on the first of the month: CURRENT immediately (PRD 3.10).
        assert data[0]["status"] == "CURRENT"
        assert data[0]["holder_partner_id"] == bank["id"]

        partner = get_success_data(api.get_partner(bank["id"], partner_admin_headers))
        assert partner["funded_balance_cents"] == 5000000
        assert partner["originated_this_month_count"] == 1
