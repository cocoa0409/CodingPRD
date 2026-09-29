"""Endpoint-shape corners: the simulation controls, the two site-status actions, a
computed read over an empty ledger, and the three response envelopes.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import ERR_FACILITY_NOT_FOUND
from test_helpers.assertions import (
    assert_array_envelope,
    assert_error_envelope,
    assert_instant_equals,
    assert_loading_delta,
    assert_millisecond_timestamp,
    assert_object_envelope,
)
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    LIAISON_HEADERS,
    OFFICER_HEADERS,
    make_operator_headers,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)


class TestLogicalClockSeedAndAdvance:
    def test_the_seed_instant_stamps_the_first_write_and_the_clock_write_moves_it(
        self, api
    ):
        """PRD §2.4: "A fresh server starts its logical clock at `2026-08-01T00:00:00Z`, and the clock advances only when a caller explicitly sets it."

        A fresh server already reads 2026-08-01T00:00:00Z, so the first facility is
        stamped at the seed instant without any clock call. Writing the clock reports the
        new instant and an expiry sweep that found nothing, and the next facility is
        stamped at the new instant.

        Design: Corner/endpoints/ep_clock_starts_at_the_seed_instant_and_advances_on_write
        """
        first = validate_success(
            api.create_facility(F.facility_payload(), make_operator_headers()), 201
        )
        assert_millisecond_timestamp(first["created_at"])
        assert_instant_equals(first["created_at"], C.SEED_CLOCK)

        moved = validate_success(
            api.set_clock(F.clock_payload("2026-09-10T12:00:00Z"), OFFICER_HEADERS)
        )
        assert_instant_equals(moved["now"], "2026-09-10T12:00:00Z")
        assert moved["expired_agreement_count"] == 0

        second = validate_success(
            api.create_facility(F.facility_payload(), make_operator_headers()), 201
        )
        assert_instant_equals(second["created_at"], "2026-09-10T12:00:00Z")
        assert second["version"] == 1


class TestWeatherObservationWritesClearance:
    def test_a_wet_forecast_alone_denies_clearance_without_touching_site_status(
        self, api, build, permitted_site
    ):
        """PRD §3.8: "`weather_clearance_ok` becomes true only when `latest_rainfall_in_24h` is strictly below 0.50 inches **and** `latest_forecast_rainfall_in_48h` is strictly below 1.00 inches **and** `latest_frozen_ground` is false."

        Clearance is a conjunction of three conditions. Rainfall of 0.10 inches is well
        under the 0.50 bound, but a 48-hour forecast of 1.20 inches is at or over the 1.00
        bound, so the single observation lands weather_clearance_ok on false. The
        observation writes all four latest_* fields and leaves the site PERMITTED.

        Design: Corner/endpoints/ep_weather_observation_writes_the_site_clearance_fields
        """
        site = validate_success(
            api.post_weather_observation(
                F.weather_payload(
                    permitted_site["id"],
                    rainfall_in_24h=0.10,
                    forecast_rainfall_in_48h=1.20,
                    frozen_ground=False,
                ),
                make_operator_headers(),
            )
        )

        assert site["latest_rainfall_in_24h"] == 0.10
        assert site["latest_forecast_rainfall_in_48h"] == 1.20
        assert site["latest_frozen_ground"] is False
        assert_instant_equals(site["latest_weather_observed_at"], C.SEED_CLOCK)
        assert site["weather_clearance_ok"] is False
        assert site["status"] == C.SITE_PERMITTED


class TestRestrictThenReinstateRoundTrip:
    def test_an_unused_site_round_trips_back_to_permitted(
        self, api, build, permitted_site
    ):
        """PRD §3.5: "**Reinstating a site** moves `RESTRICTED` back to `PERMITTED`, and both substantive conditions must hold regardless of what the `restriction_reason` was: for every analyte whose `ACTIVE` limit row carries a non-null `cplr_kg_per_hectare`, the site's cumulative loading for that analyte must be strictly below 0.90 multiplied by that limit, otherwise `ERR_CPLR_HEADROOM_EXCEEDED`; and `gating_risk_score` must be strictly below 60.00, otherwise `ERR_ODOR_RISK_BLOCK`."

        An officer's explicit restriction stamps restriction_reason OFFICER_ORDER, and
        reinstatement is conditional on both substantive tests: cumulative loading
        strictly below 0.90 of every CPLR and a gating risk score strictly below 60.00.
        On a site with an empty ledger and no complaints both hold, so the round trip
        lands back on PERMITTED with the reason cleared and version 5.

        Design: Corner/endpoints/ep_restrict_then_reinstate_round_trips_the_site_to_permitted
        """
        restricted = validate_success(
            api.restrict_site(permitted_site["id"], {}, OFFICER_HEADERS)
        )
        assert restricted["status"] == C.SITE_RESTRICTED
        assert restricted["restriction_reason"] == "OFFICER_ORDER"

        reinstated = validate_success(
            api.reinstate_site(permitted_site["id"], OFFICER_HEADERS)
        )
        assert reinstated["status"] == C.SITE_PERMITTED
        assert reinstated["restriction_reason"] is None
        assert reinstated["version"] == 5


class TestLoadingSummaryOverAnEmptyLedger:
    def test_an_unused_site_reports_empty_maps_and_full_headroom(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §3.5: "`binding_analyte` is the analyte whose remaining cumulative headroom is smallest as a fraction of its own `cplr_kg_per_hectare`, with ties broken by ascending analyte name; when no analyte has any loading it is null."

        The empty-ledger case is a legitimate read, not an error. Both loading maps come
        back as empty objects while the headroom maps carry the full limits - 39.0000 kg/ha
        cumulative and 1.9000 kg/ha annual for cadmium - and the binding analyte is null
        because no analyte carries any loading yet.

        Design: Corner/endpoints/ep_loading_summary_on_a_site_without_ledger_rows_returns_full_headroom
        """
        site = build.permitted_site(facility["id"])

        summary = validate_success(
            api.get_loading_summary(site["id"], AGRONOMIST_HEADERS)
        )

        assert summary["site_id"] == site["id"]
        assert summary["cumulative_loading_kg_per_hectare"] == {}
        assert summary["annual_loading_kg_per_hectare"] == {}
        assert_loading_delta(summary["cplr_headroom_kg_per_hectare"]["CADMIUM"], 39.0000)
        assert_loading_delta(summary["aplr_headroom_kg_per_hectare"]["CADMIUM"], 1.9000)
        assert summary["binding_analyte"] is None
        assert summary["pfas_advisory_flag"] is False


class TestResponseEnvelopeShapes:
    def test_one_resource_read_three_ways_pins_all_three_envelopes(self, api, facility):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        The single read is an object envelope carrying the resource, the unparameterised
        list is an array envelope at the declared defaults of limit 10 and offset 0 with a
        total_count of 1 and has_more false, and the unknown id is an error envelope of
        exactly error_id and message under a 404.

        Design: Corner/endpoints/ep_response_envelope_shapes_for_object_array_and_error
        """
        single = api.get_facility(facility["id"], LIAISON_HEADERS)
        body = single.json()
        assert_object_envelope(body)
        assert body["data"]["id"] == facility["id"]

        listed = api.list_facilities(LIAISON_HEADERS)
        list_body = listed.json()
        assert_array_envelope(list_body)
        assert list_body["meta"]["limit"] == 10
        assert list_body["meta"]["offset"] == 0
        assert list_body["meta"]["total_count"] == 1
        assert list_body["meta"]["has_more"] is False

        missing = api.get_facility(NON_EXISTENT_UUID, LIAISON_HEADERS)
        validate_error(missing, ERR_FACILITY_NOT_FOUND, 404)
        error_body = missing.json()
        assert_error_envelope(error_body)
        assert error_body["data"]["message"].strip() != ""
