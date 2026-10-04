"""API client: one method per route in the PRD §4 endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/api"


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper over the Kettle Campaign Corps API surface."""

    # --- logical clock (PRD §2.11) ---------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- units (PRD §2.4) ------------------------------------------------
    def create_unit(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"{API_PREFIX}/units/{unit_id}", headers=headers)

    # --- campaigns (PRD §3.2) --------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"{API_PREFIX}/campaigns/{campaign_id}", headers=headers)

    def activate_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/campaigns/{campaign_id}/activate",
                             payload, headers)

    def get_campaign_summary(self, campaign_id, headers):
        return self._request("GET", f"{API_PREFIX}/campaigns/{campaign_id}/summary",
                             headers=headers)

    # --- host sites (PRD §3.1) -------------------------------------------
    def create_host_site(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/host-sites", payload, headers)

    def list_host_sites(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/host-sites", headers=headers, params=params)

    def get_host_site(self, host_site_id, headers):
        return self._request("GET", f"{API_PREFIX}/host-sites/{host_site_id}", headers=headers)

    def decide_host_site(self, host_site_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/host-sites/{host_site_id}/approve",
                             payload, headers)

    def renew_host_site(self, host_site_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/host-sites/{host_site_id}/renew",
                             payload, headers)

    # --- kettle locations (PRD §3.1) -------------------------------------
    def create_kettle_location(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/kettle-locations", payload, headers)

    def list_kettle_locations(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/kettle-locations", headers=headers,
                             params=params)

    def get_kettle_location(self, location_id, headers):
        return self._request("GET", f"{API_PREFIX}/kettle-locations/{location_id}",
                             headers=headers)

    def activate_kettle_location(self, location_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/kettle-locations/{location_id}/activate",
                             payload, headers)

    def suspend_kettle_location(self, location_id, headers):
        return self._request("POST", f"{API_PREFIX}/kettle-locations/{location_id}/suspend",
                             headers=headers)

    def close_kettle_location(self, location_id, headers):
        return self._request("POST", f"{API_PREFIX}/kettle-locations/{location_id}/close",
                             headers=headers)

    def get_location_performance(self, location_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/kettle-locations/{location_id}/performance",
                             headers=headers, params=params)

    # --- bell ringers (PRD §3.3) -----------------------------------------
    def create_bell_ringer(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/bell-ringers", payload, headers)

    def list_bell_ringers(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/bell-ringers", headers=headers, params=params)

    def get_bell_ringer(self, ringer_id, headers):
        return self._request("GET", f"{API_PREFIX}/bell-ringers/{ringer_id}", headers=headers)

    def request_screening(self, ringer_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/bell-ringers/{ringer_id}/screenings",
                             payload, headers)

    def complete_screening(self, ringer_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/bell-ringers/{ringer_id}/screenings/complete",
                             payload, headers)

    def separate_ringer(self, ringer_id, headers):
        return self._request("POST", f"{API_PREFIX}/bell-ringers/{ringer_id}/separate",
                             headers=headers)

    # --- shifts (PRD §3.3) -----------------------------------------------
    def create_shift(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"{API_PREFIX}/shifts/{shift_id}", headers=headers)

    def confirm_shift(self, shift_id, headers):
        return self._request("POST", f"{API_PREFIX}/shifts/{shift_id}/confirm", headers=headers)

    def check_in_shift(self, shift_id, headers):
        return self._request("POST", f"{API_PREFIX}/shifts/{shift_id}/check-in", headers=headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"{API_PREFIX}/shifts/{shift_id}/complete", headers=headers)

    def cancel_shift(self, shift_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/shifts/{shift_id}/cancel", payload, headers)

    def no_show_shift(self, shift_id, headers):
        return self._request("POST", f"{API_PREFIX}/shifts/{shift_id}/no-show", headers=headers)

    def rebook_shift(self, shift_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/shifts/{shift_id}/rebook", payload, headers)

    def auto_assign_shift(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/shifts/auto-assign", payload, headers)

    # --- kettle collections (PRD §3.4) -----------------------------------
    def create_collection(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/kettle-collections", payload, headers)

    def list_collections(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/kettle-collections", headers=headers,
                             params=params)

    def get_collection(self, collection_id, headers):
        return self._request("GET", f"{API_PREFIX}/kettle-collections/{collection_id}",
                             headers=headers)

    def verify_collection(self, collection_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/kettle-collections/{collection_id}/verify",
                             payload, headers)

    def recount_collection(self, collection_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/kettle-collections/{collection_id}/recount",
                             payload, headers)

    def deposit_collection(self, collection_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/kettle-collections/{collection_id}/deposit",
                             payload, headers)

    def reconcile_collection(self, collection_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/kettle-collections/{collection_id}/reconcile",
                             payload, headers)

    # --- digital givings (PRD §3.5) --------------------------------------
    def create_digital_giving(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/digital-givings", payload, headers)

    def list_digital_givings(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/digital-givings", headers=headers,
                             params=params)

    def get_digital_giving(self, giving_id, headers):
        return self._request("GET", f"{API_PREFIX}/digital-givings/{giving_id}", headers=headers)

    def attribute_digital_giving(self, giving_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/digital-givings/{giving_id}/attribute",
                             payload, headers)

    def reverse_digital_giving(self, giving_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/digital-givings/{giving_id}/reverse",
                             payload, headers)

    # --- assistance programs and applications (PRD §3.6) -----------------
    def create_assistance_program(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/assistance-programs", payload, headers)

    def list_assistance_programs(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/assistance-programs", headers=headers,
                             params=params)

    def get_assistance_program(self, program_id, headers):
        return self._request("GET", f"{API_PREFIX}/assistance-programs/{program_id}",
                             headers=headers)

    def open_assistance_program(self, program_id, headers):
        return self._request("POST", f"{API_PREFIX}/assistance-programs/{program_id}/open",
                             headers=headers)

    def create_assistance_application(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/assistance-applications", payload, headers)

    def list_assistance_applications(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/assistance-applications", headers=headers,
                             params=params)

    def get_assistance_application(self, application_id, headers):
        return self._request("GET", f"{API_PREFIX}/assistance-applications/{application_id}",
                             headers=headers)

    def screen_assistance_application(self, application_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/assistance-applications/{application_id}/screen",
                             payload, headers)

    def approve_assistance_application(self, application_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/assistance-applications/{application_id}/approve",
                             payload, headers)

    def schedule_distribution(self, application_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/assistance-applications/{application_id}/schedule-distribution",
            payload, headers)

    def complete_distribution(self, application_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/assistance-applications/{application_id}/distribution/complete",
            payload, headers)

    def distribution_no_show(self, application_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/assistance-applications/{application_id}/distribution/no-show",
            headers=headers)

    # --- corps programs (PRD §3.7) ---------------------------------------
    def create_corps_program(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/corps-programs", payload, headers)

    def list_corps_programs(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/corps-programs", headers=headers, params=params)

    def get_corps_program(self, program_id, headers):
        return self._request("GET", f"{API_PREFIX}/corps-programs/{program_id}", headers=headers)

    def suspend_corps_program(self, program_id, headers):
        return self._request("POST", f"{API_PREFIX}/corps-programs/{program_id}/suspend",
                             headers=headers)

    def complete_corps_program(self, program_id, headers):
        return self._request("POST", f"{API_PREFIX}/corps-programs/{program_id}/complete",
                             headers=headers)

    def enroll_corps_program(self, program_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/corps-programs/{program_id}/enroll",
                             payload, headers)

    def withdraw_corps_program(self, program_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/corps-programs/{program_id}/withdraw",
                             payload, headers)

    # --- disaster deployments (PRD §3.8) ---------------------------------
    def create_deployment(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/disaster-deployments", payload, headers)

    def list_deployments(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/disaster-deployments", headers=headers,
                             params=params)

    def get_deployment(self, deployment_id, headers):
        return self._request("GET", f"{API_PREFIX}/disaster-deployments/{deployment_id}",
                             headers=headers)

    def decide_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/disaster-deployments/{deployment_id}/approve",
                             payload, headers)

    def stage_deployment(self, deployment_id, headers):
        return self._request("POST", f"{API_PREFIX}/disaster-deployments/{deployment_id}/stage",
                             headers=headers)

    def deploy_deployment(self, deployment_id, headers):
        return self._request("POST", f"{API_PREFIX}/disaster-deployments/{deployment_id}/deploy",
                             headers=headers)

    def cancel_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/disaster-deployments/{deployment_id}/cancel",
                             payload, headers)

    def demobilize_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/disaster-deployments/{deployment_id}/demobilize",
                             payload, headers)

    # --- reallocation decisions (PRD §3.9) -------------------------------
    def create_reallocation(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/reallocation-decisions", payload, headers)

    def list_reallocations(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/reallocation-decisions", headers=headers,
                             params=params)

    def get_reallocation(self, decision_id, headers):
        return self._request("GET", f"{API_PREFIX}/reallocation-decisions/{decision_id}",
                             headers=headers)

    def approve_reallocation(self, decision_id, headers):
        return self._request("POST", f"{API_PREFIX}/reallocation-decisions/{decision_id}/approve",
                             headers=headers)

    def reject_reallocation(self, decision_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/reallocation-decisions/{decision_id}/reject",
                             payload, headers)

    def revise_reallocation(self, decision_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/reallocation-decisions/{decision_id}/revise",
                             payload, headers)

    def apply_reallocation(self, decision_id, headers):
        return self._request("POST", f"{API_PREFIX}/reallocation-decisions/{decision_id}/apply",
                             headers=headers)


api_client = ApiClient()
