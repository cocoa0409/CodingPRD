"""Trade-in transition programs: dual credit variants, completion cascade,
enrollment window gate, and enrollment expiry sweep (PRD sections 2.4, 3.8).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    appraise_transition,
    create_account,
    create_active_contract,
    create_enrolled_transition,
    create_instrument,
    create_model,
    create_operational_instrument,
    create_transition_program_payload,
    make_account_manager_headers,
    make_finance_admin_headers,
    record_service_window,
    transition_advance_payload,
    validate_error,
    validate_success,
)
from test_helpers import api_client


def _setup_gap2_transition(am_user_id="am-9"):
    """RUO account; old model generation 2 at 4,000,000c; new model generation
    4; old instrument installed 2021-06-01; enrollment window 2027-01-01."""
    bag = create_enrolled_transition(
        old_installed_at="2021-06-01T00:00:00Z",
        old_model_overrides={"generation": 2, "base_price_cents": 4_000_000},
        new_model_overrides={"generation": 4, "base_price_cents": 6_000_000},
        am_user_id=am_user_id,
    )
    return bag


def _setup_appraised_transition_with_contract():
    """Old instrument OPERATIONAL under an ACTIVE contract (committed 99.0,
    fee 500,000c, cap 120,000c, coverage [2026-09-01, 2027-09-01)) with one
    closed 20-minute service window 01:00->01:20; transition APPRAISED with
    FUNCTIONAL_DEFECT + MISSING_ACCESSORIES; clock at 2026-09-01T16:40:00Z."""
    account = create_account()
    old_model = create_model(generation=2, base_price_cents=4_000_000)
    new_model = create_model(
        generation=4,
        base_price_cents=6_000_000,
        supported_chemistry_versions=["V2", "V3"],
        base_run_modes=["STD_SHORT", "STD_LONG"],
    )
    instrument = create_operational_instrument(
        account_id=account["id"],
        model_id=old_model["id"],
        installed_at="2021-06-01T00:00:00Z",
    )
    contract = create_active_contract(
        account_id=account["id"], instrument_id=instrument["id"]
    )
    record_service_window(
        instrument["id"], "2026-09-01T01:00:00Z", "2026-09-01T01:20:00Z"
    )
    transition = create_enrolled_transition(
        account_id=account["id"],
        old_instrument_id=instrument["id"],
        new_model_id=new_model["id"],
        am_user_id="am-4",
    )["transition"]
    appraised = appraise_transition(
        transition["id"],
        condition_flags=["FUNCTIONAL_DEFECT", "MISSING_ACCESSORIES"],
        fa_user_id="fa-4",
    )
    advance_clock("2026-09-01T16:40:00Z")
    return {
        "account": account,
        "instrument": instrument,
        "contract": contract,
        "transition": appraised,
    }


class TestTradeInDualCreditVariants:
    def test_enrollment_quotes_provisional_credit_by_generation_gap(self, api):
        """Enrollment of a generation-2 instrument toward a generation-4 model
        quotes the list-based provisional credit: 35% of 4,000,000c.

        PRD §3.8: "At enrollment the server quotes `provisional_credit_cents` from the list price alone: 20% of the old model's `base_price_cents` for a generation gap of one, 35% for a gap of two, and 50% for a gap of three or more, rounded half up to whole cents."
        PRD §3.8: "The enrolling manager is recorded as `created_by_user_id`, `final_credit_cents` stays null, and the program starts `ENROLLED`."

        Design: Difficulty/dual_variant_calc/tradein_provisional_vs_final_credit
        """
        bag = _setup_gap2_transition()
        transition = bag["transition"]
        assert transition["program_state"] == "ENROLLED"
        assert transition["provisional_credit_cents"] == 1_400_000, (
            "gap 2 must quote 35% of 4,000,000c, got "
            f"{transition['provisional_credit_cents']}"
        )
        assert transition["final_credit_cents"] is None

    def test_appraisal_computes_final_credit_below_provisional(self, api):
        """Appraisal applies condition (0.20 + 0.10) and age (5 years in
        service -> 2 * 2%) deductions to the same instrument: the final
        variant yields 924,000c where the provisional variant quoted
        1,400,000c.

        PRD §3.8: "Condition deductions come off first in combination: 5% of the provisional for cosmetic damage, 20% for a functional defect, and 10% for missing accessories, summed when several flags are present."
        PRD §3.8: "Age then deducts 2% of the provisional per whole year in service beyond the first three free years, where years in service is the whole-year count — rounded down — between the instrument's `installed_at` and the appraisal instant; an instrument fewer than four years in service pays no age deduction at all."
        PRD §3.8: "The final credit is the provisional minus that deduction, clamped so it never falls below a floor of 5% of the old model's `base_price_cents` (rounded half up) and never exceeds the provisional."

        Design: Difficulty/dual_variant_calc/tradein_provisional_vs_final_credit
        """
        bag = _setup_gap2_transition()
        appraised = appraise_transition(
            bag["transition"]["id"],
            condition_flags=["FUNCTIONAL_DEFECT", "MISSING_ACCESSORIES"],
            fa_user_id="fa-9",
        )
        assert appraised["program_state"] == "APPRAISED"
        # deduction = round(1,400,000 * (0.20 + 0.10 + 0.02 * (5 - 3))) = 476,000
        assert appraised["final_credit_cents"] == 924_000, (
            "final variant must deduct condition 0.30 + age 0.04 from the "
            f"provisional, got {appraised['final_credit_cents']}"
        )
        assert appraised["final_credit_cents"] != appraised[
            "provisional_credit_cents"
        ], "the two variants must disagree on identical instrument data"


class TestTransitionCompleteCascade:
    def test_completion_cascade_states(self, api):
        """COMPLETE lands the program COMPLETED, decommissions the old
        instrument, and terminates its ACTIVE contract as AUTO_DECOMMISSION.

        PRD §3.8: "On success the old instrument transitions to `DECOMMISSIONED`, its active service contracts terminate with `terminated_reason` `AUTO_DECOMMISSION` and their final uptime credits post per §3.6, and the account's `credit_balance_cents` increases by `final_credit_cents`."

        Design: Difficulty/transitive_cascade/transition_complete_cascade
        """
        bag = _setup_appraised_transition_with_contract()
        resp = api_client.advance_transition_program(
            bag["transition"]["id"],
            transition_advance_payload("COMPLETE"),
            make_finance_admin_headers("fa-4"),
        )
        completed = validate_success(resp)
        assert completed["program_state"] == "COMPLETED"
        assert completed["final_credit_cents"] == 924_000

        instrument = validate_success(
            api.get_instrument(
                bag["instrument"]["id"], make_account_manager_headers("am-1")
            )
        )
        assert instrument["install_state"] == "DECOMMISSIONED"

        contract = validate_success(
            api.get_service_contract(
                bag["contract"]["id"], make_finance_admin_headers("fa-1")
            )
        )
        assert contract["contract_state"] == "TERMINATED"
        assert contract["terminated_reason"] == "AUTO_DECOMMISSION"

    def test_completion_cascade_posts_final_uptime_credit_and_tradein(self, api):
        """The cascade's final reconciliation runs over [coverage_start,
        decommission instant) = 1000 minutes with 20 down (98.00 uptime,
        deficit exactly 1.00 -> 10% of 500,000c = 50,000c); the account
        balance receives 924,000c trade-in + 50,000c uptime credit.

        PRD §3.2: "Each so-terminated contract runs a final uptime reconciliation over the window from the later of its `coverage_start` and its `last_reconciliation_end` up to the decommission instant, computed exactly as in §3.6, and the resulting credit is added both to that contract's `credits_issued_ytd_cents` and to the account's `credit_balance_cents`."
        PRD §3.6: "Below the commitment, the deficit — the commitment minus the measured uptime, at two decimals rounded half up — selects a rate: a deficit below 1.0 percentage point pays 5% of `monthly_fee_cents`; a deficit of at least 1.0 but below 3.0 pays 10%, so a deficit of exactly 1.0 lands in the 10% tier; a deficit of 3.0 or more pays 25%."
        PRD §3.8: "On success the old instrument transitions to `DECOMMISSIONED`, its active service contracts terminate with `terminated_reason` `AUTO_DECOMMISSION` and their final uptime credits post per §3.6, and the account's `credit_balance_cents` increases by `final_credit_cents`."

        Design: Difficulty/transitive_cascade/transition_complete_cascade
        """
        bag = _setup_appraised_transition_with_contract()
        validate_success(
            api_client.advance_transition_program(
                bag["transition"]["id"],
                transition_advance_payload("COMPLETE"),
                make_finance_admin_headers("fa-4"),
            )
        )
        contract = validate_success(
            api.get_service_contract(
                bag["contract"]["id"], make_finance_admin_headers("fa-1")
            )
        )
        assert contract["credits_issued_ytd_cents"] == 50_000, (
            "final reconciliation must post 10% of 500,000c, got "
            f"{contract['credits_issued_ytd_cents']}"
        )
        account = validate_success(
            api.get_account(bag["account"]["id"], make_account_manager_headers("am-1"))
        )
        assert account["credit_balance_cents"] == 974_000, (
            "account credit must be 924,000 trade-in + 50,000 uptime, got "
            f"{account['credit_balance_cents']}"
        )


class TestTransitionEnrollmentWindow:
    def test_enrollment_after_window_end_rejected(self, api):
        """An enrollment_window_end before the current logical clock rejects
        the enrollment at creation.

        PRD §3.8: "Enrollment requires the current logical clock to be at or before `enrollment_window_end`, and it requires a genuine generational move — the new model's `generation` must exceed the old instrument's model `generation` by at least 1; either violation is rejected with `ERR_ENROLLMENT_WINDOW_CLOSED` (HTTP 422)."

        Design: Corner/validations/enrollment_window_closed_rejected
        """
        account = create_account()
        old_model = create_model(generation=2, base_price_cents=4_000_000)
        new_model = create_model(generation=3, base_price_cents=5_000_000)
        instrument = create_instrument(
            account_id=account["id"], model_id=old_model["id"]
        )
        resp = api_client.create_transition_program(
            create_transition_program_payload(
                account["id"],
                instrument["id"],
                new_model["id"],
                enrollment_window_end="2026-08-01T00:00:00Z",
            ),
            make_account_manager_headers("am-1"),
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_WINDOW_CLOSED)

    def test_enrolled_program_expires_past_window_end(self, api):
        """The clock sweep lapses an ENROLLED program once the clock passes
        its enrollment_window_end, with no direct call on the program.

        PRD §2.4: "Transition programs still `ENROLLED` once the clock has passed their `enrollment_window_end` become `EXPIRED`, and programs sitting in `APPRAISED` become `EXPIRED` once the clock passes thirty days after their `appraised_at`."

        Design: Corner/state_machines/transition_enrolled_expiry_sweep
        """
        bag = create_enrolled_transition(
            enrollment_window_end="2026-09-10T00:00:00Z"
        )
        result = advance_clock("2026-09-11T00:00:00Z")
        assert result["transitions_expired"] == 1, (
            f"exactly one transition must expire, got {result['transitions_expired']}"
        )
        transition = validate_success(
            api.get_transition_program(
                bag["transition"]["id"], make_account_manager_headers("am-1")
            )
        )
        assert transition["program_state"] == "EXPIRED"
