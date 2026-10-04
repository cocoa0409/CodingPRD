"""Two different interval semantics on two different resources."""
from test_helpers import (
    api_client, validate_success, DEVELOPER, COMPLIANCE,
    create_archive_sample, setup_archive_sample_containment,
    setup_license_window_conflict,
    SAMPLE_BASE_START, SAMPLE_BASE_END, SAMPLE_TOUCHING_START, SAMPLE_TOUCHING_END,
)


class TestArchiveSampleContainment:

    def test_a_window_wholly_inside_an_existing_draw_is_refused(self, api):
        """PRD §3.3: "Two samples on the same model version may not have overlapping
        windows under containment-tolerant semantics — a window fully contained
        inside another is tolerated, a partial overlap is not, and the conflict is
        refused with `ERR_SAMPLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/overlap_archive_sample_containment_tolerant_windows
        """
        _, model, _, existing = setup_archive_sample_containment()
        res = api_client.create_archive_sample(
            {"score_model_id": model["id"], "sample_ref": "DEV-B", "record_count": 4000,
             "segment_name": "NEAR_PRIME", "sample_kind": "DEVELOPMENT",
             "observation_window_months": 11, "window_start_month": "2024-06",
             "window_end_month": "2025-05"}, DEVELOPER)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_SAMPLE_WINDOW_OVERLAP"

    def test_an_identical_retry_is_an_idempotent_escape(self, api):
        """PRD §3.3: "The one escape hatch is an exact retry: asserting the identical
        `sample_ref` with an identical window is treated as undoing the duplicate
        rather than creating an overlap."

        Design: Difficulty/resource_temporal_overlap/overlap_archive_sample_containment_tolerant_windows
        """
        _, model, _, existing = setup_archive_sample_containment()
        res = api_client.create_archive_sample(
            {"score_model_id": model["id"], "sample_ref": "DEV-A", "record_count": 8000,
             "segment_name": "PRIME", "sample_kind": "DEVELOPMENT",
             "observation_window_months": 12, "window_start_month": SAMPLE_BASE_START,
             "window_end_month": SAMPLE_BASE_END}, DEVELOPER)
        data = validate_success(res, 201)
        assert data["id"] == existing["id"]

    def test_touching_at_one_endpoint_month_is_accepted(self, api):
        """PRD §3.3: "The window is half-open over calendar months: it occupies the
        months from `window_start_month` up to but excluding `window_end_month`"

        Design: Difficulty/resource_temporal_overlap/overlap_archive_sample_containment_tolerant_windows
        """
        _, model, _, existing = setup_archive_sample_containment()
        data = create_archive_sample(
            model["id"], sample_ref="DEV-C", record_count=6000, segment_name="SUBPRIME",
            sample_kind="DEVELOPMENT", observation_window_months=12,
            window_start_month=SAMPLE_TOUCHING_START, window_end_month=SAMPLE_TOUCHING_END)
        assert data["id"] is not None

    def test_the_model_now_holds_two_samples(self, api):
        """PRD §3.3: "A `ModelDeveloper` or `ValidationAnalyst` draws a sample
        against a version by supplying its `sample_ref` — unique within that model
        version — the `record_count` of archive records in the draw"

        Design: Difficulty/resource_temporal_overlap/overlap_archive_sample_containment_tolerant_windows
        """
        _, model, _, existing = setup_archive_sample_containment()
        create_archive_sample(
            model["id"], sample_ref="DEV-C", record_count=6000, segment_name="SUBPRIME",
            sample_kind="DEVELOPMENT", observation_window_months=12,
            window_start_month=SAMPLE_TOUCHING_START, window_end_month=SAMPLE_TOUCHING_END)
        res = api_client.list_archive_samples(
            DEVELOPER, params={"score_model_id": model["id"]})
        data, meta = validate_success(res, 200), res.json()["meta"]
        assert len(data) == 2
        assert meta["total_count"] == 2


class TestLicenceTermHalfOpen:

    def test_a_term_inside_an_active_term_is_refused(self, api):
        """PRD §3.7: "Licence terms for the same lender and variant may not overlap:
        adjacency is allowed, but any positive overlap is refused with
        `ERR_LICENSE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/overlap_license_half_open_terms_on_one_variant
        """
        _, model, variant, north, south = setup_license_window_conflict()
        res = api_client.create_license(
            {"lender_name": "North Bank", "lender_code": "LEND-NORTH",
             "score_variant_id": variant["id"], "volume_tier": "VOLUME_TIER_1",
             "entitled_count": 500, "window_start_month": "2026-06",
             "window_end_month": "2026-07"}, COMPLIANCE)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_LICENSE_WINDOW_CONFLICT"

    def test_terms_that_touch_at_one_boundary_are_legal(self, api):
        """PRD §3.7: "The term is half-open over calendar months: `window_start_month`
        must be no earlier than `2015-01` and strictly before `window_end_month`, and
        `window_end_month` must be no later than `2032-12`. Licence terms for the
        same lender and variant may not overlap: adjacency is allowed"

        Design: Difficulty/resource_temporal_overlap/overlap_license_half_open_terms_on_one_variant
        """
        _, model, variant, north, south = setup_license_window_conflict()
        data = validate_success(
            api_client.create_license(
                {"lender_name": "North Bank", "lender_code": "LEND-NORTH",
                 "score_variant_id": variant["id"], "volume_tier": "VOLUME_TIER_1",
                 "entitled_count": 500, "window_start_month": "2027-01",
                 "window_end_month": "2028-01"}, COMPLIANCE), 201)
        assert data["status"] == "PENDING"
        assert data["id"] is not None

    def test_a_distinct_lender_may_open_a_term_inside_another_window(self, api):
        """PRD §3.7: "The `lender_code` must be unique per licensed variant among
        licences whose status is `ACTIVE`."
        PRD §3.7: "Licence terms for the same lender and variant may not overlap"

        The conflict is keyed on the lender and the variant together, so a different
        lender is free to open a term inside the first lender's window.

        Design: Difficulty/resource_temporal_overlap/overlap_license_half_open_terms_on_one_variant
        """
        _, model, variant, north, south = setup_license_window_conflict()
        data = validate_success(
            api_client.create_license(
                {"lender_name": "South Bank", "lender_code": "LEND-SOUTH",
                 "score_variant_id": variant["id"], "volume_tier": "VOLUME_TIER_2",
                 "entitled_count": 500, "window_start_month": "2026-02",
                 "window_end_month": "2026-03"}, COMPLIANCE), 201)
        assert data["id"] is not None

    def test_the_variant_accumulates_four_licence_rows(self, api):
        """PRD §3.8: "A `ComplianceOfficer` creates a licence in `PENDING` by naming
        the `lender_name`, a short `lender_code` that will be stamped onto every
        score settled under it, the licensed `score_variant_id`, a `volume_tier`
        label, the `entitled_count`, and the licence term's `window_start_month` and
        `window_end_month` in `YYYY-MM` form."

        Design: Difficulty/resource_temporal_overlap/overlap_license_half_open_terms_on_one_variant
        """
        _, model, variant, north, south = setup_license_window_conflict()
        api_client.create_license(
            {"lender_name": "North Bank", "lender_code": "LEND-NORTH",
             "score_variant_id": variant["id"], "volume_tier": "VOLUME_TIER_1",
             "entitled_count": 500, "window_start_month": "2027-01",
             "window_end_month": "2028-01"}, COMPLIANCE)
        api_client.create_license(
            {"lender_name": "South Bank", "lender_code": "LEND-SOUTH",
             "score_variant_id": variant["id"], "volume_tier": "VOLUME_TIER_2",
             "entitled_count": 500, "window_start_month": "2026-02",
             "window_end_month": "2026-03"}, COMPLIANCE)
        res = api_client.list_licenses(COMPLIANCE,
                                       params={"score_variant_id": variant["id"]})
        data = validate_success(res, 200)
        assert len(data) == 4