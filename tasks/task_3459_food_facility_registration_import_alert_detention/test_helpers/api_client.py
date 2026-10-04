"""API client: one method per endpoint defined in the PRD (§4 routing table).

Path discipline: every registry resource is mounted under the ``/registry``
prefix, but the logical-clock control is part of the platform surface and is
deliberately UNPREFIXED (PRD §2.4): ``POST /_clock/set_current_utc``.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Platform: logical clock (UNPREFIXED — outside /registry) ---------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Facility ----------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/registry/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request(
            "GET", f"/registry/facilities/{facility_id}", headers=headers
        )

    def renew_facility(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/registry/facilities/{facility_id}/renew", payload, headers
        )

    # ---- ImporterFirm ------------------------------------------------------
    def create_importer(self, payload, headers):
        return self._request("POST", "/registry/importers", payload, headers)

    # ---- Laboratory --------------------------------------------------------
    def create_laboratory(self, payload, headers):
        return self._request("POST", "/registry/laboratories", payload, headers)

    # ---- PriorNotice -------------------------------------------------------
    def create_prior_notice(self, payload, headers):
        return self._request("POST", "/registry/prior-notices", payload, headers)

    def get_prior_notice(self, prior_notice_id, headers):
        return self._request(
            "GET", f"/registry/prior-notices/{prior_notice_id}", headers=headers
        )

    def list_prior_notices(self, headers, params=None):
        return self._request(
            "GET", "/registry/prior-notices", headers=headers, params=params
        )

    def amend_prior_notice(self, prior_notice_id, payload, headers):
        return self._request(
            "POST",
            f"/registry/prior-notices/{prior_notice_id}/amend",
            payload,
            headers,
        )

    # ---- ImportEntry -------------------------------------------------------
    def create_entry(self, payload, headers):
        return self._request("POST", "/registry/entries", payload, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/registry/entries/{entry_id}", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/registry/entries", headers=headers, params=params)

    def screen_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/registry/entries/{entry_id}/screen", {}, headers
        )

    def record_sample(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/registry/entries/{entry_id}/record-sample", payload, headers
        )

    def release_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/registry/entries/{entry_id}/release", {}, headers
        )

    def request_reconditioning(self, entry_id, payload, headers):
        return self._request(
            "POST",
            f"/registry/entries/{entry_id}/request-reconditioning",
            payload,
            headers,
        )

    def record_reconditioning_outcome(self, entry_id, payload, headers):
        return self._request(
            "POST",
            f"/registry/entries/{entry_id}/record-reconditioning-outcome",
            payload,
            headers,
        )

    def export_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/registry/entries/{entry_id}/export", {}, headers
        )

    def refuse_entry(self, entry_id, headers):
        return self._request("POST", f"/registry/entries/{entry_id}/refuse", {}, headers)

    # ---- SampleAnalysis ----------------------------------------------------
    def list_entry_samples(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/registry/entries/{entry_id}/samples", headers=headers, params=params
        )

    def record_sample_result(self, sample_id, payload, headers):
        return self._request(
            "POST", f"/registry/samples/{sample_id}/record-result", payload, headers
        )

    # ---- ImportAlert -------------------------------------------------------
    def create_import_alert(self, payload, headers):
        return self._request("POST", "/registry/import-alerts", payload, headers)

    def get_import_alert(self, alert_id, headers):
        return self._request(
            "GET", f"/registry/import-alerts/{alert_id}", headers=headers
        )

    def list_import_alerts(self, headers, params=None):
        return self._request(
            "GET", "/registry/import-alerts", headers=headers, params=params
        )

    # ---- AlertPetition -----------------------------------------------------
    def create_alert_petition(self, alert_id, payload, headers):
        return self._request(
            "POST", f"/registry/import-alerts/{alert_id}/petitions", payload, headers
        )

    def list_alert_petitions(self, alert_id, headers, params=None):
        return self._request(
            "GET",
            f"/registry/import-alerts/{alert_id}/petitions",
            headers=headers,
            params=params,
        )

    def list_facility_petitions(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/registry/facilities/{facility_id}/petitions",
            headers=headers,
            params=params,
        )

    def submit_petition_evidence(self, petition_id, payload, headers):
        return self._request(
            "POST",
            f"/registry/alert-petitions/{petition_id}/submit-evidence",
            payload,
            headers,
        )

    def adjudicate_petition(self, petition_id, payload, headers):
        return self._request(
            "POST",
            f"/registry/alert-petitions/{petition_id}/adjudicate",
            payload,
            headers,
        )

    # ---- Inspection --------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/registry/inspections", payload, headers)

    def list_facility_inspections(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/registry/facilities/{facility_id}/inspections",
            headers=headers,
            params=params,
        )

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/registry/inspections/{inspection_id}/complete", payload, headers
        )

    def refuse_inspection_entry(self, inspection_id, headers):
        return self._request(
            "POST", f"/registry/inspections/{inspection_id}/refuse-entry", {}, headers
        )

    # ---- Recall ------------------------------------------------------------
    def create_recall(self, payload, headers):
        return self._request("POST", "/registry/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/registry/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/registry/recalls", headers=headers, params=params)

    def classify_recall(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/registry/recalls/{recall_id}/classify", payload, headers
        )

    def record_recall_effectiveness(self, recall_id, payload, headers):
        return self._request(
            "POST",
            f"/registry/recalls/{recall_id}/record-effectiveness",
            payload,
            headers,
        )

    def terminate_recall(self, recall_id, headers):
        return self._request(
            "POST", f"/registry/recalls/{recall_id}/terminate", {}, headers
        )


api_client = ApiClient()
