"""Two conserved quantities, each restored in its split by a compensating write."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bank_ledger_identity,
    assert_error_envelope,
    assert_same_instant,
    assert_take_ledger_identity,
    assert_unpaginated_list,
)
from test_helpers.factories import adjudication_payload, plan_decision_payload
from test_helpers.fixtures import (
    ADJUDICATOR,
    APPROVER,
    add_commitment,
    adjudicate_report,
    build_scenario,
    file_monitoring_report,
    read_action,
    read_bank,
    read_consultation,
    read_permit,
    read_plan,
    read_proponent,
    setup_suspension_at_trigger_clock,
)


def _return_for_revision(api, plan_id):
    return get_success_data(
        api.decide_plan(
            plan_id, plan_decision_payload("RETURN_FOR_REVISION"), APPROVER
        ),
        200,
    )


class TestBankCreditIdentityRestoredByReturnForRevision:
    """The undo must return credits to available, not park them in transferred."""

    def test_the_split_is_restored_and_not_merely_the_total(self, api):
        """59.72 credits go back to available rather than to transferred.

        PRD: "On a conservation bank, `credits_available` plus `credits_reserved` plus
        `credits_transferred` always equals `credits_total_minted`; `credits_total_minted`
        itself never changes after the bank is established."
        PRD: "Every commitment in `RESERVED` moves `RESERVED - RELEASED` in `created_at`
        ascending order, and for each released commitment whose `mechanism` is
        `CONSERVATION_BANK_CREDIT` the bank's `credits_reserved` decreases by `units`
        while its `credits_available` increases by the same `units` - the bank ledger
        returns to its exact pre-commitment split, not merely to a consistent total."

        Design: Difficulty/compensating_invariant/bank_credit_ledger_identity_restored_by_return_for_revision
        """
        scenario = build_scenario("submitted")
        before = read_bank(scenario["bank"]["id"])
        assert before["credits_total_minted"] == 500.00
        assert before["credits_available"] == 440.28
        assert before["credits_reserved"] == 59.72
        assert before["credits_transferred"] == 0.00
        assert scenario["plan"]["final_mitigation_units"] == 59.70
        assert scenario["plan"]["secured_mitigation_units"] == 59.72
        assert scenario["plan"]["funding_status"] == "FULLY_ASSURED"

        plan = _return_for_revision(api, scenario["plan"]["id"])
        assert plan["plan_status"] == "DRAFT"

        after = read_bank(scenario["bank"]["id"])
        assert after["credits_available"] == 500.00
        assert after["credits_reserved"] == 0.00
        assert after["credits_transferred"] == 0.00
        assert after["credits_total_minted"] == 500.00
        assert_bank_ledger_identity(after)

    def test_both_commitments_are_released_in_created_at_order(self, api):
        """The compensation touches every reserved commitment on the plan.

        PRD: "Every commitment in `RESERVED` moves `RESERVED - RELEASED` in `created_at`
        ascending order"

        Design: Difficulty/compensating_invariant/bank_credit_ledger_identity_restored_by_return_for_revision
        """
        scenario = build_scenario("submitted")
        _return_for_revision(api, scenario["plan"]["id"])

        commitments = assert_unpaginated_list(
            api.list_plan_mitigation_commitments(
                scenario["plan"]["id"], scenario["proponent_headers"]
            )
        )
        assert [row["status"] for row in commitments] == ["RELEASED", "RELEASED"]
        assert [row["units"] for row in commitments] == [45.01, 14.71]
        assert [row["created_at"] for row in commitments] == sorted(
            row["created_at"] for row in commitments
        )

    def test_the_plan_aggregates_recompute_over_an_empty_contributing_set(self, api):
        """Releasing every commitment empties the endowment requirement.

        PRD: "Because `RELEASED` commitments never contribute, `endowment_base_cents`,
        `changed_circumstance_reserve_cents`, and `endowment_required_cents` all recompute
        to 0 over the now-empty contributing set, `funded_ratio` becomes 0.0000, and
        `funding_status` becomes `UNFUNDED`"
        PRD: "When `endowment_required_cents` is 0, `funded_ratio` is pinned to 0.0000 and
        `funding_status` is pinned to `UNFUNDED` - deliberately not `FULLY_ASSURED`, so
        that a returned-for-revision plan with an empty commitment set cannot be approved
        on a technicality."

        Design: Difficulty/compensating_invariant/bank_credit_ledger_identity_restored_by_return_for_revision
        """
        scenario = build_scenario("submitted")
        plan = _return_for_revision(api, scenario["plan"]["id"])

        assert plan["endowment_base_cents"] == 0
        assert plan["changed_circumstance_reserve_cents"] == 0
        assert plan["endowment_required_cents"] == 0
        assert plan["reserve_remaining_cents"] == 0
        assert plan["funded_ratio"] == 0.0000
        assert plan["funding_status"] == "UNFUNDED"

    def test_the_money_already_accepted_stays_on_the_books(self, api):
        """The contribution ledger is not reversed by the revision.

        PRD: "Each accepted contribution **adds** `contribution_cents` to
        `endowment_secured_cents`, which is the running sum of every accepted
        funding-assurance contribution plus every changed-circumstance response
        contribution, and then re-derives the funding dimension."

        Design: Difficulty/compensating_invariant/bank_credit_ledger_identity_restored_by_return_for_revision
        """
        scenario = build_scenario("submitted")
        assert scenario["plan"]["endowment_secured_cents"] == 5_026_514

        plan = _return_for_revision(api, scenario["plan"]["id"])

        assert plan["endowment_secured_cents"] == 5_026_514
        assert plan["endowment_required_cents"] == 0
        assert plan["funded_ratio"] == 0.0000

    def test_re_booking_finds_no_hidden_reservation(self, api):
        """A fresh commitment draws against the fully restored available balance.

        PRD: "For a `CONSERVATION_BANK_CREDIT` commitment, the bank's `credits_available`
        decreases by `units` and its `credits_reserved` increases by the same `units`,
        which moves credits across the ledger without changing the total."

        Design: Difficulty/compensating_invariant/bank_credit_ledger_identity_restored_by_return_for_revision
        """
        scenario = build_scenario("submitted")
        _return_for_revision(api, scenario["plan"]["id"])

        commitment = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 45.01,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )
        assert commitment["status"] == "RESERVED"

        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_available"] == 454.99
        assert bank["credits_reserved"] == 45.01
        assert bank["credits_transferred"] == 0.00
        assert_bank_ledger_identity(bank)

    def test_a_returned_plan_admits_no_second_decision(self, api):
        """The decision endpoint is closed once the plan is back in DRAFT.

        PRD: "A decision is available only while `plan_status` is `SUBMITTED`."

        Design: Difficulty/compensating_invariant/bank_credit_ledger_identity_restored_by_return_for_revision
        """
        scenario = build_scenario("submitted")
        plan = _return_for_revision(api, scenario["plan"]["id"])
        assert plan["plan_status"] == "DRAFT"

        response = api.decide_plan(
            plan["id"], plan_decision_payload("APPROVE"), APPROVER
        )

        assert_error_envelope(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        assert read_plan(plan["id"])["plan_status"] == "DRAFT"


class TestPermitTakeIdentityRestoredByReportRejection:
    """A partial compensation: the ledger unwinds, the obligation does not."""

    def test_the_take_identity_is_restored_without_drift(self, api):
        """Rejection returns the ledger to 0.00 consumed and 4.00 remaining.

        PRD: "On an incidental take permit, `authorized_take_units` always equals
        `take_consumed_units` plus `take_remaining_units`."
        PRD: "`REJECT` moves the report `SUBMITTED - REJECTED` and is a full compensation:
        the permit's `take_consumed_units` decreases by that report's
        `take_units_reported` and `take_remaining_units` is restored by the same amount,
        both rounded half up to two decimal places"

        Design: Difficulty/compensating_invariant/permit_take_ledger_identity_restored_by_report_rejection
        """
        scenario = setup_suspension_at_trigger_clock()
        permit = scenario["permit"]
        assert permit["status"] == "SUSPENDED"
        assert permit["take_consumed_units"] == 3.60
        assert permit["take_remaining_units"] == 0.40
        assert permit["suspension_count"] == 1
        assert scenario["r1"]["is_late"] is False

        report = get_success_data(
            api.adjudicate_monitoring_report(
                scenario["r1"]["id"],
                adjudication_payload(
                    "REJECT",
                    adjudication_note="Survey methodology does not support the take.",
                ),
                ADJUDICATOR,
            ),
            200,
        )

        assert report["status"] == "REJECTED"
        assert_same_instant(
            report["adjudicated_at"], "2027-02-14T00:00:00Z", "adjudicated_at"
        )
        assert report["adjudicated_by_user_id"] == "fws-user-adjudicator"

        after = read_permit(permit["id"])
        assert after["authorized_take_units"] == 4.00
        assert after["take_consumed_units"] == 0.00
        assert after["take_remaining_units"] == 4.00
        assert_take_ledger_identity(after)

    def test_the_suspension_unwinds_but_the_audit_counter_does_not(self, api):
        """The permit reopens while `suspension_count` stays at 1.

        PRD: "If the reversal brings `take_consumed_units` **strictly below**
        `reinitiation_trigger_units` while the permit is `SUSPENDED`, the cascade unwinds:
        the permit moves `SUSPENDED - ACTIVE` and the plan moves
        `SUSPENDED_IMPLEMENTATION - IMPLEMENTING` with `assurance_review_required` set
        back to false."

        Design: Difficulty/compensating_invariant/permit_take_ledger_identity_restored_by_report_rejection
        """
        scenario = setup_suspension_at_trigger_clock()
        adjudicate_report(scenario["r1"]["id"], "REJECT")

        permit = read_permit(scenario["permit"]["id"])
        assert permit["status"] == "ACTIVE"
        assert permit["suspension_count"] == 1

        plan = read_plan(scenario["plan"]["id"])
        assert plan["plan_status"] == "IMPLEMENTING"
        assert plan["assurance_review_required"] is False

    def test_the_reinitiation_obligation_survives_the_rejection(self, api):
        """Hops four and five of the cascade are deliberately not undone.

        PRD: "Hop four moves the action `PERMITTED - REINITIATION_PENDING` with
        `reinitiation_reason` set to `TAKE_EXCEEDANCE`."
        PRD: "it moves `OPINION_ISSUED - REINITIATION_REQUIRED`, stamping
        `reinitiation_triggered_at` and increasing `reinitiation_count` by 1"

        Design: Difficulty/compensating_invariant/permit_take_ledger_identity_restored_by_report_rejection
        """
        scenario = setup_suspension_at_trigger_clock()
        adjudicate_report(scenario["r1"]["id"], "REJECT")

        action = read_action(scenario["action"]["id"])
        assert action["status"] == "REINITIATION_PENDING"
        assert action["reinitiation_reason"] == "TAKE_EXCEEDANCE"

        consultation = read_consultation(scenario["consultation"]["id"])
        assert consultation["status"] == "REINITIATION_REQUIRED"
        assert consultation["reinitiation_count"] == 1

    def test_the_compliance_score_carries_both_surviving_penalties(self, api):
        """A rejected report of weight 11 and an open reinitiation of weight 18.

        PRD: "A monitoring report that reached `REJECTED` contributes a weight of 11,
        dated at the report's `adjudicated_at`."
        PRD: "Each of the proponent's consultations currently sitting in
        `REINITIATION_REQUIRED` contributes a weight of 18, dated at that consultation's
        `reinitiation_triggered_at`."
        PRD: "The finished score is 100 minus the summed penalty, rounded half up to two
        decimal places, and then floored at 0"

        Design: Difficulty/compensating_invariant/permit_take_ledger_identity_restored_by_report_rejection
        """
        scenario = setup_suspension_at_trigger_clock()
        adjudicate_report(scenario["r1"]["id"], "REJECT")

        proponent = read_proponent(scenario["proponent"]["id"])

        assert proponent["open_reinitiation_count"] == 1
        assert proponent["compliance_variant_applied"] == "ROLLING_12_MONTH"
        assert proponent["compliance_standing_score"] == 71.00

    def test_the_rejected_interval_can_be_refiled(self, api):
        """The same half-open period is reusable once its report is rejected.

        PRD: "`REJECTED` reports free their interval and never participate in this
        check."

        Design: Difficulty/compensating_invariant/permit_take_ledger_identity_restored_by_report_rejection
        """
        scenario = setup_suspension_at_trigger_clock()
        adjudicate_report(scenario["r1"]["id"], "REJECT")

        replacement = file_monitoring_report(
            scenario["permit"]["id"],
            scenario["proponent"],
            period_start="2026-10-01",
            period_end="2026-12-31",
            take_units_reported=1.00,
            mitigation_units_verified=59.72,
        )
        assert replacement["status"] == "SUBMITTED"

        permit = read_permit(scenario["permit"]["id"])
        assert permit["take_consumed_units"] == 1.00
        assert permit["take_remaining_units"] == 3.00
        assert_take_ledger_identity(permit)

    def test_the_reversal_cannot_be_applied_twice(self, api):
        """A REJECTED report is terminal, so a second adjudication is refused.

        PRD: "It is available only while the report's `status` is `SUBMITTED`, so
        re-adjudicating an already-adjudicated report is `ERR_INVALID_STATE_TRANSITION`
        (HTTP 409)"

        Design: Difficulty/compensating_invariant/permit_take_ledger_identity_restored_by_report_rejection
        """
        scenario = setup_suspension_at_trigger_clock()
        adjudicate_report(scenario["r1"]["id"], "REJECT")

        response = api.adjudicate_monitoring_report(
            scenario["r1"]["id"], adjudication_payload("REJECT"), ADJUDICATOR
        )

        assert_error_envelope(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        assert read_permit(scenario["permit"]["id"])["take_consumed_units"] == 0.00
