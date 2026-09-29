"""Scope and money ceilings: credits, seasons, balances, reserves and budgets.

Each refusal here is separated from its neighbours by a fixture that satisfies
every adjacent rule, so a collapsed check cannot produce the same codes.
"""

from test_helpers import (
    AccessStatus,
    ApiErrorId,
    AssignmentStatus,
    DuesStatus,
    JobCode,
    ProjectStatus,
    RegistrationStatus,
    SeasonStatus,
    Squad,
    assertions as a,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    fund_project_payload,
    household_payment_payload,
    membership_payload,
    membership_payment_payload,
    registration_payload,
    transition_payload,
    volunteer_assignment_payload,
)
from test_helpers.test_users import (
    BOARD_PRESIDENT,
    MEMBERSHIP_CHAIR,
    SWIM_TEAM_COACH,
    TREASURER,
)

SCOPE_CLOCK = "2027-07-01T09:00:00Z"


def _two_meets_and_two_swimmers(api):
    """A tight two-credit roster and a roomy four-credit one, same household."""
    fx.set_clock(api, SCOPE_CLOCK)
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)
    household = fx.create_household(
        api, primary_contact_name="Roster Household",
        address_line="251 Cedar Court", member_count=4, prior_member=False,
    )
    membership = fx.setup_membership(api, household["id"], category["id"],
                                    season["id"], join_date="2027-06-01")
    membership = fx.invoice_membership(api, membership["id"])
    first = fx.register_swimmer(api, membership["id"], season["id"],
                                swimmer_name="Ines Roster",
                                swimmer_birthdate="2016-03-04",
                                squad=Squad.MINI)
    second = fx.register_swimmer(api, membership["id"], season["id"],
                                 swimmer_name="Jonas Roster",
                                 swimmer_birthdate="2017-05-06",
                                 squad=Squad.MINI)
    tight = fx.create_meet(api, season["id"], name="Tight Roster Invitational",
                           start_iso="2027-07-24T13:00:00Z",
                           end_iso="2027-07-24T18:00:00Z",
                           expected_swimmers=40, volunteer_slots_required=2)
    roomy = fx.create_meet(api, season["id"], name="Roomy Roster Classic",
                           start_iso="2027-07-31T13:00:00Z",
                           end_iso="2027-07-31T18:00:00Z",
                           expected_swimmers=60, volunteer_slots_required=4)
    return {"season": season, "household": household, "membership": membership,
            "first": first, "second": second, "tight": tight, "roomy": roomy}


def _attempt_assignment(api, meet_id, registration_id, job_code):
    return api.create_volunteer_assignment(
        volunteer_assignment_payload(
            meet_id=meet_id, swim_team_registration_id=registration_id,
            job_code=job_code,
        ),
        SWIM_TEAM_COACH,
    )


def _assignments_of(api, meet_id):
    rows, _ = validate_paginated(
        api.list_volunteer_assignments(SWIM_TEAM_COACH, {"meet_id": meet_id})
    )
    return rows


class TestMeetRosterCreditCeilingAndDuplicateJob:
    """Slots are credits, and the ceiling is checked before the duplicate rule."""

    def test_a_new_meet_starts_with_an_empty_credit_roster(self, api):
        """One scorer fills a two-credit roster on its own.

        PRD §3.6: "A new meet is `SCHEDULED`, with `volunteer_slots_filled` at 0,
        `roster_closed_at` null and `understaffed_penalty_cents` at 0."

        PRD §3.6: "a `credit_value` of 2 is stamped for `STARTER` and for
        `SCORER`, and of 1 for `TIMER`, `CONCESSIONS` and `MARSHAL`. **Slots are
        counted in credits, not in bodies, and a new assignment counts the instant
        it is created** — it is born `ASSIGNED` and immediately raises the meet's
        `volunteer_slots_filled` by its `credit_value`."

        Design: Corner/validations/violation_to_error_meet_roster_credit_ceiling_and_duplicate_job
        """
        ctx = _two_meets_and_two_swimmers(api)

        assert ctx["tight"]["volunteer_slots_required"] == 2
        assert ctx["tight"]["volunteer_slots_filled"] == 0
        assert ctx["membership"]["access_status"] == AccessStatus.ACTIVE
        assert ctx["first"]["status"] == RegistrationStatus.PENDING

        assignment = fx.assign_volunteer(api, ctx["tight"]["id"],
                                         ctx["first"]["id"], JobCode.SCORER)
        assert assignment["credit_value"] == 2
        assert assignment["status"] == AssignmentStatus.ASSIGNED
        assert fx.read_meet(api, ctx["tight"]["id"])["volunteer_slots_filled"] == 2

    def test_the_roster_is_full_in_credits_not_in_bodies(self, api):
        """One body of two has signed up and the roster is already closed out.

        PRD §3.6: "The meet may not be oversubscribed in credits: the meet's
        current `volunteer_slots_filled` plus the new job's credit value must not
        exceed `volunteer_slots_required`, and an attempt to go beyond is
        `ERR_VOLUNTEER_SLOTS_FULL`."

        Design: Corner/validations/violation_to_error_meet_roster_credit_ceiling_and_duplicate_job
        """
        ctx = _two_meets_and_two_swimmers(api)
        fx.assign_volunteer(api, ctx["tight"]["id"], ctx["first"]["id"],
                            JobCode.SCORER)

        validate_error(
            _attempt_assignment(api, ctx["tight"]["id"], ctx["second"]["id"],
                                JobCode.TIMER),
            ApiErrorId.VOLUNTEER_SLOTS_FULL, 409,
        )
        assert len(_assignments_of(api, ctx["tight"]["id"])) == 1
        assert fx.read_meet(api, ctx["tight"]["id"])["volunteer_slots_filled"] == 2

    def test_the_duplicate_rule_keys_on_the_registration_not_the_job(self, api):
        """With credits to spare, only the repeated swimmer can explain a refusal.

        PRD §3.6: "And a single registration may not hold two jobs at the same
        meet, so a registration that already has an assignment for this meet in
        `ASSIGNED` or `COMPLETED` is refused with
        `ERR_DUPLICATE_VOLUNTEER_ASSIGNMENT`."

        Design: Corner/validations/violation_to_error_meet_roster_credit_ceiling_and_duplicate_job
        """
        ctx = _two_meets_and_two_swimmers(api)
        first_job = fx.assign_volunteer(api, ctx["roomy"]["id"],
                                        ctx["first"]["id"], JobCode.SCORER)
        assert first_job["credit_value"] == 2
        assert ctx["roomy"]["volunteer_slots_required"] == 4

        body = validate_error(
            _attempt_assignment(api, ctx["roomy"]["id"], ctx["first"]["id"],
                                JobCode.STARTER),
            ApiErrorId.DUPLICATE_VOLUNTEER_ASSIGNMENT, 409,
        )
        assert body["error_id"] != ApiErrorId.VOLUNTEER_SLOTS_FULL

        twin = fx.assign_volunteer(api, ctx["roomy"]["id"], ctx["second"]["id"],
                                   JobCode.STARTER)
        assert twin["credit_value"] == 2
        assert twin["job_code"] == JobCode.STARTER

    def test_neither_refusal_left_a_row_or_moved_the_filled_count(self, api):
        """Two admitted jobs, two refused ones, and the count reads 4.

        PRD §3.6: "Assignments are listed and filtered by `meet_id`,
        `swim_team_registration_id`, `job_code` and `status`."

        Design: Corner/validations/violation_to_error_meet_roster_credit_ceiling_and_duplicate_job
        """
        ctx = _two_meets_and_two_swimmers(api)
        fx.assign_volunteer(api, ctx["roomy"]["id"], ctx["first"]["id"],
                            JobCode.SCORER)
        validate_error(
            _attempt_assignment(api, ctx["roomy"]["id"], ctx["first"]["id"],
                                JobCode.STARTER),
            ApiErrorId.DUPLICATE_VOLUNTEER_ASSIGNMENT, 409,
        )
        fx.assign_volunteer(api, ctx["roomy"]["id"], ctx["second"]["id"],
                            JobCode.STARTER)

        assert fx.read_meet(api, ctx["roomy"]["id"])["volunteer_slots_filled"] == 4
        assert len(_assignments_of(api, ctx["roomy"]["id"])) == 2


def _two_coexisting_seasons(api):
    """2027 OPEN and 2028 still PLANNED, with one 2027 swimmer and one meet."""
    fx.set_clock(api, SCOPE_CLOCK)
    category = fx.create_couple_category(api)
    season_2027 = fx.setup_open_season(api)
    season_2028 = fx.setup_planned_season(
        api, year=2028, open_date="2028-05-20", close_date="2028-09-04",
        dues_due_date="2028-04-15",
    )
    household = fx.create_household(
        api, primary_contact_name="Two Season Household",
        address_line="261 Cedar Court", member_count=4, prior_member=False,
    )
    membership = fx.setup_membership(api, household["id"], category["id"],
                                    season_2027["id"], join_date="2027-06-01")
    membership = fx.invoice_membership(api, membership["id"])
    registration = fx.register_swimmer(api, membership["id"],
                                       season_2027["id"],
                                       swimmer_name="Priya Twoseason",
                                       swimmer_birthdate="2016-04-04",
                                       squad=Squad.MINI)
    meet = fx.create_meet(api, season_2027["id"],
                          name="Cross Season Control Meet",
                          start_iso="2027-08-07T13:00:00Z",
                          end_iso="2027-08-07T18:00:00Z",
                          expected_swimmers=40, volunteer_slots_required=6)
    return {"category": category, "season_2027": season_2027,
            "season_2028": season_2028, "household": household,
            "membership_2027": membership, "registration_2027": registration,
            "meet_2027": meet}


def _attempt_membership_in(api, ctx, season_id, join_date):
    return api.create_membership(
        membership_payload(
            household_id=ctx["household"]["id"],
            membership_category_id=ctx["category"]["id"],
            season_id=season_id, join_date=join_date,
        ),
        MEMBERSHIP_CHAIR,
    )


def _attempt_registration(api, membership_id, season_id):
    return api.create_registration(
        registration_payload(
            membership_id=membership_id, season_id=season_id,
            swimmer_name="Priya Twoseason", swimmer_birthdate="2016-04-04",
            squad=Squad.MINI,
        ),
        SWIM_TEAM_COACH,
    )


def _membership_for_2028(api, ctx):
    """Open the 2028 season, buy it and invoice it."""
    fx.open_season(api, ctx["season_2028"]["id"])
    membership = validate_success(
        _attempt_membership_in(api, ctx, ctx["season_2028"]["id"],
                               "2028-05-20"),
        201,
    )
    return fx.invoice_membership(api, membership["id"])


class TestSeasonScopeGuardsOnStatusAndCrossSeasonJoins:
    """With two seasons alive, "the season" must come from the request."""

    def test_a_planned_season_is_not_a_missing_one(self, api):
        """Existence is not enough: the referenced season must be OPEN.

        PRD §3.3: "The referenced season must be `OPEN`."

        PRD §3.1: "A `PoolManager` opens the season for swimming, moving `status`
        from `PLANNED` to `OPEN`; the operation is available only while the season
        is still `PLANNED`."

        Design: Corner/validations/violation_to_error_season_scope_guards_on_status_and_cross_season_joins
        """
        ctx = _two_coexisting_seasons(api)
        assert ctx["season_2028"]["status"] == SeasonStatus.PLANNED

        validate_error(
            _attempt_membership_in(api, ctx, ctx["season_2028"]["id"],
                                   "2028-05-20"),
            ApiErrorId.SEASON_NOT_OPEN, 409,
        )

        opened = fx.open_season(api, ctx["season_2028"]["id"])
        assert opened["status"] == SeasonStatus.OPEN

        membership = validate_success(
            _attempt_membership_in(api, ctx, ctx["season_2028"]["id"],
                                   "2028-05-20"),
            201,
        )
        assert membership["assessed_dues_cents"] == 30000
        assert membership["dues_status"] == DuesStatus.UNBILLED

    def test_a_registration_may_not_cross_the_season_boundary(self, api):
        """The membership's season and the request's season must agree.

        PRD §3.6: "The `season_id` on the request must be the same season as the
        membership's own `season_id`; a disagreement between two season-scoped
        references in one request is `ERR_SEASON_MISMATCH`."

        Design: Corner/validations/violation_to_error_season_scope_guards_on_status_and_cross_season_joins
        """
        ctx = _two_coexisting_seasons(api)
        membership_2028 = _membership_for_2028(api, ctx)

        validate_error(
            _attempt_registration(api, ctx["membership_2027"]["id"],
                                  ctx["season_2028"]["id"]),
            ApiErrorId.SEASON_MISMATCH, 422,
        )

        registration = validate_success(
            _attempt_registration(api, membership_2028["id"],
                                  ctx["season_2028"]["id"]),
            201,
        )
        assert registration["status"] == RegistrationStatus.PENDING
        assert registration["season_id"] == ctx["season_2028"]["id"]

    def test_an_assignment_may_not_cross_the_season_boundary(self, api):
        """A 2027 meet refuses a 2028 swimmer, and it is not a lookup failure.

        PRD §3.6: "The meet named and the registration named must also belong to
        the same season, or the request is `ERR_SEASON_MISMATCH`."

        Design: Corner/validations/violation_to_error_season_scope_guards_on_status_and_cross_season_joins
        """
        ctx = _two_coexisting_seasons(api)
        membership_2028 = _membership_for_2028(api, ctx)
        registration_2028 = validate_success(
            _attempt_registration(api, membership_2028["id"],
                                  ctx["season_2028"]["id"]),
            201,
        )

        body = validate_error(
            _attempt_assignment(api, ctx["meet_2027"]["id"],
                                registration_2028["id"], JobCode.MARSHAL),
            ApiErrorId.SEASON_MISMATCH, 422,
        )
        assert body["error_id"] != ApiErrorId.REGISTRATION_NOT_FOUND

        admitted = fx.assign_volunteer(api, ctx["meet_2027"]["id"],
                                       ctx["registration_2027"]["id"],
                                       JobCode.MARSHAL)
        assert admitted["credit_value"] == 1
        assert admitted["status"] == AssignmentStatus.ASSIGNED

    def test_both_seasons_stay_open_and_independent(self, api):
        """Two memberships for one household, one per season, and no crosstalk.

        PRD §3.3: "A household that already holds a membership for the same season
        whose `access_status` is anything other than `LAPSED` or `TERMINATED` is
        refused as a duplicate (`ERR_DUPLICATE_MEMBERSHIP`)"

        Design: Corner/validations/violation_to_error_season_scope_guards_on_status_and_cross_season_joins
        """
        ctx = _two_coexisting_seasons(api)
        membership_2028 = _membership_for_2028(api, ctx)

        validate_error(
            _attempt_membership_in(api, ctx, ctx["season_2027"]["id"],
                                   "2027-06-01"),
            ApiErrorId.DUPLICATE_MEMBERSHIP, 409,
        )

        assert membership_2028["season_id"] == ctx["season_2028"]["id"]
        assert ctx["membership_2027"]["season_id"] == ctx["season_2027"]["id"]
        for key in ("season_2027", "season_2028"):
            season = fx.read_season(api, ctx[key]["id"])
            assert season["status"] == SeasonStatus.OPEN
        assert fx.read_season(
            api, ctx["season_2027"]["id"]
        )["year"] == 2027
        assert fx.read_season(
            api, ctx["season_2028"]["id"]
        )["year"] == 2028


INVOICE_TOTAL = 31050


def _an_invoiced_household_and_an_empty_reserve(api):
    """A 31050-cent balance, a zero guest-fee bucket and a reserve of nothing."""
    fx.set_clock(api, SCOPE_CLOCK)
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)
    household = fx.create_household(
        api, primary_contact_name="Ceiling Household",
        address_line="271 Cedar Court", member_count=2, prior_member=False,
    )
    membership = fx.setup_membership(api, household["id"], category["id"],
                                    season["id"], join_date="2027-05-22")
    invoiced = fx.invoice_membership(api, membership["id"])
    return {"category": category, "season": season, "household": household,
            "membership": invoiced, "fresh_season": season,
            "fresh_household": household}


def _approve_project(api, season_id, budget_cents, title, project_kind):
    project = fx.propose_project(api, season_id, budget_cents, title=title,
                                 project_kind=project_kind)
    approved = validate_success(
        api.transition_capital_project(
            project["id"], transition_payload(ProjectStatus.APPROVED),
            BOARD_PRESIDENT,
        ),
        200,
    )
    return project, approved


def _attempt_draw(api, project_id, draw_amount_cents):
    version = fx.read_project(api, project_id)["version"]
    return api.fund_capital_project(
        project_id,
        fund_project_payload(draw_amount_cents=draw_amount_cents,
                             expected_capital_project_version=version),
        TREASURER,
    )


def _projects_of(api, season_id):
    rows, _ = validate_paginated(
        api.list_capital_projects(TREASURER, {"funding_season_id": season_id})
    )
    return rows


class TestMoneyCeilingsOnPaymentsAndReserveDraws:
    """Three ceilings that a single sanity check would collapse into one."""

    def test_a_payment_may_not_exceed_the_membership_balance(self, api):
        """The ceiling is the balance, not the invoice's dues line.

        PRD §3.4: "No payment may exceed `balance_due_cents`; one that does is
        rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."

        PRD §3.4: "`invoice_total_cents` is the penalty base plus the penalty."

        Design: Corner/validations/violation_to_error_money_ceilings_on_payments_and_reserve_draws
        """
        ctx = _an_invoiced_household_and_an_empty_reserve(api)
        assert ctx["membership"]["invoice_total_cents"] == INVOICE_TOTAL
        assert ctx["membership"]["balance_due_cents"] == INVOICE_TOTAL
        assert ctx["membership"]["late_penalty_cents"] == 1050

        validate_error(
            api.create_membership_payment(
                ctx["membership"]["id"],
                membership_payment_payload(amount_cents=40000,
                                           allocation="DUES"),
                TREASURER,
            ),
            ApiErrorId.PAYMENT_EXCEEDS_BALANCE, 422,
        )

        membership = fx.read_membership(api, ctx["membership"]["id"])
        assert membership["amount_paid_cents"] == 0
        assert membership["balance_due_cents"] == INVOICE_TOTAL
        assert membership["dues_status"] == DuesStatus.INVOICED

    def test_a_zero_bucket_is_still_a_ceiling(self, api):
        """Paying into an empty counter is an overpayment, not a credit.

        PRD §3.2: "No payment may exceed the counter it settles: for `GUEST_FEES`
        the ceiling is `guest_fee_owed_cents`"

        Design: Corner/validations/violation_to_error_money_ceilings_on_payments_and_reserve_draws
        """
        ctx = _an_invoiced_household_and_an_empty_reserve(api)
        assert ctx["fresh_household"]["guest_fee_owed_cents"] == 0

        validate_error(
            api.create_household_payment(
                ctx["household"]["id"],
                household_payment_payload(amount_cents=5000,
                                          allocation="GUEST_FEES"),
                TREASURER,
            ),
            ApiErrorId.PAYMENT_EXCEEDS_BALANCE, 422,
        )

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["guest_fee_owed_cents"] == 0
        assert household["account_credit_cents"] == 0

    def test_the_reserve_ceiling_is_a_season_pool_every_project_shares(self, api):
        """A draw inside the project's budget still fails on the season's pool.

        PRD §3.10: "the `draw_amount_cents` may not exceed the season's
        `reserve_unallocated_cents` (`ERR_INSUFFICIENT_RESERVE`)"

        Design: Corner/validations/violation_to_error_money_ceilings_on_payments_and_reserve_draws
        """
        ctx = _an_invoiced_household_and_an_empty_reserve(api)
        a.assert_reserve_counters(ctx["fresh_season"], 0, 0)

        funded_season = fx.contribute_reserve(api, ctx["season"]["id"], 100000,
                                              note="First special assessment")
        a.assert_reserve_counters(funded_season, 100000, 100000)

        project, approved = _approve_project(
            api, ctx["season"]["id"], 200000, "Resurface the main tank",
            "POOL_RESURFACING",
        )
        assert project["status"] == ProjectStatus.PROPOSED
        assert project["funded_cents"] == 0
        assert approved["status"] == ProjectStatus.APPROVED

        validate_error(_attempt_draw(api, project["id"], 150000),
                       ApiErrorId.INSUFFICIENT_RESERVE, 402)

        assert fx.read_project(api, project["id"])["funded_cents"] == 0
        a.assert_reserve_counters(fx.read_season(api, ctx["season"]["id"]),
                                  100000, 100000)

    def test_the_budget_ceiling_belongs_to_the_project_alone(self, api):
        """The same 150000 draw now clears the reserve and fails the budget.

        PRD §3.10: "the project's `funded_cents` plus the `draw_amount_cents` may
        not exceed its `budget_cents` (`ERR_DRAW_EXCEEDS_BUDGET`)"

        Design: Corner/validations/violation_to_error_money_ceilings_on_payments_and_reserve_draws
        """
        ctx = _an_invoiced_household_and_an_empty_reserve(api)
        fx.contribute_reserve(api, ctx["season"]["id"], 100000,
                              note="First special assessment")
        topped_up = fx.contribute_reserve(api, ctx["season"]["id"], 100000,
                                          note="Second special assessment")
        a.assert_reserve_counters(topped_up, 200000, 200000)

        pump, approved = _approve_project(
            api, ctx["season"]["id"], 120000, "Replace the circulation pump",
            "PUMP_REPLACEMENT",
        )
        assert approved["status"] == ProjectStatus.APPROVED

        body = validate_error(_attempt_draw(api, pump["id"], 150000),
                              ApiErrorId.DRAW_EXCEEDS_BUDGET, 422)
        assert body["error_id"] != ApiErrorId.INSUFFICIENT_RESERVE

        assert fx.read_project(api, pump["id"])["funded_cents"] == 0
        a.assert_reserve_counters(fx.read_season(api, ctx["season"]["id"]),
                                  200000, 200000)

    def test_the_draw_that_clears_both_ceilings_moves_only_one_counter(self, api):
        """Contributions never fall; the unallocated side pays for the work.

        PRD §3.10: "A draw that passes raises `funded_cents` by the drawn amount
        and lowers `reserve_unallocated_cents` by the same amount while leaving
        `reserve_contributions_cents` untouched"

        PRD §3.10: "The first successful draw against an `APPROVED` project also
        moves it to `FUNDED`; subsequent draws leave it there."

        Design: Corner/validations/violation_to_error_money_ceilings_on_payments_and_reserve_draws
        """
        ctx = _an_invoiced_household_and_an_empty_reserve(api)
        fx.contribute_reserve(api, ctx["season"]["id"], 100000,
                              note="First special assessment")
        tank, _ = _approve_project(
            api, ctx["season"]["id"], 200000, "Resurface the main tank",
            "POOL_RESURFACING",
        )
        validate_error(_attempt_draw(api, tank["id"], 150000),
                       ApiErrorId.INSUFFICIENT_RESERVE, 402)
        fx.contribute_reserve(api, ctx["season"]["id"], 100000,
                              note="Second special assessment")

        drawn = validate_success(_attempt_draw(api, tank["id"], 150000), 200)
        assert drawn["status"] == ProjectStatus.FUNDED
        assert drawn["funded_cents"] == 150000

        season = fx.read_season(api, ctx["season"]["id"])
        a.assert_reserve_counters(season, 200000, 50000)
        a.assert_reserve_identity(season, _projects_of(api, ctx["season"]["id"]))
