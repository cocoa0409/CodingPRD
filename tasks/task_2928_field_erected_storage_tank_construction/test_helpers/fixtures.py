"""Composite setup helpers.

Each helper drives the API through real requests only - there is no direct
database access and nothing is mocked. Setup calls go through
``get_success_data`` so a broken precondition reports the API's own error_id
rather than a bare KeyError.

The helpers are layered:

* thin one-call wrappers, one per endpoint;
* state-progression composites that walk a tank along `construction_phase`;
* entity-hierarchy composites that build the plate / seam / examination trees;
* lifecycle shortcuts that reach a plan's `FILL_HOLD` or a package's
  `SUBMITTED` in one call;
* accumulation helpers that target a specific nonconformance count, reject
  rate or steel ledger figure.
"""

from typing import Iterable, List

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from . import test_users as U


class Ctx(dict):
    """A setup result bag with attribute access."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - developer error
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


# ======================================================================
# Thin one-call wrappers
# ======================================================================
def set_clock(api, to_iso8601: str, headers=None) -> str:
    data = get_success_data(api.set_clock(to_iso8601, headers or U.PE1))
    return data["current_utc"]


def create_tank(api, headers=None, **overrides):
    return get_success_data(api.create_tank(F.tank_payload(**overrides), headers or U.PE1), 201)


def read_tank(api, tank_id, headers=None):
    return get_success_data(api.get_tank(tank_id, headers or U.PE1))


def tank_version(api, tank_id, headers=None) -> int:
    return read_tank(api, tank_id, headers)["version"]


def read_tank_summary(api, tank_id, headers=None):
    return get_success_data(api.get_tank_summary(tank_id, headers or U.PE1))


def phase_transition(api, tank_id, target_phase=C.PHASE_SHELL_COMPLETE, headers=None, **overrides):
    return get_success_data(
        api.phase_transition(
            tank_id, F.phase_transition_payload(target_phase, **overrides), headers or U.PE1
        )
    )


def create_foundation_package(api, tank_id, headers=None, **overrides):
    return get_success_data(
        api.create_foundation_package(
            F.foundation_package_payload(tank_id, **overrides), headers or U.CC1
        ),
        201,
    )


def read_foundation_package(api, package_id, headers=None):
    return get_success_data(api.get_foundation_package(package_id, headers or U.PE1))


def create_survey(api, package_id, elevations=None, fill_percent=0.0, headers=None, **overrides):
    return get_success_data(
        api.create_settlement_survey(
            F.settlement_survey_payload(package_id, elevations, fill_percent, **overrides),
            headers or U.CC1,
        ),
        201,
    )


def read_survey(api, survey_id, headers=None):
    return get_success_data(api.get_settlement_survey(survey_id, headers or U.PE1))


def accept_foundation(api, package_id, decision=C.DECISION_ACCEPT, headers=None, **overrides):
    return get_success_data(
        api.foundation_acceptance(
            package_id, F.foundation_acceptance_payload(decision, **overrides), headers or U.PE1
        )
    )


def create_plate_lot(api, tank_id, headers=None, **overrides):
    return get_success_data(
        api.create_plate_lot(F.plate_lot_payload(tank_id, **overrides), headers or U.ES1), 201
    )


def lot_transition(api, lot_id, target_status, headers=None, **overrides):
    return get_success_data(
        api.plate_lot_status_transition(
            lot_id, F.lot_status_payload(target_status, **overrides), headers or U.ES1
        )
    )


def read_plate_lot(api, lot_id, headers=None):
    return get_success_data(api.get_plate_lot(lot_id, headers or U.PE1))


def receive_plate_lot(api, tank_id, mtr_number="MTR-77123", headers=None, **overrides):
    """Walk one lot ORDERED -> ROLLED -> SHIPPED -> RECEIVED and return it."""
    lot = create_plate_lot(api, tank_id, headers=headers, **overrides)
    lot_transition(api, lot["id"], C.LOT_ROLLED, headers=headers)
    lot_transition(api, lot["id"], C.LOT_SHIPPED, headers=headers)
    return lot_transition(api, lot["id"], C.LOT_RECEIVED, headers=headers, mtr_number=mtr_number)


def allocate(api, lot_id, course_id, allocated_weight_lb, headers=None):
    """Charge plate weight from a lot to a course; returns the updated course."""
    return get_success_data(
        api.plate_lot_allocation(
            lot_id, F.allocation_payload(course_id, allocated_weight_lb), headers or U.ES1
        )
    )


def release_allocation(api, course_id, headers=None, **overrides):
    return get_success_data(
        api.allocation_release(
            course_id, F.allocation_release_payload(**overrides), headers or U.ES1
        )
    )


def create_course(api, tank_id, course_number=1, headers=None, **overrides):
    return get_success_data(
        api.create_shell_course(
            F.shell_course_payload(tank_id, course_number, **overrides), headers or U.PE1
        ),
        201,
    )


def read_course(api, course_id, headers=None):
    return get_success_data(api.get_shell_course(course_id, headers or U.PE1))


def fitup(api, course_id, headers=None):
    return get_success_data(api.fitup(course_id, headers or U.ES1))


def create_welder(api, welder_stamp="W-07", headers=None, **overrides):
    """Registered by AI1, so `qualified_by_user_id` is ai-1 unless overridden."""
    return get_success_data(
        api.create_welder(F.welder_payload(welder_stamp, **overrides), headers or U.AI1), 201
    )


def read_welder(api, welder_id, headers=None):
    return get_success_data(api.get_welder(welder_id, headers or U.PE1))


def welder_action(api, welder_id, action, headers=None, **overrides):
    return get_success_data(
        api.welder_qualification_action(
            welder_id, F.qualification_action_payload(action, **overrides), headers or U.AI1
        )
    )


def create_seam(api, course_id, seam_label="V1", sequence_index=1, headers=None, **overrides):
    return get_success_data(
        api.create_weld_seam(
            F.weld_seam_payload(course_id, seam_label, sequence_index, **overrides),
            headers or U.ES1,
        ),
        201,
    )


def read_seam(api, seam_id, headers=None):
    return get_success_data(api.get_weld_seam(seam_id, headers or U.PE1))


def weld(api, seam_id, welder_id, headers=None, **overrides):
    """Logged by the welder themselves, so X-User-ID equals `welder_id`."""
    return get_success_data(
        api.weld_log(
            seam_id, F.weld_log_payload(welder_id, **overrides), headers or U.welder_headers(welder_id)
        )
    )


def repair_start(api, seam_id, headers=None, **overrides):
    return get_success_data(
        api.repair_start(seam_id, F.repair_start_payload(**overrides), headers or U.ES1)
    )


def schedule_nde(
    api, seam_id, window_start_utc, window_end_utc, method=C.NDE_METHOD_RT,
    coverage_pct=100.0, headers=None, **overrides,
):
    return get_success_data(
        api.create_nde_report(
            F.nde_report_payload(
                seam_id, window_start_utc, window_end_utc, method, coverage_pct, **overrides
            ),
            headers or U.QC1,
        ),
        201,
    )


def read_nde_report(api, report_id, headers=None):
    return get_success_data(api.get_nde_report(report_id, headers or U.PE1))


def report_nde(
    api, report_id, decision, indication_count, film_count=6, defect_type=None,
    headers=None, **overrides,
):
    return get_success_data(
        api.nde_result(
            report_id,
            F.nde_result_payload(decision, indication_count, film_count, defect_type, **overrides),
            headers or U.QC1,
        )
    )


def void_nde(api, report_id, headers=None, **overrides):
    return get_success_data(
        api.nde_void(report_id, F.nde_void_payload(**overrides), headers or U.AI2)
    )


def create_water_source(api, source_name="Riverside Intake", headers=None, **overrides):
    return get_success_data(
        api.create_water_source(F.water_source_payload(source_name, **overrides), headers or U.PE1),
        201,
    )


def read_water_source(api, source_id, headers=None):
    return get_success_data(api.get_water_source(source_id, headers or U.PE1))


def source_version(api, source_id, headers=None) -> int:
    return read_water_source(api, source_id, headers)["version"]


def create_plan(api, tank_id, source_id, headers=None, expected_tank_version=None, **overrides):
    """Reads the tank's live `version` first, as the OCC guard of PRD 2.6 requires."""
    version = (
        expected_tank_version if expected_tank_version is not None else tank_version(api, tank_id)
    )
    return get_success_data(
        api.create_hydrotest_plan(
            F.hydrotest_plan_payload(tank_id, source_id, version, **overrides), headers or U.PE1
        ),
        201,
    )


def read_plan(api, plan_id, headers=None):
    return get_success_data(api.get_hydrotest_plan(plan_id, headers or U.PE1))


def approve_plan(api, plan_id, decision=C.APPROVE, headers=None, **overrides):
    return get_success_data(
        api.plan_approval(plan_id, F.plan_approval_payload(decision, **overrides), headers or U.PE1)
    )


def reserve_withdrawal(
    api, plan_id, source_id, window_start_utc, window_end_utc, rate_gpm,
    reserved_volume_gal, headers=None, expected_water_source_version=None, **overrides,
):
    """Reads the source's live `version` first, as the OCC guard of PRD 2.6 requires."""
    version = (
        expected_water_source_version
        if expected_water_source_version is not None
        else source_version(api, source_id)
    )
    return get_success_data(
        api.create_water_withdrawal(
            F.withdrawal_payload(
                plan_id, source_id, window_start_utc, window_end_utc, rate_gpm,
                reserved_volume_gal, version, **overrides,
            ),
            headers or U.ES1,
        ),
        201,
    )


def read_withdrawal(api, withdrawal_id, headers=None):
    return get_success_data(api.get_water_withdrawal(withdrawal_id, headers or U.PE1))


def cancel_withdrawal(api, withdrawal_id, headers=None, **overrides):
    return get_success_data(
        api.withdrawal_cancellation(
            withdrawal_id, F.withdrawal_cancellation_payload(**overrides), headers or U.ES1
        )
    )


def fill_advance(api, plan_id, target_fill_percent, settlement_survey_id=None, headers=None):
    return get_success_data(
        api.fill_advance(
            plan_id, F.fill_advance_payload(target_fill_percent, settlement_survey_id),
            headers or U.ES1,
        )
    )


def complete_plan(api, plan_id, decision, headers=None, **overrides):
    return get_success_data(
        api.plan_completion(
            plan_id, F.plan_completion_payload(decision, **overrides), headers or U.AI2
        )
    )


def create_coating(api, tank_id, scope=C.SCOPE_INTERNAL_LINING, headers=None, **overrides):
    return get_success_data(
        api.create_coating_application(
            F.coating_application_payload(tank_id, scope, **overrides), headers or U.PE1
        ),
        201,
    )


def read_coating(api, application_id, headers=None):
    return get_success_data(api.get_coating_application(application_id, headers or U.PE1))


def surface_prep(api, application_id, headers=None, **overrides):
    return get_success_data(
        api.surface_prep(application_id, F.surface_prep_payload(**overrides), headers or U.QC1)
    )


def dft_readings(api, application_id, spot_readings, headers=None):
    return get_success_data(
        api.dft_readings(application_id, F.dft_readings_payload(spot_readings), headers or U.QC1)
    )


def holiday_test(api, application_id, holidays_found, test_voltage_v, headers=None):
    return get_success_data(
        api.holiday_test(
            application_id, F.holiday_test_payload(holidays_found, test_voltage_v),
            headers or U.QC1,
        )
    )


def create_appurtenance(api, tank_id, host_course_id, headers=None, **overrides):
    return get_success_data(
        api.create_appurtenance(
            F.appurtenance_payload(tank_id, host_course_id, **overrides), headers or U.PE1
        ),
        201,
    )


def read_appurtenance(api, appurtenance_id, headers=None):
    return get_success_data(api.get_appurtenance(appurtenance_id, headers or U.PE1))


def install_appurtenance(api, appurtenance_id, installed_at_utc=None, headers=None):
    return get_success_data(
        api.appurtenance_installation(
            appurtenance_id, F.installation_payload(installed_at_utc), headers or U.ES1
        )
    )


def create_commissioning_package(api, tank_id, headers=None, **overrides):
    return get_success_data(
        api.create_commissioning_package(
            F.commissioning_package_payload(tank_id, **overrides), headers or U.PE1
        ),
        201,
    )


def read_commissioning_package(api, package_id, headers=None):
    return get_success_data(api.get_commissioning_package(package_id, headers or U.PE1))


def add_document(api, package_id, document_type, reference_number=None, headers=None):
    return get_success_data(
        api.add_commissioning_document(
            package_id,
            F.document_payload(document_type, reference_number or f"REF-{document_type}"),
            headers or U.PE1,
        )
    )


def submit_package(api, package_id, headers=None, **overrides):
    return get_success_data(
        api.package_submission(package_id, F.submission_payload(**overrides), headers or U.PE1)
    )


def review_package(api, package_id, decision=C.REVIEW_ACCEPT, headers=None, **overrides):
    return get_success_data(
        api.package_review(package_id, F.review_payload(decision, **overrides), headers or U.AI3)
    )


# ======================================================================
# Canonical settlement reading sets
# ======================================================================
# Datum shot: every monitoring point at the same elevation.
UNIFORM_BASELINE = [100.0] * 8

# Two inches of perfectly uniform settlement: uniform_settlement_in 2.000,
# max_out_of_plane_in 0.000 and max_adjacent_differential_in 0.000, so the
# round is WITHIN_TOLERANCE under either evaluation method.
SETTLED_2IN = [98.0] * 8

# A single dished point: uniform_settlement_in 0.750, max_out_of_plane_in
# 3.750 and max_adjacent_differential_in 6.000. Both differential metrics
# exceed an allowable_differential_in of 2.356, so the round is
# OUT_OF_TOLERANCE under either method.
DISHED_POINT1 = [94.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]

# A settlement pattern that follows a cosine curve exactly:
# uniform_settlement_in 5.000, max_out_of_plane_in 0.000 and
# max_adjacent_differential_in 2.828. COSINE_BEST_FIT accepts it and
# ADJACENT_PAIR refuses it against the same 2.356 envelope.
COSINE_PATTERN = [91.0, 92.172, 95.0, 97.828, 99.0, 97.828, 95.0, 92.172]


def rt_window(day: str = "2026-08-11", index: int = 0, hours: int = 1):
    """A one-hour RT window whose 60-minute buffer clears every sibling window.

    Windows are placed four hours apart, so buffered window i spans
    [start-1h, end+1h] and cannot touch buffered window i+1.
    """
    start_hour = 2 + index * 4
    return (
        f"{day}T{start_hour:02d}:00:00Z",
        f"{day}T{start_hour + hours:02d}:00:00Z",
    )


# ======================================================================
# Tier 1 - state progression along construction_phase
# ======================================================================
def tank_with_package(api, clock: str = C.CLOCK_BASE, tank_kwargs=None, package_kwargs=None) -> Ctx:
    """Clock set, tank registered at DESIGN_REGISTERED, foundation package PLANNED."""
    set_clock(api, clock)
    tank = create_tank(api, **(tank_kwargs or {}))
    package = create_foundation_package(api, tank["id"], **(package_kwargs or {}))
    return Ctx(
        clock=clock,
        tank=tank,
        tank_id=tank["id"],
        package=package,
        package_id=package["id"],
    )


def tank_with_baseline(api, **kwargs) -> Ctx:
    """Package armed with its datum survey, so its status is BASELINE_SET."""
    ctx = tank_with_package(api, **kwargs)
    ctx.baseline = create_survey(api, ctx.package_id, UNIFORM_BASELINE, 0.0)
    ctx.baseline_id = ctx.baseline["id"]
    ctx.package = read_foundation_package(api, ctx.package_id)
    return ctx


def foundation_accepted_tank(api, **kwargs) -> Ctx:
    """Foundation ACCEPTED, so the tank stands at FOUNDATION_ACCEPTED."""
    ctx = tank_with_baseline(api, **kwargs)
    ctx.package = accept_foundation(api, ctx.package_id)
    ctx.tank = read_tank(api, ctx.tank_id)
    return ctx


def erecting_tank(api, course_kwargs=None, **kwargs) -> Ctx:
    """Course 1 specified and fitted up, so the tank stands at ERECTION_IN_PROGRESS."""
    ctx = foundation_accepted_tank(api, **kwargs)
    ctx.course = create_course(api, ctx.tank_id, 1, **(course_kwargs or {}))
    ctx.course_id = ctx.course["id"]
    ctx.course = fitup(api, ctx.course_id)
    ctx.courses = [ctx.course]
    ctx.tank = read_tank(api, ctx.tank_id)
    return ctx


def welded_course(api, seam_labels: Iterable[str] = ("V1",), welder_kwargs=None, **kwargs) -> Ctx:
    """Every named seam declared and welded by a single QUALIFIED welder."""
    ctx = erecting_tank(api, **kwargs)
    ctx.welder = create_welder(api, **(welder_kwargs or {}))
    ctx.welder_id = ctx.welder["id"]
    ctx.seams: List[dict] = []
    for index, label in enumerate(seam_labels):
        seam = create_seam(api, ctx.course_id, label, index + 1)
        ctx.seams.append(weld(api, seam["id"], ctx.welder_id))
    ctx.seam = ctx.seams[0]
    ctx.seam_id = ctx.seams[0]["id"]
    ctx.course = read_course(api, ctx.course_id)
    ctx.welder = read_welder(api, ctx.welder_id)
    return ctx


def rt_accepted_course(
    api, seam_labels: Iterable[str] = ("V1",), window_day: str = "2026-08-11", **kwargs
) -> Ctx:
    """Every seam radiographed and accepted, so the course reaches RT_ACCEPTED."""
    ctx = welded_course(api, seam_labels=seam_labels, **kwargs)
    ctx.reports: List[dict] = []
    for index, seam in enumerate(ctx.seams):
        start, end = rt_window(window_day, index)
        report = schedule_nde(api, seam["id"], start, end)
        ctx.reports.append(report_nde(api, report["id"], C.DECISION_ACCEPT, 0, 4))
    ctx.report = ctx.reports[0]
    ctx.report_id = ctx.reports[0]["id"]
    ctx.course = read_course(api, ctx.course_id)
    ctx.tank = read_tank(api, ctx.tank_id)
    return ctx


def shell_complete_tank(api, **kwargs) -> Ctx:
    """The one operator-requestable phase move: ERECTION_IN_PROGRESS to SHELL_COMPLETE."""
    ctx = rt_accepted_course(api, **kwargs)
    ctx.tank = phase_transition(api, ctx.tank_id, C.PHASE_SHELL_COMPLETE)
    return ctx


# ======================================================================
# Tier 2 - hydrostatic test lifecycle shortcuts
# ======================================================================
def approved_plan(api, source_kwargs=None, plan_kwargs=None, **kwargs) -> Ctx:
    """A water source registered and a plan approved by pe-1 on a SHELL_COMPLETE tank."""
    ctx = shell_complete_tank(api, **kwargs)
    ctx.source = create_water_source(api, **(source_kwargs or {}))
    ctx.source_id = ctx.source["id"]
    ctx.plan = create_plan(api, ctx.tank_id, ctx.source_id, **(plan_kwargs or {}))
    ctx.plan_id = ctx.plan["id"]
    ctx.plan = approve_plan(api, ctx.plan_id, headers=U.PE1)
    ctx.source = read_water_source(api, ctx.source_id)
    return ctx


def approved_plan_with_water(
    api,
    window_start_utc: str = "2026-08-10T01:00:00Z",
    window_end_utc: str = "2026-08-10T20:00:00Z",
    rate_gpm: float = 400.0,
    reserved_volume_gal: float = 400000.0,
    **kwargs,
) -> Ctx:
    """An approved plan holding one reserved withdrawal window."""
    ctx = approved_plan(api, **kwargs)
    ctx.withdrawal = reserve_withdrawal(
        api, ctx.plan_id, ctx.source_id, window_start_utc, window_end_utc,
        rate_gpm, reserved_volume_gal,
    )
    ctx.withdrawal_id = ctx.withdrawal["id"]
    ctx.withdrawals = [ctx.withdrawal]
    ctx.plan = read_plan(api, ctx.plan_id)
    ctx.source = read_water_source(api, ctx.source_id)
    return ctx


def plan_at_fill_hold(api, with_water: bool = True, **kwargs) -> Ctx:
    """All four mandatory hold points surveyed and filled, so the plan is FILL_HOLD.

    Every hold-point survey reads two inches of uniform settlement, which is
    WITHIN_TOLERANCE, and each advance quotes the survey taken at exactly that
    fill level.
    """
    ctx = approved_plan_with_water(api, **kwargs) if with_water else approved_plan(api, **kwargs)
    ctx.hold_surveys = {}
    for level in C.HOLD_POINTS:
        survey = create_survey(
            api, ctx.package_id, SETTLED_2IN, float(level), hydrotest_plan_id=ctx.plan_id
        )
        ctx.hold_surveys[level] = survey
        ctx.plan = fill_advance(api, ctx.plan_id, float(level), survey["id"])
    return ctx


def hydrotest_passed_tank(api, clock_after_hold: str = "2026-08-11T00:00:00Z", **kwargs) -> Ctx:
    """The hold elapsed and ai-2 recorded a PASS, so the tank reaches HYDROTEST_PASSED."""
    ctx = plan_at_fill_hold(api, **kwargs)
    set_clock(api, clock_after_hold)
    ctx.clock = clock_after_hold
    ctx.plan = complete_plan(api, ctx.plan_id, C.PASS_DECISION, headers=U.AI2)
    ctx.tank = read_tank(api, ctx.tank_id)
    ctx.source = read_water_source(api, ctx.source_id)
    return ctx


# ======================================================================
# Tier 3 - coating and commissioning lifecycle shortcuts
# ======================================================================
PASSING_SPOT_READINGS = [[11.0, 11.0, 11.0]]
INTERNAL_LINING_HOLIDAY_VOLTAGE = 675.0


def accept_coating(api, application_id, spot_readings=None, test_voltage_v=None, holidays_found=0):
    """Walk one application preparation -> readings -> clean holiday test -> ACCEPTED."""
    surface_prep(api, application_id)
    dft_readings(api, application_id, spot_readings or PASSING_SPOT_READINGS)
    return holiday_test(
        api,
        application_id,
        holidays_found,
        INTERNAL_LINING_HOLIDAY_VOLTAGE if test_voltage_v is None else test_voltage_v,
    )


def coated_tank(api, scopes: Iterable[str] = (C.SCOPE_INTERNAL_LINING,), **kwargs) -> Ctx:
    """Every coating application of the tank ACCEPTED, so the tank reaches COATED."""
    ctx = hydrotest_passed_tank(api, **kwargs)
    ctx.coatings: List[dict] = []
    for scope in scopes:
        application = create_coating(api, ctx.tank_id, scope)
        ctx.coatings.append(accept_coating(api, application["id"]))
    ctx.coating = ctx.coatings[0]
    ctx.coating_id = ctx.coatings[0]["id"]
    ctx.tank = read_tank(api, ctx.tank_id)
    return ctx


def package_with_documents(api, ctx: Ctx, document_types=None) -> Ctx:
    """Open the tank's commissioning package and record the named documents."""
    ctx.commissioning = create_commissioning_package(api, ctx.tank_id)
    ctx.commissioning_id = ctx.commissioning["id"]
    for document_type in (
        C.REQUIRED_DOCUMENT_TYPES if document_types is None else document_types
    ):
        ctx.commissioning = add_document(api, ctx.commissioning_id, document_type)
    return ctx


def submitted_package_tank(api, scopes=(C.SCOPE_INTERNAL_LINING,), **kwargs) -> Ctx:
    """A COATED tank whose complete commissioning package has been submitted by pe-1."""
    ctx = coated_tank(api, scopes=scopes, **kwargs)
    package_with_documents(api, ctx)
    ctx.commissioning = submit_package(api, ctx.commissioning_id, headers=U.PE1)
    return ctx


# ======================================================================
# Tier 4 - accumulation and threshold targeting
# ======================================================================
def reject_examination(
    api, seam_id, window_day: str = "2026-08-12", window_index: int = 0,
    indication_count: int = 1, defect_type: str = C.DEFECT_SLAG_INCLUSION,
    film_count: int = 4,
):
    """Schedule one RT examination on a welded seam and report it as a rejection."""
    start, end = rt_window(window_day, window_index)
    report = schedule_nde(api, seam_id, start, end)
    return report_nde(
        api, report["id"], C.DECISION_REJECT, indication_count, film_count, defect_type
    )


def accept_examination(
    api, seam_id, window_day: str = "2026-08-12", window_index: int = 0, film_count: int = 4
):
    """Schedule one RT examination on a welded seam and report it as an acceptance."""
    start, end = rt_window(window_day, window_index)
    report = schedule_nde(api, seam_id, start, end)
    return report_nde(api, report["id"], C.DECISION_ACCEPT, 0, film_count)


def open_nonconformances_by_rejection(api, ctx: Ctx, count: int, window_day="2026-08-12") -> List[dict]:
    """Reject one examination on each of the first `count` welded seams of the tank.

    Each unresolved rejection is one carrier of `open_nonconformance_count`, so
    a count of 1 or 2 drives the posture to RESTRICTED and a count of 3 or more
    drives it to FROZEN.
    """
    assert count <= len(ctx.seams), "not enough welded seams to open that many rejections"
    reports = []
    for index in range(count):
        reports.append(
            reject_examination(api, ctx.seams[index]["id"], window_day, index)
        )
    ctx.rejections = reports
    ctx.tank = read_tank(api, ctx.tank_id)
    return reports


def restricted_tank(api, seam_labels=("V1", "V2"), **kwargs) -> Ctx:
    """A tank whose single unresolved rejection puts the posture at RESTRICTED."""
    ctx = welded_course(api, seam_labels=seam_labels, **kwargs)
    open_nonconformances_by_rejection(api, ctx, 1)
    return ctx


def frozen_tank(api, seam_labels=("V1", "V2", "V3"), **kwargs) -> Ctx:
    """A tank whose three unresolved rejections put the posture at FROZEN."""
    ctx = welded_course(api, seam_labels=seam_labels, **kwargs)
    open_nonconformances_by_rejection(api, ctx, 3)
    return ctx


def second_tank(api, tank_tag: str = "TK-102", **overrides) -> Ctx:
    """A second, independent tank used for cross-tank and per-tank scoping probes."""
    tank = create_tank(api, tank_tag=tank_tag, **overrides)
    return Ctx(tank=tank, tank_id=tank["id"])


def list_rows(api, response) -> tuple:
    """Return (rows, meta) from a list response without re-validating the envelope."""
    body = response.json()
    return body["data"], body["meta"]
