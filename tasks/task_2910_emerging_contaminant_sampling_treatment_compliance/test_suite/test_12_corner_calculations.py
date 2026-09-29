"""Derived quantities: thresholds, rate tables, input sets and waterfalls.

Nothing in this section is a state transition for its own sake. Each test drives
one arithmetic rule to a value that only that rule produces, so a formula that
looks right but reads the wrong input, rounds at the wrong point or fills the
buckets in the wrong order cannot survive it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_INSUFFICIENT_MONITORING_HISTORY
from test_helpers.assertions import (
    assert_allocation_buckets,
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_instant_equals,
    assert_is_null,
    assert_money_cents,
    assert_rate_ladder,
    assert_status,
    assert_total_count,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.fixtures import (
    accept_result,
    accepted_quarters,
    build_registry,
    classify_manifest,
    completed_gac_pilot,
    completed_ix_pilot,
    draft_determination,
    filed_claim,
    issued_violation,
    open_evaluation,
    raise_manifest,
    read_entry_point,
    read_evaluation,
    read_lab_result,
    read_pilot,
    read_project,
    read_sample,
    received_sample,
    register_entry_point,
    reject_result,
    selected_project,
    ship_manifest,
    submit_result,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, FINANCE_OFFICER_HEADERS


def test_the_two_leachate_thresholds_are_inclusive_lower_bounds(api):
    """Four sibling manifests off one run pin both thresholds and their neighbours.

    The 800 kg of spent carbon is split into four 100 kg manifests and each is
    classified at a reading a hundredth of a nanogram apart from a threshold:
    500.0 is hazardous while 499.99 is only special waste, and 50.00 is special
    waste while 49.99 is merely non-hazardous solid. Classification alone prices
    nothing, so all four still carry a null disposal cost, and the pilot's ledger
    reads 400.00 kg unmanifested against the 800.00 kg it spent.

    PRD: "The `waste_classification` follows two inclusive thresholds read from
    the top: `HAZARDOUS` when the reading is at or above 500.0 nanograms per
    litre, `SPECIAL_WASTE` when it is at or above 50.0, and
    `NON_HAZARDOUS_SOLID` otherwise. A reading of exactly 500.0 is hazardous and
    a reading of exactly 50.0 is special waste; both boundaries belong to the
    more severe class."

    Design: Corner/calculations/waste_classification_thresholds_are_inclusive_lower_bounds
    """
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=500000)
    pilot = completed_gac_pilot(api, evaluation["id"])
    manifests = [
        raise_manifest(api, pilot["id"], media_type="GAC_CARBON", mass_kg=100.00)
        for _ in range(4)
    ]

    classified = [
        classify_manifest(api, manifest["id"], leachate)
        for manifest, leachate in zip(manifests, (500.0, 499.99, 50.00, 49.99))
    ]

    expected = ["HAZARDOUS", "SPECIAL_WASTE", "SPECIAL_WASTE", "NON_HAZARDOUS_SOLID"]
    for manifest, classification in zip(classified, expected):
        assert_status(manifest, "CLASSIFIED")
        assert_equals(manifest, "waste_classification", classification)
        assert_is_null(manifest, "disposal_cost_cents", "disposal_method")

    stored = read_pilot(api, pilot["id"])
    assert_decimal(stored["spent_media_kg"], 800.00, label="spent_media_kg")
    assert_decimal(stored["unmanifested_media_kg"], 400.00, label="unmanifested_media_kg")
    assert_decimal(stored["removal_pct"], 96.30, label="removal_pct")


def test_the_disposal_rate_is_looked_up_by_route_not_by_classification(api):
    """Special waste hauled to reactivation is priced from the route's own rate.

    Three hundred kilograms of exhausted resin classified as special waste at a
    leachate of 60.00 is shipped for reactivation at 95 cents a kilogram, so the
    disposal cost is exactly 28500 cents and precisely that integer lands in the
    evaluation's residuals ledger against its 500000-cent budget. The pilot's
    media ledger is emptied in the same movement.

    PRD: "The `disposal_cost_cents` is then the manifest's `mass_kg` multiplied
    by the route's per-kilogram rate — 12 cents for `LANDFILL`, 95 cents for
    `REACTIVATION`, 340 cents for `INCINERATION_1100C` and 210 cents for
    `DEEP_WELL` — rounded half-up to whole cents."

    Design: Corner/calculations/disposal_cost_uses_the_per_method_rate_from_the_constants_table
    """
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=500000)
    pilot = completed_ix_pilot(api, evaluation["id"])
    manifest = raise_manifest(api, pilot["id"], media_type="IX_RESIN", mass_kg=300.00)
    classify_manifest(api, manifest["id"], 60.00)

    shipped = ship_manifest(api, manifest["id"], "REACTIVATION", carrier_ref="HAULER-4417")

    assert_status(shipped, "SHIPPED")
    assert_equals(shipped, "waste_classification", "SPECIAL_WASTE")
    assert_equals(shipped, "disposal_method", "REACTIVATION")
    assert_money_cents(shipped["disposal_cost_cents"], 28500, "disposal_cost_cents")

    parent = read_evaluation(api, evaluation["id"])
    assert_money_cents(parent["residuals_spent_cents"], 28500, "residuals_spent_cents")
    assert_money_cents(parent["residuals_budget_cents"], 500000, "residuals_budget_cents")

    stored = read_pilot(api, pilot["id"])
    assert_decimal(stored["unmanifested_media_kg"], 0.00, label="unmanifested_media_kg")
    assert_decimal(stored["removal_pct"], 92.00, label="removal_pct")


def test_the_running_average_ignores_unreviewed_and_rejected_quarters(api):
    """Three quarters exist on paper and only one of them is an input.

    A 2025Q4 reading of 9.00 was rejected and a 2026Q1 reading of 9.00 has never
    been reviewed, so neither is in `ACCEPTED` status and neither reaches the
    average; only the accepted 2026Q2 reading of 3.00 does. The frozen average is
    therefore 3.00 over a single quarter rather than 7.00 over three, and because
    just one quarter is on the record at an entry point now on quarterly
    monitoring the verdict is the monitoring failure rather than the trigger the
    concentration alone would have earned.

    PRD: "Its input set is every result in `ACCEPTED` status whose sample belongs
    to that entry point, whose `contaminant_id` is that contaminant, and whose
    sample has reached `ANALYZED` status."

    Design: Corner/calculations/lraa_ignores_submitted_and_rejected_results
    """
    registry = build_registry(api)
    rejected_sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        monitoring_period="2025Q4",
        preservative_lot="LOT-F1",
    )
    rejected = submit_result(
        api,
        registry["laboratory_id"],
        rejected_sample["id"],
        registry["contaminant_id"],
        reported_ng_per_l=9.00,
        analyzed_at="2025-11-19T08:00:00.000Z",
    )
    reject_result(api, rejected["id"], reject_reason_code="QC_FAILURE")
    unreviewed_sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        monitoring_period="2026Q1",
        preservative_lot="LOT-F2",
    )
    unreviewed = submit_result(
        api,
        registry["laboratory_id"],
        unreviewed_sample["id"],
        registry["contaminant_id"],
        reported_ng_per_l=9.00,
        analyzed_at="2026-02-18T08:00:00.000Z",
    )
    accepted_sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        monitoring_period="2026Q2",
        preservative_lot="LOT-F3",
    )
    accepted = submit_result(
        api,
        registry["laboratory_id"],
        accepted_sample["id"],
        registry["contaminant_id"],
        reported_ng_per_l=3.00,
        analyzed_at="2026-05-20T08:00:00.000Z",
    )
    accept_result(api, accepted["id"])

    determination = draft_determination(
        api, registry["entry_point_id"], registry["contaminant_id"], period_end="2026Q2"
    )

    assert_equals(determination, "quarters_used", 1)
    assert_decimal(determination["lraa_ng_per_l"], 3.00, label="lraa_ng_per_l")
    assert_decimal(
        determination["planning_lraa_ng_per_l"], 3.00, label="planning_lraa_ng_per_l"
    )
    assert_equals(determination, "determination", "MONITORING_VIOLATION")
    assert_equals(determination, "violation_type", "MONITORING_AND_REPORTING")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        posture="TRIGGERED",
        monitoring_status="QUARTERLY",
        accepted_result_count=1,
        max_compliance_ratio=0.7500,
    )
    assert_status(read_lab_result(api, rejected["id"]), "REJECTED")
    assert_status(read_lab_result(api, unreviewed["id"]), "SUBMITTED")
    assert_status(read_sample(api, unreviewed_sample["id"]), "RECEIVED")
    assert_status(read_sample(api, accepted_sample["id"]), "ANALYZED")


def test_an_acute_exceedance_overrides_the_contaminants_own_notification_tier(api):
    """Five times the limit at 45000 people escalates a TIER_2 compound to TIER_1.

    PFOA carries the default TIER_2 baseline, but a frozen average of 20.00 against
    a limit of 4.00 is five times the limit and the population is well over ten
    thousand, so the violation is acute and the auto-created notice takes the acute
    tier instead of the compound's own. The 24-hour TIER_1 deadline then falls a
    single day after the 2026-08-01 issuance rather than the 720 hours TIER_2 would
    have bought, and the notice itself is still an empty draft.

    PRD: "The auto-created notification carries the `determination_id`,
    `revision_count` of zero, empty `content_elements` and `delivery_methods`, and
    a `tier` chosen as follows: `TIER_1` when `violation_type` is `ACUTE`;
    `TIER_3` when `determination` is `MONITORING_VIOLATION`; and otherwise the
    contaminant's own `notification_tier`."

    Design: Corner/calculations/an_acute_violation_escalates_the_notification_to_tier_one
    """
    registry = build_registry(api)
    assert_equals(registry["contaminant"], "notification_tier", "TIER_2")

    violation = issued_violation(api, registry, reported_ng_per_l=20.00)

    determination = violation["determination"]
    assert_decimal(determination["lraa_ng_per_l"], 20.00, label="lraa_ng_per_l")
    assert_equals(determination, "determination", "MCL_VIOLATION")
    assert_equals(determination, "violation_type", "ACUTE")
    assert_instant_equals(determination["issued_at"], DEFAULT_CLOCK, label="issued_at")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        max_compliance_ratio=5.0000,
        open_violation_count=1,
    )

    assert_total_count(
        api.list_notifications(
            COMPLIANCE_OFFICER_HEADERS, params={"determination_id": determination["id"]}
        ),
        1,
    )
    notification = violation["notification"]
    assert_equals(notification, "tier", "TIER_1")
    assert_instant_equals(
        notification["required_by_at"], "2026-08-02T00:00:00.000Z", label="required_by_at"
    )
    assert_status(notification, "DRAFT")
    assert_equals(notification, "revision_count", 0)
    assert_equals(notification, "content_elements", [])


def test_a_quarter_exactly_at_the_trigger_level_truncates_the_qualifying_streak(api):
    """Four clean quarters earn a streak of three because one of them ties the trigger.

    The walk runs backwards from 2026Q2 and a period only qualifies when its
    compliance value is strictly below the 2.00 trigger, so the oldest quarter's
    reading of exactly 2.00 does not qualify and stops the prefix at three. The
    four-quarter average of 1.44 is comfortably compliant and the entry point sits
    at QUARTERLY with nothing pending, yet the reduction request fails the
    four-quarter history test on that single tie.

    PRD: "`consecutive_qualifying_quarters` is the length of the qualifying run at
    the front of that list: the walk stops at the first period that does not
    qualify, and older clean periods behind it do not count."

    Design: Corner/calculations/the_qualifying_quarter_streak_stops_at_a_value_equal_to_the_trigger_level
    """
    registry = build_registry(api)
    quarters = accepted_quarters(
        api,
        registry,
        [("2025Q3", 2.00), ("2025Q4", 1.90), ("2026Q1", 1.20), ("2026Q2", 1.85)],
        detection_limit_ng_per_l=1.80,
    )

    validate_error(
        api.request_monitoring_reduction(
            registry["entry_point_id"],
            f.reduction_request_payload(target_status="ANNUAL"),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_INSUFFICIENT_MONITORING_HISTORY,
        422,
    )

    stored = read_entry_point(api, registry["entry_point_id"])
    assert_entry_point_posture(
        stored,
        posture="COMPLIANT",
        monitoring_status="QUARTERLY",
        accepted_result_count=4,
        max_compliance_ratio=0.3600,
        consecutive_qualifying_quarters=3,
    )
    assert_is_null(stored, "requested_monitoring_status")

    censored = read_lab_result(api, quarters[2]["result_id"])
    assert_equals(censored, "censored", True)
    assert_decimal(censored["compliance_value_ng_per_l"], 0.00, label="compliance_value_ng_per_l")
    assert_decimal(censored["planning_value_ng_per_l"], 0.90, label="planning_value_ng_per_l")


def test_a_settlement_larger_than_three_ceilings_proves_the_waterfall_order(api):
    """Only the second bucket reaches the project, and only after the first is full.

    A 750000000-cent recovery is more than the first three ceilings can absorb, so
    it fills investigation at its 20000000-cent cost, capital at the project's
    whole 680000000-cent local share, the O&M reserve at a quarter of the
    31000000-cent annual cost, and drops the last 42250000 into rate
    stabilization. Only the capital bucket moves the project: its local share is
    extinguished, so nothing is borrowed, debt service vanishes and the annual
    requirement collapses to the operating cost alone — a 3.02 percent impact with
    no surcharge and a 144-cent monthly bill.

    PRD: "The recovery is then divided among four buckets, filled strictly in
    order, each taking the lesser of what remains and its own ceiling:
    `alloc_investigation_cents` takes the lesser of the remainder and the claim's
    `investigation_cost_cents`; `alloc_capital_cents` takes the lesser of the
    remainder and the project's `local_share_cents` as it stands immediately
    before this settlement is applied; `alloc_om_reserve_cents` takes the lesser
    of the remainder and 25.00 percent of the project's `annual_om_cost_cents`,
    that ceiling being rounded half-up to whole cents; and
    `alloc_rate_stabilization_cents` absorbs whatever remains, including zero."

    Design: Corner/calculations/cost_recovery_settlement_fills_the_four_buckets_strictly_in_order
    """
    entry_point = register_entry_point(api)
    selected = selected_project(api, entry_point["id"], residuals_budget_cents=500000)
    claim = filed_claim(
        api,
        entry_point["id"],
        selected["project_id"],
        claimed_cents=900000000,
        allocation_pct=60.00,
        investigation_cost_cents=20000000,
    )

    settled = validate_success(
        api.resolve_cost_recovery_claim(
            claim["id"], f.settle_claim_payload(750000000), FINANCE_OFFICER_HEADERS
        )
    )

    assert_status(settled, "SETTLED")
    assert_money_cents(settled["claim_basis_cents"], 420000000, "claim_basis_cents")
    assert_allocation_buckets(
        settled,
        investigation=20000000,
        capital=680000000,
        om_reserve=7750000,
        rate_stabilization=42250000,
        recovered=750000000,
    )

    project = read_project(api, selected["project_id"])
    assert_money_cents(project["recovered_cents"], 680000000, "recovered_cents")
    assert_rate_ladder(
        project,
        local_share_cents=0,
        borrowed_cents=0,
        annual_debt_service_cents=0,
        base_annual_requirement_cents=31000000,
        provisional_rate_impact_pct=3.02,
        surcharge_bp=0,
        final_annual_requirement_cents=31000000,
        rate_impact_pct=3.02,
        uniform_monthly_increase_cents=144,
        monthly_bill_increase_cents=144,
    )
