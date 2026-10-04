"""Difficulty tests: cross-entity state dependencies — COE gating loan creation,
appraisal gating close, payoff gating restoration, deployment gating occupancy."""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    add_standard_service_period,
    approve_underwriting,
    close_loan,
    create_coe_request_payload,
    create_deployment_exception_payload,
    create_loan_payload,
    create_restoration_payload,
    create_south_appraiser,
    create_veteran_payload,
    get_occupancy_certificate,
    order_assigned_appraisal,
    setup_approved_loan,
    setup_closed_loan,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    submit_value_issued_report,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestLoanCreateRequiresIssuedCoe:
    def test_loan_create_requires_issued_coe(self, api):
        """PRD §3.3: "The cited certificate must belong to the path veteran — a
        mismatch is rejected with `ERR_SERVICE_PERIOD_MISMATCH` — and must be
        `ISSUED`, else creation fails with `ERR_COE_NOT_ISSUED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/loan_create_requires_issued_coe
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Gate")),
            expected_status=201,
        )
        add_standard_service_period(veteran["id"])
        coe = validate_success(
            api.create_coe_request(veteran["id"], create_coe_request_payload()),
            expected_status=201,
        )
        assert coe["status"] == "REQUESTED"
        validate_error(
            api.create_loan(
                veteran["id"],
                create_loan_payload(coe["id"], purchase_price_cents=30000000),
            ),
            ApiErrorId.ERR_COE_NOT_ISSUED, expected_status=409,
        )
        validate_success(api.issue_coe(coe["id"]))
        loan = validate_success(
            api.create_loan(
                veteran["id"],
                create_loan_payload(coe["id"], purchase_price_cents=30000000),
            ),
            expected_status=201,
        )
        assert loan["underwriting_status"] == "SUBMITTED"

    def test_loan_create_with_denied_coe_also_rejected(self, api):
        """PRD §3.3: "must be `ISSUED`, else creation fails with
        `ERR_COE_NOT_ISSUED` (HTTP 409)"
        PRD §3.2: "Denial moves a certificate from `REQUESTED` (or, on
        re-adjudication, from `RECONSIDERATION`) to `DENIED`"

        Design: Difficulty/cross_entity_state_dependency/loan_create_requires_issued_coe
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(
                full_name="V GateD", character_of_discharge="DISHONORABLE")),
            expected_status=201,
        )
        add_standard_service_period(veteran["id"])
        coe = validate_success(
            api.create_coe_request(veteran["id"], create_coe_request_payload()),
            expected_status=201,
        )
        denied = validate_success(api.deny_coe(coe["id"]))
        assert denied["status"] == "DENIED"
        validate_error(
            api.create_loan(
                veteran["id"],
                create_loan_payload(coe["id"], purchase_price_cents=30000000),
            ),
            ApiErrorId.ERR_COE_NOT_ISSUED, expected_status=409,
        )


class TestCloseRequiresAppraisalValueIssued:
    def test_close_requires_appraisal_value_issued(self, api):
        """PRD §3.4: "Some appraisal of the loan must have reached `VALUE_ISSUED`
        with an `appraised_value_cents` at least equal to the loan's
        `purchase_price_cents`."
        PRD §2.11: "an action attempted on a resource in a state that does not
        permit it is rejected with `ERR_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/close_requires_appraisal_value_issued
        """
        # Approved loan whose appraisal is ASSIGNED but has no issued value yet.
        ctx = setup_submitted_loan(
            loan_overrides={"purchase_price_cents": 30000000})
        appraiser = create_south_appraiser(name="App S8")
        appraisal = order_assigned_appraisal(ctx["loan"]["id"], appraiser)
        approve_underwriting(ctx["loan"]["id"])

        validate_error_is_one_of(
            api.close_loan(ctx["loan"]["id"], {
                "closing_date": "2026-03-10",
                "first_payment_due_date": "2026-05-01",
            }),
            [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_LOAN_NOT_CLOSABLE],
        )
        submit_value_issued_report(appraisal["id"], appraiser["id"], 30000000)
        closed = validate_success(
            api.close_loan(ctx["loan"]["id"], {
                "closing_date": "2026-03-10",
                "first_payment_due_date": "2026-05-01",
            })
        )
        assert closed["closing_status"] == "CLOSED"

    def test_close_blocked_when_appraisal_value_below_price(self, api):
        """PRD §3.4: "Some appraisal of the loan must have reached `VALUE_ISSUED`
        with an `appraised_value_cents` at least equal to the loan's
        `purchase_price_cents`."

        Design: Difficulty/cross_entity_state_dependency/close_requires_appraisal_value_issued
        """
        ctx = setup_submitted_loan(
            loan_overrides={"purchase_price_cents": 30000000})
        appraiser = create_south_appraiser(name="App Low")
        appraisal = order_assigned_appraisal(ctx["loan"]["id"], appraiser)
        approve_underwriting(ctx["loan"]["id"])
        # Value issued but below the purchase price: close still cannot proceed.
        submit_value_issued_report(appraisal["id"], appraiser["id"], 29999900)
        validate_error_is_one_of(
            api.close_loan(ctx["loan"]["id"], {
                "closing_date": "2026-03-10",
                "first_payment_due_date": "2026-05-01",
            }),
            [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_LOAN_NOT_CLOSABLE],
        )


class TestRestorationRequiresPaidOffLoan:
    def test_restoration_requires_paid_off_loan(self, api):
        """PRD §3.7: "The cited loan must be `PAID_IN_FULL`, else
        `ERR_LOAN_NOT_PAID_OFF` (HTTP 409)."
        PRD §3.7: "On grant, the request's `restored_amount_cents` is set to the
        loan's `entitlement_charged_cents`, the status becomes the terminal
        `GRANTED`"

        Design: Difficulty/cross_entity_state_dependency/restoration_requires_paid_off_loan
        """
        ctx = setup_closed_loan(price_cents=30000000)
        request = validate_success(
            api.create_restoration_request(
                ctx["veteran"]["id"],
                create_restoration_payload(ctx["loan"]["id"],
                                           restoration_type="SALE_PAYOFF"),
            ),
            expected_status=201,
        )
        validate_error(
            api.grant_restoration(request["id"]),
            ApiErrorId.ERR_LOAN_NOT_PAID_OFF, expected_status=409,
        )
        validate_success(api.record_payoff(ctx["loan"]["id"], "SALE"))
        granted = validate_success(api.grant_restoration(request["id"]))
        assert granted["status"] == "GRANTED"
        assert granted["restored_amount_cents"] == 7500000

    def test_restoration_type_must_match_payoff_type(self, api):
        """PRD §3.7: "The restoration type must match the loan's recorded payoff:
        `SALE_PAYOFF` requires the loan's `payoff_type` to be `SALE`, and
        `REFINANCE_PAYOFF` requires `REFINANCE_PAYOFF`."

        Design: Difficulty/cross_entity_state_dependency/restoration_requires_paid_off_loan
        """
        ctx = setup_closed_loan(price_cents=30000000)
        validate_success(api.record_payoff(ctx["loan"]["id"], "SALE"))
        # REFINANCE_PAYOFF request against a SALE payoff: granting it must fail.
        request = validate_success(
            api.create_restoration_request(
                ctx["veteran"]["id"],
                create_restoration_payload(ctx["loan"]["id"],
                                           restoration_type="REFINANCE_PAYOFF"),
            ),
            expected_status=201,
        )
        resp = api.grant_restoration(request["id"])
        assert resp.status_code in (409, 422), (
            f"grant with mismatched payoff type must fail, got {resp.status_code}"
        )


class TestOccupancyExceptedRequiresDeployment:
    def test_occupancy_excepted_requires_deployment_window(self, api):
        """PRD §3.6: "When it falls after the deadline, the outcome depends on
        deployment. If a `DeploymentException` of the loan's veteran exists whose
        half-open window — running from `deployment_start` up to but not
        including `deployment_end` — contains the `move_in_deadline`, the
        certificate becomes `EXCEPTED` with `exception_type` set to `DEPLOYMENT`.
        With no covering deployment window, a late move-in leaves the
        certificate `VIOLATED`"

        Design: Difficulty/cross_entity_state_dependency/occupancy_excepted_requires_deployment_window
        """
        # Veteran A: no deployment window -> late move-in is VIOLATED.
        # Veteran A's loan lives in the WEST region (pool disjoint from
        # SOUTH per PRD §3.5, "active appraisers whose region equals the
        # loan's property_region") so its appraisal can never contend with
        # veteran B's dedicated SOUTH appraiser below.
        ctx_a = setup_veteran_with_issued_coe(
            veteran_overrides={"full_name": "V Occ A"})
        loan_a = validate_success(
            api.create_loan(
                ctx_a["veteran"]["id"],
                create_loan_payload(ctx_a["coe"]["id"],
                                    property_region="WEST",
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        appraiser_a = validate_success(
            api.create_appraiser({"name": "App W1", "region": "WEST"}),
            expected_status=201,
        )
        appraisal_a = order_assigned_appraisal(loan_a["id"], appraiser_a)
        submit_value_issued_report(appraisal_a["id"], appraiser_a["id"], 20000000)
        approve_underwriting(loan_a["id"])
        close_loan(loan_a["id"])
        occ_a = get_occupancy_certificate(loan_a["id"])
        violated = validate_success(
            api.verify_occupancy(occ_a["id"], move_in_date="2026-06-15"))
        assert violated["status"] == "VIOLATED"

        # Veteran B: window [2026-03-01, 2026-09-01) contains 2026-05-09.
        # App S10 is the only SOUTH appraiser, so the selector policy
        # (PRD §3.5) must assign loan B's appraisal to it.
        appraiser = validate_success(
            api.create_appraiser({"name": "App S10", "region": "SOUTH"}),
            expected_status=201,
        )
        vet_b = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Occ B")),
            expected_status=201,
        )
        add_standard_service_period(vet_b["id"], branch="NAVY")
        validate_success(
            api.create_deployment_exception(
                vet_b["id"],
                create_deployment_exception_payload(
                    deployment_start="2026-03-01", deployment_end="2026-09-01",
                    orders_reference="ORD-77"),
            ),
            expected_status=201,
        )
        coe_b = validate_success(
            api.create_coe_request(vet_b["id"], create_coe_request_payload()),
            expected_status=201,
        )
        validate_success(api.issue_coe(coe_b["id"]))
        loan_b = validate_success(
            api.create_loan(
                vet_b["id"],
                create_loan_payload(coe_b["id"], purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        appraisal_b = order_assigned_appraisal(loan_b["id"], appraiser)
        submit_value_issued_report(appraisal_b["id"], appraiser["id"], 20000000)
        approve_underwriting(loan_b["id"])
        close_loan(loan_b["id"])
        occ_b = get_occupancy_certificate(loan_b["id"])
        excepted = validate_success(
            api.verify_occupancy(occ_b["id"], move_in_date="2026-06-15"))
        assert excepted["status"] == "EXCEPTED"
        assert excepted["exception_type"] == "DEPLOYMENT"

    def test_occupancy_late_move_in_without_window_violated(self, api):
        """PRD §3.6: "With no covering deployment window, a late move-in leaves
        the certificate `VIOLATED`, and an audit event records the violation."
        PRD §3.6: "All three of `SATISFIED`, `EXCEPTED`, and `VIOLATED` are
        terminal."

        Design: Difficulty/cross_entity_state_dependency/occupancy_excepted_requires_deployment_window
        """
        ctx = setup_closed_loan(price_cents=20000000)
        occ = get_occupancy_certificate(ctx["loan"]["id"])
        violated = validate_success(
            api.verify_occupancy(occ["id"], move_in_date="2026-06-15"))
        assert violated["status"] == "VIOLATED"
        assert violated["exception_type"] == "NONE"
        events, meta = validate_paginated(
            api.list_audit_events(params={"entity_id": occ["id"]}))
        assert len(events) >= 1
