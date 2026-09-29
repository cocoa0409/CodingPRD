"""
The gates that read another entity: standing, sizing, cardinality and bounds.

Every refusal here needs a second record to decide it — the installer's certification, the
approved calculation's requirement, the row that already exists, the program's floor or the
catalog's ceiling — and each of those gates keeps its own identifier.
"""

from test_helpers import (
    WARRANTY_AGENT_HEADERS,
    ApiErrorId,
    BuildStatus,
    CertificationStatus,
    ExportMode,
    InverterModel,
    ModelCode,
    Season,
    TestType,
    assert_program_ledger,
    assert_quantity,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

LAPSED_EXPIRY = "2026-07-31T00:00:00.000Z"
DUPLICATE_TEST_WINDOW = ("2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")


class TestTheCertificationGate:
    """One identifier, two independent ways to fail it: the model list and the expiry."""

    def test_an_uncovered_model_and_a_lapsed_certification_are_both_refused(self, api):
        """The company is in good standing and still cannot design either bank.

        The company's certification covers one model, so a design naming a different catalog
        model is refused even though the account is active and unexpired. The warranty desk
        then amends the certification, moving its expiry to the day before the logical clock's
        startup reading; only the field named in the amendment changes, so the account is still
        active, and a design naming the one covered model is now refused too because the expiry
        bound is exclusive and the clock has passed it. Both refusals carry the same
        certification identifier, and no bank was created against the calculation.

        PRD 3.3: "Three prerequisites are checked at design time, in this order. First, the acting installer must be in good standing: `certification_status` of `ACTIVE`, a `certification_expires_on` that the logical clock has not yet reached, and a `certified_model_codes` list that contains the requested `model_code`; any of the three failing raises `ERR_INSTALLER_NOT_CERTIFIED`."
        PRD 3.1: "Expiry is an **exclusive** upper bound: the certification is usable while the logical clock reads strictly earlier than `certification_expires_on`, and is unusable from that instant onward."
        PRD 3.1: "Only the fields present in the amendment are replaced; anything omitted keeps its stored value, and the amendment advances the installer account's `version` by one."
        PRD 2.5: "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

        Design: Corner/errors/uncertified_installer_design_creation_rejected
        """
        project = fixtures.certified_installer(
            api, certified_model_codes=[ModelCode.PWX_A]
        )
        project = fixtures.site_for(api, project)
        project = fixtures.approved_load_calculation(api, project)

        validate_error(
            api.create_battery_system(
                factories.battery_system_payload(
                    project.site_id,
                    project.installer_id,
                    project.load_calculation_id,
                    model_code=ModelCode.PWX_B,
                    inverter_model=InverterModel.GW3_HOME,
                    firmware_version="25.4.0",
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_INSTALLER_NOT_CERTIFIED,
            expected_status=422,
        )

        amended = validate_success(
            api.amend_certification(
                project.installer_id,
                factories.certification_amendment_payload(
                    certification_expires_on=LAPSED_EXPIRY
                ),
                headers=WARRANTY_AGENT_HEADERS,
            )
        )
        assert amended["certification_expires_on"] == LAPSED_EXPIRY
        assert amended["certification_status"] == CertificationStatus.ACTIVE
        assert amended["certified_model_codes"] == [ModelCode.PWX_A]

        validate_error(
            api.create_battery_system(
                factories.battery_system_payload(
                    project.site_id, project.installer_id, project.load_calculation_id
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_INSTALLER_NOT_CERTIFIED,
            expected_status=422,
        )

        systems, _ = validate_paginated(
            api.list_battery_systems(
                {"load_calculation_id": project.load_calculation_id},
                headers=project.installer_headers,
            )
        )
        assert systems == [], "a refused design left a bank behind"


class TestTheSizingGate:
    """A bank sized against the whole house rather than four circuits."""

    def test_one_unit_against_a_whole_home_requirement_is_refused(self, api):
        """Five kilowatts of continuous power against a 21.48 kilowatt obligation.

        Under whole-home scoping the continuous requirement is the connected load itself, so
        the approved calculation demands 21.48 kilowatts. A single unit of the model delivers
        5.0 kilowatts of continuous power, derived from the catalog rather than from anything
        the request said, and the design is refused for insufficient capacity. The calculation
        is untouched and no bank exists against it.

        PRD 3.2: "**Step two, whole-home branch.** When the scope is `WHOLE_HOME`, `required_continuous_kw` is exactly `connected_load_kw`, and `required_surge_kw` is `connected_load_kw` multiplied by 1.75, rounded half up to two decimals."
        PRD 3.3: "Third, the bank's derived `continuous_kw` must be at least the calculation's `required_continuous_kw`, else `ERR_CAPACITY_BELOW_REQUIRED`. A bank whose continuous power exactly equals the requirement is acceptable."
        PRD 2.11: "Model `PWX_A` provides 13.5 usable kWh and 5.0 kW of continuous power per unit, permits at most 10 units in one bank, and requires firmware `24.4.0` or newer."

        Design: Corner/errors/undersized_bank_rejected_against_whole_home_continuous_requirement
        """
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project)
        project = fixtures.approved_load_calculation(
            api,
            project,
            payload=factories.whole_home_load_calculation_payload(project.site_id),
        )
        calculation = get_success_data(
            api.get_load_calculation(
                project.load_calculation_id, headers=project.installer_headers
            )
        )
        assert_quantity(calculation, "required_continuous_kw", 21.48)

        validate_error(
            api.create_battery_system(
                factories.battery_system_payload(
                    project.site_id,
                    project.installer_id,
                    project.load_calculation_id,
                    unit_count=1,
                    installed_cost_cents=1700000,
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_CAPACITY_BELOW_REQUIRED,
            expected_status=422,
        )

        systems, _ = validate_paginated(
            api.list_battery_systems(
                {"load_calculation_id": project.load_calculation_id},
                headers=project.installer_headers,
            )
        )
        assert systems == [], "an undersized design was stored anyway"


class TestThreeCardinalityRules:
    """One permit ever, one live application, one test per type."""

    def test_a_second_permit_application_and_test_each_name_their_own_duplicate(self, api):
        """Three attempts to add a second of something the bank may only hold one of.

        The bank already carries an issued permit, an approved application and all four
        bookings. A second permit is refused because no permit status is terminal and one bank
        may carry one permit ever; a second application is refused because the existing one is
        not denied, even though it asks for a different export posture; and a second booking of
        a type already on the bank is refused as a duplicate rather than as a scheduling
        conflict, because its window sits two days clear of every existing window and so is far
        outside the travel buffer. Each refusal names the entity it guards, and the counts are
        unchanged: one permit, one application, four tests.

        PRD 3.4: "No permit status is terminal, so a bank may carry at most one permit ever: a second attempt is rejected with `ERR_DUPLICATE_PERMIT`."
        PRD 3.5: "A bank may carry only one live application: if it already has one whose `status` is anything other than `DENIED`, a second filing is rejected with `ERR_DUPLICATE_APPLICATION`."
        PRD 3.6: "The four types are `BACKUP_TRANSITION`, `CAPACITY_DISCHARGE`, `ANTI_ISLANDING` and `FIRMWARE_BASELINE`, and a bank may hold at most one test of each type — a second booking of the same type for the same bank is rejected with `ERR_DUPLICATE_TEST`."
        PRD 3.6: "Both sides of every window are padded by 30 minutes of travel buffer before the comparison, and windows are treated as half-open intervals that include their start and exclude their end."

        Design: Corner/errors/second_permit_application_and_test_of_the_same_type_rejected_as_duplicates
        """
        project = fixtures.tests_recorded_project(api)
        system_id = project.battery_system_id

        validate_error(
            api.create_permit(
                factories.permit_payload(system_id, plan_set_ref="PS-2790-B"),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_PERMIT,
            expected_status=409,
        )
        validate_error(
            api.create_application(
                factories.application_payload(
                    system_id,
                    export_mode=ExportMode.NON_EXPORT,
                    requested_export_kw=0.0,
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_APPLICATION,
            expected_status=409,
        )
        validate_error(
            api.create_commissioning_test(
                factories.commissioning_test_payload(
                    system_id, TestType.BACKUP_TRANSITION, *DUPLICATE_TEST_WINDOW
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_TEST,
            expected_status=409,
        )

        permits, permit_meta = validate_paginated(
            api.list_permits(
                {"battery_system_id": system_id}, headers=project.installer_headers
            )
        )
        assert permit_meta["total_count"] == 1
        assert [permit["id"] for permit in permits] == [project.permit_id]
        applications, application_meta = validate_paginated(
            api.list_applications(
                {"battery_system_id": system_id}, headers=project.installer_headers
            )
        )
        assert application_meta["total_count"] == 1
        assert [row["id"] for row in applications] == [project.application_id]
        _, test_meta = validate_paginated(
            api.list_commissioning_tests(
                {"battery_system_id": system_id}, headers=project.installer_headers
            )
        )
        assert test_meta["total_count"] == 4

    def test_a_second_live_claim_on_the_same_pool_is_a_duplicate_not_a_stale_write(self, api):
        """The second reservation carries a freshly read version and is still refused.

        The bank already holds a live reservation against this pool. The second attempt reads
        the bank's current version first, so the concurrency guard is satisfied and cannot be
        what refuses it; the pair of bank and program is what is unique. The pool is untouched
        by the refusal: it still holds exactly the first reservation's 423000 cents, and the
        bank still has exactly one claim.

        PRD 3.7: "A bank may hold only one live claim per program: if it already has a claim on the same program whose `status` is not `VOID`, `DENIED` or `CLAWED_BACK`, the reservation is rejected with `ERR_DUPLICATE_PROGRAM_CLAIM`."
        PRD 2.12: "The supplied expected parent version matches, else `ERR_STALE_SYSTEM_VERSION` or `ERR_STALE_EVENT_VERSION`. This applies to claim reservation, bank expansion and event participation."

        Design: Corner/errors/second_live_claim_against_the_same_program_rejected_as_duplicate
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project)
        first = fixtures.reserve_claim(api, project, program_id)

        validate_error(
            api.create_claim(
                factories.claim_payload(
                    project.battery_system_id,
                    program_id,
                    fixtures.system_version(api, project),
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_PROGRAM_CLAIM,
            expected_status=409,
        )

        claims, meta = validate_paginated(
            api.list_claims(
                {"battery_system_id": project.battery_system_id},
                headers=project.installer_headers,
            )
        )
        assert meta["total_count"] == 1
        assert [claim["id"] for claim in claims] == [first["id"]]
        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=4577000, reserved=423000, paid=0)

    def test_a_second_enrollment_for_the_same_season_is_a_duplicate(self, api):
        """A smaller, perfectly sizeable pledge is still a second enrollment.

        The bank is already enrolled for the season with a five kilowatt pledge. The second
        enrollment offers three kilowatts, well inside what the two-unit bank can sustain, and
        keeps a reserve floor inside the permitted range, so nothing about the pledge itself is
        wrong — the season is already taken. The bank keeps exactly one enrollment and the
        original pledge is unchanged.

        PRD 3.9: "A bank may hold only one live enrollment per season — an existing enrollment for the same `season` whose `status` is not `WITHDRAWN` causes `ERR_DUPLICATE_ENROLLMENT`."
        PRD 3.9: "The pledge itself is bounded: `pledged_kw` must be greater than zero and must not exceed the bank's `continuous_kw`, and `reserve_soc_pct` must lie between 0 and 50 inclusive; either violation is rejected with `ERR_PLEDGE_EXCEEDS_CAPACITY`."

        Design: Corner/errors/second_enrollment_for_the_same_season_rejected_as_duplicate
        """
        project = fixtures.enrolled_project(api)

        validate_error(
            api.create_enrollment(
                factories.enrollment_payload(
                    project.battery_system_id,
                    pledged_kw=3.0,
                    reserve_soc_pct=30,
                    season=Season.SUMMER_2026,
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_ENROLLMENT,
            expected_status=409,
        )

        enrollments, meta = validate_paginated(
            api.list_enrollments(
                {"battery_system_id": project.battery_system_id},
                headers=project.installer_headers,
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in enrollments] == [project.enrollment_id]
        assert_quantity(enrollments[0], "pledged_kw", 5.0)


class TestBoundsSetByTwoDifferentEntities:
    """A figure the program floors and the catalog-derived bank rating ceilings."""

    def test_a_commitment_below_the_pool_floor_and_above_the_bank_rating_share_one_objection(
        self, api
    ):
        """Four kilowatts is too little for the pool, twelve is more than the bank has.

        The pool will not fund a commitment below five kilowatts, and the two-unit bank cannot
        sustain twelve, so the same field is bounded from below by the program and from above by
        the catalog-derived rating of the bank. Both attempts are refused with the one commitment
        objection rather than with two different ones. Neither attempt wrote anything: no claim
        exists on the bank, the pool holds nothing, and the bank's own version is where it was
        before the two refusals, because a refused request is not a mutation.

        PRD 3.7: "The `capacity_commitment_kw` must be at least the program's `min_capacity_commitment_kw` and at most the bank's `continuous_kw` — a household cannot promise more power than its bank can produce — else `ERR_CAPACITY_COMMITMENT_INVALID`."
        PRD 3.7: "`requires_export_commitment` is a boolean that defaults to false, and `min_capacity_commitment_kw` is the least dispatchable capacity a claim must commit and must be non-negative."
        PRD 2.11: "A bank's `usable_kwh` is its `unit_count` multiplied by the per-unit usable energy of its model, and its `continuous_kw` is its `unit_count` multiplied by the per-unit continuous power of its model, each rounded half up to two decimals."
        PRD 2.5: "`version` (integer): a counter that increases by exactly one on every mutation of that resource."

        Design: Corner/errors/capacity_commitment_below_program_minimum_and_above_bank_capacity_rejected
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project)
        system = fixtures.read_system(api, project)
        assert_quantity(system, "continuous_kw", 10.0)

        for commitment in (4.0, 12.0):
            validate_error(
                api.create_claim(
                    factories.claim_payload(
                        project.battery_system_id,
                        program_id,
                        system["version"],
                        capacity_commitment_kw=commitment,
                    ),
                    headers=project.installer_headers,
                ),
                ApiErrorId.ERR_CAPACITY_COMMITMENT_INVALID,
                expected_status=422,
            )

        claims, _ = validate_paginated(
            api.list_claims(
                {"battery_system_id": project.battery_system_id},
                headers=project.installer_headers,
            )
        )
        assert claims == [], "a refused commitment left a claim behind"
        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=5000000, reserved=0, paid=0)
        assert fixtures.system_version(api, project) == system["version"]


class TestTheExpansionCompatibilityTriad:
    """Three catalog rules on one endpoint, each with its own identifier."""

    def test_a_foreign_gateway_old_firmware_and_too_many_units_are_each_refused(self, api):
        """The base bank is energized and eligible; all three requests are still refused.

        The bank is commissioned and permitted to operate, so the expansion endpoint is
        available to it. The first request pairs the bank's GW2-family gateway with a GW3-family
        one and is refused as incompatible. The second keeps the family and offers firmware
        older than both the bank's own and the catalog minimum for the model. The third keeps
        both and asks for nine more units on top of two, one past the model's ceiling of ten.
        Nothing was created or changed: the base bank is still commissioned with two units, its
        version is exactly where it was before the three attempts, and it has no successor.

        PRD 3.8: "Expansion is available only for a bank whose `build_status` is `COMMISSIONED` and whose `grid_status` is `PTO_GRANTED`."
        PRD 3.8: "First, the supplied `inverter_model` must belong to the same gateway family as the base bank's `inverter_model`; mixing a GW2-family gateway with a GW3-family one is rejected with `ERR_INVERTER_INCOMPATIBLE`. Second, the supplied `firmware_version` must be no older than the base bank's `firmware_version` and no older than the catalog minimum firmware for the base bank's `model_code`; either shortfall is rejected with `ERR_FIRMWARE_TOO_OLD`. Third, the base bank's `unit_count` plus `additional_unit_count` must not exceed the catalog's maximum unit count for that model, else `ERR_UNIT_LIMIT_EXCEEDED`."
        PRD 2.11: "The `GW2_HOME` inverter belongs to gateway family GW2 and the `GW3_HOME` inverter belongs to gateway family GW3."
        PRD 2.11: "Model `PWX_A` provides 13.5 usable kWh and 5.0 kW of continuous power per unit, permits at most 10 units in one bank, and requires firmware `24.4.0` or newer."

        Design: Corner/errors/expansion_with_wrong_gateway_old_firmware_or_too_many_units_rejected
        """
        project = fixtures.pto_granted_project(api)
        base_version = fixtures.system_version(api, project)

        attempts = [
            (
                dict(
                    additional_unit_count=2,
                    inverter_model=InverterModel.GW3_HOME,
                    firmware_version="24.6.0",
                    installed_cost_cents=2600000,
                ),
                ApiErrorId.ERR_INVERTER_INCOMPATIBLE,
            ),
            (
                dict(
                    additional_unit_count=2,
                    inverter_model=InverterModel.GW2_HOME,
                    firmware_version="24.2.0",
                    installed_cost_cents=2600000,
                ),
                ApiErrorId.ERR_FIRMWARE_TOO_OLD,
            ),
            (
                dict(
                    additional_unit_count=9,
                    inverter_model=InverterModel.GW2_HOME,
                    firmware_version="24.6.0",
                    installed_cost_cents=9600000,
                ),
                ApiErrorId.ERR_UNIT_LIMIT_EXCEEDED,
            ),
        ]

        for overrides, error_id in attempts:
            validate_error(
                api.expand_system(
                    project.battery_system_id,
                    factories.expansion_payload(base_version, **overrides),
                    headers=project.installer_headers,
                ),
                error_id,
                expected_status=422,
            )

        base = fixtures.read_system(api, project)
        assert base["build_status"] == BuildStatus.COMMISSIONED
        assert base["unit_count"] == 2
        assert base["version"] == base_version
        successors, _ = validate_paginated(
            api.list_battery_systems(
                {"expands_system_id": project.battery_system_id},
                headers=project.installer_headers,
            )
        )
        assert successors == [], "a refused expansion created a successor bank"
