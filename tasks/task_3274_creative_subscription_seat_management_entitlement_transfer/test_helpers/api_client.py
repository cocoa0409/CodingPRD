"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/licensing/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- organizations ---
    def create_organization(self, payload, headers):
        return self._request("POST", "/licensing/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"/licensing/organizations/{org_id}", headers=headers)

    def list_organizations(self, headers, params=None):
        return self._request("GET", "/licensing/organizations", headers=headers, params=params)

    # --- admins ---
    def create_admin(self, payload, headers):
        return self._request("POST", "/licensing/admins", payload, headers)

    def get_admin(self, admin_id, headers):
        return self._request("GET", f"/licensing/admins/{admin_id}", headers=headers)

    def list_admins(self, headers, params=None):
        return self._request("GET", "/licensing/admins", headers=headers, params=params)

    # --- end users ---
    def create_end_user(self, payload, headers):
        return self._request("POST", "/licensing/end-users", payload, headers)

    def get_end_user(self, user_id, headers):
        return self._request("GET", f"/licensing/end-users/{user_id}", headers=headers)

    def list_end_users(self, headers, params=None):
        return self._request("GET", "/licensing/end-users", headers=headers, params=params)

    def deactivate_end_user(self, user_id, headers):
        return self._request("POST", f"/licensing/end-users/{user_id}/deactivate", headers=headers)

    def reactivate_end_user(self, user_id, headers):
        return self._request("POST", f"/licensing/end-users/{user_id}/reactivate", headers=headers)

    def mark_departed_end_user(self, user_id, headers):
        return self._request("POST", f"/licensing/end-users/{user_id}/mark-departed", headers=headers)

    # --- devices ---
    def create_device(self, payload, headers):
        return self._request("POST", "/licensing/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/licensing/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/licensing/devices", headers=headers, params=params)

    # --- plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/licensing/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/licensing/plans/{plan_id}", headers=headers)

    # --- product versions ---
    def create_product_version(self, payload, headers):
        return self._request("POST", "/licensing/product-versions", payload, headers)

    def get_product_version(self, version_id, headers):
        return self._request("GET", f"/licensing/product-versions/{version_id}", headers=headers)

    def list_product_versions(self, headers, params=None):
        return self._request("GET", "/licensing/product-versions", headers=headers, params=params)

    def deprecate_product_version(self, version_id, headers):
        return self._request("POST", f"/licensing/product-versions/{version_id}/deprecate", headers=headers)

    def restore_product_version(self, version_id, headers):
        return self._request("POST", f"/licensing/product-versions/{version_id}/restore", headers=headers)

    def force_upgrade_product_version(self, version_id, payload, headers):
        return self._request("POST", f"/licensing/product-versions/{version_id}/force-upgrade",
                             payload, headers)

    # --- resellers ---
    def create_reseller(self, payload, headers):
        return self._request("POST", "/licensing/resellers", payload, headers)

    def get_reseller(self, reseller_id, headers):
        return self._request("GET", f"/licensing/resellers/{reseller_id}", headers=headers)

    def suspend_reseller(self, reseller_id, headers):
        return self._request("POST", f"/licensing/resellers/{reseller_id}/suspend", headers=headers)

    def reinstate_reseller(self, reseller_id, headers):
        return self._request("POST", f"/licensing/resellers/{reseller_id}/reinstate", headers=headers)

    # --- subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/licensing/subscriptions", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/licensing/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/licensing/subscriptions", headers=headers, params=params)

    def activate_subscription(self, sub_id, headers):
        return self._request("POST", f"/licensing/subscriptions/{sub_id}/activate", headers=headers)

    def settle_subscription(self, sub_id, headers):
        return self._request("POST", f"/licensing/subscriptions/{sub_id}/settle", headers=headers)

    # --- seats ---
    def create_seat(self, payload, headers):
        return self._request("POST", "/licensing/seats", payload, headers)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/licensing/seats/{seat_id}", headers=headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", "/licensing/seats", headers=headers, params=params)

    def assign_seat(self, seat_id, payload, headers):
        return self._request("POST", f"/licensing/seats/{seat_id}/assign", payload, headers)

    def reclaim_seat(self, seat_id, headers):
        return self._request("POST", f"/licensing/seats/{seat_id}/reclaim", headers=headers)

    def cancel_reclaim_seat(self, seat_id, headers):
        return self._request("POST", f"/licensing/seats/{seat_id}/reclaim/cancel", headers=headers)

    def finalize_reclaim_seat(self, seat_id, headers):
        return self._request("POST", f"/licensing/seats/{seat_id}/reclaim/finalize", headers=headers)

    # --- entitlements ---
    def get_entitlement(self, ent_id, headers):
        return self._request("GET", f"/licensing/entitlements/{ent_id}", headers=headers)

    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/licensing/entitlements", headers=headers, params=params)

    def activate_entitlement(self, ent_id, payload, headers):
        return self._request("POST", f"/licensing/entitlements/{ent_id}/activate", payload, headers)

    # --- transfer requests ---
    def create_transfer_request(self, payload, headers):
        return self._request("POST", "/licensing/transfer-requests", payload, headers)

    def get_transfer_request(self, tr_id, headers):
        return self._request("GET", f"/licensing/transfer-requests/{tr_id}", headers=headers)

    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", "/licensing/transfer-requests", headers=headers, params=params)

    def approve_transfer_request(self, tr_id, headers):
        return self._request("POST", f"/licensing/transfer-requests/{tr_id}/approve", headers=headers)

    def reject_transfer_request(self, tr_id, headers):
        return self._request("POST", f"/licensing/transfer-requests/{tr_id}/reject", headers=headers)

    def execute_transfer_request(self, tr_id, headers):
        return self._request("POST", f"/licensing/transfer-requests/{tr_id}/execute", headers=headers)

    # --- cancellation requests ---
    def create_cancellation_request(self, payload, headers):
        return self._request("POST", "/licensing/cancellation-requests", payload, headers)

    def get_cancellation_request(self, cr_id, headers):
        return self._request("GET", f"/licensing/cancellation-requests/{cr_id}", headers=headers)

    def list_cancellation_requests(self, headers, params=None):
        return self._request("GET", "/licensing/cancellation-requests", headers=headers, params=params)

    def finalize_cancellation_request(self, cr_id, headers):
        return self._request("POST", f"/licensing/cancellation-requests/{cr_id}/finalize", headers=headers)

    # --- add-on services ---
    def create_add_on_service(self, payload, headers):
        return self._request("POST", "/licensing/add-on-services", payload, headers)

    def get_add_on_service(self, addon_id, headers):
        return self._request("GET", f"/licensing/add-on-services/{addon_id}", headers=headers)

    def list_add_on_services(self, headers, params=None):
        return self._request("GET", "/licensing/add-on-services", headers=headers, params=params)

    def consume_add_on_service(self, addon_id, payload, headers):
        return self._request("POST", f"/licensing/add-on-services/{addon_id}/consume", payload, headers)

    def top_up_add_on_service(self, addon_id, payload, headers):
        return self._request("POST", f"/licensing/add-on-services/{addon_id}/top-up", payload, headers)

    def cancel_add_on_service(self, addon_id, headers):
        return self._request("POST", f"/licensing/add-on-services/{addon_id}/cancel", headers=headers)

    # --- assets ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/licensing/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/licensing/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/licensing/assets", headers=headers, params=params)

    def transfer_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/licensing/assets/{asset_id}/transfer", payload, headers)

    def accept_asset_transfer(self, asset_id, headers):
        return self._request("POST", f"/licensing/assets/{asset_id}/transfer/accept", headers=headers)

    def cancel_asset_transfer(self, asset_id, headers):
        return self._request("POST", f"/licensing/assets/{asset_id}/transfer/cancel", headers=headers)

    def claim_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/licensing/assets/{asset_id}/claim", payload, headers)

    def purge_asset(self, asset_id, headers):
        return self._request("POST", f"/licensing/assets/{asset_id}/purge", headers=headers)

    # --- deployment packages ---
    def create_deployment_package(self, payload, headers):
        return self._request("POST", "/licensing/deployment-packages", payload, headers)

    def get_deployment_package(self, pkg_id, headers):
        return self._request("GET", f"/licensing/deployment-packages/{pkg_id}", headers=headers)

    def list_deployment_packages(self, headers, params=None):
        return self._request("GET", "/licensing/deployment-packages", headers=headers, params=params)

    def submit_deployment_package(self, pkg_id, headers):
        return self._request("POST", f"/licensing/deployment-packages/{pkg_id}/submit", headers=headers)

    def approve_deployment_package(self, pkg_id, headers):
        return self._request("POST", f"/licensing/deployment-packages/{pkg_id}/approve", headers=headers)

    def reject_deployment_package(self, pkg_id, headers):
        return self._request("POST", f"/licensing/deployment-packages/{pkg_id}/reject", headers=headers)

    def publish_deployment_package(self, pkg_id, headers):
        return self._request("POST", f"/licensing/deployment-packages/{pkg_id}/publish", headers=headers)

    def retire_deployment_package(self, pkg_id, headers):
        return self._request("POST", f"/licensing/deployment-packages/{pkg_id}/retire", headers=headers)

    # --- reseller orders ---
    def create_reseller_order(self, payload, headers):
        return self._request("POST", "/licensing/reseller-orders", payload, headers)

    def get_reseller_order(self, order_id, headers):
        return self._request("GET", f"/licensing/reseller-orders/{order_id}", headers=headers)

    def list_reseller_orders(self, headers, params=None):
        return self._request("GET", "/licensing/reseller-orders", headers=headers, params=params)

    def fulfill_reseller_order(self, order_id, headers):
        return self._request("POST", f"/licensing/reseller-orders/{order_id}/fulfill", headers=headers)

    def reject_reseller_order(self, order_id, headers):
        return self._request("POST", f"/licensing/reseller-orders/{order_id}/reject", headers=headers)

    def cancel_reseller_order(self, order_id, headers):
        return self._request("POST", f"/licensing/reseller-orders/{order_id}/cancel", headers=headers)

    # --- compliance audits ---
    def create_compliance_audit(self, payload, headers):
        return self._request("POST", "/licensing/compliance-audits", payload, headers)

    def get_compliance_audit(self, audit_id, headers):
        return self._request("GET", f"/licensing/compliance-audits/{audit_id}", headers=headers)

    def list_compliance_audits(self, headers, params=None):
        return self._request("GET", "/licensing/compliance-audits", headers=headers, params=params)

    def raise_audit_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/licensing/compliance-audits/{audit_id}/raise-findings",
                             payload, headers)

    def remediate_compliance_audit(self, audit_id, headers):
        return self._request("POST", f"/licensing/compliance-audits/{audit_id}/remediate", headers=headers)

    def close_compliance_audit(self, audit_id, headers):
        return self._request("POST", f"/licensing/compliance-audits/{audit_id}/close", headers=headers)


api_client = ApiClient()
