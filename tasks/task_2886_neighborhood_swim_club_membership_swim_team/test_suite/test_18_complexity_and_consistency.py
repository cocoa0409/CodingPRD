"""Optimistic concurrency on the two ledger-bearing writes, and immediate visibility.

The two version guards are the whole of this API's concurrency story, so each is
driven three ways: the fresh token is accepted, the replayed token is refused
with a 412 that moves nothing, and the refreshed token is accepted again. The
last class then shows that a write's own response already carries every figure a
follow-up read will report.
"""

from test_helpers import (
    AccessStatus,
    ApiErrorId,
    DuesStatus,
    GuestSettlementPolicy,
    GuestVisitStatus,
    ProjectKind,
    ProjectStatus,
    canonical_instant,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    fund_project_payload,
    guest_visit_payload,
    transition_payload,
)
from test_helpers.test_users import BOARD_PRESIDENT, POOL_MANAGER, TREASURER

OCC_CLOCK = "2027-07-01T09:00:00Z"
VISIT_INSTANT = "2027-06-25T14:00:00Z"
WEEKDAY_FEE_CENTS = 500
COUPLE_PASSES = 2
RESERVE_CONTRIBUTION = 300000
PROJECT_BUDGET = 250000
FIRST_DRAW = 100000
OVERDRAWING_DRAW = 200000


def _a_two_pass_household_at_the_gate(api):
    """A COUPLE membership, invoiced and ACTIVE, holding exactly two passes."""
    season = fx.setup_open_season(
        api, clock_iso=OCC_CLOCK,
        guest_settlement_policy=GuestSettlementPolicy.PASS_FIRST,
    )
    category = fx.create_couple_category(api)
    household = fx.create_household(api,
                                    primary_contact_name="Occ Guest Household",
                                    address_line="381 Cedar Court",
                                    member_count=2)
    membership = fx.setup_membership(api, household["id"], category["id"],
                                     season["id"], join_date="2027-06-01")
    fx.invoice_membership(api, membership["id"])
    return {"season": season, "category": category, "membership": membership,
            "household": fx.read_household(api, household["id"])}


def _sign_in(api, membership_id, expected_household_version, sponsor_name,
             guest_count=1):
    return api.create_guest_visit(
        guest_visit_payload(
            membership_id=membership_id,
            expected_household_version=expected_household_version,
            sponsor_name=sponsor_name, guest_count=guest_count,
            visit_start_iso=VISIT_INSTANT,
        ),
        POOL_MANAGER,
    )


def _visits_of(api, membership_id):
    rows, meta = validate_paginated(
        api.list_guest_visits(POOL_MANAGER, {"membership_id": membership_id})
    )
    return rows, meta


class TestAStaleHouseholdVersionCannotSpendAPassTwice:
    """The gate's OCC token is part of the contract, not an optimisation."""

    def test_the_household_holds_the_category_allotment_before_any_visit(self, api):
        """Two passes are in hand the moment the membership is sold.

        PRD §3.3: "The household's `guest_pass_allotment_granted` rises by the
        category's `guest_pass_allotment` and its `guest_pass_balance` rises by the
        same number, so the passes are in hand before the gate ever opens."

        PRD §3.5: "a household's `guest_pass_balance` plus its
        `guest_passes_consumed` always equals its `guest_pass_allotment_granted`"

        PRD §3.3: "A membership is born with `dues_status` `UNBILLED` and
        `access_status` `PENDING`."

        Design: Corner/complexity_layers/optimistic_concurrency_a_stale_household_version_cannot_spend_a_pass_twice
        """
        ctx = _a_two_pass_household_at_the_gate(api)

        household = ctx["household"]
        assert household["guest_pass_allotment_granted"] == COUPLE_PASSES
        assert household["guest_passes_consumed"] == 0
        assert household["guest_pass_balance"] == COUPLE_PASSES
        assert ctx["membership"]["access_status"] == AccessStatus.PENDING

    def test_the_first_sign_in_spends_one_pass_and_moves_the_household(self, api):
        """Recording a visit is a household write, so the household's version moves.

        PRD §3.5: "Under the `PASS_FIRST` variant, `passes_used` is the smaller of
        the household's current `guest_pass_balance` and the visit's `guest_count`,
        on every day of the week alike."

        PRD §2.4: "When admitting a guest changes the sponsoring household's pass
        balance, the household's `version` moves as well as the visit's."

        PRD §3.5: "the season's `guest_settlement_policy`, which is copied onto the
        visit as its `settlement_variant` so the historical record survives a later
        policy change"

        Design: Corner/complexity_layers/optimistic_concurrency_a_stale_household_version_cannot_spend_a_pass_twice
        """
        ctx = _a_two_pass_household_at_the_gate(api)
        before = ctx["household"]

        visit = validate_success(
            _sign_in(api, ctx["membership"]["id"], before["version"],
                     "First Sign In"),
            201,
        )
        assert visit["settlement_variant"] == GuestSettlementPolicy.PASS_FIRST
        assert visit["passes_used"] == 1
        assert visit["fee_charged_cents"] == 0

        after = fx.read_household(api, before["id"])
        assert after["version"] == before["version"] + 1
        assert after["guest_passes_consumed"] == 1
        assert after["guest_pass_balance"] == 1

    def test_the_replayed_token_is_refused_and_bumps_nothing(self, api):
        """A second sign-in from the same screenshot is a 412, not a 409 or a 422.

        PRD §2.7: "If `expected_household_version` does not equal that household's
        current `version`, the visit is not recorded and the request is rejected with
        `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412)."

        PRD §3.5: "Recording a visit whose `expected_household_version` does not equal
        the sponsoring household's current `version` is rejected with
        `ERR_STALE_HOUSEHOLD_VERSION`, and nothing about the household's pass ledger
        changes."

        Design: Corner/complexity_layers/optimistic_concurrency_a_stale_household_version_cannot_spend_a_pass_twice
        """
        ctx = _a_two_pass_household_at_the_gate(api)
        stale = ctx["household"]["version"]
        first = validate_success(
            _sign_in(api, ctx["membership"]["id"], stale, "First Sign In"), 201
        )
        fresh = fx.read_household(api, ctx["household"]["id"])

        validate_error(
            _sign_in(api, ctx["membership"]["id"], stale,
                     "Second Sign In From A Stale Screen"),
            ApiErrorId.STALE_HOUSEHOLD_VERSION, 412,
        )

        unmoved = fx.read_household(api, ctx["household"]["id"])
        assert unmoved["version"] == fresh["version"]
        assert unmoved["guest_passes_consumed"] == 1
        assert unmoved["guest_pass_balance"] == 1
        rows, meta = _visits_of(api, ctx["membership"]["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

    def test_the_retry_with_the_refreshed_token_spends_the_second_pass(self, api):
        """Exactly two of the two passes are spent, never three.

        PRD §2.7: "Recording several visits for the same household in sequence is
        entirely legitimate, so no state precondition blocks a repeated request"

        PRD §3.5: "The household's ledgers then move together: `guest_pass_balance`
        falls by `passes_used`, `guest_passes_consumed` rises by `passes_used`, and
        `guest_fee_owed_cents` rises by `fee_charged_cents`."

        Design: Corner/complexity_layers/optimistic_concurrency_a_stale_household_version_cannot_spend_a_pass_twice
        """
        ctx = _a_two_pass_household_at_the_gate(api)
        stale = ctx["household"]["version"]
        first = validate_success(
            _sign_in(api, ctx["membership"]["id"], stale, "First Sign In"), 201
        )
        fresh = fx.read_household(api, ctx["household"]["id"])
        validate_error(
            _sign_in(api, ctx["membership"]["id"], stale,
                     "Second Sign In From A Stale Screen"),
            ApiErrorId.STALE_HOUSEHOLD_VERSION, 412,
        )

        second = validate_success(
            _sign_in(api, ctx["membership"]["id"], fresh["version"],
                     "Second Sign In Retried"),
            201,
        )
        assert second["passes_used"] == 1
        assert second["fee_charged_cents"] == 0

        final = fx.read_household(api, ctx["household"]["id"])
        assert final["version"] == fresh["version"] + 1
        assert final["guest_passes_consumed"] == COUPLE_PASSES
        assert final["guest_pass_balance"] == 0
        assert final["guest_fee_owed_cents"] == 0
        rows, meta = _visits_of(api, ctx["membership"]["id"])
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}


def _an_approved_project_against_a_funded_reserve(api):
    """A 250000 project approved by a second pair of eyes over a 300000 reserve."""
    season = fx.setup_open_season(api, clock_iso=OCC_CLOCK)
    funded_season = fx.contribute_reserve(api, season["id"], RESERVE_CONTRIBUTION)
    proposed = fx.propose_project(api, season["id"], PROJECT_BUDGET,
                                 title="Replace the circulation pump",
                                 project_kind=ProjectKind.PUMP_REPLACEMENT)
    project = validate_success(
        api.transition_capital_project(
            proposed["id"], transition_payload(ProjectStatus.APPROVED),
            BOARD_PRESIDENT,
        ),
        200,
    )
    return {"season": funded_season, "project": project}


def _draw(api, project_id, draw_amount_cents, expected_version):
    return api.fund_capital_project(
        project_id,
        fund_project_payload(
            draw_amount_cents=draw_amount_cents,
            expected_capital_project_version=expected_version,
        ),
        TREASURER,
    )


class TestAStaleProjectVersionCannotOverdrawTheReserve:
    """The token guards a figure the request itself cannot see."""

    def test_the_reserve_and_the_project_start_from_pinned_figures(self, api):
        """An approved project holds no money, and the whole reserve is unallocated.

        PRD §3.10: "both `reserve_contributions_cents` and `reserve_unallocated_cents`
        rise by that amount and the season's `version` advances"

        PRD §3.10: "Projects in `PROPOSED`, `APPROVED` or `REJECTED` contribute nothing
        to the allocated side because they hold no money"

        Design: Corner/complexity_layers/optimistic_concurrency_a_stale_project_version_cannot_overdraw_the_reserve
        """
        ctx = _an_approved_project_against_a_funded_reserve(api)

        assert ctx["season"]["reserve_contributions_cents"] == RESERVE_CONTRIBUTION
        assert ctx["season"]["reserve_unallocated_cents"] == RESERVE_CONTRIBUTION
        assert ctx["project"]["status"] == ProjectStatus.APPROVED
        assert ctx["project"]["funded_cents"] == 0
        assert ctx["project"]["budget_cents"] == PROJECT_BUDGET

    def test_the_first_draw_funds_the_project_and_moves_both_rows(self, api):
        """Money crosses the identity: allocated rises as unallocated falls.

        PRD §3.10: "A draw that passes raises `funded_cents` by the drawn amount and
        lowers `reserve_unallocated_cents` by the same amount while leaving
        `reserve_contributions_cents` untouched — money moves across the identity, it
        is not created or destroyed — and advances both the project's `version` and the
        season's `version`."

        PRD §3.10: "The first successful draw against an `APPROVED` project also moves
        it to `FUNDED`; subsequent draws leave it there."

        Design: Corner/complexity_layers/optimistic_concurrency_a_stale_project_version_cannot_overdraw_the_reserve
        """
        ctx = _an_approved_project_against_a_funded_reserve(api)
        project = ctx["project"]

        drawn = validate_success(
            _draw(api, project["id"], FIRST_DRAW, project["version"]), 200
        )
        assert drawn["status"] == ProjectStatus.FUNDED
        assert drawn["funded_cents"] == FIRST_DRAW
        assert drawn["version"] == project["version"] + 1

        season = fx.read_season(api, ctx["season"]["id"])
        assert season["reserve_contributions_cents"] == RESERVE_CONTRIBUTION
        assert season["reserve_unallocated_cents"] == (
            RESERVE_CONTRIBUTION - FIRST_DRAW
        )

    def test_a_replayed_project_version_is_refused_though_the_money_would_have_fitted(self, api):
        """The 412 is about staleness, not about the amount.

        PRD §2.7: "If it does not equal the project's current `version`, no draw is
        made and the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        PRD §2.9: "**Stale-version guards**, as described in §2.7 —
        `ERR_STALE_HOUSEHOLD_VERSION` then `ERR_STALE_PROJECT_VERSION`, both HTTP 412."

        Design: Corner/complexity_layers/optimistic_concurrency_a_stale_project_version_cannot_overdraw_the_reserve
        """
        ctx = _an_approved_project_against_a_funded_reserve(api)
        stale = ctx["project"]["version"]
        drawn = validate_success(
            _draw(api, ctx["project"]["id"], FIRST_DRAW, stale), 200
        )

        validate_error(_draw(api, ctx["project"]["id"], FIRST_DRAW, stale),
                       ApiErrorId.STALE_PROJECT_VERSION, 412)

        unmoved = fx.read_project(api, ctx["project"]["id"])
        assert unmoved["version"] == drawn["version"]
        assert unmoved["funded_cents"] == FIRST_DRAW
        season = fx.read_season(api, ctx["season"]["id"])
        assert season["reserve_unallocated_cents"] == (
            RESERVE_CONTRIBUTION - FIRST_DRAW
        )

    def test_the_stale_guard_is_evaluated_before_the_budget_ceiling(self, api):
        """A draw that would also have breached the budget still answers 412.

        PRD §2.9: "**Stale-version guards**, as described in §2.7 —
        `ERR_STALE_HOUSEHOLD_VERSION` then `ERR_STALE_PROJECT_VERSION`, both HTTP 412."

        PRD §2.9: "**Fiscal, last of all**, in this internal order: household
        delinquency (`ERR_DUES_DELINQUENT`, 402), an unsettled bond before a party may
        be booked (`ERR_BOND_NOT_PAID`, 402), a payment exceeding the counter it
        settles (`ERR_PAYMENT_EXCEEDS_BALANCE`, 422), a reserve draw exceeding the
        unallocated reserve (`ERR_INSUFFICIENT_RESERVE`, 402) and a draw exceeding the
        project's budget (`ERR_DRAW_EXCEEDS_BUDGET`, 422)."

        Design: Corner/complexity_layers/optimistic_concurrency_a_stale_project_version_cannot_overdraw_the_reserve
        """
        ctx = _an_approved_project_against_a_funded_reserve(api)
        stale = ctx["project"]["version"]
        validate_success(_draw(api, ctx["project"]["id"], FIRST_DRAW, stale), 200)
        assert FIRST_DRAW + OVERDRAWING_DRAW > PROJECT_BUDGET

        validate_error(_draw(api, ctx["project"]["id"], OVERDRAWING_DRAW, stale),
                       ApiErrorId.STALE_PROJECT_VERSION, 412)

        assert fx.read_project(api, ctx["project"]["id"])["funded_cents"] == FIRST_DRAW

    def test_the_refreshed_token_draws_again_and_the_identity_survives(self, api):
        """A 412 in the middle of a funding sequence leaves the identity exact.

        PRD §3.10: "`reserve_unallocated_cents` plus the sum of `funded_cents` over the
        season's capital projects in `FUNDED`, `IN_PROGRESS` or `COMPLETED` always
        equals `reserve_contributions_cents`."

        PRD §3.10: "A draw does not reduce it, a project cancellation does not reduce
        it, and writing off a delinquent membership's dues does not claw back a
        contribution already booked from that membership."

        Design: Corner/complexity_layers/optimistic_concurrency_a_stale_project_version_cannot_overdraw_the_reserve
        """
        ctx = _an_approved_project_against_a_funded_reserve(api)
        stale = ctx["project"]["version"]
        first = validate_success(
            _draw(api, ctx["project"]["id"], FIRST_DRAW, stale), 200
        )
        validate_error(_draw(api, ctx["project"]["id"], FIRST_DRAW, stale),
                       ApiErrorId.STALE_PROJECT_VERSION, 412)

        second = validate_success(
            _draw(api, ctx["project"]["id"], FIRST_DRAW, first["version"]), 200
        )
        assert second["funded_cents"] == FIRST_DRAW * 2
        assert second["version"] == first["version"] + 1

        season = fx.read_season(api, ctx["season"]["id"])
        assert season["reserve_contributions_cents"] == RESERVE_CONTRIBUTION
        assert season["reserve_unallocated_cents"] == (
            RESERVE_CONTRIBUTION - FIRST_DRAW * 2
        )
        assert (season["reserve_unallocated_cents"] + second["funded_cents"]
                == season["reserve_contributions_cents"])

IMMEDIATE_DUES = 30000
IMMEDIATE_PENALTY = 1050
IMMEDIATE_TOTAL = IMMEDIATE_DUES + IMMEDIATE_PENALTY
IMMEDIATE_GUEST_COUNT = 3


def _a_household_whose_paperwork_is_written_in_one_pass(api):
    """A COUPLE membership joined on the open date, so full dues are assessed."""
    season = fx.setup_open_season(
        api, clock_iso=OCC_CLOCK,
        guest_settlement_policy=GuestSettlementPolicy.PASS_FIRST,
    )
    category = fx.create_couple_category(api)
    household = fx.create_household(api,
                                    primary_contact_name="Immediate Household",
                                    address_line="391 Cedar Court",
                                    member_count=2)
    membership = fx.setup_membership(api, household["id"], category["id"],
                                     season["id"], join_date=season["open_date"])
    return {"season": season, "category": category, "household": household,
            "membership": membership}


class TestEveryWriteIsVisibleInItsOwnResponseAndTheNextRead:
    """No write defers a recomputation to a later read."""

    def test_the_creation_response_already_carries_the_assessed_dues(self, api):
        """Selling the membership stamps the assessment there and then.

        PRD §3.3: "A membership is born with `dues_status` `UNBILLED` and
        `access_status` `PENDING`."

        PRD §3.3: "`assessed_dues_cents` is stamped exactly once, while the membership
        is still `UNBILLED`, and is never re-derived."

        PRD §3.3: "if the effective start is at or before the season's `open_date`, the
        household is charged the category's full `seasonal_dues_cents` with no proration
        whatsoever"

        Design: Corner/consistency_model/immediate_every_write_is_visible_in_its_own_response_and_the_next_read
        """
        ctx = _a_household_whose_paperwork_is_written_in_one_pass(api)

        created = ctx["membership"]
        assert created["dues_status"] == DuesStatus.UNBILLED
        assert created["access_status"] == AccessStatus.PENDING
        assert created["assessed_dues_cents"] == IMMEDIATE_DUES

        assert fx.read_membership(api, created["id"]) == created

    def test_the_invoice_response_already_carries_every_recomputed_field(self, api):
        """The caller need not re-read to learn the penalty, total and balance.

        PRD §3.4: "when the logical clock's date is strictly later than the season's
        `dues_due_date`, the penalty is that base multiplied by three and one half per
        cent, rounded half up to a whole cent"

        PRD §3.4: "`invoice_total_cents` is the penalty base plus the penalty."

        PRD §3.4: "`invoiced_at` is stamped with the logical clock"

        Design: Corner/consistency_model/immediate_every_write_is_visible_in_its_own_response_and_the_next_read
        """
        ctx = _a_household_whose_paperwork_is_written_in_one_pass(api)

        invoiced = fx.invoice_membership(api, ctx["membership"]["id"])
        assert invoiced["dues_status"] == DuesStatus.INVOICED
        assert invoiced["late_penalty_cents"] == IMMEDIATE_PENALTY
        assert invoiced["invoice_total_cents"] == IMMEDIATE_TOTAL
        assert invoiced["balance_due_cents"] == IMMEDIATE_TOTAL
        assert canonical_instant(invoiced["invoiced_at"]) == \
            canonical_instant(OCC_CLOCK)

    def test_the_read_immediately_after_the_invoice_is_field_for_field_identical(self, api):
        """The follow-up read adds nothing and changes nothing, version included.

        PRD §2.4: "every row the request actually changes has its own `version`
        incremented and its own `updated_at` refreshed"

        PRD §2.4: "Cascades are executed depth-first and to completion inside the
        originating request; there is no deferred or eventual processing."

        Design: Corner/consistency_model/immediate_every_write_is_visible_in_its_own_response_and_the_next_read
        """
        ctx = _a_household_whose_paperwork_is_written_in_one_pass(api)
        invoiced = fx.invoice_membership(api, ctx["membership"]["id"])

        reread = fx.read_membership(api, ctx["membership"]["id"])
        assert reread == invoiced
        assert reread["version"] == invoiced["version"]
        assert fx.read_membership(api, ctx["membership"]["id"]) == invoiced

    def test_the_visit_response_settles_the_party_before_it_returns(self, api):
        """Three guests against two passes: the split is reported by the write itself.

        PRD §3.5: "Under the `PASS_FIRST` variant, `passes_used` is the smaller of
        the household's current `guest_pass_balance` and the visit's `guest_count`,
        on every day of the week alike."

        PRD §3.5: "The billable guest count is `guest_count` less `passes_used`, and
        `fee_charged_cents` is that billable count multiplied by the unit fee; every
        term is an integer, so no rounding arises."

        PRD §3.5: "eight hundred cents per guest on a weekend, five hundred cents per
        guest on a weekday"

        PRD §3.5: "Voiding moves the visit `RECORDED → VOIDED`"

        Design: Corner/consistency_model/immediate_every_write_is_visible_in_its_own_response_and_the_next_read
        """
        ctx = _a_household_whose_paperwork_is_written_in_one_pass(api)
        fx.invoice_membership(api, ctx["membership"]["id"])
        household = fx.read_household(api, ctx["household"]["id"])

        visit = validate_success(
            _sign_in(api, ctx["membership"]["id"], household["version"],
                     "Immediate Party", guest_count=IMMEDIATE_GUEST_COUNT),
            201,
        )
        assert visit["status"] == GuestVisitStatus.RECORDED
        assert visit["passes_used"] == COUPLE_PASSES
        assert visit["fee_charged_cents"] == WEEKDAY_FEE_CENTS
        assert visit["settlement_variant"] == GuestSettlementPolicy.PASS_FIRST

    def test_the_household_read_straight_after_the_visit_shows_the_moved_ledger(self, api):
        """The sponsor's counters are already settled when the next read arrives.

        PRD §3.5: "The household's ledgers then move together: `guest_pass_balance`
        falls by `passes_used`, `guest_passes_consumed` rises by `passes_used`, and
        `guest_fee_owed_cents` rises by `fee_charged_cents`."

        PRD §3.5: "a household's `guest_pass_balance` plus its
        `guest_passes_consumed` always equals its `guest_pass_allotment_granted`"

        Design: Corner/consistency_model/immediate_every_write_is_visible_in_its_own_response_and_the_next_read
        """
        ctx = _a_household_whose_paperwork_is_written_in_one_pass(api)
        fx.invoice_membership(api, ctx["membership"]["id"])
        before = fx.read_household(api, ctx["household"]["id"])
        validate_success(
            _sign_in(api, ctx["membership"]["id"], before["version"],
                     "Immediate Party", guest_count=IMMEDIATE_GUEST_COUNT),
            201,
        )

        after = fx.read_household(api, ctx["household"]["id"])
        assert after["guest_passes_consumed"] == COUPLE_PASSES
        assert after["guest_pass_balance"] == 0
        assert after["guest_fee_owed_cents"] == WEEKDAY_FEE_CENTS
        assert after["version"] == before["version"] + 1
        assert (after["guest_pass_balance"] + after["guest_passes_consumed"]
                == after["guest_pass_allotment_granted"])

    def test_the_list_projection_agrees_with_the_detail_projection(self, api):
        """A membership reported through the collection carries the same figures.

        PRD §2.4: "every row the request actually changes has its own `version`
        incremented and its own `updated_at` refreshed"

        PRD §3.4: "`balance_due_cents` is at all times the membership's
        `invoice_total_cents` plus its `volunteer_buyout_cents` minus its
        `amount_paid_cents`, floored at 0 so it never goes negative."

        Design: Corner/consistency_model/immediate_every_write_is_visible_in_its_own_response_and_the_next_read
        """
        ctx = _a_household_whose_paperwork_is_written_in_one_pass(api)
        invoiced = fx.invoice_membership(api, ctx["membership"]["id"])

        rows, meta = validate_paginated(
            api.list_memberships(TREASURER,
                                 {"household_id": ctx["household"]["id"]})
        )
        assert meta["total_count"] == 1
        listed = rows[0]
        assert listed["id"] == invoiced["id"]
        assert listed["dues_status"] == DuesStatus.INVOICED
        assert listed["invoice_total_cents"] == IMMEDIATE_TOTAL
        assert listed["balance_due_cents"] == (
            listed["invoice_total_cents"] + listed["volunteer_buyout_cents"]
            - listed["amount_paid_cents"]
        )
        assert listed["version"] == invoiced["version"]

    def test_re_reading_the_visit_drifts_nowhere(self, api):
        """The settled visit is a fact, not a view recomputed per read.

        PRD §2.4: "Cascades are executed depth-first and to completion inside the
        originating request; there is no deferred or eventual processing."

        PRD §3.5: "the season's `guest_settlement_policy`, which is copied onto the
        visit as its `settlement_variant` so the historical record survives a later
        policy change"

        Design: Corner/consistency_model/immediate_every_write_is_visible_in_its_own_response_and_the_next_read
        """
        ctx = _a_household_whose_paperwork_is_written_in_one_pass(api)
        fx.invoice_membership(api, ctx["membership"]["id"])
        household = fx.read_household(api, ctx["household"]["id"])
        visit = validate_success(
            _sign_in(api, ctx["membership"]["id"], household["version"],
                     "Immediate Party", guest_count=IMMEDIATE_GUEST_COUNT),
            201,
        )

        assert fx.read_visit(api, visit["id"]) == visit
        assert fx.read_visit(api, visit["id"]) == visit
        rows, meta = _visits_of(api, ctx["membership"]["id"])
        assert meta["total_count"] == 1
        assert rows[0]["passes_used"] == COUPLE_PASSES
        assert rows[0]["fee_charged_cents"] == WEEKDAY_FEE_CENTS
