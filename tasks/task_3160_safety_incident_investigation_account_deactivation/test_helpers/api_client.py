"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Clock -------------------------------------------------------------
    def set_current_utc(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- Account -----------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/safety/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/safety/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/safety/accounts/{account_id}", headers=headers)

    def list_account_trips(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/safety/accounts/{account_id}/trips", headers=headers, params=params
        )

    def list_account_enforcement_actions(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/safety/accounts/{account_id}/enforcement-actions",
            headers=headers,
            params=params,
        )

    def list_account_background_checks(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/safety/accounts/{account_id}/background-checks",
            headers=headers,
            params=params,
        )

    def list_account_incidents(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/safety/accounts/{account_id}/incidents", headers=headers, params=params
        )

    # --- DeviceCluster -----------------------------------------------------
    def create_device_cluster(self, payload, headers):
        return self._request("POST", "/safety/device-clusters", payload, headers)

    def get_device_cluster(self, cluster_id, headers):
        return self._request("GET", f"/safety/device-clusters/{cluster_id}", headers=headers)

    def list_device_clusters(self, headers, params=None):
        return self._request("GET", "/safety/device-clusters", headers=headers, params=params)

    def list_cluster_links(self, cluster_id, headers, params=None):
        return self._request(
            "GET",
            f"/safety/device-clusters/{cluster_id}/account-device-links",
            headers=headers,
            params=params,
        )

    def stabilize_cluster(self, cluster_id, expected_cluster_version, headers):
        return self._request(
            "POST",
            f"/safety/clusters/{cluster_id}/stabilize",
            {"expected_cluster_version": expected_cluster_version},
            headers,
        )

    # --- AccountDeviceLink -------------------------------------------------
    def create_account_device_link(self, payload, headers):
        return self._request("POST", "/safety/account-device-links", payload, headers)

    def list_account_device_links(self, headers, params=None):
        return self._request(
            "GET", "/safety/account-device-links", headers=headers, params=params
        )

    def get_account_device_link(self, link_id, headers):
        return self._request("GET", f"/safety/account-device-links/{link_id}", headers=headers)

    def dormancy_sweep(self, headers):
        return self._request(
            "POST", "/safety/account-device-links/dormancy-sweep", {}, headers
        )

    # --- Trip --------------------------------------------------------------
    def create_trip(self, payload, headers):
        return self._request("POST", "/safety/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/safety/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/safety/trips", headers=headers, params=params)

    def complete_start_trip(self, trip_id, headers):
        return self._request("POST", f"/safety/trips/{trip_id}/complete-start", {}, headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/safety/trips/{trip_id}/complete", {}, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/safety/trips/{trip_id}/cancel", {}, headers)

    # --- SafetyIncident ----------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", "/safety/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/safety/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/safety/incidents/{incident_id}", headers=headers)

    def patch_incident_severity(self, incident_id, aggravator_codes, headers):
        return self._request(
            "PATCH",
            f"/safety/incidents/{incident_id}/severity",
            {"aggravator_codes": aggravator_codes},
            headers,
        )

    def hold_incident(self, incident_id, headers):
        return self._request("POST", f"/safety/incidents/{incident_id}/hold", {}, headers)

    def release_hold(self, incident_id, headers):
        return self._request(
            "POST", f"/safety/incidents/{incident_id}/hold/release", {}, headers
        )

    def withdraw_incident(self, incident_id, headers):
        return self._request("POST", f"/safety/incidents/{incident_id}/withdraw", {}, headers)

    def create_evidence(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/safety/incidents/{incident_id}/evidence", payload, headers
        )

    def list_evidence(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/safety/incidents/{incident_id}/evidence", headers=headers, params=params
        )

    def accept_evidence(self, incident_id, evidence_id, accepted, headers):
        return self._request(
            "POST",
            f"/safety/incidents/{incident_id}/evidence/accept",
            {"evidence_id": evidence_id, "accepted": accepted},
            headers,
        )

    def get_evidence_score(self, incident_id, headers):
        return self._request(
            "GET", f"/safety/incidents/{incident_id}/evidence-score", headers=headers
        )

    def get_decision_criteria(self, incident_id, headers):
        return self._request(
            "GET", f"/safety/incidents/{incident_id}/decision-criteria", headers=headers
        )

    def commit_decision(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/safety/incidents/{incident_id}/decision", payload, headers
        )

    def file_appeal(self, incident_id, headers):
        return self._request("POST", f"/safety/incidents/{incident_id}/appeals", {}, headers)

    def commit_appeal_outcome(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/safety/incidents/{incident_id}/appeals/outcome", payload, headers
        )

    def get_appeal_eligibility(self, incident_id, headers):
        return self._request(
            "GET", f"/safety/incidents/{incident_id}/appeals/eligibility", headers=headers
        )

    def get_incident_summary(self, headers, params=None):
        return self._request(
            "GET", "/safety/incidents/summary", headers=headers, params=params
        )

    # --- EnforcementAction -------------------------------------------------
    def get_enforcement_action(self, action_id, headers):
        return self._request("GET", f"/safety/enforcement-actions/{action_id}", headers=headers)

    def list_enforcement_actions(self, headers, params=None):
        return self._request(
            "GET", "/safety/enforcement-actions", headers=headers, params=params
        )

    def expiry_sweep(self, account_id, expected_account_version, headers):
        return self._request(
            "POST",
            "/safety/enforcement-actions/expiry-sweep",
            {"account_id": account_id, "expected_account_version": expected_account_version},
            headers,
        )

    def review_tick(self, account_id, headers):
        return self._request(
            "POST", "/safety/enforcement-actions/review-tick", {"account_id": account_id}, headers
        )

    # --- RegulatorReport ---------------------------------------------------
    def create_regulator_report(self, payload, headers):
        return self._request("POST", "/safety/regulator-reports", payload, headers)

    def get_regulator_report(self, report_id, headers):
        return self._request("GET", f"/safety/regulator-reports/{report_id}", headers=headers)

    def list_regulator_reports(self, headers, params=None):
        return self._request(
            "GET", "/safety/regulator-reports", headers=headers, params=params
        )

    def list_incident_regulator_reports(self, incident_id, headers, params=None):
        return self._request(
            "GET",
            f"/safety/incidents/{incident_id}/regulator-reports",
            headers=headers,
            params=params,
        )

    def rollup_sweep(self, incident_id, headers):
        return self._request(
            "POST", "/safety/regulator-reports/rollup-sweep", {"incident_id": incident_id}, headers
        )

    def window_open(self, expected_report_version, headers):
        return self._request(
            "POST",
            "/safety/regulator-reports/window-open",
            {"expected_report_version": expected_report_version},
            headers,
        )

    def report_attempt(self, report_id, window_index, headers):
        return self._request(
            "POST",
            "/safety/regulator-reports/attempt",
            {"report_id": report_id, "window_index": window_index},
            headers,
        )

    # --- BackgroundCheck ---------------------------------------------------
    def get_background_check(self, check_id, headers):
        return self._request("GET", f"/safety/background-checks/{check_id}", headers=headers)

    def list_background_checks(self, headers, params=None):
        return self._request(
            "GET", "/safety/background-checks", headers=headers, params=params
        )

    def acknowledge_background_check(self, check_id, headers):
        return self._request(
            "POST", f"/safety/background-checks/{check_id}/acknowledge", {}, headers
        )

    def adjudicate_background_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/safety/background-checks/{check_id}/adjudicate", payload, headers
        )

    def rescreen_sweep(self, headers):
        return self._request("POST", "/safety/background-checks/rescreen-sweep", {}, headers)

    # --- PlatformPolicy ----------------------------------------------------
    def create_platform_policy(self, payload, headers):
        return self._request("POST", "/safety/platform-policies", payload, headers)

    def get_platform_policy(self, policy_id, headers):
        return self._request("GET", f"/safety/platform-policies/{policy_id}", headers=headers)

    def list_platform_policies(self, headers, params=None):
        return self._request("GET", "/safety/platform-policies", headers=headers, params=params)

    def patch_platform_policy(self, policy_id, payload, headers):
        return self._request("PATCH", f"/safety/platform-policies/{policy_id}", payload, headers)

    def config_advance(self, region_code, advance_counter, headers):
        return self._request(
            "POST",
            "/safety/config/advance",
            {"region_code": region_code, "advance_counter": advance_counter},
            headers,
        )


api_client = ApiClient()