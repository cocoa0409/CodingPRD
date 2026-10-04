"""Alternative-asset valuation, the account listing dimension and fee-basis filtering."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    setup_firm_with_agreement,
    setup_household,
    open_account,
    refetch_account,
    refetch_household,
    setup_listed_account,
    refetch_alternative,
)
"""Alternative-asset valuation, the account listing dimension and fee-basis filtering."""
"""Alternative-asset valuation, the account listing dimension and fee-basis filtering."""

ADVISOR = TEST_USERS["advisor_ops_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestAlternativeValuation:

    def test_the_aged_haircut_is_applied_and_the_floor_binds(self):
        """PRD §3.5: "the accepted value is the holding's stated value reduced by the
        applicable haircut percentage, then clamped so that it is never below
        `valuation_floor_cents` and never above `stated_value_cents`."
        PRD §3.5: "A valuation at or under the 270-day threshold is subject to a
        2500-basis-point haircut".

        Design: Corner/calculations/alt_haircut_honours_floor_and_caps_at_stated_value
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("ALTERNATIVE_ASSETS", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-115100")

        floor_holding = validate_success(api_client.create_alternative(
            {"account_id": account["id"], "asset_name": "Harbour Lane Credit Fund III",
             "unit_count": 10, "stated_value_cents": 40_000_000,
             "valuation_floor_cents": 32_000_000, "valuation_as_of_date": "2026-08-15T00:00:00Z"},
            ADVISOR,
        ), 201)
        validate_success(api_client.submit_valuation(floor_holding["id"], {}, ADVISOR, row=floor_holding), 200)
        accepted_floor = validate_success(
            api_client.accept_valuation(floor_holding["id"], {}, COMPLIANCE, row=refetch_alternative(floor_holding["id"])), 200
        )
        assert accepted_floor["accepted_value_cents"] == 32_000_000
        assert accepted_floor["haircut_pct"] == 2500

        hair_holding = validate_success(api_client.create_alternative(
            {"account_id": account["id"], "asset_name": "Harbour Lane Value Fund IV",
             "unit_count": 10, "stated_value_cents": 40_000_000,
             "valuation_floor_cents": 1000, "valuation_as_of_date": "2026-08-15T00:00:00Z"},
            ADVISOR,
        ), 201)
        validate_success(api_client.submit_valuation(hair_holding["id"], {}, ADVISOR, row=hair_holding), 200)
        accepted_hair = validate_success(
            api_client.accept_valuation(hair_holding["id"], {}, COMPLIANCE, row=refetch_alternative(hair_holding["id"])), 200
        )
        assert accepted_hair["accepted_value_cents"] == 30_000_000
        assert accepted_hair["haircut_pct"] == 2500

    def test_both_accepted_holdings_reach_the_household_fee_basis(self):
        """PRD §3.6: "The alternative basis is the sum of `accepted_value_cents` over
        the account's alternative holdings that are `ACCEPTED` and not stale."

        Design: Corner/calculations/alt_haircut_honours_floor_and_caps_at_stated_value
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("ALTERNATIVE_ASSETS", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-115101")
        for name, floor in (("Harbour Lane Credit Fund III", 32_000_000), ("Harbour Lane Value Fund IV", 1000)):
            holding = validate_success(api_client.create_alternative(
                {"account_id": account["id"], "asset_name": name, "unit_count": 10,
                 "stated_value_cents": 40_000_000, "valuation_floor_cents": floor,
                 "valuation_as_of_date": "2026-08-15T00:00:00Z"},
                ADVISOR,
            ), 201)
            validate_success(api_client.submit_valuation(holding["id"], {}, ADVISOR, row=holding), 200)
            validate_success(api_client.accept_valuation(holding["id"], {}, COMPLIANCE, row=refetch_alternative(holding["id"])), 200)

        assert refetch_household(household["id"])["household_fee_basis_cents"] == 62_000_000

    def test_a_271_day_valuation_is_refused_as_stale(self):
        """PRD §3.5: "The valuation age must be at most 270 days — a holding older
        than that may not be admitted to the fee basis at all, and is refused with
        `ERR_VALUATION_STALE` (HTTP 422)."

        Design: Corner/validations/valuation_age_271_days_is_rejected_and_270_is_accepted
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("ALTERNATIVE_ASSETS", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-115102")
        holding = validate_success(api_client.create_alternative(
            {"account_id": account["id"], "asset_name": "Coastal Infrastructure Fund V",
             "unit_count": 5, "stated_value_cents": 20_000_000,
             "valuation_floor_cents": 30_000_000, "valuation_as_of_date": "2025-12-04T00:00:00Z"},
            ADVISOR,
        ), 201)
        submitted = validate_success(api_client.submit_valuation(holding["id"], {}, ADVISOR, row=holding), 200)
        assert submitted["valuation_age_days"] == 271
        assert submitted["stale_valuation"] is True

        res = api_client.accept_valuation(holding["id"], {}, COMPLIANCE, row=refetch_alternative(holding["id"]))
        validate_error(res, "ERR_VALUATION_STALE", expected_status=422)

    def test_a_stale_holding_never_enters_the_basis_despite_the_lower_failure(self):
        """PRD §3.5: "A holding older than the 270-day threshold is never admitted:
        `accepted_value_cents` stays null and `stale_valuation` becomes true, which
        removes the holding from the fee-basis aggregation even if a later call
        re-supplies a value."
        PRD §2.1: "a request that violates more than one family always reports the
        earliest family in this list".

        Design: Corner/validations/valuation_age_271_days_is_rejected_and_270_is_accepted
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("ALTERNATIVE_ASSETS", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-115103")
        holding = validate_success(api_client.create_alternative(
            {"account_id": account["id"], "asset_name": "Coastal Infrastructure Fund V",
             "unit_count": 5, "stated_value_cents": 20_000_000,
             "valuation_floor_cents": 30_000_000, "valuation_as_of_date": "2025-12-04T00:00:00Z"},
            ADVISOR,
        ), 201)
        validate_success(api_client.submit_valuation(holding["id"], {}, ADVISOR, row=holding), 200)
        error = validate_error(
            api_client.accept_valuation(holding["id"], {}, COMPLIANCE, row=refetch_alternative(holding["id"])),
            "ERR_VALUATION_STALE", expected_status=422,
        )
        assert error["error_id"] != "ERR_VALUATION_BELOW_FLOOR"

        unchanged = validate_success(
            api_client.get_alternative(holding["id"], ADVISOR), 200
        )
        assert unchanged["accepted_value_cents"] is None
        assert unchanged["fee_basis_eligible"] is False
        assert refetch_household(household["id"])["household_fee_basis_cents"] == 0


class TestBasisInputSetFiltering:

    def test_only_accepted_non_stale_alternatives_and_billable_accounts_count(self):
        """PRD §3.6: "An account contributes to the household basis only when its
        `account_status` is `OPEN` or `FROZEN`, when its `billable` flag is true, and
        when the firm's posture is `OPEN` or `LIMITED`. Accounts in `PENDING` or
        `CLOSED` are excluded; `ENTITY` accounts are excluded by their `billable`
        flag".

        Design: Corner/calculations/excluded_alternative_and_stale_sleeves_do_not_enter_fee_basis
        """
        firm, agreement = setup_firm_with_agreement(
            entitlement_codes=("BILLING", "ALTERNATIVE_ASSETS")
        )
        household = setup_household(firm["id"])
        open_account_id = open_account(household["id"], firm["id"], "RIA-115200")
        entity_account = open_account(
            household["id"], firm["id"], "RIA-115201",
            account_type="ENTITY", householding_consent="NONE",
        )
        closed_account = open_account(household["id"], firm["id"], "RIA-115202", account_type="JOINT")
        validate_success(api_client.close_account(closed_account["id"], {}, CUSTODY, row=closed_account), 200)

        holding = validate_success(api_client.create_alternative(
            {"account_id": open_account_id["id"], "asset_name": "Meridian Real Assets Fund II",
             "unit_count": 20, "stated_value_cents": 50_000_000,
             "valuation_floor_cents": 30_000_000, "valuation_as_of_date": "2026-08-01T00:00:00Z"},
            ADVISOR,
        ), 201)
        validate_success(api_client.submit_valuation(holding["id"], {}, ADVISOR, row=holding), 200)
        accepted = validate_success(api_client.accept_valuation(holding["id"], {}, COMPLIANCE, row=refetch_alternative(holding["id"])), 200)
        assert accepted["asset_acceptance_status"] == "ACCEPTED"
        assert accepted["valuation_age_days"] == 31
        assert accepted["stale_valuation"] is False
        assert accepted["accepted_value_cents"] == 37_500_000
        assert accepted["fee_basis_eligible"] is True

        assert refetch_account(entity_account["id"])["billable"] is False
        assert refetch_account(closed_account["id"])["account_status"] == "CLOSED"
        assert refetch_household(household["id"])["household_fee_basis_cents"] == 37_500_000


class TestAccountListingCooldown:

    def test_a_first_listing_is_unrestricted_and_the_second_collides(self):
        """PRD §3.3: "Listing is a separate, parallel dimension of an account's state
        that advances while the lifecycle dimension stands still."
        PRD §3.3: "it is cooldown-guarded: a listing requested inside the account's
        one-hour listing window is refused with `ERR_LISTING_COOLDOWN` (HTTP 409)."

        Design: Corner/validations/listing_cooldown_absent_until_a_first_listing_exists
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-108100")
        assert refetch_account(account["id"])["last_listed_at"] is None

        first = validate_success(api_client.list_account(account["id"], {}, ADVISOR, row=refetch_account(account["id"])), 200)
        assert first["last_listed_cents"] == 0
        assert first["last_listed_at"] == "2026-09-01T00:00:00.000Z"

        res = api_client.list_account(account["id"], {}, ADVISOR, row=refetch_account(account["id"]))
        validate_error(res, "ERR_LISTING_COOLDOWN", expected_status=409)
        assert refetch_account(account["id"])["last_listed_at"] == "2026-09-01T00:00:00.000Z"

    def test_the_one_hour_boundary_is_half_open(self):
        """PRD §3.3: "The window is the half-open interval from the account's previous
        `last_listed_at` up to but not including one hour after it, and the request
        acknowledges which calendar slot it is claiming by way of the account's
        conditional-request token."

        Design: Difficulty/resource_temporal_overlap/account_listing_slot_cooldown_gap_semantics
        """
        scenario = setup_listed_account()
        account_id = scenario["account"]["id"]

        first = validate_success(api_client.list_account(account_id, {}, ADVISOR, row=refetch_account(account_id)), 200)
        assert first["last_listed_cents"] == 100_000_000

        validate_success(api_client.set_clock({"current_utc": "2026-09-01T00:59:59Z"}, ADMIN), 200)
        res = api_client.list_account(account_id, {}, ADVISOR, row=refetch_account(account_id))
        validate_error(res, "ERR_LISTING_COOLDOWN", expected_status=409)

        validate_success(api_client.set_clock({"current_utc": "2026-09-01T01:00:00Z"}, ADMIN), 200)
        second = validate_success(api_client.list_account(account_id, {}, ADVISOR, row=refetch_account(account_id)), 200)
        assert second["last_listed_at"] == "2026-09-01T01:00:00.000Z"

    def test_the_listing_advances_without_touching_the_lifecycle_state(self):
        """PRD §3.3: "An `AdvisorOperationsLead` may run a listing against an account
        in `PENDING`, `OPEN` or `FROZEN`; the lifecycle state is unchanged by the
        operation. Listing recomputes the account's presented value and writes the
        traditional sleeve into `last_listed_cents` and the run's instant into
        `last_listed_at`."

        Design: Difficulty/resource_temporal_overlap/account_listing_slot_cooldown_gap_semantics
        """
        scenario = setup_listed_account()
        account_id = scenario["account"]["id"]
        before = refetch_account(account_id)
        assert before["account_status"] == "OPEN"

        listed = validate_success(api_client.list_account(account_id, {}, ADVISOR, row=refetch_account(account_id)), 200)
        assert listed["account_status"] == "OPEN"
        assert listed["last_listed_cents"] == 100_000_000
        assert listed["last_listed_at"] == "2026-09-01T00:00:00.000Z"


class TestAccountTypeEnumeration:

    def test_an_unsupported_account_type_is_refused(self):
        """PRD §3.3: "The permitted `account_type` values are `INDIVIDUAL`, `JOINT`,
        `TRUST`, `IRA`, `ROTH_IRA` and `ENTITY`".

        Design: Corner/entities/account_type_enum_and_frozen_rejection_of_listing
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household = setup_household(firm["id"])

        res = api_client.create_account(
            {"household_id": household["id"], "firm_id": firm["id"],
             "account_number": "RIA-113100", "account_type": "CRYPTO_VAULT",
             "householding_consent": "OP_IN"},
            ADVISOR,
        )
        assert res.status_code >= 400, "an undeclared account_type must not be accepted"
        assert res.json().get("response_type") == "error"

        accepted = validate_success(api_client.create_account(
            {"household_id": household["id"], "firm_id": firm["id"],
             "account_number": "RIA-113101", "account_type": "ROTH_IRA",
             "householding_consent": "OP_IN"},
            ADVISOR,
        ), 201)
        assert accepted["account_type"] == "ROTH_IRA"
        assert accepted["account_status"] == "PENDING"

    def test_the_rejected_type_leaves_no_row_behind(self):
        """PRD §3.3: "A new account begins at `account_status` `PENDING`".
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects."

        Design: Corner/entities/account_type_enum_and_frozen_rejection_of_listing
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household = setup_household(firm["id"])
        api_client.create_account(
            {"household_id": household["id"], "firm_id": firm["id"],
             "account_number": "RIA-113200", "account_type": "CRYPTO_VAULT",
             "householding_consent": "OP_IN"},
            ADVISOR,
        )
        validate_success(api_client.create_account(
            {"household_id": household["id"], "firm_id": firm["id"],
             "account_number": "RIA-113201", "account_type": "ROTH_IRA",
             "householding_consent": "OP_IN"},
            ADVISOR,
        ), 201)

        rows = validate_success(
            api_client.list_accounts(ADVISOR, params={"household_id": household["id"]}), 200
        )
        assert len(rows) == 1
        assert rows[0]["account_type"] == "ROTH_IRA"