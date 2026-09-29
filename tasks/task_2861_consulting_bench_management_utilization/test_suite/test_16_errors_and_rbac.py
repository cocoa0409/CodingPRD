"""The 404 catalogue, path-before-body resolution, and the whole RBAC matrix."""

import pytest

from test_helpers import (
    FINANCE_CONTROLLER,
    FINANCE_CONTROLLER_USER_ID,
    PRACTICE_PARTNER,
    RESOURCE_MANAGER,
    SALES_LEAD,
    SALES_LEAD_USER_ID,
    ApiErrorId,
    AvailabilityStatus,
    PeriodStatus,
    PipelineStatus,
    Posture,
    Role,
    build_user_headers,
    factories,
    fixtures,
    make_consultant_headers,
    make_finance_controller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import INSTANT_AUG_03

MISSING_A = "00000000-0000-4000-8000-0000000000a1"
MISSING_B = "00000000-0000-4000-8000-0000000000b1"
MISSING_C = "00000000-0000-4000-8000-0000000000c1"


class TestMasterDataPathIdsReturnTheirOwnCodes:
    def test_five_master_data_reads_each_name_their_own_entity(self, api):
        """PRD §2.7: "Every collection has its own 404 code, and each is used both for path
        segments and for foreign keys carried in a request body: `ERR_PRACTICE_GROUP_NOT_FOUND`
        for a group path segment or a `practice_group_id` or `parent_group_id` value;
        `ERR_SKILL_NOT_FOUND` for a skill path segment or a `required_skill_id`, `skill_id` or
        `development_goal_skill_id` value; `ERR_CONSULTANT_NOT_FOUND` for a consultant path
        segment or a `consultant_id` value; `ERR_SKILL_ASSERTION_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_BENCH_SPELL_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
        `ERR_PLACEMENT_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND` and `ERR_FORECAST_NOT_FOUND` for
        their own path segments; `ERR_OPPORTUNITY_NOT_FOUND` for a demand path segment or a
        `demand_opportunity_id` value; `ERR_FIRM_NOT_FOUND` for a firm path segment or a
        `subcontractor_firm_id` value; and `ERR_PERIOD_NOT_FOUND` for a period segment."

        Design: Corner/errors/master_data_path_ids_return_their_own_not_found_codes
        """
        group = fixtures.create_group(api, name="Cloud NA", geography_code="NA")

        validate_error(
            api.get_skill(MISSING_A, PRACTICE_PARTNER), ApiErrorId.ERR_SKILL_NOT_FOUND, 404
        )
        validate_error(
            api.get_skill_assertion(MISSING_A, RESOURCE_MANAGER),
            ApiErrorId.ERR_SKILL_ASSERTION_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_demand(MISSING_A, SALES_LEAD),
            ApiErrorId.ERR_OPPORTUNITY_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_assignment(MISSING_A, RESOURCE_MANAGER),
            ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_bench_spell(MISSING_A, RESOURCE_MANAGER),
            ApiErrorId.ERR_BENCH_SPELL_NOT_FOUND,
            404,
        )

        assert fixtures.read_group(api, group["id"])["version"] == 1


class TestSourcingAndFinancePathIdsReturnTheirOwnCodes:
    def test_five_sourcing_and_finance_reads_complete_the_catalogue(self, api):
        """PRD §2.9: "4. **Path existence** — every templated identifier in the path resolves,
        checked left to right as described in §2.7. Applies to every endpoint with a templated
        segment. Failure: the relevant 404 code."

        Design: Corner/errors/sourcing_and_finance_path_ids_return_their_own_not_found_codes
        """
        group = fixtures.create_group(api, name="Cloud NA", geography_code="NA")

        validate_error(
            api.get_reskilling_program(MISSING_B, RESOURCE_MANAGER),
            ApiErrorId.ERR_PROGRAM_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_firm(MISSING_B, PRACTICE_PARTNER), ApiErrorId.ERR_FIRM_NOT_FOUND, 404
        )
        validate_error(
            api.get_placement(MISSING_B, PRACTICE_PARTNER),
            ApiErrorId.ERR_PLACEMENT_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_discount_approval(MISSING_B, FINANCE_CONTROLLER),
            ApiErrorId.ERR_APPROVAL_NOT_FOUND,
            404,
        )
        # The forecast is immutable, but a missing one is still a 404, not an empty 200.
        validate_error(
            api.get_hiring_forecast(MISSING_B, FINANCE_CONTROLLER),
            ApiErrorId.ERR_FORECAST_NOT_FOUND,
            404,
        )

        assert fixtures.read_group(api, group["id"])["version"] == 1


class TestPathsAreResolvedBeforeBodies:
    @staticmethod
    def _a_consultant_a_period_and_a_cohort(api):
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=None)
        consultant_id = staff["consultant"]["id"]
        period = fixtures.create_period(api, consultant_id, "2026-08-03", "2026-08-28")
        program = fixtures.create_program(
            api,
            world["skill"]["id"],
            target_proficiency_level=4,
            cohort_start_on="2026-09-01",
            cohort_end_on="2026-09-30",
            seat_capacity=2,
        )
        return world, consultant_id, period, program

    def test_the_nested_route_names_whichever_segment_failed(self, api):
        """PRD §2.7: "Path identifiers are resolved **left to right**, and the first segment
        that names no existing row decides the error."

        Design: Corner/errors/nested_and_action_paths_check_the_path_before_the_body
        """
        _, consultant_id, _, _ = self._a_consultant_a_period_and_a_cohort(api)

        validate_error(
            api.get_utilization_period(consultant_id, MISSING_C, FINANCE_CONTROLLER),
            ApiErrorId.ERR_PERIOD_NOT_FOUND,
            404,
        )
        validate_error(
            api.list_utilization_periods(MISSING_C, FINANCE_CONTROLLER, {"limit": 10}),
            ApiErrorId.ERR_CONSULTANT_NOT_FOUND,
            404,
        )

    def test_the_programme_in_the_path_outranks_the_unknown_body_key(self, api):
        """PRD §2.7: "Any path-borne identifier is always resolved before any body-borne one."

        Design: Corner/errors/nested_and_action_paths_check_the_path_before_the_body
        """
        _, _, _, program = self._a_consultant_a_period_and_a_cohort(api)

        validate_error(
            api.enrol_in_program(MISSING_C, MISSING_C, RESOURCE_MANAGER),
            ApiErrorId.ERR_PROGRAM_NOT_FOUND,
            404,
        )
        validate_error(
            api.enrol_in_program(program["id"], MISSING_C, RESOURCE_MANAGER),
            ApiErrorId.ERR_CONSULTANT_NOT_FOUND,
            404,
        )
        assert fixtures.read_program(api, program["id"])["seats_taken"] == 0

    def test_an_action_route_on_a_missing_row_never_reaches_its_state_rule(self, api):
        """PRD §2.9: "4. **Path existence** — every templated identifier in the path resolves,
        checked left to right as described in §2.7. Applies to every endpoint with a templated
        segment. Failure: the relevant 404 code."

        Design: Corner/errors/nested_and_action_paths_check_the_path_before_the_body
        """
        _, consultant_id, period, _ = self._a_consultant_a_period_and_a_cohort(api)

        validate_error(
            api.propose_separation(MISSING_C, RESOURCE_MANAGER, rationale="no such spell"),
            ApiErrorId.ERR_BENCH_SPELL_NOT_FOUND,
            404,
        )
        assert (
            fixtures.read_period(api, consultant_id, period["id"])["status"]
            == PeriodStatus.OPEN
        )


EMPTY_ROLE_HEADERS = build_user_headers("u-nobody", "")
UNRECOGNISED_ROLE_HEADERS = build_user_headers("u-nobody", "PracticeManager")
MISSING_D = "00000000-0000-4000-8000-0000000000d1"


class TestBrokenIdentityPairsAreNeverAuthorisationFailures:
    def test_three_defective_identity_pairs_all_return_401(self, api):
        """PRD §2.9: "1. **Authentication** — `X-User-Role` present and equal to one of the
        five role names, `X-User-ID` present and non-empty, and for the entity-backed
        `Consultant` role the supplied id must resolve to an existing consultant row. Applies
        to every endpoint. Failure: `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/missing_unknown_and_unbacked_identity_headers_are_rejected
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=None)
        consultant_id = staff["consultant"]["id"]

        validate_error(
            api.list_consultants(EMPTY_ROLE_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.list_consultants(UNRECOGNISED_ROLE_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        # The path id is a real consultant row; the *caller's* id is not, and the
        # Consultant role is resolved against the table rather than merely parsed.
        validate_error(
            api.get_consultant(consultant_id, make_consultant_headers(MISSING_D)),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

    def test_an_unrecognisable_identity_is_never_told_which_roles_are_allowed(self, api):
        """PRD §2.1: "A request missing either header, carrying an empty value for either, or
        naming a role that is not one of the five recognised names is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_unknown_and_unbacked_identity_headers_are_rejected
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=None)

        # POST /consultants is ResourceManager-only, so rung 2 would also refuse this
        # caller — but rung 1 is evaluated first.
        validate_error(
            api.create_consultant(
                factories.consultant_payload(
                    world["group"]["id"],
                    full_name="Ghost Writer",
                    email=factories.unique_email("ghost"),
                ),
                UNRECOGNISED_ROLE_HEADERS,
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

        _, meta = validate_paginated(api.list_consultants(RESOURCE_MANAGER))
        assert meta["total_count"] == 1


class TestRolesCannotReachEachOthersOperations:
    @staticmethod
    def _one_of_everything_a_write_needs(api):
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=4)
        demand = fixtures.qualified_demand(api, world, required_fte=1.00)
        return world, staff, demand

    def test_four_exclusive_writes_refuse_the_wrong_role(self, api):
        """PRD §2.9: "2. **Authorisation** — the caller's role appears in the target endpoint's
        authorised-role list. Applies to every endpoint. Failure: `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/roles_cannot_reach_each_others_exclusive_operations
        """
        world, staff, demand = self._one_of_everything_a_write_needs(api)

        validate_error(
            api.create_consultant(
                factories.consultant_payload(
                    world["group"]["id"],
                    full_name="Sales Hire",
                    email=factories.unique_email("sales"),
                ),
                SALES_LEAD,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_practice_group(
                factories.practice_group_payload(name="Shadow NA", geography_code="NA"),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_demand(
                factories.demand_payload(
                    world["group"]["id"], world["skill"]["id"], client_name="Partner Corp"
                ),
                PRACTICE_PARTNER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_assignment(
                factories.assignment_payload(
                    staff["consultant"]["id"],
                    demand["id"],
                    staff["consultant"]["version"],
                ),
                FINANCE_CONTROLLER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        _, consultants = validate_paginated(api.list_consultants(RESOURCE_MANAGER))
        assert consultants["total_count"] == 1
        _, assignments = validate_paginated(api.list_assignments(RESOURCE_MANAGER))
        assert assignments["total_count"] == 0

    def test_the_ledger_read_and_the_owners_own_period_write_are_both_refused(self, api):
        """PRD §2.9: "2. **Authorisation** — the caller's role appears in the target endpoint's
        authorised-role list. Applies to every endpoint. Failure: `ERR_UNAUTHORIZED` (403)."
        PRD §2.9: "6. **Ownership** — a `Consultant`-role caller may only read or write rows
        belonging to the consultant whose `id` equals `X-User-ID`. Applies to reading one
        consultant, listing a consultant's utilization periods, reading one utilization period,
        creating a skill assertion and updating a skill assertion. Failure:
        `ERR_NOT_RESOURCE_OWNER` (403)."

        Design: Corner/rbac/roles_cannot_reach_each_others_exclusive_operations
        """
        _, staff, _ = self._one_of_everything_a_write_needs(api)
        consultant_id = staff["consultant"]["id"]

        # The one GET a ResourceManager is not on.
        validate_error(
            api.list_discount_approvals(RESOURCE_MANAGER),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        # The caller owns the collection, but opening a period is FinanceController-only
        # and rung 2 fires before rung 6.
        validate_error(
            api.create_utilization_period(
                consultant_id,
                factories.utilization_period_payload("2026-08-03", "2026-08-28"),
                make_consultant_headers(consultant_id),
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        _, periods = validate_paginated(
            api.list_utilization_periods(consultant_id, FINANCE_CONTROLLER)
        )
        assert periods["total_count"] == 0


class TestAConsultantIsFencedIntoTheirOwnRows:
    @staticmethod
    def _two_consultants_one_with_data(api):
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        first = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=None)
        second = fixtures.hire(api, world, full_name="Grace Hopper", proficiency_level=3)
        period = fixtures.create_period(
            api, second["consultant"]["id"], "2026-08-03", "2026-08-28"
        )
        return world, first["consultant"], second["consultant"], second["assertion"], period

    def test_every_read_of_another_consultants_rows_is_refused(self, api):
        """PRD §2.1: "Concretely, a `Consultant` caller may read only their own consultant row,
        may list and read only their own utilization periods, and may create or revise skill
        assertions only where `consultant_id` equals their own `X-User-ID`."

        Design: Corner/rbac/consultant_role_cannot_touch_another_consultants_rows
        """
        _, first, second, _, period = self._two_consultants_one_with_data(api)
        intruder = make_consultant_headers(first["id"])

        validate_error(
            api.get_consultant(second["id"], intruder),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.list_utilization_periods(second["id"], intruder),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.get_utilization_period(second["id"], period["id"], intruder),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )

    def test_every_write_against_another_consultants_evidence_is_refused(self, api):
        """PRD §2.9: "6. **Ownership** — a `Consultant`-role caller may only read or write rows
        belonging to the consultant whose `id` equals `X-User-ID`. Applies to reading one
        consultant, listing a consultant's utilization periods, reading one utilization period,
        creating a skill assertion and updating a skill assertion. Failure:
        `ERR_NOT_RESOURCE_OWNER` (403)."

        Design: Corner/rbac/consultant_role_cannot_touch_another_consultants_rows
        """
        world, first, second, assertion, _ = self._two_consultants_one_with_data(api)
        intruder = make_consultant_headers(first["id"])

        validate_error(
            api.create_skill_assertion(
                factories.skill_assertion_payload(
                    second["id"], world["skill"]["id"], proficiency_level=5
                ),
                intruder,
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.patch_skill_assertion(assertion["id"], {"proficiency_level": 5}, intruder),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )

        untouched = validate_success(
            api.get_skill_assertion(assertion["id"], RESOURCE_MANAGER), 200
        )
        assert untouched["proficiency_level"] == 3
        assert untouched["version"] == 1
        own_rows, meta = validate_paginated(
            api.list_skill_assertions(RESOURCE_MANAGER, {"consultant_id": first["id"]})
        )
        assert meta["total_count"] == 0
        assert own_rows == []


OPAQUE_ROLES = (
    Role.SALES_LEAD,
    Role.RESOURCE_MANAGER,
    Role.PRACTICE_PARTNER,
    Role.FINANCE_CONTROLLER,
)


class TestEveryRolePerformsItsOwnAndItsSharedOperations:
    @staticmethod
    def _one_write_per_owning_role(api):
        """Each row below is created by the single role that owns its endpoint, so a
        server that refused any of them would fail here rather than pass by accident."""
        group = validate_success(
            api.create_practice_group(
                factories.practice_group_payload(name="Cloud NA", geography_code="NA"),
                PRACTICE_PARTNER,
            ),
            201,
        )
        skill = validate_success(
            api.create_skill(
                factories.skill_payload(
                    code="CLOUD_ARCH", name="Cloud Architecture", family="CLOUD"
                ),
                PRACTICE_PARTNER,
            ),
            201,
        )
        consultant = validate_success(
            api.create_consultant(
                factories.consultant_payload(
                    group["id"],
                    full_name="Ada Byron",
                    email="ada.byron@firm.test",
                ),
                RESOURCE_MANAGER,
            ),
            201,
        )
        demand = validate_success(
            api.create_demand(
                factories.demand_payload(
                    group["id"],
                    skill["id"],
                    client_name="Acme Retail",
                    start_date="2026-08-17",
                    end_date="2026-08-28",
                    requested_rate_usd_per_hour=250.00,
                ),
                SALES_LEAD,
            ),
            201,
        )
        period = validate_success(
            api.create_utilization_period(
                consultant["id"],
                factories.utilization_period_payload("2026-08-03", "2026-08-28"),
                FINANCE_CONTROLLER,
            ),
            201,
        )
        own = make_consultant_headers(consultant["id"])
        assertion = validate_success(
            api.create_skill_assertion(
                factories.skill_assertion_payload(
                    consultant["id"], skill["id"], proficiency_level=4
                ),
                own,
            ),
            201,
        )
        return {
            "group": group,
            "skill": skill,
            "consultant": consultant,
            "demand": demand,
            "period": period,
            "assertion": assertion,
            "own": own,
        }

    def test_each_owning_role_writes_its_own_row_and_all_four_may_set_the_clock(self, api):
        """PRD §4: "| POST | `/_clock/set_current_utc` | Set the server's logical clock from a
        `current_utc` instant; re-derives clock-dependent fields but advances no state machine.
        | ResourceManager, PracticePartner, FinanceController, SalesLead |"

        Design: Corner/rbac/every_role_performs_its_own_and_its_shared_operations
        """
        for role in OPAQUE_ROLES:
            validate_success(
                api.set_clock(INSTANT_AUG_03, build_user_headers("u_ops_1", role)), 200
            )

        world = self._one_write_per_owning_role(api)

        assert world["group"]["posture"] == Posture.OPEN
        assert world["demand"]["pipeline_status"] == PipelineStatus.QUALIFYING
        assert world["period"]["status"] == PeriodStatus.OPEN
        assert world["assertion"]["proficiency_level"] == 4

    def test_the_owners_own_reads_and_the_shared_assignment_read_all_succeed(self, api):
        """PRD §4: "| GET | `/assignments` | List assignments, filterable by `consultant_id`,
        `demand_opportunity_id`, `status` and `category`. | ResourceManager, PracticePartner,
        FinanceController, SalesLead, Consultant |"

        Design: Corner/rbac/every_role_performs_its_own_and_its_shared_operations
        """
        fixtures.set_clock(api, INSTANT_AUG_03)
        world = self._one_write_per_owning_role(api)
        consultant_id = world["consultant"]["id"]
        own = world["own"]

        mine = validate_success(api.get_consultant(consultant_id, own), 200)
        assert mine["id"] == consultant_id
        assert mine["availability_status"] == AvailabilityStatus.BENCH

        _, my_periods = validate_paginated(
            api.list_utilization_periods(consultant_id, own, {"limit": 10})
        )
        assert my_periods["total_count"] == 1

        query = {"consultant_id": consultant_id}
        _, my_assignments = validate_paginated(api.list_assignments(own, query))
        assert my_assignments["total_count"] == 0

        for headers in (SALES_LEAD, RESOURCE_MANAGER, PRACTICE_PARTNER, FINANCE_CONTROLLER):
            _, meta = validate_paginated(api.list_assignments(headers, query))
            assert meta["total_count"] == 0


class TestSegregationOfDutiesIsKeyedOnTheUserNotTheRole:
    @staticmethod
    def _a_finance_tier_request_from_the_sales_lead(api):
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        demand = fixtures.qualified_demand(
            api,
            world,
            staffing_mode=None,
            required_fte=1.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        approval = fixtures.request_discount(api, demand["id"], 200.00, headers=SALES_LEAD)
        return demand, approval

    def test_the_requester_is_refused_even_wearing_the_deciding_role(self, api):
        """PRD §2.9: "19. **Segregation of duties** — the user deciding a discount approval must
        differ from its `requested_by_user_id`, and the user deciding a separation must differ
        from the spell's `separation_proposed_by_user_id`. Applies to the discount decision and
        the separation decision. Failure: `ERR_SELF_APPROVAL_FORBIDDEN` (403)."

        Design: Corner/rbac/same_user_id_cannot_decide_what_it_requested_whatever_role_it_wears
        """
        _, approval = self._a_finance_tier_request_from_the_sales_lead(api)

        assert approval["required_tier"] == "L2_FINANCE"
        assert approval["status"] == "PENDING"
        assert approval["requested_by_user_id"] == SALES_LEAD_USER_ID
        assert approval["projected_margin_pct"] == pytest.approx(60.00, abs=0.005)

        # The role header now satisfies the L2_FINANCE tier, so identity is the only
        # remaining reason to refuse. PRD rung 19 fixes the status at 403.
        validate_error(
            api.decide_discount_approval(
                approval["id"],
                "APPROVED",
                make_finance_controller_headers(SALES_LEAD_USER_ID),
            ),
            ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN,
            403,
        )
        assert fixtures.read_approval(api, approval["id"])["status"] == "PENDING"

    def test_a_different_user_still_needs_the_tier_and_then_the_row_is_decided(self, api):
        """PRD §2.9: "20. **Approval tier authority** — the caller's role must satisfy the
        approval's `required_tier`. Applies to the discount decision only. Failure:
        `ERR_APPROVAL_TIER_INSUFFICIENT` (403)."
        PRD §2.11: "A tier of `L2_FINANCE` is satisfied by a `FinanceController` and by nobody
        else — a `PracticePartner` attempting it is rejected with
        `ERR_APPROVAL_TIER_INSUFFICIENT`."

        Design: Corner/rbac/same_user_id_cannot_decide_what_it_requested_whatever_role_it_wears
        """
        demand, approval = self._a_finance_tier_request_from_the_sales_lead(api)

        validate_error(
            api.decide_discount_approval(approval["id"], "APPROVED", PRACTICE_PARTNER),
            ApiErrorId.ERR_APPROVAL_TIER_INSUFFICIENT,
            403,
        )

        decided = validate_success(
            api.decide_discount_approval(approval["id"], "APPROVED", FINANCE_CONTROLLER), 200
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == FINANCE_CONTROLLER_USER_ID

        after = fixtures.read_demand(api, demand["id"])
        assert after["approved_rate_usd_per_hour"] == pytest.approx(200.00, abs=0.01)
        assert after["effective_rate_usd_per_hour"] == pytest.approx(200.00, abs=0.01)
        assert after["booked_realization_pct"] == pytest.approx(80.00, abs=0.005)
