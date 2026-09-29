"""Derived figures read from their declared input sets: the two contractor-budget bases,
the live-ops envelope, the ship-date fixed point, the rights ratio and the readiness
rounding."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CONTRACTOR_BUDGET_EXCEEDED,
    ERR_LIVE_OPS_CAP_EXCEEDED,
    ERR_POST_LAUNCH_NOT_ACTIVE,
)
from test_helpers.assertions import (
    assert_budget_summary,
    assert_fields_equal,
    assert_ledger,
    assert_pct_equals,
    assert_ratio_equals,
    assert_two_decimal_places,
)
from test_helpers.api_client import original_data
from test_helpers.constants import ALPHA_PASSING_METRICS
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    approve_invoice,
    create_engagement,
    read_agreement,
    read_milestone,
    record_accepted_review,
    setup_aurora_drift,
    setup_single_alpha,
    setup_single_gold,
    submit_build,
    submit_invoice,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

GOLD_EXACT_METRICS = {
    "feature_completeness_pct": 100.00,
    "crash_free_sessions_pct": 99.50,
    "content_completeness_pct": 100.00,
    "known_blocker_count": 0,
}


def _shipped_sunset_cut(api):
    """Sunset Cut driven to COMPLETED, which is what turns live-ops funding on."""
    scenario = setup_single_gold(api, title="Sunset Cut", advance_total_cents=3000000,
                                live_ops_quarterly_funding_cents=400000)
    build = submit_build(scenario.reg, scenario.m1["id"], 1, GOLD_EXACT_METRICS)
    record_accepted_review(scenario.reg, build["id"], end_hour=15)
    assert scenario.read_agreement()["post_launch_support_state"] == "ACTIVE"
    return scenario


def test_the_live_ops_envelope_caps_one_draw_and_the_four_quarter_total(api):
    """PRD §3.9: "Two caps then apply, and both report `ERR_LIVE_OPS_CAP_EXCEEDED`: a
    single draw may not exceed `live_ops_quarterly_funding_cents`, and the agreement's
    `live_ops_drawn_cents` plus this draw may not exceed the total envelope, which is
    `live_ops_quarterly_funding_cents` multiplied by the four quarters of post-launch
    support the agreement funds." And: "the moment `live_ops_drawn_cents` equals the
    four-quarter total exactly, `post_launch_support_state` flips to `EXPIRED` and no
    further draw will ever succeed."

    Design: Corner/calculations/corner_live_ops_draw_allowance_caps_each_draw_and_the_four_quarter_total
    """
    scenario = _shipped_sunset_cut(api)
    reg = scenario.reg

    validate_error(
        api.create_live_ops_draw(
            scenario.agreement_id,
            f.live_ops_draw_payload(400001, "Over the quarterly cap by one cent"),
            reg.finance,
        ),
        ERR_LIVE_OPS_CAP_EXCEEDED, 422,
    )
    assert scenario.read_agreement()["live_ops_drawn_cents"] == 0

    for quarter, running in ((1, 400000), (2, 800000), (3, 1200000)):
        validate_success(
            api.create_live_ops_draw(
                scenario.agreement_id,
                f.live_ops_draw_payload(400000, f"Q{quarter} live ops"),
                reg.finance,
            )
        )
        assert_fields_equal(
            scenario.read_agreement(),
            {"live_ops_drawn_cents": running, "post_launch_support_state": "ACTIVE"},
            "agreement",
        )

    validate_success(
        api.create_live_ops_draw(
            scenario.agreement_id, f.live_ops_draw_payload(400000, "Q4 live ops"),
            reg.finance,
        )
    )
    assert_fields_equal(
        scenario.read_agreement(),
        {"live_ops_drawn_cents": 1600000, "post_launch_support_state": "EXPIRED"},
        "agreement",
    )

    validate_error(
        api.create_live_ops_draw(
            scenario.agreement_id,
            f.live_ops_draw_payload(100000, "One quarter too many"),
            reg.finance,
        ),
        ERR_POST_LAUNCH_NOT_ACTIVE, 409,
    )
    assert scenario.read_agreement()["live_ops_drawn_cents"] == 1600000


def test_the_two_budget_bases_read_different_input_sets(api):
    """PRD §3.8: "A milestone's committed basis is the sum of `committed_cents` over every
    engagement of that milestone whose `status` is `PROPOSED`, `ACTIVE`, `SUSPENDED` or
    `COMPLETED`" while "The complementary figure is the **incurred basis**: the sum of
    `amount_cents` over every invoice in `APPROVED` status whose engagement belongs to the
    milestone".

    Design: Corner/calculations/corner_budget_bases_filter_by_engagement_and_invoice_status
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=800000,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    engagement = create_engagement(reg, scenario.m1["id"], "ART-QUILL", 400000,
                                   "2026-08-05", "2026-09-05", "Concept art")
    good = submit_invoice(reg, engagement["id"], "QUILL-001", 150000, "2026-08-15")
    bad = submit_invoice(reg, engagement["id"], "QUILL-002", 90000, "2026-08-31")

    assert approve_invoice(reg, good["id"])["status"] == "APPROVED"
    assert validate_success(
        api.get_engagement(engagement["id"], reg.dev)
    )["approved_invoice_total_cents"] == 150000

    rejected = validate_success(
        api.decide_invoice(bad["id"], f.reject_invoice_payload("Outside the agreed scope"),
                           reg.finance)
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "Outside the agreed scope"
    assert validate_success(
        api.get_engagement(engagement["id"], reg.dev)
    )["approved_invoice_total_cents"] == 150000

    completed = validate_success(api.complete_engagement(engagement["id"], reg.dev))
    assert completed["status"] == "COMPLETED"

    assert_budget_summary(
        validate_success(api.get_budget_summary(scenario.m1["id"], reg.dev)),
        scenario.m1["id"], budget=800000, committed_basis=400000, incurred_basis=150000,
        available_committed=400000, overrun=0,
    )


def test_the_committed_basis_aggregates_across_every_live_engagement(api):
    """PRD §3.8: "Admission requires that basis plus the new engagement's
    `committed_cents` to be no greater than the milestone's `contractor_budget_cents`;
    exceeding it is `ERR_CONTRACTOR_BUDGET_EXCEEDED`."

    Design: Corner/calculations/corner_committed_basis_aggregates_across_engagements_and_blocks_the_collective_excess
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=800000,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    first = create_engagement(reg, scenario.m1["id"], "AUDIO-LARK", 300000,
                              "2026-08-05", "2026-09-05", "Adaptive music")
    second = create_engagement(reg, scenario.m1["id"], "ART-QUILL", 400000,
                               "2026-08-05", "2026-09-05", "Concept art")
    assert first["status"] == "ACTIVE" and second["status"] == "ACTIVE"

    validate_error(
        api.create_engagement(
            f.engagement_payload(scenario.m1["id"], "VFX-PRISM", 200000,
                                 "2026-08-05", "2026-09-05", "Particle FX"),
            reg.dev,
        ),
        ERR_CONTRACTOR_BUDGET_EXCEEDED, 422,
    )

    rows, meta = validate_paginated(
        api.list_engagements(reg.dev, {"milestone_id": scenario.m1["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}

    assert_budget_summary(
        validate_success(api.get_budget_summary(scenario.m1["id"], reg.dev)),
        scenario.m1["id"], budget=800000, committed_basis=700000, incurred_basis=0,
        available_committed=100000, overrun=0,
    )


def test_the_ship_date_is_a_fixed_point_over_every_approved_delta(api):
    """PRD §3.7: "take every change order of the agreement whose `state` is
    `APPROVED_UPLIFT` or `APPROVED_CUT`, process them in ascending `decided_at` order with
    ties broken by ascending `created_at`, and set `ship_date_current` to
    `ship_date_original` advanced by the sum of their `ship_date_delta_days` in whole
    calendar days. `schedule_slip_days` is then the difference in whole days between
    `ship_date_current` and `ship_date_original`".

    Design: Corner/calculations/corner_ship_date_propagates_the_sum_of_approved_change_order_deltas
    """
    scenario = setup_aurora_drift(api)
    reg = scenario.reg

    uplift = validate_success(
        api.create_change_order(
            f.change_order_payload(scenario.agreement_id, scenario.m1["id"],
                                   "FUNDING_UPLIFT", scenario.version(), "Extra biome",
                                   requested_amount_cents=500000,
                                   ship_date_delta_days=20),
            reg.dev,
        ),
        201,
    )
    decided = validate_success(
        api.decide_change_order(uplift["id"], f.approve_payload("Funded"), reg.finance)
    )
    assert decided["state"] == "APPROVED_UPLIFT"
    after_uplift = scenario.read_agreement()
    assert_fields_equal(after_uplift,
                        {"ship_date_current": "2027-04-20", "schedule_slip_days": 20},
                        "agreement")
    assert_ledger(after_uplift, funding_pool_cents=12500000,
                  uplift_funded_cents=500000, committed_cents=12500000)
    assert read_milestone(reg, scenario.m1["id"])["uplift_cents"] == 500000

    cut = validate_success(
        api.create_change_order(
            f.change_order_payload(scenario.agreement_id, scenario.m1["id"],
                                   "FEATURE_CUT", scenario.version(),
                                   "Drop the vehicle sandbox",
                                   requested_amount_cents=200000,
                                   ship_date_delta_days=10,
                                   content_threshold_relief_pct=5.00),
            reg.dev,
        ),
        201,
    )
    cut_decided = validate_success(
        api.decide_change_order(cut["id"], f.approve_payload("Scope trimmed"), reg.finance)
    )
    assert cut_decided["state"] == "APPROVED_CUT"

    final = scenario.read_agreement()
    assert_fields_equal(final,
                        {"ship_date_current": "2027-04-30", "schedule_slip_days": 30},
                        "agreement")
    assert_ledger(final, uplift_funded_cents=500000, funding_pool_cents=12500000,
                  committed_cents=12300000, available_funding_cents=200000)

    milestone = read_milestone(reg, scenario.m1["id"])
    assert milestone["uplift_cents"] == 300000
    assert_pct_equals(milestone["content_threshold_relief_pct"], 5.00,
                      "content_threshold_relief_pct")

    rows, meta = validate_paginated(
        api.list_change_orders(reg.finance, {"agreement_id": scenario.agreement_id})
    )
    assert meta["total_count"] == 2
    assert all(row["state"] != "SUPERSEDED" for row in rows)


def test_one_acceptance_of_three_milestones_reverts_the_rights(api):
    """PRD §3.9: "`accepted_milestone_ratio` is the count of the agreement's milestones
    whose `status` is `ACCEPTED` divided by the count of *all* milestones ever created for
    the agreement — every status, `CANCELLED` and `BREACHED` included — rounded half up to
    four decimal places". "A ratio strictly below 0.5000 sets `ip_reversion_state` to
    `REVERTED_TO_DEVELOPER` and `sequel_rights_holder` to `DEVELOPER`".

    Design: Corner/calculations/corner_ip_reversion_threshold_constants_score_a_one_of_three_acceptance_as_full_reversion
    """
    scenario = setup_aurora_drift(api)
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING_METRICS)
    record_accepted_review(reg, build["id"], end_hour=12)
    assert read_milestone(reg, scenario.m2["id"])["status"] == "IN_DEVELOPMENT"
    assert read_milestone(reg, scenario.m3["id"])["status"] == "DEFINED"

    terminated = validate_success(
        api.terminate_agreement(scenario.agreement_id, reg.finance,
                                {"reason": "Publisher restructuring"})
    )
    assert_ratio_equals(terminated["accepted_milestone_ratio"], 0.3333,
                        "accepted_milestone_ratio")
    assert_fields_equal(
        terminated,
        {"ip_reversion_state": "REVERTED_TO_DEVELOPER",
         "sequel_rights_holder": "DEVELOPER"},
        "agreement",
    )
    assert read_milestone(reg, scenario.m1["id"])["status"] == "ACCEPTED"
    assert read_milestone(reg, scenario.m2["id"])["status"] == "CANCELLED"
    assert read_milestone(reg, scenario.m3["id"])["status"] == "CANCELLED"
    assert_ledger(read_agreement(reg, scenario.agreement_id), committed_cents=3600000,
                  available_funding_cents=8400000)


def test_a_readiness_score_landing_on_a_half_cent_rounds_up(api):
    """PRD §3.4 weights the three figures "at 0.45", "at 0.35" and "at 0.20", "with the
    total of those three weighted terms rounded half up to two decimal places", and PRD
    §2.5 insists "Rounding is always half up, never banker's rounding and never
    truncation."

    Design: Corner/calculations/corner_readiness_score_rounds_half_up_at_the_third_decimal
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg

    response = api.create_build(
        f.build_payload(scenario.m1["id"], 2, 91.00, 96.50, 61.00, 4,
                        release_notes="Rounding probe"),
        reg.dev,
    )
    build = validate_success(response, 201)
    assert_pct_equals(build["readiness_score"], 86.93, "readiness_score")
    assert build["gate_state"] == "PASSED"
    assert read_milestone(reg, scenario.m1["id"])["status"] == "UNDER_REVIEW"
    assert_two_decimal_places(original_data(response)["readiness_score"],
                              "readiness_score")
