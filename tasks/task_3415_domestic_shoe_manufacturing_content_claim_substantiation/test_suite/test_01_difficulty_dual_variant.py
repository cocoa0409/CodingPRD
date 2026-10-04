"""Depth probes: dual-variant calculations (PROVISIONAL vs CERTIFIED content;
certified-only vs pipeline-adjusted workforce coverage)."""
import pytest

from test_helpers import (
    WEEK_36, ApiErrorId, bom_line, certify_pair, certify_worker, complete_run,
    create_report, enroll, get_run, lock_allocation, make_allocation,
    make_component, make_factory, make_lot, make_model, make_run, make_worker,
    reserve_run, set_clock, standard_kit, start_run, validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["admin"]
PLANNER = TEST_USERS["planner"]


def _m990v6_kit():
    """DOMESTIC factory; M990V6 (upper 2.0 DOMESTIC_PREFERRED planned 1200
    domestic + midsole 1.0 IMPORT_ALLOWED planned 800); domestic upper lot
    500 @1250, imported midsole lot 500 @800; STOCK run of 100 in 2026-W36
    (allocation total 500), locked and reserved."""
    set_clock()
    factory = make_factory(factory_name="Lawrence MA Plant", line_count=2)
    c_up = make_component("Full-grain leather upper", "UPPER")
    c_mid = make_component("EVA midsole", "MIDSOLE")
    make_lot(c_up["id"], supplier_name="Lawrence Leather Co", quantity_received=500,
             unit_cost_cents=1250, is_domestic=True)
    make_lot(c_mid["id"], supplier_name="Saigon Foam Ltd", quantity_received=500,
             unit_cost_cents=800, is_domestic=False)
    model = make_model(bom_lines=[
        bom_line(c_up["id"], quantity_per_pair=2.0,
                 sourcing_requirement="DOMESTIC_PREFERRED",
                 planned_unit_cost_cents=1200, planned_is_domestic=True),
        bom_line(c_mid["id"], planned_unit_cost_cents=800, planned_is_domestic=False),
    ], style_code="M990V6", base_price_cents=15000, import_cost_basis_cents=4000,
        standard_stitching_minutes=10, standard_lasting_minutes=5,
        standard_assembly_minutes=5)
    allocation = make_allocation(factory["id"], WEEK_36, 500)
    run = make_run(model["id"], factory["id"], planned_units=100)
    lock_allocation(allocation["id"])
    run = reserve_run(run["id"])
    return {"factory": factory, "model": model, "run": run}


def test_provisional_variant_uses_planned_costs_and_standard_minutes(api):
    """PRD §3.6: "For a `PROVISIONAL` report, each BOM line's extended cost is
    its `quantity_per_pair` times its `planned_unit_cost_cents`, rounded half up
    to integer cents; the report's `material_cost_cents` is the sum of those
    per-line costs over all lines, and its `domestic_material_cost_cents` is the
    same sum restricted to lines whose `planned_is_domestic` is true, while the
    labor minutes total is the sum of the model's `standard_stitching_minutes`,
    `standard_lasting_minutes`, and `standard_assembly_minutes`."

    Design: Difficulty/dual_variant_calc/content_provisional_vs_certified_diverge
    """
    kit = _m990v6_kit()
    report = create_report(kit["run"]["id"], "PROVISIONAL")

    assert report["variant"] == "PROVISIONAL" and report["status"] == "ACTIVE"
    assert report["material_cost_cents"] == 3200          # 2400 + 800
    assert report["domestic_material_cost_cents"] == 2400  # upper line only
    assert report["labor_cost_cents"] == 1000              # (10+5+5) * 50
    assert report["overhead_cost_cents"] == 600
    assert report["total_cost_cents"] == 4800
    assert report["domestic_value_cents"] == 4000          # 2400 + 1000 + 600
    assert report["us_content_pct"] == pytest.approx(83.33)
    assert report["final_assembly_domestic"] is True


def test_certified_variant_diverges_and_refreshes_model_pricing(api):
    """PRD §3.6: "A certified report therefore diverges from its provisional
    counterpart whenever actual lot prices or actual minutes differ from plan."
    PRD §3.6: "Whenever a `CERTIFIED` report is created on a run whose factory
    is `DOMESTIC` — including one created by the recompute cascade — the run's
    model is refreshed event-driven: the model's `domestic_unit_cost_cents` is
    set to the report's `total_cost_cents`, and its `domestic_price_cents` is
    set to the model's `base_price_cents` multiplied by the report's
    `total_cost_cents` and divided by the model's `import_cost_basis_cents`,
    rounded half up to integer cents."

    Design: Difficulty/dual_variant_calc/content_provisional_vs_certified_diverge
    """
    kit = _m990v6_kit()
    run_id = kit["run"]["id"]
    provisional = create_report(run_id, "PROVISIONAL")
    certify_pair(kit["factory"]["id"])
    start_run(run_id)
    complete_run(run_id, (11, 6, 5))
    certified = create_report(run_id, "CERTIFIED")

    assert certified["material_cost_cents"] == 3300          # (200*1250+100*800)/100
    assert certified["domestic_material_cost_cents"] == 2500  # 200*1250/100
    assert certified["labor_cost_cents"] == 1100              # (11+6+5) * 50
    assert certified["total_cost_cents"] == 5000
    assert certified["us_content_pct"] == pytest.approx(84.00)
    # The two variants disagree on identical nominal inputs.
    assert provisional["us_content_pct"] != certified["us_content_pct"]

    model = validate_success(api.get_model(kit["model"]["id"], TEST_USERS["sourcing"]))
    assert model["domestic_unit_cost_cents"] == 5000
    assert model["domestic_price_cents"] == 18750  # round_half_up(15000*5000/4000)

    run = get_run(run_id)
    # STOCK run of 100 units: no small-batch surcharge at 50 or more.
    assert run["certified_unit_cost_cents"] == 5000


def _two_runs_in_production_with_trainee():
    """DOMESTIC factory (2 lines); two STOCK runs of 10 IN_PRODUCTION in
    2026-W36 (required headcount STITCHING 4 / LASTING 2 / ASSEMBLY 2); two
    fully certified workers; one extra worker with an open STITCHING
    enrollment (never assessed)."""
    set_clock()
    factory = make_factory(factory_name="Lawrence MA Plant", line_count=2)
    c_out = make_component("Rubber outsole", "OUTSOLE")
    make_lot(c_out["id"], supplier_name="Akron Rubber", quantity_received=1000,
             unit_cost_cents=3000, is_domestic=True)
    model = make_model(bom_lines=[
        bom_line(c_out["id"], planned_unit_cost_cents=3000, planned_is_domestic=False),
    ], style_code="M880V2", base_price_cents=9900, import_cost_basis_cents=3000)
    allocation = make_allocation(factory["id"], WEEK_36, 500)
    r1 = make_run(model["id"], factory["id"], planned_units=10, line_index=1)
    r2 = make_run(model["id"], factory["id"], planned_units=10, line_index=2)
    lock_allocation(allocation["id"])
    reserve_run(r1["id"])
    reserve_run(r2["id"])
    certify_pair(factory["id"])
    start_run(r1["id"])
    start_run(r2["id"])
    trainee = make_worker(factory["id"], "Alan Turing")
    enroll(trainee["id"], "STITCHING", target_level=1)
    return factory


def test_skill_coverage_certified_only_variant(api):
    """PRD §3.2: "Otherwise, the operation's coverage is the smaller of 100 and
    the ratio of available to required workers expressed as a percentage and
    rounded half up to a whole number. What counts as *available* depends on the
    variant: the **certified-only** variant counts `ACTIVE` workers holding a
    certification for the operation with `cert_status` `CERTIFIED`"
    PRD §3.2: "The factory's overall score is the weighted blend of the three
    operation coverages — stitching weighted at one half, lasting at three
    tenths, and assembly at one fifth — rounded half up to 1 decimal place."

    Design: Difficulty/dual_variant_calc/skill_coverage_certified_vs_pipeline_diverge
    """
    factory = _two_runs_in_production_with_trainee()
    data = validate_success(api.get_factory(factory["id"], ADMIN))
    # STITCHING 2 certified of 4 required -> 50; LASTING 100; ASSEMBLY 100.
    # 50*0.5 + 100*0.3 + 100*0.2 = 75.0
    assert data["skill_coverage_certified_pct"] == pytest.approx(75.0)


def test_skill_coverage_pipeline_adjusted_variant_diverges(api):
    """PRD §3.2: "the **pipeline-adjusted** variant adds a half-worker credit
    (0.5) for each `ACTIVE` worker holding an open enrollment — `ENROLLED` or
    `REMEDIATION` — for that operation."
    PRD §3.2: "The certified-only blend is published as
    `skill_coverage_certified_pct` and the pipeline-adjusted blend as
    `skill_coverage_pipeline_pct`; the two diverge exactly when a factory has
    training in flight but thin certification on the floor."

    Design: Difficulty/dual_variant_calc/skill_coverage_certified_vs_pipeline_diverge
    """
    factory = _two_runs_in_production_with_trainee()
    data = validate_success(api.get_factory(factory["id"], ADMIN))
    # STITCHING pipeline coverage = round_half_up(100 * 2.5 / 4) = 63.
    # 63*0.5 + 100*0.3 + 100*0.2 = 81.5
    assert data["skill_coverage_pipeline_pct"] == pytest.approx(81.5)
    assert data["skill_coverage_pipeline_pct"] != data["skill_coverage_certified_pct"]
