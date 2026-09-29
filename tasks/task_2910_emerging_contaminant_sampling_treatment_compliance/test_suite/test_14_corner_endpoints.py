"""Endpoint surface: the one update, a parent-scoped creation, a computed read.

These tests exercise the endpoint contracts themselves rather than the rules
behind them: what a PATCH is allowed to change, how a child creation resolves its
parent path segment and becomes visible from both ends of the link, what a plain
GET must already have computed, and how a conditional action refuses and then
accepts the very same request.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CONCENTRATE_PERMIT_REQUIRED,
    ERR_PROJECT_IN_SERVICE,
    ERR_PROJECT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_decimal,
    assert_equals,
    assert_is_null,
    assert_money_cents,
    assert_rate_ladder,
    assert_status,
    assert_total_count,
    first_row,
)
from test_helpers.fixtures import (
    apply_for_funding,
    award_funding,
    complete_pilot,
    open_evaluation,
    project_of_evaluation,
    read_application,
    read_entry_point,
    read_evaluation,
    read_pilot,
    read_project,
    register_entry_point,
    register_pilot,
    select_technology,
    selected_project,
    start_pilot,
)
from test_helpers.test_users import FINANCE_OFFICER_HEADERS, TREATMENT_ENGINEER_HEADERS


def test_patching_the_rate_design_switches_the_authoritative_bill_variant(api):
    """The ladder does not move a cent, but the reported bill drops by one.

    A freshly selected GAC project carries the whole 680000000-cent cost locally
    and reports the uniform 341-cent bill its UNIFORM default selects. Patching
    nothing but the rate design leaves every rung of the ladder exactly where it
    was — the same 41586568 debt service, the same 150 basis points of surcharge,
    the same 7.18 percent impact — while the authoritative bill becomes the
    volumetric 340 cents that the 68-cent-per-kgal rate produces. Both variants
    stay readable side by side on the row.

    PRD: "`monthly_bill_increase_cents` then reports whichever variant
    `rate_design` selects: the uniform figure under `UNIFORM` and the volumetric
    figure under `VOLUMETRIC`."

    Design: Corner/endpoints/the_capital_project_patch_switches_the_authoritative_bill_variant
    """
    entry_point = register_entry_point(api)
    selected = selected_project(api, entry_point["id"], residuals_budget_cents=500000)
    project = selected["project"]
    assert_equals(project, "rate_design", "UNIFORM")
    assert_rate_ladder(
        project,
        uniform_monthly_increase_cents=341,
        volumetric_monthly_increase_cents=340,
        monthly_bill_increase_cents=341,
    )

    patched = validate_success(
        api.patch_capital_project(
            project["id"],
            f.project_patch_payload(rate_design="VOLUMETRIC"),
            FINANCE_OFFICER_HEADERS,
        )
    )

    assert_equals(patched, "rate_design", "VOLUMETRIC")
    assert_money_cents(patched["capital_cost_cents"], 680000000, "capital_cost_cents")
    assert_money_cents(patched["annual_om_cost_cents"], 31000000, "annual_om_cost_cents")
    assert_rate_ladder(
        patched,
        local_share_cents=680000000,
        borrowed_cents=680000000,
        annual_debt_service_cents=41586568,
        base_annual_requirement_cents=72586568,
        provisional_rate_impact_pct=7.07,
        surcharge_bp=150,
        final_annual_requirement_cents=73675367,
        rate_impact_pct=7.18,
        uniform_monthly_increase_cents=341,
        volumetric_rate_increase_cents_per_kgal=68,
        volumetric_monthly_increase_cents=340,
        monthly_bill_increase_cents=340,
    )


def test_a_funding_application_is_visible_from_the_project_and_from_the_list(api):
    """The same body dies on an unresolvable parent and lives on the real one.

    Posting the application under an identifier that matches no project is refused
    with the project collection's own 404 and creates nothing, so the applications
    collection is still empty. The identical body posted under the real project is
    created directly in SUBMITTED status with no draft stage, records the parent it
    was posted under, resolves an ordinary SRF loan to no forgiveness at all and
    leaves the awarded amount null. The parent's funding status becomes APPLIED and
    the child is reachable from it through the declared reverse-list filter.

    PRD: "There is no draft stage: the application is created directly in
    `SUBMITTED` status with its `capital_project_id` recorded and its
    `forgiveness_pct` resolved immediately from the program and the community
    designation."

    Design: Corner/endpoints/a_funding_application_links_the_project_and_appears_on_its_reverse_list
    """
    entry_point = register_entry_point(api)
    selected = selected_project(api, entry_point["id"], residuals_budget_cents=500000)
    project = selected["project"]
    body = f.funding_application_payload(
        project["version"],
        program="SRF_LOAN",
        amount_requested_cents=400000000,
        disadvantaged_community=False,
    )

    validate_error(
        api.create_funding_application(NON_EXISTENT_UUID, body, FINANCE_OFFICER_HEADERS),
        ERR_PROJECT_NOT_FOUND,
        404,
    )
    assert_total_count(api.list_funding_applications(FINANCE_OFFICER_HEADERS), 0)

    application = validate_success(
        api.create_funding_application(project["id"], body, FINANCE_OFFICER_HEADERS), 201
    )

    assert_status(application, "SUBMITTED")
    assert_equals(application, "capital_project_id", project["id"])
    assert_money_cents(
        application["amount_requested_cents"], 400000000, "amount_requested_cents"
    )
    assert_decimal(application["forgiveness_pct"], 0.00, label="forgiveness_pct")
    assert_is_null(application, "awarded_cents", "forgiven_cents")

    assert_equals(read_project(api, project["id"]), "funding_status", "APPLIED")
    listed = api.list_funding_applications(
        FINANCE_OFFICER_HEADERS, params={"capital_project_id": project["id"]}
    )
    assert_total_count(listed, 1)
    assert_equals(first_row(listed), "id", application["id"])


def test_reading_a_completed_pilot_returns_the_round_then_sum_composite(api):
    """80.14, not 80.13: the read exposes the accumulation order itself.

    The completed carbon skid removed 96.30 percent and its 2550000000-cent
    lifecycle converts to a merit score of 74.50, so the five weighted terms are
    33.71, 18.63, 12.40, 7.10 and 8.30. Rounding each term before adding gives
    80.14, while accumulating first and rounding once gives 80.13, and only the
    former is the contract. The plain read also shows the residuals ledger still
    untouched at the full 800.00 kilograms, the skid not yet chosen, and its parent
    evaluation still piloting.

    PRD: "`technology_score` is the weighted composite, and its accumulation rule
    is exact and deliberate: the five terms are `removal_pct` multiplied by 0.35,
    `lifecycle_cost_score` multiplied by 0.25, `residuals_burden_score` multiplied
    by 0.20, `footprint_score` multiplied by 0.10 and `om_complexity_score`
    multiplied by 0.10"

    Design: Corner/endpoints/a_completed_pilot_read_returns_its_computed_removal_and_score
    """
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=500000)
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

    stored = validate_success(api.get_pilot_test(pilot["id"], TREATMENT_ENGINEER_HEADERS))

    assert_status(stored, "COMPLETED")
    assert_decimal(stored["removal_pct"], 96.30, label="removal_pct")
    assert_decimal(stored["lifecycle_cost_score"], 74.50, label="lifecycle_cost_score")
    assert_decimal(stored["technology_score"], 80.14, label="technology_score")
    assert float(stored["technology_score"]) != 80.13, (
        "technology_score 80.13 means the five terms were summed before rounding"
    )
    assert_decimal(stored["spent_media_kg"], 800.00, label="spent_media_kg")
    assert_decimal(stored["unmanifested_media_kg"], 800.00, label="unmanifested_media_kg")
    assert_equals(stored, "selected", False)
    assert_status(read_evaluation(api, evaluation["id"]), "PILOTING")


def test_a_membrane_project_reaches_bidding_only_once_its_permit_is_named(api):
    """The permit gate refuses the request, then the identical request plus a reference passes.

    Reverse osmosis wins the comparison on a composite of 73.15 against carbon's
    54.75 with both skids above the removal floor, and being a membrane it is the
    one branch that needs a discharge permit for its concentrate. Its fully forgiven
    900000000-cent grant leaves nothing borrowed, so the ladder collapses to the
    45000000-cent operating requirement, a 4.39 percent impact and a 208-cent
    monthly bill. The first move to bidding is refused for want of a permit
    reference and the project does not budge; supplying one carries it through
    bidding, construction and into service, which installs treatment at the entry
    point and freezes the cost basis against the adjustment that would have worked
    an hour earlier.

    PRD: "The move into `BIDDING` carries two extra preconditions, checked in this
    order: when the project's `concentrate_permit_required` is true, a
    `concentrate_permit_ref` must be supplied, else
    `ERR_CONCENTRATE_PERMIT_REQUIRED`; and the project's `funding_status` must be
    `AWARDED`, else `ERR_FUNDING_NOT_SECURED`."

    Design: Corner/endpoints/reaching_bidding_is_a_conditional_action_gated_on_funding_and_the_permit
    """
    entry_point = register_entry_point(api, label="EPTDS-03")
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=500000)
    ro = register_pilot(
        api,
        f.ro_pilot_payload(
            evaluation["id"],
            window_start_at="2026-05-01T00:00:00.000Z",
            window_end_at="2026-05-15T00:00:00.000Z",
            ebct_min=15.00,
            lifecycle_cost_cents=3000000000,
            capital_cost_estimate_cents=900000000,
            annual_om_estimate_cents=45000000,
            residuals_burden_score=30.00,
            footprint_score=60.00,
            om_complexity_score=90.00,
        ),
    )
    gac = register_pilot(
        api,
        f.gac_pilot_payload(
            evaluation["id"],
            window_start_at="2026-05-17T00:00:00.000Z",
            window_end_at="2026-05-31T00:00:00.000Z",
            lifecycle_cost_cents=5000000000,
            capital_cost_estimate_cents=600000000,
            annual_om_estimate_cents=25000000,
            residuals_burden_score=20.00,
            footprint_score=30.00,
            om_complexity_score=20.00,
        ),
    )
    start_pilot(api, ro["id"])
    complete_pilot(
        api,
        ro["id"],
        influent_ng_per_l=50.00,
        effluent_ng_per_l=0.50,
        bed_volumes_treated=30000.00,
        spent_media_kg=200.00,
    )
    start_pilot(api, gac["id"])
    complete_pilot(
        api,
        gac["id"],
        influent_ng_per_l=50.00,
        effluent_ng_per_l=2.50,
        bed_volumes_treated=20000.00,
        spent_media_kg=500.00,
    )
    decided = select_technology(
        api,
        evaluation["id"],
        decision_note="RO wins on score with both pilots above the removal floor",
    )
    assert_equals(decided, "selected_technology", "RO")
    ro_pilot = read_pilot(api, ro["id"])
    gac_pilot = read_pilot(api, gac["id"])
    assert_decimal(ro_pilot["removal_pct"], 99.00, label="removal_pct")
    assert_decimal(ro_pilot["technology_score"], 73.15, label="technology_score")
    assert_decimal(gac_pilot["removal_pct"], 95.00, label="removal_pct")
    assert_decimal(gac_pilot["technology_score"], 54.75, label="technology_score")
    assert_equals(ro_pilot, "selected", True)
    assert_equals(gac_pilot, "selected", False)

    project = project_of_evaluation(api, evaluation["id"])
    assert_money_cents(project["capital_cost_cents"], 900000000, "capital_cost_cents")
    assert_money_cents(project["annual_om_cost_cents"], 45000000, "annual_om_cost_cents")
    assert_equals(project, "required_disposal_method", "DEEP_WELL")
    assert_equals(project, "concentrate_permit_required", True)
    application = apply_for_funding(
        api,
        project["id"],
        program="EC_GRANT",
        amount_requested_cents=900000000,
        disadvantaged_community=False,
    )
    award_funding(api, application["id"], 900000000)
    awarded_application = read_application(api, application["id"])
    assert_decimal(awarded_application["forgiveness_pct"], 100.00, label="forgiveness_pct")
    assert_money_cents(awarded_application["forgiven_cents"], 900000000, "forgiven_cents")
    funded = read_project(api, project["id"])
    assert_equals(funded, "funding_status", "AWARDED")
    assert_rate_ladder(
        funded,
        local_share_cents=0,
        borrowed_cents=0,
        annual_debt_service_cents=0,
        base_annual_requirement_cents=45000000,
        provisional_rate_impact_pct=4.39,
        surcharge_bp=0,
        rate_impact_pct=4.39,
        uniform_monthly_increase_cents=208,
    )

    validate_error(
        api.advance_construction(
            project["id"], f.construction_status_payload("BIDDING"), FINANCE_OFFICER_HEADERS
        ),
        ERR_CONCENTRATE_PERMIT_REQUIRED,
        422,
    )
    assert_equals(read_project(api, project["id"]), "construction_status", "PLANNED")

    bidding = validate_success(
        api.advance_construction(
            project["id"],
            f.construction_status_payload("BIDDING", concentrate_permit_ref="NPDES-2026-114"),
            FINANCE_OFFICER_HEADERS,
        )
    )
    assert_equals(bidding, "construction_status", "BIDDING")
    construction = validate_success(
        api.advance_construction(
            project["id"],
            f.construction_status_payload("CONSTRUCTION"),
            FINANCE_OFFICER_HEADERS,
        )
    )
    assert_equals(construction, "construction_status", "CONSTRUCTION")
    in_service = validate_success(
        api.advance_construction(
            project["id"], f.construction_status_payload("IN_SERVICE"), FINANCE_OFFICER_HEADERS
        )
    )
    assert_equals(in_service, "construction_status", "IN_SERVICE")
    assert_equals(read_entry_point(api, entry_point["id"]), "treatment_status", "INSTALLED")

    validate_error(
        api.patch_capital_project(
            project["id"],
            f.project_patch_payload(capital_cost_cents=950000000),
            FINANCE_OFFICER_HEADERS,
        ),
        ERR_PROJECT_IN_SERVICE,
        422,
    )
    assert_money_cents(
        read_project(api, project["id"])["capital_cost_cents"], 900000000, "capital_cost_cents"
    )
