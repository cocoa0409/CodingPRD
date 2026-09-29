"""The immutable definition library and the mapping proposal, verdict and revision loop."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_common_fields,
    assert_immutable_definition_shape,
    assert_null,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
)

RACE_DOMAIN = ["ASIAN", "BLACK", "WHITE", "UNKNOWN"]
BAD_RACE_MAP = {"A": "ASIAN", "B": "BLACK", "H": "HISPANIC"}
GOOD_RACE_MAP = {"A": "ASIAN", "B": "BLACK", "H": "UNKNOWN"}
RACE_REJECTION = (
    "HISPANIC is not a code in the federal race/ethnicity value domain for this cycle."
)


class TestDefinitionLibraryIsImmutable:
    """A correction to a federal definition is a new row, never an edit."""

    def test_the_same_code_is_reusable_only_under_another_effective_cycle_code(
        self, api, steward
    ):
        """The create response carries no version and no updated_at at all.

        PRD 3.2: "The pair of `definition_code` and `effective_cycle_code` must be unique; a
        collision reports `ERR_DUPLICATE_DEFINITION`."

        PRD 3.2: "As noted in §2.4, a federal definition exposes only `id` and `created_at` — it has
        no `updated_at`, no `version`, and no way to be changed once written."

        Design: Corner/entities/corner_federal_definition_is_immutable_and_versioned_by_cycle_code
        """
        first = validate_success(
            api.create_federal_definition(
                f.make_federal_definition_payload(
                    definition_code="ENR_LEVEL",
                    survey_component=K.DOMAIN_ENROLLMENT,
                    value_domain=["UNDERGRAD", "GRADUATE"],
                    unit_of_measure="code",
                    effective_cycle_code=K.CYCLE_CODE,
                ),
                steward,
            ),
            201,
        )
        assert_immutable_definition_shape(first)
        assert first["required"] is True
        assert first["value_domain"] == ["UNDERGRAD", "GRADUATE"]

        second = validate_success(
            api.create_federal_definition(
                f.make_federal_definition_payload(
                    definition_code="ENR_LEVEL",
                    survey_component=K.DOMAIN_ENROLLMENT,
                    value_domain=["UNDERGRAD", "GRADUATE", "NON_DEGREE"],
                    unit_of_measure="code",
                    effective_cycle_code=K.CYCLE_CODE_ALT,
                ),
                steward,
            ),
            201,
        )
        assert_immutable_definition_shape(second)
        assert second["effective_cycle_code"] == K.CYCLE_CODE_ALT
        assert len(second["value_domain"]) == 3

        collision = api.create_federal_definition(
            f.make_federal_definition_payload(
                definition_code="ENR_LEVEL",
                survey_component=K.DOMAIN_ENROLLMENT,
                value_domain=["UNDERGRAD"],
                unit_of_measure="code",
                effective_cycle_code=K.CYCLE_CODE,
            ),
            steward,
        )
        validate_error(collision, ApiErrorId.DUPLICATE_DEFINITION, 409)

        rows, meta = validate_paginated(
            api.list_federal_definitions(steward, survey_component=K.DOMAIN_ENROLLMENT)
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
        for row in rows:
            assert_immutable_definition_shape(row)
        stored = validate_success(api.get_federal_definition(first["id"], steward))
        assert stored["value_domain"] == ["UNDERGRAD", "GRADUATE"]


class TestMappingIsAJunctionRow:
    """A mapping is unique on the triple of cycle, definition and local system."""

    def test_two_local_systems_coexist_while_the_same_system_collides(
        self, api, registrar, steward, analyst
    ):
        """The same definition stays mappable in a second cycle because the triple differs.

        PRD 3.2: "The triple of `cycle_id`, `definition_id` and `local_system_code` must be unique
        among mappings whose `status` is anything other than `REJECTED`, so a rejected proposal does
        not block a fresh attempt on the same field; a collision against a live row reports
        `ERR_DUPLICATE_MAPPING`."

        Design: Corner/entities/corner_element_mapping_is_the_graph_junction_of_cycle_and_definition
        """
        definition = fx.create_definition(
            api,
            steward,
            definition_code="ENR_LEVEL",
            survey_component=K.DOMAIN_ENROLLMENT,
            value_domain=["UNDERGRAD", "GRADUATE"],
            required=False,
            unit_of_measure="code",
        )
        cycle = fx.create_cycle(api, registrar)
        other = fx.create_cycle(
            api,
            registrar,
            cycle_code="IPEDS-2026",
            collection_year=2026,
            census_date="2025-10-15",
            collection_deadline="2026-02-15T23:59:59Z",
        )

        from_sis = validate_success(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    cycle["id"],
                    definition["id"],
                    local_system_code=K.LOCAL_SYSTEM_SIS,
                    local_field_path="sis.student.level",
                    transform_expression="upper(level_code)",
                    value_map={"UG": "UNDERGRAD", "GR": "GRADUATE"},
                ),
                analyst,
            ),
            201,
        )
        assert from_sis["status"] == K.MAPPING_PROPOSED
        assert from_sis["revision_round"] == 0
        assert_version(from_sis, 1, "mapping")
        assert_common_fields(from_sis, "mapping")

        from_hr = validate_success(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    cycle["id"],
                    definition["id"],
                    local_system_code=K.LOCAL_SYSTEM_HR,
                    local_field_path="hr.appointment.level",
                    transform_expression="upper(appt_level)",
                    value_map={"U": "UNDERGRAD"},
                ),
                analyst,
            ),
            201,
        )
        assert from_hr["status"] == K.MAPPING_PROPOSED

        collision = api.propose_element_mapping(
            f.make_element_mapping_payload(
                cycle["id"],
                definition["id"],
                local_system_code=K.LOCAL_SYSTEM_SIS,
                local_field_path="sis.student.level_v2",
                transform_expression="upper(level_code)",
                value_map={"UG": "UNDERGRAD"},
            ),
            analyst,
        )
        validate_error(collision, ApiErrorId.DUPLICATE_MAPPING, 409)

        elsewhere = validate_success(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    other["id"],
                    definition["id"],
                    local_system_code=K.LOCAL_SYSTEM_SIS,
                    local_field_path="sis.student.level",
                    transform_expression="upper(level_code)",
                    value_map={"UG": "UNDERGRAD"},
                ),
                analyst,
            ),
            201,
        )
        assert elsewhere["cycle_id"] == other["id"]

        by_definition, definition_meta = validate_paginated(
            api.list_element_mappings(analyst, definition_id=definition["id"])
        )
        assert definition_meta["total_count"] == 3
        assert len(by_definition) == 3
        _, cycle_meta = validate_paginated(
            api.list_element_mappings(analyst, cycle_id=cycle["id"])
        )
        assert cycle_meta["total_count"] == 2


class TestValueDomainGuardsBothEndsOfTheLoop:
    """The closed federal domain is enforced on the approval and on the revision alike."""

    def test_a_code_outside_the_domain_blocks_the_approval_and_the_revision(
        self, api, registrar, steward, analyst
    ):
        """A bad code cannot sneak back in through the rejected-to-proposed edge.

        PRD 3.2: "An approval drives `PROPOSED → VALIDATED`: it requires the mapping to be
        `PROPOSED` (otherwise `ERR_INVALID_MAPPING_STATE`), requires the governing cycle's posture to
        be neither `FROZEN` nor `ARCHIVED` (otherwise `ERR_CYCLE_FROZEN`), and requires **every value
        of the `value_map` to appear in the target definition's `value_domain`**, failing which the
        approval is refused with `ERR_VALUE_DOMAIN_VIOLATION`."

        PRD 3.2: "A revision is refused with `ERR_INVALID_MAPPING_STATE` unless the mapping is
        `REJECTED`, with `ERR_CYCLE_FROZEN` when the cycle's posture is `FROZEN` or `ARCHIVED`, and
        with `ERR_VALUE_DOMAIN_VIOLATION` when any value of the *new* `value_map` falls outside the
        target definition's `value_domain`."

        Design: Corner/validations/corner_val_every_value_map_target_must_sit_in_the_federal_value_domain
        """
        cycle = fx.create_cycle(api, registrar)
        definition = fx.create_definition(
            api,
            steward,
            definition_code="EF_RACE_ETHNICITY",
            survey_component=K.DOMAIN_ENROLLMENT,
            value_domain=RACE_DOMAIN,
            required=False,
            unit_of_measure="CODE",
        )
        mapping = validate_success(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    cycle["id"],
                    definition["id"],
                    local_system_code=K.LOCAL_SYSTEM_SIS,
                    local_field_path="SIS.STUDENT.ETHNICITY",
                    transform_expression="UPPER(TRIM(x))",
                    value_map=BAD_RACE_MAP,
                ),
                analyst,
            ),
            201,
        )
        assert mapping["status"] == K.MAPPING_PROPOSED

        refused = api.validate_element_mapping(
            mapping["id"], f.make_mapping_verdict_payload(K.DECISION_APPROVE), steward
        )
        validate_error(refused, ApiErrorId.VALUE_DOMAIN_VIOLATION, 422)

        held = validate_success(api.get_element_mapping(mapping["id"], analyst))
        assert held["status"] == K.MAPPING_PROPOSED
        assert_version(held, 1, "mapping")

        rejected = validate_success(
            api.validate_element_mapping(
                mapping["id"],
                f.make_mapping_verdict_payload(K.DECISION_REJECT, RACE_REJECTION),
                steward,
            )
        )
        assert rejected["status"] == K.MAPPING_REJECTED
        assert rejected["rejection_reason"] == RACE_REJECTION
        assert rejected["validated_by_user_id"] == "steward-1"
        assert_version(rejected, 2, "mapping")

        replayed = api.revise_element_mapping(
            mapping["id"],
            f.make_mapping_revision_payload("UPPER(TRIM(x))", BAD_RACE_MAP),
            analyst,
        )
        validate_error(replayed, ApiErrorId.VALUE_DOMAIN_VIOLATION, 422)

        still_rejected = validate_success(api.get_element_mapping(mapping["id"], analyst))
        assert still_rejected["status"] == K.MAPPING_REJECTED
        assert still_rejected["revision_round"] == 0
        assert_version(still_rejected, 2, "mapping")

        revised = validate_success(
            api.revise_element_mapping(
                mapping["id"],
                f.make_mapping_revision_payload("UPPER(TRIM(x))", GOOD_RACE_MAP),
                analyst,
            )
        )
        assert revised["status"] == K.MAPPING_PROPOSED
        assert revised["revision_round"] == 1
        assert_null(revised["rejection_reason"], "mapping.rejection_reason")
        assert_version(revised, 3, "mapping")
        assert revised["value_map"] == GOOD_RACE_MAP

        validated = validate_success(
            api.validate_element_mapping(
                mapping["id"], f.make_mapping_verdict_payload(K.DECISION_APPROVE), steward
            )
        )
        assert validated["status"] == K.MAPPING_VALIDATED
        assert_version(validated, 4, "mapping")

        rows, meta = validate_paginated(
            api.list_element_mappings(
                analyst, cycle_id=cycle["id"], status=K.MAPPING_VALIDATED
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1


class TestRejectionReasonIsDecisionConditional:
    """Only the negative verdict carries the ten-character narrative burden."""

    def test_a_missing_and_a_nine_character_reason_both_fail_while_approve_needs_none(
        self, api, registrar, steward, analyst
    ):
        """Neither refused verdict records a steward or moves the mapping's status.

        PRD 3.2: "A rejection drives `PROPOSED → REJECTED`: it likewise requires the mapping to be
        `PROPOSED`, and it additionally demands a `rejection_reason` of 10 to 500 characters, absent
        which the verdict is refused with `ERR_REJECTION_REASON_REQUIRED`."

        Design: Corner/validations/corner_val_mapping_rejection_demands_a_reason_of_at_least_ten_characters
        """
        cycle = fx.create_cycle(api, registrar)
        definition = fx.create_definition(
            api,
            steward,
            definition_code="EF_ATTENDANCE_STATUS",
            survey_component=K.DOMAIN_ENROLLMENT,
            value_domain=[K.ENTRY_FULL_TIME, K.ENTRY_PART_TIME],
            required=False,
            unit_of_measure="CODE",
        )
        mapping = validate_success(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    cycle["id"],
                    definition["id"],
                    local_system_code=K.LOCAL_SYSTEM_SIS,
                    local_field_path="SIS.ENROLL.LOAD_CODE",
                    transform_expression="CASE WHEN x >= 12 THEN 'FT' ELSE 'PT' END",
                    value_map={"FT": K.ENTRY_FULL_TIME, "PT": K.ENTRY_PART_TIME},
                ),
                analyst,
            ),
            201,
        )

        omitted = api.validate_element_mapping(
            mapping["id"], f.make_mapping_verdict_payload(K.DECISION_REJECT), steward
        )
        validate_error(omitted, ApiErrorId.REJECTION_REASON_REQUIRED, 422)

        short_reason = "too short"
        assert len(short_reason) == K.MIN_REJECTION_REASON_LENGTH - 1
        below_floor = api.validate_element_mapping(
            mapping["id"],
            f.make_mapping_verdict_payload(K.DECISION_REJECT, short_reason),
            steward,
        )
        validate_error(below_floor, ApiErrorId.REJECTION_REASON_REQUIRED, 422)

        untouched = validate_success(api.get_element_mapping(mapping["id"], analyst))
        assert untouched["status"] == K.MAPPING_PROPOSED
        assert_null(untouched["rejection_reason"], "mapping.rejection_reason")
        assert_null(untouched["validated_by_user_id"], "mapping.validated_by_user_id")
        assert_version(untouched, 1, "mapping")

        approved = validate_success(
            api.validate_element_mapping(
                mapping["id"], f.make_mapping_verdict_payload(K.DECISION_APPROVE), steward
            )
        )
        assert approved["status"] == K.MAPPING_VALIDATED
        assert approved["validated_by_user_id"] == "steward-1"
        assert_version(approved, 2, "mapping")
