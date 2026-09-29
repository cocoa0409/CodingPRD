"""Declared transitions, undeclared ones, terminal states and the two independent axes.

Every assertion here is about a source state: the same request that is refused now becomes
legal once the record is moved, and a refused transition writes nothing at all.
"""

from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    CLERK_HEADERS,
    ApiErrorId,
    api_client,
    assert_timestamps_equal,
    factories,
    fixtures,
    make_driver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    AccessorialType,
    AdvanceStatus,
    AdvanceType,
    ClaimStatus,
    DisputeStatus,
    DriverType,
    EmploymentStatus,
    EscrowStatus,
    LineType,
    MileageGuide,
    MovementStatus,
    PayStatus,
    PerDiemMethod,
    RejectReasonCode,
    SettlementStatus,
    VoidReasonCode,
)


def _assigned_but_onboarding_driver(name: str, legal_name: str):
    """An ACTIVE per-mile package with a driver assigned to it but still ONBOARDING."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name=name,
    )
    driver = fixtures.create_driver(
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name=legal_name,
        home_state="TX",
    )
    validate_success(
        api_client.assign_pay_package(
            driver["id"], factories.assign_package_payload(package["id"]), ADMIN_HEADERS
        )
    )
    return package, fixtures.read_driver(driver["id"])


class TestDriverEmploymentAxis:
    """Four statuses, one status-setting operation, and an escrow axis that ignores it."""

    def test_a_new_driver_starts_onboarding_with_no_package_and_zeroed_accumulators(self):
        """Registration is the base case every later invariant builds on, so the balances and
        year-to-date accumulators must read 0 rather than null.

        PRD 3.2: "A new driver begins on the employment axis in `ONBOARDING` with no
        `pay_package_id`, on the escrow axis in `NOT_REQUIRED`, with every balance and
        year-to-date accumulator at 0, `settlement_hold` false, and `terminated_at`,
        `escrow_funded_at`, `escrow_return_due_at` and `escrow_returned_at` all null."

        Design: Corner/state_machines/newly_created_driver_starts_onboarding_with_no_package_and_zeroed_accumulators
        """
        fixtures.reset_clock()

        driver = validate_success(
            api_client.create_driver(
                factories.driver_payload(
                    legal_name="Ivy Initial",
                    driver_type=DriverType.OWNER_OPERATOR,
                    home_state="TX",
                    per_diem_elected=False,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert driver["version"] == 1
        assert driver["employment_status"] == EmploymentStatus.ONBOARDING
        assert driver["pay_package_id"] is None
        assert driver["escrow_status"] == EscrowStatus.NOT_REQUIRED
        assert driver["escrow_balance_cents"] == 0
        assert driver["escrow_target_cents"] == 0
        assert driver["ytd_gross_pay_cents"] == 0
        assert driver["ytd_taxable_wages_cents"] == 0
        assert driver["ytd_per_diem_non_taxable_cents"] == 0
        assert driver["advance_outstanding_cents"] == 0
        assert driver["pending_retro_correction_cents"] == 0
        assert driver["settlement_hold"] is False
        assert driver["terminated_at"] is None
        assert driver["escrow_funded_at"] is None
        assert driver["escrow_return_due_at"] is None
        assert driver["escrow_returned_at"] is None

    def test_activation_moves_only_the_employment_axis_and_bumps_the_version(self):
        """The third write to the driver row is the activation, so the version reads 3, and the
        escrow axis is untouched because the package required no escrow.

        PRD 3.2: "`ONBOARDING` → `ACTIVE` requires the driver's assigned package to be `ACTIVE`,
        which is why a driver with no package cannot be activated."
        PRD 3.2: "Every one of these moves increments the driver's `version` by 1".

        Design: Corner/state_machines/driver_status_onboarding_to_active_sets_the_employment_axis
        """
        fixtures.reset_clock()
        package, driver = _assigned_but_onboarding_driver(
            "Leased Activation", "Ada Activate"
        )
        assert driver["employment_status"] == EmploymentStatus.ONBOARDING
        assert driver["version"] == 2, "creation then assignment are the first two writes"

        activated = validate_success(
            api_client.set_driver_status(
                driver["id"],
                factories.driver_status_payload(EmploymentStatus.ACTIVE),
                ADMIN_HEADERS,
            )
        )

        assert activated["employment_status"] == EmploymentStatus.ACTIVE
        assert activated["pay_package_id"] == package["id"]
        assert activated["escrow_status"] == EscrowStatus.NOT_REQUIRED
        assert activated["terminated_at"] is None
        assert activated["version"] == 3

    def test_suspension_is_reachable_from_active_only(self):
        """The very same request that is refused against an ONBOARDING driver succeeds once the
        driver is ACTIVE, which shows the refusal was about the source state.

        PRD 3.2: "An `ACTIVE` driver may be suspended, `ACTIVE` → `SUSPENDED`".
        PRD 3.2: "a `new_status` that is not reachable from the current `employment_status` along
        that axis is rejected with `ERR_DRIVER_NOT_ACTIVE` (HTTP 409)".

        Design: Corner/state_machines/driver_status_onboarding_to_suspended_is_not_a_declared_transition
        """
        fixtures.reset_clock()
        _package, driver = _assigned_but_onboarding_driver(
            "Leased Suspend Probe", "Sal Suspend"
        )

        premature = api_client.set_driver_status(
            driver["id"],
            factories.driver_status_payload(EmploymentStatus.SUSPENDED),
            ADMIN_HEADERS,
        )
        validate_error(premature, ApiErrorId.DRIVER_NOT_ACTIVE, 409)
        assert (
            fixtures.read_driver(driver["id"])["employment_status"]
            == EmploymentStatus.ONBOARDING
        )

        fixtures.set_driver_status(driver["id"], EmploymentStatus.ACTIVE)
        suspended = validate_success(
            api_client.set_driver_status(
                driver["id"],
                factories.driver_status_payload(EmploymentStatus.SUSPENDED),
                ADMIN_HEADERS,
            )
        )

        assert suspended["employment_status"] == EmploymentStatus.SUSPENDED

    def test_termination_is_terminal_in_both_directions(self):
        """Neither reactivation nor suspension is reachable from TERMINATED, and the stamp of the
        one real transition survives both refused attempts.

        PRD 3.2: "`TERMINATED` is terminal on the employment axis."
        PRD 3.2: "which sets `employment_status` to `TERMINATED` and stamps `terminated_at` —
        from the request body when supplied, otherwise from the logical clock".

        Design: Corner/state_machines/terminated_driver_cannot_be_reactivated_or_suspended
        """
        fixtures.reset_clock()
        _package, driver = _assigned_but_onboarding_driver(
            "Leased Terminal Probe", "Tom Terminal"
        )
        fixtures.set_driver_status(driver["id"], EmploymentStatus.ACTIVE)
        fixtures.set_clock("2026-08-06T12:00:00Z")
        fixtures.set_driver_status(driver["id"], EmploymentStatus.TERMINATED)

        reactivate = api_client.set_driver_status(
            driver["id"],
            factories.driver_status_payload(EmploymentStatus.ACTIVE),
            ADMIN_HEADERS,
        )
        resuspend = api_client.set_driver_status(
            driver["id"],
            factories.driver_status_payload(EmploymentStatus.SUSPENDED),
            ADMIN_HEADERS,
        )

        validate_error(reactivate, ApiErrorId.DRIVER_NOT_ACTIVE, 409)
        validate_error(resuspend, ApiErrorId.DRIVER_NOT_ACTIVE, 409)
        final = fixtures.read_driver(driver["id"])
        assert final["employment_status"] == EmploymentStatus.TERMINATED
        assert_timestamps_equal(final["terminated_at"], "2026-08-06T12:00:00Z")
        assert final["escrow_status"] == EscrowStatus.NOT_REQUIRED


def _tendered_load(name: str, legal_name: str):
    """An ACTIVE driver with one load tendered and not yet dispatched."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name=name,
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name=legal_name,
        home_state="TX",
    )
    load = fixtures.tender_load(driver["id"], stop_count=1)
    return package, driver, load


class TestLoadMovementAxis:
    """Delivery has a precondition, dispatch is not idempotent, and the snapshot is pinned."""

    def test_delivering_a_tendered_load_is_refused_and_computes_no_pay(self):
        """Skipping dispatch is refused, and the refusal must not run the pay computation: the
        pay fields stay null and the pay axis stays UNPAID rather than jumping to ACCRUED.

        PRD 2.9 rung 22: "`ERR_LOAD_NOT_DELIVERED` — the load's `movement_status` is the one the
        operation needs: `TENDERED` to dispatch, `IN_TRANSIT` to deliver".
        PRD 3.4: "Before delivery, `applied_mileage_guide`, `base_guide_miles`, `paid_miles`,
        `linehaul_pay_cents` and `linehaul_line_type` are all null."

        Design: Corner/state_machines/deliver_before_dispatch_is_rejected_and_pay_axis_stays_unpaid
        """
        fixtures.reset_clock()
        _package, _driver, load = _tendered_load(
            "Leased Deliver Precondition", "Pia Precondition"
        )

        response = api_client.deliver_load(
            load["id"], factories.deliver_payload(), ADMIN_HEADERS
        )

        validate_error(response, ApiErrorId.LOAD_NOT_DELIVERED, 409)
        stored = fixtures.read_load(load["id"])
        assert stored["movement_status"] == MovementStatus.TENDERED
        assert stored["pay_status"] == PayStatus.UNPAID
        assert stored["paid_miles"] is None
        assert stored["linehaul_pay_cents"] is None
        assert stored["delivered_at"] is None

    def test_a_second_dispatch_is_refused_and_does_not_restamp_the_first(self):
        """Dispatch is not idempotent: the second call finds the load IN_TRANSIT and the stored
        instant stays the one from the first dispatch even though the clock has moved on.

        PRD 3.4: "Dispatching a tendered load advances `TENDERED` → `IN_TRANSIT`, sets
        `dispatched_at` from the optional `dispatched_at` in the request body or from the logical
        clock when it is omitted".
        PRD 2.9 rung 22: "`TENDERED` to dispatch".

        Design: Corner/state_machines/dispatching_the_same_load_twice_is_rejected_on_the_second_call
        """
        fixtures.reset_clock()
        package, _driver, load = _tendered_load("Leased Idempotency", "Ivo Idempotent")
        fixtures.set_clock("2026-08-03T08:00:00Z")
        fixtures.dispatch(load["id"])
        fixtures.set_clock("2026-08-03T15:00:00Z")

        response = api_client.dispatch_load(
            load["id"], factories.dispatch_payload(), ADMIN_HEADERS
        )

        validate_error(response, ApiErrorId.LOAD_NOT_DELIVERED, 409)
        stored = fixtures.read_load(load["id"])
        assert stored["movement_status"] == MovementStatus.IN_TRANSIT
        assert_timestamps_equal(stored["dispatched_at"], "2026-08-03T08:00:00Z")
        assert stored["pay_package_id_snapshot"] == package["id"]

    def test_delivery_pays_from_the_pinned_snapshot_not_the_drivers_current_package(self):
        """Reassigning the driver mid-haul to a 120 cents-per-mile package leaves the load paying
        46080 from the 58-cent package it was dispatched under, not 93600 and not 72000.

        PRD 3.4: "Dispatching a tendered load advances `TENDERED` → `IN_TRANSIT` ... and — the
        critical act — **pins** `pay_package_id_snapshot` to the driver's current
        `pay_package_id`."
        PRD 3.4: "`applied_mileage_guide` is taken from the `mileage_guide` of the package in
        `pay_package_id_snapshot`".

        Design: Corner/state_machines/dispatch_pins_the_package_snapshot_and_a_later_reassignment_cannot_move_it
        """
        fixtures.reset_clock()
        original, driver, load = _tendered_load("Leased Snapshot Original", "Sven Snapshot")
        fixtures.set_clock("2026-08-03T08:00:00Z")
        fixtures.dispatch(load["id"])
        replacement = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            per_mile_rate=120,
            revenue_bps=4000,
            name="Leased Snapshot Replacement",
        )
        validate_success(
            api_client.assign_pay_package(
                driver["id"],
                factories.assign_package_payload(replacement["id"]),
                ADMIN_HEADERS,
            )
        )

        fixtures.set_clock(fixtures.TS_DELIVER)
        delivered = validate_success(
            api_client.deliver_load(load["id"], factories.deliver_payload(), ADMIN_HEADERS)
        )

        assert delivered["pay_package_id_snapshot"] == original["id"]
        assert delivered["pay_package_id_snapshot"] != replacement["id"]
        assert delivered["paid_miles"] == 780
        assert delivered["linehaul_pay_cents"] == 46080, (
            "the pinned 58-cent package pays 46080, not 93600 at 120 cents and not 72000 at 4000 bps"
        )
        assert delivered["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE
        assert delivered["pay_status"] == PayStatus.ACCRUED
        assert fixtures.read_driver(driver["id"])["pay_package_id"] == replacement["id"]


class TestAccessorialClaimAxis:
    """REJECTED is reachable from SUBMITTED alone."""

    def test_rejecting_an_approved_claim_is_refused_and_keeps_the_priced_amount(self):
        """The claim is APPROVED and carries no settlement yet, so the refusal is the claim-state
        rung rather than the already-settled rung, and the computed 7500 survives.

        PRD 2.9 rung 49: "`ERR_CLAIM_NOT_SUBMITTED` — the accessorial claim's `status` is
        `SUBMITTED` to approve and to reject".
        PRD 3.5: "**`TARPING`.** Tarping is a flat event: `billable_units` is 1 and `amount_cents`
        is 7,500 cents."

        Design: Corner/state_machines/rejecting_an_already_approved_claim_is_not_a_declared_transition
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Claim Lifecycle",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Cara Claim",
            home_state="TX",
        )
        load = fixtures.delivered_load(driver["id"], stop_count=1, tarp_required=True)
        fixtures.set_clock("2026-08-06T09:00:00Z")
        claim = fixtures.submit_claim(
            load["id"],
            driver["id"],
            AccessorialType.TARPING,
            "2026-08-04T10:00:00Z",
            "2026-08-04T11:00:00Z",
            "doc://tarp-cara",
            CLERK_HEADERS,
        )
        approved = validate_success(
            api_client.approve_accessorial_claim(claim["id"], CLERK_HEADERS)
        )
        assert approved["status"] == ClaimStatus.APPROVED
        assert approved["settlement_id"] is None

        response = api_client.reject_accessorial_claim(
            claim["id"],
            factories.claim_reject_payload(RejectReasonCode.OUTSIDE_POLICY),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.CLAIM_NOT_SUBMITTED, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.CLAIM_ALREADY_SETTLED, (
            "the claim carries no settlement_id, so the already-settled rung cannot be the one"
        )
        stored = fixtures.read_claim(claim["id"])
        assert stored["status"] == ClaimStatus.APPROVED
        assert stored["amount_cents"] == 7500
        assert stored["billable_units"] == 1
        assert stored["reject_reason_code"] is None


def _draft_settlement_environment(name: str, legal_name: str):
    """A delivered load and a DRAFT settlement covering it, opened by the clerk."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name=name,
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name=legal_name,
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1)
    fixtures.set_clock(fixtures.TS_SETTLE)
    settlement = fixtures.open_settlement(driver["id"])
    return driver, load, settlement


class TestSettlementAxis:
    """APPROVED comes only from PREPARED, and both PAID and VOIDED are terminal."""

    def test_approving_a_draft_settlement_is_refused_before_the_duties_check(self):
        """The approver identity differs from every preparer — there is no preparer yet — so the
        refusal is the state rung and not the segregation-of-duties rung, and nothing is stamped.

        PRD 2.9 rung 24: "`ERR_SETTLEMENT_STATE_INVALID` — the settlement's `status` is `DRAFT`
        to sweep corrections and to prepare, `PREPARED` to approve, `APPROVED` to pay."
        PRD 3.7: "At creation the settlement's `status` is `DRAFT`, its `line_count` is 0, every
        money total is 0, `prepared_by_user_id`, `approved_by_user_id`, `prepared_at`,
        `approved_at`, `paid_at`, `voided_at`, `payment_reference` and `void_reason_code` are all
        null".

        Design: Corner/state_machines/approving_a_draft_settlement_is_rejected_before_any_segregation_check
        """
        fixtures.reset_clock()
        _driver, _load, settlement = _draft_settlement_environment(
            "Leased Settlement State", "Stan State"
        )
        assert settlement["prepared_by_user_id"] is None

        response = api_client.approve_settlement(settlement["id"], APPROVER_HEADERS)

        validate_error(response, ApiErrorId.SETTLEMENT_STATE_INVALID, 409)
        stored = fixtures.read_settlement(settlement["id"])
        assert stored["status"] == SettlementStatus.DRAFT
        assert stored["approved_by_user_id"] is None
        assert stored["approved_at"] is None
        assert stored["line_count"] == 0
        assert stored["gross_pay_cents"] == 0

    def test_voiding_an_already_voided_settlement_hits_the_terminal_rung(self):
        """The second void is refused by the terminal rung rather than the state rung, and the
        reason code and stamp written by the first void are preserved.

        PRD 2.9 rung 25: "`ERR_SETTLEMENT_TERMINAL` — the settlement is not already `PAID` or
        `VOIDED`; both are terminal and accept no further transition, void included."
        PRD 3.8: "Every void advances the settlement `DRAFT` → `VOIDED`, `PREPARED` → `VOIDED` or
        `APPROVED` → `VOIDED` as the case may be, stamps `voided_at`, records the
        `void_reason_code` and increments `version` by 1".

        Design: Corner/state_machines/voiding_an_already_voided_settlement_hits_the_terminal_guard
        """
        fixtures.reset_clock()
        _driver, _load, settlement = _draft_settlement_environment(
            "Leased Void Twice", "Vera Void"
        )
        voided = validate_success(
            api_client.void_settlement(
                settlement["id"],
                factories.void_payload(VoidReasonCode.WRONG_PERIOD),
                ADMIN_HEADERS,
            )
        )
        assert voided["status"] == SettlementStatus.VOIDED
        assert_timestamps_equal(voided["voided_at"], fixtures.TS_SETTLE)

        response = api_client.void_settlement(
            settlement["id"],
            factories.void_payload(VoidReasonCode.CLERICAL_ERROR),
            ADMIN_HEADERS,
        )

        validate_error(response, ApiErrorId.SETTLEMENT_TERMINAL, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.SETTLEMENT_STATE_INVALID
        stored = fixtures.read_settlement(settlement["id"])
        assert stored["status"] == SettlementStatus.VOIDED
        assert stored["void_reason_code"] == VoidReasonCode.WRONG_PERIOD
        assert_timestamps_equal(stored["voided_at"], fixtures.TS_SETTLE)


class TestDisputeWithdrawal:
    """WITHDRAWN is terminal in a way DENIED is not."""

    def test_withdrawal_keeps_the_review_history_and_locks_the_dispute(self):
        """The withdrawal writes no correction and touches no load, keeps the reviewer as
        history, and a following review is refused — the difference from a denial.

        PRD 3.9: "Withdrawal, available to the `Driver` or a `PayrollAdmin` from either `OPEN` or
        `UNDER_REVIEW`, advances the dispute `OPEN` → `WITHDRAWN` or `UNDER_REVIEW` →
        `WITHDRAWN` and increments `version`; any `reviewed_by_user_id` already recorded is
        retained as history, no correction is ever created by a withdrawal, and no load's pay axis
        is touched."
        PRD 3.9: "`WITHDRAWN` is terminal — a withdrawn dispute can never be reviewed, resolved or
        reopened, which is exactly what distinguishes it from `DENIED`."

        Design: Corner/state_machines/withdrawing_an_under_review_dispute_locks_it_against_further_review
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Withdrawal",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Wanda Withdraw",
            home_state="TX",
        )
        load = fixtures.delivered_load(driver["id"], stop_count=1)
        fixtures.set_clock("2026-08-06T09:00:00Z")
        driver_headers = make_driver_headers(driver["id"])
        dispute = fixtures.file_mileage_dispute(
            driver["id"],
            load["id"],
            MileageGuide.PRACTICAL,
            812,
            headers=driver_headers,
        )
        reviewed = fixtures.review(dispute["id"], CLERK_HEADERS)
        assert reviewed["status"] == DisputeStatus.UNDER_REVIEW
        assert reviewed["reviewed_by_user_id"] is not None

        withdrawn = validate_success(
            api_client.withdraw_dispute(dispute["id"], driver_headers)
        )

        assert withdrawn["status"] == DisputeStatus.WITHDRAWN
        assert withdrawn["reviewed_by_user_id"] == reviewed["reviewed_by_user_id"]
        assert withdrawn["resolution_correction_id"] is None
        _corrections, meta = validate_paginated(
            api_client.list_retro_corrections(ADMIN_HEADERS, {"driver_id": driver["id"]})
        )
        assert meta["total_count"] == 0
        stored_load = fixtures.read_load(load["id"])
        assert stored_load["pay_status"] == PayStatus.ACCRUED
        assert stored_load["paid_miles"] == 780

        second_review = api_client.review_dispute(dispute["id"], CLERK_HEADERS)
        validate_error(second_review, ApiErrorId.DISPUTE_STATE_INVALID, 409)


class TestAdvanceAxis:
    """The money follows the recovery lines; the status axis waits for approval."""

    def test_the_advance_status_moves_at_approval_and_then_refuses_cancellation(self):
        """Preparation allocates min(20000, 100000, 11520) and books it against the advance, but
        the advance is still ISSUED; approval is what moves it to RECOVERING, after which the
        cancellation that would have been legal a moment earlier is refused.

        PRD 3.6: "`recovered_cents` and `outstanding_cents` follow the recovery lines as soon as
        they exist on a settlement that is `PREPARED`, `APPROVED` or `PAID`, while the `status`
        axis advances when the settlement is approved".
        PRD 2.9 rung 27: "`ERR_ADVANCE_NOT_CANCELLABLE` — the advance's `status` is `ISSUED`; once
        recovery has begun or finished it can no longer be cancelled."

        Design: Corner/state_machines/advance_moves_issued_to_recovering_at_approve_and_can_no_longer_be_cancelled
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Advance Axis",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Abe Advance",
            home_state="TX",
        )
        fixtures.delivered_load(driver["id"], stop_count=1)
        advance = fixtures.issue_advance(
            driver["id"], 100000, AdvanceType.CASH_ADVANCE, installment_cents=20000
        )
        assert advance["status"] == AdvanceStatus.ISSUED
        fixtures.set_clock(fixtures.TS_SETTLE)
        settlement = fixtures.open_settlement(driver["id"])

        prepared = validate_success(
            api_client.prepare_settlement(settlement["id"], None, CLERK_HEADERS)
        )
        assert prepared["gross_pay_cents"] == 46080
        assert prepared["advance_recovery_cents"] == 11520, (
            "the 25 percent cap of 46080 binds below the 20000 installment"
        )
        assert prepared["net_pay_cents"] == 34560
        after_prepare = fixtures.read_advance(advance["id"])
        assert after_prepare["status"] == AdvanceStatus.ISSUED, (
            "the status axis waits for approval even though the money has already moved"
        )
        assert after_prepare["recovered_cents"] == 11520
        assert after_prepare["outstanding_cents"] == 88480

        validate_success(api_client.approve_settlement(settlement["id"], APPROVER_HEADERS))

        recovering = fixtures.read_advance(advance["id"])
        assert recovering["status"] == AdvanceStatus.RECOVERING
        assert recovering["recovered_cents"] == 11520
        assert recovering["outstanding_cents"] == 88480

        response = api_client.cancel_advance(advance["id"], ADMIN_HEADERS)

        validate_error(response, ApiErrorId.ADVANCE_NOT_CANCELLABLE, 409)
        unchanged = fixtures.read_advance(advance["id"])
        assert unchanged["status"] == AdvanceStatus.RECOVERING
        assert unchanged["recovered_cents"] == 11520
        assert fixtures.read_driver(driver["id"])["advance_outstanding_cents"] == 88480
