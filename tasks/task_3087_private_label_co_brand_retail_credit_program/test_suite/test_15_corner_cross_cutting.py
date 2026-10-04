"""Corner coverage for cross-cutting concerns: optimistic concurrency, dispute
fan-out, derived-field reconciliation, selector policy and immediate
consistency.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    onboard_partner,
    draft_agreement,
    open_negotiation,
    setup_negotiation_agreement,
    setup_active_agreement,
    setup_program,
    setup_program_with_account,
    setup_program_with_two_promo_plans,
    setup_closed_program,
    issue_program,
    issue_account,
    post_purchase,
    post_promo_purchase,
    apply_principal,
    pay_account,
    program_summary,
    open_settlement_batch,
    roll_into_winding_down,
    make_cardholder_headers,
)

SERVICE = TEST_USERS["cardholder_service_headers"]


class TestOptimisticConcurrency:

    def test_agreement_execute_rejects_a_stale_expected_version(self, api, admin_headers):
        """PRD §2.8: "The first is the execution of a negotiated program
        agreement, which must carry `expected_agreement_version`; if that value
        does not match the agreement's current `version`, the execution is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/occ_agreement_execute_rejects_stale_version
        """
        partner = onboard_partner(api)
        agreement, neg_version = setup_negotiation_agreement(api, partner["id"])
        resp = api.execute_agreement(agreement["id"], neg_version - 1, admin_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        refreshed = validate_success(api.get_agreement(agreement["id"], admin_headers), 200)
        assert refreshed["agreement_status"] == "NEGOTIATION"
        assert refreshed["version"] == neg_version

    def test_agreement_execute_advances_the_version_on_success(self, api, admin_headers):
        """PRD §3.1: "on success the agreement becomes `ACTIVE` and its `version`
        increments by one." PRD §2.8: "the check exists precisely so that a client
        which has not observed the entity's latest state cannot overwrite it."

        Design: Corner/cross_cutting/occ_agreement_execute_advances_version_on_success
        """
        partner = onboard_partner(api)
        agreement, neg_version = setup_negotiation_agreement(api, partner["id"])
        executed = validate_success(
            api.execute_agreement(agreement["id"], neg_version, admin_headers), 200
        )
        assert executed["agreement_status"] == "ACTIVE"
        assert executed["version"] == neg_version + 1


class TestDisputeFanOut:

    def test_cardholder_resolution_hits_the_transaction_plan_and_program(self, api, admin_headers):
        """PRD §3.8: "On that branch the case records `chargeback_amount_cents`
        equal to the disputed purchase's `amount_cents`, and the case becomes
        `RESOLVED_FAVOR_CARDHOLDER`." PRD §3.8: "its promotional plan keeps a
        `subsidy_at_risk_cents` of zero rather than being recomputed."

        Design: Corner/cross_cutting/cascade_dispute_fan_out_charges_back_the_transaction_set
        """
        _partner, _agreement, program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        plans, _meta = validate_paginated(
            api.list_promo_plans(admin_headers, {"transaction_id": transaction["id"]})
        )
        plan_id = plans[0]["id"]

        dispute = get_success_data(
            api.create_dispute({"transaction_id": transaction["id"],
                                "account_id": account["id"], "dispute_reason": "FRAUD"}, SERVICE)
        )
        get_success_data(api.review_dispute(dispute["id"], SERVICE))
        resolved = validate_success(api.resolve_dispute(dispute["id"], "CARDHOLDER", SERVICE), 200)

        assert resolved["chargeback_amount_cents"] == 120000
        tx = validate_success(api.get_transaction(transaction["id"], admin_headers), 200)
        assert tx["transaction_status"] == "POSTED"
        plan = validate_success(api.get_promo_plan(plan_id, admin_headers), 200)
        assert plan["subsidy_at_risk_cents"] == 0
        assert program_summary(api, program["id"])["free_look_exposure_cents"] == 0


class TestDerivedFieldReconciliation:

    def test_program_receivable_tracks_the_sum_of_balance_rows(self, api, admin_headers):
        """PRD §3.5: "Recording a slice recomputes the account's
        `outstanding_balance_cents` as the sum of its `principal_balance_cents`
        rows." PRD §3.2: "`outstanding_receivable_cents` is the sum of
        `outstanding_balance_cents` across every account on the program".

        Design: Corner/cross_cutting/derived_field_program_receivable_recomputes_on_balance_rows
        """
        _partner, _agreement, program, account = setup_program_with_account(api)
        apply_principal(api, account["id"], 100000)
        apply_principal(api, account["id"], 50000)  # second slice; no purchase, so no credit check

        refreshed = validate_success(api.get_account(account["id"], admin_headers), 200)
        assert refreshed["outstanding_balance_cents"] == 150000
        assert program_summary(api, program["id"])["outstanding_receivable_cents"] == 150000
        rows, _meta = validate_paginated(api.list_account_balances(account["id"], admin_headers))
        assert len(rows) == 2

    def test_program_exposure_recomputes_on_settlement_as_the_plans_leave_active(
            self, api, admin_headers):
        """PRD §3.4: "And when a plan settles, it leaves the `ACTIVE` exposure
        set and the program's exposure is recomputed." PRD §3.2:
        "`free_look_exposure_cents` is the sum of `subsidy_at_risk_cents` across
        every promotional plan on the program whose `plan_status` is `ACTIVE`."
        PRD §3.7: "the batch becomes `SETTLED`, every in-scope promotional plan
        moves to `SETTLED` with its `net_subsidy_cents` stamped". A settled plan
        is no longer `ACTIVE`, so it drops out of the exposure sum and the
        program's exposure recomputes to zero.

        Design: Corner/cross_cutting/derived_field_program_exposure_recomputes_on_settlement
        """
        _p, agreement, program, account, plan12, plan6 = setup_program_with_two_promo_plans(
            api, credit_limit_cents=500000
        )
        before = program_summary(api, program["id"])
        assert before["free_look_exposure_cents"] == 10432

        batch = open_settlement_batch(api, agreement["id"],
                                      "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
        validate_success(api.finalize_settlement_batch(batch["id"], admin_headers), 200)

        settled12 = validate_success(api.get_promo_plan(plan12["id"], admin_headers), 200)
        settled6 = validate_success(api.get_promo_plan(plan6["id"], admin_headers), 200)
        assert settled12["plan_status"] == "SETTLED"
        assert settled6["plan_status"] == "SETTLED"

        after = program_summary(api, program["id"])
        assert after["free_look_exposure_cents"] == 0, (
            "the settled plans have left the ACTIVE exposure set, so the "
            "program's exposure recomputes to zero"
        )
        assert after["outstanding_receivable_cents"] == 0


class TestSelectorPolicy:

    def test_program_lookup_is_an_explicit_fk_filter(self, api, admin_headers):
        """PRD §3.2: "`partner_id`, an `agreement_id`, and a `cycle_day`" names
        the program's partner foreign key; the filter selects on it exactly.
        PRD §2.3: "`total_count` reports the total number of matching resources
        before pagination is applied".

        Design: Corner/cross_cutting/selector_program_lookup_is_an_explicit_fk_filter
        """
        partner, _agreement, program = setup_program(api)
        other = onboard_partner(api, name="Merrivale Optics", code="MERRIVALE")

        mine, meta = validate_paginated(
            api.list_credit_programs(admin_headers, {"partner_id": partner["id"]})
        )
        assert len(mine) == 1
        assert mine[0]["id"] == program["id"]

        theirs, meta2 = validate_paginated(
            api.list_credit_programs(admin_headers, {"partner_id": other["id"]})
        )
        assert theirs == []
        assert meta2["total_count"] == 0

        unfiltered, meta3 = validate_paginated(api.list_credit_programs(admin_headers))
        assert meta3["total_count"] == 1


class TestImmediateConsistency:

    def test_the_payment_response_carries_the_post_payment_balance(self, api, admin_headers):
        """PRD §3.5: "The payment reduces the account's `principal_balance_cents`
        rows by the payment amount, floored at zero so that no slice goes negative,
        and then recomputes both the account's `outstanding_balance_cents` and the
        program's `program_profitability_cents`."

        Design: Corner/consistency/immediate_payment_balance_visible_in_the_same_response
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        apply_principal(api, account["id"], 100000)

        result = validate_success(
            api.post_payment(account["id"], 40000, make_cardholder_headers(account["id"])), 200
        )
        assert result["outstanding_balance_cents"] == 60000
        assert result["account_status"] == "ACTIVE"

        refreshed = validate_success(api.get_account(account["id"], admin_headers), 200)
        assert refreshed["outstanding_balance_cents"] == 60000

    def test_a_charge_off_cascade_is_visible_on_the_next_read(self, api, admin_headers):
        """PRD §3.5: "The first hop sets the account's `account_status` to
        `CHARGED_OFF`, which is the origin of the chain. The second hop is caused
        by the first: every promotional plan whose `account_id` names this account
        has its `plan_status` set to `EXPIRED`".

        Design: Corner/consistency/immediate_charge_off_and_cascade_visible_on_read
        """
        _partner, _agreement, program, account = setup_program_with_account(
            api, credit_limit_cents=500000
        )
        apply_principal(api, account["id"], 120000)
        get_success_data(api.schedule_payment(account["id"], "2026-09-10T00:00:00Z", admin_headers))
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        plans, _meta = validate_paginated(
            api.list_promo_plans(admin_headers, {"transaction_id": transaction["id"]})
        )
        get_success_data(api.advance_clock(200, admin_headers))

        charged = validate_success(api.charge_off(account["id"], admin_headers), 200)
        assert charged["account_status"] == "CHARGED_OFF"

        plan = validate_success(api.get_promo_plan(plans[0]["id"], admin_headers), 200)
        assert plan["plan_status"] == "EXPIRED"
        assert program_summary(api, program["id"])["outstanding_receivable_cents"] == 0