"""Federal Reserve cash letters: eligibility, the shipping gate and reconciliation."""

from test_helpers import (
    ApiErrorId,
    FED_AGENT_1,
    MANAGER_1,
    assert_cash_letter_reconciliation,
    assert_fed_deposit,
    confirm_cash_letter,
    confirm_fed_deposit_payload,
    create_fed_deposit_payload,
    create_vault,
    make_fed_agent_headers,
    make_manager_headers,
    prepare_cash_letter,
    read_fed_deposit,
    read_session_lots,
    read_vault,
    setup_bag_with_suspect_lot,
    setup_drafted_counterfeit_report,
    setup_shipped_cash_letter,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCashLetterPreparation:
    def test_an_empty_lot_list_is_a_business_outcome_not_a_shape_error(self, api):
        """PRD §3.8: "If the array is empty, the failure is not a malformed-request error but
        `ERR_NO_ELIGIBLE_LOTS`; that is the one place where an empty array is treated as a
        business outcome rather than a shape violation."
        PRD §2.6: "One deliberate exception: an empty `fitness_lot_ids` array on a cash
        letter is **not** treated as a shape error here; it surfaces much later as
        `ERR_NO_ELIGIBLE_LOTS`."

        Design: Difficulty/boundary_precision_check/empty_fitness_lot_list_rejected_while_single_lot_list_is_accepted
        """
        scenario = setup_bag_with_suspect_lot()

        response = api.create_fed_deposit(
            create_fed_deposit_payload(
                scenario["vault"]["id"], [], cash_letter_number="CL-0001", deposit_date="2026-08-04"
            ),
            make_manager_headers(MANAGER_1),
        )
        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_LOTS.value)
        assert response.status_code == 422, (
            f"ERR_NO_ELIGIBLE_LOTS must be HTTP 422, got {response.status_code}"
        )

    def test_a_single_eligible_lot_freezes_the_declared_total_and_attaches(self, api):
        """PRD §3.8: "A prepared cash letter is created in `PREPARED` with
        `declared_total_cents` frozen as the sum of `face_value_cents` over the lots named at
        creation, `attached_lot_count` frozen as the number of those lots,
        `credited_total_cents` and `adjustment_cents` at 0, and `submitted_at` and
        `confirmed_at` null. Each named lot has its `fed_deposit_id` set to the new cash
        letter and moves `PENDING_DEPOSIT → ATTACHED`."

        Design: Difficulty/boundary_precision_check/empty_fitness_lot_list_rejected_while_single_lot_list_is_accepted
        """
        scenario = setup_bag_with_suspect_lot()
        fit_lot = scenario["fit_lot"]
        assert fit_lot["face_value_cents"] == 80_000

        response = api.create_fed_deposit(
            create_fed_deposit_payload(
                scenario["vault"]["id"],
                [fit_lot["id"]],
                cash_letter_number="CL-0002",
                deposit_date="2026-08-04",
            ),
            make_manager_headers(MANAGER_1),
        )
        fed_deposit = validate_success(response, 201)
        assert_fed_deposit(fed_deposit)
        assert fed_deposit["declared_total_cents"] == 80_000, (
            f"Expected declared_total_cents 80000, got {fed_deposit['declared_total_cents']}"
        )
        assert fed_deposit["attached_lot_count"] == 1, (
            f"Expected attached_lot_count 1, got {fed_deposit['attached_lot_count']}"
        )
        assert fed_deposit["status"] == "PREPARED"
        assert fed_deposit["credited_total_cents"] == 0
        assert fed_deposit["adjustment_cents"] == 0

        attached = read_session_lots(scenario["session"]["id"], category="FIT")[0]
        assert attached["status"] == "ATTACHED", (
            f"The named lot moves PENDING_DEPOSIT -> ATTACHED, got {attached['status']}"
        )
        assert attached["fed_deposit_id"] == fed_deposit["id"], (
            "The lot's fed_deposit_id must point at the new cash letter"
        )

    def test_a_counterfeit_suspect_lot_is_not_eligible(self, api):
        """PRD §3.8: "Eligibility for attachment is checked lot by lot. Every named lot must
        have a `category` of either `FIT` or `UNFIT` and a `status` of `PENDING_DEPOSIT`; a
        `COUNTERFEIT_SUSPECT` lot or one already attached, deposited or seized is
        `ERR_LOT_NOT_ELIGIBLE`."

        Design: Corner/validations/counterfeit_suspect_lot_is_not_eligible_for_a_cash_letter
        """
        scenario = setup_bag_with_suspect_lot()
        suspect_lot = scenario["suspect_lot"]

        response = api.create_fed_deposit(
            create_fed_deposit_payload(
                scenario["vault"]["id"],
                [suspect_lot["id"]],
                cash_letter_number="CL-C39",
                deposit_date="2026-08-04",
            ),
            make_manager_headers(MANAGER_1),
        )
        validate_error(response, ApiErrorId.ERR_LOT_NOT_ELIGIBLE.value)
        assert response.status_code == 422

        lot = read_session_lots(scenario["session"]["id"], category="COUNTERFEIT_SUSPECT")[0]
        assert lot["status"] == "PENDING_REVIEW", "The suspect lot is untouched"
        assert lot["fed_deposit_id"] is None
        _, meta = validate_paginated(
            api.list_fed_deposits(
                make_manager_headers(MANAGER_1), params={"vault_id": scenario["vault"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No cash letter may be created by a rejected preparation, got {meta['total_count']}"
        )

    def test_a_lot_counted_on_another_vaults_floor_is_refused(self, api):
        """PRD §3.8: "Every named lot must also have been counted on this vault's own floor —
        the counting machine behind the lot's counting session must belong to the same vault
        as the cash letter's `vault_id` — and a lot from another vault is
        `ERR_LOT_VAULT_MISMATCH`."

        Design: Corner/validations/lot_counted_at_another_vault_rejected_on_cash_letter
        """
        scenario = setup_bag_with_suspect_lot()
        other_vault = create_vault(vault_code="CV-C40B", name="CV-C40B Vault")

        response = api.create_fed_deposit(
            create_fed_deposit_payload(
                other_vault["id"],
                [scenario["fit_lot"]["id"]],
                cash_letter_number="CL-C40",
                deposit_date="2026-08-04",
            ),
            make_manager_headers(MANAGER_1),
        )
        validate_error(response, ApiErrorId.ERR_LOT_VAULT_MISMATCH.value)
        assert response.status_code == 422

        lot = read_session_lots(scenario["session"]["id"], category="FIT")[0]
        assert lot["status"] == "PENDING_DEPOSIT", (
            f"The otherwise eligible lot stays PENDING_DEPOSIT, got {lot['status']}"
        )
        _, meta = validate_paginated(
            api.list_fed_deposits(
                make_manager_headers(MANAGER_1), params={"vault_id": other_vault["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestShippingGate:
    def test_a_draft_counterfeit_report_blocks_the_shipment(self, api):
        """PRD §3.8: "No counterfeit report may still be sitting in `DRAFT` on any fitness lot
        that shares a `count_session_id` with any lot attached to this cash letter — the
        compliance chain must be resolved before the vault ships anything counted alongside a
        suspect batch, and a pending draft is `ERR_COUNTERFEIT_REPORT_PENDING`."
        PRD §3.5: "One further consequence reaches outside this workflow: while any report on
        a lot sits in `DRAFT`, the cash letter covering that lot's counting session cannot be
        shipped, as §3.8 describes."

        Design: Difficulty/cross_entity_state_dependency/fed_deposit_submit_gated_by_draft_counterfeit_report
        """
        scenario = setup_drafted_counterfeit_report()
        assert scenario["report"]["status"] == "DRAFT"
        fed_deposit = prepare_cash_letter(
            scenario["vault"]["id"],
            [scenario["fit_lot"]["id"]],
            cash_letter_number="CL-1501",
            deposit_date="2026-08-04",
        )

        response = api.submit_fed_deposit(fed_deposit["id"], make_manager_headers(MANAGER_1))
        validate_error(response, ApiErrorId.ERR_COUNTERFEIT_REPORT_PENDING.value)
        assert response.status_code == 409, (
            f"ERR_COUNTERFEIT_REPORT_PENDING must be HTTP 409, got {response.status_code}"
        )

    def test_the_blocked_shipment_leaves_the_letter_prepared_and_its_lot_attached(self, api):
        """PRD §3.8: "Shipping the cash letter moves it `PREPARED → SUBMITTED` and stamps
        `submitted_at` from the logical clock."
        PRD §3.8: "On success every attached lot moves `ATTACHED → DEPOSITED`."
        PRD §3.8: "No counterfeit report may still be sitting in `DRAFT` on any fitness lot
        that shares a `count_session_id` with any lot attached to this cash letter — the
        compliance chain must be resolved before the vault ships anything counted alongside a
        suspect batch, and a pending draft is `ERR_COUNTERFEIT_REPORT_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/fed_deposit_submit_gated_by_draft_counterfeit_report
        """
        scenario = setup_drafted_counterfeit_report()
        fed_deposit = prepare_cash_letter(
            scenario["vault"]["id"],
            [scenario["fit_lot"]["id"]],
            cash_letter_number="CL-1502",
            deposit_date="2026-08-04",
        )

        response = api.submit_fed_deposit(fed_deposit["id"], make_manager_headers(MANAGER_1))
        validate_error(response, ApiErrorId.ERR_COUNTERFEIT_REPORT_PENDING.value)

        refreshed = read_fed_deposit(fed_deposit["id"])
        assert refreshed["status"] == "PREPARED", (
            f"The cash letter stays PREPARED, got {refreshed['status']}"
        )
        assert refreshed["submitted_at"] is None, (
            f"submitted_at must stay null, got {refreshed['submitted_at']!r}"
        )
        lot = read_session_lots(scenario["session"]["id"], category="FIT")[0]
        assert lot["status"] == "ATTACHED", (
            f"The attached lot must not move to DEPOSITED, got {lot['status']}"
        )


class TestFederalReserveConfirmation:
    def test_a_short_credit_takes_the_adjustment_branch(self, api):
        """PRD §3.8: "When the adjustment is anything other than 0, whether the Reserve
        credited above the declared figure or below it, the cash letter moves `SUBMITTED →
        CONFIRMED_WITH_ADJUSTMENT` and the shipping vault's `cash_letter_adjustment_cents` is
        increased by that signed adjustment."
        PRD §3.8: "The adjustment is that reported figure minus the cash letter's frozen
        `declared_total_cents`, stored signed as `adjustment_cents`, and `confirmed_at` is
        stamped from the logical clock."
        PRD §3.8: "The boolean `reconciled` is true exactly when `outstanding_cents` is 0
        **and** `net_adjustment_cents` equals the vault's own persisted
        `cash_letter_adjustment_cents`; if either condition fails, `reconciled` is false."

        Design: Corner/state_machines/fed_deposit_confirm_with_short_credit_takes_adjustment_branch
        """
        scenario = setup_shipped_cash_letter()
        assert scenario["fed_deposit"]["declared_total_cents"] == 80_000
        assert scenario["fed_deposit"]["status"] == "SUBMITTED"

        response = api.confirm_fed_deposit(
            scenario["fed_deposit"]["id"],
            confirm_fed_deposit_payload(79_500),
            make_fed_agent_headers(FED_AGENT_1),
        )
        confirmed = validate_success(response, 200)
        assert confirmed["status"] == "CONFIRMED_WITH_ADJUSTMENT", (
            f"Expected CONFIRMED_WITH_ADJUSTMENT, got {confirmed['status']}"
        )
        assert confirmed["adjustment_cents"] == -500, (
            f"79500 - 80000 = -500, got {confirmed['adjustment_cents']}"
        )
        assert read_vault(scenario["vault"]["id"])["cash_letter_adjustment_cents"] == -500, (
            "The adjustment branch moves the vault's running total"
        )

        lot = read_session_lots(scenario["session"]["id"], category="FIT")[0]
        assert lot["status"] == "DEPOSITED", (
            f"Shipping moved the attached lot to DEPOSITED, got {lot['status']}"
        )

        reconciliation = validate_success(
            api.get_cash_letter_reconciliation(
                scenario["vault"]["id"], make_manager_headers(MANAGER_1)
            )
        )
        assert_cash_letter_reconciliation(reconciliation)
        assert reconciliation["shipped_total_cents"] == 80_000
        assert reconciliation["credited_total_cents"] == 79_500
        assert reconciliation["outstanding_cents"] == 0
        assert reconciliation["net_adjustment_cents"] == -500
        assert reconciliation["reconciled"] is True

    def test_a_matching_credit_takes_the_clean_branch(self, api):
        """PRD §3.8: "When the adjustment is exactly 0 — the Federal Reserve credited
        precisely what was declared — the cash letter moves `SUBMITTED → CONFIRMED` and no
        vault field moves at all."
        PRD §3.8: "Only this second branch ever moves the vault's running adjustment total;
        the clean-confirmation branch leaves it untouched."
        PRD §3.8: "The `net_adjustment_cents` is the sum of `adjustment_cents` over this
        vault's cash letters whose `status` is `CONFIRMED_WITH_ADJUSTMENT`."

        Design: Corner/state_machines/fed_deposit_confirm_with_matching_credit_takes_the_no_adjustment_branch
        """
        scenario = setup_shipped_cash_letter()
        assert scenario["fed_deposit"]["declared_total_cents"] == 80_000

        confirmed = confirm_cash_letter(scenario["fed_deposit"]["id"], 80_000)
        assert confirmed["status"] == "CONFIRMED", f"Expected CONFIRMED, got {confirmed['status']}"
        assert confirmed["adjustment_cents"] == 0
        assert confirmed["credited_total_cents"] == 80_000

        assert read_vault(scenario["vault"]["id"])["cash_letter_adjustment_cents"] == 0, (
            "The clean branch leaves the vault's running adjustment total untouched"
        )

        reconciliation = validate_success(
            api.get_cash_letter_reconciliation(
                scenario["vault"]["id"], make_manager_headers(MANAGER_1)
            )
        )
        assert reconciliation["net_adjustment_cents"] == 0
        assert reconciliation["outstanding_cents"] == 0
        assert reconciliation["reconciled"] is True
