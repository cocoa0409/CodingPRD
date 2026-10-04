"""Collection listing, pagination and composite renormalization."""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_hospital_payload,
    create_cycle,
    current_hospital_version,
    cut_score_run,
    measure_definition,
    open_survey,
    pin_methodology,
    publish_methodology,
    record_measure,
    refresh_measures,
    register_hospital,
    submit_survey,
    validate_paginated,
    validate_success,
    verify_survey,
)

ADMIN = TEST_USERS["rating_admin_headers"]
READER = TEST_USERS["reader_headers"]


class TestHospitalListing:

    def test_listing_paginates_and_reports_the_whole_filtered_total(self):
        """PRD §2.3: "`limit` bounds the number of items returned and defaults
        to 10 when omitted; it must fall between a minimum of 1 and a maximum of
        100 inclusive."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope"

        Design: Corner/entities/hospitals_list_paginates_and_reports_total_count_and_has_more
        """
        register_hospital(name="C0 Community Hospital", ccn="261000", state_code="MO")
        register_hospital(name="C1 Community Hospital", ccn="261001", state_code="MO")
        register_hospital(name="C2 Community Hospital", ccn="261002", state_code="KS",
                          teaching_status="TEACHING")

        first_page, meta = validate_paginated(api_client.list_hospitals(
            READER, {"limit": 2, "offset": 0}))
        assert len(first_page) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        second_page, meta = validate_paginated(api_client.list_hospitals(
            READER, {"limit": 2, "offset": 2}))
        assert len(second_page) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        filtered, meta = validate_paginated(api_client.list_hospitals(
            READER, {"state_code": "KS"}))
        assert len(filtered) == 1
        assert filtered[0]["state_code"] == "KS"

        everything, meta = validate_paginated(api_client.list_hospitals(READER))
        assert len(everything) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestCompositeRenormalization:

    def test_a_run_with_no_dropped_domain_reports_the_provisional_composite(self):
        """PRD §3.5: "The renormalisation variant, `final_renormalized`, applies
        whenever a domain is dropped — because the readiness state is
        `OMITTED_FROM_CYCLE`, or because a granted reanalysis has made the
        official cycle final."
        PRD §3.5: "`D` when it is at least `30.00`, and `F` otherwise."

        Design: Corner/calculations/composite_renormalization_provisional_versus_final_variant
        """
        # PRD §3.5 refuses a run whose pinned version omits any of the five
        # domains, so the pinned version spans all five and the fixture reports
        # each of them, one measure per domain.
        version = publish_methodology(
            [
                measure_definition("o1", "PATIENT_SAFETY", scale_factor=1.0, weight=0.20,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
                measure_definition("o2", "CPOE", scale_factor=1.0, weight=0.20,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
                measure_definition("o3", "STAFFING", scale_factor=1.0, weight=0.20,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
                measure_definition("o4", "INFECTION_PREVENTION", scale_factor=1.0, weight=0.20,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
                measure_definition("o5", "SURGICAL_VOLUME", scale_factor=1.0, weight=0.20,
                                   multiplier=1.00, peer_mean=50.00, peer_sd=15.00),
            ],
            label="Five-Domain Methodology")
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        for code, raw in [("o1", 50.0), ("o2", 20.0), ("o3", 35.0),
                          ("o4", 50.0), ("o5", 50.0)]:
            record_measure(hospital["id"], survey["id"], code, raw)
        submit_survey(hospital["id"], survey["id"])
        verify_survey(survey["id"], "ACCEPT")
        measure_set = refresh_measures(hospital["id"], current_hospital_version(hospital["id"]))
        cycle = create_cycle(version["id"], label="Five-Domain Grades",
                             publication_date="2026-09-15T00:00:00Z")
        run = cut_score_run(hospital["id"], version["id"], cycle["id"])

        names = [entry["domain"] for entry in run["domain_scores"]]
        assert names == ["PATIENT_SAFETY", "CPOE", "STAFFING",
                         "INFECTION_PREVENTION", "SURGICAL_VOLUME"], (
            "the run reports its domain scores in the pinned definition order")
        # Every standardized term but CPOE sits at 50.00; CPOE's domain score of
        # 20.00 standardizes to 50.00 + 15.00 * (20.00 - 50.00) / 15.00 = 20.00.
        # STAFFING at 35.00 standardizes to 35.00, so the equal-weight mean of
        # (50, 20, 35, 50, 50) is 41.00.
        assert run["composite_score"] - 41.00 == pytest.approx(0.00, abs=0.005)
        assert run["base_grade_letter"] == "D"
        assert run["letter_grade"] == "D", (
            "reliability_weight is 1.0000, so no one-letter downgrade applies")