"""
Two competing earned-value assessments per phase, and the two overhead rate
variants that govern what a public agency may be billed against.

Revenue recognition in an architecture practice is never a single number. Every phase
carries a cost-to-cost figure derived from the labour actually burned against
budget, and a physical-completion figure derived from the project manager's own
judgement of how much of the phase is really built. Only one of the two rolls
up into the books, and which one it is depends entirely on the project's
declared percent-complete method — so two projects holding byte-identical
timesheets can recognise wildly different revenue.

The firm-wide overhead rate has the same dual shape. The provisional rate
annualises year-to-date figures and leaves statutorily unallowable costs inside
the indirect cost pool; the final rate, computed only at certification, works on
actual unannualised figures with those costs stripped out. Only the final rate
publishes the multiplier ceiling that binds every public-agency project.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_errors import ERR_MULTIPLIER_ABOVE_CERTIFIED_CEILING
from test_helpers.assertions import (
    assert_billing_posture,
    assert_computed_report,
    assert_earned_value_report,
    assert_money,
    assert_null,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_ratio,
    quantize_money,
    quantize_ratio,
)
from test_helpers.constants import (
    CERT_CERTIFIED,
    CERT_SUBMITTED,
    CLOCK_2026_06_01,
    CONTRACT_TIME_AND_MATERIALS,
    METHOD_ASSESSED,
    METHOD_EFFORT_BASED,
    MULTIPLIER_ACTIVE,
    POSTURE_HOLD,
    POSTURE_OPEN,
)
from test_helpers.factories import assess_payload, multiplier_payload
from test_helpers.fixtures import (
    CANONICAL_MULTIPLIER,
    RATE_EFFECTIVE_FROM,
    activate_project,
    add_approved_time_entry,
    add_lump_sum_phase,
    add_percent_phase,
    create_private_client,
    create_project,
    create_public_client,
    project_version,
    publish_labor_rate,
    read_certification,
    read_earned_value,
    read_phase,
    read_project,
    set_clock,
    set_multiplier,
    submit_certification,
)
from test_helpers.test_users import (
    CONTROLLER,
    CONTROLLER_CERTIFIER,
    CONTROLLER_CERTIFIER_USER_ID,
    PROJECT_MANAGER,
)
from test_helpers.types import ProjectContext

# The two timesheet lines both variants share: 7.35 h freezes a raw cost of
# 459.38 and 10.00 h freezes 625.00, so the phase carries 1084.38 of actual
# labour cost against a 60000.00 budget on a 200000.00 fee.
SHARED_HOURS = [(7.35, "2026-05-11"), (10.00, "2026-05-12")]
PHASE_FEE = 200000.00
PHASE_BUDGET_LABOR_COST = 60000.00
ACTUAL_LABOR_COST = 1084.38
EFFORT_PERCENT_COMPLETE = 0.0181
EFFORT_EARNED_VALUE = 3620.00
ASSESSED_PERCENT_COMPLETE = 0.2500
ASSESSED_EARNED_VALUE = 50000.00
VARIANT_GAP = 46380.00

# The certification figures and the three rates they produce.
CERT_FIGURES = dict(
    ytd_months=6,
    direct_labor_base=1200000.00,
    indirect_cost_pool=1980000.00,
    unallowable_costs=90000.00,
)
PROVISIONAL_RATE = 1.6500
FINAL_RATE = 1.5750
MULTIPLIER_CEILING = 2.8325
ABOVE_CEILING_MULTIPLIER = 3.0500


def _build_variant_project(api, client_id, percent_complete_method, name):
    """
    An ACTIVE project on the given client whose single leaf phase carries the
    two shared timesheet lines and a 0.2500 physical completion assessment.
    """
    project = create_project(
        api,
        client_id,
        name=name,
        contract_type=CONTRACT_TIME_AND_MATERIALS,
        contract_amount=800000.00,
        percent_complete_method=percent_complete_method,
        target_multiplier=3.0000,
        wip_alert_threshold=50000.00,
    )
    phase = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="02-DD",
        lump_sum_fee=PHASE_FEE,
        budget_labor_cost=PHASE_BUDGET_LABOR_COST,
        consultant_budget=100000.00,
    )
    set_multiplier(
        api,
        project["id"],
        multiplier=CANONICAL_MULTIPLIER,
        effective_from=RATE_EFFECTIVE_FROM,
        expected_project_version=project["version"],
    )
    activated = activate_project(api, project["id"])
    ctx = ProjectContext(
        client_id=client_id,
        project_id=project["id"],
        version=activated["version"],
        phase_ids=[phase["id"]],
        contract_type=CONTRACT_TIME_AND_MATERIALS,
    )
    for hours, work_date in SHARED_HOURS:
        add_approved_time_entry(api, ctx, hours=hours, work_date=work_date)
    get_success_data(
        api.assess_phase(
            ctx.phase_id, assess_payload(ASSESSED_PERCENT_COMPLETE), PROJECT_MANAGER
        )
    )
    return ctx


def _build_public_agency_project(api):
    """An ACTIVE public-agency project billed on a 2.5000 multiplier, with no
    fiscal year certified yet."""
    set_clock(api, CLOCK_2026_06_01)
    client = create_public_client(api)
    project = create_project(
        api,
        client["id"],
        name="Transit Center Renovation",
        contract_type=CONTRACT_TIME_AND_MATERIALS,
        contract_amount=900000.00,
        percent_complete_method=METHOD_EFFORT_BASED,
        target_multiplier=2.5000,
    )
    phase = add_percent_phase(
        api,
        project["id"],
        wbs_code="01-SD",
        fee_percent=0.2500,
        budget_labor_cost=50000.00,
        consultant_budget=0.00,
    )
    set_multiplier(
        api,
        project["id"],
        multiplier=2.5000,
        effective_from=RATE_EFFECTIVE_FROM,
        expected_project_version=project["version"],
    )
    activated = activate_project(api, project["id"])
    return ProjectContext(
        client_id=client["id"],
        project_id=project["id"],
        version=activated["version"],
        phase_ids=[phase["id"]],
        is_public_agency=True,
    )


def test_effort_based_phase_recognizes_the_cost_to_cost_figure(api):
    """
    On an EFFORT_BASED project the phase computes both routes but books only the
    cost-to-cost one: 1084.38 of actual labour against a 60000.00 budget is
    0.0181 of the phase, so 3620.00 of the 200000.00 fee is recognised even
    though the project manager has assessed the phase at a quarter built.

    PRD §3.6: "it is the full `phase_fee` whenever the phase's `status` is `COMPLETE`; otherwise it is `effort_based_earned_value` when the project's `percent_complete_method` is `EFFORT_BASED`; otherwise it is `assessed_earned_value`"
    PRD §3.6: "the cost-to-cost route recognises 3620.00 while the assessed route recognises 50000.00"

    Design: Difficulty/dual_variant_calc/phase_earned_value_effort_based_vs_assessed
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    publish_labor_rate(api)
    ctx = _build_variant_project(
        api, client["id"], METHOD_EFFORT_BASED, "Riverside Library - effort"
    )

    phase = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(
        phase,
        actual_labor_cost_to_date=ACTUAL_LABOR_COST,
        phase_fee=PHASE_FEE,
        effort_based_percent_complete=EFFORT_PERCENT_COMPLETE,
        effort_based_earned_value=EFFORT_EARNED_VALUE,
        assessed_percent_complete=ASSESSED_PERCENT_COMPLETE,
        assessed_earned_value=ASSESSED_EARNED_VALUE,
        recognized_earned_value=EFFORT_EARNED_VALUE,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(project, earned_revenue_to_date=EFFORT_EARNED_VALUE)


def test_assessed_phase_recognizes_the_physical_completion_figure(api):
    """
    The same fee, budget, timesheets and 0.2500 assessment on an ASSESSED
    project book 50000.00 instead. The cost-to-cost figure is still computed and
    still reads 3620.00 — it simply does not reach the books.

    PRD §3.6: "it recomputes both earned-value figures and refreshes the project's `earned_revenue_to_date`, though it moves `recognized_earned_value` only when the project's method is `ASSESSED`"
    PRD §3.6: "the cost-to-cost route recognises 3620.00 while the assessed route recognises 50000.00"

    Design: Difficulty/dual_variant_calc/phase_earned_value_effort_based_vs_assessed
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    publish_labor_rate(api)
    ctx = _build_variant_project(
        api, client["id"], METHOD_ASSESSED, "Riverside Library - assessed"
    )

    phase = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(
        phase,
        actual_labor_cost_to_date=ACTUAL_LABOR_COST,
        phase_fee=PHASE_FEE,
        effort_based_percent_complete=EFFORT_PERCENT_COMPLETE,
        effort_based_earned_value=EFFORT_EARNED_VALUE,
        assessed_percent_complete=ASSESSED_PERCENT_COMPLETE,
        assessed_earned_value=ASSESSED_EARNED_VALUE,
        recognized_earned_value=ASSESSED_EARNED_VALUE,
    )

    report = read_earned_value(api, ctx.phase_id)
    assert_computed_report(report)
    assert_earned_value_report(
        report,
        actual_labor_cost_to_date=ACTUAL_LABOR_COST,
        phase_fee=PHASE_FEE,
        effort_based_percent_complete=EFFORT_PERCENT_COMPLETE,
        effort_based_earned_value=EFFORT_EARNED_VALUE,
        assessed_percent_complete=ASSESSED_PERCENT_COMPLETE,
        assessed_earned_value=ASSESSED_EARNED_VALUE,
        recognized_earned_value=ASSESSED_EARNED_VALUE,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(project, earned_revenue_to_date=ASSESSED_EARNED_VALUE)


def test_identical_charge_data_diverges_by_exactly_the_variant_gap(api):
    """
    Two projects on one client, identical in fee, budget, timesheets and
    assessment and differing only in the method that selects the variant,
    recognise 3620.00 and 50000.00 respectively — a gap of exactly 46380.00
    produced by nothing but the method flag.

    PRD §3.6: "`earned_revenue_to_date` is the sum of `recognized_earned_value` over the project's **leaf** phases only"
    PRD §3.6: "The two variants really do diverge on identical timesheets."

    Design: Difficulty/dual_variant_calc/phase_earned_value_effort_based_vs_assessed
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    publish_labor_rate(api)
    effort_ctx = _build_variant_project(
        api, client["id"], METHOD_EFFORT_BASED, "Riverside Library - effort"
    )
    assessed_ctx = _build_variant_project(
        api, client["id"], METHOD_ASSESSED, "Riverside Library - assessed"
    )

    effort_phase = read_phase(api, effort_ctx.phase_id)
    assessed_phase = read_phase(api, assessed_ctx.phase_id)
    # The charge data underneath the two phases really is identical.
    assert_money(
        effort_phase["actual_labor_cost_to_date"], ACTUAL_LABOR_COST, "effort actual cost"
    )
    assert_money(
        assessed_phase["actual_labor_cost_to_date"],
        ACTUAL_LABOR_COST,
        "assessed actual cost",
    )
    assert_money(
        effort_phase["effort_based_earned_value"], EFFORT_EARNED_VALUE, "effort route"
    )
    assert_money(
        assessed_phase["effort_based_earned_value"],
        EFFORT_EARNED_VALUE,
        "assessed project's unused effort route",
    )
    assert_money(
        effort_phase["assessed_earned_value"],
        ASSESSED_EARNED_VALUE,
        "effort project's unused assessed route",
    )
    assert_money(
        assessed_phase["assessed_earned_value"], ASSESSED_EARNED_VALUE, "assessed route"
    )
    assert_money(
        effort_phase["recognized_earned_value"], EFFORT_EARNED_VALUE, "effort recognised"
    )
    assert_money(
        assessed_phase["recognized_earned_value"],
        ASSESSED_EARNED_VALUE,
        "assessed recognised",
    )

    effort_project = read_project(api, effort_ctx.project_id)
    assessed_project = read_project(api, assessed_ctx.project_id)
    assert_project_ledger(effort_project, earned_revenue_to_date=EFFORT_EARNED_VALUE)
    assert_project_ledger(assessed_project, earned_revenue_to_date=ASSESSED_EARNED_VALUE)
    gap = quantize_money(assessed_project["earned_revenue_to_date"]) - quantize_money(
        effort_project["earned_revenue_to_date"]
    )
    assert_money(gap, VARIANT_GAP, "revenue gap between the two variants")


def test_submission_publishes_only_the_annualized_provisional_rate(api):
    """
    A pool of 1980000.00 against a base of 1200000.00 with six months of
    actuals annualises to a provisional rate of 1.6500 the moment the figures
    are submitted, and nothing else is published yet: no final rate, no ceiling.
    Until a year is certified the public-agency project has no ceiling at all
    and its posture is HOLD.

    PRD §3.9: "`provisional_overhead_rate` comes to 1.6500 while `final_overhead_rate` comes to 1.5750"
    PRD §3.9: "the row lands in `status` `SUBMITTED`, and its `final_overhead_rate`, `certified_multiplier_ceiling`, `certified_by_user_id` and `findings` are all `null`"

    Design: Difficulty/dual_variant_calc/overhead_rate_provisional_vs_final_ceiling
    """
    ctx = _build_public_agency_project(api)

    before = read_project(api, ctx.project_id)
    assert_null(before["certified_multiplier_ceiling"], "project.certified_multiplier_ceiling")
    assert_billing_posture(before, POSTURE_HOLD)

    submitted = submit_certification(api, **CERT_FIGURES)
    assert submitted["status"] == CERT_SUBMITTED
    assert_ratio(
        submitted["provisional_overhead_rate"], PROVISIONAL_RATE, "provisional_overhead_rate"
    )
    assert_null(submitted["final_overhead_rate"], "final_overhead_rate")
    assert_null(submitted["certified_multiplier_ceiling"], "certified_multiplier_ceiling")
    assert_null(submitted["certified_by_user_id"], "certified_by_user_id")
    assert_null(submitted["findings"], "findings")

    # The unfinished certification publishes nothing to the project.
    still_held = read_project(api, ctx.project_id)
    assert_null(
        still_held["certified_multiplier_ceiling"], "project.certified_multiplier_ceiling"
    )
    assert_billing_posture(still_held, POSTURE_HOLD)


def test_certification_publishes_the_lower_final_rate_and_the_ceiling(api):
    """
    Certifying the very same figures strips the 90000.00 of unallowable costs
    and drops the annualisation, producing a final rate of 1.5750 — lower than
    the 1.6500 provisional rate that survives unchanged alongside it — and from
    it a ceiling of 2.8325 which reaches the public-agency project and releases
    its billing posture.

    PRD §3.9: "`final_overhead_rate` is the `indirect_cost_pool` less `unallowable_costs`, divided by the `direct_labor_base`, rounded half up to 4 decimal places"
    PRD §3.9: "`certified_multiplier_ceiling` is one plus `final_overhead_rate`, multiplied by one plus a profit margin cap of 0.1000, rounded half up to 4 decimal places. On the figures above, the ceiling is 2.8325."
    PRD §3.9: "those projects re-run `billing_posture`, so a project that was held for a missing certification moves from `HOLD` to `OPEN` and becomes invoiceable"

    Design: Difficulty/dual_variant_calc/overhead_rate_provisional_vs_final_ceiling
    """
    ctx = _build_public_agency_project(api)
    submitted = submit_certification(api, **CERT_FIGURES)
    certified = validate_success(
        api.certify_certification(submitted["id"], CONTROLLER_CERTIFIER)
    )

    assert certified["status"] == CERT_CERTIFIED
    assert_ratio(certified["final_overhead_rate"], FINAL_RATE, "final_overhead_rate")
    assert_ratio(
        certified["certified_multiplier_ceiling"],
        MULTIPLIER_CEILING,
        "certified_multiplier_ceiling",
    )
    # The provisional figure is not overwritten: the two rates coexist and differ.
    assert_ratio(
        certified["provisional_overhead_rate"], PROVISIONAL_RATE, "provisional_overhead_rate"
    )
    assert quantize_ratio(certified["final_overhead_rate"]) < quantize_ratio(
        certified["provisional_overhead_rate"]
    ), "the final rate must be strictly lower than the provisional rate"

    reread = read_certification(api, submitted["id"])
    assert_ratio(reread["final_overhead_rate"], FINAL_RATE, "final_overhead_rate on reread")
    assert reread["certified_by_user_id"] == CONTROLLER_CERTIFIER_USER_ID

    project = read_project(api, ctx.project_id)
    assert_ratio(
        project["certified_multiplier_ceiling"],
        MULTIPLIER_CEILING,
        "project.certified_multiplier_ceiling",
    )
    assert_billing_posture(project, POSTURE_OPEN)


def test_published_ceiling_refuses_3_0500_but_admits_2_8325_exactly(api):
    """
    Only the final rate publishes a ceiling, and once 2.8325 is in force on a
    public-agency project a 3.0500 multiplier is refused outright while 2.8325
    itself is accepted — the comparison is an exceedance test, so the boundary
    value is admitted and lands ACTIVE.

    PRD §3.2: "a new `multiplier` may not exceed the project's `certified_multiplier_ceiling` — the ceiling derived from the certified final overhead rate as described in §3.9"
    PRD §3.2: "A multiplier above that ceiling is refused with `ERR_MULTIPLIER_ABOVE_CERTIFIED_CEILING` (HTTP 422)."
    PRD §3.2: "A new multiplier is created with `status` `ACTIVE`."

    Design: Difficulty/dual_variant_calc/overhead_rate_provisional_vs_final_ceiling
    """
    ctx = _build_public_agency_project(api)
    submitted = submit_certification(api, **CERT_FIGURES)
    validate_success(api.certify_certification(submitted["id"], CONTROLLER_CERTIFIER))

    version_after_certify = project_version(api, ctx.project_id)
    over = api.create_billing_multiplier(
        multiplier_payload(
            ctx.project_id,
            version_after_certify,
            multiplier=ABOVE_CEILING_MULTIPLIER,
            effective_from="2026-07-01",
        ),
        CONTROLLER,
    )
    validate_error(over, ERR_MULTIPLIER_ABOVE_CERTIFIED_CEILING, 422)

    # A refused multiplier changes nothing, so the boundary value may reuse the
    # very same expected project version.
    at_ceiling = validate_success(
        api.create_billing_multiplier(
            multiplier_payload(
                ctx.project_id,
                version_after_certify,
                multiplier=MULTIPLIER_CEILING,
                effective_from="2026-07-01",
            ),
            CONTROLLER,
        ),
        201,
    )
    assert_ratio(at_ceiling["multiplier"], MULTIPLIER_CEILING, "multiplier")
    assert at_ceiling["status"] == MULTIPLIER_ACTIVE
    assert at_ceiling["version"] == 1

    project = read_project(api, ctx.project_id)
    assert_ratio(
        project["certified_multiplier_ceiling"],
        MULTIPLIER_CEILING,
        "project.certified_multiplier_ceiling",
    )
    assert project["version"] == version_after_certify + 1
