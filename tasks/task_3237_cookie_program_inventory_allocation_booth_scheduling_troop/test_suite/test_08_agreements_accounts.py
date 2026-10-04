"""Participant agreements, troop accounts, deposits, settlement, forfeiture."""
from test_helpers import (
    ApiErrorId,
    add_product,
    assert_participant_agreement,
    create_agreement,
    create_and_confirm_order,
    create_season,
    create_troop,
    create_troop_with_account,
    get_account,
    make_council_admin_headers,
    make_troop_leader_headers,
    open_season,
    set_clock,
    setup_open_season_with_supply,
    setup_selling_season,
    validate_error,
    validate_success,
)


class TestIncentiveTier:
    def test_incentive_tier_boundaries_inclusive(self, api):
        """PRD §3.7: "Each agreement also carries a computed `incentive_tier`
        driven by inclusive package thresholds: `GOLD` at one hundred or more
        assigned packages, `SILVER` at fifty or more, `BRONZE` at twenty or
        more, and `NONE` below that — exactly twenty packages earns `BRONZE`,
        while nineteen earns nothing."

        Design: Corner/calculations/incentive_tier_boundaries_inclusive
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        add_product(season["id"], admin=admin)
        open_season(season["id"], admin=admin)
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        ag19 = create_agreement(
            season["id"], troop, leader=leader,
            participant_name="Scout 19", parent_name="P19", assigned_packages=19,
        )
        assert_participant_agreement(ag19)
        assert ag19["incentive_tier"] == "NONE"
        ag20 = create_agreement(
            season["id"], troop, leader=leader,
            participant_name="Scout 20", parent_name="P20", assigned_packages=20,
        )
        assert ag20["incentive_tier"] == "BRONZE"


class TestSettlement:
    def test_underpaid_settle_rejected(self, api):
        """PRD §3.7: "Settling an agreement — from `PENDING` or `DISPUTED` —
        requires the supplied `settle_amount_cents` to cover the outstanding
        balance in full after the settle; partial payment is rejected with
        `ERR_UNDERPAID`."

        Design: Corner/validations/underpaid_settle_rejected
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        add_product(season["id"], admin=admin, unit_price_cents=600)
        open_season(season["id"], admin=admin)
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        agreement = create_agreement(
            season["id"], troop, leader=leader,
            assigned_packages=10, paid_amount_cents=0,
        )
        resp = api.settle_agreement(agreement["id"], {"settle_amount_cents": 5999}, leader)
        validate_error(resp, ApiErrorId.ERR_UNDERPAID, 422)
        settled = validate_success(
            api.settle_agreement(agreement["id"], {"settle_amount_cents": 6000}, leader)
        )
        assert settled["status"] == "PAID"


class TestForfeiture:
    def test_derived_field_reconciliation_uncollected_after_forfeit(self, api):
        """PRD §3.7: "a `CouncilAdmin` may forfeit an agreement in `PENDING` or
        `DISPUTED`, posting the full `outstanding_cents` at that moment as a
        charge against the troop account — parent responsibility is enforced at
        troop level — and dropping the agreement out of the uncollected
        total." PRD §3.7: "The `uncollected_amount_cents` counter is the sum of
        `outstanding_cents` over the troop's agreements in `PENDING` or
        `DISPUTED` status for the season, recomputed on every agreement
        mutation."

        Design: Corner/complexity_layers/derived_field_reconciliation_uncollected_after_forfeit
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        add_product(season["id"], admin=admin, unit_price_cents=600)
        open_season(season["id"], admin=admin)
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        agreement = create_agreement(
            season["id"], troop, leader=leader,
            assigned_packages=10, paid_amount_cents=0,
        )
        assert agreement["outstanding_cents"] == 6000
        validate_success(api.forfeit_agreement(agreement["id"], admin))
        acct = get_account(account["id"], admin=admin)
        assert acct["uncollected_amount_cents"] == 0
        assert acct["balance_cents"] == 6000


class TestDeposits:
    def test_deposit_credits_account(self, api):
        """PRD §3.7: "Deposits are recorded against an account by either role
        with an `amount_cents` and a `reference`; each deposit adds to
        `deposit_cents`, subtracts from `balance_cents`, and advances the
        account's `version`."

        Design: Corner/endpoints/deposit_credits_account
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(200, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        create_and_confirm_order(
            season["id"], troop, [(product["id"], 80)], leader=leader, admin=admin
        )
        deposited = validate_success(
            api.record_deposit(
                account["id"], {"amount_cents": 10000, "reference": "DEP-1"}, leader
            ),
            expected_status=201,
        )
        assert deposited["balance_cents"] == 38000
        assert deposited["deposit_cents"] == 10000
