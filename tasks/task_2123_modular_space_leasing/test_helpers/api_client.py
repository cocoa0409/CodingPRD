"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Branch ───────────────────────────────────────────────────────────────
    def create_branch(self, payload, headers):
        return self._request("POST", "/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}", headers=headers)

    # ── Jurisdiction ─────────────────────────────────────────────────────────
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    # ── BuildingSpec ─────────────────────────────────────────────────────────
    def create_building_spec(self, payload, headers):
        return self._request("POST", "/building-specs", payload, headers)

    def get_building_spec(self, spec_id, headers):
        return self._request("GET", f"/building-specs/{spec_id}", headers=headers)

    # ── FloorplanConfiguration ───────────────────────────────────────────────
    def create_floorplan_configuration(self, payload, headers):
        return self._request("POST", "/floorplan-configurations", payload, headers)

    def get_floorplan_configuration(self, config_id, headers):
        return self._request(
            "GET", f"/floorplan-configurations/{config_id}", headers=headers)

    def list_floorplan_configurations(self, headers, params=None):
        return self._request(
            "GET", "/floorplan-configurations", headers=headers, params=params)

    def publish_floorplan_configuration(self, config_id, headers):
        return self._request(
            "POST", f"/floorplan-configurations/{config_id}/publish", {}, headers)

    # ── Unit ─────────────────────────────────────────────────────────────────
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # ── Customer ─────────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ── Lease ────────────────────────────────────────────────────────────────
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/activate", {}, headers)

    def void_lease(self, lease_id, headers, payload=None):
        return self._request(
            "POST", f"/leases/{lease_id}/void", payload or {}, headers)

    def extend_lease(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/leases/{lease_id}/extensions", payload, headers)

    # ── AccessoryPackage ─────────────────────────────────────────────────────
    def create_accessory_package(self, payload, headers):
        return self._request("POST", "/accessory-packages", payload, headers)

    def get_accessory_package(self, package_id, headers):
        return self._request(
            "GET", f"/accessory-packages/{package_id}", headers=headers)

    def list_accessory_packages(self, headers, params=None):
        return self._request(
            "GET", "/accessory-packages", headers=headers, params=params)

    # ── PermitApplication ────────────────────────────────────────────────────
    def create_permit_application(self, payload, headers):
        return self._request("POST", "/permit-applications", payload, headers)

    def get_permit_application(self, permit_id, headers):
        return self._request(
            "GET", f"/permit-applications/{permit_id}", headers=headers)

    def list_permit_applications(self, headers, params=None):
        return self._request(
            "GET", "/permit-applications", headers=headers, params=params)

    def submit_permit_application(self, permit_id, headers):
        return self._request(
            "POST", f"/permit-applications/{permit_id}/submit", {}, headers)

    def decide_permit_application(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/permit-applications/{permit_id}/decide", payload, headers)

    # ── LogisticsJob ─────────────────────────────────────────────────────────
    def create_logistics_job(self, payload, headers):
        return self._request("POST", "/logistics-jobs", payload, headers)

    def get_logistics_job(self, job_id, headers):
        return self._request("GET", f"/logistics-jobs/{job_id}", headers=headers)

    def list_logistics_jobs(self, headers, params=None):
        return self._request("GET", "/logistics-jobs", headers=headers, params=params)

    def dispatch_logistics_job(self, job_id, headers):
        return self._request("POST", f"/logistics-jobs/{job_id}/dispatch", {}, headers)

    def complete_logistics_job(self, job_id, headers):
        return self._request("POST", f"/logistics-jobs/{job_id}/complete", {}, headers)

    def cancel_logistics_job(self, job_id, headers, payload=None):
        return self._request(
            "POST", f"/logistics-jobs/{job_id}/cancel", payload or {}, headers)

    # ── DamageAssessment ─────────────────────────────────────────────────────
    def create_damage_assessment(self, payload, headers):
        return self._request("POST", "/damage-assessments", payload, headers)

    def get_damage_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/damage-assessments/{assessment_id}", headers=headers)

    def list_damage_assessments(self, headers, params=None):
        return self._request(
            "GET", "/damage-assessments", headers=headers, params=params)

    def create_damage_line_item(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/damage-assessments/{assessment_id}/line-items", payload, headers)

    def list_damage_line_items(self, assessment_id, headers, params=None):
        return self._request(
            "GET", f"/damage-assessments/{assessment_id}/line-items",
            headers=headers, params=params)

    def submit_damage_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/damage-assessments/{assessment_id}/submit", {}, headers)

    def dispute_damage_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/damage-assessments/{assessment_id}/dispute", payload, headers)

    def finalize_damage_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/damage-assessments/{assessment_id}/finalize", payload, headers)

    # ── RefurbishmentOrder ───────────────────────────────────────────────────
    def create_refurbishment_order(self, payload, headers):
        return self._request("POST", "/refurbishment-orders", payload, headers)

    def get_refurbishment_order(self, order_id, headers):
        return self._request(
            "GET", f"/refurbishment-orders/{order_id}", headers=headers)

    def list_refurbishment_orders(self, headers, params=None):
        return self._request(
            "GET", "/refurbishment-orders", headers=headers, params=params)

    def approve_refurbishment_order(self, order_id, headers):
        return self._request(
            "POST", f"/refurbishment-orders/{order_id}/approve", {}, headers)

    def reject_refurbishment_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/refurbishment-orders/{order_id}/reject", payload, headers)

    def complete_refurbishment_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/refurbishment-orders/{order_id}/complete", payload, headers)

    # ── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
