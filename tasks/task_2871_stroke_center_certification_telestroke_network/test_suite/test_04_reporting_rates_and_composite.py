"""Report rate variants, the nested dtn-excess rounding and the composite certification score."""
from test_helpers import assertions as a
from test_helpers import fixtures as fx

PERIOD_START = "2026-09-01T00:00:00Z"
PERIOD_END = "2026-10-01T00:00:00Z"


def _mixed_pool_report():
    """One treated case with a FINALIZED row and one transfer-only case whose row stays DRAFT."""
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    treated = fx.setup_reportable_case(context, door_at, dtn_minutes=50, dti_minutes=20)
    shipped = fx.setup_accepted_transfer(
        context, "2026-09-01T09:10:00Z", mode="TRANSFER_ONLY", dti_minutes=20
    )
    draft_row = fx.create_abstraction(shipped["case"]["id"], "STK_DTN_60")
    fx.complete_handoff(
        shipped["transfer"]["id"], mode="TRANSFER_ONLY", at="2026-09-01T09:50:00Z"
    )
    shipped_case = fx.read_case(shipped["case"]["id"])
    assert shipped_case["status"] == "CLOSED"
    assert shipped_case["disposition"] == "TRANSFER_ONLY"
    assert shipped_case["door_to_needle_minutes"] is None
    report = fx.create_report(
        context["spoke"]["id"], PERIOD_START, PERIOD_END, at="2026-09-01T12:00:00Z"
    )
    return {
        "context": context, "report": report,
        "finalized_row": treated["abstractions"]["STK_DTN_60"],
        "draft_row": draft_row,
    }


def test_draft_report_pools_the_draft_row_and_reads_a_fifty_percent_rate():
    """The PROVISIONAL pool admits DRAFT rows and counts an excluded row in the denominator.

    PRD 3.9: "under the `PROVISIONAL` variant, those whose `status` is `DRAFT` or `FINALIZED`; under the `CERTIFIED` variant, only those whose `status` is `FINALIZED`"
    PRD 3.9: "A draft abstraction on a transfer-only case therefore reports `exclusion_reason` `TRANSFER_ONLY` while still counting itself in the denominator"
    PRD 2.8: "A report's `included_abstraction_count` is the number of abstractions whose `report_id` names it and whose `status` is `FINALIZED`"

    Design: Difficulty/dual_variant_calc/measure_compliance_rate_provisional_and_certified_diverge_on_draft_pool
    """
    scenario = _mixed_pool_report()
    report = scenario["report"]

    assert report["rate_variant"] == "PROVISIONAL", (
        f"a DRAFT report carries the provisional variant, got {report['rate_variant']}"
    )
    assert report["included_abstraction_count"] == 1, (
        "the count is the attached rows whose status is FINALIZED, so only the "
        f"finalised row counts, got {report['included_abstraction_count']}"
    )
    assert report["dtn_60_compliance_pct"] == 50.00, (
        "one numerator over a denominator of two, got "
        f"{report['dtn_60_compliance_pct']}"
    )
    a.assert_two_decimal_places(report["dtn_60_compliance_pct"], "dtn_60_compliance_pct")
    assert report["closed_case_count_in_period"] == 2
    assert report["composite_certification_score"] == 0.00, (
        "the composite is produced at submission and nowhere else, got "
        f"{report['composite_certification_score']}"
    )

    draft_row = fx.read_abstraction(scenario["draft_row"]["id"])
    assert draft_row["report_id"] == report["id"], "the draft row attached to the new report"
    assert draft_row["status"] == "DRAFT"
    assert draft_row["variant"] == "PROVISIONAL"
    assert draft_row["exclusion_reason"] == "TRANSFER_ONLY", (
        f"the shipped-unlysed case records its exclusion, got {draft_row['exclusion_reason']}"
    )
    assert draft_row["denominator_included"] is True, (
        "the provisional variant records the exclusion without applying it"
    )
    assert draft_row["numerator_flag"] is False, "a null needle time cannot score the numerator"

    finalized_row = fx.read_abstraction(scenario["finalized_row"]["id"])
    assert finalized_row["variant"] == "CERTIFIED"
    assert finalized_row["denominator_included"] is True
    assert finalized_row["numerator_flag"] is True


def test_submission_detaches_the_draft_row_and_lifts_the_rate_to_one_hundred():
    """The variant switch drops the unattested row from both the pool and the count.

    PRD 3.9: "It first re-gathers: every attached abstraction still in `DRAFT` is detached with `report_id` cleared to null, every `FINALIZED` abstraction on an in-period closed case is attached, and `included_abstraction_count` is recomputed."
    PRD 3.9: "Then `rate_variant` becomes `CERTIFIED` and the three rates are recomputed under that variant"

    Design: Difficulty/dual_variant_calc/measure_compliance_rate_provisional_and_certified_diverge_on_draft_pool
    """
    scenario = _mixed_pool_report()
    provisional_rate = scenario["report"]["dtn_60_compliance_pct"]

    submitted = fx.submit_report(scenario["report"]["id"], at="2026-09-01T13:00:00Z")

    assert submitted["status"] == "SUBMITTED"
    assert submitted["rate_variant"] == "CERTIFIED", (
        f"submission switches the variant, got {submitted['rate_variant']}"
    )
    assert submitted["included_abstraction_count"] == 1, (
        f"only the finalized row survives the re-gather, got {submitted['included_abstraction_count']}"
    )
    assert submitted["dtn_60_compliance_pct"] == 100.00, (
        "one numerator over a denominator of one, got "
        f"{submitted['dtn_60_compliance_pct']}"
    )
    assert submitted["dtn_60_compliance_pct"] - provisional_rate == 50.00, (
        "the variant switch moves the rate by exactly fifty points"
    )
    assert submitted["closed_case_count_in_period"] == 2, (
        "the closed-case volume is a property of the period, not of the pool"
    )
    assert submitted["mean_dtn_excess_pct"] == 0.00, (
        "the one measured needle is inside target, got "
        f"{submitted['mean_dtn_excess_pct']}"
    )

    detached = fx.read_abstraction(scenario["draft_row"]["id"])
    assert detached["report_id"] is None, "submission detaches the draft row"
    assert detached["status"] == "DRAFT", "submission detaches, it does not finalize"
    assert detached["exclusion_reason"] == "TRANSFER_ONLY"
    assert detached["denominator_included"] is True, (
        "the detached row is still on its own provisional variant"
    )


def _dtn_excess_report():
    scenario = fx.setup_report_scenario(
        cases=[
            {"door_at": "2026-09-01T08:00:00Z", "dtn_minutes": 70, "dti_minutes": 20},
            {"door_at": "2026-09-01T09:30:00Z", "dtn_minutes": 50, "dti_minutes": 20},
        ],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )
    return scenario


def test_each_case_excess_is_rounded_to_a_whole_percent_before_the_mean():
    """Seventy minutes rounds to a 17 percent excess and averages with a zero to 8.50.

    PRD 3.9: "Two cases at 70 and 50 minutes yield 17 and 0, and a mean of 8.50."

    Design: Difficulty/combinatorial_formula/dtn_excess_rounds_each_case_to_a_whole_percent_before_the_mean
    """
    scenario = _dtn_excess_report()
    report = scenario["report"]
    late, ontime = scenario["cases"]

    assert late["case"]["door_to_needle_minutes"] == 70
    assert ontime["case"]["door_to_needle_minutes"] == 50

    assert report["mean_dtn_excess_pct"] == 8.50, (
        "17 and 0 average to 8.50 once each case is rounded first, got "
        f"{report['mean_dtn_excess_pct']}"
    )
    assert report["mean_dtn_excess_pct"] != 8.33, (
        "pooling the raw excess minutes and rounding once at the end is the forbidden order"
    )
    a.assert_two_decimal_places(report["mean_dtn_excess_pct"], "mean_dtn_excess_pct")
    assert report["dtn_60_compliance_pct"] == 50.00, (
        f"one of the two needles is inside target, got {report['dtn_60_compliance_pct']}"
    )
    assert report["included_abstraction_count"] == 2
    assert report["closed_case_count_in_period"] == 2
    assert report["substantiated_major_count"] == 0, (
        "the system-detected deviation is only OPEN, so it never enters the penalty"
    )
    assert late["case"]["deviation_count"] == 1, "the late needle opened one deviation"
    assert ontime["case"]["deviation_count"] == 0


def test_certified_recomputation_reruns_the_same_pinned_excess_order():
    """Submission recomputes the excess over the finalized population and lands on 8.50 again.

    PRD 3.9: "Then average those whole percents and round the average to two decimals half up."

    Design: Difficulty/combinatorial_formula/dtn_excess_rounds_each_case_to_a_whole_percent_before_the_mean
    """
    scenario = _dtn_excess_report()

    submitted = fx.submit_report(scenario["report"]["id"])

    assert submitted["rate_variant"] == "CERTIFIED"
    assert submitted["mean_dtn_excess_pct"] == 8.50, (
        "the certified recomputation reruns the same per-case-first order, got "
        f"{submitted['mean_dtn_excess_pct']}"
    )
    assert submitted["mean_dtn_excess_pct"] != 8.34, (
        "rounding each per-case excess to two decimals first is the forbidden order"
    )
    assert submitted["dtn_60_compliance_pct"] == 50.00, (
        "both rows were already finalized, so the variant switch changes no rate"
    )
    assert submitted["included_abstraction_count"] == 2


def _composite_report(*, submit=False, decide=False):
    measures = ("STK_DTN_60", "STK_DTI_45", "STK_TELESTROKE_RESPONSE")
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    fast = fx.setup_reportable_case(
        context, door_at, dtn_minutes=50, dti_minutes=20,
        accept_after_seconds=180, measures=measures,
    )
    slow = fx.setup_reportable_case(
        context, "2026-09-01T09:10:00Z", dtn_minutes=55, dti_minutes=20,
        accept_after_seconds=420, measures=measures,
    )
    assert fast["consult"]["response_latency_seconds"] == 180
    assert slow["consult"]["response_latency_seconds"] == 420
    fx.substantiate_deviation(slow["case"]["id"], severity="MAJOR")
    report = fx.create_report(
        context["spoke"]["id"], PERIOD_START, PERIOD_END, at="2026-09-01T12:00:00Z"
    )
    if submit:
        report = fx.submit_report(report["id"], at="2026-09-01T12:30:00Z")
    if decide:
        report = fx.decide_report(report["id"], at="2026-09-01T13:00:00Z")
    return {"context": context, "report": report, "cases": [fast, slow]}


def test_composite_multiplies_the_penalised_base_by_the_spoke_tier_multiplier():
    """87.5 of weighted base less 8.0 of penalty, times 0.95, rounded once, is 75.53.

    PRD 3.9: "The raw figure is the base minus the penalty plus the credit, all multiplied by the tier multiplier; the multiplier applies to the whole bracket, not to the base alone."
    PRD 3.9: "8.0 for each substantiated `MAJOR` deviation plus 18.0 for each substantiated `SENTINEL` one, capped at 24.0 in total."

    Design: Difficulty/combinatorial_formula/composite_certification_score_couples_three_rates_penalty_and_tier_multiplier
    """
    draft = _composite_report()
    assert draft["report"]["composite_certification_score"] == 0.00, (
        "a DRAFT report carries no composite yet"
    )
    assert draft["report"]["substantiated_major_count"] == 1, (
        "the penalty input is already in place while the report is DRAFT"
    )

    submitted = fx.submit_report(draft["report"]["id"], at="2026-09-01T12:30:00Z")

    assert submitted["dtn_60_compliance_pct"] == 100.00, (
        f"needles at 50 and 55 minutes both count, got {submitted['dtn_60_compliance_pct']}"
    )
    assert submitted["dti_45_compliance_pct"] == 100.00
    assert submitted["telestroke_response_compliance_pct"] == 50.00, (
        "a 180-second answer counts and a 420-second one does not, got "
        f"{submitted['telestroke_response_compliance_pct']}"
    )
    assert submitted["included_abstraction_count"] == 6, (
        f"six finalized rows are attached, got {submitted['included_abstraction_count']}"
    )
    assert submitted["substantiated_major_count"] == 1
    assert submitted["substantiated_sentinel_count"] == 0
    assert submitted["composite_certification_score"] == 75.53, (
        "(87.5 - 8.0) * 0.95 is 75.525 and rounds half up once at the end, got "
        f"{submitted['composite_certification_score']}"
    )
    assert submitted["composite_certification_score"] != 75.13, (
        "multiplying the base before subtracting the penalty is the forbidden order"
    )
    assert submitted["composite_certification_score"] != 75.52, (
        "the final figure rounds half up rather than truncating"
    )
    a.assert_two_decimal_places(
        submitted["composite_certification_score"], "composite_certification_score"
    )
    assert submitted["mean_dtn_excess_pct"] == 0.00
    assert submitted["rate_variant"] == "CERTIFIED"
    assert submitted["closed_case_count_in_period"] == 2


def test_a_seventy_five_point_five_three_composite_lands_conditional_and_reaches_the_facility():
    """The reviewer re-reads the stored composite and the acceptance flows into the centre.

    PRD 3.9: "`CERTIFIED` at 85.00 or above, `CONDITIONAL` from 70.00 up to but not including 85.00, and `DENIED` below 70.00"
    PRD 3.9: "Acceptance flows straight into the facility: its `certification_status` is set from the `decision`"

    Design: Difficulty/combinatorial_formula/composite_certification_score_couples_three_rates_penalty_and_tier_multiplier
    """
    scenario = _composite_report(submit=True, decide=True)
    report = scenario["report"]

    assert report["composite_certification_score"] == 75.53, (
        "the decision judges whatever the submission produced, got "
        f"{report['composite_certification_score']}"
    )
    assert report["decision"] == "CONDITIONAL", (
        f"75.53 sits between 70.00 and 85.00, got {report['decision']}"
    )
    assert report["status"] == "ACCEPTED", (
        f"a conditional decision accepts the report, got {report['status']}"
    )
    assert report["decided_at"] == "2026-09-01T13:00:00Z"

    center = fx.read_center(scenario["context"]["spoke"]["id"])
    assert center["certification_status"] == "CONDITIONAL", (
        f"the facility takes its status from the decision, got {center['certification_status']}"
    )
    assert center["consecutive_denied_report_count"] == 0
    assert center["suspension_reason"] is None
    assert center["ems_routing_posture"] == "DIVERT_ADVISORY", (
        "a conditional facility acquires a standing divert advisory, got "
        f"{center['ems_routing_posture']}"
    )
    assert center["public_dtn_compliance_pct"] is None, (
        "the public figure is only refreshed at publication"
    )
