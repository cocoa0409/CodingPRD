"""Domain client for the Pressure Vessel Fabrication API.

Wraps the framework's ``GenericApiClient`` with one method per endpoint of PRD §4
so that tests read as shop operations rather than as URL strings. Every method
returns the raw ``requests.Response`` so the caller decides whether to validate a
success envelope or an error envelope.
"""

import re

from prd_bench_local_runner.testing import GenericApiClient

_FRACTION_RE = re.compile(r"^(?P<head>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?P<frac>\.\d+)?(?P<zone>Z|[+-]\d{2}:\d{2})$")


def canonical_instant(value):
    """Normalise an ISO 8601 UTC instant to the three-fractional-digit form.

    PRD §2.4 declares audit timestamps as "an ISO 8601 UTC timestamp with exactly
    three fractional digits", but a caller-supplied instant may legitimately be
    written with none, one or three. Comparisons between what a test sent and what
    the server echoes are therefore made on this canonical form rather than on the
    raw string width.
    """
    if not isinstance(value, str):
        return value
    match = _FRACTION_RE.match(value)
    if match is None:
        return value
    fraction = (match.group("frac") or ".")[1:]
    fraction = (fraction + "000")[:3]
    zone = match.group("zone")
    if zone != "Z":
        zone = "Z"
    return "{head}.{frac}{zone}".format(head=match.group("head"), frac=fraction, zone=zone)


def same_instant(left, right):
    """True when two ISO 8601 UTC instants denote the same reading."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient:
    """One method per PRD §4 endpoint."""

    def __init__(self, base_url=None):
        self._client = GenericApiClient(base_url=base_url)

    # --- raw plumbing --------------------------------------------------------
    @property
    def base_url(self):
        return self._client.base_url

    def get(self, path, headers=None, params=None):
        return self._client.get(path, headers=headers, params=params)

    def post(self, path, payload=None, headers=None):
        return self._client.post(path, json={} if payload is None else payload, headers=headers)

    # --- §2.5 logical clock --------------------------------------------------
    def set_clock(self, current_utc, headers=None):
        return self.post("/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload, headers=None):
        return self.post("/_clock/set_current_utc", payload, headers)

    # --- §3.2 personnel ------------------------------------------------------
    def register_person(self, payload, headers=None):
        return self.post("/personnel", payload, headers)

    def get_person(self, personnel_id, headers=None):
        return self.get("/personnel/{0}".format(personnel_id), headers=headers)

    def list_people(self, headers=None, params=None):
        return self.get("/personnel", headers=headers, params=params)

    # --- §3.1 certificates ---------------------------------------------------
    def create_certificate(self, payload, headers=None):
        return self.post("/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers=None):
        return self.get("/certificates/{0}".format(certificate_id), headers=headers)

    def list_certificates(self, headers=None, params=None):
        return self.get("/certificates", headers=headers, params=params)

    def renew_certificate(self, certificate_id, payload, headers=None):
        return self.post("/certificates/{0}/renewals".format(certificate_id), payload, headers)

    # --- §3.1 shop audits ----------------------------------------------------
    def create_audit(self, payload, headers=None):
        return self.post("/shop-audits", payload, headers)

    def get_audit(self, audit_id, headers=None):
        return self.get("/shop-audits/{0}".format(audit_id), headers=headers)

    def list_audits(self, headers=None, params=None):
        return self.get("/shop-audits", headers=headers, params=params)

    def close_audit(self, audit_id, payload, headers=None):
        return self.post("/shop-audits/{0}/close".format(audit_id), payload, headers)

    # --- §3.2 vessel jobs ----------------------------------------------------
    def create_job(self, payload, headers=None):
        return self.post("/vessel-jobs", payload, headers)

    def get_job(self, job_id, headers=None):
        return self.get("/vessel-jobs/{0}".format(job_id), headers=headers)

    def list_jobs(self, headers=None, params=None):
        return self.get("/vessel-jobs", headers=headers, params=params)

    def cancel_job(self, job_id, payload, headers=None):
        return self.post("/vessel-jobs/{0}/cancel".format(job_id), payload, headers)

    # --- §3.3 design calculations -------------------------------------------
    def create_calculation(self, job_id, payload, headers=None):
        return self.post("/vessel-jobs/{0}/design-calculations".format(job_id), payload, headers)

    def get_calculation(self, calculation_id, headers=None):
        return self.get("/design-calculations/{0}".format(calculation_id), headers=headers)

    def list_calculations(self, headers=None, params=None):
        return self.get("/design-calculations", headers=headers, params=params)

    def submit_calculation(self, calculation_id, headers=None, payload=None):
        return self.post("/design-calculations/{0}/submit".format(calculation_id), payload, headers)

    def approve_calculation(self, calculation_id, headers=None, payload=None):
        return self.post("/design-calculations/{0}/approve".format(calculation_id), payload, headers)

    def reject_calculation(self, calculation_id, payload, headers=None):
        return self.post("/design-calculations/{0}/reject".format(calculation_id), payload, headers)

    def revise_calculation(self, calculation_id, payload, headers=None):
        return self.post("/design-calculations/{0}/revise".format(calculation_id), payload, headers)

    # --- §3.4 material heats and parts --------------------------------------
    def create_heat(self, payload, headers=None):
        return self.post("/material-heats", payload, headers)

    def get_heat(self, heat_id, headers=None):
        return self.get("/material-heats/{0}".format(heat_id), headers=headers)

    def list_heats(self, headers=None, params=None):
        return self.get("/material-heats", headers=headers, params=params)

    def review_heat(self, heat_id, payload, headers=None):
        return self.post("/material-heats/{0}/mtr-review".format(heat_id), payload, headers)

    def issue_part(self, job_id, payload, headers=None):
        return self.post("/vessel-jobs/{0}/parts".format(job_id), payload, headers)

    def get_part(self, part_id, headers=None):
        return self.get("/parts/{0}".format(part_id), headers=headers)

    def list_parts(self, headers=None, params=None):
        return self.get("/parts", headers=headers, params=params)

    def scrap_part(self, part_id, payload, headers=None):
        return self.post("/parts/{0}/scrap".format(part_id), payload, headers)

    # --- §3.5 procedures, qualifications, weld map --------------------------
    def create_wps(self, payload, headers=None):
        return self.post("/wps", payload, headers)

    def get_wps(self, wps_id, headers=None):
        return self.get("/wps/{0}".format(wps_id), headers=headers)

    def list_wps(self, headers=None, params=None):
        return self.get("/wps", headers=headers, params=params)

    def qualify_wps(self, wps_id, headers=None, payload=None):
        return self.post("/wps/{0}/qualify".format(wps_id), payload, headers)

    def create_welder_qualification(self, payload, headers=None):
        return self.post("/welder-qualifications", payload, headers)

    def get_welder_qualification(self, qualification_id, headers=None):
        return self.get("/welder-qualifications/{0}".format(qualification_id), headers=headers)

    def list_welder_qualifications(self, headers=None, params=None):
        return self.get("/welder-qualifications", headers=headers, params=params)

    def log_continuity(self, qualification_id, payload, headers=None):
        return self.post(
            "/welder-qualifications/{0}/continuity-logs".format(qualification_id), payload, headers
        )

    def plan_weld(self, job_id, payload, headers=None):
        return self.post("/vessel-jobs/{0}/production-welds".format(job_id), payload, headers)

    def get_weld(self, weld_id, headers=None):
        return self.get("/production-welds/{0}".format(weld_id), headers=headers)

    def list_welds(self, headers=None, params=None):
        return self.get("/production-welds", headers=headers, params=params)

    def complete_weld(self, weld_id, payload, headers=None):
        return self.post("/production-welds/{0}/complete".format(weld_id), payload, headers)

    def release_weld_map(self, job_id, headers=None, payload=None):
        return self.post("/vessel-jobs/{0}/weld-map-release".format(job_id), payload, headers)

    # --- §3.6 examinations ---------------------------------------------------
    def run_nde_plan(self, job_id, headers=None, payload=None):
        return self.post("/vessel-jobs/{0}/nde-plan".format(job_id), payload, headers)

    def get_exam(self, exam_id, headers=None):
        return self.get("/nde-exams/{0}".format(exam_id), headers=headers)

    def list_exams(self, headers=None, params=None):
        return self.get("/nde-exams", headers=headers, params=params)

    def record_exam_result(self, exam_id, payload, headers=None):
        return self.post("/nde-exams/{0}/result".format(exam_id), payload, headers)

    # --- §3.7 nonconformances -----------------------------------------------
    def get_nonconformance(self, nonconformance_id, headers=None):
        return self.get("/nonconformances/{0}".format(nonconformance_id), headers=headers)

    def list_nonconformances(self, headers=None, params=None):
        return self.get("/nonconformances", headers=headers, params=params)

    def disposition_nonconformance(self, nonconformance_id, payload, headers=None):
        return self.post(
            "/nonconformances/{0}/disposition".format(nonconformance_id), payload, headers
        )

    def create_repair_weld(self, nonconformance_id, payload, headers=None):
        return self.post(
            "/nonconformances/{0}/repair-welds".format(nonconformance_id), payload, headers
        )

    def close_nonconformance(self, nonconformance_id, headers=None, payload=None):
        return self.post("/nonconformances/{0}/close".format(nonconformance_id), payload, headers)

    # --- §3.8 furnace charges and pressure tests ----------------------------
    def create_pwht_batch(self, payload, headers=None):
        return self.post("/pwht-batches", payload, headers)

    def get_pwht_batch(self, batch_id, headers=None):
        return self.get("/pwht-batches/{0}".format(batch_id), headers=headers)

    def list_pwht_batches(self, headers=None, params=None):
        return self.get("/pwht-batches", headers=headers, params=params)

    def start_pwht_batch(self, batch_id, headers=None, payload=None):
        return self.post("/pwht-batches/{0}/start".format(batch_id), payload, headers)

    def complete_pwht_batch(self, batch_id, payload, headers=None):
        return self.post("/pwht-batches/{0}/complete".format(batch_id), payload, headers)

    def create_pressure_test(self, payload, headers=None):
        return self.post("/pressure-tests", payload, headers)

    def get_pressure_test(self, test_id, headers=None):
        return self.get("/pressure-tests/{0}".format(test_id), headers=headers)

    def list_pressure_tests(self, headers=None, params=None):
        return self.get("/pressure-tests", headers=headers, params=params)

    def witness_pressure_test(self, test_id, headers=None, payload=None):
        return self.post("/pressure-tests/{0}/witness".format(test_id), payload, headers)

    def record_pressure_test_result(self, test_id, payload, headers=None):
        return self.post("/pressure-tests/{0}/result".format(test_id), payload, headers)

    # --- §3.9 data package ---------------------------------------------------
    def assemble_data_report(self, job_id, payload, headers=None):
        return self.post("/vessel-jobs/{0}/data-report".format(job_id), payload, headers)

    def get_data_report(self, report_id, headers=None):
        return self.get("/data-reports/{0}".format(report_id), headers=headers)

    def list_data_reports(self, headers=None, params=None):
        return self.get("/data-reports", headers=headers, params=params)

    def submit_report_to_ai(self, report_id, headers=None, payload=None):
        return self.post("/data-reports/{0}/submit-to-ai".format(report_id), payload, headers)

    def sign_data_report(self, report_id, headers=None, payload=None):
        return self.post("/data-reports/{0}/ai-sign".format(report_id), payload, headers)

    def stamp_nameplate(self, report_id, payload, headers=None):
        return self.post("/data-reports/{0}/stamp-nameplate".format(report_id), payload, headers)
