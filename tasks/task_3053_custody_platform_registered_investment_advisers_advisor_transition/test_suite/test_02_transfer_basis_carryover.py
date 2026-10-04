"""Asset transfers, lot grading and cost-basis carryover."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error_is_one_of,
    NON_EXISTENT_UUID,
    TEST_USERS,
    setup_transfer_variant_pair,
    setup_chronological_ordering_scenario,
    setup_account_in_basis_review,
    setup_funded_household,
    refetch_account,
    refetch_household,
    refetch_transfer,
)
"""Asset transfers, lot grading and cost-basis carryover."""
"""Asset transfers, lot grading and cost-basis carryover."""

ADVISOR = TEST_USERS["advisor_ops_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]


def _lots(transfer_id):
    return validate_success(api_client.list_transfer_lots(transfer_id, ADVISOR), 200)


class TestCarryoverVariants:

    def test_acat_delivery_carries_only_the_high_grade_basis(self):
        """PRD §3.3: "A firm-to-firm delivery — an `ACAT` or `DTC_NON_ACAT` transfer
        — grades every lot and carries only the `HIGH`-graded basis, leaving
        `MEDIUM`, `LOW` and `NONE` lots uncosted."
        PRD §3.3: "The transfer's `carryover_cents` is the sum of
        `sent_cost_basis_cents` over its `HIGH`-graded lots only, and
        `cost_basis_complete` is true exactly when every received position was
        stamped with a `HIGH`-confidence basis."

        Design: Difficulty/dual_variant_calc/transfer_basis_graded_vs_full_carryover_variant
        """
        scenario = setup_transfer_variant_pair()
        graded = scenario["graded_transfer"]
        assert graded["transfer_status"] == "CREDITED"
        assert graded["sent_basis_confidence"] == "HIGH"
        assert graded["carryover_cents"] == 1_200_000
        # The MEDIUM-graded BND lot carries a larger reported basis but is uncosted,
        # and not every received position was HIGH, so the package is incomplete.
        assert graded["cost_basis_complete"] is False

        lots = {lot["symbol"]: lot for lot in _lots(graded["id"])}
        assert lots["VTI"]["basis_confidence_grade"] == "HIGH"
        assert lots["BND"]["basis_confidence_grade"] == "MEDIUM"

    def test_rollover_carries_every_reported_basis_regardless_of_grade(self):
        """PRD §3.3: "A `DIRECT_ROLLOVER`, by contrast, carries every non-null
        reported basis regardless of grade, and a rollover lot is never downgraded
        to `LOW` because rollovers are exempt from the double-basis suspicion."

        Design: Difficulty/dual_variant_calc/transfer_basis_graded_vs_full_carryover_variant
        """
        scenario = setup_transfer_variant_pair()
        rollover = scenario["rollover_transfer"]
        graded = scenario["graded_transfer"]

        assert rollover["transfer_status"] == "CREDITED"
        assert rollover["sent_basis_confidence"] == "HIGH"
        assert rollover["carryover_cents"] == 3_600_000
        assert rollover["carryover_cents"] - graded["carryover_cents"] == 2_400_000


class TestChronologicalGrading:

    def test_grading_follows_lot_inventory_date_not_posting_order(self):
        """PRD §3.3: "The transfer's lots are processed in ascending
        `lot_inventory_date`, with `symbol` ascending as the tie-break."
        PRD §3.3: "Otherwise, if the lot's `lot_inventory_date` precedes the instant
        at which the transfer was submitted, the lot grades `HIGH`; any other lot
        with a non-null reported basis grades `MEDIUM`."

        Design: Difficulty/combinatorial_formula/carryover_chronological_grading_order
        """
        scenario = setup_chronological_ordering_scenario()
        transfer = scenario["transfer"]
        assert transfer["carryover_cents"] == 1_200_000
        assert transfer["sent_basis_confidence"] == "HIGH"
        assert transfer["cost_basis_complete"] is False
        # The larger 2400000-cent BND lot grades MEDIUM and is therefore not carried.
        assert transfer["carryover_cents"] != 3_600_000

        lots = {lot["symbol"]: lot for lot in _lots(transfer["id"])}
        assert lots["VTI"]["basis_confidence_grade"] == "HIGH"
        assert lots["VTI"]["lot_inventory_date"] == "2020-01-02T00:00:00Z"
        assert lots["BND"]["basis_confidence_grade"] == "MEDIUM"
        assert lots["BND"]["lot_inventory_date"] == "2027-01-02T00:00:00Z"

    def test_grades_are_independent_of_the_order_lots_were_posted_in(self):
        """PRD §3.3: "The transfer's lots are processed in ascending
        `lot_inventory_date`, with `symbol` ascending as the tie-break."
        PRD §3.3: "if the lot's `lot_inventory_date` precedes the instant at which
        the transfer was submitted, the lot grades `HIGH`; any other lot with a
        non-null reported basis grades `MEDIUM`."

        Design: Difficulty/combinatorial_formula/carryover_chronological_grading_order
        """
        posted_newest_first = setup_chronological_ordering_scenario()
        posted_oldest_first = setup_transfer_variant_pair()

        def grades(transfer_id):
            return {
                lot["symbol"]: lot["basis_confidence_grade"]
                for lot in validate_success(
                    api_client.list_transfer_lots(transfer_id, ADVISOR), 200
                )
            }

        assert grades(posted_newest_first["transfer"]["id"]) == {"VTI": "HIGH", "BND": "MEDIUM"}
        assert grades(posted_oldest_first["graded_transfer"]["id"]) == {"VTI": "HIGH", "BND": "MEDIUM"}
        assert posted_newest_first["transfer"]["carryover_cents"] == 1_200_000
        assert posted_oldest_first["graded_transfer"]["carryover_cents"] == 1_200_000


class TestLotLifecycleAndRejection:

    def test_receipt_stamps_and_credits_the_lots_without_a_lot_endpoint(self):
        """PRD §3.3: "Recording receipt is a `CustodyOperationsOfficer` action
        available from `SUBMITTED`; it forks the transfer, and the fork is the heart
        of the model. On receipt every lot is stamped with its
        `basis_confidence_grade` and its `suspected_double_basis` flag".
        PRD §3.3: "It is then driven to `APPLIED` when the parent transfer reaches
        `CREDITED`, at which point its `basis_appraisal_cents` receives the accepted
        basis".

        Design: Corner/state_machines/transfer_lot_stamp_and_apply_side_effect_execution
        """
        firm, _agreement, household, accounts = setup_funded_household(
            account_specs=[{"basis_cents": 0, "account_number": "RIA-110001"}],
        )
        account = accounts[0]
        transfer = validate_success(api_client.create_asset_transfer(
            {"receiving_account_id": account["id"], "firm_id": firm["id"],
             "delivering_firm_name": "Prior Custodian LLC", "method": "ACAT"}, ADVISOR,
        ), 201)
        lot = validate_success(api_client.create_transfer_lot(
            transfer["id"],
            {"symbol": "VTI", "quantity_micros": 4_000_000_000, "sent_cost_basis_cents": 90_000_000,
             "lot_inventory_date": "2019-01-02T00:00:00Z", "valuation_price_micros": 250_000_000},
            ADVISOR,
        ), 201)
        validate_success(api_client.transfer_out(transfer["id"], {}, ADVISOR, row=transfer), 200)
        credited = validate_success(
            api_client.mark_received(transfer["id"], {}, CUSTODY, row=refetch_transfer(transfer["id"])), 200
        )
        assert credited["transfer_status"] == "CREDITED"
        assert credited["cost_basis_complete"] is True

        stored = _lots(transfer["id"])[0]
        assert stored["id"] == lot["id"]
        assert stored["basis_confidence_grade"] == "HIGH"
        assert stored["basis_appraisal_cents"] == 90_000_000
        assert stored["suspected_double_basis"] is False

    def test_rejecting_the_basis_package_discards_lots_and_rebases_household(self):
        """PRD §3.3: "A `CustodyOperationsOfficer` may instead reject the package,
        which requires `BASIS_REVIEW` and a non-empty `rejected_reason_code`;
        rejection moves the transfer to `REJECTED`, forces `carryover_cents` to 0,
        removes the transfer's lots from the receiving account's positions, and
        recomputes the household's fee basis."

        Design: Corner/state_machines/asset_transfer_reject_discards_lots_and_rebases_household
        """
        scenario = setup_account_in_basis_review()
        transfer = scenario["transfer"]
        assert transfer["transfer_status"] == "BASIS_REVIEW"

        rejected = validate_success(api_client.reject_basis(
            transfer["id"], {"rejected_reason_code": "DELIVERING_FIRM_SENT_NO_BASIS"}, CUSTODY, row=transfer), 200)
        assert rejected["transfer_status"] == "REJECTED"
        assert rejected["carryover_cents"] == 0
        assert rejected["cost_basis_complete"] is False

        lots = _lots(transfer["id"])
        assert len(lots) == 2
        assert all(lot["basis_appraisal_cents"] is None for lot in lots)
        assert refetch_household(scenario["household"]["id"])["household_fee_basis_cents"] == 0
        assert refetch_account(scenario["account"]["id"])["account_status"] == "OPEN"


class TestTransferLotParentResolution:

    def test_a_lot_attaches_only_to_a_resolvable_transfer(self):
        """PRD §2.9: "A path parameter or body foreign key that resolves to nothing
        yields `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."
        PRD §3.3: "each new lot written with `transfer_id` set to the transfer that
        owns it".

        Design: Corner/entities/transfer_lot_fk_requires_its_own_transfer_parent
        """
        scenario = setup_account_in_basis_review()
        transfer = scenario["transfer"]
        lots = _lots(transfer["id"])
        assert len(lots) == 2
        assert all(lot["transfer_id"] == transfer["id"] for lot in lots)
        assert all(lot["basis_appraisal_cents"] is None for lot in lots)

        res = api_client.create_transfer_lot(
            NON_EXISTENT_UUID,
            {"symbol": "VTI", "quantity_micros": 1_000_000, "sent_cost_basis_cents": 100,
             "lot_inventory_date": "2020-01-02T00:00:00Z", "valuation_price_micros": 250_000_000},
            ADVISOR,
        )
        validate_error_is_one_of(res, ["ERR_RESOURCE_NOT_FOUND", "ERR_PARENT_CHILD_MISMATCH"])