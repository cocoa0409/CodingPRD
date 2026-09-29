"""The cyclic dispute machine and the two independent state axes of a load.

A denied dispute is not finished, and a load's money axis keeps moving after its
movement axis has become terminal.
"""

from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    CLERK_HEADERS,
    ApiErrorId,
    api_client,
    fixtures,
    make_driver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    CorrectionStatus,
    CorrectionType,
    CorrectionReasonCode,
    DisputeStatus,
    DriverType,
    LineType,
    MileageGuide,
    MovementStatus,
    PayStatus,
    PerDiemMethod,
    SettlementStatus,
)

CLAIMED_MILES = 812
REGRADED_LINEHAUL_CENTS = 48032
ORIGINAL_LINEHAUL_CENTS = 46080
REGRADE_DELTA_CENTS = 1952


def _unsettled_dispute_environment():
    """A delivered but never-settled load with an OPEN mileage dispute claiming 812
    practical miles, filed by the driver five days into the month."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Dispute Cycle",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Gus Griever",
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1)
    assert load["linehaul_pay_cents"] == ORIGINAL_LINEHAUL_CENTS
    assert load["pay_status"] == PayStatus.ACCRUED

    fixtures.set_clock("2026-08-05T09:00:00Z")
    driver_headers = make_driver_headers(driver["id"])
    dispute = fixtures.file_mileage_dispute(
        driver["id"],
        load["id"],
        MileageGuide.PRACTICAL,
        CLAIMED_MILES,
        headers=driver_headers,
        evidence_doc_ref="doc://atlas-routing-812",
        narrative="Routed practical mileage was recorded short by 32 miles.",
    )
    return {
        "driver": driver,
        "driver_headers": driver_headers,
        "load": load,
        "dispute": dispute,
    }


def _deny_once(dispute_id: str, note: str) -> None:
    fixtures.review(dispute_id, CLERK_HEADERS)
    fixtures.resolve(dispute_id, "DENY", APPROVER_HEADERS, resolution_note=note)


class TestDeniedDisputeReopenCycle:
    """DENIED is not terminal, so the same row revisits OPEN and UNDER_REVIEW."""

    def test_walk_returns_to_visited_states_and_ends_upheld(self):
        """OPEN, UNDER_REVIEW, DENIED, OPEN, UNDER_REVIEW, UPHELD is a legal walk on one
        dispute row, and the second visit to OPEN carries reopen_count 1.

        PRD 3.9: "`DENIED` is not the end: the claimant may reopen it, which moves `DENIED`
        → `OPEN`, increments `reopen_count` by 1".

        Design: Difficulty/non_linear_state_machine/dispute_denied_reopen_cycle
        """
        env = _unsettled_dispute_environment()
        dispute_id = env["dispute"]["id"]
        assert env["dispute"]["status"] == DisputeStatus.OPEN
        assert env["dispute"]["reopen_count"] == 0

        under_review = validate_success(
            api_client.review_dispute(dispute_id, CLERK_HEADERS)
        )
        assert under_review["status"] == DisputeStatus.UNDER_REVIEW
        denied = validate_success(
            api_client.resolve_dispute(
                dispute_id,
                {"outcome": "DENY", "resolution_note": "Guide printout illegible."},
                APPROVER_HEADERS,
            )
        )
        assert denied["status"] == DisputeStatus.DENIED

        reopened = validate_success(
            api_client.reopen_dispute(
                dispute_id,
                {
                    "narrative": "Legible guide printout attached.",
                    "evidence_doc_ref": "doc://atlas-routing-812-v2",
                },
                env["driver_headers"],
            )
        )
        assert reopened["status"] == DisputeStatus.OPEN
        assert reopened["reopen_count"] == 1

        fixtures.review(dispute_id, CLERK_HEADERS)
        upheld = validate_success(
            api_client.resolve_dispute(
                dispute_id,
                {
                    "outcome": "UPHOLD",
                    "resolution_note": "Second printout confirms 812 practical miles.",
                },
                APPROVER_HEADERS,
            )
        )
        assert upheld["status"] == DisputeStatus.UPHELD
        assert upheld["reopen_count"] == 1

    def test_reopen_clears_the_first_pass_review_and_resolution_history(self):
        """The second visit to OPEN is a clean slate: the reviewer, the resolver and the
        resolution note recorded on the first pass are all back to null, and the reopen
        narrative has overwritten the original.

        PRD 3.9: "overwrites `narrative` with the reopen narrative and `evidence_doc_ref` with
        the reopen evidence reference when one is supplied, and clears `resolution_note`,
        `resolved_by_user_id` and `reviewed_by_user_id` back to null, bumping `version`."

        Design: Difficulty/non_linear_state_machine/dispute_denied_reopen_cycle
        """
        env = _unsettled_dispute_environment()
        dispute_id = env["dispute"]["id"]
        _deny_once(dispute_id, "Guide printout illegible.")
        denied = fixtures.read_dispute(dispute_id)
        assert denied["reviewed_by_user_id"] is not None
        assert denied["resolved_by_user_id"] is not None

        reopened = validate_success(
            api_client.reopen_dispute(
                dispute_id,
                {
                    "narrative": "Legible guide printout attached.",
                    "evidence_doc_ref": "doc://atlas-routing-812-v2",
                },
                env["driver_headers"],
            )
        )

        assert reopened["reviewed_by_user_id"] is None
        assert reopened["resolved_by_user_id"] is None
        assert reopened["resolution_note"] is None
        assert reopened["narrative"] == "Legible guide printout attached."
        assert reopened["evidence_doc_ref"] == "doc://atlas-routing-812-v2"
        assert reopened["version"] == denied["version"] + 1

    def test_third_reopen_is_refused_although_the_state_name_is_identical(self):
        """Two full cycles are permitted; the third reopen of the very same DENIED row is
        refused, so identical state names are not interchangeable.

        PRD 3.9: "Reopening is allowed only while `reopen_count` is strictly below 2, so the
        same dispute row may traverse `OPEN` → `UNDER_REVIEW` → `DENIED` → `OPEN` twice before
        a third attempt is rejected with `ERR_DISPUTE_REOPEN_LIMIT` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/dispute_denied_reopen_cycle
        """
        env = _unsettled_dispute_environment()
        dispute_id = env["dispute"]["id"]

        _deny_once(dispute_id, "First denial.")
        validate_success(
            api_client.reopen_dispute(
                dispute_id, {"narrative": "First reopen."}, env["driver_headers"]
            )
        )
        _deny_once(dispute_id, "Second denial.")
        second = validate_success(
            api_client.reopen_dispute(
                dispute_id, {"narrative": "Second reopen."}, env["driver_headers"]
            )
        )
        assert second["reopen_count"] == 2
        _deny_once(dispute_id, "Third denial.")

        response = api_client.reopen_dispute(
            dispute_id, {"narrative": "Third reopen."}, env["driver_headers"]
        )

        validate_error(response, ApiErrorId.DISPUTE_REOPEN_LIMIT, 409)
        still_denied = fixtures.read_dispute(dispute_id)
        assert still_denied["status"] == DisputeStatus.DENIED
        assert still_denied["reopen_count"] == 2

    def test_uphold_on_an_accrued_load_regrades_it_in_place_without_a_correction(self):
        """The load has not been paid, so the upheld miles are written straight onto it, the
        pay axis self-transitions and no retroactive correction is minted.

        PRD 3.9: "The pay axis takes the self-transition `ACCRUED` → `ACCRUED`, so the
        observable `pay_status` is unchanged, and **no correction is created**, because the next
        preparation will simply pick up the new numbers."

        Design: Difficulty/non_linear_state_machine/dispute_denied_reopen_cycle
        """
        env = _unsettled_dispute_environment()
        dispute_id = env["dispute"]["id"]
        _deny_once(dispute_id, "Guide printout illegible.")
        validate_success(
            api_client.reopen_dispute(
                dispute_id, {"narrative": "Legible printout."}, env["driver_headers"]
            )
        )
        fixtures.review(dispute_id, CLERK_HEADERS)

        upheld = fixtures.resolve(
            dispute_id, "UPHOLD", APPROVER_HEADERS, resolution_note="812 confirmed."
        )

        assert upheld["resolution_correction_id"] is None
        assert upheld["adjustment_cents"] == REGRADE_DELTA_CENTS

        load = fixtures.read_load(env["load"]["id"])
        assert load["applied_mileage_guide"] == MileageGuide.PRACTICAL
        assert load["base_guide_miles"] == CLAIMED_MILES
        assert load["paid_miles"] == CLAIMED_MILES
        assert load["linehaul_pay_cents"] == REGRADED_LINEHAUL_CENTS
        assert load["pay_status"] == PayStatus.ACCRUED
        assert load["movement_status"] == MovementStatus.DELIVERED

        corrections, meta = validate_paginated(
            api_client.list_retro_corrections(ADMIN_HEADERS, {"source_dispute_id": dispute_id})
        )
        assert meta["total_count"] == 0
        assert corrections == []


def _settled_dispute_environment():
    """The same load, but paid out on a settlement, with a mileage dispute claiming 812
    practical miles already UNDER_REVIEW two days after payment."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Parallel Axes",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Hal Hauler",
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1)
    fixtures.set_clock(fixtures.TS_SETTLE)
    settlement = fixtures.open_settlement(driver["id"])
    fixtures.prepare(settlement["id"])
    fixtures.approve(settlement["id"])
    fixtures.set_clock("2026-08-10T10:00:00Z")
    fixtures.pay(settlement["id"], "ACH-2026-08-10-0001")
    settled_load = fixtures.read_load(load["id"])
    assert settled_load["pay_status"] == PayStatus.SETTLED

    fixtures.set_clock("2026-08-12T09:00:00Z")
    driver_headers = make_driver_headers(driver["id"])
    dispute = fixtures.file_mileage_dispute(
        driver["id"],
        load["id"],
        MileageGuide.PRACTICAL,
        CLAIMED_MILES,
        headers=driver_headers,
        narrative="Practical mileage short by 32 miles on an already paid settlement.",
    )
    fixtures.review(dispute["id"], CLERK_HEADERS)
    return {
        "driver": driver,
        "load": settled_load,
        "settlement": settlement,
        "dispute": dispute,
    }


class TestLoadMovementAndPayAxesMoveIndependently:
    """One row, two axes: the movement axis is frozen while the money axis walks on."""

    def test_movement_axis_stays_terminal_while_the_pay_axis_reaches_adjusted(self):
        """Upholding the dispute drives the pay axis SETTLED to ADJUSTED and leaves the
        movement axis exactly where delivery left it, a combination a single status column
        could not express.

        PRD 3.4: "Once a load reaches `DELIVERED` the movement axis is terminal and neither
        dispatch nor delivery may fire again, while the pay axis keeps moving underneath it for
        as long as the money keeps moving."
        PRD 3.9: "Hop 1: the load's pay fields are rewritten exactly as in branch A and its pay
        axis moves `SETTLED` → `ADJUSTED`, while `movement_status` stays `DELIVERED` and is not
        touched."

        Design: Difficulty/non_linear_state_machine/load_movement_pay_parallel_axes_adjusted
        """
        env = _settled_dispute_environment()

        fixtures.resolve(
            env["dispute"]["id"],
            "UPHOLD",
            APPROVER_HEADERS,
            resolution_note="Guide corrected to 812 practical miles.",
        )

        load = fixtures.read_load(env["load"]["id"])
        assert load["movement_status"] == MovementStatus.DELIVERED
        assert load["pay_status"] == PayStatus.ADJUSTED
        assert load["settlement_id"] == env["settlement"]["id"]
        assert load["paid_miles"] == CLAIMED_MILES
        assert load["linehaul_pay_cents"] == REGRADED_LINEHAUL_CENTS

    def test_the_settled_branch_mints_a_pending_correction_rather_than_re_grading_the_statement(
        self,
    ):
        """Because the money has already gone out, the pay-side branch chosen by pay_status is
        the correction branch, and the resulting record is PENDING with a +1952 delta.

        PRD 3.9: "Hop 2: that load mutation itself creates a retroactive correction in `PENDING`
        status with `correction_type` `MILEAGE_REGRADE`, `reason_code` `MILEAGE_DISPUTE_UPHELD`".
        PRD 3.9: "for every other method `delta_taxable_cents` equals `delta_gross_cents`."

        Design: Difficulty/non_linear_state_machine/load_movement_pay_parallel_axes_adjusted
        """
        env = _settled_dispute_environment()

        upheld = fixtures.resolve(
            env["dispute"]["id"],
            "UPHOLD",
            APPROVER_HEADERS,
            resolution_note="Guide corrected to 812 practical miles.",
        )

        assert upheld["status"] == DisputeStatus.UPHELD
        assert upheld["adjustment_cents"] == REGRADE_DELTA_CENTS
        correction_id = upheld["resolution_correction_id"]
        assert correction_id is not None

        correction = fixtures.read_correction(correction_id)
        assert correction["status"] == CorrectionStatus.PENDING
        assert correction["correction_type"] == CorrectionType.MILEAGE_REGRADE
        assert correction["reason_code"] == CorrectionReasonCode.MILEAGE_DISPUTE_UPHELD
        assert correction["delta_gross_cents"] == REGRADE_DELTA_CENTS
        assert correction["delta_taxable_cents"] == REGRADE_DELTA_CENTS
        assert correction["origin_settlement_id"] == env["settlement"]["id"]
        assert correction["applied_settlement_id"] is None
        assert correction["source_load_id"] == env["load"]["id"]
        assert correction["source_dispute_id"] == env["dispute"]["id"]

    def test_the_paid_statement_keeps_its_original_amounts_and_the_driver_carries_the_delta(
        self,
    ):
        """The statement of record is frozen at 46080 even though the load now reads 48032, and
        the unpaid difference sits on the driver as a pending correction below the hold
        threshold.

        PRD 3.9: "This is precisely why a settlement's `linehaul_total_cents` on the original
        statement can permanently disagree with the `linehaul_pay_cents` now stored on the
        load".
        PRD 3.9: "`settlement_hold`, which is true whenever the absolute value of
        `pending_retro_correction_cents` exceeds 50,000 cents and false otherwise".

        Design: Difficulty/non_linear_state_machine/load_movement_pay_parallel_axes_adjusted
        """
        env = _settled_dispute_environment()

        fixtures.resolve(
            env["dispute"]["id"],
            "UPHOLD",
            APPROVER_HEADERS,
            resolution_note="Guide corrected to 812 practical miles.",
        )

        settlement = fixtures.read_settlement(env["settlement"]["id"])
        assert settlement["status"] == SettlementStatus.PAID
        assert settlement["gross_pay_cents"] == ORIGINAL_LINEHAUL_CENTS
        assert settlement["linehaul_total_cents"] == ORIGINAL_LINEHAUL_CENTS

        lines = fixtures.read_settlement_lines(env["settlement"]["id"])
        linehaul_lines = [
            line for line in lines if line["line_type"] == LineType.LINEHAUL_PER_MILE
        ]
        assert len(linehaul_lines) == 1
        assert linehaul_lines[0]["amount_cents"] == ORIGINAL_LINEHAUL_CENTS

        driver = fixtures.read_driver(env["driver"]["id"])
        assert driver["pending_retro_correction_cents"] == REGRADE_DELTA_CENTS
        assert driver["settlement_hold"] is False
