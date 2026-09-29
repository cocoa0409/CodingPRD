"""Stale-version protection sitting above the state guards it protects.

Every one of these writes is repeatable by design, so nothing in the record's own state
says "you already did this". The version check is the only thing that can tell a replay
from a fresh intention, and it is asked before the state question is asked.
"""

from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    CLERK_HEADERS,
    PAYROLL_ADMIN_ID,
    ApiErrorId,
    api_client,
    assert_timestamps_equal,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    RETRO_HOLD_THRESHOLD_CENTS,
)
from test_helpers.types import (
    CorrectionReasonCode,
    CorrectionStatus,
    CorrectionType,
    DisputeStatus,
    DriverType,
    EscrowReasonCode,
    EscrowStatus,
    EscrowTxnType,
    LineType,
    MileageGuide,
    PayPackageStatus,
    PayStatus,
    PerDiemMethod,
    SettlementStatus,
)

# The reference haul of 780 practical miles at 58 cents, with the marginal bump of 3
# cents applying to the 280 miles above the 500-mile band break.
LINEHAUL_780_CENTS = 46080
# The same haul re-graded onto the household-goods guide's 742 miles, 2,318 cents lower.
REGRADE_DELTA_CENTS = -2318


class TestPayPackageRevisionUnderConcurrency:
    """Two guards can both be true of a replayed revision; only the version one is reported."""

    def test_the_replayed_revision_is_stale_and_only_the_re_read_view_meets_the_pending_guard(self):
        """One revision request replayed verbatim satisfies neither guard's happy path: the
        package has moved on *and* it now has a DRAFT successor open. The stale-version answer
        is the one that comes back, and only after re-reading the package does the request get
        far enough to hear about the pending revision.

        PRD 2.8: "A package may legitimately be revised more than once and the newest revision
        supersedes it on activation, so the stale-version check is the only deterministic guard
        against opening a revision from an out-of-date view of the package."
        PRD 2.9 rung 15: "`ERR_STALE_PAY_PACKAGE_VERSION` — on a revision,
        `expected_pay_package_version` equals the package's current `version`."
        PRD 2.9 rung 19: "`ERR_PAY_PACKAGE_REVISION_PENDING` — the package's
        `has_pending_revision` is false; a package whose successor is still `DRAFT` can neither
        be revised again nor retired."

        Design: Corner/cross_cutting_complexity_layers/a_stale_pay_package_version_outranks_the_pending_revision_guard
        """
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            name="Leased OCC Revision",
        )
        assert package["status"] == PayPackageStatus.ACTIVE
        assert package["has_pending_revision"] is False
        observed_version = package["version"]

        successor = validate_success(
            api_client.revise_pay_package(
                package["id"],
                factories.revise_payload(observed_version, name="Leased OCC Revision v2"),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert successor["status"] == PayPackageStatus.DRAFT
        assert successor["supersedes_pay_package_id"] == package["id"]
        assert successor["id"] != package["id"]

        replay = api_client.revise_pay_package(
            package["id"],
            factories.revise_payload(observed_version, name="Leased OCC Revision v2"),
            ADMIN_HEADERS,
        )

        validate_error(replay, ApiErrorId.STALE_PAY_PACKAGE_VERSION, 412)
        assert replay.json()["data"]["error_id"] != ApiErrorId.PAY_PACKAGE_REVISION_PENDING, (
            "the stale-version rung is asked before the pending-revision state rung"
        )

        reread = validate_success(api_client.get_pay_package(package["id"], ADMIN_HEADERS))
        assert reread["version"] != observed_version, (
            "opening the revision bumped the predecessor, which is why the replay was stale"
        )
        assert reread["has_pending_revision"] is True

        with_fresh_version = api_client.revise_pay_package(
            package["id"],
            factories.revise_payload(reread["version"], name="Leased OCC Revision v3"),
            ADMIN_HEADERS,
        )

        validate_error(with_fresh_version, ApiErrorId.PAY_PACKAGE_REVISION_PENDING, 409)
        successors, meta = validate_paginated(
            api_client.list_pay_packages(
                ADMIN_HEADERS, {"supersedes_pay_package_id": package["id"]}
            )
        )
        assert meta["total_count"] == 1, "neither refused revision opened a second successor"
        assert successors[0]["id"] == successor["id"]
        final = validate_success(api_client.get_pay_package(package["id"], ADMIN_HEADERS))
        assert final["status"] == PayPackageStatus.ACTIVE
        assert final["has_pending_revision"] is True
        assert final["version"] == reread["version"], "a refused revision is not a mutation"


def _swept_correction_environment():
    """A paid statement of 46,080 cents, an upheld HHG re-grade that mints a 2,318-cent
    down-grade against it, and a fresh DRAFT settlement for the following week."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        revenue_bps=None,
        name="Leased OCC Sweep",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Cass Concurrent",
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1)
    assert load["linehaul_pay_cents"] == LINEHAUL_780_CENTS

    first = fixtures.paid_settlement(driver["id"], payment_reference="ACH-OCCS-1")
    assert first["status"] == SettlementStatus.PAID
    assert first["linehaul_total_cents"] == LINEHAUL_780_CENTS

    fixtures.set_clock("2026-08-11T09:00:00Z")
    dispute = fixtures.file_mileage_dispute(
        driver["id"],
        load["id"],
        MileageGuide.HHG,
        fixtures.REF_HHG_MILES,
        narrative="The household-goods guide is the contracted basis for this lane.",
        evidence_doc_ref="doc://occ-sweep-guide",
    )
    fixtures.review(dispute["id"], CLERK_HEADERS)
    upheld = fixtures.resolve(
        dispute["id"], "UPHOLD", APPROVER_HEADERS, resolution_note="HHG basis confirmed."
    )
    assert upheld["status"] == DisputeStatus.UPHELD
    assert upheld["adjustment_cents"] == REGRADE_DELTA_CENTS
    correction_id = upheld["resolution_correction_id"]
    assert correction_id is not None
    assert fixtures.read_driver(driver["id"])["settlement_hold"] is False

    fixtures.set_clock("2026-08-12T09:00:00Z")
    second = fixtures.open_settlement(
        driver["id"], "2026-08-10T00:00:00Z", "2026-08-17T00:00:00Z"
    )
    assert second["status"] == SettlementStatus.DRAFT
    return {
        "driver": driver,
        "load": load,
        "first": first,
        "correction_id": correction_id,
        "second": second,
    }


class TestCorrectionSweepUnderConcurrency:
    """A sweep is repeatable while the settlement is DRAFT, so nothing but the version
    distinguishes a replay from an intention to sweep again."""

    def test_the_replayed_sweep_is_stale_rather_than_empty_and_the_swept_line_is_untouched(self):
        """After the first sweep there is nothing left to take, so an empty-sweep answer would
        also be defensible; the version mismatch is reported instead, and the replay leaves the
        single RETRO_CORRECTION line exactly as the first sweep wrote it.

        PRD 2.8: "Sweeping corrections is repeatable while the settlement remains `DRAFT` — a
        later call simply picks up whatever corrections are pending then — so a stale view of
        the settlement's totals is detectable only by the version check."
        PRD 2.9 rung 16: "`ERR_STALE_SETTLEMENT_VERSION` — on a correction sweep,
        `expected_settlement_version` equals the settlement's current `version`."
        PRD 2.9 rung 51: "`ERR_NO_PENDING_CORRECTIONS` — every correction a sweep would take is
        `PENDING` and belongs to the settlement's driver, and at least one such correction
        exists."

        Design: Corner/cross_cutting_complexity_layers/a_stale_settlement_version_outranks_the_no_pending_corrections_guard
        """
        env = _swept_correction_environment()
        settlement_id = env["second"]["id"]
        observed_version = env["second"]["version"]

        swept = validate_success(
            api_client.apply_corrections(
                settlement_id,
                factories.apply_corrections_payload(observed_version),
                ADMIN_HEADERS,
            )
        )

        assert swept["retro_correction_total_cents"] == REGRADE_DELTA_CENTS
        assert swept["line_count"] == 1
        assert swept["version"] > observed_version
        applied = fixtures.read_correction(env["correction_id"])
        assert applied["status"] == CorrectionStatus.APPLIED
        assert applied["applied_settlement_id"] == settlement_id
        assert applied["delta_gross_cents"] == REGRADE_DELTA_CENTS
        swept_lines = fixtures.read_settlement_lines(settlement_id)
        assert len(swept_lines) == 1
        original_sequence = swept_lines[0]["sequence"]

        replay = api_client.apply_corrections(
            settlement_id,
            factories.apply_corrections_payload(observed_version),
            ADMIN_HEADERS,
        )

        validate_error(replay, ApiErrorId.STALE_SETTLEMENT_VERSION, 412)
        assert replay.json()["data"]["error_id"] != ApiErrorId.NO_PENDING_CORRECTIONS, (
            "the stale-version rung is asked long before the money-side sweep rung"
        )
        lines = fixtures.read_settlement_lines(settlement_id)
        assert len(lines) == 1, "the refused replay appended no second line"
        assert lines[0]["line_type"] == LineType.RETRO_CORRECTION
        assert lines[0]["amount_cents"] == REGRADE_DELTA_CENTS
        assert lines[0]["reference_id"] == env["correction_id"]
        assert lines[0]["sequence"] == original_sequence, (
            "swept lines keep the sequence they were given"
        )
        after = fixtures.read_settlement(settlement_id)
        assert after["status"] == SettlementStatus.DRAFT
        assert after["retro_correction_total_cents"] == REGRADE_DELTA_CENTS
        assert after["version"] == swept["version"], "a refused sweep is not a mutation"


class TestEscrowDeductionUnderConcurrency:
    """The balance an operator sized a deduction against is the thing the version protects."""

    def test_the_second_deduction_on_a_stale_view_is_refused_and_succeeds_on_the_fresh_one(self):
        """Two deductions against the same driver are entirely legitimate, so no state field can
        refuse the second one; only the driver version, bumped by the first deduction, reveals
        that the 2,686-cent balance the second was sized against is no longer what the operator
        saw.

        PRD 2.8: "Multiple deductions against the same driver are legitimate and no state field
        blocks a second one, so the escrow balance the operator sized the deduction against can
        only be protected this way."
        PRD 2.9 rung 17: "`ERR_STALE_DRIVER_VERSION` — on an escrow deduction,
        `expected_driver_version` equals the driver's current `version`."
        PRD 3.3: "A `PERMISSIBLE_DEDUCTION` is negative: the request supplies a positive
        magnitude and the server negates it."
        PRD 2.3: "collections are returned sorted by `created_at` in ascending order — oldest row
        first — which makes the escrow ledger, the settlement-line list and the advance list
        readable as chronological registers."

        Design: Corner/cross_cutting_complexity_layers/a_stale_driver_version_blocks_a_second_escrow_deduction_on_an_old_balance
        """
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=True,
            escrow_target_cents=250000,
            escrow_monthly_deduction_cents=40000,
            name="Leased OCC Escrow",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Dex Deduction",
            home_state="TX",
        )
        assert fixtures.delivered_load(driver["id"], stop_count=1)[
            "linehaul_pay_cents"
        ] == LINEHAUL_780_CENTS
        fixtures.approved_settlement(driver["id"])

        accrued = fixtures.read_driver(driver["id"])
        assert accrued["escrow_balance_cents"] == 3686
        observed_version = accrued["version"]

        fixtures.set_clock("2026-08-10T10:00:00Z")
        first = validate_success(
            api_client.create_escrow_deduction(
                driver["id"],
                factories.escrow_deduction_payload(
                    1000,
                    observed_version,
                    reason_code=EscrowReasonCode.TRACTOR_LEASE,
                    document_ref="doc://occ-tractor-lease",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert first["txn_type"] == EscrowTxnType.PERMISSIBLE_DEDUCTION
        assert first["amount_cents"] == -1000
        assert first["balance_after_cents"] == 2686

        stale = api_client.create_escrow_deduction(
            driver["id"],
            factories.escrow_deduction_payload(
                500,
                observed_version,
                reason_code=EscrowReasonCode.INSURANCE_PREMIUM,
                document_ref="doc://occ-insurance",
            ),
            ADMIN_HEADERS,
        )

        validate_error(stale, ApiErrorId.STALE_DRIVER_VERSION, 412)
        refused_id = stale.json()["data"]["error_id"]
        assert refused_id != ApiErrorId.ESCROW_INSUFFICIENT_BALANCE, (
            "500 cents is well inside the 2,686-cent balance"
        )
        assert refused_id != ApiErrorId.DEDUCTION_NOT_PERMISSIBLE, (
            "an insurance premium is one of the six permissible reasons"
        )
        held = fixtures.read_driver(driver["id"])
        assert held["escrow_balance_cents"] == 2686, "the refused deduction moved no money"
        assert held["version"] != observed_version

        fixtures.set_clock("2026-08-10T11:00:00Z")
        retried = validate_success(
            api_client.create_escrow_deduction(
                driver["id"],
                factories.escrow_deduction_payload(
                    500,
                    held["version"],
                    reason_code=EscrowReasonCode.INSURANCE_PREMIUM,
                    document_ref="doc://occ-insurance",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert retried["amount_cents"] == -500
        assert retried["balance_after_cents"] == 2186
        ledger = fixtures.list_escrow_transactions(driver_id=driver["id"])
        assert len(ledger) == 3, "the stale attempt appended nothing to an append-only ledger"
        assert [row["amount_cents"] for row in ledger] == [3686, -1000, -500]
        assert [row["txn_type"] for row in ledger] == [
            EscrowTxnType.DEPOSIT,
            EscrowTxnType.PERMISSIBLE_DEDUCTION,
            EscrowTxnType.PERMISSIBLE_DEDUCTION,
        ]
        final = fixtures.read_driver(driver["id"])
        assert final["escrow_balance_cents"] == 2186
        assert final["escrow_status"] == EscrowStatus.COLLECTING


class TestCancellingACorrectionWalksTheDerivedChainBackwards:
    """settlement_hold is derived from a sum which is itself derived from a set of rows, so
    removing one row has to be felt two hops away in the same request."""

    def test_the_cancel_clears_the_sum_and_the_flag_and_is_then_immutable(self):
        """A 57,200-cent down-grade is over the hold threshold, so cancelling that single PENDING
        row must recompute the sum to zero and drop the flag with no clock advance and no second
        request; and because the cancelled row is then immutable, a replay cannot drive the pair
        negative.

        PRD 2.11: "A driver's `pending_retro_correction_cents` is the signed sum of
        `delta_gross_cents` across that driver's retroactive corrections whose `status` is
        `PENDING`, with `APPLIED` and `CANCELLED` corrections excluded, and is 0 when there are
        none. `settlement_hold` is derived from it and recomputed on every change to it."
        PRD 3.9: "`settlement_hold`, which is true whenever the absolute value of
        `pending_retro_correction_cents` exceeds 50,000 cents and false otherwise".
        PRD 3.9: "Cancellation advances the correction `PENDING` → `CANCELLED`, stamps
        `cancelled_at` and records the acting `X-User-ID` as `cancelled_by_user_id`, recomputes
        the driver's `pending_retro_correction_cents` and therefore `settlement_hold`".
        PRD 2.9 rung 28: "`ERR_CORRECTION_NOT_PENDING` — the retroactive correction's `status` is
        `PENDING`; `APPLIED` and `CANCELLED` corrections are immutable."

        Design: Corner/cross_cutting_complexity_layers/cancelling_the_pending_correction_reconciles_the_hold_back_to_false
        """
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            revenue_bps=None,
            name="Leased Derived Reconcile",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Dev Derived",
            home_state="TX",
        )
        load = fixtures.delivered_load(driver["id"], practical_miles=1200, hhg_miles=250, stop_count=1)
        assert load["linehaul_pay_cents"] == 71700
        settlement = fixtures.paid_settlement(driver["id"], payment_reference="ACH-DRC-1")
        assert settlement["gross_pay_cents"] == 71700

        fixtures.set_clock("2026-08-11T09:00:00Z")
        dispute = fixtures.file_mileage_dispute(
            driver["id"],
            load["id"],
            MileageGuide.HHG,
            250,
            narrative="Routing was short-line.",
            evidence_doc_ref="doc://drc",
        )
        fixtures.review(dispute["id"], CLERK_HEADERS)
        upheld = fixtures.resolve(
            dispute["id"], "UPHOLD", APPROVER_HEADERS, resolution_note="Short-line confirmed."
        )
        assert upheld["status"] == DisputeStatus.UPHELD
        assert upheld["adjustment_cents"] == -57200
        correction_id = upheld["resolution_correction_id"]
        pending = fixtures.read_correction(correction_id)
        assert pending["status"] == CorrectionStatus.PENDING
        assert pending["correction_type"] == CorrectionType.MILEAGE_REGRADE
        assert pending["reason_code"] == CorrectionReasonCode.MILEAGE_DISPUTE_UPHELD
        assert pending["delta_gross_cents"] == -57200
        assert pending["applied_settlement_id"] is None
        held = fixtures.read_driver(driver["id"])
        assert held["pending_retro_correction_cents"] == -57200
        assert abs(held["pending_retro_correction_cents"]) > RETRO_HOLD_THRESHOLD_CENTS
        assert held["settlement_hold"] is True

        cancelled = validate_success(
            api_client.cancel_retro_correction(correction_id, ADMIN_HEADERS)
        )

        assert cancelled["status"] == CorrectionStatus.CANCELLED
        assert_timestamps_equal(cancelled["cancelled_at"], "2026-08-11T09:00:00Z", "cancelled_at")
        assert cancelled["cancelled_by_user_id"] == PAYROLL_ADMIN_ID
        released = fixtures.read_driver(driver["id"])
        assert released["pending_retro_correction_cents"] == 0
        assert released["settlement_hold"] is False

        replay = api_client.cancel_retro_correction(correction_id, ADMIN_HEADERS)

        validate_error(replay, ApiErrorId.CORRECTION_NOT_PENDING, 409)
        after = fixtures.read_driver(driver["id"])
        assert after["pending_retro_correction_cents"] == 0, "the refused replay double-counted nothing"
        assert after["settlement_hold"] is False

    def test_the_cancel_abandons_the_money_without_un_adjudicating_the_upheld_dispute(self):
        """The pay axis walks back to SETTLED, yet the re-graded 250 miles and 14,500 cents stay
        on the load while the paid statement keeps its 71,700 — a disagreement that is now
        permanent and correct.

        PRD 3.9: "If the cancelled correction had re-graded a load, that load's pay axis returns
        `ADJUSTED` → `SETTLED`, but its `applied_mileage_guide`, `base_guide_miles`, `paid_miles`,
        `linehaul_pay_cents` and `linehaul_line_type` stay at their re-graded values: cancelling
        the correction abandons the money movement, it does not un-adjudicate the upheld dispute."
        PRD 3.9: "This is precisely why a settlement's `linehaul_total_cents` on the original
        statement can permanently disagree with the `linehaul_pay_cents` now stored on the load"

        Design: Corner/cross_cutting_complexity_layers/cancelling_the_pending_correction_reconciles_the_hold_back_to_false
        """
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            revenue_bps=None,
            name="Leased Derived Reconcile",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Dev Derived",
            home_state="TX",
        )
        load = fixtures.delivered_load(driver["id"], practical_miles=1200, hhg_miles=250, stop_count=1)
        settlement = fixtures.paid_settlement(driver["id"], payment_reference="ACH-DRC-1")

        fixtures.set_clock("2026-08-11T09:00:00Z")
        dispute = fixtures.file_mileage_dispute(
            driver["id"],
            load["id"],
            MileageGuide.HHG,
            250,
            narrative="Routing was short-line.",
            evidence_doc_ref="doc://drc",
        )
        fixtures.review(dispute["id"], CLERK_HEADERS)
        upheld = fixtures.resolve(
            dispute["id"], "UPHOLD", APPROVER_HEADERS, resolution_note="Short-line confirmed."
        )
        adjusted = fixtures.read_load(load["id"])
        assert adjusted["pay_status"] == PayStatus.ADJUSTED

        validate_success(
            api_client.cancel_retro_correction(upheld["resolution_correction_id"], ADMIN_HEADERS)
        )

        walked_back = fixtures.read_load(load["id"])
        assert walked_back["pay_status"] == PayStatus.SETTLED
        assert walked_back["settlement_id"] == settlement["id"]
        assert walked_back["applied_mileage_guide"] == MileageGuide.HHG
        assert walked_back["base_guide_miles"] == 250
        assert walked_back["paid_miles"] == 250
        assert walked_back["linehaul_pay_cents"] == 14500

        statement = fixtures.read_settlement(settlement["id"])
        assert statement["status"] == SettlementStatus.PAID
        assert statement["linehaul_total_cents"] == 71700
        assert statement["gross_pay_cents"] == 71700
        lines = fixtures.read_settlement_lines(settlement["id"])
        linehaul = [line for line in lines if line["line_type"] == LineType.LINEHAUL_PER_MILE]
        assert len(linehaul) == 1
        assert linehaul[0]["amount_cents"] == 71700, "the settlement-line log is the statement of record"
        assert fixtures.read_dispute(dispute["id"])["status"] == DisputeStatus.UPHELD
