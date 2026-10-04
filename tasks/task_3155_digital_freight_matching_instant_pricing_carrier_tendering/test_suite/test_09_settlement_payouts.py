"""Settlements: the pinned arithmetic, payout modes, quick pay and clawback."""
from test_helpers import (
    api_client as api,
    add_paid_history,
    assert_settlement_arithmetic,
    make_carrier_headers,
    make_claims_adjuster_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    read_carrier,
    read_settlement,
    set_clock,
    setup_delivered_load,
    setup_invoiced_load,
    setup_paid_load,
    setup_ready_settlement_with_reviewed_claim,
    shift,
    list_load_settlements,
)


class TestSettlementArithmetic:
    """The gross is struck before the quick-pay discount, and net last."""

    def test_gross_is_struck_before_the_discount_and_net_after_it(self):
        """PRD section 2.9: "The gross payable is the move's agreed rate plus the
        load's accessorial total, minus the cargo liability withheld from the
        carrier.  The quick-pay discount is then computed on that gross — not on
        the line haul alone — and it is zero whenever the carrier has not elected
        accelerated payout.  The net payable is the gross minus that discount."

        Design: Difficulty/combinatorial_formula/settlement_gross_struck_before_the_quick_pay_discount
        """
        board = setup_invoiced_load()
        settlement = read_settlement(board["settlement"]["id"])
        assert settlement["line_haul_cents"] == 372240
        assert settlement["claims_deduction_cents"] == 0
        assert settlement["gross_payable_cents"] == (
            settlement["line_haul_cents"] + settlement["accessorial_cents"]
        )
        assert settlement["quick_pay_discount_cents"] == 0
        assert settlement["net_payable_cents"] == settlement["gross_payable_cents"]
        assert_settlement_arithmetic(settlement)

    def test_the_discount_is_taken_on_the_gross_not_the_line_haul(self):
        """PRD section 3.9: "The rate is carried to four decimal places and the
        discount is the gross payable multiplied by that rate, rounded half up to
        the cent."

        Design: Difficulty/combinatorial_formula/settlement_gross_struck_before_the_quick_pay_discount
        """
        board = setup_invoiced_load(pickup_window_start="2026-10-05T08:00:00Z",
                                    pickup_window_end="2026-10-05T12:00:00Z")
        history = add_paid_history(board, 4)
        assert len(history) == 4

        settlement = read_settlement(board["settlement"]["id"])
        gross = settlement["gross_payable_cents"]
        assert gross > 0

        paid = api.payout_settlement(
            settlement["id"],
            {"payout_mode": "QUICK_PAY",
             "expected_settlement_version": settlement["version"]},
            make_platform_admin_headers())
        assert paid.status_code == 200, paid.text
        data = paid.json()["data"]
        expected_discount = int(gross * 0.0300 + 0.5)
        assert data["quick_pay_discount_cents"] == expected_discount
        assert data["net_payable_cents"] == gross - expected_discount
        assert data["settlement_status"] == "PAID"
        assert_settlement_arithmetic(data)

    def test_a_fifth_paid_settlement_crosses_into_the_smaller_tier(self):
        """PRD section 3.9: "a carrier's fifth paid settlement crosses from the
        0.0300 tier to the 0.0250 tier and therefore discounts a larger gross by a
        smaller rate."

        Design: Difficulty/combinatorial_formula/settlement_gross_struck_before_the_quick_pay_discount
        """
        board = setup_invoiced_load()
        history = add_paid_history(board, 5)
        assert len(history) == 5

        settlement = read_settlement(board["settlement"]["id"])
        gross = settlement["gross_payable_cents"]
        paid = api.payout_settlement(
            settlement["id"],
            {"payout_mode": "QUICK_PAY",
             "expected_settlement_version": settlement["version"]},
            make_platform_admin_headers())
        assert paid.status_code == 200, paid.text
        data = paid.json()["data"]
        assert data["quick_pay_discount_cents"] == int(gross * 0.0250 + 0.5)
        assert data["quick_pay_discount_cents"] < int(gross * 0.0300 + 0.5)


class TestPayoutModes:
    """TERMS honours the due date; QUICK_PAY beats it."""

    def test_a_terms_payout_before_the_due_date_is_refused(self):
        """PRD section 3.9: "Payout is the operator's act and comes in two modes, selected by a `payout_mode` of `TERMS` or `QUICK_PAY`. The `TERMS` mode honours the due date and is refused strictly before it, with `ERR_SETTLEMENT_NOT_DUE` (HTTP 409) — the settlement can be paid on its due date or after it, but not before."

        Design: Corner/errors/payout_before_the_due_date_returns_settlement_not_due
        """
        board = setup_invoiced_load(shipper_overrides={"payment_terms_days": 30})
        settlement = read_settlement(board["settlement"]["id"])
        assert settlement["payout_due_at"] is not None

        set_clock(shift(settlement["payout_due_at"], minutes=-1))
        refused = api.payout_settlement(
            settlement["id"],
            {"payout_mode": "TERMS", "expected_settlement_version": settlement["version"]},
            make_platform_admin_headers())
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_SETTLEMENT_NOT_DUE"
        assert read_settlement(settlement["id"])["settlement_status"] == "READY"

    def test_quick_pay_is_permitted_strictly_before_the_due_date(self):
        """PRD section 3.9: "The `TERMS` mode honours the due date and is refused strictly before it, with `ERR_SETTLEMENT_NOT_DUE` (HTTP 409) — the settlement can be paid on its due date or after it, but not before. The `QUICK_PAY` mode exists precisely to beat the date and is permitted strictly before `payout_due_at`; at exactly the due instant both modes are permitted."

        Design: Corner/errors/payout_before_the_due_date_returns_settlement_not_due
        """
        board = setup_invoiced_load()
        settlement = read_settlement(board["settlement"]["id"])
        set_clock(shift(settlement["payout_due_at"], minutes=-1))

        paid = api.payout_settlement(
            settlement["id"],
            {"payout_mode": "QUICK_PAY",
             "expected_settlement_version": settlement["version"]},
            make_platform_admin_headers())
        assert paid.status_code == 200, paid.text
        assert paid.json()["data"]["settlement_status"] == "PAID"
        booking = api.get_booking(
            board["booking"]["id"], make_carrier_headers(board["carrier_id"])).json()["data"]
        assert booking["quick_pay_elected"] is True

    def test_payout_discharges_the_shippers_reserved_exposure(self):
        """PRD section 2.8: "is discharged when the carrier is actually paid, at
        which point `credit_used_cents` falls by the same `agreed_rate_cents`."

        Design: Corner/cross_cutting_complexity_layers/replaying_a_payout_with_the_same_retry_key_does_not_pay_twice
        """
        board = setup_invoiced_load()
        before = api.get_shipper(
            board["shipper_id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert before["credit_used_cents"] == board["booking"]["agreed_rate_cents"]

        settlement = read_settlement(board["settlement"]["id"])
        set_clock(settlement["payout_due_at"])
        paid = api.payout_settlement(
            settlement["id"],
            {"payout_mode": "TERMS", "expected_settlement_version": settlement["version"]},
            make_platform_admin_headers())
        assert paid.status_code == 200, paid.text

        after = api.get_shipper(
            board["shipper_id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert after["credit_used_cents"] == 0


class TestReadyToggle:
    """A settlement may be pulled back only while it is unpaid."""

    def test_unready_clears_the_due_date_and_paying_blocks_it(self):
        """PRD section 3.9: "A settlement may also be pulled back from `READY` to
        `ACCRUED`, clearing its `payout_due_at`, while a claim is open — but never
        once it has been paid, which is refused with `ERR_INVALID_STATE` (HTTP
        409)."

        Design: Corner/errors/payout_before_the_due_date_returns_settlement_not_due
        """
        board = setup_invoiced_load()
        settlement = read_settlement(board["settlement"]["id"])
        unready = api.unready_settlement(settlement["id"], make_platform_admin_headers())
        assert unready.status_code == 200, unready.text
        assert unready.json()["data"]["settlement_status"] == "ACCRUED"
        assert unready.json()["data"]["payout_due_at"] is None

        ready_again = read_settlement(settlement["id"])
        api.invoice_booking(board["booking"]["id"], make_shipper_headers(board["shipper_id"]))
        ready_again = read_settlement(settlement["id"])
        set_clock(ready_again["payout_due_at"])
        api.payout_settlement(
            settlement["id"],
            {"payout_mode": "TERMS", "expected_settlement_version": ready_again["version"]},
            make_platform_admin_headers())

        refused = api.unready_settlement(settlement["id"], make_platform_admin_headers())
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_INVALID_STATE"


class TestClawback:
    """Clawback needs an approved claim and compounds the risk score."""

    def test_clawback_without_an_approved_claim_is_refused(self):
        """PRD section 3.9: "An operator may claw back against a `READY`
        settlement, but only when an `APPROVED` claim exists on the settlement's
        booking or load — with no approved claim the attempt is refused with
        `ERR_NO_APPROVED_CLAIM` (HTTP 409)."

        Design: Corner/errors/settling_an_approved_claim_on_a_suspended_carrier_returns_carrier_not_compliant
        """
        board = setup_invoiced_load()
        refused = api.clawback_settlement(board["settlement"]["id"],
                                          make_platform_admin_headers())
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_NO_APPROVED_CLAIM"

    def test_clawback_applies_the_deduction_and_scores_the_carrier(self):
        """PRD section 3.9: "An operator may claw back against a `READY` settlement, but only when an `APPROVED` claim exists on the settlement's booking or load — with no approved claim the attempt is refused with `ERR_NO_APPROVED_CLAIM` (HTTP 409). The approved amount is added to `claims_deduction_cents` and the net is recomputed; the carrier's `claims_clawback_count` rises by one and its `operational_risk_score` is recomputed with the five-point-per-clawback deduction of §2.10."

        Design: Corner/cross_cutting_complexity_layers/each_approved_claim_compounds_the_carriers_operational_risk_score
        """
        board = setup_ready_settlement_with_reviewed_claim(claimed_amount_cents=150000,
                                                          weight_lbs=22000)
        adjuster = make_claims_adjuster_headers()
        approved = api.approve_claim(board["claim"]["id"], adjuster)
        assert approved.status_code == 200, approved.text
        settlement = read_settlement(board["settlement"]["id"])
        assert settlement["settlement_status"] == "READY"
        assert settlement["claims_deduction_cents"] == 75000

        before_carrier = read_carrier(board["carrier_id"])
        before_settlement = read_settlement(settlement["id"])
        clawed = api.clawback_settlement(settlement["id"], make_platform_admin_headers())
        assert clawed.status_code == 200, clawed.text

        after_carrier = read_carrier(board["carrier_id"])
        assert after_carrier["claims_clawback_count"] == (
            before_carrier["claims_clawback_count"] + 1)
        assert after_carrier["operational_risk_score"] < (
            before_carrier["operational_risk_score"])

        updated = read_settlement(settlement["id"])
        assert updated["claims_deduction_cents"] >= (
            before_settlement["claims_deduction_cents"])
        assert_settlement_arithmetic(updated)


class TestSettlementIdempotency:
    """A replayed keyed action returns the stored outcome."""

    def test_a_repeated_payout_attempt_never_pays_the_carrier_twice(self):
        """PRD section 3.10: "A payment that carries a `retry_idempotency_key`
        already used for that settlement likewise returns the stored outcome instead
        of paying the carrier a second time, which is the guard that makes the
        money-moving operations safe to call again."

        Design: Corner/cross_cutting_complexity_layers/replaying_a_payout_with_the_same_retry_key_does_not_pay_twice
        """
        board = setup_paid_load()
        settlement_id = board["settlement"]["id"]
        rows = list_load_settlements(board["load"]["id"])
        assert len(rows) == 1
        assert rows[0]["settlement_status"] == "PAID"
        paid_at = rows[0]["paid_at"]

        paid = read_settlement(settlement_id)
        again = api.payout_settlement(
            settlement_id,
            {"payout_mode": "TERMS", "expected_settlement_version": paid["version"]},
            make_platform_admin_headers())

        rows_after = list_load_settlements(board["load"]["id"])
        assert len(rows_after) == 1, "a repeat payout must not open a second settlement"
        assert read_settlement(settlement_id)["settlement_status"] == "PAID"
        assert read_settlement(settlement_id)["paid_at"] == paid_at
        shipper = api.get_shipper(
            board["shipper_id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert shipper["credit_used_cents"] == 0, (
            "the shipper's exposure is discharged exactly once")
        if again.status_code == 200:
            assert again.json()["data"]["paid_at"] == paid_at