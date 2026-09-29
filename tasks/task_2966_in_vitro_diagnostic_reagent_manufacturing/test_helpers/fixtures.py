"""Composite setup helpers.

The harness restarts the server and empties the database before **every**
individual test, so nothing here may assume pre-existing data: each helper
builds the state it needs from scratch through documented endpoints only.

Every helper takes the API client as its first argument, accepts ``**overrides``
where a payload is involved, and returns the resource dict(s) the server
produced (already unwrapped).  Composite builders return a plain ``dict`` whose
keys are documented on the helper.

**Clock discipline.** There is no endpoint that reads the logical clock back, so
a helper never guesses where the clock is.  Client-supplied instants default to
offsets from the clock's documented starting value of 2026-08-01T00:00:00Z (see
``constants.clock_plus``); a test that moves the clock first should pass the
instants it wants explicitly, or move the clock back before calling a builder
whose defaults matter.
"""
from typing import Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .constants import DEFAULT_CLOCK_UTC, EM_ACTION_LIMITS
from . import factories as f
from .test_users import (DISTRIBUTION_PLANNER, PLATFORM_ADMIN,
                         PRODUCTION_OPERATOR, QA_RELEASER, QA_RELEASER_2,
                         QC_ANALYST, REGULATORY_AFFAIRS)

HTTP_CREATED = 201
HTTP_OK = 200


def created(response) -> dict:
    """Unwrap a 201 creation response."""
    return get_success_data(response, HTTP_CREATED)


def ok(response) -> dict:
    """Unwrap a 200 response."""
    return get_success_data(response, HTTP_OK)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(api, instant: str, headers=PLATFORM_ADMIN) -> str:
    """Move the logical clock and return the instant the server echoed."""
    body = ok(api.set_clock(instant, headers))
    return body["current_utc"]


def reset_clock(api, headers=PLATFORM_ADMIN) -> str:
    """Park the logical clock back on its documented starting instant."""
    return set_clock(api, DEFAULT_CLOCK_UTC, headers)


# ---------------------------------------------------------------------------
# Raw material qualification
# ---------------------------------------------------------------------------
def create_material_specification(api, headers=REGULATORY_AFFAIRS,
                                  **overrides) -> dict:
    return created(api.create_material_specification(
        f.material_specification_payload(**overrides), headers))


def create_material_lot(api, material_specification_id: str,
                        headers=PRODUCTION_OPERATOR, **overrides) -> dict:
    return created(api.create_material_lot(
        f.material_lot_payload(material_specification_id, **overrides), headers))


def passing_value_for(spec: dict, test_code: str) -> float:
    """A measured value that lands inside the specification bound governing
    ``test_code``, so the recorded outcome is PASS."""
    if test_code == "POTENCY":
        return round((spec["potency_min_pct"] + spec["potency_max_pct"]) / 2.0, 2)
    if test_code == "PURITY":
        return float(spec["purity_min_pct"])
    if test_code == "ENDOTOXIN":
        return round(float(spec["endotoxin_max_eu_per_ml"]) / 2.0, 2)
    if test_code == "IDENTITY":
        return 1.0
    raise AssertionError(f"unknown acceptance test code {test_code!r}")


def failing_value_for(spec: dict, test_code: str) -> float:
    """A measured value outside the governing bound, so the outcome is FAIL."""
    if test_code == "POTENCY":
        return round(float(spec["potency_max_pct"]) + 10.0, 2)
    if test_code == "PURITY":
        return round(float(spec["purity_min_pct"]) - 10.0, 2)
    if test_code == "ENDOTOXIN":
        return round(float(spec["endotoxin_max_eu_per_ml"]) * 2.0, 2)
    if test_code == "IDENTITY":
        return 0.0
    raise AssertionError(f"unknown acceptance test code {test_code!r}")


def record_material_measurement(api, material_lot_id: str, test_code: str,
                                measured_value: float, headers=QC_ANALYST,
                                is_retest: Optional[bool] = None,
                                **overrides) -> dict:
    return created(api.create_test_result(
        f.material_test_result_payload(material_lot_id, test_code,
                                       measured_value, is_retest=is_retest,
                                       **overrides), headers))


def record_passing_material_tests(api, material_lot_id: str, spec: dict,
                                  headers=QC_ANALYST) -> List[dict]:
    """One passing measurement per code in the specification's
    ``required_test_codes``, which is what a QUALIFY disposition demands."""
    return [record_material_measurement(api, material_lot_id, code,
                                        passing_value_for(spec, code), headers)
            for code in spec["required_test_codes"]]


def qualified_material(api, *, spec_overrides: Optional[dict] = None,
                       lot_overrides: Optional[dict] = None,
                       spec_headers=REGULATORY_AFFAIRS,
                       lot_headers=PRODUCTION_OPERATOR,
                       analyst_headers=QC_ANALYST,
                       releaser_headers=QA_RELEASER) -> dict:
    """A raw material lot carried all the way to ``QUALIFIED``.

    Returns ``{"spec", "lot", "results"}`` where ``lot`` is the lot as it reads
    after the QUALIFY disposition.
    """
    spec = create_material_specification(api, spec_headers,
                                         **(spec_overrides or {}))
    lot = create_material_lot(api, spec["id"], lot_headers,
                              **(lot_overrides or {}))
    results = record_passing_material_tests(api, lot["id"], spec,
                                            analyst_headers)
    lot = ok(api.disposition_material_lot(
        lot["id"], f.material_lot_disposition_payload("QUALIFY"),
        releaser_headers))
    return {"spec": spec, "lot": lot, "results": results}


def material_lot_under_test(api, *, spec_overrides: Optional[dict] = None,
                            lot_overrides: Optional[dict] = None,
                            test_codes: Optional[Sequence[str]] = None) -> dict:
    """A raw material lot in ``UNDER_TEST`` with one passing measurement per
    requested code (defaulting to every required code).

    Returns ``{"spec", "lot", "results"}``.
    """
    spec = create_material_specification(api, **(spec_overrides or {}))
    lot = create_material_lot(api, spec["id"], **(lot_overrides or {}))
    codes = list(test_codes) if test_codes is not None \
        else list(spec["required_test_codes"])
    results = [record_material_measurement(api, lot["id"], code,
                                           passing_value_for(spec, code))
               for code in codes]
    return {"spec": spec, "lot": ok(api.get_material_lot(lot["id"], QC_ANALYST)),
            "results": results}


def material_lot_in_oos_investigation(api, *,
                                      spec_overrides: Optional[dict] = None,
                                      lot_overrides: Optional[dict] = None,
                                      failing_code: str = "PURITY") -> dict:
    """A raw material lot pushed to ``OOS_INVESTIGATION``: one failing
    measurement recorded, then an INVESTIGATE disposition.

    Returns ``{"spec", "lot", "failing_result"}``.
    """
    spec = create_material_specification(api, **(spec_overrides or {}))
    lot = create_material_lot(api, spec["id"], **(lot_overrides or {}))
    failing = record_material_measurement(api, lot["id"], failing_code,
                                          failing_value_for(spec, failing_code))
    lot = ok(api.disposition_material_lot(
        lot["id"], f.material_lot_disposition_payload("INVESTIGATE"),
        QA_RELEASER))
    return {"spec": spec, "lot": lot, "failing_result": failing}


# ---------------------------------------------------------------------------
# Design control, traceability and clearance
# ---------------------------------------------------------------------------
def product_specification_version(api, spec_id: str,
                                  headers=REGULATORY_AFFAIRS) -> int:
    """The parent's current ``version``, re-read before every design filing so
    the mandatory concurrency guard is never stale."""
    return ok(api.get_product_specification(spec_id, headers))["version"]


def create_product_specification(api, headers=REGULATORY_AFFAIRS,
                                 **overrides) -> dict:
    return created(api.create_product_specification(
        f.product_specification_payload(**overrides), headers))


def file_design_record(api, product_specification_id: str, record_type: str,
                       traces_to_record_id: Optional[str] = None,
                       headers=REGULATORY_AFFAIRS, **overrides) -> dict:
    """File one design-control artifact, reading the parent's version first."""
    expected = overrides.pop("expected_product_specification_version", None)
    if expected is None:
        expected = product_specification_version(api, product_specification_id)
    return created(api.create_design_control_record(
        f.design_control_record_payload(product_specification_id, record_type,
                                       expected,
                                       traces_to_record_id=traces_to_record_id,
                                       **overrides), headers))


def approve_design_record(api, record_id: str, headers=QA_RELEASER) -> dict:
    """Approve a design-control record.  The default approver's identity differs
    from the default author's, which is what duty separation requires."""
    return ok(api.approve_design_control_record(record_id, headers))


def design_history_file(api, product_specification_id: str,
                        author_headers=REGULATORY_AFFAIRS,
                        approver_headers=QA_RELEASER,
                        approve: bool = True) -> dict:
    """A four-artifact design history file: input, output, verification and
    validation, approved from the bottom of the trace upward when ``approve``.

    Returns ``{"design_input", "design_output", "verification", "validation"}``.
    """
    design_input = file_design_record(api, product_specification_id,
                                      "DESIGN_INPUT", headers=author_headers)
    design_output = file_design_record(api, product_specification_id,
                                       "DESIGN_OUTPUT",
                                       traces_to_record_id=design_input["id"],
                                       headers=author_headers)
    verification = file_design_record(api, product_specification_id,
                                      "VERIFICATION",
                                      traces_to_record_id=design_output["id"],
                                      headers=author_headers)
    validation = file_design_record(api, product_specification_id,
                                    "VALIDATION",
                                    traces_to_record_id=design_output["id"],
                                    headers=author_headers)
    if approve:
        design_input = approve_design_record(api, design_input["id"],
                                             approver_headers)
        design_output = approve_design_record(api, design_output["id"],
                                              approver_headers)
        verification = approve_design_record(api, verification["id"],
                                             approver_headers)
        validation = approve_design_record(api, validation["id"],
                                           approver_headers)
    return {"design_input": design_input, "design_output": design_output,
            "verification": verification, "validation": validation}


def cleared_product(api, *, product_overrides: Optional[dict] = None,
                    author_headers=REGULATORY_AFFAIRS,
                    approver_headers=QA_RELEASER) -> dict:
    """A product specification whose design trace is complete and whose
    clearance has been recorded, so ``clearance_status`` reads ``CLEARED``.

    Returns ``{"product", "records"}``.
    """
    product = create_product_specification(api, author_headers,
                                           **(product_overrides or {}))
    records = design_history_file(api, product["id"], author_headers,
                                  approver_headers)
    product = ok(api.record_product_clearance(product["id"],
                                              f.clearance_payload(),
                                              author_headers))
    return {"product": product, "records": records}


def manufacturing_setup(api, *, material_types: Sequence[str] = ("ANTIBODY",),
                        critical_types: Iterable[str] = (),
                        cleared: bool = True,
                        product_overrides: Optional[dict] = None,
                        material_spec_overrides: Optional[dict] = None,
                        material_lot_overrides: Optional[dict] = None) -> dict:
    """Everything a finished lot needs before it can be opened.

    One qualified raw material lot per entry in ``material_types``, and a
    product specification whose bill of materials names exactly those material
    codes.  ``critical_types`` marks which of those material specifications are
    critical, which is what drives the bridging flag later.

    Returns ``{"materials", "product", "records"}`` where ``materials`` is a
    list of ``{"spec", "lot", "results"}`` in the order requested.
    """
    critical = set(critical_types)
    materials = []
    for material_type in material_types:
        spec_overrides = {"material_type": material_type,
                          "is_critical": material_type in critical}
        spec_overrides.update(material_spec_overrides or {})
        materials.append(qualified_material(
            api, spec_overrides=spec_overrides,
            lot_overrides=material_lot_overrides))

    product_kwargs = {"required_material_codes":
                      [m["spec"]["material_code"] for m in materials]}
    product_kwargs.update(product_overrides or {})
    if cleared:
        bundle = cleared_product(api, product_overrides=product_kwargs)
        product, records = bundle["product"], bundle["records"]
    else:
        product = create_product_specification(api, **product_kwargs)
        records = {}
    return {"materials": materials, "product": product, "records": records}


# ---------------------------------------------------------------------------
# Finished lots and dispensing
# ---------------------------------------------------------------------------
def reagent_lot_version(api, lot_id: str, headers=PRODUCTION_OPERATOR) -> int:
    """The finished lot's current ``version``, re-read before every dispensing
    call so the mandatory concurrency guard is never stale."""
    return ok(api.get_reagent_lot(lot_id, headers))["version"]


def create_reagent_lot(api, product_specification_id: str,
                       headers=PRODUCTION_OPERATOR, **overrides) -> dict:
    return created(api.create_reagent_lot(
        f.reagent_lot_payload(product_specification_id, **overrides), headers))


def dispense_component(api, reagent_lot_id: str, material_lot_id: str,
                       component_role: str, quantity_used: Optional[float] = None,
                       headers=PRODUCTION_OPERATOR,
                       expected_reagent_lot_version: Optional[int] = None,
                       **overrides) -> dict:
    """Dispense one raw material lot into a finished lot, reading the parent's
    version first unless the caller pins it deliberately."""
    expected = expected_reagent_lot_version
    if expected is None:
        expected = reagent_lot_version(api, reagent_lot_id, headers)
    return created(api.add_reagent_lot_component(
        reagent_lot_id,
        f.lot_component_payload(material_lot_id, component_role, expected,
                                quantity_used=quantity_used, **overrides),
        headers))


def dispense_bill_of_materials(api, reagent_lot_id: str,
                               materials: Sequence[dict],
                               quantity_used: Optional[float] = None,
                               headers=PRODUCTION_OPERATOR) -> List[dict]:
    """One dispensing call per entry of a ``manufacturing_setup`` materials list,
    each filling the component role its own material type names."""
    rows = []
    for material in materials:
        rows.append(dispense_component(api, reagent_lot_id,
                                       material["lot"]["id"],
                                       material["spec"]["material_type"],
                                       quantity_used=quantity_used,
                                       headers=headers))
    return rows


def reagent_lot_with_bom(api, setup: Optional[dict] = None, *,
                         lot_overrides: Optional[dict] = None,
                         quantity_used: Optional[float] = None,
                         **setup_kwargs) -> dict:
    """A finished lot in ``PLANNED`` whose complete bill of materials has been
    dispensed.

    Returns the ``manufacturing_setup`` bundle extended with ``{"lot",
    "components"}``.
    """
    bundle = dict(setup if setup is not None
                  else manufacturing_setup(api, **setup_kwargs))
    lot = create_reagent_lot(api, bundle["product"]["id"],
                             **(lot_overrides or {}))
    components = dispense_bill_of_materials(api, lot["id"],
                                            bundle["materials"],
                                            quantity_used=quantity_used)
    bundle["lot"] = ok(api.get_reagent_lot(lot["id"], PRODUCTION_OPERATOR))
    bundle["components"] = components
    return bundle


# ---------------------------------------------------------------------------
# Filling runs and environmental monitoring
# ---------------------------------------------------------------------------
def schedule_fill_run(api, reagent_lot_id: str, headers=PRODUCTION_OPERATOR,
                      **overrides) -> dict:
    return created(api.create_fill_run(
        f.fill_run_payload(reagent_lot_id, **overrides), headers))


def start_fill_run(api, run_id: str, headers=PRODUCTION_OPERATOR) -> dict:
    return ok(api.start_fill_run(run_id, headers))


def record_monitoring_sample(api, run_id: str, sample_type: str,
                             result_value: float, headers=QC_ANALYST,
                             **overrides) -> dict:
    return created(api.create_monitoring_sample(
        run_id, f.monitoring_sample_payload(sample_type, result_value,
                                            **overrides), headers))


def conforming_value_for(sample_type: str) -> float:
    """A monitoring result at half the channel's action limit, so the sample is
    conforming."""
    return round(EM_ACTION_LIMITS[sample_type] / 2.0, 2)


def minor_excursion_value_for(sample_type: str) -> float:
    """A result above the action limit but below twice it, so the sample grades
    MINOR."""
    limit = EM_ACTION_LIMITS[sample_type]
    return round(limit + (limit / 4.0), 2)


def major_excursion_value_for(sample_type: str) -> float:
    """A result at exactly twice the action limit, the inclusive threshold at
    which a sample grades MAJOR."""
    return float(EM_ACTION_LIMITS[sample_type] * 2)


def record_bioburden_sample(api, run_id: str, result_value: Optional[float] = None,
                            headers=QC_ANALYST, **overrides) -> dict:
    """The bulk bioburden evidence a run cannot be completed without."""
    if result_value is None:
        result_value = conforming_value_for("BIOBURDEN_BULK")
    return record_monitoring_sample(api, run_id, "BIOBURDEN_BULK",
                                    result_value, headers, **overrides)


def complete_fill_run(api, run_id: str, filled_units: int,
                      headers=PRODUCTION_OPERATOR) -> dict:
    return ok(api.complete_fill_run(
        run_id, f.fill_run_complete_payload(filled_units), headers))


def abort_fill_run(api, run_id: str, abort_reason: str = "Line deviation",
                   headers=PRODUCTION_OPERATOR) -> dict:
    return ok(api.abort_fill_run(
        run_id, f.fill_run_abort_payload(abort_reason), headers))


def running_fill_run(api, setup: Optional[dict] = None, *,
                     lot_overrides: Optional[dict] = None,
                     run_overrides: Optional[dict] = None,
                     **setup_kwargs) -> dict:
    """A finished lot whose bill of materials is dispensed and whose filling run
    has been started, so the run is ``RUNNING`` and the lot ``IN_PROCESS``.

    Returns the ``reagent_lot_with_bom`` bundle extended with ``{"run"}``.
    """
    bundle = reagent_lot_with_bom(api, setup, lot_overrides=lot_overrides,
                                  **setup_kwargs)
    run = schedule_fill_run(api, bundle["lot"]["id"], **(run_overrides or {}))
    run = start_fill_run(api, run["id"])
    bundle["run"] = run
    bundle["lot"] = ok(api.get_reagent_lot(bundle["lot"]["id"],
                                            PRODUCTION_OPERATOR))
    return bundle


def filled_reagent_lot(api, setup: Optional[dict] = None, *,
                       lot_overrides: Optional[dict] = None,
                       run_overrides: Optional[dict] = None,
                       filled_units: Optional[int] = None,
                       bioburden_value: Optional[float] = None,
                       extra_samples: Sequence[tuple] = (),
                       **setup_kwargs) -> dict:
    """A finished lot carried to ``FILLED``: bill of materials dispensed, run
    started, bulk bioburden recorded, run completed.

    ``extra_samples`` is a sequence of ``(sample_type, result_value)`` pairs
    recorded against the run before it is completed, which is how a test drives
    the run's environmental state.

    Returns the bundle extended with ``{"run", "samples"}``.
    """
    bundle = running_fill_run(api, setup, lot_overrides=lot_overrides,
                              run_overrides=run_overrides, **setup_kwargs)
    run_id = bundle["run"]["id"]
    samples = [record_bioburden_sample(api, run_id, bioburden_value)]
    for sample_type, result_value in extra_samples:
        samples.append(record_monitoring_sample(api, run_id, sample_type,
                                                result_value))
    units = (bundle["run"]["planned_fill_units"] if filled_units is None
             else filled_units)
    bundle["run"] = complete_fill_run(api, run_id, units)
    bundle["samples"] = samples
    bundle["lot"] = ok(api.get_reagent_lot(bundle["lot"]["id"],
                                            PRODUCTION_OPERATOR))
    return bundle


# ---------------------------------------------------------------------------
# Release testing and the two-axis release decision
# ---------------------------------------------------------------------------
def record_release_measurement(api, reagent_lot_id: str, test_code: str,
                               measured_value: float = 100.00,
                               reference_measured_value: float = 100.00,
                               headers=QC_ANALYST, **overrides) -> dict:
    """A release measurement against the reference material.  The default pair
    is identical, so the computed bias is 0.00 and the outcome PASS."""
    return created(api.create_test_result(
        f.release_test_result_payload(reagent_lot_id, test_code, measured_value,
                                      reference_measured_value, **overrides),
        headers))


def record_passing_release_tests(api, reagent_lot_id: str, product: dict,
                                 headers=QC_ANALYST,
                                 measured_value: float = 100.00,
                                 reference_measured_value: float = 100.00
                                 ) -> List[dict]:
    """One passing measurement per code in the product's ``release_test_codes``,
    which is what a release decision demands."""
    return [record_release_measurement(api, reagent_lot_id, code,
                                       measured_value,
                                       reference_measured_value, headers)
            for code in product["release_test_codes"]]


def lot_under_release_test(api, setup: Optional[dict] = None, *,
                           analyst_headers=QC_ANALYST, **kwargs) -> dict:
    """A finished lot in ``UNDER_RELEASE_TEST`` with a passing measurement on
    every release test code.

    Returns the ``filled_reagent_lot`` bundle extended with
    ``{"release_results"}``.
    """
    bundle = filled_reagent_lot(api, setup, **kwargs)
    bundle["release_results"] = record_passing_release_tests(
        api, bundle["lot"]["id"], bundle["product"], analyst_headers)
    bundle["lot"] = ok(api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER))
    return bundle


def disposition_reagent_lot(api, lot_id: str, decision: str,
                            headers=QA_RELEASER, **overrides) -> dict:
    return ok(api.disposition_reagent_lot(
        lot_id, f.reagent_lot_disposition_payload(decision, **overrides),
        headers))


def set_distribution_status(api, lot_id: str, distribution_status: str,
                           headers=QA_RELEASER, **overrides) -> dict:
    return ok(api.set_reagent_lot_distribution_status(
        lot_id, f.distribution_status_payload(distribution_status, **overrides),
        headers))


def released_reagent_lot(api, setup: Optional[dict] = None, *,
                         shelf_life_basis: Optional[str] = None,
                         releaser_headers=QA_RELEASER, **kwargs) -> dict:
    """A finished lot carried to ``RELEASED``, which also puts its availability
    axis at ``AVAILABLE``.

    The default releasing identity differs from the analyst identity that
    recorded the release measurements, which is what duty separation requires.

    Returns the ``lot_under_release_test`` bundle with ``lot`` refreshed.
    """
    bundle = lot_under_release_test(api, setup, **kwargs)
    overrides = {} if shelf_life_basis is None \
        else {"shelf_life_basis": shelf_life_basis}
    bundle["lot"] = disposition_reagent_lot(api, bundle["lot"]["id"], "RELEASE",
                                            releaser_headers, **overrides)
    return bundle


def available_reagent_lot(api, setup: Optional[dict] = None, **kwargs) -> dict:
    """Alias for a released lot, whose availability axis the release cascade has
    already moved to ``AVAILABLE``."""
    return released_reagent_lot(api, setup, **kwargs)


# ---------------------------------------------------------------------------
# Stability programme
# ---------------------------------------------------------------------------
def create_stability_study(api, product_specification_id: str,
                           reagent_lot_id: str, headers=REGULATORY_AFFAIRS,
                           **overrides) -> dict:
    return created(api.create_stability_study(
        f.stability_study_payload(product_specification_id, reagent_lot_id,
                                  **overrides), headers))


def approve_stability_protocol(api, study_id: str, headers=QA_RELEASER) -> dict:
    return ok(api.approve_stability_protocol(study_id, headers))


def record_timepoint(api, stability_study_id: str, month_index: int,
                     measured_value: float, test_code: str = "ACTIVITY",
                     headers=QC_ANALYST, **overrides) -> dict:
    return created(api.create_test_result(
        f.stability_test_result_payload(stability_study_id, month_index,
                                       test_code, measured_value, **overrides),
        headers))


def conforming_timepoint_value(study: dict) -> float:
    """A measured value whose recovery against the study baseline is 95.00, so
    the timepoint conforms."""
    return round(float(study["baseline_value"]) * 0.95, 2)


def nonconforming_timepoint_value(study: dict) -> float:
    """A measured value whose recovery is 50.00, well under the conforming
    floor."""
    return round(float(study["baseline_value"]) * 0.50, 2)


def approved_stability_study(api, product_specification_id: str,
                             reagent_lot_id: str,
                             study_overrides: Optional[dict] = None) -> dict:
    """A stability protocol in ``APPROVED``, ready for timepoints."""
    study = create_stability_study(api, product_specification_id,
                                   reagent_lot_id, **(study_overrides or {}))
    return approve_stability_protocol(api, study["id"])


def stability_study_in_progress(api, product_specification_id: str,
                                reagent_lot_id: str,
                                conforming_months: Sequence[int] = (0,),
                                study_overrides: Optional[dict] = None) -> dict:
    """A stability study in ``IN_PROGRESS`` with a conforming timepoint at each
    month in ``conforming_months``."""
    study = create_stability_study(api, product_specification_id,
                                   reagent_lot_id, **(study_overrides or {}))
    approve_stability_protocol(api, study["id"])
    value = conforming_timepoint_value(study)
    for month in conforming_months:
        record_timepoint(api, study["id"], month, value)
    return ok(api.get_stability_study(study["id"], REGULATORY_AFFAIRS))


def complete_stability_study(api, product_specification_id: str,
                             reagent_lot_id: str,
                             conforming_months: Sequence[int] = (0,),
                             study_overrides: Optional[dict] = None,
                             headers=REGULATORY_AFFAIRS) -> dict:
    """A stability study carried to ``COMPLETE``, so its established shelf life
    is available to a release decision."""
    study = stability_study_in_progress(api, product_specification_id,
                                        reagent_lot_id, conforming_months,
                                        study_overrides)
    return ok(api.conclude_stability_study(study["id"], headers))


# ---------------------------------------------------------------------------
# Bridging studies
# ---------------------------------------------------------------------------
def create_bridging_study(api, predicate_lot_id: str, candidate_lot_id: str,
                          changed_material_lot_id: str,
                          paired_test_codes: Optional[Sequence[str]] = None,
                          headers=REGULATORY_AFFAIRS, **overrides) -> dict:
    return created(api.create_bridging_study(
        f.bridging_study_payload(predicate_lot_id, candidate_lot_id,
                                 changed_material_lot_id,
                                 paired_test_codes=paired_test_codes,
                                 **overrides), headers))


def decide_bridging_study(api, study_id: str, decision: str,
                          headers=QA_RELEASER, **overrides) -> dict:
    return ok(api.decide_bridging_study(
        study_id, f.bridging_decision_payload(decision, **overrides), headers))


def qualified_material_lot_for_spec(api, spec: dict, **lot_overrides) -> dict:
    """A second (or later) raw material lot booked in against an existing
    specification and carried to ``QUALIFIED``.  Its ``vendor_lot_code`` is
    fresh, which is what makes it a *changed* material relative to an earlier
    lot of the same specification."""
    lot = create_material_lot(api, spec["id"], **lot_overrides)
    record_passing_material_tests(api, lot["id"], spec)
    return ok(api.disposition_material_lot(
        lot["id"], f.material_lot_disposition_payload("QUALIFY"), QA_RELEASER))


def bridging_candidate(api, *, releaser_headers=QA_RELEASER) -> dict:
    """A predicate lot already ``RELEASED`` and a candidate lot of the same
    product built from a *different* vendor lot of the same critical material,
    carried to ``UNDER_RELEASE_TEST`` with passing measurements on every release
    test code.

    Returns ``{"setup", "product", "predicate", "candidate", "changed_material",
    "original_material"}``.
    """
    setup = manufacturing_setup(api, material_types=("ANTIBODY",),
                                critical_types=("ANTIBODY",))
    predicate_bundle = released_reagent_lot(api, setup=setup,
                                            releaser_headers=releaser_headers)
    material_spec = setup["materials"][0]["spec"]
    changed_material = qualified_material_lot_for_spec(api, material_spec)

    candidate = create_reagent_lot(api, setup["product"]["id"])
    dispense_component(api, candidate["id"], changed_material["id"], "ANTIBODY")
    run = schedule_fill_run(api, candidate["id"])
    start_fill_run(api, run["id"])
    record_bioburden_sample(api, run["id"])
    complete_fill_run(api, run["id"], run["planned_fill_units"])
    record_passing_release_tests(api, candidate["id"], setup["product"])
    return {
        "setup": setup,
        "product": setup["product"],
        "predicate": predicate_bundle["lot"],
        "candidate": ok(api.get_reagent_lot(candidate["id"], QA_RELEASER)),
        "changed_material": changed_material,
        "original_material": setup["materials"][0]["lot"],
    }


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------
def create_complaint(api, reagent_lot_id: str, headers=REGULATORY_AFFAIRS,
                     **overrides) -> dict:
    return created(api.create_complaint(
        f.complaint_payload(reagent_lot_id, **overrides), headers))


def triage_complaint(api, complaint_id: str, severity: str = "HIGH",
                     malfunction_suspected: bool = True,
                     headers=REGULATORY_AFFAIRS, **overrides) -> dict:
    return ok(api.triage_complaint(
        complaint_id, f.triage_payload(severity, malfunction_suspected,
                                       **overrides), headers))


def file_malfunction_report(api, complaint_id: str,
                            headers=REGULATORY_AFFAIRS, **overrides) -> dict:
    return ok(api.file_malfunction_report(
        complaint_id, f.malfunction_report_payload(**overrides), headers))


def decide_field_action(api, complaint_id: str, field_action: str,
                        headers=QA_RELEASER_2, **overrides) -> dict:
    """Decide the field action.  The default deciding identity differs from the
    identity that released a lot through ``released_reagent_lot``, which is what
    duty separation requires."""
    return ok(api.decide_field_action(
        complaint_id, f.field_action_payload(field_action, **overrides), headers))


def triaged_complaint(api, reagent_lot_id: str, severity: str = "HIGH",
                      malfunction_suspected: bool = True,
                      device_related_death_or_injury: Optional[bool] = None,
                      complaint_overrides: Optional[dict] = None) -> dict:
    """A complaint booked and triaged in one step."""
    overrides = dict(complaint_overrides or {})
    if device_related_death_or_injury is not None:
        overrides["device_related_death_or_injury"] = \
            device_related_death_or_injury
    complaint = create_complaint(api, reagent_lot_id, **overrides)
    return triage_complaint(api, complaint["id"], severity,
                            malfunction_suspected)


def complaint_on_released_lot(api, *, severity: str = "HIGH",
                              malfunction_suspected: bool = True,
                              device_related_death_or_injury: Optional[bool] = None,
                              setup: Optional[dict] = None, **kwargs) -> dict:
    """A released finished lot with a triaged complaint against it — the state
    from which the field-action branch and the recall cascade run.

    Returns the ``released_reagent_lot`` bundle extended with ``{"complaint"}``.
    """
    bundle = released_reagent_lot(api, setup, **kwargs)
    bundle["complaint"] = triaged_complaint(
        api, bundle["lot"]["id"], severity, malfunction_suspected,
        device_related_death_or_injury)
    return bundle


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------
def create_distribution_order(api, product_specification_id: str,
                              headers=DISTRIBUTION_PLANNER, **overrides) -> dict:
    return created(api.create_distribution_order(
        f.distribution_order_payload(product_specification_id, **overrides),
        headers))


def allocate_order(api, order_id: str, headers=DISTRIBUTION_PLANNER) -> dict:
    return ok(api.allocate_distribution_order(order_id, headers))


def order_allocations(api, order_id: str,
                      headers=DISTRIBUTION_PLANNER) -> List[dict]:
    response = api.list_distribution_order_allocations(order_id, headers)
    return get_success_data(response, HTTP_OK)


def ship_allocation(api, allocation_id: str,
                    headers=DISTRIBUTION_PLANNER) -> dict:
    return ok(api.ship_allocation(allocation_id, headers))


def cancel_allocation(api, allocation_id: str,
                      reason: str = "Customer cancelled",
                      headers=DISTRIBUTION_PLANNER) -> dict:
    return ok(api.cancel_allocation(
        allocation_id, headers, f.cancel_allocation_payload(reason)))


def record_cold_chain_event(api, allocation_id: str, excursion_minutes: float,
                            max_temp_c: float,
                            delivery_confirmed: Optional[bool] = None,
                            headers=DISTRIBUTION_PLANNER, **overrides) -> dict:
    return ok(api.create_cold_chain_event(
        allocation_id, f.cold_chain_event_payload(
            excursion_minutes, max_temp_c,
            delivery_confirmed=delivery_confirmed, **overrides), headers))


def allocated_order(api, setup: Optional[dict] = None, *,
                    order_overrides: Optional[dict] = None,
                    requested_units: Optional[int] = None, **kwargs) -> dict:
    """A released, available finished lot with a customer order allocated
    against it.

    Returns the ``released_reagent_lot`` bundle extended with ``{"order",
    "allocations"}``.
    """
    bundle = released_reagent_lot(api, setup, **kwargs)
    overrides = dict(order_overrides or {})
    if requested_units is not None:
        overrides["requested_units"] = requested_units
    order = create_distribution_order(api, bundle["product"]["id"], **overrides)
    bundle["order"] = allocate_order(api, order["id"])
    bundle["allocations"] = order_allocations(api, order["id"])
    bundle["lot"] = ok(api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER))
    return bundle


def shipped_allocation(api, setup: Optional[dict] = None, **kwargs) -> dict:
    """An allocated order whose first reservation has been shipped, which is the
    only state from which a cold-chain event may be recorded.

    Returns the ``allocated_order`` bundle extended with ``{"allocation"}``.
    """
    bundle = allocated_order(api, setup, **kwargs)
    first = bundle["allocations"][0]
    bundle["allocation"] = ship_allocation(api, first["id"])
    bundle["order"] = ok(api.get_distribution_order(bundle["order"]["id"],
                                                    DISTRIBUTION_PLANNER))
    bundle["lot"] = ok(api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER))
    return bundle
