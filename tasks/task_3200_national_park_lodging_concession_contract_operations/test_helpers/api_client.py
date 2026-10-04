"""One transport method per endpoint in PRD section 4.

Every method returns the raw HTTP response so a test may assert on both the
status code and the envelope.  All paths live here and nowhere else.

``canonical_instant`` exists because PRD 2.2 / 2.6 promise ISO 8601 UTC
timestamps with exactly three fractional digits.  Expected instants a test
carries are normalised through it so a server rendering the same instant
with a different fractional width is compared on value, not on spelling.
"""

import os
import re

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant with exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz")
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        suffix = tz.replace(":", "")
        suffix = "{0}:{1}".format(suffix[:3], suffix[3:])
    return "{0}T{1}.{2}{3}".format(
        match.group("date"), match.group("time"), frac, suffix
    )


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    def __init__(self, base_url=None):
        if base_url is None:
            base_url = os.environ.get("API_BASE_URL") or os.environ.get(
                "_PRD_BENCH_API_URL"
            )
        super().__init__(base_url=base_url)

    # --- Logical clock -----------------------------------------------------

    def set_clock(self, current_utc, headers=None):
        return self.post(CLOCK_PATH, json={"current_utc": current_utc}, headers=headers)

    # --- Contracts ---------------------------------------------------------

    def create_contract(self, payload, headers=None):
        return self.post("/contracts", json=payload, headers=headers)

    def list_contracts(self, headers=None, params=None):
        return self.get("/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers=None):
        return self.get("/contracts/{0}".format(contract_id), headers=headers)

    def activate_contract(self, contract_id, headers=None):
        return self.post(
            "/contracts/{0}/activate".format(contract_id), json={}, headers=headers
        )

    def initiate_transition(self, contract_id, headers=None):
        return self.post(
            "/contracts/{0}/initiate-transition".format(contract_id),
            json={},
            headers=headers,
        )

    def designate_successor(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/designate-successor".format(contract_id),
            json=payload,
            headers=headers,
        )

    def finalize_transition(self, contract_id, headers=None):
        return self.post(
            "/contracts/{0}/finalize-transition".format(contract_id),
            json={},
            headers=headers,
        )

    # --- Seasons -----------------------------------------------------------

    def create_season(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/seasons".format(contract_id), json=payload, headers=headers
        )

    def list_seasons(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/seasons".format(contract_id),
            headers=headers,
            params=params,
        )

    def get_season(self, contract_id, season_id, headers=None):
        return self.get(
            "/contracts/{0}/seasons/{1}".format(contract_id, season_id),
            headers=headers,
        )

    def reconcile_season(self, contract_id, season_id, headers=None):
        return self.post(
            "/contracts/{0}/seasons/{1}/reconcile".format(contract_id, season_id),
            json={},
            headers=headers,
        )

    # --- Service lines -----------------------------------------------------

    def create_service_line(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/service-lines".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_service_lines(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/service-lines".format(contract_id),
            headers=headers,
            params=params,
        )

    def suspend_service_line(self, contract_id, line_id, headers=None):
        return self.post(
            "/contracts/{0}/service-lines/{1}/suspend".format(contract_id, line_id),
            json={},
            headers=headers,
        )

    def reinstate_service_line(self, contract_id, line_id, headers=None):
        return self.post(
            "/contracts/{0}/service-lines/{1}/reinstate".format(contract_id, line_id),
            json={},
            headers=headers,
        )

    # --- Room classes ------------------------------------------------------

    def create_room_class(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/room-classes".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_room_classes(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/room-classes".format(contract_id),
            headers=headers,
            params=params,
        )

    # --- Comparability studies ---------------------------------------------

    def create_study(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/comparability-studies".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_studies(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/comparability-studies".format(contract_id),
            headers=headers,
            params=params,
        )

    def get_study(self, contract_id, study_id, headers=None):
        return self.get(
            "/contracts/{0}/comparability-studies/{1}".format(contract_id, study_id),
            headers=headers,
        )

    # --- Rate filings --------------------------------------------------------

    def create_filing(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/rate-filings".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_filings(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/rate-filings".format(contract_id),
            headers=headers,
            params=params,
        )

    def get_filing(self, contract_id, filing_id, headers=None):
        return self.get(
            "/contracts/{0}/rate-filings/{1}".format(contract_id, filing_id),
            headers=headers,
        )

    def start_review_filing(self, contract_id, filing_id, headers=None):
        return self.post(
            "/contracts/{0}/rate-filings/{1}/start-review".format(
                contract_id, filing_id
            ),
            json={},
            headers=headers,
        )

    def approve_filing(self, contract_id, filing_id, headers=None):
        return self.post(
            "/contracts/{0}/rate-filings/{1}/approve".format(contract_id, filing_id),
            json={},
            headers=headers,
        )

    def reject_filing(self, contract_id, filing_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/rate-filings/{1}/reject".format(contract_id, filing_id),
            json=payload,
            headers=headers,
        )

    # --- Reservations --------------------------------------------------------

    def create_reservation(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/reservations".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_reservations(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/reservations".format(contract_id),
            headers=headers,
            params=params,
        )

    def list_season_reservations(self, contract_id, season_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/seasons/{1}/reservations".format(contract_id, season_id),
            headers=headers,
            params=params,
        )

    def list_room_class_reservations(
        self, contract_id, room_class_id, headers=None, params=None
    ):
        return self.get(
            "/contracts/{0}/room-classes/{1}/reservations".format(
                contract_id, room_class_id
            ),
            headers=headers,
            params=params,
        )

    def get_reservation(self, contract_id, reservation_id, headers=None):
        return self.get(
            "/contracts/{0}/reservations/{1}".format(contract_id, reservation_id),
            headers=headers,
        )

    def cancel_reservation(self, contract_id, reservation_id, headers=None):
        return self.post(
            "/contracts/{0}/reservations/{1}/cancel".format(
                contract_id, reservation_id
            ),
            json={},
            headers=headers,
        )

    def check_in_reservation(self, contract_id, reservation_id, headers=None):
        return self.post(
            "/contracts/{0}/reservations/{1}/check-in".format(
                contract_id, reservation_id
            ),
            json={},
            headers=headers,
        )

    # --- Gross receipts reports ----------------------------------------------

    def create_receipts_report(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/receipts-reports".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_receipts_reports(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/receipts-reports".format(contract_id),
            headers=headers,
            params=params,
        )

    def submit_report(self, contract_id, report_id, payload=None, headers=None):
        return self.post(
            "/contracts/{0}/receipts-reports/{1}/submit".format(contract_id, report_id),
            json=payload if payload is not None else {},
            headers=headers,
        )

    def accept_report(self, contract_id, report_id, headers=None):
        return self.post(
            "/contracts/{0}/receipts-reports/{1}/accept".format(contract_id, report_id),
            json={},
            headers=headers,
        )

    def return_report(self, contract_id, report_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/receipts-reports/{1}/return".format(contract_id, report_id),
            json=payload,
            headers=headers,
        )

    # --- Franchise fee statements ----------------------------------------------

    def create_fee_statement(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/fee-statements".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_fee_statements(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/fee-statements".format(contract_id),
            headers=headers,
            params=params,
        )

    def pay_fee_statement(self, contract_id, statement_id, headers=None):
        return self.post(
            "/contracts/{0}/fee-statements/{1}/pay".format(contract_id, statement_id),
            json={},
            headers=headers,
        )

    # --- Capital projects ------------------------------------------------------

    def create_capital_project(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/capital-projects".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_capital_projects(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/capital-projects".format(contract_id),
            headers=headers,
            params=params,
        )

    def get_capital_project(self, contract_id, project_id, headers=None):
        return self.get(
            "/contracts/{0}/capital-projects/{1}".format(contract_id, project_id),
            headers=headers,
        )

    def authorize_project(self, contract_id, project_id, headers=None):
        return self.post(
            "/contracts/{0}/capital-projects/{1}/authorize".format(
                contract_id, project_id
            ),
            json={},
            headers=headers,
        )

    def complete_project(self, contract_id, project_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/capital-projects/{1}/complete".format(
                contract_id, project_id
            ),
            json=payload,
            headers=headers,
        )

    def approve_project(self, contract_id, project_id, headers=None):
        return self.post(
            "/contracts/{0}/capital-projects/{1}/approve".format(
                contract_id, project_id
            ),
            json={},
            headers=headers,
        )

    # --- Housing units ---------------------------------------------------------

    def create_housing_unit(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/housing-units".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_housing_units(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/housing-units".format(contract_id),
            headers=headers,
            params=params,
        )

    def take_housing_unit_offline(self, contract_id, unit_id, headers=None):
        return self.post(
            "/contracts/{0}/housing-units/{1}/take-offline".format(
                contract_id, unit_id
            ),
            json={},
            headers=headers,
        )

    # --- Seasonal hires --------------------------------------------------------

    def create_hire(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/seasonal-hires".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_hires(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/seasonal-hires".format(contract_id),
            headers=headers,
            params=params,
        )

    def get_hire(self, contract_id, hire_id, headers=None):
        return self.get(
            "/contracts/{0}/seasonal-hires/{1}".format(contract_id, hire_id),
            headers=headers,
        )

    def mark_arrived(self, contract_id, hire_id, headers=None):
        return self.post(
            "/contracts/{0}/seasonal-hires/{1}/mark-arrived".format(
                contract_id, hire_id
            ),
            json={},
            headers=headers,
        )

    def mark_departed(self, contract_id, hire_id, headers=None):
        return self.post(
            "/contracts/{0}/seasonal-hires/{1}/mark-departed".format(
                contract_id, hire_id
            ),
            json={},
            headers=headers,
        )

    def terminate_hire(self, contract_id, hire_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/seasonal-hires/{1}/terminate".format(contract_id, hire_id),
            json=payload,
            headers=headers,
        )

    # --- Transport vouchers ----------------------------------------------------

    def create_voucher(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/transport-vouchers".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_vouchers(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/transport-vouchers".format(contract_id),
            headers=headers,
            params=params,
        )

    def void_voucher(self, contract_id, voucher_id, headers=None):
        return self.post(
            "/contracts/{0}/transport-vouchers/{1}/void".format(
                contract_id, voucher_id
            ),
            json={},
            headers=headers,
        )

    # --- Environmental incidents -----------------------------------------------

    def create_incident(self, contract_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/environmental-incidents".format(contract_id),
            json=payload,
            headers=headers,
        )

    def list_incidents(self, contract_id, headers=None, params=None):
        return self.get(
            "/contracts/{0}/environmental-incidents".format(contract_id),
            headers=headers,
            params=params,
        )

    def start_review_incident(self, contract_id, incident_id, headers=None):
        return self.post(
            "/contracts/{0}/environmental-incidents/{1}/start-review".format(
                contract_id, incident_id
            ),
            json={},
            headers=headers,
        )

    def require_corrective_plan(self, contract_id, incident_id, headers=None):
        return self.post(
            "/contracts/{0}/environmental-incidents/{1}/require-corrective-plan".format(
                contract_id, incident_id
            ),
            json={},
            headers=headers,
        )

    def submit_corrective_plan(self, contract_id, incident_id, payload, headers=None):
        return self.post(
            "/contracts/{0}/environmental-incidents/{1}/submit-corrective-plan".format(
                contract_id, incident_id
            ),
            json=payload,
            headers=headers,
        )

    def close_incident(self, contract_id, incident_id, headers=None):
        return self.post(
            "/contracts/{0}/environmental-incidents/{1}/close".format(
                contract_id, incident_id
            ),
            json={},
            headers=headers,
        )

    # --- Flat retrieval forms (PRD 3.10 / 4) -----------------------------------

    def get_season_flat(self, season_id, headers=None):
        return self.get("/seasons/{0}".format(season_id), headers=headers)

    def get_service_line_flat(self, line_id, headers=None):
        return self.get("/service-lines/{0}".format(line_id), headers=headers)

    def get_room_class_flat(self, room_class_id, headers=None):
        return self.get("/room-classes/{0}".format(room_class_id), headers=headers)

    def get_study_flat(self, study_id, headers=None):
        return self.get("/comparability-studies/{0}".format(study_id), headers=headers)

    def get_filing_flat(self, filing_id, headers=None):
        return self.get("/rate-filings/{0}".format(filing_id), headers=headers)

    def get_reservation_flat(self, reservation_id, headers=None):
        return self.get("/reservations/{0}".format(reservation_id), headers=headers)

    def get_receipts_report_flat(self, report_id, headers=None):
        return self.get("/receipts-reports/{0}".format(report_id), headers=headers)

    def get_fee_statement_flat(self, statement_id, headers=None):
        return self.get("/fee-statements/{0}".format(statement_id), headers=headers)

    def get_capital_project_flat(self, project_id, headers=None):
        return self.get("/capital-projects/{0}".format(project_id), headers=headers)

    def get_housing_unit_flat(self, unit_id, headers=None):
        return self.get("/housing-units/{0}".format(unit_id), headers=headers)

    def get_hire_flat(self, hire_id, headers=None):
        return self.get("/seasonal-hires/{0}".format(hire_id), headers=headers)

    def get_voucher_flat(self, voucher_id, headers=None):
        return self.get("/transport-vouchers/{0}".format(voucher_id), headers=headers)

    def get_incident_flat(self, incident_id, headers=None):
        return self.get(
            "/environmental-incidents/{0}".format(incident_id), headers=headers
        )

    def list_filings_flat(self, headers=None, params=None):
        return self.get("/rate-filings", headers=headers, params=params)

    def list_reservations_flat(self, headers=None, params=None):
        return self.get("/reservations", headers=headers, params=params)

    def list_receipts_reports_flat(self, headers=None, params=None):
        return self.get("/receipts-reports", headers=headers, params=params)

    def list_hires_flat(self, headers=None, params=None):
        return self.get("/seasonal-hires", headers=headers, params=params)

    def list_vouchers_flat(self, headers=None, params=None):
        return self.get("/transport-vouchers", headers=headers, params=params)


api_client = ApiClient()
