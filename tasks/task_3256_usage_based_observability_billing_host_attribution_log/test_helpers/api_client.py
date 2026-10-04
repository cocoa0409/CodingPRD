"""API client: one method per endpoint defined in the PRD (§4).

All API resources live under the /api prefix; the logical-clock test-driving
endpoint is the sole exception and lives outside it (PRD §2).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock (test-driving; outside /api) -----------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---- plan tier configs -----------------------------------------------
    def create_plan_tier_config(self, payload, headers):
        return self._request("POST", "/api/plan-tier-configs", payload, headers)

    def get_plan_tier_config(self, config_id, headers):
        return self._request(
            "GET", f"/api/plan-tier-configs/{config_id}", headers=headers
        )

    # ---- billing accounts --------------------------------------------------
    def create_billing_account(self, payload, headers):
        return self._request("POST", "/api/billing-accounts", payload, headers)

    def get_billing_account(self, account_id, headers):
        return self._request(
            "GET", f"/api/billing-accounts/{account_id}", headers=headers
        )

    def list_billing_accounts(self, headers, params=None):
        return self._request(
            "GET", "/api/billing-accounts", headers=headers, params=params
        )

    # ---- billing periods ----------------------------------------------------
    def create_billing_period(self, account_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/billing-periods",
            payload,
            headers,
        )

    def get_billing_period(self, account_id, period_id, headers):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}",
            headers=headers,
        )

    def list_billing_periods(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/billing-periods",
            headers=headers,
            params=params,
        )

    def close_billing_period(self, account_id, period_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/close",
            {},
            headers,
        )

    def settle_billing_period(self, account_id, period_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/settle",
            {},
            headers,
        )

    def get_chargeback(self, account_id, period_id, headers):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/chargeback",
            headers=headers,
        )

    # ---- host hour records --------------------------------------------------
    def create_host_hour_record(self, account_id, period_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/host-hour-records",
            payload,
            headers,
        )

    def list_host_hour_records(self, account_id, period_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/host-hour-records",
            headers=headers,
            params=params,
        )

    # ---- meter accumulators ---------------------------------------------------
    def list_meter_accumulators(self, account_id, period_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/meter-accumulators",
            headers=headers,
            params=params,
        )

    # ---- log events ----------------------------------------------------------
    def ingest_log_event(self, account_id, period_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/log-events",
            payload,
            headers,
        )

    def list_log_events(self, account_id, period_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/log-events",
            headers=headers,
            params=params,
        )

    def reindex_log_event(self, account_id, event_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/log-events/{event_id}/reindex",
            {},
            headers,
        )

    # ---- retention tiers ------------------------------------------------------
    def create_retention_tier(self, account_id, payload, headers):
        return self._request(
            "POST", f"/api/billing-accounts/{account_id}/retention-tiers", payload, headers
        )

    def list_retention_tiers(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/retention-tiers",
            headers=headers,
            params=params,
        )

    # ---- exclusion filters ----------------------------------------------------
    def create_exclusion_filter(self, account_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/exclusion-filters",
            payload,
            headers,
        )

    def list_exclusion_filters(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/exclusion-filters",
            headers=headers,
            params=params,
        )

    def disable_exclusion_filter(self, account_id, filter_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/exclusion-filters/{filter_id}/disable",
            {},
            headers,
        )

    # ---- custom metric series -------------------------------------------------
    def create_custom_metric_series(self, account_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/custom-metric-series",
            payload,
            headers,
        )

    def list_custom_metric_series(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/custom-metric-series",
            headers=headers,
            params=params,
        )

    def post_rollup(self, account_id, series_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/custom-metric-series/{series_id}/rollup",
            payload,
            headers,
        )

    # ---- cardinality incidents ------------------------------------------------
    def list_cardinality_incidents(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/cardinality-incidents",
            headers=headers,
            params=params,
        )

    def triage_incident(self, account_id, incident_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/cardinality-incidents/{incident_id}/triage",
            {},
            headers,
        )

    def remediate_incident(self, account_id, incident_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/cardinality-incidents/{incident_id}/remediate",
            payload,
            headers,
        )

    def close_incident(self, account_id, incident_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/cardinality-incidents/{incident_id}/close",
            {},
            headers,
        )

    # ---- commitments ----------------------------------------------------------
    def create_commitment(self, account_id, payload, headers):
        return self._request(
            "POST", f"/api/billing-accounts/{account_id}/commitments", payload, headers
        )

    def list_commitments(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/commitments",
            headers=headers,
            params=params,
        )

    def activate_commitment(self, account_id, commitment_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/commitments/{commitment_id}/activate",
            {},
            headers,
        )

    def top_up_commitment(self, account_id, commitment_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/commitments/{commitment_id}/top-up",
            payload,
            headers,
        )

    # ---- teams ------------------------------------------------------------------
    def create_team(self, account_id, payload, headers):
        return self._request(
            "POST", f"/api/billing-accounts/{account_id}/teams", payload, headers
        )

    def list_teams(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/api/billing-accounts/{account_id}/teams", headers=headers, params=params
        )

    # ---- usage records ----------------------------------------------------------
    def create_usage_record(self, account_id, period_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/usage-records",
            payload,
            headers,
        )

    def list_usage_records(self, account_id, period_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/billing-periods/{period_id}/usage-records",
            headers=headers,
            params=params,
        )

    # ---- attribution disputes ---------------------------------------------------
    def create_dispute(self, account_id, usage_record_id, payload, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/usage-records/{usage_record_id}/disputes",
            payload,
            headers,
        )

    def accept_dispute(self, account_id, dispute_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/attribution-disputes/{dispute_id}/accept",
            {},
            headers,
        )

    def reject_dispute(self, account_id, dispute_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/attribution-disputes/{dispute_id}/reject",
            {},
            headers,
        )

    # ---- tag policies -------------------------------------------------------------
    def create_tag_policy(self, account_id, payload, headers):
        return self._request(
            "POST", f"/api/billing-accounts/{account_id}/tag-policies", payload, headers
        )

    def list_tag_policies(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/tag-policies",
            headers=headers,
            params=params,
        )

    # ---- monitors -----------------------------------------------------------------
    def create_monitor(self, account_id, payload, headers):
        return self._request(
            "POST", f"/api/billing-accounts/{account_id}/monitors", payload, headers
        )

    def list_monitors(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/monitors",
            headers=headers,
            params=params,
        )

    def mute_monitor(self, account_id, monitor_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/monitors/{monitor_id}/mute",
            {},
            headers,
        )

    def delete_monitor(self, account_id, monitor_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/monitors/{monitor_id}/delete",
            {},
            headers,
        )

    # ---- invoices ------------------------------------------------------------------
    def get_invoice(self, account_id, invoice_id, headers):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/invoices/{invoice_id}",
            headers=headers,
        )

    def list_invoice_lines(self, account_id, invoice_id, headers):
        return self._request(
            "GET",
            f"/api/billing-accounts/{account_id}/invoices/{invoice_id}/lines",
            headers=headers,
        )

    def issue_invoice(self, account_id, invoice_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/invoices/{invoice_id}/issue",
            {},
            headers,
        )

    def pay_invoice(self, account_id, invoice_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/invoices/{invoice_id}/pay",
            {},
            headers,
        )

    def void_invoice(self, account_id, invoice_id, headers):
        return self._request(
            "POST",
            f"/api/billing-accounts/{account_id}/invoices/{invoice_id}/void",
            {},
            headers,
        )

    # ---- flat single-resource / filtered-list GETs -------------------------------
    def get_billing_period_flat(self, period_id, headers):
        return self._request("GET", f"/api/billing-periods/{period_id}", headers=headers)

    def list_billing_periods_flat(self, headers, params=None):
        return self._request("GET", "/api/billing-periods", headers=headers, params=params)

    def get_host_hour_record_flat(self, record_id, headers):
        return self._request("GET", f"/api/host-hour-records/{record_id}", headers=headers)

    def list_host_hour_records_flat(self, headers, params=None):
        return self._request("GET", "/api/host-hour-records", headers=headers, params=params)

    def get_meter_accumulator_flat(self, accumulator_id, headers):
        return self._request(
            "GET", f"/api/meter-accumulators/{accumulator_id}", headers=headers
        )

    def list_meter_accumulators_flat(self, headers, params=None):
        return self._request(
            "GET", "/api/meter-accumulators", headers=headers, params=params
        )

    def get_log_event_flat(self, event_id, headers):
        return self._request("GET", f"/api/log-events/{event_id}", headers=headers)

    def list_log_events_flat(self, headers, params=None):
        return self._request("GET", "/api/log-events", headers=headers, params=params)

    def get_retention_tier_flat(self, tier_id, headers):
        return self._request("GET", f"/api/retention-tiers/{tier_id}", headers=headers)

    def list_retention_tiers_flat(self, headers, params=None):
        return self._request("GET", "/api/retention-tiers", headers=headers, params=params)

    def get_exclusion_filter_flat(self, filter_id, headers):
        return self._request("GET", f"/api/exclusion-filters/{filter_id}", headers=headers)

    def list_exclusion_filters_flat(self, headers, params=None):
        return self._request("GET", "/api/exclusion-filters", headers=headers, params=params)

    def get_custom_metric_series_flat(self, series_id, headers):
        return self._request(
            "GET", f"/api/custom-metric-series/{series_id}", headers=headers
        )

    def list_custom_metric_series_flat(self, headers, params=None):
        return self._request(
            "GET", "/api/custom-metric-series", headers=headers, params=params
        )

    def get_cardinality_incident_flat(self, incident_id, headers):
        return self._request(
            "GET", f"/api/cardinality-incidents/{incident_id}", headers=headers
        )

    def list_cardinality_incidents_flat(self, headers, params=None):
        return self._request(
            "GET", "/api/cardinality-incidents", headers=headers, params=params
        )

    def get_commitment_flat(self, commitment_id, headers):
        return self._request("GET", f"/api/commitments/{commitment_id}", headers=headers)

    def list_commitments_flat(self, headers, params=None):
        return self._request("GET", "/api/commitments", headers=headers, params=params)

    def get_team_flat(self, team_id, headers):
        return self._request("GET", f"/api/teams/{team_id}", headers=headers)

    def list_teams_flat(self, headers, params=None):
        return self._request("GET", "/api/teams", headers=headers, params=params)

    def get_usage_record_flat(self, usage_record_id, headers):
        return self._request("GET", f"/api/usage-records/{usage_record_id}", headers=headers)

    def list_usage_records_flat(self, headers, params=None):
        return self._request("GET", "/api/usage-records", headers=headers, params=params)

    def get_attribution_dispute_flat(self, dispute_id, headers):
        return self._request(
            "GET", f"/api/attribution-disputes/{dispute_id}", headers=headers
        )

    def list_attribution_disputes_flat(self, headers, params=None):
        return self._request(
            "GET", "/api/attribution-disputes", headers=headers, params=params
        )

    def get_tag_policy_flat(self, policy_id, headers):
        return self._request("GET", f"/api/tag-policies/{policy_id}", headers=headers)

    def list_tag_policies_flat(self, headers, params=None):
        return self._request("GET", "/api/tag-policies", headers=headers, params=params)

    def get_monitor_flat(self, monitor_id, headers):
        return self._request("GET", f"/api/monitors/{monitor_id}", headers=headers)

    def list_monitors_flat(self, headers, params=None):
        return self._request("GET", "/api/monitors", headers=headers, params=params)

    def get_invoice_flat(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices_flat(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice_line_flat(self, line_id, headers):
        return self._request("GET", f"/api/invoice-lines/{line_id}", headers=headers)

    def list_invoice_lines_flat(self, headers, params=None):
        return self._request("GET", "/api/invoice-lines", headers=headers, params=params)


api_client = ApiClient()
