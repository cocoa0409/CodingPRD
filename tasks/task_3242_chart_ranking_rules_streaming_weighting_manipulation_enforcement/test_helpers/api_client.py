"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601}, headers=headers,
        )

    # --- charts ---
    def create_chart(self, payload, headers):
        return self._request("POST", "/charts", payload, headers)

    def list_charts(self, headers, params=None):
        return self._request("GET", "/charts", headers=headers, params=params)

    def get_chart(self, chart_id, headers):
        return self._request("GET", f"/charts/{chart_id}", headers=headers)

    # --- methodology versions ---
    def create_methodology_version(self, chart_id, payload, headers):
        return self._request(
            "POST", f"/charts/{chart_id}/methodology-versions", payload, headers)

    def list_methodology_versions(self, chart_id, headers, params=None):
        return self._request(
            "GET", f"/charts/{chart_id}/methodology-versions",
            headers=headers, params=params)

    def activate_methodology_version(self, chart_id, mv_id, payload, headers):
        return self._request(
            "POST",
            f"/charts/{chart_id}/methodology-versions/{mv_id}/activate",
            payload, headers)

    def get_methodology_version_chart(self, mv_id, headers):
        return self._request(
            "GET", f"/methodology-versions/{mv_id}/chart", headers=headers)

    def list_computed_weeks_of_methodology(self, mv_id, headers):
        return self._request(
            "GET", f"/methodology-versions/{mv_id}/computed-weeks",
            headers=headers)

    def list_freeze_resolutions_of_methodology(self, mv_id, headers):
        return self._request(
            "GET", f"/methodology-versions/{mv_id}/freeze-resolutions",
            headers=headers)

    # --- chart freezes ---
    def freeze_chart(self, chart_id, payload, headers):
        return self._request("POST", f"/charts/{chart_id}/freeze", payload, headers)

    def resolve_freeze(self, chart_id, freeze_id, payload, headers):
        return self._request(
            "POST", f"/charts/{chart_id}/freeze/{freeze_id}/resolve",
            payload, headers)

    def list_chart_freezes(self, chart_id, headers, params=None):
        return self._request(
            "GET", f"/charts/{chart_id}/freezes", headers=headers, params=params)

    # --- chart weeks ---
    def create_chart_week(self, chart_id, payload, headers):
        return self._request("POST", f"/charts/{chart_id}/weeks", payload, headers)

    def list_chart_weeks(self, chart_id, headers, params=None):
        return self._request(
            "GET", f"/charts/{chart_id}/weeks", headers=headers, params=params)

    def get_chart_week(self, week_id, headers):
        return self._request("GET", f"/chart-weeks/{week_id}", headers=headers)

    def lock_week(self, week_id, headers):
        return self._request("POST", f"/chart-weeks/{week_id}/lock", headers=headers)

    def compute_week(self, week_id, headers):
        return self._request("POST", f"/chart-weeks/{week_id}/compute", headers=headers)

    def publish_week(self, week_id, headers):
        return self._request("POST", f"/chart-weeks/{week_id}/publish", headers=headers)

    def holiday_adjust_week(self, week_id, payload, headers):
        return self._request(
            "POST", f"/chart-weeks/{week_id}/holiday-adjust", payload, headers)

    def list_week_entries(self, week_id, headers, params=None):
        return self._request(
            "GET", f"/chart-weeks/{week_id}/entries", headers=headers, params=params)

    def list_week_reports(self, week_id, headers, params=None):
        return self._request(
            "GET", f"/chart-weeks/{week_id}/reports", headers=headers, params=params)

    def list_week_signals(self, week_id, headers, params=None):
        return self._request(
            "GET", f"/chart-weeks/{week_id}/signals", headers=headers, params=params)

    def list_week_sale_batches(self, week_id, headers, params=None):
        return self._request(
            "GET", f"/chart-weeks/{week_id}/sale-batches",
            headers=headers, params=params)

    # --- providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def suspend_provider(self, provider_id, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/suspend", headers=headers)

    def list_provider_reports(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"/providers/{provider_id}/reports",
            headers=headers, params=params)

    def submit_report(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/reports", payload, headers)

    # --- consumption reports ---
    def get_report(self, report_id, headers):
        return self._request(
            "GET", f"/consumption-reports/{report_id}", headers=headers)

    def accept_report(self, report_id, headers):
        return self._request(
            "POST", f"/consumption-reports/{report_id}/accept", headers=headers)

    def quarantine_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/consumption-reports/{report_id}/quarantine",
            payload, headers)

    def reject_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/consumption-reports/{report_id}/reject", payload, headers)

    # --- label accounts ---
    def create_label(self, payload, headers):
        return self._request("POST", "/labels", payload, headers)

    def get_label(self, label_id, headers):
        return self._request("GET", f"/labels/{label_id}", headers=headers)

    def list_label_titles(self, label_id, headers, params=None):
        return self._request(
            "GET", f"/labels/{label_id}/titles", headers=headers, params=params)

    def list_label_disputes(self, label_id, headers, params=None):
        return self._request(
            "GET", f"/labels/{label_id}/disputes", headers=headers, params=params)

    def reinstate_label(self, label_id, headers):
        return self._request(
            "POST", f"/label-accounts/{label_id}/reinstate", headers=headers)

    # --- titles ---
    def create_title(self, payload, headers):
        return self._request("POST", "/titles", payload, headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/titles", headers=headers, params=params)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/titles/{title_id}", headers=headers)

    def reinstate_title(self, title_id, headers):
        return self._request(
            "POST", f"/titles/{title_id}/reinstate", headers=headers)

    def list_title_reports(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/titles/{title_id}/reports", headers=headers, params=params)

    def list_title_entries(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/titles/{title_id}/entries", headers=headers, params=params)

    def list_title_signals(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/titles/{title_id}/signals", headers=headers, params=params)

    def list_title_disputes(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/titles/{title_id}/disputes", headers=headers, params=params)

    # --- sale batches ---
    def create_sale_batch(self, title_id, payload, headers):
        return self._request(
            "POST", f"/titles/{title_id}/sale-batches", payload, headers)

    def list_sale_batches(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/titles/{title_id}/sale-batches",
            headers=headers, params=params)

    # --- manipulation signals ---
    def create_signal(self, payload, headers):
        return self._request("POST", "/manipulation-signals", payload, headers)

    def list_signals(self, headers, params=None):
        return self._request(
            "GET", "/manipulation-signals", headers=headers, params=params)

    def get_signal(self, signal_id, headers):
        return self._request(
            "GET", f"/manipulation-signals/{signal_id}", headers=headers)

    def dismiss_signal(self, signal_id, headers):
        return self._request(
            "POST", f"/manipulation-signals/{signal_id}/dismiss", headers=headers)

    def escalate_signal(self, signal_id, payload, headers):
        return self._request(
            "POST", f"/manipulation-signals/{signal_id}/escalate",
            payload, headers)

    def list_signal_investigations(self, signal_id, headers):
        return self._request(
            "GET", f"/manipulation-signals/{signal_id}/investigations",
            headers=headers)

    # --- investigations ---
    def list_investigations(self, headers, params=None):
        return self._request(
            "GET", "/investigations", headers=headers, params=params)

    def get_investigation(self, investigation_id, headers):
        return self._request(
            "GET", f"/investigations/{investigation_id}", headers=headers)

    def resolve_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"/investigations/{investigation_id}/resolve",
            payload, headers)

    # --- genre disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/genre-disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request(
            "GET", "/genre-disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/genre-disputes/{dispute_id}", headers=headers)

    def review_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/genre-disputes/{dispute_id}/review", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/genre-disputes/{dispute_id}/resolve", payload, headers)

    def list_chart_disputes(self, chart_id, headers, params=None):
        return self._request(
            "GET", f"/charts/{chart_id}/disputes", headers=headers, params=params)

    # --- recurrent rules ---
    def create_recurrent_rule(self, payload, headers):
        return self._request("POST", "/recurrent-rules", payload, headers)

    def get_recurrent_rule(self, rule_id, headers):
        return self._request(
            "GET", f"/recurrent-rules/{rule_id}", headers=headers)

    def list_recurrent_rule_charts(self, rule_id, headers, params=None):
        return self._request(
            "GET", f"/recurrent-rules/{rule_id}/charts",
            headers=headers, params=params)


api_client = ApiClient()
