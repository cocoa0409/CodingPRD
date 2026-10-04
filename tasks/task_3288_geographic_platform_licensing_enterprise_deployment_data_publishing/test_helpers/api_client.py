"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Organizations ---
    def create_org(self, payload, headers):
        return self._request("POST", "/geo-orgs", payload, headers)

    def get_org(self, org_id, headers):
        return self._request("GET", f"/geo-orgs/{org_id}", headers=headers)

    def transition_org(self, org_id, payload, headers):
        return self._request("POST", f"/geo-orgs/{org_id}/transition", payload, headers)

    # --- Credit pools ---
    def create_credit_pool(self, payload, headers):
        return self._request("POST", "/geo-orgs/credit-pools", payload, headers)

    def get_credit_pool(self, pool_id, headers):
        return self._request("GET", f"/geo-orgs/credit-pools/{pool_id}", headers=headers)

    def list_credit_pools(self, headers, params=None):
        return self._request("GET", "/geo-orgs/credit-pools", headers=headers, params=params)

    def get_credit_pool_projection(self, org_id, headers, params=None):
        return self._request("GET", f"/geo-orgs/{org_id}/credit-pool-projection", headers=headers, params=params)

    # --- License products ---
    def create_license_product(self, payload, headers):
        return self._request("POST", "/geo-orgs/license-products", payload, headers)

    def retire_license_product(self, product_id, headers):
        return self._request("POST", f"/geo-orgs/license-products/{product_id}/retire", {}, headers)

    # --- License grants ---
    def create_license_grant(self, payload, headers):
        return self._request("POST", "/geo-orgs/license-grants", payload, headers)

    def list_license_grants(self, headers, params=None):
        return self._request("GET", "/geo-orgs/license-grants", headers=headers, params=params)

    def get_license_grant(self, grant_id, headers):
        return self._request("GET", f"/geo-orgs/license-grants/{grant_id}", headers=headers)

    def transition_license_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/geo-orgs/license-grants/{grant_id}/transition", payload, headers)

    # --- Extension grants ---
    def create_extension_grant(self, payload, headers):
        return self._request("POST", "/geo-orgs/extension-grants", payload, headers)

    def list_extension_grants(self, grant_id, headers, params=None):
        return self._request("GET", f"/geo-orgs/license-grants/{grant_id}/extension-grants", headers=headers, params=params)

    # --- Named users ---
    def create_named_user(self, payload, headers):
        return self._request("POST", "/geo-orgs/named-users", payload, headers)

    def list_named_users(self, headers, params=None):
        return self._request("GET", "/geo-orgs/named-users", headers=headers, params=params)

    def get_named_user(self, user_id, headers):
        return self._request("GET", f"/geo-orgs/named-users/{user_id}", headers=headers)

    def transition_named_user(self, user_id, payload, headers):
        return self._request("POST", f"/geo-orgs/named-users/{user_id}/transition", payload, headers)

    # --- Deployment servers ---
    def create_deployment_server(self, payload, headers):
        return self._request("POST", "/geo-orgs/deployment-servers", payload, headers)

    def list_deployment_servers(self, headers, params=None):
        return self._request("GET", "/geo-orgs/deployment-servers", headers=headers, params=params)

    def get_deployment_server(self, server_id, headers):
        return self._request("GET", f"/geo-orgs/deployment-servers/{server_id}", headers=headers)

    def transition_deployment_server(self, server_id, payload, headers):
        return self._request("POST", f"/geo-orgs/deployment-servers/{server_id}/transition", payload, headers)

    # --- Version compatibility rules ---
    def create_version_compatibility_rule(self, payload, headers):
        return self._request("POST", "/geo-orgs/version-compatibility-rules", payload, headers)

    # --- Content items ---
    def create_content_item(self, payload, headers):
        return self._request("POST", "/geo-orgs/content-items", payload, headers)

    def list_content_items(self, headers, params=None):
        return self._request("GET", "/geo-orgs/content-items", headers=headers, params=params)

    def get_content_item(self, item_id, headers):
        return self._request("GET", f"/geo-orgs/content-items/{item_id}", headers=headers)

    def transition_content_item(self, item_id, payload, headers):
        return self._request("POST", f"/geo-orgs/content-items/{item_id}/transition", payload, headers)

    def share_content_item(self, item_id, payload, headers):
        return self._request("POST", f"/geo-orgs/content-items/{item_id}/share", payload, headers)

    def moderate_content_item(self, item_id, payload, headers):
        return self._request("POST", f"/geo-orgs/content-items/{item_id}/moderate", payload, headers)

    # --- API keys ---
    def create_api_key(self, payload, headers):
        return self._request("POST", "/geo-orgs/api-keys", payload, headers)

    def list_api_keys(self, user_id, headers, params=None):
        return self._request("GET", f"/geo-orgs/named-users/{user_id}/api-keys", headers=headers, params=params)

    def revoke_api_key(self, key_id, headers):
        return self._request("POST", f"/geo-orgs/api-keys/{key_id}/revoke", {}, headers)

    # --- Credit batches ---
    def create_credit_batch(self, payload, headers):
        return self._request("POST", "/geo-orgs/credit-batches", payload, headers)

    def list_credit_batches(self, headers, params=None):
        return self._request("GET", "/geo-orgs/credit-batches", headers=headers, params=params)

    def get_credit_batch(self, batch_id, headers):
        return self._request("GET", f"/geo-orgs/credit-batches/{batch_id}", headers=headers)

    def transition_credit_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/geo-orgs/credit-batches/{batch_id}/transition", payload, headers)

    # --- Eligibility verifications ---
    def create_eligibility_verification(self, payload, headers):
        return self._request("POST", "/geo-orgs/eligibility-verifications", payload, headers)

    def list_eligibility_verifications(self, headers, params=None):
        return self._request("GET", "/geo-orgs/eligibility-verifications", headers=headers, params=params)

    def get_eligibility_verification(self, ev_id, headers):
        return self._request("GET", f"/geo-orgs/eligibility-verifications/{ev_id}", headers=headers)

    def transition_eligibility_verification(self, ev_id, payload, headers):
        return self._request("POST", f"/geo-orgs/eligibility-verifications/{ev_id}/transition", payload, headers)


api_client = ApiClient()
