"""Entity-surface probes: declared defaults, system fields, not-found handling,
listing windows, required fields, enum members, parentage and immutability.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_AGREEMENT_SITE_MISMATCH,
    ERR_BATCH_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LIMIT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_append_only_resource,
    assert_array_envelope,
    assert_dry_tons,
    assert_error_envelope,
    assert_instant_equals,
    assert_loading_delta,
    assert_object_envelope,
    assert_pagination_window,
    assert_percent,
    assert_wet_tons,
)
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    LAB_ANALYST_HEADERS,
    OFFICER_HEADERS,
    OTHER_FARMER_ID,
    make_operator_headers,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFacilityCreation:
    def test_facility_comes_back_with_declared_zeros_and_system_fields(self, api, build):
        """PRD §3.1: "The new facility is created with `version` 1 and every derived figure at its documented zero value: `storage_used_wet_tons` 0.00, `storage_utilization_pct` 0.00, `open_ceiling_exceedance_count` 0, `substantiated_complaint_count_30d` 0, `days_of_capacity` 9999 and `posture` `OPEN`."

        A facility built from the five required inputs alone returns every computed
        counter at its declared zero with posture OPEN, version 1, and created_at taken
        from the logical clock rather than wall time.

        Design: Corner/entities/entity_facility_create_returns_declared_defaults_and_system_fields
        """
        response = api.create_facility(
            F.facility_payload(name="North Water Reclamation Plant"),
            make_operator_headers(),
        )
        body = response.json()
        assert_object_envelope(body)
        facility = validate_success(response, 201)

        assert facility["name"] == "North Water Reclamation Plant"
        assert_wet_tons(facility["storage_capacity_wet_tons"], 5000.00)
        assert_wet_tons(facility["storage_used_wet_tons"], 0.00)
        assert_percent(facility["storage_utilization_pct"], 0.00)
        assert facility["open_ceiling_exceedance_count"] == 0
        assert facility["substantiated_complaint_count_30d"] == 0
        assert facility["posture"] == C.POSTURE_OPEN
        assert facility["version"] == 1
        assert_instant_equals(facility["created_at"], C.SEED_CLOCK)


class TestSiteDefaults:
    def test_omitted_optional_site_fields_take_their_declared_defaults(
        self, api, build, facility
    ):
        """PRD §3.5: "The optional fields default to `soil_ph` 6.5, `depth_to_groundwater_ft` 10.0, `slope_pct` 3.0, `nearest_residence_ft` 3000 and `reapplication_interval_days` 30."

        A site registered with required fields only takes the 30-day reapplication
        interval default, starts in DRAFT with no permit, empty loading maps, zeroed odor
        scores and no weather clearance at all - clearance is false until an observation
        has actually been posted.

        Design: Corner/entities/entity_site_omitting_reapplication_interval_applies_thirty_day_default
        """
        payload = {
            "facility_id": facility["id"],
            "site_code": "S-01",
            "acres": 100.0,
            "crop_type": C.CROP_CORN,
            "crop_n_demand_lb_per_acre": 160.0,
            "crop_p_removal_lb_per_acre": 60.0,
            "soil_p_index": 40,
            "setback_to_well_ft": 200,
            "setback_to_surface_water_ft": 150,
            "allowed_application_months": [8, 9, 10],
        }
        site = validate_success(api.create_site(payload, AGRONOMIST_HEADERS), 201)

        assert site["reapplication_interval_days"] == 30
        assert site["status"] == C.SITE_DRAFT
        assert site["permit_number"] is None
        assert site["permitted_at"] is None
        assert site["cumulative_loading_kg_per_hectare"] == {}
        assert site["annual_loading_kg_per_hectare"] == {}
        assert site["weather_clearance_ok"] is False
        assert site["latest_weather_observed_at"] is None
        assert_percent(site["odor_risk_score_historical"], 0.00)
        assert_percent(site["gating_risk_score"], 0.00)
        assert site["pfas_advisory_flag"] is False
        assert site["version"] == 1


class TestBatchNotFound:
    def test_unknown_batch_id_returns_the_error_envelope_with_404(
        self, api, build, facility
    ):
        """PRD §2.7: "**Priority 3 — path identifier existence, every endpoint carrying a path identifier.** Each path identifier resolves, validated left to right in this order: `facilityId`, `batchId`, `siteId`, `agreementId`, `eventId`, `orderId`, `complaintId`, `reportId`, `entryId`."

        A syntactically valid identifier that names no batch row answers with the
        error envelope and ERR_BATCH_NOT_FOUND, not an empty success body.

        Design: Corner/entities/entity_batch_get_with_unknown_id_returns_batch_not_found
        """
        response = api.get_batch(NON_EXISTENT_UUID, make_operator_headers())

        assert_error_envelope(response.json())
        validate_error(response, ERR_BATCH_NOT_FOUND, 404)


class TestBatchListing:
    def test_status_filter_is_applied_before_the_pagination_window(
        self, api, build, facility
    ):
        """PRD §2.3: "`total_count` is the number of rows matching the filters **before** `limit` and `offset` are applied, and `has_more` is true exactly when the sum of `offset` and the number of rows returned is less than `total_count`."

        Three batches exist and one has been digested, so the THICKENED filter reports
        a total of 2: the filter runs before the window. A one-row page at offset 0
        reports more to come, and the same page at offset 1 reports none, returning a
        different batch and never the digested one.

        Design: Corner/entities/entity_batch_list_filters_by_process_status_and_paginates
        """
        first_batch = build.batch(facility["id"], wet_tons=100.00, dry_tons_in=25.000)
        build.batch(facility["id"], wet_tons=100.00, dry_tons_in=25.000)
        build.batch(facility["id"], wet_tons=100.00, dry_tons_in=25.000)
        build.digest(first_batch["id"], dry_tons_out=20.000)

        params = {
            "facility_id": facility["id"],
            "process_status": C.PROCESS_THICKENED,
            "limit": 1,
            "offset": 0,
        }
        first_response = api.list_batches(OFFICER_HEADERS, params)
        assert_array_envelope(first_response.json())
        page_one, meta_one = validate_paginated(first_response)
        assert len(page_one) == 1
        assert meta_one["limit"] == 1 and meta_one["offset"] == 0
        assert_pagination_window(meta_one, total_count=2, returned=1)
        assert meta_one["has_more"] is True

        page_two, meta_two = validate_paginated(
            api.list_batches(OFFICER_HEADERS, dict(params, offset=1))
        )
        assert len(page_two) == 1
        assert_pagination_window(meta_two, total_count=2, returned=1)
        assert meta_two["has_more"] is False

        assert page_one[0]["id"] != page_two[0]["id"]
        assert first_batch["id"] not in (page_one[0]["id"], page_two[0]["id"])


class TestSiteRequiredFields:
    def test_missing_allowed_application_months_is_refused(self, api, build, facility):
        """PRD §3.5: "The required fields are `facility_id`, `site_code` (unique within the facility), `acres` (greater than 0, 2 decimal places), `crop_type` (one of `CORN`, `SOYBEAN`, `HAY`, `SMALL_GRAIN`, `PASTURE`), `crop_n_demand_lb_per_acre` (greater than 0), `crop_p_removal_lb_per_acre` (greater than 0), `soil_p_index` (at or above 0), `setback_to_well_ft` (at or above 0), `setback_to_surface_water_ft` (at or above 0) and `allowed_application_months` (a non-empty array of integers from 1 to 12, strictly ascending, no duplicates)."

        The allowed application months are a required input with no default, so a site
        payload that omits them is refused as an invalid request and no site row is left
        behind.

        Design: Corner/entities/entity_site_create_missing_allowed_application_months_is_rejected
        """
        payload = {
            "facility_id": facility["id"],
            "site_code": "S-01",
            "acres": 100.0,
            "crop_type": C.CROP_CORN,
            "crop_n_demand_lb_per_acre": 160.0,
            "crop_p_removal_lb_per_acre": 60.0,
            "soil_p_index": 40,
            "setback_to_well_ft": 200,
            "setback_to_surface_water_ft": 150,
        }
        validate_error(api.create_site(payload, AGRONOMIST_HEADERS), ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_sites(AGRONOMIST_HEADERS, {"facility_id": facility["id"]})
        )
        assert meta["total_count"] == 0


class TestBatchEnumMembership:
    def test_unknown_stabilization_process_is_refused(self, api, build, facility):
        """PRD §2.7: "**Priority 5 — request schema, every endpoint.** Required fields present, types correct, enum members recognised, numeric ranges honoured, month arrays strictly ascending within 1 through 12 with no duplicates, `window_end` strictly after `window_start`, `term_end` strictly after `term_start`, `return_at` strictly after `depart_at`, `limit` within 1 through 100 and `offset` at least 0, otherwise `ERR_INVALID_REQUEST` (400)."

        The stabilization process is an enum, so an unlisted member is refused as an
        invalid request rather than stored verbatim, and no batch row is created.

        Design: Corner/entities/entity_batch_create_rejects_unknown_stabilization_process_enum
        """
        payload = F.batch_payload(
            facility["id"],
            wet_tons=100.00,
            dry_tons_in=25.000,
            stabilization_process="SOLAR_DRYING",
        )
        validate_error(
            api.create_batch(payload, make_operator_headers(facility["id"])),
            ERR_INVALID_REQUEST,
        )

        _, meta = validate_paginated(
            api.list_batches(OFFICER_HEADERS, {"facility_id": facility["id"]})
        )
        assert meta["total_count"] == 0


class TestLabResultParentage:
    def test_result_filed_against_an_unknown_batch_stops_at_existence(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §2.7: "**Priority 3 — path identifier existence, every endpoint carrying a path identifier.** Each path identifier resolves, validated left to right in this order: `facilityId`, `batchId`, `siteId`, `agreementId`, `eventId`, `orderId`, `complaintId`, `reportId`, `entryId`."

        A laboratory result is a child of a batch, so a result whose parent path
        identifier resolves to nothing is refused for the missing batch and never reaches
        the active-limit check further down the ladder.

        Design: Corner/entities/entity_lab_result_rejects_unknown_parent_batch
        """
        response = api.create_lab_result(
            NON_EXISTENT_UUID, F.lab_result_payload(), LAB_ANALYST_HEADERS
        )
        error = validate_error(response, ERR_BATCH_NOT_FOUND, 404)
        assert error["error_id"] != ERR_LIMIT_NOT_FOUND


class TestEventAgreementParentage:
    def test_agreement_naming_another_site_is_refused(self, api, build):
        """PRD §2.7: "**Priority 44 — agreement covers this site.** The agreement's `site_id` equals the request's `site_id`, otherwise `ERR_AGREEMENT_SITE_MISMATCH` (422)."

        Both foreign keys resolve and both parents are in the right state, but the
        agreement covers the second site while the event names the first, so the
        cross-reference itself is refused; nothing is reserved and the agreement stands.

        Design: Corner/entities/entity_event_rejects_agreement_belonging_to_another_site
        """
        facility = build.facility()
        build.limit()
        batch = build.qualified_batch(facility["id"])
        first_site = build.permitted_site(facility["id"])
        build.active_agreement(first_site["id"], first_site["version"])
        second_site = build.permitted_site(facility["id"])
        other_agreement = build.active_agreement(
            second_site["id"],
            second_site["version"],
            farmer_user_id=OTHER_FARMER_ID,
            farm_name="Smith Acres",
        )

        response = api.create_event(
            F.event_payload(
                first_site["id"],
                batch["id"],
                other_agreement["id"],
                acres_treated=100.0,
                planned_dry_tons=80.000,
            ),
            AGRONOMIST_HEADERS,
        )
        validate_error(response, ERR_AGREEMENT_SITE_MISMATCH)

        assert_dry_tons(build.read_batch(batch["id"])["unallocated_dry_tons"], 160.000)
        assert (
            build.read_agreement(other_agreement["id"])["status"] == C.AGREEMENT_ACTIVE
        )


class TestLoadingLedgerImmutability:
    def test_ledger_row_is_append_only_and_written_only_by_close_out(self, api, build):
        """PRD §2.10: "Metal loading on a field is tracked in an append-only ledger of per-analyte entries, and the site's two loading maps are always projections of that ledger, never independently maintained accumulators."

        Closing out 80.000 dry tons over 100.0 acres writes exactly one APPLICATION
        row of 0.0359 kg/ha stamped with the source event and the applied year. The row
        exposes an identifier and a creation instant but carries no version and no update
        instant, and the site total mirrors it exactly.

        Design: Corner/entities/entity_loading_ledger_entry_is_immutable_with_no_write_endpoint
        """
        facility = build.facility()
        build.limit()
        batch = build.qualified_batch(facility["id"])
        site = build.permitted_site(facility["id"])
        agreement = build.active_agreement(site["id"], site["version"])
        build.weather(site["id"])
        event = build.completed_event(
            site["id"], batch["id"], agreement["id"],
            acres_treated=100.0, planned_dry_tons=80.000,
            complete_kwargs={"applied_dry_tons": 80.000},
        )

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                OFFICER_HEADERS,
                {
                    "site_id": site["id"],
                    "analyte": "CADMIUM",
                    "entry_type": C.ENTRY_APPLICATION,
                },
            )
        )
        assert meta["total_count"] == 1
        entry = rows[0]
        assert_append_only_resource(entry)
        assert_loading_delta(entry["kg_per_hectare_delta"], 0.0359)
        assert entry["applied_year"] == 2026
        assert entry["entry_type"] == C.ENTRY_APPLICATION
        assert entry["source_event_id"] == event["id"]
        assert entry["reversal_of_id"] is None

        site_now = build.read_site(site["id"])
        assert_loading_delta(
            site_now["cumulative_loading_kg_per_hectare"]["CADMIUM"], 0.0359
        )
