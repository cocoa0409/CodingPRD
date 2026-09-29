"""Requests that break two rules at once and must report the lower priority number.

A suspended entry point masks the sampling-kit protocol gates; a prohibited
disposal route masks the residuals budget.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DISPOSAL_METHOD_PROHIBITED,
    ERR_MONITORING_SUSPENDED,
    ERR_PROHIBITED_SAMPLING_MATERIAL,
    ERR_RESIDUALS_BUDGET_EXCEEDED,
)
from test_helpers.assertions import (
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_is_null,
    assert_money_cents,
    assert_status,
    assert_total_count,
)
from test_helpers.fixtures import (
    classify_manifest,
    complete_pilot,
    open_evaluation,
    raise_manifest,
    read_entry_point,
    read_evaluation,
    read_manifest,
    read_pilot,
    register_contaminant,
    register_entry_point,
    register_pilot,
    start_pilot,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    SAMPLING_TECHNICIAN_HEADERS,
    TREATMENT_ENGINEER_HEADERS,
    UTILITY_ADMIN_HEADERS,
)


def _suspended_entry_point_and_bad_kit(api):
    """A suspended entry point plus a collection body that also fails both kit gates."""
    contaminant = register_contaminant(api)
    entry_point = register_entry_point(api)
    validate_success(
        api.set_monitoring_status(
            entry_point["id"],
            f.monitoring_status_payload("SUSPEND", reason="Wellhead rehabilitation."),
            UTILITY_ADMIN_HEADERS,
        )
    )
    payload = f.sample_payload(
        entry_point["id"],
        [contaminant["id"]],
        monitoring_period="2026Q2",
        collected_at="2026-05-15T08:00:00.000Z",
        ptfe_free_kit=False,
        field_blank_included=False,
        preservative_lot="LOT-BAD",
    )
    return entry_point, payload


def test_a_suspended_entry_point_refuses_the_collection_before_inspecting_the_kit(api):
    """Three rules are broken and the priority-20 state rule is the one reported.

    The body declares a PTFE-bearing kit and no field blank, either of which is a
    business-safety refusal on its own, but the entry point's monitoring is
    SUSPENDED, so the state gate answers first and no sample row is created.

    PRD: "Both of these checks sit below the suspension gate, so a collection
    attempted at an entry point whose monitoring is `SUSPENDED` reports
    `ERR_MONITORING_SUSPENDED` rather than either protocol failure."

    Design: Difficulty/priority_pair_validation_conflict/suspended_monitoring_outranks_the_prohibited_sampling_kit_check
    """
    entry_point, payload = _suspended_entry_point_and_bad_kit(api)

    validate_error(
        api.create_sample(payload, SAMPLING_TECHNICIAN_HEADERS), ERR_MONITORING_SUSPENDED, 422
    )

    assert_total_count(
        api.list_samples(COMPLIANCE_OFFICER_HEADERS, params={"entry_point_id": entry_point["id"]}),
        0,
    )
    after = read_entry_point(api, entry_point["id"])
    assert_equals(after, "monitoring_status", "SUSPENDED")
    assert_entry_point_posture(after, accepted_result_count=0)


def test_resuming_monitoring_uncovers_the_masked_sampling_material_refusal(api):
    """With the suspension lifted the identical body reports the priority-60 rule.

    Resuming monitoring removes the state gate, and the same collection attempt —
    still declaring a kit with fluoropolymer wetted parts — is now refused as a
    contamination-protocol breach, which proves the suspension was masking it.

    PRD: "`ptfe_free_kit` asserts that no wetted part of the collection kit
    contained PTFE or any other fluoropolymer; a false value is a
    contamination-protocol breach and the collection is refused outright with
    `ERR_PROHIBITED_SAMPLING_MATERIAL`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_monitoring_outranks_the_prohibited_sampling_kit_check
    """
    entry_point, payload = _suspended_entry_point_and_bad_kit(api)
    validate_error(
        api.create_sample(payload, SAMPLING_TECHNICIAN_HEADERS), ERR_MONITORING_SUSPENDED, 422
    )

    resumed = validate_success(
        api.set_monitoring_status(
            entry_point["id"], f.monitoring_status_payload("RESUME"), UTILITY_ADMIN_HEADERS
        )
    )
    assert_equals(resumed, "monitoring_status", "QUARTERLY")

    validate_error(
        api.create_sample(payload, SAMPLING_TECHNICIAN_HEADERS),
        ERR_PROHIBITED_SAMPLING_MATERIAL,
        422,
    )
    assert_total_count(
        api.list_samples(COMPLIANCE_OFFICER_HEADERS, params={"entry_point_id": entry_point["id"]}),
        0,
    )


def _hazardous_manifest_on_a_zero_budget(api):
    """800 kg of hazardous carbon against a residuals budget of nothing."""
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=0)
    pilot = register_pilot(api, f.gac_pilot_payload(evaluation["id"]))
    start_pilot(api, pilot["id"])
    complete_pilot(
        api,
        pilot["id"],
        influent_ng_per_l=50.00,
        effluent_ng_per_l=1.85,
        bed_volumes_treated=25000.00,
        spent_media_kg=800.00,
    )
    manifest = raise_manifest(api, pilot["id"], media_type="GAC_CARBON", mass_kg=800.00)
    classified = classify_manifest(api, manifest["id"], 500.0)
    return evaluation, pilot, classified


def test_a_hazardous_manifest_routed_to_landfill_is_refused_on_the_route(api):
    """The cheap illegal route is never reported as a budget problem.

    Landfilling 800 kg of hazardous carbon would cost 9600 cents against a budget
    of zero, so both the route rule and the fiscal rule are broken; the
    priority-62 route refusal is the one returned and the manifest stays
    CLASSIFIED with no route, cost or carrier recorded.

    PRD: "Note the ordering: a hazardous manifest routed to landfill is refused
    as a prohibited route even when the landfill price would have fit a budget
    that the lawful incineration price would blow, so the cheap illegal option is
    never reported as a budget problem."

    Design: Difficulty/priority_pair_validation_conflict/prohibited_disposal_route_outranks_the_exhausted_residuals_budget
    """
    evaluation, pilot, classified = _hazardous_manifest_on_a_zero_budget(api)
    assert_equals(classified, "waste_classification", "HAZARDOUS")

    validate_error(
        api.ship_residuals_manifest(
            classified["id"],
            f.ship_manifest_payload("LANDFILL", carrier_ref="HAUL-0001"),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_DISPOSAL_METHOD_PROHIBITED,
        422,
    )

    manifest = read_manifest(api, classified["id"])
    assert_status(manifest, "CLASSIFIED")
    assert_is_null(manifest, "disposal_method", "disposal_cost_cents", "carrier_ref")
    assert_money_cents(
        read_evaluation(api, evaluation["id"])["residuals_spent_cents"], 0, "residuals_spent_cents"
    )
    assert_decimal(
        read_pilot(api, pilot["id"])["unmanifested_media_kg"], 0.00, label="unmanifested_media_kg"
    )


def test_the_lawful_route_then_reveals_the_exhausted_residuals_budget(api):
    """Choosing the permitted route uncovers the priority-110 fiscal refusal.

    Incineration at 1,100 degrees is permitted for hazardous waste, so the route
    rule falls silent and the same manifest is refused instead on money: 800 kg at
    340 cents a kilogram is 272000 cents against a budget of zero.

    PRD: "That cost must fit the evaluation's residuals budget: the parent
    evaluation's `residuals_spent_cents` plus the new cost may not exceed its
    `residuals_budget_cents`, and an overrun is refused with
    `ERR_RESIDUALS_BUDGET_EXCEEDED`, spending exactly to the budget being
    permitted."

    Design: Difficulty/priority_pair_validation_conflict/prohibited_disposal_route_outranks_the_exhausted_residuals_budget
    """
    evaluation, _, classified = _hazardous_manifest_on_a_zero_budget(api)
    validate_error(
        api.ship_residuals_manifest(
            classified["id"],
            f.ship_manifest_payload("LANDFILL", carrier_ref="HAUL-0001"),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_DISPOSAL_METHOD_PROHIBITED,
        422,
    )

    validate_error(
        api.ship_residuals_manifest(
            classified["id"],
            f.ship_manifest_payload("INCINERATION_1100C", carrier_ref="HAUL-0002"),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_RESIDUALS_BUDGET_EXCEEDED,
        422,
    )

    assert_status(read_manifest(api, classified["id"]), "CLASSIFIED")
    assert_money_cents(
        read_evaluation(api, evaluation["id"])["residuals_spent_cents"], 0, "residuals_spent_cents"
    )
