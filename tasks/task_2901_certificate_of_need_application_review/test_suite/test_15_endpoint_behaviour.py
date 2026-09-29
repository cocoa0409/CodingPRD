"""Endpoint-level behaviour: re-runs, supersession and a batch that spares a row."""

from test_helpers import (
    api_client,
    assert_four_decimal_value,
    get_success_data,
    validate_paginated,
)
from test_helpers.constants import (
    SCORE_ONE_SHEET,
    SHEET_REV_1,
    SHEET_REV_2,
)
from test_helpers.fixtures import (
    ADMIN,
    REVIEWER_USER_ID_1,
    file_progress_report,
    file_score_sheet,
    refresh_applicant,
    refresh_application,
    refresh_certificate,
    refresh_cycle,
    refresh_health_service_area,
    seed_comparative_review,
    seed_batching_cycle,
    seed_issued_certificate,
    set_clock,
)
from test_helpers.test_users import make_review_analyst_headers

SCORE_AFTER_REVISION = 79.25
PAST_MILESTONE_CLOCK = "2027-07-01T00:00:00Z"


class TestRecomputeNeedRepeatability:
    def test_a_second_recompute_reproduces_the_figures_and_only_bumps_the_version(self):
        """Value-idempotent but not version-idempotent: one bump per call.

        PRD §3.2: "Recomputing a cycle's need refreshes `pinned_formula_version` to
        the formula's current `version`, re-executes all five steps against current
        area inventory, and overwrites `unmet_bed_need_at_open` and
        `unallocated_bed_need` with the fresh results."
        PRD §3.2: "The cycle's `version` increases by 1."
        PRD §3.2: "Only two rows participate in this computation: the single
        planning area named by `hsa_id` and the single formula named by
        `formula_id`, both read as of the call."

        Design: Corner/endpoints/recompute_need_run_twice_without_an_amendment_reproduces_the_same_figures
        """
        world = seed_batching_cycle()
        assert world["cycle"]["version"] == 1

        first = get_success_data(
            api_client.recompute_need(world["cycle"]["id"], ADMIN)
        )
        assert first["unmet_bed_need_at_open"] == 19
        assert first["version"] == 2

        second = get_success_data(
            api_client.recompute_need(world["cycle"]["id"], ADMIN)
        )

        assert second["unmet_bed_need_at_open"] == 19
        assert second["pinned_formula_version"] == 1
        assert second["version"] == 3
        stored = refresh_cycle(world["cycle"]["id"])
        assert_four_decimal_value(stored["projected_patient_days"], 27375.0000)
        assert stored["required_beds_final"] == 89
        assert stored["unallocated_bed_need"] == 19


class TestScoreSheetRevision:
    def test_a_reviewers_second_sheet_supersedes_the_first_and_rescores(self):
        """The count stays at 1 because only the surviving ACTIVE sheet is a mean input.

        PRD §3.7: "When a reviewer files a second sheet on the same application, the
        reviewer's own earlier `ACTIVE` sheet on that application is set to
        `SUPERSEDED`, so exactly one `ACTIVE` sheet per reviewer per application
        survives."
        PRD §3.7: "Every submission — first or revised — recomputes the parent
        application's `comparative_score` and `score_sheet_count` and increases the
        application's `version` by 1."
        PRD §3.7: "First, the set of contributing sheets is fixed: only sheets on
        this application whose `status` is `ACTIVE` participate, and
        `score_sheet_count` is how many there are."
        PRD §3.7: "Sheets in `SUPERSEDED` or `STALE` are excluded from both the count
        and every mean."

        Design: Corner/endpoints/score_sheet_revision_supersedes_the_reviewers_previous_sheet_and_rescores
        """
        world = seed_comparative_review()
        first_sheet = file_score_sheet(
            world["application"], SHEET_REV_1, REVIEWER_USER_ID_1
        )
        before = refresh_application(world["application"]["id"])
        assert before["comparative_score"] == SCORE_ONE_SHEET
        assert before["score_sheet_count"] == 1

        revised = get_success_data(
            api_client.create_score_sheet(
                {
                    "application_id": before["id"],
                    **SHEET_REV_2,
                    "expected_application_version": before["version"],
                    "narrative": "Revised after site visit",
                },
                make_review_analyst_headers(REVIEWER_USER_ID_1),
            ),
            201,
        )

        assert revised["status"] == "ACTIVE"
        assert revised["reviewer_user_id"] == REVIEWER_USER_ID_1
        sheets, meta = validate_paginated(
            api_client.list_score_sheets(before["id"], ADMIN)
        )
        by_id = {sheet["id"]: sheet for sheet in sheets}
        assert meta["total_count"] == 2
        assert by_id[first_sheet["id"]]["status"] == "SUPERSEDED"
        assert by_id[revised["id"]]["status"] == "ACTIVE"

        after = refresh_application(before["id"])
        assert after["score_sheet_count"] == 1
        assert after["comparative_score"] == SCORE_AFTER_REVISION
        assert after["version"] == before["version"] + 1


class TestLapseSweepSelectivity:
    def test_a_certificate_that_met_its_required_completion_is_spared(self):
        """Evaluated but not lapsed: 30 percent clears the 25 percent bar.

        PRD §3.8: "The sweep takes no input and evaluates every certificate whose
        `lifecycle_status` is `ISSUED`."
        PRD §3.8: "A certificate lapses when its `implementation_milestone_date` is
        strictly earlier than the current date on the logical clock **and** its
        `latest_completion_pct` is strictly less than its
        `required_completion_pct_at_milestone`."
        PRD §3.8: "The sweep reports what it did as `evaluated_count`, the number of
        certificates it examined, `lapsed_count`, the number it lapsed, and
        `lapsed_certificate_ids`, the identifiers of those certificates."
        PRD §3.8: "And `latest_completion_pct` is taken as the
        `physical_completion_pct` of the contributing report with the greatest
        `period_end_date`, with the greatest `created_at` breaking a tie between two
        reports covering the same period end."

        Design: Corner/endpoints/lapse_sweep_spares_a_past_milestone_certificate_that_met_the_required_completion
        """
        world = seed_issued_certificate()
        certificate = world["certificate"]
        assert certificate["required_completion_pct_at_milestone"] == 25
        assert certificate["implementation_milestone_date"] == "2027-06-30"
        report = file_progress_report(
            certificate,
            world["applicant"],
            period_end_date="2027-06-30",
            disbursed_cents=400000000,
            obligated_cents=0,
            physical_completion_pct=30,
        )
        assert report["status"] == "ACCEPTED"
        assert refresh_certificate(certificate["id"])["latest_completion_pct"] == 30
        set_clock(PAST_MILESTONE_CLOCK)

        summary = get_success_data(api_client.run_lapse_sweep(ADMIN))

        assert summary["evaluated_count"] == 1
        assert summary["lapsed_count"] == 0
        assert summary["lapsed_certificate_ids"] == []
        spared = refresh_certificate(certificate["id"])
        assert spared["lifecycle_status"] == "ISSUED"
        assert spared["cumulative_expenditure_cash_cents"] == 400000000
        assert spared["expenditure_status"] == "WITHIN_LIMIT"
        hsa = refresh_health_service_area(world["hsa"]["id"])
        assert hsa["approved_unimplemented_beds"] == 12
        assert hsa["capital_authorization_committed_cents"] == 1000000000
        assert refresh_cycle(world["cycle"]["id"])["unallocated_bed_need"] == 7
        applicant = refresh_applicant(world["applicant"]["id"])
        assert applicant["compliance_strike_count"] == 0
        assert applicant["standing"] == "GOOD"
