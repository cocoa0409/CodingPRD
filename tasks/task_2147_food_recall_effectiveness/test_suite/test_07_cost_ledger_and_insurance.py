"""Cost accumulation and the insurance settlement waterfall."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_cost_entry,
    assert_insurance_claim,
    case_with_verified_receipt,
    create_cost_entry_payload,
    draft_case,
    make_adjuster_headers,
    make_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = make_coordinator_headers("coord-1")
ADJUSTER = make_adjuster_headers("adj-1")


def test_legal_and_lab_testing_lines_carry_their_own_rate_and_insurability(api):
    """PRD §3.9: "`insurable` is true for `NOTIFICATION`, `LOGISTICS`, `DESTRUCTION` and `PRODUCT_VALUE`, and false for `LEGAL` and `LAB_TESTING`."
    PRD §3.9: "The `overhead_rate` is 11.5 percent for `NOTIFICATION`, 8.5 percent for `LOGISTICS`, 14.5 percent for `DESTRUCTION`, zero for `LEGAL`, 5.5 percent for `PRODUCT_VALUE` and 22.5 percent for `LAB_TESTING`."
    PRD §3.9: "Every adjudication re-sums the recall's ledger from scratch: `total_loaded_cost_cents` is the sum of `line_loaded_cost_cents` over this recall's lines in `ACCEPTED`, and `insurable_loaded_cost_cents` is that same sum restricted to lines whose `insurable` is true."

    Design: Corner/calculations/legal_and_lab_testing_cost_lines_carry_their_own_overhead_and_insurability
    """
    case = draft_case()
    legal = case.file_cost("LEGAL", 123457, description="Outside counsel")
    lab = case.file_cost("LAB_TESTING", 1000, description="Serotype confirmation")

    assert legal["overhead_rate"] == pytest.approx(0.000)
    assert legal["line_loaded_cost_cents"] == 123457
    assert legal["insurable"] is False
    assert lab["overhead_rate"] == pytest.approx(0.225)
    assert lab["line_loaded_cost_cents"] == 1225
    assert lab["insurable"] is False

    case.adjudicate_cost(legal["id"], "ACCEPT")
    case.adjudicate_cost(lab["id"], "ACCEPT")

    recall = case.read_recall()
    assert recall["total_loaded_cost_cents"] == 124682
    assert recall["insurable_loaded_cost_cents"] == 0

    rows, meta = validate_paginated(
        api.list_cost_entries(case.recall_id, COORDINATOR)
    )
    assert meta["total_count"] == 2
    for row in rows:
        assert_cost_entry(row)
        assert row["status"] == "ACCEPTED"


def test_accepting_an_already_accepted_line_is_an_invalid_cost_entry_state(api):
    """PRD §3.9: "`ACCEPT` is permitted from `PENDING` and from `REJECTED`, moving `PENDING → ACCEPTED` or `REJECTED → ACCEPTED`; `REJECT` is permitted from `PENDING` and from `ACCEPTED`, moving `PENDING → REJECTED` or `ACCEPTED → REJECTED`."
    PRD §3.9: "A decision the line's current `status` does not permit is refused with `ERR_INVALID_COST_ENTRY_STATE`."

    Design: Corner/errors/accepting_an_already_accepted_cost_entry_returns_invalid_cost_entry_state
    """
    case = draft_case()
    entry = case.accepted_cost("LOGISTICS", 100000, description="Freight recovery")
    assert entry["line_loaded_cost_cents"] == 108500

    response = api.adjudicate_cost_entry(
        entry["id"], {"decision": "ACCEPT"}, COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_INVALID_COST_ENTRY_STATE.value)
    assert response.status_code == 409

    rows, _ = validate_paginated(api.list_cost_entries(case.recall_id, COORDINATOR))
    assert rows[0]["status"] == "ACCEPTED"

    recall = case.read_recall()
    assert recall["total_loaded_cost_cents"] == 108500
    assert recall["insurable_loaded_cost_cents"] == 108500


def test_adjudicating_a_draft_claim_is_an_invalid_claim_state(api):
    """PRD §3.9: "Adjudicating a claim that is not `SUBMITTED`, or submitting one that is neither `DRAFT` nor `PARTIALLY_PAID`, is refused with `ERR_INVALID_CLAIM_STATE`."
    PRD §3.9: "An insurance claim starts as a shell: a `FirmRecallOfficer` opens one with nothing but a `claim_reference` from the carrier, and it is created in `status` `DRAFT` with `claimed_cents`, `capped_total_cents`, `coinsurance_rate`, `settlement_payable_cents`, `handling_fee_cents`, `total_claim_value_cents` and `paid_cents` all zero, `supplement_round` 0, and `denial_reason` and `adjudicated_by_user_id` null."

    Design: Corner/errors/adjudicate_a_draft_insurance_claim_returns_invalid_claim_state
    """
    case = draft_case()
    claim = case.open_claim("CLM-2026-0009")
    assert_insurance_claim(claim)
    assert claim["status"] == "DRAFT"

    response = api.adjudicate_insurance_claim(
        claim["id"], {"decision": "PAY_FULL"}, ADJUSTER
    )
    validate_error(response, ApiErrorId.ERR_INVALID_CLAIM_STATE.value)
    assert response.status_code == 409

    rows, _ = validate_paginated(
        api.list_insurance_claims(case.recall_id, COORDINATOR)
    )
    assert rows[0]["status"] == "DRAFT"
    assert rows[0]["paid_cents"] == 0
    firm = validate_success(api.get_firm(case.firm_id, COORDINATOR))
    assert firm["policy_paid_to_date_cents"] == 0


def test_the_cost_ledger_is_visible_immediately_after_adjudication(api):
    """PRD §3.9: "Every adjudication re-sums the recall's ledger from scratch: `total_loaded_cost_cents` is the sum of `line_loaded_cost_cents` over this recall's lines in `ACCEPTED`, and `insurable_loaded_cost_cents` is that same sum restricted to lines whose `insurable` is true."
    PRD §3.9: "Lines in `PENDING` and `REJECTED` contribute nothing, which is exactly why accepting a line and then rejecting it restores both totals to their pre-cycle values."

    Design: Corner/consistency_model/cost_ledger_recomputation_is_visible_immediately_after_adjudication
    """
    case = draft_case()
    entry = case.file_cost("LOGISTICS", 100000, description="Freight recovery")
    assert case.read_recall()["total_loaded_cost_cents"] == 0

    accepted = case.adjudicate_cost(entry["id"], "ACCEPT")
    assert accepted["status"] == "ACCEPTED"

    recall = case.read_recall()
    assert recall["total_loaded_cost_cents"] == 108500
    assert recall["insurable_loaded_cost_cents"] == 108500

    _, meta = validate_paginated(
        api.list_cost_entries(case.recall_id, COORDINATOR, params={"status": "ACCEPTED"})
    )
    assert meta["total_count"] == 1


def test_insurance_adjuster_may_not_file_a_cost_entry(api):
    """PRD §2.1: "If both headers are well formed but the acting role does not appear in the authorized-role list published for the endpoint in §4, the rejection is `ERR_ROLE_NOT_PERMITTED` with HTTP 403."
    PRD §2.1: "An `InsuranceAdjuster` adjudicates submitted claims only, and may neither file a claim, file a cost line, nor adjudicate one."

    Design: Corner/rbac/insurance_adjuster_cannot_file_a_cost_entry
    """
    case = draft_case()

    response = api.create_cost_entry(
        case.recall_id,
        create_cost_entry_payload("LEGAL", 50000, description="Counsel"),
        ADJUSTER,
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert response.status_code == 403

    rows, meta = validate_paginated(api.list_cost_entries(case.recall_id, COORDINATOR))
    assert rows == []
    assert meta["total_count"] == 0


def test_supplement_clamps_to_the_remaining_aggregate_and_then_exhausts_it(api):
    """PRD §3.9: "The firm's remaining policy aggregate — its `policy_aggregate_cents` less its `policy_paid_to_date_cents` — must be strictly greater than zero, and a submission when it is zero or less is refused with `ERR_CLAIM_EXCEEDS_POLICY_AGGREGATE`; note that a merely *small* positive remainder never rejects, it only clamps."
    PRD §3.9: "Step five clamps that figure down to the firm's remaining policy aggregate if the aggregate is smaller."
    PRD §3.9: "A partially paid claim may be resubmitted as a supplement along `PARTIALLY_PAID → SUBMITTED`, which increments `supplement_round` by one and recomputes every settlement field from scratch against the recall's *current* `insurable_loaded_cost_cents` and the firm's *current* remaining aggregate."
    PRD §3.9: "All three stamp `adjudicated_by_user_id`, and both paying branches add the paid amount to the firm's `policy_paid_to_date_cents`."

    Design: Corner/errors/insurance_supplement_clamps_to_remaining_aggregate_then_exhausted_aggregate_rejects
    """
    case = case_with_verified_receipt(
        agency="USDA", quantity_shipped=1000, quantity_returned=960,
        quantity_unrecoverable=40,
        firm_overrides={"policy_deductible_cents": 0, "policy_aggregate_cents": 500000},
    )
    case.accepted_cost("LOGISTICS", 500000, description="Reverse logistics")

    claim_a = case.open_claim("CLM-A")
    first_submission = case.submit_claim(claim_a["id"])
    assert first_submission["coinsurance_rate"] == pytest.approx(0.80)
    assert first_submission["settlement_payable_cents"] == 434000
    assert first_submission["handling_fee_cents"] == 13020
    assert first_submission["total_claim_value_cents"] == 447020

    case.adjudicate_claim(claim_a["id"], "PAY_PARTIAL", paid_cents=400000)

    supplement = case.submit_claim(claim_a["id"])
    assert supplement["settlement_payable_cents"] == 100000
    assert supplement["handling_fee_cents"] == 3000
    assert supplement["total_claim_value_cents"] == 103000
    assert supplement["supplement_round"] == 1

    paid = case.adjudicate_claim(claim_a["id"], "PAY_FULL")
    assert paid["status"] == "PAID"
    assert paid["paid_cents"] == 100000

    firm = validate_success(api.get_firm(case.firm_id, COORDINATOR))
    assert firm["policy_paid_to_date_cents"] == 500000

    claim_b = case.open_claim("CLM-B")
    response = api.submit_insurance_claim(claim_b["id"], case.officer)
    validate_error(response, ApiErrorId.ERR_CLAIM_EXCEEDS_POLICY_AGGREGATE.value)
    assert response.status_code == 422

    rows, _ = validate_paginated(
        api.list_insurance_claims(case.recall_id, COORDINATOR)
    )
    still_draft = [row for row in rows if row["id"] == claim_b["id"]][0]
    assert still_draft["status"] == "DRAFT"
    assert still_draft["settlement_payable_cents"] == 0


class TestPerLineRoundingOrder:
    """Overhead loading is rounded on each line before any line joins a sum."""

    @staticmethod
    def _three_notification_lines():
        case = draft_case()
        case.lines = [
            case.file_cost("NOTIFICATION", 3333, description=f"Certified mail batch {n}")
            for n in (1, 2, 3)
        ]
        return case

    def test_each_notification_line_loads_to_its_own_rounded_cents(self, api):
        """PRD §3.9: "From those, `line_loaded_cost_cents` is the line's `amount_cents` multiplied by one plus its `overhead_rate`, rounded half up to whole cents — and that rounding happens on this single line, before the line ever enters a sum."
        PRD §3.9: "The `overhead_rate` is 11.5 percent for `NOTIFICATION`, 8.5 percent for `LOGISTICS`, 14.5 percent for `DESTRUCTION`, zero for `LEGAL`, 5.5 percent for `PRODUCT_VALUE` and 22.5 percent for `LAB_TESTING`."

        Design: Difficulty/combinatorial_formula/cost_ledger_rounds_each_line_before_summing_mode_b
        """
        case = self._three_notification_lines()
        for line in case.lines:
            assert_cost_entry(line)
            assert line["line_loaded_cost_cents"] == 3716
            assert line["overhead_rate"] == pytest.approx(0.115)
            assert line["insurable"] is True

        last = case.adjudicate_cost(case.lines[2]["id"], "ACCEPT")
        assert last["status"] == "ACCEPTED"
        assert last["line_loaded_cost_cents"] == 3716

    def test_the_accepted_ledger_sums_the_rounded_lines_not_the_rounded_sum(self, api):
        """PRD §3.9: "The order is load-bearing: three notification lines of 3,333 cents each load to 3,716 cents apiece for a total of 11,148 cents, whereas summing first and rounding once would give 11,149."
        PRD §2.7: "First, overhead loading on a cost line is rounded to whole cents on that single line, before any line participates in a sum; summing unrounded products and rounding the total afterwards produces a different — and wrong — figure."

        Design: Difficulty/combinatorial_formula/cost_ledger_rounds_each_line_before_summing_mode_b
        """
        case = self._three_notification_lines()
        for line in case.lines:
            case.adjudicate_cost(line["id"], "ACCEPT")

        recall = case.read_recall()
        assert recall["total_loaded_cost_cents"] == 11148
        assert recall["total_loaded_cost_cents"] != 11149
        assert recall["insurable_loaded_cost_cents"] == 11148


class TestInsuranceWaterfall:
    """The coinsurance tier is pinned to the sublimit-capped subtotal."""

    @staticmethod
    def _case_with_five_accepted_cost_lines():
        case = case_with_verified_receipt(
            agency="USDA", quantity_shipped=1000, quantity_returned=960,
            quantity_unrecoverable=40, clock="2026-09-01T00:00:00Z",
        )
        case.accepted_cost("LOGISTICS", 6000000, description="Reverse logistics")
        case.accepted_cost("DESTRUCTION", 2000000, description="Incineration")
        case.accepted_cost("NOTIFICATION", 3333, description="Certified mail")
        case.accepted_cost("PRODUCT_VALUE", 8000000, description="Destroyed finished goods")
        case.accepted_cost("LEGAL", 1000000, description="Outside counsel")
        case.claim = case.open_claim("CLM-2026-0001")
        return case

    def test_the_sublimit_cap_selects_the_coinsurance_tier(self, api):
        """PRD §3.9: "Step one snapshots `claimed_cents` from the recall's current `insurable_loaded_cost_cents`, uncapped."
        PRD §3.9: "Step two applies a per-category sublimit: for each insurable category, sum `line_loaded_cost_cents` over this recall's accepted lines of that category, then take the smaller of that subtotal and the category's sublimit — 2,000,000 cents for `NOTIFICATION`, 5,000,000 cents for `LOGISTICS`, 3,000,000 cents for `DESTRUCTION` and 25,000,000 cents for `PRODUCT_VALUE` — and `capped_total_cents` is the sum of those four capped figures."
        PRD §3.9: "Step three selects `coinsurance_rate` from `capped_total_cents` and from nothing else: 0.90 when `capped_total_cents` is at least 50,000,000 cents, otherwise 0.85 when it is at least 10,000,000 cents, otherwise 0.80."

        Design: Difficulty/combinatorial_formula/insurance_waterfall_keys_coinsurance_tier_to_capped_total_mode_c
        """
        case = self._case_with_five_accepted_cost_lines()
        submitted = case.submit_claim(case.claim["id"])
        assert_insurance_claim(submitted)
        assert submitted["claimed_cents"] == 17243716
        assert submitted["capped_total_cents"] == 15733716
        assert submitted["coinsurance_rate"] == pytest.approx(0.85)

    def test_the_deductible_precedes_coinsurance_and_the_fee_follows(self, api):
        """PRD §3.9: "Step four subtracts the deductible *before* applying coinsurance: take `capped_total_cents` less the firm's `policy_deductible_cents`, floor that difference at zero, multiply by `coinsurance_rate`, and round half up to whole cents to obtain `settlement_payable_cents`."
        PRD §3.9: "Step six computes `handling_fee_cents` as `settlement_payable_cents` multiplied by 3.0 percent, rounded half up to whole cents."
        PRD §3.9: "Step seven sets `total_claim_value_cents` to `settlement_payable_cents` plus `handling_fee_cents`."
        PRD §3.9: "Lines in `LEGAL` and `LAB_TESTING` never enter any step of this waterfall, although they do count toward the recall's `total_loaded_cost_cents`."

        Design: Difficulty/combinatorial_formula/insurance_waterfall_keys_coinsurance_tier_to_capped_total_mode_c
        """
        case = self._case_with_five_accepted_cost_lines()
        submitted = case.submit_claim(case.claim["id"])
        assert submitted["settlement_payable_cents"] == 11248659
        assert submitted["handling_fee_cents"] == 337460
        assert submitted["total_claim_value_cents"] == 11586119
        assert submitted["status"] == "SUBMITTED"
        assert case.read_recall()["total_loaded_cost_cents"] == 18243716


class TestCostLedgerConservation:
    """Accepting then rejecting a cost line restores both ledgers exactly."""

    @staticmethod
    def _case_with_two_accepted_lines_and_one_more():
        case = draft_case()
        logistics = case.file_cost("LOGISTICS", 100000, description="Freight recovery")
        legal = case.file_cost("LEGAL", 50000, description="Outside counsel")
        case.adjudicate_cost(logistics["id"], "ACCEPT")
        case.adjudicate_cost(legal["id"], "ACCEPT")
        case.logistics_line = logistics
        case.legal_line = legal
        case.destruction_line = case.file_cost(
            "DESTRUCTION", 40000, description="Third-party incineration"
        )
        return case

    def test_accept_then_reject_restores_both_ledgers(self, api):
        """PRD §2.8: "Accepting a cost line and then rejecting it restores both the recall's total loaded cost and its insurable loaded cost to exactly their pre-cycle values."
        PRD §3.9: "Lines in `PENDING` and `REJECTED` contribute nothing, which is exactly why accepting a line and then rejecting it restores both totals to their pre-cycle values."

        Design: Difficulty/compensating_invariant/cost_accept_reject_roundtrip_conserves_loaded_cost_ledger
        """
        case = self._case_with_two_accepted_lines_and_one_more()
        before = case.read_recall()
        assert before["total_loaded_cost_cents"] == 158500
        assert before["insurable_loaded_cost_cents"] == 108500

        case.adjudicate_cost(case.destruction_line["id"], "ACCEPT")
        peak = case.read_recall()
        assert peak["total_loaded_cost_cents"] == 204300
        assert peak["insurable_loaded_cost_cents"] == 154300

        case.adjudicate_cost(
            case.destruction_line["id"], "REJECT",
            adjudication_note="Certificate missing.",
        )
        after = case.read_recall()
        assert after["total_loaded_cost_cents"] == 158500
        assert after["insurable_loaded_cost_cents"] == 108500
        assert after["total_loaded_cost_cents"] == before["total_loaded_cost_cents"]
        assert after["insurable_loaded_cost_cents"] == before["insurable_loaded_cost_cents"]

    def test_a_rejected_line_keeps_its_own_loaded_cost(self, api):
        """PRD §3.9: "From those, `line_loaded_cost_cents` is the line's `amount_cents` multiplied by one plus its `overhead_rate`, rounded half up to whole cents — and that rounding happens on this single line, before the line ever enters a sum."
        PRD §3.9: "`insurable` is true for `NOTIFICATION`, `LOGISTICS`, `DESTRUCTION` and `PRODUCT_VALUE`, and false for `LEGAL` and `LAB_TESTING`."

        Design: Difficulty/compensating_invariant/cost_accept_reject_roundtrip_conserves_loaded_cost_ledger
        """
        case = self._case_with_two_accepted_lines_and_one_more()
        assert case.logistics_line["line_loaded_cost_cents"] == 108500
        assert case.legal_line["line_loaded_cost_cents"] == 50000
        assert case.legal_line["insurable"] is False
        assert case.destruction_line["line_loaded_cost_cents"] == 45800

        case.adjudicate_cost(case.destruction_line["id"], "ACCEPT")
        rejected = case.adjudicate_cost(case.destruction_line["id"], "REJECT")
        assert rejected["status"] == "REJECTED"
        assert rejected["line_loaded_cost_cents"] == 45800
