"""Error-condition corners: scoped uniqueness, the two laboratory-filing refusals,
the reporting lock, the open-events guard and the unauthenticated request.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_DUPLICATE_RESOURCE,
    ERR_LIMIT_NOT_FOUND,
    ERR_OPEN_EVENTS_EXIST,
    ERR_REPORTING_PERIOD_LOCKED,
    ERR_SAMPLING_ROUND_MISMATCH,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_dry_tons,
    assert_error_envelope,
    assert_loading_delta,
    assert_wet_tons,
)
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    LAB_ANALYST_HEADERS,
    OFFICER_HEADERS,
    make_officer_headers,
    make_operator_headers,
)
from prd_bench_local_runner.testing import validate_error, validate_success


class TestBatchCodeUniquenessIsScopedToTheFacility:
    def test_the_same_code_collides_within_a_facility_and_is_free_across_facilities(
        self, api, build
    ):
        """PRD §2.7: "**Priority 58 — uniqueness.** `npdes_permit_number` is unique across all facilities; `batch_code` is unique within a `facility_id`; `site_code` is unique within a `facility_id`; `report_year` is unique within a `facility_id` across reports whose `status` is `DRAFT`, `SUBMITTED` or `AMENDED`; and the triple of `batch_id`, `analyte` and `sampling_event_index` is unique across laboratory results."

        batch_code is unique per facility, not globally. A second B-2026-001 on the same
        plant is ERR_DUPLICATE_RESOURCE, while the identical code on a different plant is
        accepted, and the refused attempt credits no storage to the first facility.

        Design: Corner/errors/err_duplicate_batch_code_within_the_same_facility_is_rejected
        """
        first_facility = build.facility()
        second_facility = build.facility()
        build.batch(
            first_facility["id"],
            batch_code="B-2026-001",
            wet_tons=100.00,
            dry_tons_in=25.000,
        )

        validate_error(
            api.create_batch(
                F.batch_payload(
                    first_facility["id"],
                    batch_code="B-2026-001",
                    wet_tons=100.00,
                    dry_tons_in=25.000,
                ),
                make_operator_headers(first_facility["id"]),
            ),
            ERR_DUPLICATE_RESOURCE,
        )

        elsewhere = validate_success(
            api.create_batch(
                F.batch_payload(
                    second_facility["id"],
                    batch_code="B-2026-001",
                    wet_tons=100.00,
                    dry_tons_in=25.000,
                ),
                make_operator_headers(second_facility["id"]),
            ),
            201,
        )
        assert elsewhere["batch_code"] == "B-2026-001"
        assert elsewhere["facility_id"] == second_facility["id"]

        assert_wet_tons(
            build.read_facility(first_facility["id"])["storage_used_wet_tons"], 100.00
        )


class TestLabResultNeedsAnActiveLimit:
    def test_a_result_for_an_unlimited_analyte_is_refused(self, api, build, facility):
        """PRD §2.7: "**Priority 60 — limit configured.** An `ACTIVE` pollutant limit row exists for the posted `analyte`, otherwise `ERR_LIMIT_NOT_FOUND` (404)."

        A laboratory result can only be scored against an ACTIVE limit row, so filing a
        cadmium result while no cadmium limit exists is ERR_LIMIT_NOT_FOUND. The sampling
        round matches, so it is the limit rule that speaks, and the batch keeps waiting on
        results.

        Design: Corner/errors/err_lab_result_for_an_analyte_without_an_active_limit_is_rejected
        """
        batch = build.dewatered_batch(facility["id"])

        validate_error(
            api.create_lab_result(
                batch["id"], F.lab_result_payload(), LAB_ANALYST_HEADERS
            ),
            ERR_LIMIT_NOT_FOUND,
        )

        assert build.read_batch(batch["id"])["quality_status"] == C.QUALITY_PENDING_RESULTS


class TestLabResultRoundMustMatch:
    def test_a_result_claiming_the_next_round_is_refused(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §2.7: "**Priority 59 — sampling round.** A laboratory result's `sampling_event_index` equals the target batch's `retest_round`, otherwise `ERR_SAMPLING_ROUND_MISMATCH` (422)."

        sampling_event_index must equal the batch's current retest_round. A batch still on
        round 0 refuses a result claiming round 1 with ERR_SAMPLING_ROUND_MISMATCH, ahead of
        the ACTIVE-limit check that would otherwise pass anyway.

        Design: Corner/errors/err_lab_result_filed_against_a_stale_sampling_round_is_rejected
        """
        batch = build.dewatered_batch(facility["id"])

        validate_error(
            api.create_lab_result(
                batch["id"],
                F.lab_result_payload(sampling_event_index=1),
                LAB_ANALYST_HEADERS,
            ),
            ERR_SAMPLING_ROUND_MISMATCH,
        )

        current = build.read_batch(batch["id"])
        assert current["retest_round"] == 0
        assert current["quality_status"] == C.QUALITY_PENDING_RESULTS


class TestReportingLockBlocksTheVoid:
    def test_a_submitted_year_freezes_the_compensating_void(self, api, base_world):
        """PRD §2.7: "**Priority 28 — reporting lock.** No annual report for the event's facility and the calendar year of `window_start` is in status `SUBMITTED` or `AMENDED`, otherwise `ERR_REPORTING_PERIOD_LOCKED` (409)."

        Voiding a COMPLETED event is normally allowed, but once the 2026 report is
        SUBMITTED the year is frozen: the void is ERR_REPORTING_PERIOD_LOCKED, the event
        stays COMPLETED with no void stamp, no REVERSAL row is written and the site keeps
        the 0.0359 kg/ha of cadmium the close-out recorded.

        Design: Corner/errors/err_void_after_the_reporting_year_is_submitted_is_locked
        """
        w = base_world
        build = w.build
        event = build.completed_event(
            w.site_id,
            w.batch_id,
            w.agreement_id,
            complete_kwargs={"applied_dry_tons": 80.000},
        )
        report = build.annual_report(
            w.facility_id,
            2026,
            public_summary="2026 biosolids land application summary",
        )
        submitted = build.submit_report(report["id"])
        assert submitted["status"] == "SUBMITTED"
        assert_dry_tons(submitted["total_dry_tons_land_applied"], 80.000)

        validate_error(
            api.void_event(event["id"], make_officer_headers("officer-close-2")),
            ERR_REPORTING_PERIOD_LOCKED,
        )

        current_event = build.read_event(event["id"])
        assert current_event["status"] == C.EVENT_COMPLETED
        assert current_event["voided_at"] is None

        summary = build.loading_summary(w.site_id)
        assert_loading_delta(summary["cumulative_loading_kg_per_hectare"]["CADMIUM"], 0.0359)


class TestCloseSiteRefusesOpenEvents:
    def test_one_scheduled_event_is_enough_to_refuse_the_close(self, api, base_world):
        """PRD §3.5: "It is refused with `ERR_OPEN_EVENTS_EXIST` while any application event on the site is `SCHEDULED`, `WEATHER_HOLD`, `DEFERRED` or `IN_PROGRESS`."

        Closing a site is refused with ERR_OPEN_EVENTS_EXIST while any of its events is
        SCHEDULED, WEATHER_HOLD, DEFERRED or IN_PROGRESS. One SCHEDULED window is enough:
        the site stays PERMITTED at version 5 and the ACTIVE agreement is not withdrawn.

        Design: Corner/errors/err_close_site_with_a_scheduled_event_is_rejected
        """
        w = base_world
        build = w.build
        event = build.event(w.site_id, w.batch_id, w.agreement_id)

        validate_error(
            api.close_site(w.site_id, AGRONOMIST_HEADERS), ERR_OPEN_EVENTS_EXIST
        )

        current_site = build.read_site(w.site_id)
        assert current_site["status"] == C.SITE_PERMITTED
        assert current_site["version"] == 5
        assert build.read_agreement(w.agreement_id)["status"] == C.AGREEMENT_ACTIVE
        assert build.read_event(event["id"])["status"] == C.EVENT_SCHEDULED


class TestUnauthenticatedRequest:
    def test_a_request_without_identity_headers_is_refused(self, api, facility):
        """PRD §2.7: "**Priority 1 — authentication, every endpoint.** `X-User-Role` and `X-User-ID` are both present and non-blank, otherwise `ERR_UNAUTHENTICATED` (401)."

        Priority 1 runs before existence and before the role table: a read with neither
        X-User-Role nor X-User-ID is ERR_UNAUTHENTICATED under a 401 error envelope, even
        though the facility id resolves and every role is allowed to read it.

        Design: Corner/errors/err_unauthenticated_when_identity_headers_are_absent
        """
        response = api.get_facility(facility["id"], {})
        validate_error(response, ERR_UNAUTHENTICATED, 401)
        assert_error_envelope(response.json())
