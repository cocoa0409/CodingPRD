"""Escrow accrual arithmetic, the approval deposit cascade and the append-only ledger.

The escrow account is an append-only ledger whose signed sum is the driver's
balance, and the accrual that feeds it has a pinned rounding order.
"""

from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    CLERK_HEADERS,
    api_client,
    assert_append_only_record_shape,
    assert_escrow_ledger_reconciles,
    assert_timestamps_equal,
    factories,
    fixtures,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import ESCROW_ACCRUAL_BPS
from test_helpers.types import (
    DriverType,
    EscrowReasonCode,
    EscrowStatus,
    EscrowTxnType,
    LineType,
    MileageGuide,
    PerDiemMethod,
    SettlementStatus,
)


def _escrow_environment(escrow_target_cents, escrow_monthly_deduction_cents=40000, name="Leased Escrow"):
    """An escrow-bearing leased-operator package and a driver whose escrow axis is
    COLLECTING at a zero balance."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=True,
        escrow_target_cents=escrow_target_cents,
        escrow_monthly_deduction_cents=escrow_monthly_deduction_cents,
        name=name,
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Ed Escrow",
        home_state="TX",
    )
    return package, driver


def _deliver_percent_load(driver_id, miles, revenue_cents, **load_overrides):
    load = fixtures.tender_load(
        driver_id, practical_miles=miles, hhg_miles=miles,
        linehaul_revenue_cents=revenue_cents, stop_count=1, **load_overrides,
    )
    fixtures.set_clock(fixtures.TS_DISPATCH)
    fixtures.dispatch(load["id"])
    fixtures.set_clock(fixtures.TS_DELIVER)
    fixtures.deliver(load["id"])
    return fixtures.read_load(load["id"])


class TestEscrowAccrualRoundsEachLineThenSums:
    """Three earning lines whose eighth parts each land on a half cent."""

    def _three_line_settlement(self):
        _, driver = _escrow_environment(250000, name="Leased Escrow Rounding")
        first = _deliver_percent_load(driver["id"], 300, 100024)
        second = _deliver_percent_load(driver["id"], 300, 80024)
        third = _deliver_percent_load(driver["id"], 250, 60024)
        assert [first["linehaul_pay_cents"], second["linehaul_pay_cents"], third["linehaul_pay_cents"]] == [
            25006,
            20006,
            15006,
        ], "the three loads must pay the amounts the rounding order is observable on"
        fixtures.set_clock(fixtures.TS_SETTLE)
        settlement = fixtures.open_settlement(driver["id"])
        return driver, settlement

    def test_accrual_rounds_each_earning_line_before_summing_them(self):
        """Eight percent of 25006, 20006 and 15006 rounds to 2000, 1600 and 1200, which sum
        to 4800; rounding the 60018 gross once would give 4801 instead.

        PRD 3.7: "**The rounding order is pinned: round each line, then sum. Summing first
        and rounding once is explicitly wrong and produces a different cent total.**"

        Design: Difficulty/combinatorial_formula/escrow_accrual_round_per_line_then_sum
        """
        _, settlement = self._three_line_settlement()

        prepared = validate_success(
            api_client.prepare_settlement(settlement["id"], {}, CLERK_HEADERS)
        )

        assert prepared["gross_pay_cents"] == 60018
        assert prepared["escrow_deduction_cents"] == 4800, (
            "round-then-sum yields 4800 cents of escrow accrual"
        )
        assert prepared["escrow_deduction_cents"] != 4801, (
            "4801 is the sum-then-round answer and is explicitly wrong"
        )
        assert prepared["deduction_total_cents"] == 4800
        assert prepared["net_pay_cents"] == 55218

    def test_the_accrual_lands_on_one_non_taxable_escrow_deduction_line(self):
        """The accrual is carried by a single ESCROW_DEDUCTION line alongside the three
        earning lines, and that line is not taxable.

        PRD 3.7: "The escrow accrual is computed next, producing at most one
        `ESCROW_DEDUCTION` line with `reference_type` `DRIVER` and `taxable` false."

        Design: Difficulty/combinatorial_formula/escrow_accrual_round_per_line_then_sum
        """
        driver, settlement = self._three_line_settlement()

        fixtures.prepare(settlement["id"])
        lines = fixtures.read_settlement_lines(settlement["id"])

        escrow_lines = [line for line in lines if line["line_type"] == LineType.ESCROW_DEDUCTION]
        assert len(escrow_lines) == 1
        assert escrow_lines[0]["amount_cents"] == 4800
        assert escrow_lines[0]["taxable"] is False
        assert escrow_lines[0]["reference_type"] == "DRIVER"
        assert escrow_lines[0]["reference_id"] == driver["id"]

        assert fixtures.read_settlement(settlement["id"])["line_count"] == 4

    def test_accessorial_lines_are_excluded_from_the_accrual_base(self):
        """Eight percent is taken over the earning lines only, so an approved accessorial
        raises gross without raising the escrow accrual.

        PRD 3.7: "Accessorial and retroactive-correction lines never accrue escrow."

        Design: Difficulty/combinatorial_formula/escrow_accrual_round_per_line_then_sum
        """
        _, driver = _escrow_environment(250000, name="Leased Escrow Rounding")
        load = _deliver_percent_load(driver["id"], 300, 100024, tarp_required=True)
        claim = fixtures.approved_claim(
            load["id"],
            driver["id"],
            "TARPING",
            "2026-08-04T10:00:00Z",
            "2026-08-04T11:00:00Z",
            document_ref="doc://tarp-1",
        )
        assert claim["amount_cents"] == 7500

        fixtures.set_clock(fixtures.TS_SETTLE)
        settlement = fixtures.open_settlement(driver["id"])
        prepared = validate_success(
            api_client.prepare_settlement(settlement["id"], {}, CLERK_HEADERS)
        )

        assert prepared["accessorial_total_cents"] == 7500
        assert prepared["gross_pay_cents"] == 25006 + 7500
        assert prepared["escrow_deduction_cents"] == 2000, (
            "the accrual base is the 25006 earning line alone"
        )


class TestApprovalDepositsTheAccrualAndFundsTheAccount:
    """Approval is a four-hop cascade the request body never mentions."""

    def _prepared_capped_settlement(self):
        """An escrow target of 3500 caps the 3686 raw accrual, so the deposit funds the
        account exactly."""
        _, driver = _escrow_environment(3500, name="Leased Escrow Target")
        load = fixtures.delivered_load(driver["id"], stop_count=1)
        assert load["linehaul_pay_cents"] == 46080
        fixtures.set_clock(fixtures.TS_SETTLE)
        settlement = fixtures.open_settlement(driver["id"])
        fixtures.prepare(settlement["id"])
        return driver, fixtures.read_settlement(settlement["id"])

    def test_accrual_is_clamped_by_the_headroom_remaining_to_the_target(self):
        """Eight percent of 46080 is 3686, but the headroom to a 3500 target is smaller, so
        the least of the three quantities is withheld.

        PRD 3.7: "`escrow_deduction_cents` is then the least of three quantities: that raw
        accrual, the driver's `escrow_monthly_deduction_cents`, and the headroom remaining to
        the target, which is the driver's `escrow_target_cents` less the driver's current
        `escrow_balance_cents`."

        Design: Difficulty/transitive_cascade/settlement_approve_escrow_deposit_funded_cascade
        """
        _, settlement = self._prepared_capped_settlement()

        raw_accrual = round(46080 * ESCROW_ACCRUAL_BPS / 10000)
        assert raw_accrual == 3686
        assert settlement["escrow_deduction_cents"] == 3500, (
            "the headroom to the target is the least of the three quantities"
        )
        assert settlement["net_pay_cents"] == 42580

    def test_approval_appends_one_deposit_that_funds_the_escrow_axis(self):
        """Approving the statement writes a single DEPOSIT entry, raises the balance to the
        target and moves the escrow axis to FUNDED with its timestamp stamped.

        PRD 3.8: "When the settlement carries an `ESCROW_DEDUCTION` line, an escrow ledger
        entry is appended with `txn_type` `DEPOSIT`, `reason_code` `SETTLEMENT_ACCRUAL`,
        `settlement_id` set to this settlement, and `amount_cents` equal to the positive line
        amount."
        PRD 3.8: "The new `escrow_balance_cents` itself drives the escrow axis `COLLECTING` →
        `FUNDED` when it reaches `escrow_target_cents`, stamping `escrow_funded_at`".

        Design: Difficulty/transitive_cascade/settlement_approve_escrow_deposit_funded_cascade
        """
        driver, settlement = self._prepared_capped_settlement()

        approved = validate_success(
            api_client.approve_settlement(settlement["id"], APPROVER_HEADERS)
        )
        assert approved["status"] == SettlementStatus.APPROVED

        entries, meta = validate_paginated(
            api_client.list_escrow_transactions(ADMIN_HEADERS, params={"driver_id": driver["id"]})
        )
        assert meta["total_count"] == 1
        entry = entries[0]
        assert_append_only_record_shape(entry, "escrow entry")
        assert entry["txn_type"] == EscrowTxnType.DEPOSIT
        assert entry["reason_code"] == EscrowReasonCode.SETTLEMENT_ACCRUAL
        assert entry["amount_cents"] == 3500
        assert entry["settlement_id"] == settlement["id"]
        assert entry["balance_after_cents"] == 3500

        after = fixtures.read_driver(driver["id"])
        assert after["escrow_balance_cents"] == 3500
        assert after["escrow_status"] == EscrowStatus.FUNDED
        assert_timestamps_equal(after["escrow_funded_at"], fixtures.TS_SETTLE, "escrow_funded_at")

    def test_approval_also_posts_the_year_to_date_wage_accumulators(self):
        """The same approval recomputes the wage accumulators, which on a package with no per
        diem method leaves the whole gross taxable.

        PRD 3.8: "The driver's `ytd_gross_pay_cents`, `ytd_taxable_wages_cents` and
        `ytd_per_diem_non_taxable_cents` are recomputed, because this settlement now counts
        toward them."

        Design: Difficulty/transitive_cascade/settlement_approve_escrow_deposit_funded_cascade
        """
        driver, settlement = self._prepared_capped_settlement()

        fixtures.approve(settlement["id"])

        after = fixtures.read_driver(driver["id"])
        assert after["ytd_gross_pay_cents"] == 46080
        assert after["ytd_taxable_wages_cents"] == 46080
        assert after["ytd_per_diem_non_taxable_cents"] == 0


class TestEscrowLedgerIsAppendOnly:
    """A mistaken entry is compensated, never restated."""

    def _funded_driver(self):
        _, driver = _escrow_environment(3500, name="Leased Escrow Ledger")
        fixtures.delivered_load(driver["id"], stop_count=1)
        fixtures.set_clock(fixtures.TS_SETTLE)
        settlement = fixtures.open_settlement(driver["id"])
        fixtures.prepare(settlement["id"])
        fixtures.approve(settlement["id"])
        funded = fixtures.read_driver(driver["id"])
        assert funded["escrow_status"] == EscrowStatus.FUNDED
        assert funded["escrow_balance_cents"] == 3500
        return funded

    def test_permissible_deduction_is_stored_negative_and_drops_the_axis_to_collecting(self):
        """The request supplies a positive magnitude, the ledger stores the negation, and the
        balance falling below the target reopens collection.

        PRD 3.3: "A `PERMISSIBLE_DEDUCTION` is negative: the request supplies a positive
        magnitude and the server negates it."
        PRD 3.3: "Whenever an appended entry drops `escrow_balance_cents` back below
        `escrow_target_cents`, the axis moves `FUNDED` → `COLLECTING`, `escrow_funded_at` is
        cleared to null".

        Design: Difficulty/compensating_invariant/escrow_principal_ledger_invariant_after_reversal
        """
        driver = self._funded_driver()

        entry = validate_success(
            api_client.create_escrow_deduction(
                driver["id"],
                factories.escrow_deduction_payload(
                    1200,
                    driver["version"],
                    reason_code=EscrowReasonCode.TRACTOR_LEASE,
                    document_ref="doc://lease-inv-1200",
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert entry["txn_type"] == EscrowTxnType.PERMISSIBLE_DEDUCTION
        assert entry["amount_cents"] == -1200
        assert entry["balance_after_cents"] == 2300
        assert entry["settlement_id"] is None
        assert entry["reverses_transaction_id"] is None

        after = fixtures.read_driver(driver["id"])
        assert after["escrow_balance_cents"] == 2300
        assert after["escrow_status"] == EscrowStatus.COLLECTING
        assert after["escrow_funded_at"] is None

    def test_reversal_negates_the_original_row_without_mutating_it(self):
        """The reversal is a third row whose amount is the exact negation of the entry it
        points at; the original row still reads -1200 afterwards and the balance returns.

        PRD 3.3: "A `REVERSAL` is exactly the negation of the `amount_cents` of the entry it
        reverses, identified by `reverses_transaction_id`, which is null on every other entry
        type."
        PRD 3.3: "Because an entry is never edited, a mistaken entry is corrected by writing a
        compensating one."

        Design: Difficulty/compensating_invariant/escrow_principal_ledger_invariant_after_reversal
        """
        driver = self._funded_driver()
        deduction = validate_success(
            api_client.create_escrow_deduction(
                driver["id"],
                factories.escrow_deduction_payload(
                    1200,
                    driver["version"],
                    reason_code=EscrowReasonCode.TRACTOR_LEASE,
                    document_ref="doc://lease-inv-1200",
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        reversal = validate_success(
            api_client.reverse_escrow_transaction(
                deduction["id"],
                factories.escrow_reversal_payload(EscrowReasonCode.DEDUCTION_DISPUTED),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert reversal["txn_type"] == EscrowTxnType.REVERSAL
        assert reversal["amount_cents"] == 1200
        assert reversal["reverses_transaction_id"] == deduction["id"]
        assert reversal["balance_after_cents"] == 3500

        original = validate_success(
            api_client.get_escrow_transaction(deduction["id"], ADMIN_HEADERS)
        )
        assert original["amount_cents"] == -1200, "the original row is never restated"
        assert original["txn_type"] == EscrowTxnType.PERMISSIBLE_DEDUCTION
        assert original["balance_after_cents"] == 2300

    def test_the_balance_always_equals_the_signed_sum_of_every_appended_row(self):
        """After the deposit, the deduction and its reversal the ledger holds three rows whose
        signed sum is the driver's balance, and the account is funded again.

        PRD 3.3: "The escrow account is an **append-only ledger**. Every movement is a new
        entry recording its `driver_id`, its `txn_type`".
        PRD 3.3: "Whenever an appended entry raises `escrow_balance_cents` to
        `escrow_target_cents` or above, the axis moves `COLLECTING` → `FUNDED`".

        Design: Difficulty/compensating_invariant/escrow_principal_ledger_invariant_after_reversal
        """
        driver = self._funded_driver()
        deduction = validate_success(
            api_client.create_escrow_deduction(
                driver["id"],
                factories.escrow_deduction_payload(
                    1200,
                    driver["version"],
                    reason_code=EscrowReasonCode.TRACTOR_LEASE,
                    document_ref="doc://lease-inv-1200",
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.reverse_escrow_transaction(
                deduction["id"],
                factories.escrow_reversal_payload(EscrowReasonCode.DEDUCTION_DISPUTED),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        entries, meta = validate_paginated(
            api_client.list_escrow_transactions(ADMIN_HEADERS, params={"driver_id": driver["id"]})
        )
        assert meta["total_count"] == 3
        assert [entry["txn_type"] for entry in entries] == [
            EscrowTxnType.DEPOSIT,
            EscrowTxnType.PERMISSIBLE_DEDUCTION,
            EscrowTxnType.REVERSAL,
        ]

        final = fixtures.read_driver(driver["id"])
        assert final["escrow_balance_cents"] == 3500
        assert final["escrow_status"] == EscrowStatus.FUNDED
        assert_escrow_ledger_reconciles(entries, final["escrow_balance_cents"])
