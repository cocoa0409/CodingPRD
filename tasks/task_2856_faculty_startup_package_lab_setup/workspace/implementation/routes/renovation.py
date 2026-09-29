"""Renovation projects, construction phases and cost reconciliation (PRD 3.6)."""

from datetime import date

from flask import Blueprint

import authz
import cascades
import derive
import envelope
import ledger
import lookups
import money
import serialize
import store
import validate
from errors import fail

bp = Blueprint("renovation", __name__)

SCOPE_TIERS = ("COSMETIC", "MODERATE", "GUT")
PROJECT_STATUSES = (
    "SCOPING",
    "BID",
    "AWARDED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
)
PHASE_STATUSES = ("PENDING", "ACTIVE", "COMPLETE")

READ_ROLES = (
    authz.ROLE_FACILITIES,
    authz.ROLE_DEAN_OFFICE,
    authz.ROLE_DEAN,
    authz.ROLE_DEPARTMENT_CHAIR,
)


def _phase_package(project):
    return store.db.packages.get(project["package_id"])


def _validate_plan(phases):
    """PRD 3.6 plan validation, reported in the global ladder order 26-28."""
    for index, first in enumerate(phases):
        for second in phases[index + 1:]:
            if (
                first["planned_start"] <= second["planned_end"]
                and second["planned_start"] <= first["planned_end"]
            ):
                fail(
                    "ERR_PHASE_WINDOW_OVERLAP",
                    "two construction phases occupy overlapping closed windows",
                )
    ordered = sorted(phases, key=lambda p: int(p["sequence_no"]))
    for earlier, later in zip(ordered, ordered[1:]):
        gap = (
            date.fromisoformat(later["planned_start"][:10])
            - date.fromisoformat(earlier["planned_end"][:10])
        ).days
        if gap < money.PHASE_BUFFER_DAYS:
            fail(
                "ERR_PHASE_BUFFER_VIOLATION",
                "consecutive phases need at least %d calendar days of changeover"
                % money.PHASE_BUFFER_DAYS,
            )
    sequences = sorted(int(p["sequence_no"]) for p in phases)
    if sequences != list(range(1, len(sequences) + 1)):
        fail(
            "ERR_PHASE_SEQUENCE_GAP",
            "phase sequence_no values must form the contiguous run 1..N",
        )


def _subsidy_cents(scope_tier, base_cents):
    """Round half up to whole cents first, then clamp to the standing ceiling."""
    raw = money.pct_of_cents(base_cents, money.RENOVATION_SUBSIDY_PCT[scope_tier])
    return min(raw, money.RENOVATION_SUBSIDY_CAP_CENTS)


@bp.post("/renovation-projects")
def create_project():
    authz.actor((authz.ROLE_FACILITIES,))
    payload = validate.body()
    package_id = validate.identifier(payload, "package_id")
    space_id = validate.identifier(payload, "space_id")
    scope_tier = validate.enum(payload, "scope_tier", SCOPE_TIERS)
    estimate = validate.cents(payload, "estimate_cents", positive=True)
    package = lookups.get_package(package_id)
    space = lookups.get_space(space_id)
    record = {
        "id": store.new_id(),
        "package_id": package["id"],
        "space_id": space["id"],
        "scope_tier": scope_tier,
        "estimate_cents": estimate,
        "awarded_cents": None,
        "status": "SCOPING",
        "rescope_count": 0,
        "subsidy_estimate_cents": None,
        "package_charge_estimate_cents": None,
        "actual_total_cents": None,
        "subsidy_final_cents": None,
        "package_charge_final_cents": None,
        "cost_variance_cents": None,
        "awarded_on": None,
        "completed_on": None,
    }
    store.stamp_new(record)
    store.db.renovation_projects[record["id"]] = record
    return envelope.created(serialize.renovation_project(record))


@bp.post("/renovation-projects/<project_id>/phases")
def create_phase(project_id):
    authz.actor((authz.ROLE_FACILITIES,))
    payload = validate.body()
    sequence_no = validate.integer(payload, "sequence_no", minimum=1)
    name = validate.string(payload, "name")
    planned_start = validate.instant(payload, "planned_start")
    planned_end = validate.instant(payload, "planned_end")
    budget = validate.cents(payload, "budget_cents", positive=True)
    validate.date_at_or_before(
        planned_start, planned_end, "planned_start must be at or before planned_end"
    )
    project = lookups.get_project(project_id)
    if project["status"] not in ("SCOPING", "BID"):
        fail(
            "ERR_RENOVATION_STATE_INVALID",
            "phases may only be added while the project is SCOPING or BID",
        )
    record = {
        "id": store.new_id(),
        "project_id": project["id"],
        "sequence_no": sequence_no,
        "name": name,
        "planned_start": store.iso(planned_start),
        "planned_end": store.iso(planned_end),
        "budget_cents": budget,
        "actual_cost_cents": None,
        "actual_start": None,
        "actual_end": None,
        "status": "PENDING",
    }
    store.stamp_new(record)
    candidates = cascades.phases_of_project(project["id"]) + [record]
    _validate_plan(candidates)
    store.db.renovation_phases[record["id"]] = record
    return envelope.created(serialize.renovation_phase(record))


@bp.post("/renovation-projects/<project_id>/solicit-bids")
def solicit_bids(project_id):
    authz.actor((authz.ROLE_FACILITIES,))
    project = lookups.get_project(project_id)
    if project["status"] != "SCOPING":
        fail(
            "ERR_RENOVATION_STATE_INVALID",
            "only a SCOPING project may be sent out to bid",
        )
    if not cascades.phases_of_project(project["id"]):
        fail("ERR_NO_PHASES_DEFINED", "the project has no construction phase")
    project["status"] = "BID"
    store.touch(project)
    return envelope.object_response(serialize.renovation_project(project))


@bp.post("/renovation-projects/<project_id>/rescope")
def rescope_project(project_id):
    authz.actor((authz.ROLE_FACILITIES,))
    payload = validate.body()
    revised = validate.cents(payload, "revised_estimate_cents", positive=True)
    scope_tier = validate.enum(payload, "scope_tier", SCOPE_TIERS)
    project = lookups.get_project(project_id)
    if project["status"] != "BID":
        fail(
            "ERR_RENOVATION_STATE_INVALID",
            "only a project out to BID may be rescoped",
        )
    project["status"] = "SCOPING"
    project["estimate_cents"] = revised
    project["scope_tier"] = scope_tier
    project["rescope_count"] = int(project["rescope_count"]) + 1
    store.touch(project)
    return envelope.object_response(serialize.renovation_project(project))


@bp.post("/renovation-projects/<project_id>/award")
def award_project(project_id):
    authz.actor((authz.ROLE_DEAN,))
    payload = validate.body()
    awarded = validate.cents(payload, "awarded_cents")
    project = lookups.get_project(project_id)
    package = _phase_package(project)
    if package is None:
        fail("ERR_PACKAGE_NOT_FOUND", "the funding package no longer exists")
    if package["spend_status"] != "SPENDING":
        fail(
            "ERR_PACKAGE_SPEND_FROZEN",
            "the funding package is not in spend_status SPENDING",
        )
    if project["status"] != "BID":
        fail(
            "ERR_RENOVATION_STATE_INVALID",
            "only a project out to BID may be awarded",
        )
    record_faculty = store.db.faculty.get(package["faculty_id"])
    if record_faculty is None or record_faculty["appointment_status"] != "ACTIVE":
        fail(
            "ERR_FACULTY_NOT_ACTIVE",
            "the package's faculty member must be ACTIVE",
        )
    phases = cascades.phases_of_project(project["id"])
    _validate_plan(phases)
    if not phases:
        fail("ERR_NO_PHASES_DEFINED", "the project has no construction phase")
    if sum(int(p["budget_cents"]) for p in phases) != awarded:
        fail(
            "ERR_NO_PHASES_DEFINED",
            "the phase budgets must sum to awarded_cents exactly",
        )
    subsidy = _subsidy_cents(project["scope_tier"], awarded)
    charge = awarded - subsidy
    ledger.check_waterfall(package, "RENOVATION", charge)
    project["status"] = "AWARDED"
    project["awarded_cents"] = awarded
    project["subsidy_estimate_cents"] = subsidy
    project["package_charge_estimate_cents"] = charge
    project["awarded_on"] = ledger.clock_iso()
    store.touch(project)
    ledger.run_waterfall(
        package,
        "RENOVATION",
        charge,
        ledger.SOURCE_RENOVATION_PROJECT,
        project["id"],
        "renovation contract awarded",
    )
    space = store.db.lab_spaces.get(project["space_id"])
    if space is not None and space["status"] in ("AVAILABLE", "ASSIGNED"):
        space["status"] = "UNDER_RENOVATION"
        store.touch(space)
    return envelope.object_response(serialize.renovation_project(project))


@bp.post("/renovation-projects/<project_id>/phases/<phase_id>/start")
def start_phase(project_id, phase_id):
    authz.actor((authz.ROLE_FACILITIES,))
    project = lookups.get_project(project_id)
    phase = lookups.get_phase(project["id"], phase_id)
    if project["status"] not in ("AWARDED", "IN_PROGRESS"):
        fail(
            "ERR_RENOVATION_STATE_INVALID",
            "phases run only while the project is AWARDED or IN_PROGRESS",
        )
    if phase["status"] != "PENDING":
        fail("ERR_RENOVATION_STATE_INVALID", "only a PENDING phase may be started")
    for other in cascades.phases_of_project(project["id"]):
        if int(other["sequence_no"]) < int(phase["sequence_no"]):
            if other["status"] != "COMPLETE":
                fail(
                    "ERR_RENOVATION_STATE_INVALID",
                    "every earlier phase must be COMPLETE before this one starts",
                )
    phase["status"] = "ACTIVE"
    phase["actual_start"] = ledger.clock_iso()
    store.touch(phase)
    if int(phase["sequence_no"]) == 1 and project["status"] == "AWARDED":
        project["status"] = "IN_PROGRESS"
        store.touch(project)
    return envelope.object_response(serialize.renovation_phase(phase))


@bp.post("/renovation-projects/<project_id>/phases/<phase_id>/complete")
def complete_phase(project_id, phase_id):
    authz.actor((authz.ROLE_FACILITIES,))
    payload = validate.body()
    actual_cost = validate.cents(payload, "actual_cost_cents")
    project = lookups.get_project(project_id)
    phase = lookups.get_phase(project["id"], phase_id)
    if project["status"] not in ("AWARDED", "IN_PROGRESS"):
        fail(
            "ERR_RENOVATION_STATE_INVALID",
            "phases run only while the project is AWARDED or IN_PROGRESS",
        )
    if phase["status"] != "ACTIVE":
        fail("ERR_RENOVATION_STATE_INVALID", "only an ACTIVE phase may be completed")
    phase["status"] = "COMPLETE"
    phase["actual_cost_cents"] = actual_cost
    phase["actual_end"] = ledger.clock_iso()
    store.touch(phase)
    return envelope.object_response(serialize.renovation_phase(phase))


@bp.post("/renovation-projects/<project_id>/substantial-completion")
def substantial_completion(project_id):
    authz.actor((authz.ROLE_FACILITIES,))
    project = lookups.get_project(project_id)
    package = _phase_package(project)
    if package is None:
        fail("ERR_PACKAGE_NOT_FOUND", "the funding package no longer exists")
    if package["spend_status"] != "SPENDING":
        fail(
            "ERR_PACKAGE_SPEND_FROZEN",
            "the funding package is not in spend_status SPENDING",
        )
    if project["status"] != "IN_PROGRESS":
        fail(
            "ERR_RENOVATION_STATE_INVALID",
            "only a project IN_PROGRESS may reach substantial completion",
        )
    phases = cascades.phases_of_project(project["id"])
    for phase in phases:
        if phase["status"] != "COMPLETE" or phase["actual_cost_cents"] is None:
            fail(
                "ERR_PHASES_INCOMPLETE",
                "every phase must be COMPLETE with a recorded actual_cost_cents",
            )
    awarded = int(project["awarded_cents"] or 0)
    estimate_charge = int(project["package_charge_estimate_cents"] or 0)
    actual_total = sum(
        int(p["actual_cost_cents"])
        for p in phases
        if p["status"] == "COMPLETE" and p["actual_cost_cents"] is not None
    )
    tolerance = money.pct_of_cents(awarded, money.OVERRUN_TOLERANCE_PCT)
    subsidisable = min(actual_total, awarded + tolerance)
    subsidy_final = _subsidy_cents(project["scope_tier"], subsidisable)
    charge_final = actual_total - subsidy_final
    variance = charge_final - estimate_charge
    if variance > 0:
        # Priorities 42 and 43 fire before a single row is written.
        ledger.check_waterfall(package, "RENOVATION", variance)
    project["status"] = "COMPLETED"
    project["completed_on"] = ledger.clock_iso()
    project["actual_total_cents"] = actual_total
    project["subsidy_final_cents"] = subsidy_final
    project["package_charge_final_cents"] = charge_final
    project["cost_variance_cents"] = variance
    store.touch(project)
    ledger.settle_source(
        package,
        ledger.SOURCE_RENOVATION_PROJECT,
        project["id"],
        min(charge_final, estimate_charge),
        "renovation reconciled at substantial completion",
    )
    if variance > 0:
        ledger.run_waterfall(
            package,
            "RENOVATION",
            variance,
            ledger.SOURCE_RENOVATION_PROJECT,
            project["id"],
            "renovation cost overrun encumbered",
        )
        ledger.settle_source(
            package,
            ledger.SOURCE_RENOVATION_PROJECT,
            project["id"],
            variance,
            "renovation cost overrun disbursed",
        )
    space = store.db.lab_spaces.get(project["space_id"])
    if space is not None:
        if space["status"] == "UNDER_RENOVATION":
            space["status"] = "ASSIGNED"
        cascades.promote_in_window_proposals(space)
        store.touch(space)
    return envelope.object_response(serialize.renovation_project(project))


@bp.get("/renovation-projects")
def list_projects():
    authz.actor(READ_ROLES)
    limit, offset = validate.pagination()
    package_filter = validate.filter_value("package_id")
    space_filter = validate.filter_value("space_id")
    status_filter = validate.filter_value("status", PROJECT_STATUSES)
    tier_filter = validate.filter_value("scope_tier", SCOPE_TIERS)
    records = store.by_created(list(store.db.renovation_projects.values()))
    if package_filter is not None:
        records = [p for p in records if p["package_id"] == package_filter]
    if space_filter is not None:
        records = [p for p in records if p["space_id"] == space_filter]
    if status_filter is not None:
        records = [p for p in records if p["status"] == status_filter]
    if tier_filter is not None:
        records = [p for p in records if p["scope_tier"] == tier_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.renovation_project(p) for p in page], limit, offset, total
    )


@bp.get("/renovation-projects/<project_id>")
def read_project(project_id):
    act = authz.actor(READ_ROLES + (authz.ROLE_FACULTY,))
    project = lookups.get_project(project_id)
    package = _phase_package(project)
    if package is not None:
        authz.faculty_scope(act, package["faculty_id"])
    return envelope.object_response(serialize.renovation_project(project))


@bp.get("/renovation-projects/<project_id>/phases")
def list_phases(project_id):
    act = authz.actor(READ_ROLES + (authz.ROLE_FACULTY,))
    limit, offset = validate.pagination()
    status_filter = validate.filter_value("status", PHASE_STATUSES)
    project = lookups.get_project(project_id)
    package = _phase_package(project)
    if package is not None:
        authz.faculty_scope(act, package["faculty_id"])
    records = cascades.phases_of_project(project["id"])
    if status_filter is not None:
        records = [p for p in records if p["status"] == status_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.renovation_phase(p) for p in page], limit, offset, total
    )
