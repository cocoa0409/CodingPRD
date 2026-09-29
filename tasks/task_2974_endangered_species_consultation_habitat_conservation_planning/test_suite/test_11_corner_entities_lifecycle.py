"""Lifecycle-side entity claims: determinations, opinions, banks, plans, permits.

Body foreign-key resolution, the per-entity 404 codes, the system-created
consultation row, opinion immutability, and the seeded ledgers of a bank, a plan,
a commitment, a permit and a monitoring report.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bank_ledger_identity,
    assert_biological_opinion,
    assert_conservation_bank,
    assert_error_envelope,
    assert_habitat_conservation_plan,
    assert_incidental_take_permit,
    assert_mitigation_commitment,
    assert_monitoring_report,
    assert_presence_determination,
    assert_same_instant,
    assert_take_ledger_identity,
    assert_unpaginated_list,
)
from test_helpers.factories import (
    ACTION_COUNTY_CODE,
    adjudication_payload,
    circumstance_response_payload,
    conservation_bank_payload,
    field_survey_payload,
    habitat_conservation_plan_payload,
    incidental_take_permit_payload,
    project_action_payload,
    species_payload,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    AUDITOR,
    CANONICAL_CLOCK,
    ISSUER,
    REGISTRAR,
    build_scenario,
    designate_critical_habitat_unit,
    read_action,
    read_bank,
    read_plan,
    register_proponent,
    register_species,
    set_clock,
)
from test_helpers.test_users import make_proponent_headers

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


class TestBodyForeignKeyResolution:
    """Rung 6 resolves body ids in one declared order, each with its own code."""

    def test_body_foreign_keys_report_their_own_error_ids(self, api):
        """A ghost proponent, species and habitat unit each get a distinct 404.

        PRD: "Foreign keys supplied in a request **body** are resolved after path
        resolution and after the proponent ownership check, and they are resolved in a
        fixed declared order: `proponent_id` first, then `species_id`, then
        `critical_habitat_unit_id`, then `conservation_bank_id`."

        PRD: "If that body `proponent_id` resolves to no row at all, the ownership
        check does not fire and the request instead falls through to referential
        resolution and is reported as `ERR_PROPONENT_NOT_FOUND`."

        PRD: "A unit that exists but is designated for a different species is reported
        as `ERR_CRITICAL_HABITAT_UNIT_NOT_FOUND` - from the perspective of that
        species, the unit does not exist."

        Design: Corner/entities/body_foreign_keys_are_resolved_flat_with_per_target_error_ids
        """
        scenario = build_scenario("action")
        headers = scenario["proponent_headers"]
        action_id = scenario["action"]["id"]
        foreign_unit = designate_critical_habitat_unit(
            scenario["threatened_species"]["id"],
            unit_code="CHU-T1",
            designation_status="PROPOSED",
        )

        ghost_proponent = api.create_project_action(
            project_action_payload(MISSING_UUID, action_name="Ghost Action"), headers
        )
        assert_error_envelope(ghost_proponent, ApiErrorId.ERR_PROPONENT_NOT_FOUND, 404)

        ghost_species = api.create_presence_determination(
            action_id, field_survey_payload(MISSING_UUID), headers
        )
        assert_error_envelope(ghost_species, ApiErrorId.ERR_SPECIES_NOT_FOUND, 404)

        ghost_unit = api.create_presence_determination(
            action_id,
            field_survey_payload(
                scenario["species"]["id"], critical_habitat_unit_id=MISSING_UUID
            ),
            headers,
        )
        assert_error_envelope(
            ghost_unit, ApiErrorId.ERR_CRITICAL_HABITAT_UNIT_NOT_FOUND, 404
        )

        cross_species = api.create_presence_determination(
            action_id,
            field_survey_payload(
                scenario["species"]["id"], critical_habitat_unit_id=foreign_unit["id"]
            ),
            headers,
        )
        assert_error_envelope(
            cross_species, ApiErrorId.ERR_CRITICAL_HABITAT_UNIT_NOT_FOUND, 404
        )

        accepted = api.create_presence_determination(
            action_id,
            field_survey_payload(
                scenario["species"]["id"],
                critical_habitat_unit_id=scenario["unit"]["id"],
            ),
            headers,
        )
        determination = get_success_data(accepted, 201)
        assert determination["critical_habitat_unit_id"] == scenario["unit"]["id"]

    def test_missing_resource_ids_return_their_own_404_error_ids(self, api):
        """Ten reachable entities, ten distinct existence codes.

        PRD: "The eleven existence codes are `ERR_SPECIES_NOT_FOUND`,
        `ERR_PROPONENT_NOT_FOUND`, `ERR_PROJECT_ACTION_NOT_FOUND`,
        `ERR_CRITICAL_HABITAT_UNIT_NOT_FOUND`,
        `ERR_PRESENCE_DETERMINATION_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
        `ERR_HCP_NOT_FOUND`, `ERR_CONSERVATION_BANK_NOT_FOUND`,
        `ERR_PERMIT_NOT_FOUND`, `ERR_MONITORING_REPORT_NOT_FOUND`, and
        `ERR_CIRCUMSTANCE_EVENT_NOT_FOUND`, each carrying HTTP 404."

        PRD: "A request naming a species that does not exist, then a habitat unit
        under it, reports the species failure and never reaches the unit."

        Design: Corner/entities/missing_resource_ids_return_their_own_404_error_ids
        """
        set_clock(CANONICAL_CLOCK)

        probes = (
            (api.get_species(MISSING_UUID, AUDITOR), ApiErrorId.ERR_SPECIES_NOT_FOUND),
            (
                api.get_proponent(MISSING_UUID, AUDITOR),
                ApiErrorId.ERR_PROPONENT_NOT_FOUND,
            ),
            (
                api.get_project_action(MISSING_UUID, AUDITOR),
                ApiErrorId.ERR_PROJECT_ACTION_NOT_FOUND,
            ),
            (
                api.get_presence_determination(MISSING_UUID, AUDITOR),
                ApiErrorId.ERR_PRESENCE_DETERMINATION_NOT_FOUND,
            ),
            (
                api.get_consultation(MISSING_UUID, AUDITOR),
                ApiErrorId.ERR_CONSULTATION_NOT_FOUND,
            ),
            (
                api.get_habitat_conservation_plan(MISSING_UUID, AUDITOR),
                ApiErrorId.ERR_HCP_NOT_FOUND,
            ),
            (
                api.get_conservation_bank(MISSING_UUID, AUDITOR),
                ApiErrorId.ERR_CONSERVATION_BANK_NOT_FOUND,
            ),
            (
                api.get_incidental_take_permit(MISSING_UUID, AUDITOR),
                ApiErrorId.ERR_PERMIT_NOT_FOUND,
            ),
            (
                api.adjudicate_monitoring_report(
                    MISSING_UUID, adjudication_payload(), ADJUDICATOR
                ),
                ApiErrorId.ERR_MONITORING_REPORT_NOT_FOUND,
            ),
        )
        for response, expected in probes:
            assert_error_envelope(response, expected, 404)

        proponent = register_proponent()
        event = api.respond_to_circumstance_event(
            MISSING_UUID,
            circumstance_response_payload(1000),
            make_proponent_headers(proponent["id"]),
        )
        assert_error_envelope(event, ApiErrorId.ERR_CIRCUMSTANCE_EVENT_NOT_FOUND, 404)

        listing = api.list_critical_habitat_units(MISSING_UUID, AUDITOR)
        assert_error_envelope(listing, ApiErrorId.ERR_SPECIES_NOT_FOUND, 404)
        plans = api.list_action_habitat_conservation_plans(MISSING_UUID, AUDITOR)
        assert_error_envelope(plans, ApiErrorId.ERR_PROJECT_ACTION_NOT_FOUND, 404)


class TestPresenceDeterminationDerivation:
    """Two rows created back to back diverge on both computed fields."""

    def test_presence_determination_computes_status_and_seasonality(self, api):
        """A field survey is confirmed and in season; a desk query is neither.

        PRD: "A `DATABASE_QUERY` can never produce a confirmed status: `DETECTED`
        yields `PRESUMED_PRESENT`, `NOT_DETECTED` yields `PRESUMED_ABSENT`, and
        `INCONCLUSIVE` yields `PRESUMED_PRESENT`. A `FIELD_SURVEY` can: `DETECTED`
        yields `PRESENT`"

        PRD: "`survey_in_season` is computed from the calendar month of
        `survey_window_start` and the calendar month of `survey_window_end`, tested
        against the species' detectability season, and it is true only when **both**
        months fall inside that season."

        PRD: "For a `DATABASE_QUERY` determination, `survey_in_season` is always
        false."

        PRD: "`requires_reevaluation` is set to false on creation and is only ever
        raised afterwards by the uplisting cascade of §3.1."

        Design: Corner/entities/presence_determination_computes_status_and_seasonality
        """
        scenario = build_scenario("determinations")
        headers = scenario["proponent_headers"]

        field_row = get_success_data(
            api.get_presence_determination(
                scenario["field_determination"]["id"], headers
            ),
            200,
        )
        query_row = get_success_data(
            api.get_presence_determination(
                scenario["query_determination"]["id"], headers
            ),
            200,
        )

        assert field_row["presence_status"] == "PRESENT"
        assert field_row["survey_in_season"] is True
        assert field_row["critical_habitat_unit_id"] == scenario["unit"]["id"]
        assert query_row["presence_status"] == "PRESUMED_PRESENT"
        assert query_row["survey_in_season"] is False
        assert query_row["critical_habitat_unit_id"] is None
        assert field_row["requires_reevaluation"] is False
        assert query_row["requires_reevaluation"] is False
        assert_presence_determination(field_row)
        assert_presence_determination(query_row)


class TestConsultationCreation:
    """The consultation row has no POST route of its own."""

    def test_consultation_is_created_only_by_the_effect_determination(self, api):
        """The LAA fork seeds one fully derived FORMAL consultation.

        PRD: "On `LAA`, the action moves `SCREENING - FORMAL_CONSULTATION`, the same
        three fields are written, and exactly one consultation is created with
        `consultation_type` `FORMAL`, `status` `DRAFT_BA`, `clock_started_at` at the
        current logical clock, `statutory_days` of 135, and `tolled_days` of 0;
        `active_consultation_id` is set to that new consultation."

        PRD: "`deadline_at` is `clock_started_at` advanced by a number of days equal to
        `statutory_days` plus `tolled_days`"

        Design: Corner/entities/consultation_is_created_only_by_the_effect_determination
        """
        scenario = build_scenario("effect_determination")
        action = scenario["action"]

        rows = assert_unpaginated_list(
            api.list_action_consultations(action["id"], AUDITOR)
        )

        assert len(rows) == 1
        consultation = rows[0]
        assert consultation["consultation_type"] == "FORMAL"
        assert consultation["status"] == "DRAFT_BA"
        assert consultation["statutory_days"] == 135
        assert consultation["tolled_days"] == 0
        assert consultation["info_request_count"] == 0
        assert consultation["ba_revision_number"] == 0
        assert consultation["reinitiation_count"] == 0
        assert_same_instant(consultation["clock_started_at"], CANONICAL_CLOCK)
        assert_same_instant(consultation["deadline_at"], "2027-02-13T00:00:00Z")
        assert consultation["project_action_id"] == action["id"]
        assert action["active_consultation_id"] == consultation["id"]


class TestBiologicalOpinionImmutability:
    """The one entity with no version and no updated_at."""

    def test_biological_opinion_is_immutable_and_has_no_common_fields(self, api):
        """A second issuance is refused and the stored snapshot is untouched.

        PRD: "A `BiologicalOpinion` is immutable once issued: it carries `id` and
        `created_at` and nothing else from the common set. It has **no** `updated_at`
        field and **no** `version` field, and neither appears in its representation."

        PRD: "The consultation moves `UNDER_REVIEW - OPINION_ISSUED` and the action
        moves `FORMAL_CONSULTATION - CONSULTATION_CONCLUDED`."

        Design: Corner/entities/biological_opinion_is_immutable_and_has_no_common_fields
        """
        scenario = build_scenario("opinion")
        consultation_id = scenario["consultation"]["id"]

        response = api.issue_biological_opinion(consultation_id, {}, ISSUER)

        assert_error_envelope(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        rows = assert_unpaginated_list(
            api.list_biological_opinions(consultation_id, AUDITOR)
        )
        assert len(rows) == 1
        opinion = rows[0]
        assert "version" not in opinion
        assert "updated_at" not in opinion
        assert opinion["authorized_take_units"] == 4.00
        assert opinion["jeopardy_fraction"] == 0.0010
        assert opinion["conclusion"] == "NO_JEOPARDY"
        assert opinion["issued_by_user_id"] == "fws-user-issuer"
        assert_biological_opinion(opinion)
        consultation = get_success_data(
            api.get_consultation(consultation_id, AUDITOR), 200
        )
        assert consultation["status"] == "OPINION_ISSUED"
        assert consultation["reinitiation_count"] == 0


class TestConservationBankSeeding:
    """A new bank opens with the whole balance available."""

    def test_conservation_bank_creation_seeds_the_credit_ledger_identity(self, api):
        """credits_available is initialised from credits_total_minted, not to zero.

        PRD: "On establishment `credits_available` is set equal to
        `credits_total_minted`, while `credits_reserved` and `credits_transferred` both
        start at 0.00, which establishes the ledger identity of §2.10."

        PRD: "A bank may only be established for a species whose `listing_status` is
        `ENDANGERED` or `THREATENED`; `PROPOSED` and `CANDIDATE` species carry no take
        liability and therefore no sellable credits, so naming one is
        `ERR_SPECIES_NOT_LISTED` (HTTP 422)."

        PRD: "a `service_area_county_codes` array of between 1 and 12 five-digit county
        codes describing the approved service area"

        Design: Corner/entities/conservation_bank_creation_seeds_the_credit_ledger_identity
        """
        set_clock(CANONICAL_CLOCK)
        listed = register_species()
        candidate = get_success_data(
            api.create_species(
                species_payload(
                    scientific_name="Athene cunicularia hypugaea",
                    common_name="Western burrowing owl",
                    listing_status="CANDIDATE",
                ),
                REGISTRAR,
            ),
            201,
        )

        bank = get_success_data(
            api.create_conservation_bank(
                conservation_bank_payload(listed["id"]), REGISTRAR
            ),
            201,
        )

        assert bank["credits_available"] == 500.00
        assert bank["credits_reserved"] == 0.00
        assert bank["credits_transferred"] == 0.00
        assert bank["credits_total_minted"] == 500.00
        assert bank["credit_price_cents"] == 250_000
        assert bank["service_area_county_codes"] == [ACTION_COUNTY_CODE]
        assert_bank_ledger_identity(bank)
        assert_conservation_bank(bank)

        listed_banks = assert_unpaginated_list(
            api.list_species_conservation_banks(listed["id"], AUDITOR)
        )
        assert len(listed_banks) == 1
        candidate_banks = assert_unpaginated_list(
            api.list_species_conservation_banks(candidate["id"], AUDITOR)
        )
        assert candidate_banks == []

        unlisted = api.create_conservation_bank(
            conservation_bank_payload(candidate["id"]), REGISTRAR
        )
        assert_error_envelope(unlisted, ApiErrorId.ERR_SPECIES_NOT_LISTED, 422)

        short_code = api.create_conservation_bank(
            conservation_bank_payload(listed["id"], service_area_county_codes=["6037"]),
            REGISTRAR,
        )
        assert_error_envelope(short_code, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestPlanCreationLedger:
    """Plan creation writes one computed figure and zeroes every ledger field."""

    def test_habitat_conservation_plan_creation_zeroes_the_endowment_ledger(self, api):
        """Two dimensions at their own initial state, one non-zero computed value.

        PRD: "On success the action moves `CONSULTATION_CONCLUDED - HCP_DEVELOPMENT`
        and the plan is created with `plan_status` `DRAFT` and `funding_status`
        `UNFUNDED`."

        PRD: "with `endowment_base_cents`, `changed_circumstance_reserve_cents`,
        `endowment_required_cents`, `endowment_secured_cents`, `reserve_drawn_cents`,
        and `reserve_remaining_cents` all at 0; with `funded_ratio` at 0.0000; with
        `approved_by_user_id` null; and with `assurance_review_required` false. Its
        `preliminary_mitigation_units` is computed immediately."

        PRD: "it takes the single **largest** listing ratio anywhere in the candidate
        set and multiplies the plan's whole `covered_acres` by it"

        Design: Corner/entities/habitat_conservation_plan_creation_zeroes_the_endowment_ledger
        """
        scenario = build_scenario("opinion")

        plan = get_success_data(
            api.create_habitat_conservation_plan(
                scenario["action"]["id"],
                habitat_conservation_plan_payload(),
                scenario["proponent_headers"],
            ),
            201,
        )

        assert plan["plan_status"] == "DRAFT"
        assert plan["funding_status"] == "UNFUNDED"
        assert plan["preliminary_mitigation_units"] == 60.00
        assert plan["secured_mitigation_units"] == 0.00
        assert plan["endowment_base_cents"] == 0
        assert plan["changed_circumstance_reserve_cents"] == 0
        assert plan["endowment_required_cents"] == 0
        assert plan["endowment_secured_cents"] == 0
        assert plan["funded_ratio"] == 0.0000
        assert plan["reserve_drawn_cents"] == 0
        assert plan["reserve_remaining_cents"] == 0
        assert plan["approved_by_user_id"] is None
        assert plan["assurance_review_required"] is False
        assert_habitat_conservation_plan(plan)
        assert read_action(scenario["action"]["id"])["status"] == "HCP_DEVELOPMENT"


class TestCommitmentCostFields:
    """All four cost fields are populated for every mechanism."""

    def test_mitigation_commitment_populates_all_four_cost_fields(self, api):
        """A bank commitment carries a 0.000 tier rather than a null one.

        PRD: "Step one produces `base_fee_cents`, and it is populated for **every**
        mechanism, not only for bank credits. A `CONSERVATION_BANK_CREDIT` commitment
        multiplies its `units` by the cited bank's `credit_price_cents`."

        PRD: "For every other mechanism, `admin_fee_pct_applied` is 0.000 - a
        bank-credit commitment whose `base_fee_cents` happens to land inside an
        in-lieu-fee band still carries 0.000. The field is stored with exactly three
        decimal places."

        PRD: "For a `CONSERVATION_BANK_CREDIT` commitment, the bank's
        `credits_available` decreases by `units` and its `credits_reserved` increases by
        the same `units`, which moves credits across the ledger without changing the
        total."

        45.01 credits at 250,000 cents price at 11,252,500 with no administrative fee,
        and the row stores its own endowment contribution of 3,382,502 cents.

        Design: Corner/entities/mitigation_commitment_populates_all_four_cost_fields
        """
        scenario = build_scenario("plan")
        plan = scenario["plan"]

        commitment = get_success_data(
            api.create_mitigation_commitment(
                plan["id"],
                {
                    "mechanism": "CONSERVATION_BANK_CREDIT",
                    "units": 45.01,
                    "expected_hcp_version": plan["version"],
                    "conservation_bank_id": scenario["bank"]["id"],
                },
                scenario["proponent_headers"],
            ),
            201,
        )

        assert commitment["base_fee_cents"] == 11_252_500
        assert commitment["total_cost_cents"] == 11_252_500
        assert commitment["admin_fee_pct_applied"] == 0.000
        assert commitment["admin_fee_cents"] == 0
        assert commitment["endowment_contribution_cents"] == 3_382_502
        assert commitment["status"] == "RESERVED"
        assert commitment["mechanism"] == "CONSERVATION_BANK_CREDIT"
        assert commitment["units"] == 45.01
        assert commitment["conservation_bank_id"] == scenario["bank"]["id"]
        assert_mitigation_commitment(commitment)
        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_reserved"] == 45.01
        assert bank["credits_available"] == 454.99
        assert bank["credits_transferred"] == 0.00
        assert_bank_ledger_identity(bank)

    def test_an_in_lieu_fee_commitment_prices_its_own_administrative_tier(self, api):
        """The second commitment on the refreshed version pays tier one.

        PRD: "An `IN_LIEU_FEE` commitment multiplies its `units` by the standard
        in-lieu base rate of 182,500 cents per unit - one thousand eight hundred
        twenty-five dollars per unit."

        PRD: "For an in-lieu-fee commitment, `admin_fee_pct_applied` is 0.150 when
        `base_fee_cents` is below 5,000,000 cents (fifty thousand dollars)"

        PRD: "Step four sets `total_cost_cents` to `base_fee_cents` plus
        `admin_fee_cents`, and the tier is not revisited."

        14.71 units price at 2,684,575, the 0.150 tier adds 402,686 (402,686.25 rounded
        half up), and the total is 3,087,261.

        Design: Corner/entities/mitigation_commitment_populates_all_four_cost_fields
        """
        scenario = build_scenario("plan")
        plan = scenario["plan"]
        get_success_data(
            api.create_mitigation_commitment(
                plan["id"],
                {
                    "mechanism": "CONSERVATION_BANK_CREDIT",
                    "units": 45.01,
                    "expected_hcp_version": plan["version"],
                    "conservation_bank_id": scenario["bank"]["id"],
                },
                scenario["proponent_headers"],
            ),
            201,
        )
        refreshed = read_plan(plan["id"], scenario["proponent_headers"])

        commitment = get_success_data(
            api.create_mitigation_commitment(
                plan["id"],
                {
                    "mechanism": "IN_LIEU_FEE",
                    "units": 14.71,
                    "expected_hcp_version": refreshed["version"],
                },
                scenario["proponent_headers"],
            ),
            201,
        )

        assert commitment["base_fee_cents"] == 2_684_575
        assert commitment["admin_fee_pct_applied"] == 0.150
        assert commitment["admin_fee_cents"] == 402_686
        assert commitment["total_cost_cents"] == 3_087_261
        assert commitment.get("conservation_bank_id") is None
        assert_mitigation_commitment(commitment)


class TestPermitAndReportSeeding:
    """The permit inherits its ledger; the report starts unadjudicated."""

    def test_incidental_take_permit_number_and_take_ledger_are_seeded(self, api):
        """ITP-000001, a thirty-year term, and a ledger copied from the opinion.

        PRD: "`permit_number` is the literal prefix `ITP-` followed by a six-digit
        zero-padded ordinal equal to one more than the number of incidental take permits
        created before this one, counting the whole global permit table ordered by
        `created_at` ascending - never by `id`. The first permit issued in a fresh
        database is therefore `ITP-000001`."

        PRD: "`term_end` is `term_start` with its year advanced by the plan's
        `permit_term_years`, keeping the same month and day"

        PRD: "`take_consumed_units` starts at 0.00, `take_remaining_units` starts equal
        to `authorized_take_units`, and `suspension_count` starts at 0. The permit is
        created in `status` `ACTIVE`, the plan moves `APPROVED - IMPLEMENTING`, and the
        action moves `HCP_DEVELOPMENT - PERMITTED`."

        Design: Corner/entities/incidental_take_permit_number_and_take_ledger_are_seeded
        """
        scenario = build_scenario("approved")

        permit = get_success_data(
            api.issue_incidental_take_permit(
                scenario["plan"]["id"], incidental_take_permit_payload(), ISSUER
            ),
            201,
        )

        assert permit["permit_number"] == "ITP-000001"
        assert permit["status"] == "ACTIVE"
        assert permit["term_start"] == "2026-10-01"
        assert permit["term_end"] == "2056-10-01"
        assert permit["authorized_take_units"] == 4.00
        assert permit["take_unit"] == "INDIVIDUALS"
        assert permit["reinitiation_trigger_units"] == 3.60
        assert permit["take_consumed_units"] == 0.00
        assert permit["take_remaining_units"] == 4.00
        assert permit["suspension_count"] == 0
        assert permit["issued_by_user_id"] == "fws-user-issuer"
        assert permit["hcp_id"] == scenario["plan"]["id"]
        assert_incidental_take_permit(permit)
        assert_take_ledger_identity(permit)
        rows = assert_unpaginated_list(
            api.list_plan_incidental_take_permits(scenario["plan"]["id"], AUDITOR)
        )
        assert len(rows) == 1

    def test_monitoring_report_starts_submitted_with_null_adjudication(self, api):
        """The take is applied at submission even though nothing is adjudicated yet.

        PRD: "The report is created in `status` `SUBMITTED` and the permit's `version`
        increases by 1."

        PRD: "`due_at` is `period_end` advanced by 45 calendar days, and it is a
        date-only value. `is_late` is true when the UTC calendar date of `submitted_at`
        is **strictly later** than `due_at`, so a report filed on the due date itself is
        on time."

        PRD: "The reported take is applied at **submission**, before any adjudication,
        and the ledger is maintained incrementally rather than recomputed from scratch."

        A period closing 2027-04-01 is due 2027-05-16, so a report filed at the
        2027-04-15 clock is on time, and the permit's ledger already shows 1.00
        consumed against a 3.60 trigger it does not reach.

        Design: Corner/entities/monitoring_report_starts_submitted_with_null_adjudication
        """
        scenario = build_scenario("permit")
        permit = scenario["permit"]
        set_clock("2027-04-15T00:00:00Z")

        report = get_success_data(
            api.create_monitoring_report(
                permit["id"],
                {
                    "period_start": "2027-01-01",
                    "period_end": "2027-04-01",
                    "take_units_reported": 1.00,
                    "mitigation_units_verified": 59.72,
                    "expected_permit_version": permit["version"],
                },
                scenario["proponent_headers"],
            ),
            201,
        )

        assert report["status"] == "SUBMITTED"
        assert report["adjudicated_at"] is None
        assert report["adjudicated_by_user_id"] is None
        assert report["adjudication_note"] is None
        assert_same_instant(report["submitted_at"], "2027-04-15T00:00:00Z")
        assert report["due_at"] == "2027-05-16"
        assert report["is_late"] is False
        assert report["take_units_reported"] == 1.00
        assert report["mitigation_units_verified"] == 59.72
        assert_monitoring_report(report)
        reread = get_success_data(
            api.get_incidental_take_permit(permit["id"], AUDITOR), 200
        )
        assert reread["take_consumed_units"] == 1.00
        assert reread["take_remaining_units"] == 3.00
        assert reread["status"] == "ACTIVE"
        assert reread["suspension_count"] == 0
        assert_take_ledger_identity(reread)
