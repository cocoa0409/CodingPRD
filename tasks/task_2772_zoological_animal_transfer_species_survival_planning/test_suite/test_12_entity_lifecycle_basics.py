"""Registration, defaults, reads, listings and the not-found and schema rungs."""

from __future__ import annotations

from prd_bench_local_runner.testing import (NON_EXISTENT_UUID, validate_error,
                                            validate_paginated,
                                            validate_success)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_ANIMAL_NOT_FOUND, ERR_INVALID_REQUEST,
                                     ERR_SPECIES_PROGRAM_NOT_FOUND)
from test_helpers.assertions import (assert_envelope_meta, assert_money,
                                     assert_slot_counts,
                                     assert_versioned_system_fields)
from test_helpers.test_users import (make_admin_headers,
                                    make_coordinator_headers,
                                    make_registrar_headers)


class TestInstitutionRegistration:
    """A freshly registered institution starts from declared zero values."""

    def test_registration_returns_the_declared_starting_values(self, api):
        """Both slot counters are 0, both balances 0.00 and version is 1.

        PRD: "A freshly registered institution starts with `occupied_slots` at 0,
        `reserved_slots` at 0, `transfer_credit_balance` at 0.00 and
        `compliance_points_balance` at 0.00."

        Design: Corner/entities/institution_creation_returns_declared_defaults
        """
        response = api.create_institution(
            f.sender_institution_payload(), make_admin_headers()
        )
        data = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object"
        assert_envelope_meta(body)
        assert data["name"] == "Cedar Ridge Zoo"
        assert data["jurisdiction_code"] == "US-CA"
        assert data["holding_capacity_slots"] == 40
        assert data["disposition_policy_on_file"] is True
        assert_slot_counts(data, 0, 0)
        assert_money(data["transfer_credit_balance"], 0.00, "credit balance")
        assert_money(data["compliance_points_balance"], 0.00, "points balance")
        assert_versioned_system_fields(data)
        assert data["version"] == 1
        assert data["created_at"] == data["updated_at"]


class TestAnimalAccessionDefaults:
    """An accession without pedigree pointers still gets every declared default."""

    def test_accession_omitting_parents_stamps_the_opening_state(self, api):
        """location_status HELD, genetic_designation UNEVALUATED and null pointers.

        PRD: "A newly accessioned animal opens with `location_status` at `HELD`,
        `genetic_designation` at `UNEVALUATED`, `pending_recommendation_id` null,
        `crate_training_sessions_count` at 0 and `last_crate_session_on` null."

        Design: Corner/entities/animal_creation_omits_optional_parents_and_applies_state_defaults
        """
        world = fx.base_world(api, publish=False)
        data = validate_success(
            api.create_animal(
                f.animal_payload(world.program_id, world.sender_id),
                make_registrar_headers(world.sender_id),
            ),
            201,
        )
        assert data["location_status"] == "HELD"
        assert data["genetic_designation"] == "UNEVALUATED"
        assert data["crate_training_sessions_count"] == 0
        assert data["last_crate_session_on"] is None
        assert data["pending_recommendation_id"] is None
        assert data["sire_id"] is None
        assert data["dam_id"] is None
        assert data["version"] == 1


class TestSpeciesProgramRead:
    """A read echoes what creation stored, including the derived opening values."""

    def test_reading_a_new_programme_returns_its_draft_row(self, api):
        """plan_status DRAFT, cycle 1, no open recommendations and no closing date.

        PRD: "A new programme opens with `plan_status` at `DRAFT`,
        `current_plan_cycle` at 1, `current_population_count` at 0,
        `open_recommendation_count` at 0 and `cycle_closed_on` null."

        Design: Corner/entities/get_species_program_returns_stored_row
        """
        created = validate_success(
            api.create_species_program(f.species_program_payload(),
                                       make_admin_headers()),
            201,
        )
        response = api.get_species_program(
            created["id"], make_coordinator_headers(created["id"])
        )
        data = validate_success(response)
        assert response.json()["response_type"] == "object"
        assert data["taxon_name"] == "Panthera uncia"
        assert data["program_type"] == "SSP_RED"
        assert data["target_population_size"] == 300
        assert data["plan_status"] == "DRAFT"
        assert data["current_plan_cycle"] == 1
        assert data["current_population_count"] == 0
        assert data["open_recommendation_count"] == 0
        assert data["cycle_closed_on"] is None


class TestAnimalListing:
    """Filters narrow the matching set and pagination pages through it."""

    @staticmethod
    def _three_animals(api):
        world = fx.base_world(api, publish=False)
        fx.accession(world, world.sender_id, "CR-101", "MALE", "2019-05-10", 12.45)
        fx.accession(world, world.sender_id, "CR-102", "MALE", "2019-09-01", 22.00)
        fx.accession(world, world.receiver_id, "HB-201", "FEMALE", "2020-03-15",
                     30.00)
        return world

    def test_a_holder_filter_with_a_one_row_page_reports_the_full_match_count(
            self, api):
        """total_count counts the two Cedar Ridge animals before paging is applied.

        PRD: "the `meta` object carries `limit` (the effective page size for this
        response), `offset` (the effective starting position), `total_count` (the
        number of records matching the filters before pagination is applied) and
        `has_more` (true when records remain beyond this page)."

        Design: Corner/entities/list_animals_filtered_by_holder_and_paginated
        """
        world = self._three_animals(api)
        response = api.list_animals(
            world.admin,
            {"holding_institution_id": world.sender_id, "limit": 1, "offset": 0},
        )
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert len(rows) == 1
        assert rows[0]["holding_institution_id"] == world.sender_id
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

    def test_an_offset_past_the_end_returns_an_empty_final_page(self, api):
        """Offset 2 over a two-row match set yields no rows and has_more false.

        PRD: "`offset` controls the starting position: it defaults to 0 when
        omitted and its minimum accepted value is 0, with no upper bound."

        Design: Corner/entities/list_animals_filtered_by_holder_and_paginated
        """
        world = self._three_animals(api)
        rows, meta = validate_paginated(
            api.list_animals(
                world.admin,
                {"holding_institution_id": world.sender_id, "limit": 1,
                 "offset": 2},
            )
        )
        assert rows == []
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

    def test_omitting_the_page_size_applies_the_default_limit(self, api):
        """A status filter matching all three rows pages at the default size of 10.

        PRD: "`limit` controls page size: it defaults to 10 when omitted, its
        minimum accepted value is 1 and its maximum accepted value is 100."

        Design: Corner/entities/list_animals_filtered_by_holder_and_paginated
        """
        world = self._three_animals(api)
        rows, meta = validate_paginated(
            api.list_animals(world.admin, {"location_status": "HELD"})
        )
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert len(rows) == 3


class TestNotFoundReads:
    """A path resource that names nothing produces the 404 for its kind."""

    def test_reading_an_unminted_animal_id_is_an_error_envelope(self, api):
        """The response is a 404 error envelope, not an empty success object.

        PRD: "Each miss produces the 404 that names the missing kind:
        `ERR_SPECIES_PROGRAM_NOT_FOUND`, `ERR_INSTITUTION_NOT_FOUND`,
        `ERR_VETERINARIAN_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`"

        Design: Corner/entities/get_animal_unknown_id_returns_animal_not_found
        """
        world = fx.register_institutions(api)
        response = api.get_animal(NON_EXISTENT_UUID,
                                  make_registrar_headers(world.sender_id))
        data = validate_error(response, ERR_ANIMAL_NOT_FOUND, 404)
        assert response.json()["response_type"] == "error"
        assert isinstance(data["message"], str) and data["message"].strip()

    def test_a_nested_route_resolves_its_path_parent_before_the_body(self, api):
        """A crate session logged against an unknown animal is a 404, not a 400.

        PRD: "Resources named in the path are resolved first, left to right, and
        only then are resources named in the request body resolved, in the order
        their fields are declared on the target entity."

        Design: Corner/entities/crate_training_session_on_unknown_animal_returns_animal_not_found
        """
        world = fx.register_institutions(api)
        response = api.create_crate_training_session(
            NON_EXISTENT_UUID, f.crate_training_session_payload(),
            make_registrar_headers(world.sender_id),
        )
        validate_error(response, ERR_ANIMAL_NOT_FOUND, 404)


class TestSchemaRungPrecedesExistence:
    """The schema rung fires before any foreign key is resolved."""

    def test_a_missing_required_field_is_refused_before_the_body_keys_resolve(
            self, api):
        """An accession with no sex and an unknown programme reports the schema fault.

        PRD: "**Schema** — required fields present; enum values in range; numbers
        within their stated bounds; dates and instants well-formed ISO 8601"

        Design: Corner/entities/create_animal_without_sex_returns_invalid_request
        """
        world = fx.base_world(api, publish=False)
        payload = f.animal_payload(NON_EXISTENT_UUID, world.sender_id)
        payload.pop("sex")
        response = api.create_animal(payload,
                                     make_registrar_headers(world.sender_id))
        validate_error(response, ERR_INVALID_REQUEST, 400)
        _, meta = validate_paginated(api.list_animals(world.admin))
        assert meta["total_count"] == 0

    def test_an_enum_value_outside_the_declared_set_is_refused(self, api):
        """A sex of NEUTER is outside MALE, FEMALE and UNDETERMINED.

        PRD: "**Physical custody** is tracked by `location_status`, which takes
        one of `HELD`, `RESERVED`, `IN_TRANSIT`, `IN_QUARANTINE`,
        `AWAITING_INTRODUCTION`, `INTRODUCING` or `DISPOSED`, with `DISPOSED`
        terminal."

        Design: Corner/entities/create_animal_with_unknown_sex_enum_returns_invalid_request
        """
        world = fx.base_world(api, publish=False)
        response = api.create_animal(
            f.animal_payload(world.program_id, world.sender_id, sex="NEUTER"),
            make_registrar_headers(world.sender_id),
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)
        _, meta = validate_paginated(api.list_animals(world.admin))
        assert meta["total_count"] == 0

    def test_a_body_foreign_key_that_names_nothing_is_a_404(self, api):
        """An unknown species_program_id on an accession is reported by kind.

        PRD: "Each miss produces the 404 that names the missing kind:
        `ERR_SPECIES_PROGRAM_NOT_FOUND`, `ERR_INSTITUTION_NOT_FOUND`,
        `ERR_VETERINARIAN_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`"

        Design: Corner/entities/create_animal_with_unknown_species_program_returns_program_not_found
        """
        world = fx.register_institutions(api)
        response = api.create_animal(
            f.animal_payload(NON_EXISTENT_UUID, world.sender_id),
            make_registrar_headers(world.sender_id),
        )
        validate_error(response, ERR_SPECIES_PROGRAM_NOT_FOUND, 404)
        _, meta = validate_paginated(api.list_animals(world.admin))
        assert meta["total_count"] == 0


class TestAnimalSystemFields:
    """Every write bumps the version and leaves the creation stamp alone."""

    def test_a_crate_session_raises_the_version_and_stamps_the_recency_marker(
            self, api):
        """Version moves 1 to 2, the count is recomputed and the date is stored.

        PRD: "Each logged session recomputes two fields on the animal:
        `crate_training_sessions_count` is the total number of sessions ever
        recorded for that animal, and `last_crate_session_on` is the latest
        `session_date` among them"

        Design: Corner/entities/animal_system_fields_stamped_and_version_increments_on_write
        """
        world = fx.base_world(api, publish=False)
        created = fx.accession(world, world.sender_id, "CR-101", "MALE",
                               "2019-05-10", 12.45)
        assert created["version"] == 1
        assert_versioned_system_fields(created)
        validate_success(
            api.create_crate_training_session(
                created["id"], f.crate_training_session_payload(),
                make_registrar_headers(world.sender_id),
            ),
            201,
        )
        animal = validate_success(api.get_animal(created["id"], world.admin))
        assert animal["version"] == 2
        assert animal["created_at"] == created["created_at"]
        assert animal["crate_training_sessions_count"] == 1
        assert str(animal["last_crate_session_on"])[:10] == "2026-07-28"
