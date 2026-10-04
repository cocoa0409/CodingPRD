"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving endpoints ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/v1/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def run_periodic(self, headers, payload=None):
        return self._request("POST", "/v1/_ops/run_periodic", payload or {}, headers)

    # --- organizations / catalog ---
    def create_organization(self, payload, headers):
        return self._request("POST", "/v1/organizations", payload, headers)

    def create_key_model(self, payload, headers):
        return self._request("POST", "/v1/key-models", payload, headers)

    # --- devices / fleet ---
    def create_device(self, org_id, payload, headers):
        return self._request("POST", f"/v1/organizations/{org_id}/devices", payload, headers)

    def list_devices(self, org_id, headers, params=None):
        return self._request("GET", f"/v1/organizations/{org_id}/devices", headers=headers, params=params)

    def get_fleet_fit(self, org_id, model_code, headers):
        return self._request(
            "GET", f"/v1/organizations/{org_id}/fleet-fit",
            headers=headers, params={"model_code": model_code},
        )

    # --- employees ---
    def create_employee(self, org_id, payload, headers):
        return self._request("POST", f"/v1/organizations/{org_id}/employees", payload, headers)

    def terminate_employee(self, org_id, employee_id, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/employees/{employee_id}/terminate",
            {}, headers,
        )

    # --- identity accounts ---
    def get_identity_account(self, account_id, headers):
        return self._request("GET", f"/v1/identity-accounts/{account_id}", headers=headers)

    def lock_identity_account(self, account_id, headers):
        return self._request("POST", f"/v1/identity-accounts/{account_id}/lock", {}, headers)

    # --- purchase orders ---
    def create_purchase_order(self, org_id, payload, headers):
        return self._request("POST", f"/v1/organizations/{org_id}/purchase-orders", payload, headers)

    def list_purchase_orders(self, org_id, headers, params=None):
        return self._request("GET", f"/v1/organizations/{org_id}/purchase-orders", headers=headers, params=params)

    def approve_purchase_order(self, org_id, po_id, expected_version, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/purchase-orders/{po_id}/approve",
            {"expected_purchase_order_version": expected_version}, headers,
        )

    def ship_purchase_order(self, org_id, po_id, headers, supply_chain_cert_id=None):
        payload = {}
        if supply_chain_cert_id is not None:
            payload["supply_chain_cert_id"] = supply_chain_cert_id
        return self._request(
            "POST", f"/v1/organizations/{org_id}/purchase-orders/{po_id}/ship",
            payload, headers,
        )

    def receive_purchase_order(self, org_id, po_id, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/purchase-orders/{po_id}/receive",
            {}, headers,
        )

    def quarantine_purchase_order(self, org_id, po_id, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/purchase-orders/{po_id}/quarantine",
            {}, headers,
        )

    def release_purchase_order(self, org_id, po_id, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/purchase-orders/{po_id}/release",
            {}, headers,
        )

    # --- security keys ---
    def preregister_keys(self, org_id, po_id, payload, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/purchase-orders/{po_id}/keys",
            payload, headers,
        )

    def list_security_keys(self, org_id, headers, params=None):
        return self._request("GET", f"/v1/organizations/{org_id}/security-keys", headers=headers, params=params)

    def assign_security_key(self, org_id, key_id, identity_account_id, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/security-keys/{key_id}/assign",
            {"identity_account_id": identity_account_id}, headers,
        )

    def mark_distributed(self, org_id, key_id, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/security-keys/{key_id}/mark-distributed",
            {}, headers,
        )

    def return_to_stock(self, org_id, key_id, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/security-keys/{key_id}/return-to-stock",
            {}, headers,
        )

    def revoke_security_key(self, org_id, key_id, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/security-keys/{key_id}/revoke",
            {}, headers,
        )

    def attest_security_key(self, org_id, key_id, headers):
        return self._request(
            "POST", f"/v1/organizations/{org_id}/security-keys/{key_id}/attest",
            {}, headers,
        )

    # --- enrollment ceremonies ---
    def create_enrollment(self, account_id, security_key_id, headers):
        return self._request(
            "POST", f"/v1/identity-accounts/{account_id}/enrollments",
            {"security_key_id": security_key_id}, headers,
        )

    def list_enrollments(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/v1/identity-accounts/{account_id}/enrollments",
            headers=headers, params=params,
        )

    def activate_enrollment(self, account_id, enrollment_id, expected_version, headers):
        return self._request(
            "POST",
            f"/v1/identity-accounts/{account_id}/enrollments/{enrollment_id}/activate",
            {"expected_identity_account_version": expected_version}, headers,
        )

    def renew_enrollment(self, account_id, enrollment_id, headers):
        return self._request(
            "POST",
            f"/v1/identity-accounts/{account_id}/enrollments/{enrollment_id}/renew",
            {}, headers,
        )

    def revoke_enrollment(self, account_id, enrollment_id, headers):
        return self._request(
            "POST",
            f"/v1/identity-accounts/{account_id}/enrollments/{enrollment_id}/revoke",
            {}, headers,
        )

    # --- temporary access ---
    def create_temporary_access(self, account_id, payload, headers):
        return self._request(
            "POST", f"/v1/identity-accounts/{account_id}/temporary-access",
            payload, headers,
        )

    def list_temporary_access(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/v1/identity-accounts/{account_id}/temporary-access",
            headers=headers, params=params,
        )

    def use_temporary_access(self, account_id, grant_id, headers):
        return self._request(
            "POST",
            f"/v1/identity-accounts/{account_id}/temporary-access/{grant_id}/use",
            {}, headers,
        )

    def void_temporary_access(self, account_id, grant_id, headers):
        return self._request(
            "POST",
            f"/v1/identity-accounts/{account_id}/temporary-access/{grant_id}/void",
            {}, headers,
        )

    # --- subscriptions ---
    def create_subscription(self, org_id, payload, headers):
        return self._request("POST", f"/v1/organizations/{org_id}/subscriptions", payload, headers)

    def list_subscriptions(self, org_id, headers, params=None):
        return self._request("GET", f"/v1/organizations/{org_id}/subscriptions", headers=headers, params=params)

    # --- help desk cases ---
    def create_help_desk_case(self, payload, headers):
        return self._request("POST", "/v1/help-desk-cases", payload, headers)

    def list_help_desk_cases(self, headers, params=None):
        return self._request("GET", "/v1/help-desk-cases", headers=headers, params=params)

    def submit_case_review(self, case_id, headers):
        return self._request("POST", f"/v1/help-desk-cases/{case_id}/submit-review", {}, headers)

    def resolve_help_desk_case(self, case_id, payload, headers):
        return self._request("POST", f"/v1/help-desk-cases/{case_id}/resolve", payload, headers)


api_client = ApiClient()
