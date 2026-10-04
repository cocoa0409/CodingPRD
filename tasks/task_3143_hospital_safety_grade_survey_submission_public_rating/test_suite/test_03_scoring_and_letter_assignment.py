"""Scoring pipeline: domain rollup, standardization, composite and letters."""

import pytest

from test_helpers import (
    STANDARDIZATION_MIDPOINT,
    STANDARDIZATION_SPAN,
    TEST_USERS,
    api_client,
    create_methodology_version_payload,
    create_survey_payload,
    current_hospital_version,
    cut_score_run,
    domain_score_of,
    make_respondent_headers,
    measure_definition,
    publish_methodology,
    reference_methodology_hospital,
    validate_success,
)

ADMIN = TEST_USERS["rating_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ENGINE = TEST_USERS["engine_headers"]
READER = TEST_USERS["reader_headers"]


class TestDomainRollup:

    def test_infection_prevention_reads_the_measure_first_rounding(self):
        """PRD §2.6: "Reported measures are converted and each converted value
        is rounded half up to one decimal place before it joins a domain;
        domain scores are the mean of their bucket and are rounded half up to
        two decimal places".
        PRD §3.5: "The rounding order is pinned and not negotiable: one rounding
        per measure to a single decimal place before the value enters its
        bucket, and one rounding per domain to two decimal places after the
        bucket mean is taken."

        Design: Difficulty/dual_variant_calc/domain_rollup_measure_first_rounding_pair
        """
        ctx = reference_methodology_hospital()
        preview = validate_success(api_client.get_composite_preview(
            ctx.hospital["id"], READER, {"methodology_version_id": ctx.methodology_version_id}))
        assert domain_score_of(preview["domain_scores"], "INFECTION_PREVENTION") == pytest.approx(
            83.13, abs=0.005), "the pinned per-measure rounding yields 83.13"
        assert domain_score_of(preview["domain_scores"], "INFECTION_PREVENTION") != pytest.approx(
            83.15, abs=0.005), "rounding only at the domain level would yield 83.15"

    def test_pinned_domain_array_and_composite_for_the_reference_fixture(self):
        """PRD §3.5: "Every other converted value is rounded half up to one
        decimal place and appended to the bucket named by that measure's
        `domain`."
        PRD §3.5: "The composite is the sum of the terms of the retained domains
        divided by the sum of the effective weights of the retained domains,
        rounded half up to two decimal places exactly once, at the very end."

        Design: Difficulty/dual_variant_calc/domain_rollup_measure_first_rounding_pair
        """
        ctx = reference_methodology_hospital()
        preview = validate_success(api_client.get_composite_preview(
            ctx.hospital["id"], READER, {"methodology_version_id": ctx.methodology_version_id}))
        assert domain_score_of(preview["domain_scores"], "PATIENT_SAFETY") == pytest.approx(100.00)
        assert domain_score_of(preview["domain_scores"], "INFECTION_PREVENTION") == pytest.approx(83.13)
        assert domain_score_of(preview["domain_scores"], "CPOE") == pytest.approx(95.00)
        assert domain_score_of(preview["domain_scores"], "STAFFING") == pytest.approx(37.40)
        assert domain_score_of(preview["domain_scores"], "SURGICAL_VOLUME") == pytest.approx(0.00)
        assert preview["composite_score"] == pytest.approx(71.62, abs=0.005)

    def test_domain_rollup_keeps_the_nested_mean_of_rounded_measures(self):
        """PRD §2.6: "No quantity in this system is rounded at a stage other
        than the one its rule names."
        PRD §3.5: "A measure that was neither submitted nor sourced from a
        public programme is an excluded measure and is skipped entirely"

        Design: Difficulty/combinatorial_formula/domain_rollup_nested_mean_of_rounded_measures
        """
        ctx = reference_methodology_hospital()
        preview = validate_success(api_client.get_composite_preview(
            ctx.hospital["id"], READER, {"methodology_version_id": ctx.methodology_version_id}))
        infection = domain_score_of(preview["domain_scores"], "INFECTION_PREVENTION")
        assert infection == pytest.approx(83.13), (
            f"the INFECTION_PREVENTION bucket mean of the rounded measures is 83.13, got {infection}")
        assert infection != pytest.approx(83.15)
        assert preview["composite_score"] != pytest.approx(71.65, abs=0.005), (
            "the un-nested reading would carry the divergence into the composite as 71.65")

    def test_rate_to_count_floor_precedes_the_scale_factor(self):
        """PRD §3.4: "Under `RATE_TO_COUNT_FLOOR` the derived value is the raw
        value floored to a whole number."
        PRD §3.5: "for each one computes a converted value by multiplying the
        measure's `derived_value` by that measure's `scale_factor`"

        Design: Difficulty/combinatorial_formula/domain_rollup_nested_mean_of_rounded_measures
        """
        ctx = reference_methodology_hospital()
        preview = validate_success(api_client.get_composite_preview(
            ctx.hospital["id"], READER, {"methodology_version_id": ctx.methodology_version_id}))
        assert domain_score_of(preview["domain_scores"], "PATIENT_SAFETY") == pytest.approx(100.00), (
            "1.0200 floors to 1 first, then the scale factor of 100 applies")


class TestCompositeStandardization:

    def test_cpoe_term_is_standardized_before_weight_and_multiplier(self):
        """PRD §3.5: "Each retained domain, taken in the pinned definition
        order, produces a standardized score equal to `50.00` plus `15.00`
        multiplied by the difference between the domain score and that domain's
        `peer_mean`, divided by that domain's `peer_sd`"

        Design: Difficulty/dual_variant_calc/cpoe_standardized_order_of_operations_pair
        """
        ctx = reference_methodology_hospital()
        preview = validate_success(api_client.get_composite_preview(
            ctx.hospital["id"], READER, {"methodology_version_id": ctx.methodology_version_id}))
        assert preview["composite_score"] == pytest.approx(71.62, abs=0.005), (
            "the pinned composite standardizes the CPOE term before the weight and multiplier")
        assert preview["composite_score"] != pytest.approx(69.42, abs=0.005), (
            "ignoring the per-definition multiplier would collapse every term's weight and yield 69.42")

    def test_score_run_reports_the_pinned_composite_letter_and_reliability(self):
        """PRD §3.5: "The base letter is `A` when the composite is at least
        `85.00`, `B` when it is at least `62.50`, `C` when it is at least
        `45.00`, `D` when it is at least `30.00`, and `F` otherwise."
        PRD §3.5: "A completed run stores its `domain_scores` in the pinned
        definition order"

        Design: Difficulty/dual_variant_calc/cpoe_standardized_order_of_operations_pair
        """
        from test_helpers import create_cycle, refresh_measures

        ctx = reference_methodology_hospital()
        cycle = create_cycle(ctx.methodology_version_id, label="Main Methodology Grades")
        run = cut_score_run(ctx.hospital["id"], ctx.methodology_version_id,
                            cycle["id"], ctx.hospital_version)
        assert run["composite_score"] == pytest.approx(71.62, abs=0.005)
        assert run["base_grade_letter"] == "B"
        assert run["letter_grade"] == "B", "71.62 sits in the 62.50-84.99 band with no cap in force"
        assert run["reliability_weight"] == pytest.approx(1.0000)

    @pytest.mark.parametrize(
        "peer_sd,lot,expected_composite,expected_letter",
        [
            (15.00, (62.50, 62.50), 62.50, "B"),
            (15.00, (62.40, 62.50), 62.45, "C"),
        ],
    )
    def test_letter_cut_off_is_inclusive_at_the_boundary(self, peer_sd, lot,
                                                        expected_composite, expected_letter):
        """PRD §3.5: "`B` when it is at least `62.50`"
        PRD §2.10: "Standardization places every domain score on a common scale
        centred at `50.00` with a span of `15.00` standard units"

        Design: Corner/calculations/grade_assignment_exact_cut_off_boundaries
        """
        from test_helpers import create_cycle, refresh_measures, register_hospital, open_survey, \
            pin_methodology, record_measure, submit_survey, verify_survey

        # PRD §3.5 refuses a run whose pinned version omits any of the five
        # domains. Only PATIENT_SAFETY carries a measure here; the other four
        # domains are declared but their measures are unreported, so they are
        # dropped from both the numerator and the denominator and the composite
        # is the standardized PATIENT_SAFETY term alone.
        # PRD §3.5 rounds each converted measure to one decimal place before it
        # enters its bucket, and PRD §3.5 then stores the bucket mean "rounded
        # half up to two decimal places". A two-measure PATIENT_SAFETY bucket
        # therefore lands on the cut-off's own decimal grid: (62.50, 62.50)
        # averages to 62.50 and (62.40, 62.50) to 62.45 — one grid step below.
        code_a, code_b = lot
        version = publish_methodology(
            [measure_definition("o1", "PATIENT_SAFETY", scale_factor=1.0, weight=0.50,
                                multiplier=1.00, peer_mean=50.00, peer_sd=peer_sd),
             measure_definition("o6", "PATIENT_SAFETY", scale_factor=1.0, weight=0.50,
                                multiplier=1.00, peer_mean=50.00, peer_sd=peer_sd),
             measure_definition("o2", "CPOE", scale_factor=1.0, weight=1.00,
                                multiplier=1.00, peer_mean=50.00, peer_sd=peer_sd),
             measure_definition("o3", "STAFFING", scale_factor=1.0, weight=1.00,
                                multiplier=1.00, peer_mean=50.00, peer_sd=peer_sd),
             measure_definition("o4", "INFECTION_PREVENTION", scale_factor=1.0, weight=1.00,
                                multiplier=1.00, peer_mean=50.00, peer_sd=peer_sd),
             measure_definition("o5", "SURGICAL_VOLUME", scale_factor=1.0, weight=1.00,
                                multiplier=1.00, peer_mean=50.00, peer_sd=peer_sd)],
            label="Cut-Off Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        record_measure(hospital["id"], survey["id"], "o1", code_a)
        record_measure(hospital["id"], survey["id"], "o6", code_b)
        submit_survey(hospital["id"], survey["id"])
        verify_survey(survey["id"], "ACCEPT")
        measure_set = refresh_measures(hospital["id"], current_hospital_version(hospital["id"]))
        cycle = create_cycle(version["id"], label="Cut-Off Grades",
                             publication_date="2026-09-15T00:00:00Z")
        run = cut_score_run(hospital["id"], version["id"], cycle["id"])

        assert run["composite_score"] == pytest.approx(expected_composite)
        assert run["letter_grade"] == expected_letter
        assert run["base_grade_letter"] == expected_letter
        assert run["reliability_weight"] == pytest.approx(1.0000)


class TestDomainRetention:

    def test_domain_with_no_available_measure_is_dropped_not_scored_as_zero(self):
        """PRD §3.5: "A domain is retained only when at least one of its
        measures has a status of `REPORTED` or `PUBLIC_SOURCE_SUBSTITUTED`; a
        domain whose measures are all excluded is dropped, and a dropped domain
        contributes neither a numerator term nor a denominator weight."

        Design: Corner/calculations/domain_readiness_filtering_excludes_unscored_domains
        """
        from test_helpers import create_cycle, refresh_measures, register_hospital, open_survey, \
            pin_methodology, record_measure, submit_survey, verify_survey

        # PRD §3.5 refuses a run whose pinned version omits any of the five
        # domains, so all five are declared and only PATIENT_SAFETY reports.
        version = publish_methodology(
            [
                measure_definition("o1", "PATIENT_SAFETY", scale_factor=1.0, weight=0.60,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
                measure_definition("o2", "CPOE", scale_factor=1.0, weight=0.40,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
                measure_definition("o3", "STAFFING", scale_factor=1.0, weight=0.40,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
                measure_definition("o4", "INFECTION_PREVENTION", scale_factor=1.0, weight=0.40,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
                measure_definition("o5", "SURGICAL_VOLUME", scale_factor=1.0, weight=0.40,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
            ],
            label="One-Reported-Domain Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        record_measure(hospital["id"], survey["id"], "o1", 65.0)
        submit_survey(hospital["id"], survey["id"])
        verify_survey(survey["id"], "ACCEPT")
        measure_set = refresh_measures(hospital["id"], current_hospital_version(hospital["id"]))
        cycle = create_cycle(version["id"], label="One-Reported-Domain Grades",
                             publication_date="2026-09-15T00:00:00Z")
        run = cut_score_run(hospital["id"], version["id"], cycle["id"])

        assert measure_set["readiness_state"] == "READY"
        assert run["composite_score"] == pytest.approx(65.00), (
            "the dropped CPOE weight leaves 0.60 standing alone as the effective weight sum")
        names = [entry["domain"] for entry in run["domain_scores"]]
        assert "PATIENT_SAFETY" in names
        assert "CPOE" not in names


class TestDerivedValues:

    def test_per_hundred_beds_floor_is_observable_through_the_preview(self):
        """PRD §3.4: "Under `PER_100_BEDS_FLOOR` the derived value is the raw
        value divided by `100`, floored to a whole number."
        PRD §2.6: "Values that a derivation rule floors — the count-floored and
        per-hundred-bed measures — are integers after flooring and are not
        carried at a fractional precision."

        Design: Corner/endpoints/composite_preview_exposes_the_submitted_raw_composite
        """
        from test_helpers import create_survey_payload as _create_survey_payload
        from test_helpers import (create_survey_measure_payload, open_survey, pin_methodology,
                                  record_measure, register_hospital, submit_survey, verify_survey,
                                  refresh_measures)

        # PRD §3.5 refuses a run whose pinned version omits any of the five
        # domains; only PATIENT_SAFETY reports, so the other four are dropped.
        version = publish_methodology(
            [measure_definition("o1", "PATIENT_SAFETY", scale_factor=1.0, weight=1.00,
                                multiplier=1.00, peer_mean=50.00, peer_sd=15.00,
                                derivation_rule="PER_100_BEDS_FLOOR"),
             measure_definition("o2", "CPOE", scale_factor=1.0, weight=1.00,
                                multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
             measure_definition("o3", "STAFFING", scale_factor=1.0, weight=1.00,
                                multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
             measure_definition("o4", "INFECTION_PREVENTION", scale_factor=1.0, weight=1.00,
                                multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
             measure_definition("o5", "SURGICAL_VOLUME", scale_factor=1.0, weight=1.00,
                                multiplier=1.00, peer_mean=50.00, peer_sd=15.00)],
            label="Beds-Derivation Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        measure = record_measure(hospital["id"], survey["id"], "o1", 6050.0)
        submit_survey(hospital["id"], survey["id"])
        verify_survey(survey["id"], "ACCEPT")
        refresh_measures(hospital["id"], current_hospital_version(hospital["id"]))

        assert measure["derived_value"] == pytest.approx(60.0)
        preview = validate_success(api_client.get_composite_preview(
            hospital["id"], READER, {"methodology_version_id": version["id"]}))
        assert preview["composite_score"] == pytest.approx(60.00)
        # PRD §3.5 defines `submitted_raw_composite_score` as the composite "that
        # would result from using the hospital's submitted values without source
        # substitution". With nothing substituted the two coincide.
        assert preview["submitted_raw_composite_score"] == pytest.approx(60.00)
        assert preview["base_grade_letter"] == "C"
        assert preview["letter_grade"] == "C"
        assert preview["reliability_weight"] == pytest.approx(1.0000)