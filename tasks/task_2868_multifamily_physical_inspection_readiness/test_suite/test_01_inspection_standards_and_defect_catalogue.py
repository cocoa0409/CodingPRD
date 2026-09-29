"""Publishing a standard and building its catalogue of scoreable defects."""

from test_helpers import (
    ApiErrorId,
    assert_common_fields,
    assert_created,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_null,
    assert_ok,
    assert_total_count,
    assert_two_decimals,
    constants as K,
    factories as F,
    fixtures as X,
)
from test_helpers.test_users import make_platform_admin_headers

ADMIN = make_platform_admin_headers()


class TestStandardRegistration:
    """Registering a DRAFT standard with its inspectable-area weighting."""

    def test_supplied_adoption_fields_are_ignored_and_the_row_starts_draft(self, api):
        """A body claiming ADOPTED still yields a DRAFT standard.

        PRD: "A newly registered standard has `adoption_status` `DRAFT`,
        `adopted_at` null, `superseded_at` null, and both of its derived
        catalogue counters - `defect_definition_count` and
        `life_threatening_definition_count` - at 0."

        Design: Corner/entities/create_standard_with_supplied_system_extra_field_is_ignored
        """
        response = api.create_standard(
            F.standard_payload(
                adoption_status="ADOPTED",
                adopted_at="2020-01-01T00:00:00.000Z",
                version=77,
            ),
            ADMIN,
        )

        standard = assert_created(response)
        assert_fields(standard, adoption_status="DRAFT")
        assert_null(standard, "adopted_at", "superseded_at")
        assert_integer(
            standard["defect_definition_count"], 0, "defect_definition_count"
        )
        assert_integer(
            standard["life_threatening_definition_count"],
            0,
            "life_threatening_definition_count",
        )
        assert_common_fields(standard, expected_version=1)
        assert standard["id"] != 77

    def test_weights_that_miss_one_hundred_are_rejected(self, api):
        """Weights of 50.00, 30.00 and 30.00 sum to 110.00 and are refused.

        PRD: "The three weights must sum to exactly 100.00, checked at
        registration and again at adoption; a submission that misses is
        rejected with `ERR_WEIGHTS_NOT_NORMALIZED` (HTTP 422)."

        Design: Corner/errors/create_standard_with_weights_that_miss_one_hundred_is_rejected
        """
        response = api.create_standard(
            F.standard_payload(
                code="NSPIRE-BAD",
                name="NSPIRE Bad Weights",
                unit_weight_pct=50.0,
                inside_weight_pct=30.0,
                outside_weight_pct=30.0,
            ),
            ADMIN,
        )

        assert_error(response, ApiErrorId.WEIGHTS_NOT_NORMALIZED)
        assert_total_count(api.list_standards(ADMIN, code="NSPIRE-BAD"), 0)

    def test_second_standard_reusing_a_live_code_is_rejected(self, api):
        """A code held by a DRAFT row cannot be registered again.

        PRD: "a second registration under a code already held by a `DRAFT` or
        `ADOPTED` row is rejected with `ERR_DUPLICATE_STANDARD_CODE` (HTTP
        409)."

        Design: Corner/errors/second_standard_reusing_a_live_code_is_rejected_as_duplicate
        """
        assert_created(api.create_standard(F.standard_payload(), ADMIN))

        response = api.create_standard(
            F.standard_payload(name="NSPIRE 2026 Duplicate"), ADMIN
        )

        assert_error(response, ApiErrorId.DUPLICATE_STANDARD_CODE)
        assert_total_count(api.list_standards(ADMIN, code=K.STANDARD_CODE), 1)

    def test_reading_an_unknown_standard_id_returns_not_found(self, api):
        """A well-formed but unknown path id produces its own 404.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404:
        `ERR_STANDARD_NOT_FOUND`".

        Design: Corner/errors/get_inspection_standard_with_unknown_id_returns_standard_not_found
        """
        response = api.get_standard("00000000-0000-4000-8000-000000000001", ADMIN)

        body = assert_error(response, ApiErrorId.STANDARD_NOT_FOUND)
        assert isinstance(body["message"], str) and body["message"]


class TestDefectCatalogue:
    """Defining the scoreable defects that hang under a standard."""

    def test_reading_a_definition_returns_the_stored_row_and_derived_flag(self, api):
        """The single read echoes the definition plus `is_life_threatening`.

        PRD: "The system derives `is_life_threatening` on the definition,
        setting it to true exactly when `severity` is `LIFE_THREATENING` and
        false otherwise".

        Design: Corner/entities/get_defect_definition_returns_the_stored_row
        """
        bundle = X.draft_standard(api, ("LT_GAS",))
        definition_id = bundle["definition_ids"]["LT_GAS"]

        definition = assert_ok(
            api.get_defect_definition(definition_id, X.INSPECTOR)
        )

        assert_fields(
            definition,
            id=definition_id,
            standard_id=bundle["standard_id"],
            code="LT_GAS",
            inspectable_area="UNIT",
            severity="LIFE_THREATENING",
            correction_deadline_hours=24,
            is_life_threatening=True,
        )
        assert_two_decimals(definition["base_point_value"], 10.00, "base_point_value")

    def test_unknown_severity_is_rejected_as_an_invalid_enum_value(self, api):
        """`CRITICAL` is not a member of the severity enumeration.

        PRD: "every enum-typed body field carries a declared member of its
        enumeration, else `ERR_INVALID_ENUM_VALUE` (422)."

        Design: Corner/entities/create_defect_definition_with_unknown_severity_returns_invalid_enum_value
        """
        bundle = X.draft_standard(api, ())
        standard_id = bundle["standard_id"]

        response = api.create_defect_definition(
            F.defect_definition_payload(
                standard_id,
                "LOW_TRASH",
                code="CRIT_ROOF",
                name="Collapsing roof deck",
                inspectable_area="OUTSIDE",
                severity="CRITICAL",
                base_point_value=8.0,
                correction_deadline_hours=720,
            ),
            ADMIN,
        )

        assert_error(response, ApiErrorId.INVALID_ENUM_VALUE)
        assert_total_count(
            api.list_defect_definitions(ADMIN, standard_id=standard_id), 0
        )
        standard = assert_ok(api.get_standard(standard_id, ADMIN))
        assert_integer(
            standard["defect_definition_count"], 0, "defect_definition_count"
        )

    def test_a_life_threatening_definition_must_declare_a_24_hour_deadline(self, api):
        """A life-threatening defect with a 48-hour clock is refused.

        PRD: "when the `severity` is `LIFE_THREATENING` it must be exactly 24,
        because the twenty-four-hour correction obligation is not negotiable. A
        life-threatening definition declaring anything else is rejected with
        `ERR_LT_DEADLINE_MUST_BE_24H` (HTTP 422)."

        Design: Corner/errors/life_threatening_definition_with_a_forty_eight_hour_deadline_is_rejected
        """
        standard_id = X.draft_standard(api, ())["standard_id"]

        response = api.create_defect_definition(
            F.defect_definition_payload(
                standard_id,
                "LT_GAS",
                code="LT_SLOW",
                name="Slow gas leak",
                correction_deadline_hours=48,
            ),
            ADMIN,
        )

        assert_error(response, ApiErrorId.LT_DEADLINE_MUST_BE_24H)
        standard = assert_ok(api.get_standard(standard_id, ADMIN))
        assert_integer(
            standard["defect_definition_count"], 0, "defect_definition_count"
        )
        assert_integer(
            standard["life_threatening_definition_count"],
            0,
            "life_threatening_definition_count",
        )

    def test_second_definition_reusing_a_code_under_one_standard_is_rejected(self, api):
        """Definition codes are unique per owning standard.

        PRD: "carries a `code` that must be unique among the definitions
        sharing that `standard_id` - a collision is rejected with
        `ERR_DUPLICATE_DEFECT_CODE` (HTTP 409)".

        Design: Corner/errors/second_defect_definition_reusing_a_code_under_one_standard_is_rejected
        """
        bundle = X.draft_standard(api, ("SEV_WINDOW",))
        standard_id = bundle["standard_id"]

        response = api.create_defect_definition(
            F.defect_definition_payload(
                standard_id, "SEV_WINDOW", name="Second inoperable window"
            ),
            ADMIN,
        )

        assert_error(response, ApiErrorId.DUPLICATE_DEFECT_CODE)
        standard = assert_ok(api.get_standard(standard_id, ADMIN))
        assert_integer(
            standard["defect_definition_count"], 1, "defect_definition_count"
        )


class TestAdoption:
    """Adoption is the only producer of an ADOPTED standard."""

    def test_adoption_moves_draft_to_adopted_and_stamps_the_instant(self, api):
        """The supplied `adopted_at` lands on the row with the counts derived.

        PRD: "On success the standard moves `DRAFT -> ADOPTED`, its
        `adoption_status` becomes `ADOPTED` and its `adopted_at` is set to the
        supplied instant."

        Design: Corner/state_machines/adopt_standard_moves_draft_to_adopted_and_stamps_adopted_at
        """
        bundle = X.draft_standard(api, ("LT_GAS", "SEV_WINDOW"))
        draft_version = bundle["standard"]["version"]

        standard = assert_ok(
            api.adopt_standard(bundle["standard_id"], F.adopt_payload(), ADMIN)
        )

        assert_fields(standard, adoption_status="ADOPTED")
        assert_instant(standard["adopted_at"], K.ADOPTED_AT, "adopted_at")
        assert_null(standard, "superseded_at")
        assert_integer(
            standard["defect_definition_count"], 2, "defect_definition_count"
        )
        assert_integer(
            standard["life_threatening_definition_count"],
            1,
            "life_threatening_definition_count",
        )
        assert standard["version"] == draft_version + 1

    def test_adoption_without_a_life_threatening_definition_is_rejected(self, api):
        """A catalogue of one SEVERE defect cannot be adopted.

        PRD: "a standard that defines no life-threatening defect cannot be
        adopted, and the attempt is rejected with
        `ERR_NO_LIFE_THREATENING_DEFINITION` (HTTP 422)."

        Design: Corner/errors/adopting_a_standard_with_no_life_threatening_definition_is_rejected
        """
        bundle = X.draft_standard(api, ("SEV_WINDOW",))

        response = api.adopt_standard(
            bundle["standard_id"], F.adopt_payload(), ADMIN
        )

        assert_error(response, ApiErrorId.NO_LIFE_THREATENING_DEFINITION)
        standard = assert_ok(api.get_standard(bundle["standard_id"], ADMIN))
        assert_fields(standard, adoption_status="DRAFT")
        assert_null(standard, "adopted_at")
        assert_integer(
            standard["defect_definition_count"], 1, "defect_definition_count"
        )
        assert_integer(
            standard["life_threatening_definition_count"],
            0,
            "life_threatening_definition_count",
        )

    def test_adopting_the_same_standard_twice_is_rejected(self, api):
        """A second adoption of an ADOPTED row is inadmissible.

        PRD: "An adoption requested against a standard already in `ADOPTED` or
        in `SUPERSEDED` is rejected with `ERR_STANDARD_ALREADY_ADOPTED` (HTTP
        409)."

        Design: Corner/state_machines/adopt_the_same_standard_twice_returns_already_adopted
        """
        bundle = X.adopted_standard(api, ("LT_GAS", "SEV_WINDOW"))
        adopted_version = bundle["standard"]["version"]

        response = api.adopt_standard(
            bundle["standard_id"],
            F.adopt_payload(adopted_at="2026-01-05T00:00:00.000Z"),
            ADMIN,
        )

        assert_error(response, ApiErrorId.STANDARD_ALREADY_ADOPTED)
        standard = assert_ok(api.get_standard(bundle["standard_id"], ADMIN))
        assert_fields(standard, adoption_status="ADOPTED", version=adopted_version)
        assert_instant(standard["adopted_at"], K.ADOPTED_AT, "adopted_at")
