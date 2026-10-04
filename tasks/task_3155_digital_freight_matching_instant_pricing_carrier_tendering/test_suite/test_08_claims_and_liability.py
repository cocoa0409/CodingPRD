"""Cargo claims: filing, review rounds, liability caps and clawback."""
from test_helpers import (
    api_client as api,
    create_claim_payload,
    make_claims_adjuster_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    read_carrier,
    read_settlement,
    set_clock,
    setup_delivered_load,
    setup_invoiced_load,
    setup_ready_settlement_with_reviewed_claim,
    list_load_settlements,
)


def _file(board, claimed_amount_cents):
    carrier = read_carrier(board["carrier_id"])
    payload = create_claim_payload(board["load"]["id"], board["carrier_id"],
                                   claimed_amount_cents, carrier["version"])
    response = api.file_claim(payload, make_shipper_headers(board["shipper_id"]))
    assert response.status_code == 201, f"setup failed: {response.status_code} {response.text}"
    return response.json()["data"]


class TestProvisionalLiability:
    """The provisional figure takes the smallest of three caps."""

    def test_the_price_cap_binds_below_the_claimed_amount_and_the_coverage(self):
        """PRD section 3.8: "`price_cap_cents`, which is the load's
        `declared_cargo_value_cents` multiplied by one and a half and rounded half
        up to the cent — the shipper cannot recover more than a hundred and fifty
        percent of what it declared the cargo was worth; and
        `provisional_liability_cents`, which is the smallest of the claimed amount,
        the liability limit, and the price cap."

        Design: Difficulty/combinatorial_formula/claim_price_cap_is_one_and_a_half_times_declared_value_while_claimed_is_twenty_million
        """
        board = setup_invoiced_load(declared_cargo_value_cents=5000000)
        claim = _file(board, 20000000)
        reviewed = api.review_claim(claim["id"], make_claims_adjuster_headers())
        assert reviewed.status_code == 200, reviewed.text
        data = reviewed.json()["data"]

        assert data["liability_limit_cents"] == 100000000
        assert data["price_cap_cents"] == 7500000
        assert data["provisional_liability_cents"] == 7500000
        assert data["provisional_liability_cents"] != 20000000
        assert data["review_rounds"] == 1
        assert data["status"] == "UNDER_REVIEW"

    def test_the_provisional_liability_is_not_yet_prorated_by_weight(self):
        """PRD section 3.8: "That provisional figure is capped by the carrier's
        coverage and by the value ceiling, but it is not yet prorated by weight."

        Design: Difficulty/combinatorial_formula/claim_price_cap_is_one_and_a_half_times_declared_value_while_claimed_is_twenty_million
        """
        board = setup_invoiced_load(declared_cargo_value_cents=5000000, weight_lbs=22000)
        claim = _file(board, 20000000)
        data = api.review_claim(
            claim["id"], make_claims_adjuster_headers()).json()["data"]
        assert data["provisional_liability_cents"] == 7500000, (
            "the provisional figure is the un-prorated minimum of the three caps")

    def test_a_high_value_commodity_lifts_the_commodity_cap(self):
        """PRD section 3.8: "The claim opens in `FILED` status with `review_rounds` zero and `escalated` false. At filing the server also captures `liability_limit_cents` as the lesser of the carrier's `cargo_coverage_limit_cents` and the commodity's liability cap — 100,000,000 cents for `GENERAL`, `TEMPERATURE_CONTROLLED`, and `HAZMAT`, but 250,000,000 cents for `HIGH_VALUE` cargo."

        Design: Corner/calculations/high_value_commodity_takes_the_250_million_liability_cap_not_the_100_million_default
        """
        board = setup_invoiced_load(commodity="HIGH_VALUE",
                                    declared_cargo_value_cents=200000000,
                                    carrier_overrides={"cargo_coverage_limit_cents": 100000000})
        claim = _file(board, 120000000)
        data = api.review_claim(
            claim["id"], make_claims_adjuster_headers()).json()["data"]

        assert data["liability_limit_cents"] == 100000000
        assert data["price_cap_cents"] == 300000000
        assert data["provisional_liability_cents"] == 100000000
        assert data["provisional_liability_cents"] != 120000000


class TestReviewCycle:
    """The review cycle is bounded by a round ceiling."""

    def test_the_review_round_ceiling_is_enforced(self):
        """PRD section 3.8: "three rounds is the ceiling, and any request that
        would push the count past three is refused with
        `ERR_CLAIM_REVIEW_ROUNDS_EXHAUSTED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/claim_case_cycles_between_under_review_and_info_requested_until_denied
        """
        board = setup_invoiced_load()
        claim = _file(board, 900000)
        adjuster = make_claims_adjuster_headers()
        assert api.review_claim(claim["id"], adjuster).status_code == 200
        assert api.request_claim_info(
            claim["id"], "Provide the seal photo", adjuster).status_code == 200
        assert api.review_claim(claim["id"], adjuster).status_code == 200

        before = api.get_claim(claim["id"], adjuster).json()["data"]
        assert before["review_rounds"] == 3
        assert before["status"] == "UNDER_REVIEW"

        exhausted = api.request_claim_info(claim["id"], "One more photo", adjuster)
        assert exhausted.status_code == 409, exhausted.text
        assert exhausted.json()["data"]["error_id"] == "ERR_CLAIM_REVIEW_ROUNDS_EXHAUSTED"

    def test_the_case_bounces_back_into_review_with_the_round_raised(self):
        """PRD section 3.8: "Reopening an `INFO_REQUESTED` case returns it to
        `UNDER_REVIEW` under the same round ceiling, raising `review_rounds` and
        recomputing `provisional_liability_cents` against the freshly captured
        liability limit."

        Design: Difficulty/non_linear_state_machine/claim_case_cycles_between_under_review_and_info_requested_until_denied
        """
        board = setup_invoiced_load()
        claim = _file(board, 900000)
        adjuster = make_claims_adjuster_headers()

        first = api.review_claim(claim["id"], adjuster).json()["data"]
        assert first["status"] == "UNDER_REVIEW"
        assert first["review_rounds"] == 1
        provisional_after_first = first["provisional_liability_cents"]

        bounced = api.request_claim_info(claim["id"], "Provide the seal photo", adjuster)
        assert bounced.status_code == 200, bounced.text
        assert bounced.json()["data"]["status"] == "INFO_REQUESTED"
        assert bounced.json()["data"]["review_rounds"] == 2

        returned = api.review_claim(claim["id"], adjuster)
        assert returned.status_code == 200, returned.text
        data = returned.json()["data"]
        assert data["status"] == "UNDER_REVIEW"
        assert data["review_rounds"] == 3
        assert data["provisional_liability_cents"] == provisional_after_first

    def test_denial_closes_the_case_without_a_deduction(self):
        """PRD section 3.8: "Denial ends a case cheaply: a case in
        `INFO_REQUESTED` — or any case past its first review round — can be denied
        once it has that round behind it, leaving `approved_amount_cents` at zero
        and taking no deduction anywhere."

        Design: Difficulty/non_linear_state_machine/claim_case_cycles_between_under_review_and_info_requested_until_denied
        """
        board = setup_invoiced_load()
        claim = _file(board, 900000)
        adjuster = make_claims_adjuster_headers()
        api.review_claim(claim["id"], adjuster)
        api.request_claim_info(claim["id"], "Provide the seal photo", adjuster)
        api.review_claim(claim["id"], adjuster)
        api.request_claim_info(claim["id"], "One more photo", adjuster)

        denied = api.deny_claim(claim["id"], "INSUFFICIENT_EVIDENCE", adjuster)
        assert denied.status_code == 200, denied.text
        assert denied.json()["data"]["status"] == "DENIED"
        assert denied.json()["data"]["approved_amount_cents"] == 0
        assert denied.json()["data"]["review_rounds"] == 3

        settlement = read_settlement(board["settlement"]["id"])
        assert settlement["claims_deduction_cents"] == 0


class TestEscalationThreshold:
    """Escalation is gated at strictly more than 2,500,000 cents."""

    def test_a_claim_at_the_threshold_is_not_large_enough_to_escalate(self):
        """PRD section 3.8: "Escalation is the treatment for the largest claims: a case in `UNDER_REVIEW` may be escalated only when its `provisional_liability_cents` is strictly greater than 2,500,000 cents, or the attempt is refused with `ERR_ESCALATION_THRESHOLD_NOT_MET` (HTTP 409); a case exactly at 2,500,000 cents is not large enough."

        Design: Corner/errors/escalating_a_small_claim_returns_escalation_threshold_not_met
        """
        board = setup_invoiced_load()
        claim = _file(board, 900000)
        data = api.review_claim(
            claim["id"], make_claims_adjuster_headers()).json()["data"]
        assert data["provisional_liability_cents"] == 900000

        refused = api.escalate_claim(claim["id"], make_claims_adjuster_headers())
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_ESCALATION_THRESHOLD_NOT_MET"

        after = api.get_claim(claim["id"], make_claims_adjuster_headers()).json()["data"]
        assert after["status"] == "UNDER_REVIEW"
        assert after["escalated"] is False

    def test_a_claim_above_the_threshold_escalates(self):
        """PRD section 3.8: "An escalated case sets `escalated` true and leaves the
        adjuster queue."

        Design: Corner/errors/escalating_a_small_claim_returns_escalation_threshold_not_met
        """
        board = setup_invoiced_load(declared_cargo_value_cents=50000000)
        claim = _file(board, 20000000)
        data = api.review_claim(
            claim["id"], make_claims_adjuster_headers()).json()["data"]
        assert data["provisional_liability_cents"] == 20000000

        escalated = api.escalate_claim(claim["id"], make_claims_adjuster_headers())
        assert escalated.status_code == 200, escalated.text
        assert escalated.json()["data"]["escalated"] is True
        assert escalated.json()["data"]["status"] == "ESCALATED"


class TestSettlementBlocking:
    """An open claim freezes the settlement; resolution releases it."""

    def test_an_unresolved_claim_blocks_invoicing(self):
        """PRD section 3.9: "the load must carry no claim in `FILED`,
        `UNDER_REVIEW`, or `INFO_REQUESTED` status, or the invoice is refused with
        `ERR_OPEN_CLAIMS_BLOCK_SETTLEMENT` (HTTP 409) — a disputed load does not
        get invoiced until the dispute is resolved."

        Design: Corner/errors/open_claim_blocks_invoicing_returns_open_claims_block_settlement
        """
        board = setup_delivered_load()
        _file(board, 500000)

        blocked = api.invoice_booking(board["booking"]["id"],
                                      make_shipper_headers(board["shipper_id"]))
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["data"]["error_id"] == "ERR_OPEN_CLAIMS_BLOCK_SETTLEMENT"

        settlements = list_load_settlements(board["load"]["id"])
        assert len(settlements) == 1
        assert settlements[0]["settlement_status"] == "ACCRUED"

    def test_resolving_the_claim_releases_the_invoice(self):
        """PRD section 3.9: "A `Shipper` invoicing a delivered booking requires two things: the load must be `DELIVERED`, or the request fails with `ERR_INVALID_STATE` (HTTP 409), and the load must carry no claim in `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED` status, or the invoice is refused with `ERR_OPEN_CLAIMS_BLOCK_SETTLEMENT` (HTTP 409) — a disputed load does not get invoiced until the dispute is resolved. On success the settlement moves from `ACCRUED` to `READY` and its `payout_due_at` is mustered from the load's delivery instant plus the shipper's `payment_terms_days`, counted in calendar days."

        Design: Corner/errors/open_claim_blocks_invoicing_returns_open_claims_block_settlement
        """
        board = setup_delivered_load()
        claim = _file(board, 500000)
        adjuster = make_claims_adjuster_headers()
        api.review_claim(claim["id"], adjuster)
        api.request_claim_info(claim["id"], "Send the BOL", adjuster)
        api.deny_claim(claim["id"], "NO_DAMAGE_FOUND", adjuster)

        invoiced = api.invoice_booking(board["booking"]["id"],
                                       make_shipper_headers(board["shipper_id"]))
        assert invoiced.status_code == 200, invoiced.text
        settlement = read_settlement(list_load_settlements(board["load"]["id"])[0]["id"])
        assert settlement["settlement_status"] == "READY"


class TestApprovalAndClawback:
    """Approval is weight-prorated and drags the settlement with it."""

    def test_approval_prorates_by_weight_and_deducts_from_the_settlement(self):
        """PRD section 3.8: "The `approved_amount_cents` is the provisional
        liability multiplied by the lesser of one and the load's `weight_lbs`
        divided by 44,000, rounded half up to the cent."
        PRD section 3.8: "Approval drags the settlement with it. If the load's settlement is
        `ACCRUED` or `READY`, the approved amount is added to that
        settlement's `claims_deduction_cents` as a deduction from the
        carrier's pay, and the settlement's gross, discount, and net are
        re-struck in the pinned order."

        Design: Corner/consistency_model/claim_approval_recomputes_the_ready_settlement_in_the_same_request_window
        """
        board = setup_ready_settlement_with_reviewed_claim(claimed_amount_cents=150000,
                                                          weight_lbs=22000)
        before = read_settlement(board["settlement"]["id"])
        assert before["claims_deduction_cents"] == 0
        assert before["gross_payable_cents"] == before["line_haul_cents"] \
            + before["accessorial_cents"]

        approved = api.approve_claim(board["claim"]["id"], make_claims_adjuster_headers())
        assert approved.status_code == 200, approved.text
        approved_data = approved.json()["data"]
        assert approved_data["approved_amount_cents"] == 75000, (
            "22,000 lb is exactly half a truckload, so the 150,000-cent "
            "provisional liability approves at half")

        after = read_settlement(board["settlement"]["id"])
        assert after["claims_deduction_cents"] == 75000
        assert after["gross_payable_cents"] == before["gross_payable_cents"] - 75000
        assert after["settlement_status"] == "READY"

    def test_each_approved_claim_compounds_the_carrier_risk_score(self):
        """PRD section 2.10: "twelve points for each of its claims that reached
        `APPROVED` or `SETTLED`, and five points for each clawback recorded against
        it."

        Design: Corner/cross_cutting_complexity_layers/each_approved_claim_compounds_the_carriers_operational_risk_score
        """
        board = setup_delivered_load()
        assert read_carrier(board["carrier_id"])["operational_risk_score"] == 100.0

        first = _file(board, 150000)
        second = _file(board, 150000)
        adjuster = make_claims_adjuster_headers()
        api.review_claim(first["id"], adjuster)
        api.review_claim(second["id"], adjuster)

        api.approve_claim(first["id"], adjuster)
        after_first = read_carrier(board["carrier_id"])
        # Twelve points for the approved claim, plus five for the clawback the
        # approval recorded against the live settlement.
        assert after_first["operational_risk_score"] == 83.0

        api.approve_claim(second["id"], adjuster)
        after_second = read_carrier(board["carrier_id"])
        assert after_second["operational_risk_score"] == 66.0
        assert after_second["claims_clawback_count"] == 2


class TestSettlementConfirmation:
    """Confirming an approved claim requires a compliant carrier."""

    def test_settling_on_a_suspended_carrier_is_refused(self):
        """PRD section 3.8: "An escalated case sets `escalated` true and leaves the adjuster queue. Settlement of an approved case is an operator act, available only while the carrier is `VERIFIED` — a non-compliant carrier yields `ERR_CARRIER_NOT_COMPLIANT` (HTTP 409) — and it confirms the approved amount against the carrier's settlement without incrementing the clawback count a second time."

        Design: Corner/errors/settling_an_approved_claim_on_a_suspended_carrier_returns_carrier_not_compliant
        """
        board = setup_delivered_load()
        claim = _file(board, 150000)
        adjuster = make_claims_adjuster_headers()
        api.review_claim(claim["id"], adjuster)
        approved = api.approve_claim(claim["id"], adjuster)
        assert approved.status_code == 200, approved.text

        settlement_id = list_load_settlements(board["load"]["id"])[0]["id"]
        deduction = read_settlement(settlement_id)["claims_deduction_cents"]

        set_clock("2027-06-01T00:00:00Z")
        api.run_sweep(make_platform_admin_headers())
        assert read_carrier(board["carrier_id"])["status"] == "SUSPENDED"

        refused = api.settle_claim(claim["id"], make_platform_admin_headers())
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_CARRIER_NOT_COMPLIANT"

        assert api.get_claim(
            claim["id"], adjuster).json()["data"]["status"] == "APPROVED"
        assert read_settlement(settlement_id)["claims_deduction_cents"] == deduction