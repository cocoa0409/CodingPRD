"""The reporting calendar, the retraction ledger and the hub suspension cascade."""
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import COORD

AUGUST = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
SEPTEMBER = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
INTERIOR = ("2026-09-15T00:00:00Z", "2026-10-15T00:00:00Z")
OCTOBER = ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")


def _reports_for(center_id):
    data, _meta = validate_paginated(
        api_client.list_certification_reports(COORD, {"center_id": center_id, "limit": 100, "offset": 0})
    )
    return [row for row in data if row["center_id"] == center_id]


def _calendar_center():
    context = fx.setup_network(clock="2026-10-05T00:00:00Z")
    return context["spoke"]["id"]


def test_period_beginning_at_an_existing_period_end_is_admitted_and_supersedes_the_draft():
    """Half-open intervals let September start exactly where August stopped.

    PRD 3.9: "Adjacency is explicitly allowed: a period beginning at exactly an existing period's `period_end` is accepted, because the existing period never included that instant."
    PRD 3.9: "Any existing `DRAFT` report for the same facility moves to `SUPERSEDED` with its `superseded_by_report_id` pointing at the new report"

    Design: Difficulty/resource_temporal_overlap/report_period_half_open_adjacency_admitted_and_interior_conflict_detected
    """
    center_id = _calendar_center()
    version_before = fx.read_center(center_id)["version"]

    august = fx.create_report(center_id, *AUGUST)
    assert august["status"] == "DRAFT"
    version_after_august = fx.read_center(center_id)["version"]
    assert version_after_august == version_before + 1, (
        "each successful create raises the facility version by exactly one"
    )

    september = fx.create_report(center_id, *SEPTEMBER)

    assert september["status"] == "DRAFT", (
        f"the adjacent period is accepted, got {september['status']}"
    )
    assert september["period_start"] == august["period_end"], (
        "September begins exactly where August stopped"
    )
    assert september["superseded_by_report_id"] is None
    assert fx.read_center(center_id)["version"] == version_after_august + 1

    august_after = fx.read_report(august["id"])
    assert august_after["status"] == "SUPERSEDED", (
        f"the earlier draft is superseded by the new report, got {august_after['status']}"
    )
    assert august_after["superseded_by_report_id"] == september["id"]


def test_interior_overlap_is_refused_while_the_far_side_adjacency_is_admitted():
    """A period cutting into a live one conflicts; one touching its end does not.

    PRD 3.9: "the interval must not intersect the interval of any existing report for the same facility whose `status` is not `SUPERSEDED` (`ERR_REPORT_PERIOD_OVERLAP`)"

    Design: Difficulty/resource_temporal_overlap/report_period_half_open_adjacency_admitted_and_interior_conflict_detected
    """
    center_id = _calendar_center()
    august = fx.create_report(center_id, *AUGUST)
    september = fx.create_report(center_id, *SEPTEMBER)
    assert fx.read_report(august["id"])["status"] == "SUPERSEDED"
    version_before = fx.read_center(center_id)["version"]

    response = api_client.create_certification_report(
        f.certification_report_payload(center_id, INTERIOR[0], INTERIOR[1], version_before), COORD
    )

    validate_error(response, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value, 409)
    assert fx.read_center(center_id)["version"] == version_before, (
        "the failed create does not bump the facility version"
    )
    assert len(_reports_for(center_id)) == 2, "no third report row was written"
    still_draft = fx.read_report(september["id"])
    assert still_draft["status"] == "DRAFT", (
        f"the live September report is untouched, got {still_draft['status']}"
    )
    assert still_draft["superseded_by_report_id"] is None

    october = fx.create_report(center_id, *OCTOBER)

    assert october["status"] == "DRAFT", (
        "touching September's period_end from the other side is admitted"
    )
    assert october["period_start"] == september["period_end"]
    assert fx.read_report(september["id"])["status"] == "SUPERSEDED"
    assert fx.read_report(september["id"])["superseded_by_report_id"] == october["id"]
    assert fx.read_center(center_id)["version"] == version_before + 1


LEDGER_FIELDS = (
    "included_abstraction_count",
    "dtn_60_compliance_pct",
    "dti_45_compliance_pct",
    "telestroke_response_compliance_pct",
    "mean_dtn_excess_pct",
    "closed_case_count_in_period",
    "substantiated_major_count",
    "rate_variant",
)


def _ledger(report_id):
    report = fx.read_report(report_id)
    return {field: report[field] for field in LEDGER_FIELDS}


def _perturbable_report():
    """A report attaching one finalized row, plus an open 70-minute case to perturb it with."""
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    closed = fx.setup_reportable_case(context, door_at, dtn_minutes=50, dti_minutes=10)
    open_case = fx.setup_treated_case(
        context, "2026-09-01T09:10:00Z", dtn_minutes=70, dti_minutes=10
    )
    assert open_case["case"]["status"] == "THROMBOLYSIS_ADMINISTERED"
    report = fx.create_report(
        context["spoke"]["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
        at="2026-09-01T10:30:00Z",
    )
    return {
        "context": context, "report": report,
        "finalized_row": closed["abstractions"]["STK_DTN_60"],
        "open_case": open_case["case"],
    }


def test_a_draft_row_on_a_still_open_case_attaches_and_perturbs_the_ledger():
    """The auto-attach moves the rate to 50.00 while the two control quantities hold still.

    PRD 3.9: "Its `report_id` is set to the id of the `DRAFT` certification report for the case's facility whose reporting period contains the case's `door_at`, when exactly one such report exists"
    PRD 2.8: "A report's `included_abstraction_count` is the number of abstractions whose `report_id` names it and whose `status` is `FINALIZED`"

    Design: Difficulty/compensating_invariant/abstraction_retraction_restores_report_ledger_without_drift
    """
    scenario = _perturbable_report()
    baseline = _ledger(scenario["report"]["id"])
    assert baseline["included_abstraction_count"] == 1, (
        "only the closed case's row was gathered, got "
        f"{baseline['included_abstraction_count']}"
    )
    assert baseline["dtn_60_compliance_pct"] == 100.00
    assert baseline["dti_45_compliance_pct"] == 0.00, (
        "an empty denominator reads 0.00 rather than 100.00"
    )
    assert baseline["telestroke_response_compliance_pct"] == 0.00
    assert baseline["closed_case_count_in_period"] == 1
    assert baseline["rate_variant"] == "PROVISIONAL"

    perturbing = fx.create_abstraction(scenario["open_case"]["id"], "STK_DTN_60")

    assert perturbing["report_id"] == scenario["report"]["id"], (
        "the new draft attaches to the single in-period draft report"
    )
    assert perturbing["status"] == "DRAFT"
    assert perturbing["variant"] == "PROVISIONAL"
    assert perturbing["numerator_flag"] is False, "a 70-minute needle misses the target"
    assert perturbing["denominator_included"] is True, (
        "the provisional variant counts the row regardless"
    )

    perturbed = _ledger(scenario["report"]["id"])
    assert perturbed["included_abstraction_count"] == 1, (
        "the count tallies only the attached FINALIZED rows, so a DRAFT attachment "
        f"leaves it alone, got {perturbed['included_abstraction_count']}"
    )
    assert perturbed["dtn_60_compliance_pct"] == 50.00, (
        f"one numerator over a denominator of two, got {perturbed['dtn_60_compliance_pct']}"
    )
    assert perturbed["mean_dtn_excess_pct"] == baseline["mean_dtn_excess_pct"] == 0.00, (
        "the excess pool takes only finalized rows, so the open case contributes nothing"
    )
    assert perturbed["closed_case_count_in_period"] == 1, (
        "the closed-case control never moved"
    )


def test_retraction_restores_the_ledger_by_recomputation_and_frees_the_pair():
    """Every counter returns to its pre-attachment value and the measure can be re-opened.

    PRD 3.9: "every counter and rate the abstraction contributed to is restored to the value it would have had if the row had never existed"
    PRD 3.9: "Retraction also frees the case-and-measure pair, so a fresh abstraction for the same measure on the same case may then be created."

    Design: Difficulty/compensating_invariant/abstraction_retraction_restores_report_ledger_without_drift
    """
    scenario = _perturbable_report()
    report_id = scenario["report"]["id"]
    baseline = _ledger(report_id)
    perturbing = fx.create_abstraction(scenario["open_case"]["id"], "STK_DTN_60")
    assert _ledger(report_id)["dtn_60_compliance_pct"] == 50.00

    retracted = fx.retract_abstraction(perturbing["id"])

    assert retracted["status"] == "RETRACTED"
    assert retracted["report_id"] is None, "the retracted row detaches itself"

    restored = _ledger(report_id)
    assert restored == baseline, (
        f"the ledger must return bit for bit; baseline {baseline} restored {restored}"
    )
    assert restored["dtn_60_compliance_pct"] == 100.00, (
        "the rate is recomputed over the survivor, not left at 50.00 or reset to 0.00"
    )

    survivor = fx.read_abstraction(scenario["finalized_row"]["id"])
    assert survivor["status"] == "FINALIZED"
    assert survivor["report_id"] == report_id
    assert survivor["variant"] == "CERTIFIED"
    assert survivor["numerator_flag"] is True

    untouched = fx.read_case(scenario["open_case"]["id"])
    assert untouched["status"] == "THROMBOLYSIS_ADMINISTERED", (
        "the compensation does not reach the case"
    )
    assert untouched["door_to_needle_minutes"] == 70
    assert untouched["deviation_count"] == 1
    assert fx.list_case_deviations(untouched["id"])[0]["status"] == "OPEN"

    replacement = fx.create_abstraction(scenario["open_case"]["id"], "STK_DTN_60")
    assert replacement["report_id"] == report_id, "the freed pair may be abstracted again"
    reperturbed = _ledger(report_id)
    assert reperturbed["included_abstraction_count"] == 1, (
        "the replacement row is DRAFT, and the count tallies only attached FINALIZED "
        f"rows, got {reperturbed['included_abstraction_count']}"
    )
    assert reperturbed["dtn_60_compliance_pct"] == 50.00, (
        "the ledger is recomputed from the rows that exist, not from a remembered delta"
    )


def _suspended_hub():
    """A live IN_SESSION consult under an ACTIVE agreement whose hub is then suspended."""
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    case = fx.activate_case(context["spoke"]["id"], door_at)
    fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    consult = fx.request_consult(case["id"], context["agreement"]["id"], at="2026-09-01T08:12:00Z")
    fx.accept_consult(consult["id"], context["neurologist"]["id"], at="2026-09-01T08:15:00Z")
    pre = fx.read_neurologist(context["neurologist"]["id"])
    assert pre["on_call_state"] == "IN_CONSULT"
    assert pre["active_consult_count"] == 1
    fx.set_clock("2026-09-01T08:20:00Z")
    hub = fx.suspend_center(context["hub"]["id"], suspension_reason="certification body findings")
    return {"context": context, "case": case, "consult": consult, "hub": hub}


def test_hub_suspension_bypasses_the_hub_suspends_the_agreement_and_cancels_the_consult():
    """Three hops run outward from the hub without the request naming any of them.

    PRD 3.9: "The facility's `certification_status` becomes `SUSPENDED` with the reason recorded, and its `ems_routing_posture` becomes `BYPASS`."
    PRD 3.9: "Then every consult on those agreements whose `status` is `REQUESTED`, `ASSIGNED` or `IN_SESSION` moves to `CANCELLED` with a `cancellation_reason` of 'agreement suspended'."

    Design: Difficulty/transitive_cascade/center_suspension_cascades_agreement_consult_and_neurologist_release
    """
    scenario = _suspended_hub()
    context = scenario["context"]

    hub = fx.read_center(context["hub"]["id"])
    assert hub["certification_status"] == "SUSPENDED", (
        f"the suspended hub records its new status, got {hub['certification_status']}"
    )
    assert hub["suspension_reason"] == "certification body findings"
    assert hub["ems_routing_posture"] == "BYPASS", (
        f"a suspended facility goes on bypass, got {hub['ems_routing_posture']}"
    )

    agreement = fx.read_agreement(context["agreement"]["id"])
    assert agreement["status"] == "SUSPENDED", (
        f"an unservable hub suspends its coverage, got {agreement['status']}"
    )
    assert agreement["suspension_reason"] == "hub certification suspended", (
        f"the cascade stamps its own reason, got {agreement['suspension_reason']}"
    )

    consult = fx.read_consult(scenario["consult"]["id"])
    assert consult["status"] == "CANCELLED", (
        f"the live consult is cancelled by the suspended agreement, got {consult['status']}"
    )
    assert consult["cancellation_reason"] == "agreement suspended"
    assert consult["assigned_neurologist_id"] == context["neurologist"]["id"], (
        "a cancelled consult retains its assignee for audit"
    )
    assert consult["completed_at"] is None

    spoke = fx.read_center(context["spoke"]["id"])
    assert spoke["certification_status"] == "PROVISIONAL", (
        "the cascade follows the agreement, not the geography, got "
        f"{spoke['certification_status']}"
    )
    assert spoke["ems_routing_posture"] == "ROUTINE", (
        "the untouched spoke keeps its own posture with one open case"
    )


def test_the_released_neurologist_takes_no_cooldown_and_the_case_records_the_deviation():
    """The fourth hop releases the roster and opens a major deviation on the stranded case.

    PRD 3.9: "each released neurologist has `active_consult_count` lowered and returns from `IN_CONSULT` to `ON_CALL` without any cooldown being started"
    PRD 3.9: "a system-detected `ProtocolDeviation` of type `CONSULT_UNFILLED` and severity `MAJOR` is opened against each affected case"

    Design: Difficulty/transitive_cascade/center_suspension_cascades_agreement_consult_and_neurologist_release
    """
    scenario = _suspended_hub()
    context = scenario["context"]

    neurologist = fx.read_neurologist(context["neurologist"]["id"])
    assert neurologist["on_call_state"] == "ON_CALL", (
        f"the released neurologist is routable again, got {neurologist['on_call_state']}"
    )
    assert neurologist["active_consult_count"] == 0
    assert neurologist["last_consult_completed_at"] is None, (
        "a cancellation is not work performed, so no cooldown is armed"
    )
    assert neurologist["completed_consult_count"] == 0, (
        f"the lifetime tally is untouched, got {neurologist['completed_consult_count']}"
    )
    assert fx.read_agreement(context["agreement"]["id"])["active_consult_count"] == 0

    deviations = fx.list_case_deviations(scenario["case"]["id"])
    assert len(deviations) == 1, f"exactly one deviation on the stranded case, got {len(deviations)}"
    a.assert_system_detected_deviation(deviations[0], "CONSULT_UNFILLED", "MAJOR")
    assert deviations[0]["opened_by_user_id"] == "system"
    assert deviations[0]["status"] == "OPEN"

    case = fx.read_case(scenario["case"]["id"])
    assert case["deviation_count"] == 1
    assert case["status"] == "CONSULT_IN_PROGRESS", (
        f"the cascade stops at the consult and does not close the case, got {case['status']}"
    )
    assert case["disposition"] == "PENDING"
