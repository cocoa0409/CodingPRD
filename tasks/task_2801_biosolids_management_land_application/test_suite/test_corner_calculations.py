"""Derived-figure corners: constants applied at their exact bound, conjunction
branches, input-set filtering in the annual rollup, and the odor score clamp.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_PATHOGEN_CLASS_INSUFFICIENT,
    ERR_VECTOR_OPTION_EVIDENCE_MISSING,
    ERR_VSR_BELOW_MINIMUM,
)
from test_helpers.assertions import (
    assert_dry_tons,
    assert_percent,
)
from test_helpers.test_users import (
    CERTIFYING_OFFICER_HEADERS,
    LIAISON_HEADERS,
    OFFICER_HEADERS,
)
from prd_bench_local_runner.testing import validate_error, validate_success


class TestPathogenClassBelowTheDetentionConstant:
    def test_ten_detention_days_yields_pathogen_class_none(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §3.3: "`PSRP_ALT1_TIME_TEMP` yields `CLASS_B` when `digester_temp_c` is at or above 35.0 and `detention_days` is at or above 15.0."

        Under PSRP_ALT1_TIME_TEMP the class requires 35.0 C and 15.0 detention days
        together. A run at 36.0 C for only 10.0 days clears the temperature and misses
        the duration, so the conjunction fails, pathogen_class is NONE and certification
        is refused with ERR_PATHOGEN_CLASS_INSUFFICIENT even though the reduction
        figures and the metal panel are both clean.

        Design: Corner/calculations/calc_pathogen_class_is_none_below_the_class_b_detention_constant
        """
        batch = build.batch(facility["id"], detention_days=10.0, digester_temp_c=36.0)
        build.digest(batch["id"], detention_days=10.0, digester_temp_c=36.0)
        build.dewater(batch["id"])
        build.lab_result(batch["id"])

        error = validate_error(
            api.certify_batch(batch["id"], CERTIFYING_OFFICER_HEADERS),
            ERR_PATHOGEN_CLASS_INSUFFICIENT,
        )
        assert error["error_id"] != ERR_VSR_BELOW_MINIMUM

        current = build.read_batch(batch["id"])
        assert current["pathogen_class"] == C.PATHOGEN_CLASS_NONE
        assert_percent(current["vsr_pct_van_kleeck"], 47.62)
        assert_percent(current["vsr_pct_mass_balance"], 37.14)
        assert current["vector_demonstrated_at_batch"] is False
        assert current["quality_status"] == C.QUALITY_PENDING_RESULTS
        assert current["certified_at"] is None


class TestVectorOptionThreeTemperatureBound:
    def test_sour_within_bound_but_digester_too_warm_is_not_demonstrated(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §3.3: "`VAR_OPTION_3_SOUR` is demonstrated when `sour_mg_o2_per_g_hr` is not null and at or below 1.5 milligrams of oxygen per gram of total solids per hour, **and** `digester_temp_c` is at or below 20.0 degrees Celsius."

        VAR_OPTION_3_SOUR is a conjunction: the uptake rate must be at or below 1.5
        and the digester at or below 20.0 C. A rate of 1.2 in a 36.0 C digester
        satisfies only the first half, so certification fails with
        ERR_VECTOR_OPTION_EVIDENCE_MISSING - not ERR_VSR_BELOW_MINIMUM, which belongs to
        a different option - and the batch keeps its CLASS_B pathogen class.

        Design: Corner/calculations/calc_vector_option_three_sour_fails_above_the_temperature_bound
        """
        batch = build.batch(
            facility["id"],
            vector_option=C.VECTOR_OPTION_3_SOUR,
            sour_mg_o2_per_g_hr=1.2,
            detention_days=20.0,
            digester_temp_c=36.0,
        )
        build.digest(batch["id"])
        build.dewater(batch["id"])
        build.lab_result(batch["id"])

        error = validate_error(
            api.certify_batch(batch["id"], CERTIFYING_OFFICER_HEADERS),
            ERR_VECTOR_OPTION_EVIDENCE_MISSING,
        )
        assert error["error_id"] != ERR_VSR_BELOW_MINIMUM

        current = build.read_batch(batch["id"])
        assert current["vector_demonstrated_at_batch"] is False
        assert current["pathogen_class"] == C.PATHOGEN_CLASS_B
        assert_percent(current["vsr_pct_van_kleeck"], 47.62)
        assert current["quality_status"] == C.QUALITY_PENDING_RESULTS


class TestAnnualRollupInputSetFiltering:
    def test_rollup_counts_only_completed_events_and_settled_diversions(
        self, api, base_world
    ):
        """PRD §3.12: "Each line is scoped to the calendar year by the exact timestamp field named on that line — `window_start` for events, `settled_at` for diversions, `created_at` for batches, `analyzed_at` for laboratory results — and by exactly the status filters written."

        Three tonnage-bearing rows exist for 2026 - a COMPLETED event of 80.000 dry
        tons, a CANCELLED event of 20.000 and a DRAFT diversion order of 10.000 - and
        each rollup line is scoped by exactly the status filter it declares. The report
        opens with every figure at zero and freezes at submission with
        total_dry_tons_land_applied 80.000, total_dry_tons_diverted 0.000 and one
        distinct site reported.

        Design: Corner/calculations/calc_annual_report_rollup_excludes_cancelled_event_and_unsettled_diversion
        """
        w = base_world
        build = w.build
        build.completed_event(
            w.site_id,
            w.batch_id,
            w.agreement_id,
            complete_kwargs={"applied_dry_tons": 80.000},
        )
        cancelled = build.event(
            w.site_id,
            w.batch_id,
            w.agreement_id,
            window_start="2026-09-05T00:00:00Z",
            window_end="2026-09-06T00:00:00Z",
            planned_dry_tons=20.000,
        )
        build.cancel(cancelled["id"])

        outlet = build.outlet()
        order = build.order(
            w.batch_id,
            outlet["id"],
            build.read_batch(w.batch_id)["version"],
            dry_tons=10.000,
            wet_tons=50.00,
            haul_miles=12.0,
        )

        opened = validate_success(
            api.create_annual_report(
                F.annual_report_payload(
                    w.facility_id,
                    2026,
                    public_summary="2026 biosolids land application summary",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert opened["status"] == C.REPORT_DRAFT
        assert opened["amendment_index"] == 0
        assert_dry_tons(opened["total_dry_tons_land_applied"], 0.000)
        assert_dry_tons(opened["total_dry_tons_diverted"], 0.000)
        assert opened["diverted_dry_tons_by_outlet_type"] == {}
        assert_percent(opened["vsr_compliance_rate_pct"], 0.00)
        assert opened["ceiling_exceedance_count"] == 0
        assert opened["sites_reported_count"] == 0

        frozen = build.submit_report(opened["id"])
        assert_dry_tons(frozen["total_dry_tons_land_applied"], 80.000)
        assert_dry_tons(frozen["total_dry_tons_diverted"], 0.000)
        for outlet_type in (C.OUTLET_COMPOST, C.OUTLET_LANDFILL, C.OUTLET_THERMAL):
            assert_dry_tons(
                frozen["diverted_dry_tons_by_outlet_type"][outlet_type], 0.000
            )
        assert_percent(frozen["vsr_compliance_rate_pct"], 100.00)
        assert frozen["ceiling_exceedance_count"] == 0
        assert frozen["sites_reported_count"] == 1

        assert build.read_event(cancelled["id"])["status"] == C.EVENT_CANCELLED
        assert_dry_tons(build.read_event(cancelled["id"])["reserved_dry_tons"], 0.000)
        assert build.read_order(order["id"])["status"] == C.ORDER_DRAFT


class TestOdorRiskScoreClamp:
    def test_fourth_severe_complaint_clamps_the_precautionary_score(self, api, build):
        """PRD §3.11: "`odor_risk_score_precautionary` is the sum of severity weights over the substantiated set **plus** every complaint whose `status` is `RECEIVED` or `INVESTIGATING`, again within the window, multiplied by 4.0, multiplied by 1.5 when the site's `pfas_advisory_flag` is true and by 1.0 otherwise, clamped by the same minimum against 100.0, and rounded to 2 decimal places."

        Three open SEVERE complaints weigh 21 for a precautionary score of 84.00; the
        fourth takes the weight to 28 and the raw product to 112.00, which the minimum
        against 100.0 clamps to exactly 100.00. The site sits 1200 feet from the nearest
        dwelling so the precautionary variant is the gating score, while the historical
        variant stays 0.00 because nothing has been substantiated.

        Design: Corner/calculations/calc_odor_risk_score_clamps_at_one_hundred
        """
        facility = build.facility()
        site = build.permitted_site(facility["id"], nearest_residence_ft=1200)

        for received_at in (
            "2026-07-20T13:00:00Z",
            "2026-07-25T13:00:00Z",
            "2026-07-30T13:00:00Z",
        ):
            build.complaint(
                facility["id"],
                site_id=site["id"],
                received_at=received_at,
                severity="SEVERE",
                description="Persistent odor at the fence line",
            )

        three_open = build.read_site(site["id"])
        assert_percent(three_open["odor_risk_score_precautionary"], 84.00)
        assert_percent(three_open["gating_risk_score"], 84.00)

        fourth = validate_success(
            api.create_complaint(
                F.complaint_payload(
                    facility["id"],
                    site_id=site["id"],
                    received_at="2026-07-31T13:00:00Z",
                    severity="SEVERE",
                    description="Persistent odor at the fence line",
                ),
                LIAISON_HEADERS,
            ),
            201,
        )
        assert fourth["status"] == C.COMPLAINT_RECEIVED

        clamped = build.read_site(site["id"])
        assert_percent(clamped["odor_risk_score_precautionary"], 100.00)
        assert_percent(clamped["odor_risk_score_historical"], 0.00)
        assert_percent(clamped["gating_risk_score"], 100.00)
        assert clamped["status"] == C.SITE_PERMITTED

        current_facility = build.read_facility(facility["id"])
        assert current_facility["substantiated_complaint_count_30d"] == 0
        assert current_facility["posture"] == C.POSTURE_OPEN
