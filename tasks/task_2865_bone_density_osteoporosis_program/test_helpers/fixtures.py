"""Composite fixtures.

The harness restarts the server before every individual test, so each test
begins against an empty database and a logical clock at its default start.
Every precondition below is therefore built from scratch through the API's own
endpoints — nothing is seeded behind the API's back.

``ProgramWorld`` is the workhorse: it walks the ordering, booking, acquisition,
review, reporting and therapy chain one step at a time, so a test can stop at
whatever state it needs and override any single input along the way.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    BMD_FEMORAL_NECK_OSTEOPENIC,
    BMD_FEMORAL_NECK_OSTEOPOROTIC,
    CLOCK_SCAN_DAY,
    CLOCK_SETUP,
)
from .factories import (
    appointment_payload,
    calibration_event_payload,
    cross_cal_run_payload,
    diagnostic_report_payload,
    densitometer_payload,
    frax_payload,
    patient_payload,
    payer_policy_payload,
    positioning_review_payload,
    precision_assessment_payload,
    qc_run_payload,
    refill_payload,
    risk_profile_payload,
    scan_order_payload,
    scan_session_payload,
    site_measurement_payload,
    treatment_plan_payload,
    vfa_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    PHYSICIAN_HEADERS,
    REVIEWER_HEADERS,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_USER_ID,
    make_technologist_headers,
)


@dataclass
class Pipeline:
    """Every resource produced by one walk down the acquisition chain."""

    policy: Dict[str, Any]
    device: Dict[str, Any]
    patient: Dict[str, Any]
    profile: Optional[Dict[str, Any]] = None
    order: Optional[Dict[str, Any]] = None
    appointment: Optional[Dict[str, Any]] = None
    session: Optional[Dict[str, Any]] = None
    measurements: List[Dict[str, Any]] = field(default_factory=list)
    review: Optional[Dict[str, Any]] = None
    report: Optional[Dict[str, Any]] = None
    plan: Optional[Dict[str, Any]] = None

    @property
    def policy_id(self) -> str:
        return self.policy["id"]

    @property
    def device_id(self) -> str:
        return self.device["id"]

    @property
    def patient_id(self) -> str:
        return self.patient["id"]

    @property
    def profile_id(self) -> str:
        assert self.profile is not None
        return self.profile["id"]

    @property
    def order_id(self) -> str:
        assert self.order is not None
        return self.order["id"]

    @property
    def appointment_id(self) -> str:
        assert self.appointment is not None
        return self.appointment["id"]

    @property
    def session_id(self) -> str:
        assert self.session is not None
        return self.session["id"]

    @property
    def report_id(self) -> str:
        assert self.report is not None
        return self.report["id"]

    @property
    def plan_id(self) -> str:
        assert self.plan is not None
        return self.plan["id"]


class ProgramWorld:
    """Builds program state through the API, one declared endpoint at a time."""

    def __init__(self, api: ApiClient):
        self.api = api

    # ── Logical clock ───────────────────────────────────────────────────────

    def set_clock(self, instant: str) -> None:
        response = self.api.set_clock(instant, ADMIN_HEADERS)
        assert response.status_code == 204, (
            f"Setting the clock to {instant} returned {response.status_code}: "
            f"{response.text}"
        )

    # ── Program foundations ─────────────────────────────────────────────────

    def create_policy(self, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_payer_policy(payer_policy_payload(**overrides), ADMIN_HEADERS)
        )

    def create_patient(self, policy_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_patient(
                patient_payload(policy_id, **overrides), SCHEDULER_HEADERS
            )
        )

    def read_patient(self, patient_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_patient(patient_id, SCHEDULER_HEADERS))

    def create_profile(self, patient: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
        """Record a risk factor profile using the patient's current version."""
        current = self.read_patient(patient["id"])
        payload = risk_profile_payload(current["version"], **overrides)
        return get_success_data(
            self.api.create_risk_factor_profile(patient["id"], payload, SCHEDULER_HEADERS)
        )

    # ── Equipment ───────────────────────────────────────────────────────────

    def create_device(self, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_densitometer(densitometer_payload(**overrides), ADMIN_HEADERS)
        )

    def read_device(self, device_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_densitometer(device_id, ADMIN_HEADERS))

    def certify_device(self, device: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
        """Accept a precision study so the device carries a least significant change."""
        current = self.read_device(device["id"])
        payload = precision_assessment_payload(current["version"], **overrides)
        return get_success_data(
            self.api.create_precision_assessment(device["id"], payload, ADMIN_HEADERS)
        )

    def create_certified_device(self, **overrides: Any) -> Dict[str, Any]:
        rms = overrides.pop("rms_sd_g_cm2", 0.0100)
        device = self.create_device(**overrides)
        return self.certify_device(device, rms_sd_g_cm2=rms)

    def record_qc_run(self, device_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_qc_run(device_id, qc_run_payload(**overrides), ADMIN_HEADERS)
        )

    def open_calibration_event(self, device_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_calibration_event(
                device_id, calibration_event_payload(**overrides), ADMIN_HEADERS
            )
        )

    def record_cross_cal_runs(
        self,
        device_id: str,
        event_id: str,
        purpose: str,
        density: float,
        count: int,
    ) -> List[Dict[str, Any]]:
        rows = []
        for _ in range(count):
            rows.append(
                get_success_data(
                    self.api.create_qc_run(
                        device_id,
                        cross_cal_run_payload(purpose, event_id, density),
                        ADMIN_HEADERS,
                    )
                )
            )
        return rows

    def close_calibration_event(self, event_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.close_calibration_event(event_id, ADMIN_HEADERS)
        )

    def adjudicate_calibration_event(self, event_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.adjudicate_calibration_event(event_id, ADMIN_HEADERS)
        )

    def retire_device(self, device_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.retire_densitometer(device_id, ADMIN_HEADERS))

    # ── Ordering and booking ────────────────────────────────────────────────

    def create_order(self, patient_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_scan_order(
                scan_order_payload(patient_id, **overrides), SCHEDULER_HEADERS
            )
        )

    def book(self, order_id: str, device_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_scan_appointment(
                appointment_payload(order_id, device_id, **overrides), SCHEDULER_HEADERS
            )
        )

    def cancel(self, appointment_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.cancel_scan_appointment(appointment_id, SCHEDULER_HEADERS)
        )

    # ── Acquisition ─────────────────────────────────────────────────────────

    def start_session(
        self,
        appointment_id: str,
        technologist_user_id: str = TECHNOLOGIST_USER_ID,
        **overrides: Any,
    ) -> Dict[str, Any]:
        headers = make_technologist_headers(technologist_user_id)
        return get_success_data(
            self.api.create_scan_session(
                appointment_id, scan_session_payload(**overrides), headers
            )
        )

    def measure(
        self,
        session_id: str,
        site_code: str = "FEMORAL_NECK",
        bmd_g_cm2: Optional[float] = None,
        technologist_user_id: str = TECHNOLOGIST_USER_ID,
        **overrides: Any,
    ) -> Dict[str, Any]:
        headers = make_technologist_headers(technologist_user_id)
        payload = site_measurement_payload(site_code, bmd_g_cm2, **overrides)
        return get_success_data(
            self.api.create_site_measurement(session_id, payload, headers)
        )

    def record_vfa(
        self,
        session_id: str,
        genant_grades: Optional[List[int]] = None,
        technologist_user_id: str = TECHNOLOGIST_USER_ID,
    ) -> Dict[str, Any]:
        headers = make_technologist_headers(technologist_user_id)
        return get_success_data(
            self.api.create_vfa(session_id, vfa_payload(genant_grades), headers)
        )

    def submit(
        self, session_id: str, technologist_user_id: str = TECHNOLOGIST_USER_ID
    ) -> Dict[str, Any]:
        headers = make_technologist_headers(technologist_user_id)
        return get_success_data(self.api.submit_acquisition(session_id, headers))

    def review_positioning(
        self,
        session_id: str,
        defect_codes: Optional[List[str]] = None,
        headers: Optional[Dict[str, str]] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_positioning_review(
                session_id,
                positioning_review_payload(defect_codes, **overrides),
                headers or REVIEWER_HEADERS,
            )
        )

    def repeat(
        self, session_id: str, technologist_user_id: str = TECHNOLOGIST_USER_ID
    ) -> Dict[str, Any]:
        headers = make_technologist_headers(technologist_user_id)
        return get_success_data(self.api.repeat_acquisition(session_id, headers))

    def read_session(self, session_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_scan_session(session_id, PHYSICIAN_HEADERS))

    # ── Interpretation ──────────────────────────────────────────────────────

    def assess_frax(
        self,
        patient_id: str,
        profile_id: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_frax_assessment(
                frax_payload(patient_id, profile_id, session_id), PHYSICIAN_HEADERS
            )
        )

    def draft_report(self, session_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_diagnostic_report(
                diagnostic_report_payload(session_id, **overrides), PHYSICIAN_HEADERS
            )
        )

    def finalize_report(self, report_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.finalize_diagnostic_report(report_id, PHYSICIAN_HEADERS)
        )

    def read_report(self, report_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_diagnostic_report(report_id, PHYSICIAN_HEADERS)
        )

    # ── Therapy ─────────────────────────────────────────────────────────────

    def create_plan(
        self, patient_id: str, report_id: str, **overrides: Any
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_treatment_plan(
                treatment_plan_payload(patient_id, report_id, **overrides),
                PHYSICIAN_HEADERS,
            )
        )

    def record_refill(self, plan_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_adherence_refill(
                plan_id, refill_payload(**overrides), PHYSICIAN_HEADERS
            )
        )

    def review_adherence(self, plan_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_adherence_review(plan_id, dict(overrides), PHYSICIAN_HEADERS)
        )

    def read_plan(self, plan_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_treatment_plan(plan_id, PHYSICIAN_HEADERS))

    # ── Composite chains ────────────────────────────────────────────────────

    def foundation(
        self,
        clock: str = CLOCK_SETUP,
        policy_overrides: Optional[Dict[str, Any]] = None,
        device_overrides: Optional[Dict[str, Any]] = None,
        patient_overrides: Optional[Dict[str, Any]] = None,
        with_profile: bool = False,
        profile_overrides: Optional[Dict[str, Any]] = None,
    ) -> Pipeline:
        """Clock, policy, certified device and patient — the base of every chain."""
        self.set_clock(clock)
        policy = self.create_policy(**(policy_overrides or {}))
        device = self.create_certified_device(**(device_overrides or {}))
        patient = self.create_patient(policy["id"], **(patient_overrides or {}))
        pipeline = Pipeline(policy=policy, device=device, patient=patient)
        if with_profile:
            pipeline.profile = self.create_profile(patient, **(profile_overrides or {}))
            pipeline.patient = self.read_patient(patient["id"])
        return pipeline

    def build(
        self,
        stop_after: str = "finalized",
        clock: str = CLOCK_SETUP,
        scan_clock: str = CLOCK_SCAN_DAY,
        policy_overrides: Optional[Dict[str, Any]] = None,
        device_overrides: Optional[Dict[str, Any]] = None,
        patient_overrides: Optional[Dict[str, Any]] = None,
        with_profile: bool = False,
        profile_overrides: Optional[Dict[str, Any]] = None,
        order_overrides: Optional[Dict[str, Any]] = None,
        appointment_overrides: Optional[Dict[str, Any]] = None,
        sites: Optional[List[Any]] = None,
        defect_codes: Optional[List[str]] = None,
        report_overrides: Optional[Dict[str, Any]] = None,
        plan_overrides: Optional[Dict[str, Any]] = None,
        technologist_user_id: str = TECHNOLOGIST_USER_ID,
    ) -> Pipeline:
        """Walk the chain as far as ``stop_after`` and return everything created.

        ``stop_after`` is one of ``foundation``, ``order``, ``booked``,
        ``session``, ``measured``, ``submitted``, ``reviewed``, ``drafted``,
        ``finalized`` or ``plan``. ``sites`` is a list of either site codes or
        ``(site_code, bmd_g_cm2)`` pairs.
        """
        stages = [
            "foundation",
            "order",
            "booked",
            "session",
            "measured",
            "submitted",
            "reviewed",
            "drafted",
            "finalized",
            "plan",
        ]
        assert stop_after in stages, f"Unknown stage {stop_after!r}"
        limit = stages.index(stop_after)

        pipeline = self.foundation(
            clock=clock,
            policy_overrides=policy_overrides,
            device_overrides=device_overrides,
            patient_overrides=patient_overrides,
            with_profile=with_profile,
            profile_overrides=profile_overrides,
        )
        if limit == 0:
            return pipeline

        site_specs = sites or [("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC)]
        normalised = [
            (spec, None) if isinstance(spec, str) else (spec[0], spec[1])
            for spec in site_specs
        ]
        order_kwargs = dict(order_overrides or {})
        order_kwargs.setdefault(
            "requested_sites", [site for site, _ in normalised]
        )
        pipeline.order = self.create_order(pipeline.patient_id, **order_kwargs)
        if limit == 1:
            return pipeline

        pipeline.appointment = self.book(
            pipeline.order_id, pipeline.device_id, **(appointment_overrides or {})
        )
        if limit == 2:
            return pipeline

        self.set_clock(scan_clock)
        pipeline.session = self.start_session(
            pipeline.appointment_id, technologist_user_id=technologist_user_id
        )
        if limit == 3:
            return pipeline

        for site_code, bmd in normalised:
            pipeline.measurements.append(
                self.measure(
                    pipeline.session_id,
                    site_code,
                    bmd,
                    technologist_user_id=technologist_user_id,
                )
            )
        if limit == 4:
            return pipeline

        pipeline.session = self.submit(
            pipeline.session_id, technologist_user_id=technologist_user_id
        )
        if limit == 5:
            return pipeline

        pipeline.review = self.review_positioning(pipeline.session_id, defect_codes)
        pipeline.session = self.read_session(pipeline.session_id)
        if limit == 6:
            return pipeline

        pipeline.report = self.draft_report(
            pipeline.session_id, **(report_overrides or {})
        )
        if limit == 7:
            return pipeline

        pipeline.report = self.finalize_report(pipeline.report_id)
        pipeline.patient = self.read_patient(pipeline.patient_id)
        if limit == 8:
            return pipeline

        pipeline.plan = self.create_plan(
            pipeline.patient_id, pipeline.report_id, **(plan_overrides or {})
        )
        return pipeline

    def build_treatment_pipeline(self, **kwargs: Any) -> Pipeline:
        """A finalized osteoporotic report plus the therapy plan it justifies."""
        kwargs.setdefault("sites", [("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPOROTIC)])
        kwargs.setdefault("stop_after", "plan")
        return self.build(**kwargs)


# ── pytest fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def world(api: ApiClient) -> ProgramWorld:
    """The state builder every test drives its preconditions through."""
    return ProgramWorld(api)


@pytest.fixture
def foundation(world: ProgramWorld) -> Pipeline:
    """Clock at the setup instant, one policy, one certified device, one patient."""
    return world.foundation()


@pytest.fixture
def foundation_with_profile(world: ProgramWorld) -> Pipeline:
    """The foundation plus an active clinical risk factor profile."""
    return world.foundation(with_profile=True)


@pytest.fixture
def ordered(world: ProgramWorld) -> Pipeline:
    """A requested, eligible baseline screening order."""
    return world.build(stop_after="order")


@pytest.fixture
def booked(world: ProgramWorld) -> Pipeline:
    """That order booked onto the certified device."""
    return world.build(stop_after="booked")


@pytest.fixture
def in_progress_session(world: ProgramWorld) -> Pipeline:
    """An acquisition open on the device, with the clock on the scan day."""
    return world.build(stop_after="session")


@pytest.fixture
def measured_session(world: ProgramWorld) -> Pipeline:
    """An acquisition carrying its femoral neck measurement, not yet submitted."""
    return world.build(stop_after="measured")


@pytest.fixture
def submitted_session(world: ProgramWorld) -> Pipeline:
    """A submitted acquisition awaiting positioning review."""
    return world.build(stop_after="submitted")


@pytest.fixture
def accepted_session(world: ProgramWorld) -> Pipeline:
    """A submitted acquisition whose positioning review accepted it."""
    return world.build(stop_after="reviewed")


@pytest.fixture
def draft_report(world: ProgramWorld) -> Pipeline:
    """A draft diagnostic report on an accepted osteopenic study."""
    return world.build(stop_after="drafted")


@pytest.fixture
def finalized_report(world: ProgramWorld) -> Pipeline:
    """A finalized report, so the patient's screening clock has advanced."""
    return world.build(stop_after="finalized")


@pytest.fixture
def treatment_plan(world: ProgramWorld) -> Pipeline:
    """A therapy plan opened off a finalized osteoporotic report."""
    return world.build_treatment_pipeline()
