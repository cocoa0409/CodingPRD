"""Cross-cutting layers: the two optimistic-concurrency guards, monotonic row
versioning, and the inclusive storage-utilization threshold with its reset.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_STALE_BATCH_VERSION,
    ERR_STALE_SITE_VERSION,
)
from test_helpers.assertions import (
    assert_dry_tons,
    assert_facility_storage,
    assert_percent,
    assert_wet_tons,
)
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    OFFICER_HEADERS,
    make_operator_headers,
)
from prd_bench_local_runner.testing import validate_error, validate_success


class TestStaleSiteVersionGuardsTheAgreementDraft:
    def test_a_second_draft_is_refused_only_by_the_version_guard(
        self, api, build, facility
    ):
        """PRD §2.7: "**Priority 10 — agreement stale read.** `expected_site_version` equals the site's current `version`, otherwise `ERR_STALE_SITE_VERSION` (412)."

        A second DRAFT agreement on the same site is legal, so no state precondition can
        refuse it - only the stale-read guard can. The site sits at version 3 after the
        permit decision, the first draft and the weather observation each add one, and the
        caller replaying version 3 is refused with ERR_STALE_SITE_VERSION 412; re-reading
        the site yields version 5 and the identical body then succeeds.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_site_version_rejects_a_second_agreement_create
        """
        site = build.permitted_site(facility["id"])
        assert site["version"] == 3

        first = build.agreement(site["id"], site["version"])
        build.weather(site["id"])

        stale_body = F.agreement_payload(
            site["id"], site["version"], max_dry_tons_per_acre=18.0
        )
        validate_error(
            api.create_agreement(stale_body, AGRONOMIST_HEADERS),
            ERR_STALE_SITE_VERSION,
            412,
        )

        current_version = build.read_site(site["id"])["version"]
        assert current_version == 5

        fresh_body = F.agreement_payload(
            site["id"], current_version, max_dry_tons_per_acre=18.0
        )
        second = validate_success(
            api.create_agreement(fresh_body, AGRONOMIST_HEADERS), 201
        )
        assert second["status"] == C.AGREEMENT_DRAFT
        assert second["max_dry_tons_per_acre"] == 18.0

        assert build.read_agreement(first["id"])["status"] == C.AGREEMENT_DRAFT
        assert build.read_site(site["id"])["version"] == 6


class TestStaleBatchVersionGuardsTheDiversionDraft:
    def test_the_first_order_succeeds_and_the_replay_at_the_same_version_is_refused(
        self, api, build, diversion_world
    ):
        """PRD §2.7: "**Priority 11 — diversion stale read.** `expected_batch_version` equals the batch's current `version`, otherwise `ERR_STALE_BATCH_VERSION` (412)."

        Splitting one batch across two diversion orders is legitimate, so the guard is
        purely version-based. The DEWATERED batch is at version 3; the first 40.000 dry ton
        order takes it to 4, the replay at 3 is ERR_STALE_BATCH_VERSION 412, and the
        re-read at 4 succeeds, leaving 80.000 of the 160.000 unallocated at version 5 with
        storage untouched, because drafting never debits the cake pad.

        Design: Corner/cross_cutting_complexity_layers/occ_correct_batch_version_succeeds_then_the_stale_repeat_is_rejected
        """
        w = diversion_world
        build = w["build"]
        batch = w["batch"]
        outlet = w["outlet"]
        assert batch["version"] == 3

        first = validate_success(
            api.create_diversion_order(
                F.diversion_order_payload(
                    batch["id"], outlet["id"], 3, dry_tons=40.000, wet_tons=200.00,
                    haul_miles=24.0,
                ),
                make_operator_headers(),
            ),
            201,
        )
        assert first["status"] == C.ORDER_DRAFT

        validate_error(
            api.create_diversion_order(
                F.diversion_order_payload(
                    batch["id"], outlet["id"], 3, dry_tons=40.000, wet_tons=200.00,
                    haul_miles=24.0,
                ),
                make_operator_headers(),
            ),
            ERR_STALE_BATCH_VERSION,
            412,
        )

        current_version = build.read_batch(batch["id"])["version"]
        assert current_version == 4

        second = validate_success(
            api.create_diversion_order(
                F.diversion_order_payload(
                    batch["id"], outlet["id"], current_version, dry_tons=40.000,
                    wet_tons=200.00, haul_miles=24.0,
                ),
                make_operator_headers(),
            ),
            201,
        )
        assert second["status"] == C.ORDER_DRAFT

        final_batch = build.read_batch(batch["id"])
        assert_dry_tons(final_batch["unallocated_dry_tons"], 80.000)
        assert final_batch["version"] == 5
        assert_wet_tons(
            build.read_facility(w["facility"]["id"])["storage_used_wet_tons"], 800.00
        )


class TestVersionIncrementsOnEveryWriteOfTheRow:
    def test_three_writes_take_the_batch_from_one_to_three_with_no_gaps(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §3.2: "Both advances increment the batch's `version` by 1 and refresh `updated_at` to the logical clock."

        Every mutation of a row bumps its version by exactly one, with no gaps and no
        double increment: create is version 1, the DIGESTED advance is 2 and the DEWATERED
        advance is 3, and by that third write the digestion figures are already derived -
        van Kleeck 47.62 percent with the quality dimension opened to PENDING_RESULTS.

        Design: Corner/cross_cutting_complexity_layers/layer_version_increments_on_every_write_of_the_same_row
        """
        operator = make_operator_headers(facility["id"])

        created = validate_success(
            api.create_batch(F.batch_payload(facility["id"]), operator), 201
        )
        assert created["version"] == 1

        digested = validate_success(
            api.advance_process(created["id"], F.digest_payload(), operator)
        )
        assert digested["version"] == 2

        dewatered = validate_success(
            api.advance_process(created["id"], F.dewater_payload(), operator)
        )
        assert dewatered["version"] == 3

        current = build.read_batch(created["id"])
        assert current["version"] == 3
        assert current["process_status"] == C.PROCESS_DEWATERED
        assert current["quality_status"] == C.QUALITY_PENDING_RESULTS
        assert_percent(current["vsr_pct_van_kleeck"], 47.62)


class TestUtilizationThresholdFreezesThenResets:
    def test_ninety_eight_percent_freezes_the_plant_and_settlement_reopens_it(
        self, api, build
    ):
        """PRD §2.8: "Both thresholds are inclusive and both comparisons use the 2-decimal rounded `storage_utilization_pct`."

        The freeze threshold is inclusive and it reverses. A second batch lifts 800.00 of
        1000.00 wet tons to exactly 980.00, which is 98.00 percent, so posture flips to
        FROZEN and the drawdown projection reports 0 days of capacity against 40.00 wet tons
        a day of production. Settling a 200.00 wet ton diversion is the only step that
        debits the cake pad: 780.00 stored is 78.00 percent, posture returns to OPEN and the
        projection reports 5 days.

        Design: Corner/cross_cutting_complexity_layers/layer_utilization_threshold_freezes_at_the_boundary_and_resets_on_settlement
        """
        facility = build.facility(
            storage_capacity_wet_tons=1000.00, daily_production_wet_tons=40.00
        )
        build.limit()
        batch = build.dewatered_batch(facility["id"])
        outlet = build.outlet()

        build.batch(facility["id"], wet_tons=180.00, dry_tons_in=45.000)

        frozen = build.read_facility(facility["id"])
        assert_facility_storage(frozen, 980.00, 98.00, C.POSTURE_FROZEN)
        assert frozen["days_of_capacity"] == 0

        order = build.order(batch["id"], outlet["id"], batch["version"],
                            dry_tons=40.000, wet_tons=200.00, haul_miles=24.0)
        build.commit_order(order["id"])
        build.settle_order(order["id"])
        assert build.read_order(order["id"])["status"] == C.ORDER_SETTLED

        reopened = build.read_facility(facility["id"])
        assert_facility_storage(reopened, 780.00, 78.00, C.POSTURE_OPEN)

        projection = validate_success(
            api.get_storage_projection(facility["id"], OFFICER_HEADERS)
        )
        assert projection["days_of_capacity"] == 5
        assert_wet_tons(projection["projected_outflow_wet_tons"], 0.00)
