"""
One method per endpoint of the eye bank API, plus the logical-clock capability.

Every method returns the raw ``requests.Response`` so that tests can assert on the
HTTP status code as well as the envelope. All business paths live under ``/eye-bank``;
the clock capability lives at ``/_clock/set_current_utc``.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/eye-bank"


def _clean(params):
    """Drop keys whose value is None so an omitted filter is genuinely omitted."""
    if not params:
        return None
    cleaned = {k: v for k, v in params.items() if v is not None}
    return cleaned or None


def _bool_param(value):
    """Render a boolean query filter the way a URL carries it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


class EyeBankApiClient(GenericApiClient):
    """HTTP surface of the eye bank corneal tissue recovery and distribution API."""

    # -----------------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -----------------------------------------------------------------------
    # Donors
    # -----------------------------------------------------------------------
    def create_donor(self, payload, headers=None):
        return self._request("POST", f"{BASE}/donors", payload, headers)

    def get_donor(self, donor_id, headers=None):
        return self._request("GET", f"{BASE}/donors/{donor_id}", None, headers)

    def list_donors(
        self, headers=None, status=None, lookback_flag=None, limit=None, offset=None,
        extra_params=None,
    ):
        params = {
            "status": status,
            "lookback_flag": _bool_param(lookback_flag),
            "limit": limit,
            "offset": offset,
        }
        if extra_params:
            params.update(extra_params)
        return self._request("GET", f"{BASE}/donors", _clean(params), headers)

    def create_screening_record(self, donor_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/screening-records", payload, headers
        )

    def list_screening_records(self, donor_id, headers=None, params=None):
        return self._request(
            "GET", f"{BASE}/donors/{donor_id}/screening-records", _clean(params), headers
        )

    def record_consent(self, donor_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/consent", payload, headers
        )

    def defer_donor(self, donor_id, payload, headers=None):
        return self._request("POST", f"{BASE}/donors/{donor_id}/defer", payload, headers)

    def reinstate_donor(self, donor_id, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/reinstate", payload or {}, headers
        )

    def approve_recovery(self, donor_id, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/approve-recovery", payload or {}, headers
        )

    # -----------------------------------------------------------------------
    # Serology
    # -----------------------------------------------------------------------
    def create_serology_panel(self, donor_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/serology-panels", payload, headers
        )

    def list_serology_panels(self, donor_id, headers=None, params=None):
        return self._request(
            "GET", f"{BASE}/donors/{donor_id}/serology-panels", _clean(params), headers
        )

    def post_serology_results(self, panel_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/serology-panels/{panel_id}/results", payload, headers
        )

    # -----------------------------------------------------------------------
    # Technicians
    # -----------------------------------------------------------------------
    def create_technician(self, payload, headers=None):
        return self._request("POST", f"{BASE}/technicians", payload, headers)

    def get_technician(self, technician_id, headers=None):
        return self._request("GET", f"{BASE}/technicians/{technician_id}", None, headers)

    def set_technician_status(self, technician_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/technicians/{technician_id}/status", payload, headers
        )

    def list_technician_evaluations(self, technician_id, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/technicians/{technician_id}/tissue-evaluations",
            _clean(params),
            headers,
        )

    # -----------------------------------------------------------------------
    # Recoveries
    # -----------------------------------------------------------------------
    def create_recovery(self, payload, headers=None):
        return self._request("POST", f"{BASE}/recoveries", payload, headers)

    def get_recovery(self, recovery_id, headers=None):
        return self._request("GET", f"{BASE}/recoveries/{recovery_id}", None, headers)

    def list_recoveries(
        self, headers=None, donor_id=None, technician_id=None, status=None,
        limit=None, offset=None, extra_params=None,
    ):
        params = {
            "donor_id": donor_id,
            "technician_id": technician_id,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        if extra_params:
            params.update(extra_params)
        return self._request("GET", f"{BASE}/recoveries", _clean(params), headers)

    def arrive_recovery(self, recovery_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/recoveries/{recovery_id}/arrive", payload, headers
        )

    def complete_recovery(self, recovery_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/recoveries/{recovery_id}/complete", payload, headers
        )

    def abort_recovery(self, recovery_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/recoveries/{recovery_id}/abort", payload, headers
        )

    # -----------------------------------------------------------------------
    # Tissues
    # -----------------------------------------------------------------------
    def get_tissue(self, tissue_id, headers=None):
        return self._request("GET", f"{BASE}/tissues/{tissue_id}", None, headers)

    def list_tissues(
        self, headers=None, donor_id=None, recovery_id=None, disposition_status=None,
        custody_status=None, limit=None, offset=None, extra_params=None,
    ):
        params = {
            "donor_id": donor_id,
            "recovery_id": recovery_id,
            "disposition_status": disposition_status,
            "custody_status": custody_status,
            "limit": limit,
            "offset": offset,
        }
        if extra_params:
            params.update(extra_params)
        return self._request("GET", f"{BASE}/tissues", _clean(params), headers)

    def create_tissue_evaluation(self, tissue_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/tissues/{tissue_id}/evaluations", payload, headers
        )

    def list_tissue_evaluations(self, tissue_id, headers=None, params=None):
        return self._request(
            "GET", f"{BASE}/tissues/{tissue_id}/evaluations", _clean(params), headers
        )

    def classify_tissue(self, tissue_id, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/tissues/{tissue_id}/classify", payload or {}, headers
        )

    def quarantine_tissue(self, tissue_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/tissues/{tissue_id}/quarantine", payload, headers
        )

    def release_quarantine(self, tissue_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{BASE}/tissues/{tissue_id}/release-quarantine",
            payload or {},
            headers,
        )

    def discard_tissue(self, tissue_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/tissues/{tissue_id}/discard", payload, headers
        )

    def implant_tissue(self, tissue_id, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/tissues/{tissue_id}/implant", payload or {}, headers
        )

    def return_tissue(self, tissue_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/tissues/{tissue_id}/return", payload, headers
        )

    # -----------------------------------------------------------------------
    # Surgeons
    # -----------------------------------------------------------------------
    def create_surgeon(self, payload, headers=None):
        return self._request("POST", f"{BASE}/surgeons", payload, headers)

    def get_surgeon(self, surgeon_id, headers=None):
        return self._request("GET", f"{BASE}/surgeons/{surgeon_id}", None, headers)

    def set_credential_status(self, surgeon_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/surgeons/{surgeon_id}/credential-status", payload, headers
        )

    def list_surgeon_requests_nested(self, surgeon_id, headers=None, params=None):
        return self._request(
            "GET", f"{BASE}/surgeons/{surgeon_id}/requests", _clean(params), headers
        )

    # -----------------------------------------------------------------------
    # Surgeon requests
    # -----------------------------------------------------------------------
    def create_surgeon_request(self, payload, headers=None):
        return self._request("POST", f"{BASE}/surgeon-requests", payload, headers)

    def get_surgeon_request(self, request_id, headers=None):
        return self._request(
            "GET", f"{BASE}/surgeon-requests/{request_id}", None, headers
        )

    def list_surgeon_requests(
        self, headers=None, surgeon_id=None, status=None, limit=None, offset=None,
        extra_params=None,
    ):
        params = {
            "surgeon_id": surgeon_id,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        if extra_params:
            params.update(extra_params)
        return self._request("GET", f"{BASE}/surgeon-requests", _clean(params), headers)

    def cancel_surgeon_request(self, request_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/surgeon-requests/{request_id}/cancel", payload, headers
        )

    # -----------------------------------------------------------------------
    # Allocations
    # -----------------------------------------------------------------------
    def create_allocation(self, payload, headers=None):
        return self._request("POST", f"{BASE}/allocations", payload, headers)

    def create_allocation_run(self, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/allocation-runs", payload or {}, headers
        )

    def get_allocation(self, allocation_id, headers=None):
        return self._request(
            "GET", f"{BASE}/allocations/{allocation_id}", None, headers
        )

    def list_allocations(
        self, headers=None, tissue_id=None, request_id=None, status=None,
        limit=None, offset=None, extra_params=None,
    ):
        params = {
            "tissue_id": tissue_id,
            "request_id": request_id,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        if extra_params:
            params.update(extra_params)
        return self._request("GET", f"{BASE}/allocations", _clean(params), headers)

    def confirm_allocation(self, allocation_id, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/allocations/{allocation_id}/confirm", payload or {}, headers
        )

    def cancel_allocation(self, allocation_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/allocations/{allocation_id}/cancel", payload, headers
        )

    # -----------------------------------------------------------------------
    # Shipments
    # -----------------------------------------------------------------------
    def create_shipment(self, payload, headers=None):
        return self._request("POST", f"{BASE}/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers=None):
        return self._request("GET", f"{BASE}/shipments/{shipment_id}", None, headers)

    def list_shipments(
        self, headers=None, allocation_id=None, replaces_shipment_id=None, status=None,
        limit=None, offset=None, extra_params=None,
    ):
        params = {
            "allocation_id": allocation_id,
            "replaces_shipment_id": replaces_shipment_id,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        if extra_params:
            params.update(extra_params)
        return self._request("GET", f"{BASE}/shipments", _clean(params), headers)

    def create_temperature_reading(self, shipment_id, payload, headers=None):
        return self._request(
            "POST",
            f"{BASE}/shipments/{shipment_id}/temperature-readings",
            payload,
            headers,
        )

    def list_temperature_readings(self, shipment_id, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/shipments/{shipment_id}/temperature-readings",
            _clean(params),
            headers,
        )

    def dispatch_shipment(self, shipment_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/shipments/{shipment_id}/dispatch", payload, headers
        )

    def deliver_shipment(self, shipment_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/shipments/{shipment_id}/deliver", payload, headers
        )

    # -----------------------------------------------------------------------
    # Adverse reaction reports
    # -----------------------------------------------------------------------
    def create_adverse_reaction_report(self, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/adverse-reaction-reports", payload, headers
        )

    def get_adverse_reaction_report(self, report_id, headers=None):
        return self._request(
            "GET", f"{BASE}/adverse-reaction-reports/{report_id}", None, headers
        )

    def list_adverse_reaction_reports(
        self, headers=None, tissue_id=None, surgeon_id=None, status=None,
        limit=None, offset=None, extra_params=None,
    ):
        params = {
            "tissue_id": tissue_id,
            "surgeon_id": surgeon_id,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        if extra_params:
            params.update(extra_params)
        return self._request(
            "GET", f"{BASE}/adverse-reaction-reports", _clean(params), headers
        )

    def substantiate_report(self, report_id, payload, headers=None):
        return self._request(
            "POST",
            f"{BASE}/adverse-reaction-reports/{report_id}/substantiate",
            payload,
            headers,
        )

    def dismiss_report(self, report_id, payload, headers=None):
        return self._request(
            "POST",
            f"{BASE}/adverse-reaction-reports/{report_id}/dismiss",
            payload,
            headers,
        )

    # -----------------------------------------------------------------------
    # Lookback investigations
    # -----------------------------------------------------------------------
    def create_lookback_investigation(self, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/lookback-investigations", payload, headers
        )

    def get_lookback_investigation(self, investigation_id, headers=None):
        return self._request(
            "GET", f"{BASE}/lookback-investigations/{investigation_id}", None, headers
        )

    def list_lookback_investigations(
        self, headers=None, donor_id=None, source_report_id=None, status=None,
        limit=None, offset=None, extra_params=None,
    ):
        params = {
            "donor_id": donor_id,
            "source_report_id": source_report_id,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        if extra_params:
            params.update(extra_params)
        return self._request(
            "GET", f"{BASE}/lookback-investigations", _clean(params), headers
        )

    def notify_investigation(self, investigation_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{BASE}/lookback-investigations/{investigation_id}/notify",
            payload or {},
            headers,
        )

    def close_investigation(self, investigation_id, payload, headers=None):
        return self._request(
            "POST",
            f"{BASE}/lookback-investigations/{investigation_id}/close",
            payload,
            headers,
        )


__all__ = ["EyeBankApiClient", "BASE"]
