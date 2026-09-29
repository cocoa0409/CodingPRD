"""Composite setup builders.

These are plain functions rather than pytest fixtures so they compose freely:
each tier calls the tier below it, every one accepts `**overrides` for the
payload it owns, and all of them validate leniently with `get_success_data`
so a setup failure surfaces as a setup error rather than a masked assertion.

Ownership is threaded explicitly: any call gated on owning a property goes
through `make_property_owner_headers(property_id)`, so two properties in one
test always act under two distinct `X-User-ID` values.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import constants as K
from . import factories as F
from .test_users import (
    make_appeals_officer_headers,
    make_housing_agency_inspector_headers,
    make_maintenance_technician_headers,
    make_platform_admin_headers,
    make_property_owner_headers,
    make_quality_assurance_reviewer_headers,
)
from .types import Headers, Payload

ADMIN: Headers = make_platform_admin_headers()
INSPECTOR: Headers = make_housing_agency_inspector_headers()
TECHNICIAN: Headers = make_maintenance_technician_headers()
REVIEWER: Headers = make_quality_assurance_reviewer_headers()
APPEALS: Headers = make_appeals_officer_headers()


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def advance_clock(api: Any, current_utc: str) -> None:
    """Move the server's logical clock to `current_utc`."""
    get_success_data(api.set_clock(F.clock_payload(current_utc), ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------
def draft_standard(
    api: Any,
    definition_codes: Sequence[str] = ("LT_GAS", "SEV_WINDOW"),
    **overrides: Any
) -> Dict[str, Any]:
    """A DRAFT standard plus one defect definition per requested code."""
    standard = get_success_data(
        api.create_standard(F.standard_payload(**overrides), ADMIN)
    )
    definitions: Dict[str, Dict[str, Any]] = {}
    for code in definition_codes:
        definitions[code] = get_success_data(
            api.create_defect_definition(
                F.defect_definition_payload(standard["id"], code), ADMIN
            )
        )
    if definition_codes:
        # Each definition made the standard recompute defect_definition_count and
        # life_threatening_definition_count, so the creation-time snapshot is stale;
        # re-read it so callers observe the standard's current version.
        standard = get_success_data(api.get_standard(standard["id"], ADMIN))
    return {
        "standard": standard,
        "standard_id": standard["id"],
        "definitions": definitions,
        "definition_ids": {
            code: row["id"] for code, row in definitions.items()
        },
    }


def adopted_standard(
    api: Any,
    definition_codes: Sequence[str] = ("LT_GAS", "SEV_WINDOW"),
    adopted_at: str = K.ADOPTED_AT,
    **overrides: Any
) -> Dict[str, Any]:
    """An ADOPTED standard, which is the only kind an inspection may cite."""
    bundle = draft_standard(api, definition_codes, **overrides)
    bundle["standard"] = get_success_data(
        api.adopt_standard(
            bundle["standard_id"], F.adopt_payload(adopted_at=adopted_at), ADMIN
        )
    )
    return bundle


def create_property(
    api: Any, blueprint: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_property(F.property_payload(blueprint, **overrides), ADMIN)
    )


def create_units(
    api: Any, property_id: str, unit_specs: Sequence[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Create units from a list of specs, keyed by their unit_number."""
    units: Dict[str, Dict[str, Any]] = {}
    for spec in unit_specs:
        spec = dict(spec)
        unit_number = spec.pop("unit_number")
        units[unit_number] = get_success_data(
            api.create_unit(F.unit_payload(property_id, unit_number, **spec), ADMIN)
        )
    return units


def property_with_units(
    api: Any,
    blueprint: Optional[Dict[str, Any]] = None,
    unit_specs: Optional[Sequence[Dict[str, Any]]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """A property, its units, and the owner headers whose id is the property id."""
    row = create_property(api, blueprint, **overrides)
    if unit_specs is None:
        unit_specs = [{"unit_number": "101", "bedroom_count": 1}]
    units = create_units(api, row["id"], unit_specs)
    return {
        "property": row,
        "property_id": row["id"],
        "owner_headers": make_property_owner_headers(row["id"]),
        "units": units,
        "unit_ids": {number: unit["id"] for number, unit in units.items()},
    }


# ---------------------------------------------------------------------------
# Reads used to thread ids and versions
# ---------------------------------------------------------------------------
def read_property(api: Any, property_id: str, headers: Optional[Headers] = None) -> Dict[str, Any]:
    return get_success_data(api.get_property(property_id, headers or ADMIN))


def read_unit(api: Any, unit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_unit(unit_id, ADMIN))


def read_inspection(api: Any, inspection_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inspection(inspection_id, INSPECTOR))


def read_sweep(api: Any, sweep_id: str, headers: Optional[Headers] = None) -> Dict[str, Any]:
    return get_success_data(api.get_sweep(sweep_id, headers or ADMIN))


def read_work_order(api: Any, work_order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_work_order(work_order_id, ADMIN))


def read_deficiency(api: Any, deficiency_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_deficiency(deficiency_id, ADMIN))


def read_appeal(api: Any, appeal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_appeal(appeal_id, ADMIN))


def read_cap(api: Any, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cap(plan_id, ADMIN))


def read_selection(api: Any, selection_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_sample_selection(selection_id, INSPECTOR))


def list_selections(api: Any, inspection_id: str, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_sample_selections(INSPECTOR, inspection_id=inspection_id, **params)
    )


def selections_by_unit(api: Any, inspection_id: str) -> Dict[str, Dict[str, Any]]:
    """Index this inspection's ACTIVE sample slots by the unit they hold."""
    rows = list_selections(api, inspection_id, limit=K.MAX_LIMIT)
    return {
        row["unit_id"]: row
        for row in rows
        if row["selection_status"] == "ACTIVE"
    }


# ---------------------------------------------------------------------------
# Tier 1: inspection state progression
# ---------------------------------------------------------------------------
def scheduled_inspection(
    api: Any, property_id: str, standard_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_inspection(
            F.inspection_payload(property_id, standard_id, **overrides), INSPECTOR
        )
    )


def sampled_inspection(
    api: Any,
    property_id: str,
    standard_id: str,
    drawn_at: str = K.DRAWN_AT,
    **overrides: Any
) -> Dict[str, Any]:
    """A SAMPLED inspection together with the slots the draw produced."""
    inspection = scheduled_inspection(api, property_id, standard_id, **overrides)
    inspection = get_success_data(
        api.draw_sample(
            inspection["id"], F.draw_sample_payload(drawn_at=drawn_at), INSPECTOR
        )
    )
    return {
        "inspection": inspection,
        "inspection_id": inspection["id"],
        "slots": selections_by_unit(api, inspection["id"]),
    }


def noticed_inspection(
    api: Any,
    property_id: str,
    standard_id: str,
    notified_at: str = K.NOTIFIED_AT,
    access_window_start: str = K.ACCESS_WINDOW_START,
    access_window_end: str = K.ACCESS_WINDOW_END,
    drawn_at: str = K.DRAWN_AT,
    **overrides: Any
) -> Dict[str, Any]:
    """Every ACTIVE slot noticed by the owner, which bubbles it to NOTIFIED."""
    bundle = sampled_inspection(
        api, property_id, standard_id, drawn_at=drawn_at, **overrides
    )
    owner_headers = make_property_owner_headers(property_id)
    for slot in bundle["slots"].values():
        get_success_data(
            api.issue_notice(
                slot["id"],
                F.notice_payload(
                    notified_at=notified_at,
                    access_window_start=access_window_start,
                    access_window_end=access_window_end,
                ),
                owner_headers,
            )
        )
    bundle["slots"] = selections_by_unit(api, bundle["inspection_id"])
    bundle["inspection"] = read_inspection(api, bundle["inspection_id"])
    return bundle


def in_progress_inspection(
    api: Any,
    property_id: str,
    standard_id: str,
    started_at: str = K.INSPECTION_STARTED_AT,
    **overrides: Any
) -> Dict[str, Any]:
    bundle = noticed_inspection(api, property_id, standard_id, **overrides)
    bundle["inspection"] = get_success_data(
        api.start_inspection(
            bundle["inspection_id"],
            F.start_inspection_payload(started_at=started_at),
            INSPECTOR,
        )
    )
    return bundle


def inspection_with_access(
    api: Any,
    property_id: str,
    standard_id: str,
    access_results: Optional[Dict[str, str]] = None,
    recorded_at: str = K.ACCESS_RECORDED_AT,
    **overrides: Any
) -> Dict[str, Any]:
    """An IN_PROGRESS inspection with entry recorded on every ACTIVE slot.

    `access_results` maps a unit id to GRANTED or REFUSED; omitted units are
    GRANTED.
    """
    bundle = in_progress_inspection(api, property_id, standard_id, **overrides)
    results = access_results or {}
    for unit_id, slot in list(bundle["slots"].items()):
        result = results.get(unit_id, "GRANTED")
        get_success_data(
            api.record_access(
                slot["id"],
                F.access_payload(result, recorded_at=recorded_at),
                INSPECTOR,
            )
        )
    bundle["slots"] = selections_by_unit(api, bundle["inspection_id"])
    bundle["inspection"] = read_inspection(api, bundle["inspection_id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 4: accumulating deficiencies against one inspection
# ---------------------------------------------------------------------------
def record_deficiencies(
    api: Any,
    inspection_id: str,
    specs: Sequence[Dict[str, Any]],
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Record deficiencies in order, threading the optimistic-concurrency token.

    Each spec carries `defect_definition_id` and optionally `unit_id`,
    `inspectable_area`, `observed_at` and `supersedes_deficiency_id`. The token
    for the first call is read from the inspection unless supplied; every later
    call reuses the `inspection_version_after_record` the previous one returned.
    """
    version = (
        expected_version
        if expected_version is not None
        else read_inspection(api, inspection_id)["version"]
    )
    rows: List[Dict[str, Any]] = []
    default_instants = (
        K.OBSERVED_AT_1,
        K.OBSERVED_AT_2,
        K.OBSERVED_AT_3,
        K.OBSERVED_AT_4,
        K.OBSERVED_AT_5,
    )
    for index, spec in enumerate(specs):
        spec = dict(spec)
        definition_id = spec.pop("defect_definition_id")
        unit_id = spec.pop("unit_id", None)
        area = spec.pop("inspectable_area", "UNIT")
        spec.setdefault(
            "observed_at", default_instants[min(index, len(default_instants) - 1)]
        )
        row = get_success_data(
            api.record_deficiency(
                inspection_id,
                F.deficiency_payload(version, definition_id, unit_id, area, **spec),
                INSPECTOR,
            )
        )
        rows.append(row)
        version = row["inspection_version_after_record"]
    return {"deficiencies": rows, "version": version}


# ---------------------------------------------------------------------------
# Tier 5: scoring, finalization and the plan chain
# ---------------------------------------------------------------------------
def scored_inspection(
    api: Any, inspection_id: str, scored_at: str = K.SCORED_AT, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.score_inspection(
            inspection_id, F.score_payload(scored_at=scored_at, **overrides), INSPECTOR
        )
    )


def finalized_inspection(
    api: Any, inspection_id: str, finalized_at: str = K.FINALIZED_AT, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.finalize_inspection(
            inspection_id,
            F.finalize_payload(finalized_at=finalized_at, **overrides),
            INSPECTOR,
        )
    )


def submitted_cap(
    api: Any, inspection_id: str, property_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_cap(
            F.cap_payload(inspection_id, **overrides),
            make_property_owner_headers(property_id),
        )
    )


def approved_cap(
    api: Any,
    inspection_id: str,
    property_id: str,
    decided_at: str = K.CAP_DECIDED_AT,
    **overrides: Any
) -> Dict[str, Any]:
    plan = submitted_cap(api, inspection_id, property_id, **overrides)
    return get_success_data(
        api.review_cap(
            plan["id"], F.cap_review_payload("APPROVED", decided_at=decided_at), REVIEWER
        )
    )


def filed_appeal(
    api: Any,
    inspection_id: str,
    property_id: str,
    contested_deficiency_id: str,
    appeal_type: str = "TECHNICAL_ERROR",
    **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_appeal(
            F.appeal_payload(
                inspection_id, contested_deficiency_id, appeal_type, **overrides
            ),
            make_property_owner_headers(property_id),
        )
    )


def returned_appeal(
    api: Any,
    inspection_id: str,
    property_id: str,
    contested_deficiency_id: str,
    appeal_type: str = "TECHNICAL_ERROR",
    decided_at: str = K.APPEAL_DECIDED_AT,
    **overrides: Any
) -> Dict[str, Any]:
    """An appeal parked in RETURNED_FOR_INFO, the only resubmittable status."""
    appeal = filed_appeal(
        api, inspection_id, property_id, contested_deficiency_id, appeal_type, **overrides
    )
    return get_success_data(
        api.review_appeal(
            appeal["id"],
            F.appeal_review_payload("RETURNED_FOR_INFO", decided_at=decided_at),
            APPEALS,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: sweep state progression
# ---------------------------------------------------------------------------
def planned_sweep(api: Any, property_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_sweep(
            F.sweep_payload(property_id, **overrides),
            make_property_owner_headers(property_id),
        )
    )


def in_progress_sweep(
    api: Any,
    property_id: str,
    started_at: str = K.SWEEP_STARTED_AT,
    **overrides: Any
) -> Dict[str, Any]:
    """An IN_PROGRESS sweep plus the version a first finding must present."""
    sweep = planned_sweep(api, property_id, **overrides)
    sweep = get_success_data(
        api.start_sweep(
            sweep["id"],
            F.sweep_start_payload(started_at=started_at),
            make_property_owner_headers(property_id),
        )
    )
    return {
        "sweep": sweep,
        "sweep_id": sweep["id"],
        "sweep_version": sweep["version"],
    }


def record_finding(
    api: Any,
    property_id: str,
    sweep_id: str,
    sweep_version: int,
    defect_definition_id: str,
    unit_id: Optional[str] = None,
    inspectable_area: str = "UNIT",
    observed_at: str = K.SWEEP_OBSERVED_AT_1,
    **overrides: Any
) -> Dict[str, Any]:
    """Record one finding and return the work order it created.

    The endpoint answers with the WorkOrder, so the deficiency it remediates is
    reached through the returned `deficiency_id`.
    """
    work_order = get_success_data(
        api.record_finding(
            sweep_id,
            F.finding_payload(
                sweep_version,
                defect_definition_id,
                unit_id,
                inspectable_area,
                observed_at=observed_at,
                **overrides
            ),
            make_property_owner_headers(property_id),
        )
    )
    return {
        "work_order": work_order,
        "work_order_id": work_order["id"],
        "deficiency_id": work_order["deficiency_id"],
        "sweep_version": read_sweep(api, sweep_id)["version"],
    }


def sweep_with_finding(
    api: Any,
    property_id: str,
    defect_definition_id: str,
    unit_id: Optional[str] = None,
    inspectable_area: str = "UNIT",
    observed_at: str = K.SWEEP_OBSERVED_AT_1,
    **overrides: Any
) -> Dict[str, Any]:
    """An IN_PROGRESS sweep that has already generated one work order."""
    bundle = in_progress_sweep(api, property_id, **overrides)
    finding = record_finding(
        api,
        property_id,
        bundle["sweep_id"],
        bundle["sweep_version"],
        defect_definition_id,
        unit_id,
        inspectable_area,
        observed_at,
    )
    bundle.update(finding)
    bundle["sweep"] = read_sweep(api, bundle["sweep_id"])
    return bundle


def completed_work_order(
    api: Any,
    work_order_id: str,
    headers: Optional[Headers] = None,
    completed_at: str = K.WORK_ORDER_COMPLETED_AT,
    **overrides: Any
) -> Dict[str, Any]:
    """A REPAIRED work order; the acting user id is stored for segregation."""
    return get_success_data(
        api.complete_work_order(
            work_order_id,
            F.work_order_complete_payload(completed_at=completed_at, **overrides),
            headers or TECHNICIAN,
        )
    )


def verified_work_order(
    api: Any,
    work_order_id: str,
    headers: Optional[Headers] = None,
    verified_at: str = K.WORK_ORDER_VERIFIED_AT,
    **overrides: Any
) -> Dict[str, Any]:
    """A work order whose closure a second user has verified as PASSED."""
    completed_work_order(api, work_order_id)
    return get_success_data(
        api.verify_work_order_closure(
            work_order_id,
            F.verify_closure_payload("PASSED", verified_at=verified_at, **overrides),
            headers or REVIEWER,
        )
    )


# ---------------------------------------------------------------------------
# Capital needs
# ---------------------------------------------------------------------------
def inject_history(
    api: Any,
    property_id: str,
    standard_id: str,
    finalized_at: str,
    defect_definition_ids: Sequence[str],
    unit_id: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Inject one already-CLOSED historical inspection with VERIFIED rows."""
    return get_success_data(
        api.inject_completed_inspection_history(
            F.history_payload(
                property_id,
                standard_id,
                finalized_at,
                list(defect_definition_ids),
                unit_id,
                **overrides
            ),
            ADMIN,
        )
    )


def recompute_capital_needs(
    api: Any,
    property_id: str,
    recurrence_basis: str = "CALENDAR_SCOPED",
    expected_property_version: Optional[int] = None,
    **overrides: Any
) -> List[Dict[str, Any]]:
    """Recompute the plan, reading the property version for the token."""
    version = (
        expected_property_version
        if expected_property_version is not None
        else read_property(api, property_id)["version"]
    )
    return get_success_data(
        api.recompute_capital_needs(
            F.capital_recompute_payload(
                property_id, version, recurrence_basis=recurrence_basis, **overrides
            ),
            make_property_owner_headers(property_id),
        )
    )


def active_capital_items(api: Any, property_id: str) -> List[Dict[str, Any]]:
    """The ACTIVE generation of capital need items for a property."""
    rows = get_success_data(
        api.list_capital_needs(ADMIN, property_id=property_id, limit=K.MAX_LIMIT)
    )
    return [row for row in rows if row["status"] == "ACTIVE"]


def capital_items_by_status(
    api: Any, property_id: str, status: str
) -> List[Dict[str, Any]]:
    """One generation of capital need items, read through the status filter."""
    return get_success_data(
        api.list_capital_needs(
            ADMIN, property_id=property_id, status=status, limit=K.MAX_LIMIT
        )
    )


def read_capital_item(api: Any, item_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_capital_need(item_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: whole-lifecycle shortcuts
# ---------------------------------------------------------------------------
def ready_to_record(
    api: Any,
    blueprint: Optional[Dict[str, Any]] = None,
    unit_specs: Optional[Sequence[Dict[str, Any]]] = None,
    definition_codes: Sequence[str] = ("LT_GAS", "SEV_WINDOW"),
    access_results: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Everything needed before the first deficiency: standard, property with
    units, and an IN_PROGRESS inspection whose slots have entry recorded."""
    bundle = adopted_standard(api, definition_codes)
    bundle.update(property_with_units(api, blueprint, unit_specs))
    bundle.update(
        inspection_with_access(
            api,
            bundle["property_id"],
            bundle["standard_id"],
            access_results=access_results,
            **overrides
        )
    )
    return bundle


def scored_lifecycle(
    api: Any,
    specs: Optional[Sequence[Dict[str, Any]]] = None,
    blueprint: Optional[Dict[str, Any]] = None,
    unit_specs: Optional[Sequence[Dict[str, Any]]] = None,
    definition_codes: Sequence[str] = ("LT_GAS", "SEV_WINDOW"),
    deficiency_code: str = "SEV_WINDOW",
    deficiency_count: int = 2,
    scored_at: str = K.SCORED_AT,
    **overrides: Any
) -> Dict[str, Any]:
    """A SCORED inspection carrying `deficiency_count` deficiencies.

    By default the deficiencies are SEVERE, so no life-threatening row can block
    scoring; `specs` overrides the default set outright.
    """
    bundle = ready_to_record(
        api, blueprint, unit_specs, definition_codes, **overrides
    )
    unit_id = sorted(bundle["unit_ids"].items())[0][1]
    if specs is None:
        specs = [
            {
                "defect_definition_id": bundle["definition_ids"][deficiency_code],
                "unit_id": unit_id,
            }
            for _ in range(deficiency_count)
        ]
    recorded = record_deficiencies(api, bundle["inspection_id"], specs)
    bundle["deficiencies"] = recorded["deficiencies"]
    bundle["deficiency_ids"] = [row["id"] for row in recorded["deficiencies"]]
    bundle["inspection"] = scored_inspection(
        api, bundle["inspection_id"], scored_at=scored_at
    )
    return bundle


def finalized_lifecycle(
    api: Any, finalized_at: str = K.FINALIZED_AT, **kwargs: Any
) -> Dict[str, Any]:
    """A SCORED inspection carried through finalization."""
    bundle = scored_lifecycle(api, **kwargs)
    bundle["inspection"] = finalized_inspection(
        api, bundle["inspection_id"], finalized_at=finalized_at
    )
    return bundle


def cap_approved_lifecycle(
    api: Any,
    finalized_at: str = K.FINALIZED_AT,
    decided_at: str = K.CAP_DECIDED_AT,
    cap_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any
) -> Dict[str, Any]:
    """A finalized inspection whose corrective action plan is APPROVED."""
    bundle = finalized_lifecycle(api, finalized_at=finalized_at, **kwargs)
    bundle["plan"] = approved_cap(
        api,
        bundle["inspection_id"],
        bundle["property_id"],
        decided_at=decided_at,
        **(cap_overrides or {})
    )
    bundle["plan_id"] = bundle["plan"]["id"]
    bundle["inspection"] = read_inspection(api, bundle["inspection_id"])
    return bundle


def sweep_lifecycle(
    api: Any,
    defect_code: str = "SEV_WINDOW",
    blueprint: Optional[Dict[str, Any]] = None,
    unit_specs: Optional[Sequence[Dict[str, Any]]] = None,
    definition_codes: Sequence[str] = ("LT_GAS", "SEV_WINDOW"),
    inspectable_area: str = "UNIT",
    observed_at: str = K.SWEEP_OBSERVED_AT_1,
    **overrides: Any
) -> Dict[str, Any]:
    """A property whose IN_PROGRESS sweep has raised one work order."""
    bundle = adopted_standard(api, definition_codes)
    bundle.update(property_with_units(api, blueprint, unit_specs))
    unit_id = (
        sorted(bundle["unit_ids"].items())[0][1] if inspectable_area == "UNIT" else None
    )
    bundle.update(
        sweep_with_finding(
            api,
            bundle["property_id"],
            bundle["definition_ids"][defect_code],
            unit_id,
            inspectable_area,
            observed_at,
            **overrides
        )
    )
    bundle["deficiency"] = read_deficiency(api, bundle["deficiency_id"])
    return bundle
