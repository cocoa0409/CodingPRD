"""Standing instructions, money-movement authorization and the withholding rules."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    make_client_headers,
    setup_firm_with_agreement,
    setup_household,
    open_account,
    setup_verified_standing_instruction,
    setup_submitted_movement,
    authorize_movement_as_client,
    setup_withholding_dominant_rule_scenario,
    setup_money_movement_scenario,
    setup_account_at_periodic_limit_consumption,
    refetch_instruction,
    refetch_account,
)
"""Standing instructions, money-movement authorization and the withholding rules."""
"""Standing instructions, money-movement authorization and the withholding rules."""

ADVISOR = TEST_USERS["advisor_ops_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestWithholdingRules:

    def test_the_read_probe_reports_no_withholding_for_an_unverified_instruction(self):
        """PRD §3.8: "On an account whose authorization chain is not fully
        propagated, the probe reports the entitlement-level withdrawal — which is
        0 — rather than the jurisdiction withholding, because it re-reads the
        posture chain before it reads the movement row."

        Design: Difficulty/dual_variant_calc/money_movement_first_binding_vs_dominant_rule_variant
        """
        scenario = setup_withholding_dominant_rule_scenario()
        account_id = scenario["account"]["id"]
        household_id = scenario["household"]["id"]

        summary = validate_success(api_client.money_movement_summary(
            account_id, make_client_headers(household_id),
        ), 200)
        assert len(summary) == 1
        assert summary[0]["withheld_cents"] == 0
        movement = validate_success(
            api_client.get_money_movement(scenario["movement"]["id"], ADVISOR), 200
        )
        assert movement["jurisdiction_withholding_required"] is False

    def test_the_write_path_refuses_at_the_first_binding_rule(self):
        """PRD §3.8: "1. If the `authorization_note` is blank, the movement is
        rejected with `ERR_AUTHORIZATION_NOTE_REQUIRED` (HTTP 422)."
        PRD §3.8: "the first one that fires determines both the error and — where
        the sequence does not reject — the withholding decision; a later rule never
        overrides an earlier one's withholding outcome."

        Design: Difficulty/dual_variant_calc/money_movement_first_binding_vs_dominant_rule_variant
        """
        scenario = setup_withholding_dominant_rule_scenario()
        res = authorize_movement_as_client(scenario["movement"]["id"], scenario["household"]["id"])
        validate_error(res, "ERR_AUTHORIZATION_NOTE_REQUIRED", expected_status=422)

        movement = validate_success(
            api_client.get_money_movement(scenario["movement"]["id"], ADVISOR), 200
        )
        assert movement["movement_status"] == "PENDING_AUTHORIZATION"
        instruction = validate_success(
            api_client.get_standing_instruction(scenario["instruction"]["id"], ADVISOR), 200
        )
        assert instruction["consumed_period_cents"] == 0

    def test_an_ira_account_withholds_ten_percent_at_authorization(self):
        """PRD §3.8: "If the account's `account_type` is `IRA` or `ROTH_IRA`, the
        movement's `jurisdiction_withholding_required` is set to true and
        `withheld_cents` is the movement amount multiplied by 1000 basis points and
        divided by one hundred, floored to whole cents, and capped so that it never
        exceeds the movement amount itself".

        Design: Corner/endpoints/account_money_movement_summary_computed_read_matches_c7
        """
        scenario = setup_money_movement_scenario(account_type="IRA", account_number="RIA-117001", movement_amount_cents=250_000)
        validate_success(authorize_movement_as_client(
            scenario["movement"]["id"], scenario["household"]["id"],
        ), 200)

        movement = validate_success(
            api_client.get_money_movement(scenario["movement"]["id"], ADVISOR), 200
        )
        assert movement["jurisdiction_withholding_required"] is True
        assert movement["withheld_cents"] == 25_000
        assert movement["net_disbursed_cents"] == 225_000

    def test_the_summary_read_agrees_with_the_persisted_withholding(self):
        """PRD §3.8: "This probe reports, per movement on an account, the withdrawal
        amount each restriction would independently demand and returns the single
        largest of them".

        Design: Corner/endpoints/account_money_movement_summary_computed_read_matches_c7
        """
        scenario = setup_money_movement_scenario(
            account_type="IRA", account_number="RIA-117001", movement_amount_cents=250_000,
        )
        validate_success(authorize_movement_as_client(
            scenario["movement"]["id"], scenario["household"]["id"],
        ), 200)

        summary = validate_success(api_client.money_movement_summary(
            scenario["account"]["id"], make_client_headers(scenario["household"]["id"]),
        ), 200)
        assert summary[0]["withheld_cents"] == 25_000
        assert summary[0]["net_disbursed_cents"] == 225_000

        instruction = validate_success(
            api_client.get_standing_instruction(scenario["instruction"]["id"], ADVISOR), 200
        )
        assert instruction["consumed_period_cents"] == 250_000


class TestPeriodicLimit:

    def test_the_third_tranche_breaches_the_cumulative_periodic_limit(self):
        """PRD §3.8: "2. If the movement's `amount_cents` exceeds the linked
        instruction's `periodic_limit_cents` minus its already-consumed total, it is
        rejected with `ERR_STANDING_LIMIT_EXCEEDED` (HTTP 409)."
        PRD §3.8: "The amount-versus-limit check compares against the instruction's
        remaining headroom, not its raw limit, so consumed movements reduce the room
        available to later ones."

        Design: Difficulty/resource_temporal_overlap/standing_instruction_periodic_cumulative_limit_overlap
        """
        scenario = setup_account_at_periodic_limit_consumption(
            limit_cents=500_000, accepted_amounts=(200_000, 200_000),
            pending_amount_cents=100_001,
        )
        instruction = scenario["instruction"]
        assert instruction["consumed_period_cents"] == 400_000

        third = scenario["pending_movement"]
        res = authorize_movement_as_client(third["id"], scenario["household"]["id"])
        validate_error(res, "ERR_STANDING_LIMIT_EXCEEDED", expected_status=409)

    def test_a_rejected_tranche_leaves_the_consumed_total_untouched(self):
        """PRD §3.8: "On successful authorization the movement's `movement_status`
        becomes `AUTHORIZED`, the linked instruction's `consumed_period_cents`
        increases by the movement's `amount_cents`".

        Design: Difficulty/resource_temporal_overlap/standing_instruction_periodic_cumulative_limit_overlap
        """
        scenario = setup_account_at_periodic_limit_consumption(
            limit_cents=500_000, accepted_amounts=(200_000, 200_000),
            pending_amount_cents=100_001,
        )
        third = scenario["pending_movement"]
        authorize_movement_as_client(third["id"], scenario["household"]["id"])

        instruction = validate_success(
            api_client.get_standing_instruction(scenario["instruction"]["id"], ADVISOR), 200
        )
        assert instruction["consumed_period_cents"] == 400_000
        movement = validate_success(
            api_client.get_money_movement(third["id"], ADVISOR), 200
        )
        assert movement["movement_status"] == "PENDING_AUTHORIZATION"


class TestInstructionStateDependency:

    def test_a_stale_instruction_refuses_authorization_on_day_seven(self):
        """PRD §3.8: "4. If the instruction's `round_trip_days` has reached 7 or
        more, the movement is rejected with `ERR_STANDING_INSTRUCTION_EXPIRED`
        (HTTP 409)."
        PRD §3.8: "`round_trip_days` is the number of whole days between the current
        instant and `verified_at`, and the instruction may be expired once that
        figure has reached 7."

        Design: Difficulty/cross_entity_state_dependency/money_movement_authorization_depends_on_standing_instruction_state
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("MONEY_MOVEMENT", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-106001")
        instruction = setup_verified_standing_instruction(
            account["id"], household["id"], periodic_limit_cents=5_000_000,
        )
        assert instruction["round_trip_days"] == 0

        validate_success(api_client.set_clock({"current_utc": "2026-09-07T00:00:00Z"},
                                              TEST_USERS["admin_headers"]), 200)
        movement = setup_submitted_movement(
            account["id"], instruction["id"], amount_cents=100_000,
            authorization_note="Client confirmed by signed form 2026-09-07",
        )
        aged = validate_success(
            api_client.get_standing_instruction(instruction["id"], ADVISOR), 200
        )
        assert aged["round_trip_days"] == 6

        validate_success(api_client.set_clock({"current_utc": "2026-09-08T00:00:00Z"},
                                              TEST_USERS["admin_headers"]), 200)
        res = authorize_movement_as_client(movement["id"], household["id"])
        validate_error(res, "ERR_STANDING_INSTRUCTION_EXPIRED", expected_status=409)

    def test_an_unverified_instruction_blocks_authorization(self):
        """PRD §3.8: "3. If the linked instruction's `verification_status` is
        anything other than `VERIFIED`, the movement is rejected with
        `ERR_STANDING_INSTRUCTION_NOT_VERIFIED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/money_movement_authorization_depends_on_standing_instruction_state
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("MONEY_MOVEMENT", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-106002")
        instruction = setup_verified_standing_instruction(
            account["id"], household["id"], periodic_limit_cents=5_000_000, verify=False,
        )
        assert instruction["verification_status"] == "PENDING"

        movement = setup_submitted_movement(account["id"], instruction["id"], amount_cents=100_000)
        res = authorize_movement_as_client(movement["id"], household["id"])
        validate_error(res, "ERR_STANDING_INSTRUCTION_NOT_VERIFIED", expected_status=409)

    def test_expiring_a_round_trip_short_of_seven_days_is_refused(self):
        """PRD §3.8: "Expiry is an operational check performed by a
        `CustodyOperationsOfficer` against a `VERIFIED` instruction, and it fires
        only once the round trip has reached its ceiling".

        Design: Difficulty/cross_entity_state_dependency/money_movement_authorization_depends_on_standing_instruction_state
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("MONEY_MOVEMENT", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-106003")
        instruction = setup_verified_standing_instruction(
            account["id"], household["id"], periodic_limit_cents=5_000_000,
        )
        validate_success(api_client.set_clock({"current_utc": "2026-09-07T00:00:00Z"},
                                              TEST_USERS["admin_headers"]), 200)
        assert validate_success(
            api_client.get_standing_instruction(instruction["id"], ADVISOR), 200
        )["round_trip_days"] == 6

        res = api_client.expire_check_standing_instruction(instruction["id"], {}, CUSTODY, row=refetch_instruction(instruction["id"]))
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestStateBeforeSafety:

    def test_a_frozen_account_outranks_the_unverified_instruction(self):
        """PRD §3.8: "A movement against a frozen or otherwise ineligible account is
        refused with `ERR_ACCOUNT_NOT_ELIGIBLE` (HTTP 409)".
        PRD §2.1: "a request that violates more than one family always reports the
        earliest family in this list".

        Design: Difficulty/priority_pair_validation_conflict/money_movement_state_before_safety_pair
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("MONEY_MOVEMENT", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-102001")
        instruction = setup_verified_standing_instruction(
            account["id"], household["id"], periodic_limit_cents=500_000, verify=False,
        )
        movement = setup_submitted_movement(
            account["id"], instruction["id"], amount_cents=100_000, authorization_note="",
        )
        validate_success(api_client.freeze_account(account["id"], {}, COMPLIANCE, row=refetch_account(account["id"])), 200)

        res = authorize_movement_as_client(movement["id"], household["id"])
        validate_error(res, "ERR_ACCOUNT_NOT_ELIGIBLE", expected_status=409)

    def test_the_other_two_failures_do_not_win_the_race(self):
        """PRD §3.8: "The two-priority residual is deliberate and is pinned in that
        order — account eligibility first, then the verification rules, then the
        note and limit constraints".

        Design: Difficulty/priority_pair_validation_conflict/money_movement_state_before_safety_pair
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("MONEY_MOVEMENT", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-102002")
        instruction = setup_verified_standing_instruction(
            account["id"], household["id"], periodic_limit_cents=500_000, verify=False,
        )
        movement = setup_submitted_movement(
            account["id"], instruction["id"], amount_cents=100_000, authorization_note="",
        )
        validate_success(api_client.freeze_account(account["id"], {}, COMPLIANCE, row=refetch_account(account["id"])), 200)

        error = validate_error(
            authorize_movement_as_client(movement["id"], household["id"]),
            "ERR_ACCOUNT_NOT_ELIGIBLE", expected_status=409,
        )
        assert error["error_id"] != "ERR_STANDING_INSTRUCTION_NOT_VERIFIED"
        assert error["error_id"] != "ERR_AUTHORIZATION_NOTE_REQUIRED"
        assert validate_success(
            api_client.get_money_movement(movement["id"], ADVISOR), 200
        )["movement_status"] == "PENDING_AUTHORIZATION"
        assert validate_success(
            api_client.get_account(account["id"], ADVISOR), 200
        )["account_status"] == "FROZEN"
