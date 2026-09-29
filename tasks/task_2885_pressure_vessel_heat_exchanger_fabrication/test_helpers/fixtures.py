"""Pytest fixtures and the workflow builder that composes shop preconditions.

The harness restarts the API server before every individual test, so every fixture
here builds its preconditions from scratch through the endpoints PRD §4 declares.
Nothing is seeded directly into storage.

`ShopWorkflow` is the single composition point. It keeps one registered person per
functional capacity, hands out that person's own headers, and re-reads a job's
`version` before every version-guarded write so that the optimistic-concurrency
field of §2.7 always names the value the client last observed.
"""

from types import SimpleNamespace

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .api_errors import register_error_status_map
from .constants import (
    COMPONENT_TYPE_SHELL,
    DESIGN_CODE_DIV1,
    FORM_PLATE,
    JOINT_CATEGORY_A,
    JOINT_TYPE_BUTT,
    ROLE_CODE_AUTHORIZED_INSPECTOR,
    ROLE_CODE_DESIGN_ENGINEER,
    ROLE_CODE_QC_INSPECTOR,
    ROLE_CODE_WELDING_ENGINEER,
    RT_EXTENT_FULL,
    RT_EXTENT_NONE,
    SPEC_SA_516_70,
    VESSEL_TYPE_PRESSURE_VESSEL,
)
from .test_users import headers_for_person, shop_admin_headers


class ShopWorkflow:
    """Composes the shop preconditions a test needs, one PRD endpoint at a time."""

    def __init__(self, client):
        self.client = client
        self.admin = shop_admin_headers()
        self._people = {}

    # ------------------------------------------------------------------ people
    def register(self, role_code, key=None, **overrides):
        """Register a person and cache them under ``key`` (§3.2)."""
        if key is not None and key in self._people:
            return self._people[key]
        payload = factories.personnel_payload(role_code, **overrides)
        person = get_success_data(self.client.register_person(payload, self.admin))
        if key is not None:
            self._people[key] = person
        return person

    def design_engineer(self, key="design_engineer_1"):
        return self.register(ROLE_CODE_DESIGN_ENGINEER, key)

    def reviewing_design_engineer(self, key="design_engineer_2"):
        return self.register(ROLE_CODE_DESIGN_ENGINEER, key)

    def welding_engineer(self, key="welding_engineer_1"):
        return self.register(ROLE_CODE_WELDING_ENGINEER, key)

    def second_welding_engineer(self, key="welding_engineer_2"):
        return self.register(ROLE_CODE_WELDING_ENGINEER, key)

    def qc_inspector(self, key="qc_inspector_1"):
        return self.register(ROLE_CODE_QC_INSPECTOR, key)

    def second_qc_inspector(self, key="qc_inspector_2"):
        return self.register(ROLE_CODE_QC_INSPECTOR, key)

    def authorized_inspector(self, key="authorized_inspector_1"):
        return self.register(ROLE_CODE_AUTHORIZED_INSPECTOR, key)

    def second_authorized_inspector(self, key="authorized_inspector_2"):
        return self.register(ROLE_CODE_AUTHORIZED_INSPECTOR, key)

    @staticmethod
    def acting_as(person):
        """The headers that person must send: their own id under their own role."""
        return headers_for_person(person)

    # ------------------------------------------------------------------- clock
    def set_clock(self, current_utc):
        return get_success_data(self.client.set_clock(current_utc, self.admin))

    # ------------------------------------------------------- certificate chain
    def certificate(self, **overrides):
        payload = factories.certificate_payload(**overrides)
        return get_success_data(self.client.create_certificate(payload, self.admin))

    def read_certificate(self, certificate_id):
        return get_success_data(self.client.get_certificate(certificate_id, self.admin))

    def audit(self, certificate_id, **overrides):
        payload = factories.audit_payload(certificate_id, **overrides)
        return get_success_data(self.client.create_audit(payload, self.admin))

    def close_audit(self, audit_id, **overrides):
        payload = factories.audit_close_payload(**overrides)
        return get_success_data(self.client.close_audit(audit_id, payload, self.admin))

    def closed_audit(self, certificate_id, major=0, minor=0, observation=0, **overrides):
        """Schedule an audit and close it with the requested finding mix."""
        scheduled = self.audit(certificate_id, **overrides)
        self.close_audit(scheduled["id"], major=major, minor=minor, observation=observation)
        return get_success_data(self.client.get_audit(scheduled["id"], self.admin))

    def satisfactory_closed_audit(self, certificate_id, **overrides):
        return self.closed_audit(certificate_id, major=0, minor=0, **overrides)

    # --------------------------------------------------------------- job chain
    def job(self, certificate=None, **overrides):
        if certificate is None:
            certificate = self.certificate()
        certificate_id = certificate["id"] if isinstance(certificate, dict) else certificate
        payload = factories.vessel_job_payload(certificate_id, **overrides)
        job = get_success_data(self.client.create_job(payload, self.admin))
        job["certificate_id"] = certificate_id
        return job

    def read_job(self, job_id):
        return get_success_data(self.client.get_job(job_id, self.admin))

    def job_version(self, job_id):
        """The job's current `version`, re-read for the §2.7 concurrency field."""
        return self.read_job(job_id)["version"]

    def cancel_job(self, job_id, **overrides):
        payload = factories.cancel_payload(**overrides)
        return get_success_data(self.client.cancel_job(job_id, payload, self.admin))

    # ------------------------------------------------------ calculation sheets
    def prepare_sheet(self, job_id, component, preparer=None, **overrides):
        preparer = preparer or self.design_engineer()
        payload = factories.design_calculation_payload(
            self.job_version(job_id), component=component, **overrides
        )
        return get_success_data(
            self.client.create_calculation(job_id, payload, self.acting_as(preparer))
        )

    def submit_sheet(self, calculation_id, preparer=None):
        preparer = preparer or self.design_engineer()
        return get_success_data(
            self.client.submit_calculation(calculation_id, self.acting_as(preparer))
        )

    def approve_sheet(self, calculation_id, reviewer=None):
        reviewer = reviewer or self.reviewing_design_engineer()
        return get_success_data(
            self.client.approve_calculation(calculation_id, self.acting_as(reviewer))
        )

    def approved_sheet(self, job_id, component, preparer=None, reviewer=None, **overrides):
        sheet = self.prepare_sheet(job_id, component, preparer=preparer, **overrides)
        self.submit_sheet(sheet["id"], preparer=preparer)
        return self.approve_sheet(sheet["id"], reviewer=reviewer)

    def release_design(self, job, rt_extent_declared=RT_EXTENT_NONE, **overrides):
        """Approve one sheet per member of the job's `required_components` (§3.3)."""
        sheets = {}
        for component in job["required_components"]:
            sheets[component] = self.approved_sheet(
                job["id"], component, rt_extent_declared=rt_extent_declared, **overrides
            )
        return sheets

    # ------------------------------------------------------------ material
    def heat(self, **overrides):
        payload = factories.material_heat_payload(**overrides)
        return get_success_data(self.client.create_heat(payload, self.acting_as(self.qc_inspector())))

    def accept_heat(self, heat_id):
        return get_success_data(
            self.client.review_heat(
                heat_id, factories.mtr_review_payload("ACCEPT"), self.acting_as(self.qc_inspector())
            )
        )

    def accepted_heat(self, **overrides):
        heat = self.heat(**overrides)
        return self.accept_heat(heat["id"])

    def read_heat(self, heat_id):
        return get_success_data(self.client.get_heat(heat_id, self.admin))

    def issue_part(self, job_id, heat_id, **overrides):
        payload = factories.part_payload(heat_id, **overrides)
        return get_success_data(
            self.client.issue_part(job_id, payload, self.acting_as(self.welding_engineer()))
        )

    def scrap_part(self, part_id, **overrides):
        payload = factories.scrap_payload(**overrides)
        return get_success_data(
            self.client.scrap_part(part_id, payload, self.acting_as(self.welding_engineer()))
        )

    # --------------------------------------------------------------- procedures
    def wps(self, **overrides):
        payload = factories.wps_payload(**overrides)
        return get_success_data(self.client.create_wps(payload, self.acting_as(self.welding_engineer())))

    def qualify_wps(self, wps_id):
        return get_success_data(
            self.client.qualify_wps(wps_id, self.acting_as(self.welding_engineer()))
        )

    def qualified_wps(self, **overrides):
        drafted = self.wps(**overrides)
        return self.qualify_wps(drafted["id"])

    def welder_qualification(self, wps_id, **overrides):
        payload = factories.welder_qualification_payload(wps_id, **overrides)
        return get_success_data(
            self.client.create_welder_qualification(payload, self.acting_as(self.welding_engineer()))
        )

    def read_welder_qualification(self, qualification_id):
        return get_success_data(self.client.get_welder_qualification(qualification_id, self.admin))

    # ---------------------------------------------------------------- weld map
    def plan_joint(self, job_id, wps_id, part_a_id, **overrides):
        payload = factories.production_weld_payload(wps_id, part_a_id, **overrides)
        return get_success_data(
            self.client.plan_weld(job_id, payload, self.acting_as(self.welding_engineer()))
        )

    def release_weld_map(self, job_id):
        return get_success_data(
            self.client.release_weld_map(job_id, self.acting_as(self.welding_engineer()))
        )

    def complete_joint(self, weld_id, qualification_id, **overrides):
        payload = factories.weld_complete_payload(qualification_id, **overrides)
        return get_success_data(
            self.client.complete_weld(weld_id, payload, self.acting_as(self.welding_engineer()))
        )

    def read_joint(self, weld_id):
        return get_success_data(self.client.get_weld(weld_id, self.admin))

    # ------------------------------------------------------------ examinations
    def run_nde_plan(self, job_id):
        return get_success_data(
            self.client.run_nde_plan(job_id, self.acting_as(self.qc_inspector()))
        )

    def accept_exam(self, exam_id, **overrides):
        payload = factories.exam_result_payload(**overrides)
        return get_success_data(
            self.client.record_exam_result(exam_id, payload, self.acting_as(self.qc_inspector()))
        )

    def reject_exam(self, exam_id, **overrides):
        payload = factories.exam_reject_payload(**overrides)
        return get_success_data(
            self.client.record_exam_result(exam_id, payload, self.acting_as(self.qc_inspector()))
        )

    def nonconformances_of(self, job_id):
        return get_success_data(
            self.client.list_nonconformances(self.admin, params={"job_id": job_id})
        )

    def disposition(self, nonconformance_id, disposition="REPAIR", actor=None, **overrides):
        actor = actor or self.qc_inspector()
        payload = factories.disposition_payload(disposition=disposition, **overrides)
        return get_success_data(
            self.client.disposition_nonconformance(nonconformance_id, payload, self.acting_as(actor))
        )

    def repair_joint(self, nonconformance_id, wps_id, **overrides):
        payload = factories.repair_weld_payload(wps_id, **overrides)
        return get_success_data(
            self.client.create_repair_weld(
                nonconformance_id, payload, self.acting_as(self.welding_engineer())
            )
        )

    def close_nonconformance(self, nonconformance_id):
        return get_success_data(
            self.client.close_nonconformance(nonconformance_id, self.acting_as(self.qc_inspector()))
        )

    # --------------------------------------------------- furnace and test bays
    def pwht_batch(self, job_id, weld_ids, scheduler=None, **overrides):
        scheduler = scheduler or self.welding_engineer()
        payload = factories.pwht_batch_payload(job_id, weld_ids, **overrides)
        return get_success_data(self.client.create_pwht_batch(payload, self.acting_as(scheduler)))

    def start_pwht_batch(self, batch_id, actor=None):
        actor = actor or self.welding_engineer()
        return get_success_data(self.client.start_pwht_batch(batch_id, self.acting_as(actor)))

    def complete_pwht_batch(self, batch_id, reviewer=None, **overrides):
        reviewer = reviewer or self.second_welding_engineer()
        payload = factories.pwht_complete_payload(**overrides)
        return get_success_data(
            self.client.complete_pwht_batch(batch_id, payload, self.acting_as(reviewer))
        )

    def completed_pwht_batch(self, job_id, weld_ids, **overrides):
        batch = self.pwht_batch(job_id, weld_ids, **overrides)
        self.start_pwht_batch(batch["id"])
        return self.complete_pwht_batch(batch["id"])

    def pressure_test(self, job_id, **overrides):
        payload = factories.pressure_test_payload(job_id, **overrides)
        return get_success_data(
            self.client.create_pressure_test(payload, self.acting_as(self.qc_inspector()))
        )

    def witness_pressure_test(self, test_id, witness=None):
        witness = witness or self.authorized_inspector()
        return get_success_data(
            self.client.witness_pressure_test(test_id, self.acting_as(witness))
        )

    def record_pressure_test_result(self, test_id, **overrides):
        payload = factories.pressure_test_result_payload(**overrides)
        return get_success_data(
            self.client.record_pressure_test_result(
                test_id, payload, self.acting_as(self.qc_inspector())
            )
        )

    # ------------------------------------------------------------ data package
    def assemble_data_report(self, job_id, assembler=None, **overrides):
        assembler = assembler or self.qc_inspector()
        payload = factories.data_report_payload(self.job_version(job_id), **overrides)
        return get_success_data(
            self.client.assemble_data_report(job_id, payload, self.acting_as(assembler))
        )

    def submit_report_to_ai(self, report_id, actor=None):
        actor = actor or self.qc_inspector()
        return get_success_data(self.client.submit_report_to_ai(report_id, self.acting_as(actor)))

    def sign_data_report(self, report_id, signer=None):
        signer = signer or self.authorized_inspector()
        return get_success_data(self.client.sign_data_report(report_id, self.acting_as(signer)))

    def read_data_report(self, report_id):
        return get_success_data(self.client.get_data_report(report_id, self.admin))

    def stamp_nameplate(self, report_id, **overrides):
        payload = factories.stamp_payload(**overrides)
        return get_success_data(self.client.stamp_nameplate(report_id, payload, self.admin))

    # ------------------------------------------------- full-lifecycle shortcuts
    def fabricating_job(
        self,
        rt_extent_declared=RT_EXTENT_NONE,
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        design_code=DESIGN_CODE_DIV1,
        spec=SPEC_SA_516_70,
        form=FORM_PLATE,
        pwht_required=False,
        base_metal_p_number=1,
        joint_count=1,
        joint_category=JOINT_CATEGORY_A,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=1.0000,
        quantity_received_lb=20000.00,
        certificate=None,
        job_overrides=None,
        wps_overrides=None,
    ):
        """A job carried all the way to `FABRICATION` with a released weld map.

        Returns a namespace holding the certificate, the refreshed job, the
        approved sheets, the accepted heat, one issued part per required
        component, the qualified procedure, the welder qualification and the
        planned joints.
        """
        job_overrides = dict(job_overrides or {})
        wps_overrides = dict(wps_overrides or {})
        certificate = certificate or self.certificate()
        job = self.job(
            certificate, vessel_type=vessel_type, design_code=design_code, **job_overrides
        )
        sheets = self.release_design(job, rt_extent_declared=rt_extent_declared)
        heat = self.accepted_heat(spec=spec, form=form, quantity_received_lb=quantity_received_lb)
        parts = {}
        for component in job["required_components"]:
            parts[component] = self.issue_part(job["id"], heat["id"], component_type=component)
        wps = self.qualified_wps(
            pwht_required=pwht_required, base_metal_p_number=base_metal_p_number, **wps_overrides
        )
        qualification = self.welder_qualification(wps["id"])
        welds = []
        for _ in range(joint_count):
            welds.append(
                self.plan_joint(
                    job["id"],
                    wps["id"],
                    parts[COMPONENT_TYPE_SHELL]["id"],
                    joint_category=joint_category,
                    joint_type=joint_type,
                    thickness_in=thickness_in,
                )
            )
        released = self.release_weld_map(job["id"])
        return SimpleNamespace(
            certificate=self.read_certificate(certificate["id"]),
            job=released,
            sheets=sheets,
            heat=self.read_heat(heat["id"]),
            parts=parts,
            wps=wps,
            qualification=qualification,
            welds=welds,
        )

    def welded_job(self, **kwargs):
        """A `FABRICATION` job whose every planned joint has been welded."""
        scenario = self.fabricating_job(**kwargs)
        welded = []
        for weld in scenario.welds:
            welded.append(self.complete_joint(weld["id"], scenario.qualification["id"]))
        scenario.welds = welded
        scenario.job = self.read_job(scenario.job["id"])
        return scenario

    def nde_hold_job(self, **kwargs):
        """A job pushed to `NDE_HOLD` by one rejected examination."""
        kwargs.setdefault("rt_extent_declared", RT_EXTENT_FULL)
        scenario = self.welded_job(**kwargs)
        exams = self.run_nde_plan(scenario.job["id"])
        self.reject_exam(exams[0]["id"])
        scenario.exams = exams
        scenario.nonconformances = self.nonconformances_of(scenario.job["id"])
        scenario.job = self.read_job(scenario.job["id"])
        return scenario

    def testing_job(self, test_overrides=None, **kwargs):
        """A job carried to `TESTING` with one pending shell-side test."""
        scenario = self.welded_job(**kwargs)
        test = self.pressure_test(scenario.job["id"], **dict(test_overrides or {}))
        scenario.pressure_test = test
        scenario.job = self.read_job(scenario.job["id"])
        return scenario

    def data_package_job(self, result_overrides=None, **kwargs):
        """A job carried to `DATA_PACKAGE` by a witnessed, passing test."""
        scenario = self.testing_job(**kwargs)
        self.witness_pressure_test(scenario.pressure_test["id"])
        scenario.pressure_test = self.record_pressure_test_result(
            scenario.pressure_test["id"], **dict(result_overrides or {})
        )
        scenario.job = self.read_job(scenario.job["id"])
        return scenario

    def signed_report_job(self, **kwargs):
        """A job whose data report has been assembled, submitted and signed."""
        scenario = self.data_package_job(**kwargs)
        assembler = self.qc_inspector()
        report = self.assemble_data_report(scenario.job["id"], assembler=assembler)
        self.submit_report_to_ai(report["id"], actor=assembler)
        scenario.assembler = assembler
        scenario.signer = self.authorized_inspector()
        scenario.report = self.sign_data_report(report["id"], signer=scenario.signer)
        scenario.job = self.read_job(scenario.job["id"])
        return scenario


# --------------------------------------------------------------------- fixtures
@pytest.fixture(scope="session", autouse=True)
def error_status_registry():
    """Register the §5 error/status pairing with the framework validators."""
    register_error_status_map()


@pytest.fixture
def client():
    return ApiClient()


@pytest.fixture
def shop(client):
    return ShopWorkflow(client)


@pytest.fixture
def admin_headers():
    return shop_admin_headers()


# --- tier 1: single records in their initial state ---------------------------
@pytest.fixture
def active_certificate(shop):
    return shop.certificate()


@pytest.fixture
def draft_job(shop, active_certificate):
    return shop.job(active_certificate)


@pytest.fixture
def heat_exchanger_job(shop, active_certificate):
    from .constants import VESSEL_TYPE_HEAT_EXCHANGER

    return shop.job(active_certificate, vessel_type=VESSEL_TYPE_HEAT_EXCHANGER)


@pytest.fixture
def drafted_wps(shop):
    return shop.wps()


@pytest.fixture
def qualified_wps(shop):
    return shop.qualified_wps()


@pytest.fixture
def quarantined_heat(shop):
    return shop.heat()


@pytest.fixture
def accepted_heat(shop):
    return shop.accepted_heat()


# --- tier 2 and 3: composed hierarchies and lifecycle shortcuts --------------
@pytest.fixture
def design_released_job(shop, draft_job):
    shop.release_design(draft_job)
    return shop.read_job(draft_job["id"])


@pytest.fixture
def fabricating_job(shop):
    return shop.fabricating_job()


@pytest.fixture
def welded_job(shop):
    return shop.welded_job()


@pytest.fixture
def nde_hold_job(shop):
    return shop.nde_hold_job()


@pytest.fixture
def testing_job(shop):
    return shop.testing_job()


@pytest.fixture
def data_package_job(shop):
    return shop.data_package_job()


@pytest.fixture
def signed_report_job(shop):
    return shop.signed_report_job()
