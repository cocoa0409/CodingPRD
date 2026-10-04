"""API client: one method per endpoint defined in the PRD (mounted under /hv)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock / billing simulation ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/hv/_clock/set_current_utc", payload, headers)

    def simulate_billing(self, payload, headers):
        return self._request("POST", "/hv/_billing/simulate", payload, headers)

    # ---- Accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/hv/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/hv/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/hv/accounts", headers=headers, params=params)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/hv/accounts/{account_id}/suspend", headers=headers)

    def reactivate_account(self, account_id, headers):
        return self._request("POST", f"/hv/accounts/{account_id}/reactivate", headers=headers)

    def cancel_account(self, account_id, headers):
        return self._request("POST", f"/hv/accounts/{account_id}/cancel", headers=headers)

    def change_plan(self, account_id, payload, headers):
        return self._request("PATCH", f"/hv/accounts/{account_id}/plan", payload, headers)

    # ---- Households ----
    def create_household(self, account_id, payload, headers):
        return self._request("POST", f"/hv/accounts/{account_id}/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/hv/households/{household_id}", headers=headers)

    def list_households(self, account_id, headers, params=None):
        return self._request("GET", f"/hv/accounts/{account_id}/households", headers=headers, params=params)

    def relocate_household(self, household_id, payload, headers):
        return self._request("POST", f"/hv/households/{household_id}/relocate", payload, headers)

    def dissolve_household(self, household_id, headers):
        return self._request("POST", f"/hv/households/{household_id}/dissolve", headers=headers)

    # ---- Members ----
    def create_member(self, account_id, payload, headers):
        return self._request("POST", f"/hv/accounts/{account_id}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/hv/members/{member_id}", headers=headers)

    def list_members(self, account_id, headers, params=None):
        return self._request("GET", f"/hv/accounts/{account_id}/members", headers=headers, params=params)

    def remove_member(self, member_id, headers):
        return self._request("POST", f"/hv/members/{member_id}/remove", headers=headers)

    # ---- Devices ----
    def create_device(self, household_id, payload, headers):
        return self._request("POST", f"/hv/households/{household_id}/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/hv/devices/{device_id}", headers=headers)

    def list_devices(self, household_id, headers, params=None):
        return self._request("GET", f"/hv/households/{household_id}/devices", headers=headers, params=params)

    def get_device_confidence(self, device_id, headers):
        return self._request("GET", f"/hv/devices/{device_id}/confidence", headers=headers)

    def signal_device(self, device_id, payload, headers):
        return self._request("POST", f"/hv/devices/{device_id}/signal", payload, headers)

    def trust_device(self, device_id, headers):
        return self._request("POST", f"/hv/devices/{device_id}/trust", headers=headers)

    def untrust_device(self, device_id, headers):
        return self._request("POST", f"/hv/devices/{device_id}/untrust", headers=headers)

    def remove_device(self, device_id, headers):
        return self._request("POST", f"/hv/devices/{device_id}/remove", headers=headers)

    # ---- Extra member slots ----
    def purchase_slot(self, account_id, payload, headers):
        return self._request("POST", f"/hv/accounts/{account_id}/extra-member-slots", payload, headers)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/hv/extra-member-slots/{slot_id}", headers=headers)

    def list_account_slots(self, account_id, headers, params=None):
        return self._request("GET", f"/hv/accounts/{account_id}/extra-member-slots", headers=headers, params=params)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/hv/extra-member-slots", headers=headers, params=params)

    def assign_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/hv/extra-member-slots/{slot_id}/assign", payload, headers)

    def revoke_slot(self, slot_id, headers):
        return self._request("POST", f"/hv/extra-member-slots/{slot_id}/revoke", headers=headers)

    def reoffer_slot(self, slot_id, headers):
        return self._request("POST", f"/hv/extra-member-slots/{slot_id}/reoffer", headers=headers)

    # ---- Verification challenges ----
    def issue_challenge(self, account_id, payload, headers):
        return self._request("POST", f"/hv/accounts/{account_id}/verification-challenges", payload, headers)

    def get_challenge(self, challenge_id, headers):
        return self._request("GET", f"/hv/verification-challenges/{challenge_id}", headers=headers)

    def list_challenges(self, account_id, headers, params=None):
        return self._request("GET", f"/hv/accounts/{account_id}/verification-challenges", headers=headers, params=params)

    def submit_challenge(self, challenge_id, payload, headers):
        return self._request("POST", f"/hv/verification-challenges/{challenge_id}/submit", payload, headers)

    def reissue_challenge(self, challenge_id, headers):
        return self._request("POST", f"/hv/verification-challenges/{challenge_id}/reissue", headers=headers)

    # ---- Travel passes ----
    def grant_travel_pass(self, device_id, payload, headers):
        return self._request("POST", f"/hv/devices/{device_id}/travel-passes", payload, headers)

    def get_travel_pass(self, pass_id, headers):
        return self._request("GET", f"/hv/travel-passes/{pass_id}", headers=headers)

    def list_travel_passes(self, device_id, headers, params=None):
        return self._request("GET", f"/hv/devices/{device_id}/travel-passes", headers=headers, params=params)

    def revoke_travel_pass(self, pass_id, headers):
        return self._request("POST", f"/hv/travel-passes/{pass_id}/revoke", headers=headers)

    def convert_travel_pass(self, pass_id, headers):
        return self._request("POST", f"/hv/travel-passes/{pass_id}/convert", headers=headers)

    # ---- Profile transfers ----
    def initiate_transfer(self, account_id, payload, headers):
        return self._request("POST", f"/hv/accounts/{account_id}/profile-transfers", payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/hv/profile-transfers/{transfer_id}", headers=headers)

    def list_account_transfers(self, account_id, headers, params=None):
        return self._request("GET", f"/hv/accounts/{account_id}/profile-transfers", headers=headers, params=params)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/hv/profile-transfers", headers=headers, params=params)

    def accept_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/hv/profile-transfers/{transfer_id}/accept", payload, headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/hv/profile-transfers/{transfer_id}/cancel", headers=headers)

    # ---- Playback sessions ----
    def start_playback(self, member_id, payload, headers):
        return self._request("POST", f"/hv/members/{member_id}/playback-sessions", payload, headers)

    def get_playback_session(self, session_id, headers):
        return self._request("GET", f"/hv/playback-sessions/{session_id}", headers=headers)

    def list_member_sessions(self, member_id, headers, params=None):
        return self._request("GET", f"/hv/members/{member_id}/playback-sessions", headers=headers, params=params)

    def list_device_sessions(self, device_id, headers, params=None):
        return self._request("GET", f"/hv/devices/{device_id}/playback-sessions", headers=headers, params=params)

    def end_playback(self, session_id, headers):
        return self._request("POST", f"/hv/playback-sessions/{session_id}/end", headers=headers)

    # ---- Downloads ----
    def create_download(self, member_id, payload, headers):
        return self._request("POST", f"/hv/members/{member_id}/downloads", payload, headers)

    def get_download(self, download_id, headers):
        return self._request("GET", f"/hv/downloads/{download_id}", headers=headers)

    def list_member_downloads(self, member_id, headers, params=None):
        return self._request("GET", f"/hv/members/{member_id}/downloads", headers=headers, params=params)

    def list_device_downloads(self, device_id, headers, params=None):
        return self._request("GET", f"/hv/devices/{device_id}/downloads", headers=headers, params=params)

    def delete_download(self, download_id, headers):
        return self._request("DELETE", f"/hv/downloads/{download_id}", headers=headers)

    # ---- Enforcement policies ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/hv/enforcement-policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/hv/enforcement-policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/hv/enforcement-policies", headers=headers, params=params)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/hv/enforcement-policies/{policy_id}/activate", headers=headers)

    def retire_policy(self, policy_id, headers):
        return self._request("POST", f"/hv/enforcement-policies/{policy_id}/retire", headers=headers)

    # ---- Enforcement metrics & churn summary ----
    def record_metric(self, account_id, payload, headers):
        return self._request("POST", f"/hv/accounts/{account_id}/enforcement-metrics", payload, headers)

    def list_metrics(self, account_id, headers, params=None):
        return self._request("GET", f"/hv/accounts/{account_id}/enforcement-metrics", headers=headers, params=params)

    def get_churn_summary(self, account_id, headers):
        return self._request("GET", f"/hv/accounts/{account_id}/churn-summary", headers=headers)


api_client = ApiClient()
