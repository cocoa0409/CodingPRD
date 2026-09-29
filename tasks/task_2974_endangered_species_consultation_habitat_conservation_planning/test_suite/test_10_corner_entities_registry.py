"""Registry-side entity claims: species, critical habitat, proponents, actions.

Creation defaults, retrieval fidelity, rung-7 body conformance, the recomputed
critical-habitat flag, path-before-body resolution, and the unpaginated
sub-resource listing convention.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_critical_habitat_unit,
    assert_error_envelope,
    assert_project_action,
    assert_proponent,
    assert_species,
    assert_unpaginated_list,
)
from test_helpers.factories import (
    critical_habitat_unit_payload,
    project_action_payload,
    proponent_payload,
)
from test_helpers.fixtures import (
    AUDITOR,
    CANONICAL_CLOCK,
    REGISTRAR,
    designate_critical_habitat_unit,
    read_species,
    register_proponent,
    register_species,
    register_threatened_species,
    set_clock,
)
from test_helpers.test_users import anonymous_headers, make_proponent_headers

OWL_BODY = {
    "scientific_name": "Athene cunicularia hypugaea",
    "common_name": "Western burrowing owl",
    "listing_status": "CANDIDATE",
    "take_authorization_unit": "NESTS",
    "take_density_per_acre": 0.12,
    "recovery_unit_population": 21000,
    "survey_season_start_month": 3,
    "survey_season_end_month": 8,
}

FROG_BODY = {
    "scientific_name": "Rana draytonii",
    "common_name": "California red-legged frog",
    "listing_status": "THREATENED",
    "take_authorization_unit": "INDIVIDUALS",
    "take_density_per_acre": 0.30,
    "recovery_unit_population": 5000,
    "survey_season_start_month": 1,
    "survey_season_end_month": 5,
}

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


class TestSpeciesRegistration:
    """The eight declared inputs plus the three registry defaults."""

    def test_species_creation_returns_201_with_registry_defaults(self, api):
        """A complete registration echoes its inputs and seeds three counters.

        PRD: "A newly registered species has `critical_habitat_designated` false,
        `listing_change_count` at 0, and `last_listing_change_at` null."

        PRD: "`listing_change_count` starts at 0 and counts accepted listing changes.
        `last_listing_change_at` is null until the first change and thereafter holds
        the logical-clock instant of the most recent one."

        Design: Corner/entities/species_creation_returns_201_with_registry_defaults
        """
        set_clock(CANONICAL_CLOCK)

        species = get_success_data(api.create_species(dict(OWL_BODY), REGISTRAR), 201)

        assert species["scientific_name"] == "Athene cunicularia hypugaea"
        assert species["common_name"] == "Western burrowing owl"
        assert species["listing_status"] == "CANDIDATE"
        assert species["take_authorization_unit"] == "NESTS"
        assert species["take_density_per_acre"] == 0.12
        assert species["recovery_unit_population"] == 21000
        assert species["survey_season_start_month"] == 3
        assert species["survey_season_end_month"] == 8
        assert species["critical_habitat_designated"] is False
        assert species["listing_change_count"] == 0
        assert species["last_listing_change_at"] is None
        assert_species(species)
        assert_common_fields(species, "species")
        assert species["version"] == 1

    def test_species_retrieval_returns_the_stored_row(self, api):
        """The auditor reads back exactly what the registrar stored.

        PRD: "`take_density_per_acre` is a non-negative number with exactly two
        decimal places giving expected individuals - or nests - per acre of occupied
        habitat. `recovery_unit_population` is an integer of at least 1 giving the
        rangewide recovery-unit population, and it serves as the denominator of the
        jeopardy screen."

        PRD: "A species also carries its detectability season, expressed as two
        integers between 1 and 12 inclusive: `survey_season_start_month` and
        `survey_season_end_month`, the latter being the last month of the season and
        inclusive."

        Design: Corner/entities/species_retrieval_returns_the_stored_row
        """
        set_clock(CANONICAL_CLOCK)
        created = register_species()

        species = read_species(created["id"], AUDITOR)

        assert species["scientific_name"] == "Gopherus agassizii"
        assert species["listing_status"] == "ENDANGERED"
        assert species["take_authorization_unit"] == "INDIVIDUALS"
        assert species["take_density_per_acre"] == 0.40
        assert species["recovery_unit_population"] == 4000
        assert species["survey_season_start_month"] == 4
        assert species["survey_season_end_month"] == 7
        assert species["critical_habitat_designated"] is False
        assert species["listing_change_count"] == 0
        assert species["id"] == created["id"]


class TestSpeciesBodyConformance:
    """Rung 7 decides every malformed species registration.

    PRD: "(7) Request-body shape and type conformance - `ERR_INVALID_REQUEST`."
    """

    def test_species_creation_missing_recovery_unit_population_is_rejected(self, api):
        """Omitting the jeopardy denominator is a 400, never a defaulted zero.

        PRD: "It requires every mandatory field present, no unknown fields, correct
        JSON types, enum values drawn from the declared member set for that field"

        PRD: "`recovery_unit_population` is an integer of at least 1 giving the
        rangewide recovery-unit population, and it serves as the denominator of the
        jeopardy screen."

        Nothing is stored by the rejected call, which is observable because the
        register enforces a unique `scientific_name`: the identical body carrying the
        missing field is accepted afterwards under the same name.

        Design: Corner/entities/species_creation_missing_required_field_rejected
        """
        set_clock(CANONICAL_CLOCK)
        body = {k: v for k, v in FROG_BODY.items() if k != "recovery_unit_population"}

        response = api.create_species(body, REGISTRAR)

        assert_error_envelope(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        stored = get_success_data(api.create_species(dict(FROG_BODY), REGISTRAR), 201)
        assert stored["recovery_unit_population"] == 5000

    def test_every_omitted_required_species_field_is_rejected(self, api):
        """None of the eight inputs is optional.

        PRD: "Registering a species records its `scientific_name` - the binomial name,
        between 1 and 120 characters, and unique across the whole register under a
        case-sensitive exact-match comparison - together with its `common_name`, also
        between 1 and 120 characters, which is the name that appears on
        determinations."

        PRD: "It requires every mandatory field present, no unknown fields"

        Design: Corner/entities/species_creation_missing_required_field_rejected
        """
        set_clock(CANONICAL_CLOCK)

        for field in FROG_BODY:
            body = {k: v for k, v in FROG_BODY.items() if k != field}
            response = api.create_species(body, REGISTRAR)
            assert_error_envelope(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_species_creation_with_an_undeclared_enum_member_is_rejected(self, api):
        """EXTINCT and PAIRS are outside the declared member sets.

        PRD: "`listing_status` is one of `ENDANGERED`, `THREATENED`, `PROPOSED`, or
        `CANDIDATE`, and it is the only field on a species that a later operation can
        change."

        PRD: "`take_authorization_unit` is one of `INDIVIDUALS`, `ACRES`, or `NESTS`,
        and it declares the unit in which incidental take for this species is
        authorized and reported."

        Design: Corner/entities/species_creation_invalid_enum_or_month_rejected
        """
        set_clock(CANONICAL_CLOCK)

        listing = api.create_species(
            dict(FROG_BODY, listing_status="EXTINCT"), REGISTRAR
        )
        assert_error_envelope(listing, ApiErrorId.ERR_INVALID_REQUEST, 400)

        unit = api.create_species(
            dict(FROG_BODY, take_authorization_unit="PAIRS"), REGISTRAR
        )
        assert_error_envelope(unit, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_species_numeric_range_constraints_are_enforced(self, api):
        """A month of 13, a negative density and a population of 0 are each 400.

        PRD: "quantity fields non-negative and carrying at most two decimal places,
        month fields as integers between 1 and 12 inclusive"

        PRD: "A species also carries its detectability season, expressed as two
        integers between 1 and 12 inclusive"

        Design: Corner/entities/species_creation_invalid_enum_or_month_rejected
        """
        set_clock(CANONICAL_CLOCK)

        month = api.create_species(
            dict(FROG_BODY, survey_season_start_month=13), REGISTRAR
        )
        assert_error_envelope(month, ApiErrorId.ERR_INVALID_REQUEST, 400)

        density = api.create_species(
            dict(FROG_BODY, take_density_per_acre=-0.10), REGISTRAR
        )
        assert_error_envelope(density, ApiErrorId.ERR_INVALID_REQUEST, 400)

        population = api.create_species(
            dict(FROG_BODY, recovery_unit_population=0), REGISTRAR
        )
        assert_error_envelope(population, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_system_counter_supplied_as_input_is_rejected_not_ignored(self, api):
        """An unknown key is a 400 even when its value matches the default.

        PRD: "It requires every mandatory field present, no unknown fields, correct
        JSON types"

        PRD: "`listing_change_count` starts at 0 and counts accepted listing changes."

        With the extra key removed the identical body is accepted and the counter
        still reads 0, so the rejection is about the key, not about the value.

        Design: Corner/entities/species_system_counter_input_ignored
        """
        set_clock(CANONICAL_CLOCK)

        counter = api.create_species(
            dict(FROG_BODY, listing_change_count=7), REGISTRAR
        )
        assert_error_envelope(counter, ApiErrorId.ERR_INVALID_REQUEST, 400)

        computed = api.create_species(
            dict(FROG_BODY, critical_habitat_designated=True), REGISTRAR
        )
        assert_error_envelope(computed, ApiErrorId.ERR_INVALID_REQUEST, 400)

        species = get_success_data(api.create_species(dict(FROG_BODY), REGISTRAR), 201)
        assert species["listing_change_count"] == 0
        assert species["critical_habitat_designated"] is False

    def test_common_fields_supplied_as_input_are_rejected(self, api):
        """Clients never supply id, created_at, updated_at or version.

        PRD: "Every persisted resource carries a server-minted `id`, formatted as a
        UUID with no type prefix of any kind. Clients never supply an `id`."

        PRD: "`version` begins at 1 on creation and increases by exactly 1 on every
        mutation of that row"

        Design: Corner/entities/species_system_counter_input_ignored
        """
        set_clock(CANONICAL_CLOCK)

        for field, value in (
            ("id", MISSING_UUID),
            ("created_at", "2026-10-01T00:00:00.000Z"),
            ("updated_at", "2026-10-01T00:00:00.000Z"),
            ("version", 1),
        ):
            response = api.create_species(dict(FROG_BODY, **{field: value}), REGISTRAR)
            assert_error_envelope(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestCriticalHabitatDesignation:
    """The species flag is recomputed from the unit set on every unit create."""

    def test_the_designation_flag_tracks_only_final_units(self, api):
        """A PROPOSED unit leaves the flag false; a later FINAL unit flips it true.

        PRD: "Whenever a unit is created, the owning species' `critical_habitat_designated`
        flag is recomputed: it becomes true when at least one unit belonging to that
        species has `designation_status` equal to `FINAL`, and stays false otherwise. A
        register of purely `PROPOSED` units therefore leaves the flag false."

        Design: Corner/entities/critical_habitat_unit_creation_recomputes_species_designation_flag
        """
        set_clock(CANONICAL_CLOCK)
        endangered = register_species()
        threatened = register_threatened_species()
        designate_critical_habitat_unit(endangered["id"])
        designate_critical_habitat_unit(
            threatened["id"], unit_code="CHU-T1", designation_status="PROPOSED"
        )

        assert read_species(threatened["id"], AUDITOR)["critical_habitat_designated"] is False
        assert read_species(endangered["id"], AUDITOR)["critical_habitat_designated"] is True

        designate_critical_habitat_unit(
            threatened["id"], unit_code="CHU-T2", designation_status="FINAL"
        )

        assert read_species(threatened["id"], AUDITOR)["critical_habitat_designated"] is True
        rows = assert_unpaginated_list(
            api.list_critical_habitat_units(threatened["id"], AUDITOR)
        )
        assert [row["unit_code"] for row in rows] == ["CHU-T1", "CHU-T2"]

    def test_unit_creation_under_an_unknown_species_reports_the_species(self, api):
        """Path resolution at rung 4 precedes body conformance at rung 7.

        PRD: "Path identifiers are resolved **left to right**, and the leftmost
        unresolvable segment decides the error. A request naming a species that does
        not exist, then a habitat unit under it, reports the species failure and never
        reaches the unit."

        PRD: "(4) Left-to-right path existence - the eleven 404 codes."

        Design: Corner/entities/critical_habitat_unit_parent_species_not_found
        """
        set_clock(CANONICAL_CLOCK)
        body = critical_habitat_unit_payload(
            unit_code="CHU-X", acres=120.00, primary_constituent_elements=["burrow substrate"]
        )

        response = api.create_critical_habitat_unit(MISSING_UUID, body, REGISTRAR)
        assert_error_envelope(response, ApiErrorId.ERR_SPECIES_NOT_FOUND, 404)

        malformed = {k: v for k, v in body.items() if k != "unit_code"}
        response = api.create_critical_habitat_unit(MISSING_UUID, malformed, REGISTRAR)
        assert_error_envelope(response, ApiErrorId.ERR_SPECIES_NOT_FOUND, 404)

    def test_unit_listing_is_unpaginated_and_created_at_ascending(self, api):
        """The sub-resource envelope carries a null pagination block.

        PRD: "Every other list endpoint in this specification - a species' critical
        habitat units ... is **unpaginated**. Those endpoints return the complete
        collection, accept no `limit` or `offset`, and carry a null pagination block in
        `meta` rather than pagination counters."

        PRD: "All lists, paginated and unpaginated alike, are ordered by `created_at`
        ascending. No list is ordered by `id`"

        Design: Corner/entities/critical_habitat_units_listing_is_unpaginated_and_ordered
        """
        set_clock(CANONICAL_CLOCK)
        species = register_species()
        designate_critical_habitat_unit(species["id"])
        designate_critical_habitat_unit(
            species["id"], unit_code="CHU-2", designation_status="PROPOSED"
        )

        rows = assert_unpaginated_list(
            api.list_critical_habitat_units(species["id"], AUDITOR)
        )

        assert len(rows) == 2
        assert rows[0]["unit_code"] == "CHU-1"
        assert rows[1]["unit_code"] == "CHU-2"
        assert rows[0]["designation_status"] == "FINAL"
        assert rows[1]["designation_status"] == "PROPOSED"
        for row in rows:
            assert row["species_id"] == species["id"]
            assert_critical_habitat_unit(row)


class TestProponentRegistration:
    """The one anonymous endpoint, its single default, and its seeded scores."""

    def test_proponent_creation_applies_declared_defaults(self, api):
        """The omitted optional flag defaults to false and the scores start clean.

        PRD: "and optionally `is_federal_agency`, a boolean that defaults to false and
        marks the case where the proponent is itself a federal action agency."

        PRD: "A freshly registered proponent has `compliance_standing_score` at
        100.00, `compliance_variant_applied` at `LIFETIME`, and
        `open_reinitiation_count` at 0, because no reports exist yet to score it
        against."

        Design: Corner/entities/proponent_creation_applies_declared_defaults
        """
        set_clock(CANONICAL_CLOCK)
        body = {
            "org_name": "Sunrise Logistics Park LLC",
            "contact_email": "permits@sunrise-park.example",
        }

        proponent = get_success_data(
            api.create_proponent(body, anonymous_headers()), 201
        )

        assert proponent["is_federal_agency"] is False
        assert proponent["compliance_standing_score"] == 100.00
        assert proponent["compliance_variant_applied"] == "LIFETIME"
        assert proponent["open_reinitiation_count"] == 0
        assert proponent["org_name"] == "Sunrise Logistics Park LLC"
        assert proponent["contact_email"] == "permits@sunrise-park.example"
        assert_proponent(proponent)

    def test_contact_email_must_carry_exactly_one_at_sign(self, api):
        """An address with no at-sign is a rung-7 rejection.

        PRD: "`contact_email`, the notification address for consultation
        correspondence, between 5 and 160 characters and containing exactly one
        at-sign"

        Design: Corner/entities/proponent_creation_applies_declared_defaults
        """
        set_clock(CANONICAL_CLOCK)

        response = api.create_proponent(
            proponent_payload(contact_email="permits-sunrise-park.example"),
            anonymous_headers(),
        )

        assert_error_envelope(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestProjectActionRegistration:
    """Six seeded values and the one cross-field date check at rung 7."""

    def test_a_new_action_is_seeded_screening_and_pending(self, api):
        """PENDING is a distinct member from NO_EFFECT, and no consultation exists yet.

        PRD: "Every new action begins with `status` at `SCREENING`,
        `effect_determination` at `PENDING`, `total_overlap_acres` at 0.00,
        `overlap_pct` at 0.00, `active_consultation_id` null, and `reinitiation_reason`
        at `NONE`."

        A consultation row is only ever created by the NLAA or LAA branch of the effect
        determination, so a freshly registered action's consultation list is empty.

        Design: Corner/entities/project_action_creation_seeds_screening_and_pending_determination
        """
        set_clock(CANONICAL_CLOCK)
        proponent = register_proponent()
        headers = make_proponent_headers(proponent["id"])

        action = get_success_data(
            api.create_project_action(project_action_payload(proponent["id"]), headers),
            201,
        )

        assert action["status"] == "SCREENING"
        assert action["effect_determination"] == "PENDING"
        assert action["effect_determination"] != "NO_EFFECT"
        assert action["total_overlap_acres"] == 0.00
        assert action["overlap_pct"] == 0.00
        assert action["active_consultation_id"] is None
        assert action["reinitiation_reason"] == "NONE"
        assert action["proponent_id"] == proponent["id"]
        assert action["footprint_acres"] == 200.00
        assert action["county_code"] == "06037"
        assert_project_action(action)
        rows = assert_unpaginated_list(
            api.list_action_consultations(action["id"], headers)
        )
        assert rows == []

    def test_an_inverted_construction_schedule_is_rejected(self, api):
        """The cross-field date check lives at rung 7, not lower.

        PRD: "Two cross-field checks also live at rung 7 rather than lower:
        `construction_start_date` must not be later than `construction_end_date` on
        project-action registration"

        Design: Corner/entities/project_action_creation_seeds_screening_and_pending_determination
        """
        set_clock(CANONICAL_CLOCK)
        proponent = register_proponent()
        headers = make_proponent_headers(proponent["id"])

        response = api.create_project_action(
            project_action_payload(
                proponent["id"],
                construction_start_date="2027-12-31",
                construction_end_date="2027-01-01",
            ),
            headers,
        )

        assert_error_envelope(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
