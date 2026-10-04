"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/wte/_clock/set_current_utc", payload, headers)

    # --- municipalities ---
    def create_municipality(self, payload, headers):
        return self._request("POST", "/wte/municipalities", payload, headers)

    def list_municipalities(self, headers, params=None):
        return self._request("GET", "/wte/municipalities", headers=headers, params=params)

    def get_municipality(self, municipality_id, headers):
        return self._request("GET", f"/wte/municipalities/{municipality_id}", headers=headers)

    # --- host community agreements ---
    def create_host_community_agreement(self, payload, headers):
        return self._request("POST", "/wte/host-community-agreements", payload, headers)

    def list_host_community_agreements(self, headers, params=None):
        return self._request("GET", "/wte/host-community-agreements", headers=headers, params=params)

    def get_host_community_agreement(self, agreement_id, headers):
        return self._request("GET", f"/wte/host-community-agreements/{agreement_id}", headers=headers)

    # --- waste supply agreements ---
    def create_waste_supply_agreement(self, payload, headers):
        return self._request("POST", "/wte/waste-supply-agreements", payload, headers)

    def list_waste_supply_agreements(self, headers, params=None):
        return self._request("GET", "/wte/waste-supply-agreements", headers=headers, params=params)

    def get_waste_supply_agreement(self, agreement_id, headers):
        return self._request("GET", f"/wte/waste-supply-agreements/{agreement_id}", headers=headers)

    def activate_waste_supply_agreement(self, agreement_id, headers):
        return self._request("POST", f"/wte/waste-supply-agreements/{agreement_id}/activate", {}, headers)

    def terminate_waste_supply_agreement(self, agreement_id, headers):
        return self._request("POST", f"/wte/waste-supply-agreements/{agreement_id}/terminate", {}, headers)

    # --- waste deliveries ---
    def create_waste_delivery(self, payload, headers):
        return self._request("POST", "/wte/waste-deliveries", payload, headers)

    def list_waste_deliveries(self, headers, params=None):
        return self._request("GET", "/wte/waste-deliveries", headers=headers, params=params)

    def get_waste_delivery(self, delivery_id, headers):
        return self._request("GET", f"/wte/waste-deliveries/{delivery_id}", headers=headers)

    def update_waste_delivery(self, delivery_id, payload, headers):
        return self._request("PUT", f"/wte/waste-deliveries/{delivery_id}", payload, headers)

    def receive_waste_delivery(self, delivery_id, headers):
        return self._request("POST", f"/wte/waste-deliveries/{delivery_id}/receive", {}, headers)

    def accept_waste_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/wte/waste-deliveries/{delivery_id}/accept", payload, headers)

    def reject_waste_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/wte/waste-deliveries/{delivery_id}/reject", payload, headers)

    def divert_waste_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/wte/waste-deliveries/{delivery_id}/divert", payload, headers)

    # --- boilers ---
    def create_boiler(self, payload, headers):
        return self._request("POST", "/wte/boilers", payload, headers)

    def list_boilers(self, headers, params=None):
        return self._request("GET", "/wte/boilers", headers=headers, params=params)

    def get_boiler(self, boiler_id, headers):
        return self._request("GET", f"/wte/boilers/{boiler_id}", headers=headers)

    def derate_boiler(self, boiler_id, payload, headers):
        return self._request("POST", f"/wte/boilers/{boiler_id}/derate", payload, headers)

    def restore_boiler(self, boiler_id, headers):
        return self._request("POST", f"/wte/boilers/{boiler_id}/restore", {}, headers)

    def decommission_boiler(self, boiler_id, headers):
        return self._request("POST", f"/wte/boilers/{boiler_id}/decommission", {}, headers)

    # --- outage windows ---
    def create_outage_window(self, payload, headers):
        return self._request("POST", "/wte/outage-windows", payload, headers)

    def list_outage_windows(self, headers, params=None):
        return self._request("GET", "/wte/outage-windows", headers=headers, params=params)

    def get_outage_window(self, outage_id, headers):
        return self._request("GET", f"/wte/outage-windows/{outage_id}", headers=headers)

    def start_outage_window(self, outage_id, payload, headers):
        return self._request("POST", f"/wte/outage-windows/{outage_id}/start", payload, headers)

    def complete_outage_window(self, outage_id, headers):
        return self._request("POST", f"/wte/outage-windows/{outage_id}/complete", {}, headers)

    def cancel_outage_window(self, outage_id, headers):
        return self._request("POST", f"/wte/outage-windows/{outage_id}/cancel", {}, headers)

    # --- diversion plans and legs ---
    def create_diversion_plan(self, payload, headers):
        return self._request("POST", "/wte/diversion-plans", payload, headers)

    def list_diversion_plans(self, headers, params=None):
        return self._request("GET", "/wte/diversion-plans", headers=headers, params=params)

    def get_diversion_plan(self, plan_id, headers):
        return self._request("GET", f"/wte/diversion-plans/{plan_id}", headers=headers)

    def approve_diversion_plan(self, plan_id, headers):
        return self._request("POST", f"/wte/diversion-plans/{plan_id}/approve", {}, headers)

    def create_diversion_leg(self, plan_id, payload, headers):
        return self._request("POST", f"/wte/diversion-plans/{plan_id}/legs", payload, headers)

    def list_diversion_legs(self, plan_id, headers, params=None):
        return self._request("GET", f"/wte/diversion-plans/{plan_id}/legs", headers=headers, params=params)

    # --- daily throughput reports ---
    def create_daily_throughput_report(self, payload, headers):
        return self._request("POST", "/wte/daily-throughput-reports", payload, headers)

    def list_daily_throughput_reports(self, headers, params=None):
        return self._request("GET", "/wte/daily-throughput-reports", headers=headers, params=params)

    def get_daily_throughput_report(self, report_id, headers):
        return self._request("GET", f"/wte/daily-throughput-reports/{report_id}", headers=headers)

    def update_daily_throughput_report(self, report_id, payload, headers):
        return self._request("PUT", f"/wte/daily-throughput-reports/{report_id}", payload, headers)

    def finalize_daily_throughput_report(self, report_id, headers):
        return self._request("POST", f"/wte/daily-throughput-reports/{report_id}/finalize", {}, headers)

    # --- power purchase agreements ---
    def create_power_purchase_agreement(self, payload, headers):
        return self._request("POST", "/wte/power-purchase-agreements", payload, headers)

    def list_power_purchase_agreements(self, headers, params=None):
        return self._request("GET", "/wte/power-purchase-agreements", headers=headers, params=params)

    def get_power_purchase_agreement(self, ppa_id, headers):
        return self._request("GET", f"/wte/power-purchase-agreements/{ppa_id}", headers=headers)

    def activate_power_purchase_agreement(self, ppa_id, headers):
        return self._request("POST", f"/wte/power-purchase-agreements/{ppa_id}/activate", {}, headers)

    def terminate_power_purchase_agreement(self, ppa_id, headers):
        return self._request("POST", f"/wte/power-purchase-agreements/{ppa_id}/terminate", {}, headers)

    # --- energy deliveries ---
    def create_energy_delivery(self, payload, headers):
        return self._request("POST", "/wte/energy-deliveries", payload, headers)

    def list_energy_deliveries(self, headers, params=None):
        return self._request("GET", "/wte/energy-deliveries", headers=headers, params=params)

    def get_energy_delivery(self, delivery_id, headers):
        return self._request("GET", f"/wte/energy-deliveries/{delivery_id}", headers=headers)

    # --- metals recovery ---
    def create_metals_recovery_contract(self, payload, headers):
        return self._request("POST", "/wte/metals-recovery-contracts", payload, headers)

    def list_metals_recovery_contracts(self, headers, params=None):
        return self._request("GET", "/wte/metals-recovery-contracts", headers=headers, params=params)

    def get_metals_recovery_contract(self, contract_id, headers):
        return self._request("GET", f"/wte/metals-recovery-contracts/{contract_id}", headers=headers)

    def suspend_metals_recovery_contract(self, contract_id, headers):
        return self._request("POST", f"/wte/metals-recovery-contracts/{contract_id}/suspend", {}, headers)

    def terminate_metals_recovery_contract(self, contract_id, headers):
        return self._request("POST", f"/wte/metals-recovery-contracts/{contract_id}/terminate", {}, headers)

    def create_metals_recovery_batch(self, payload, headers):
        return self._request("POST", "/wte/metals-recovery-batches", payload, headers)

    def list_metals_recovery_batches(self, headers, params=None):
        return self._request("GET", "/wte/metals-recovery-batches", headers=headers, params=params)

    def get_metals_recovery_batch(self, batch_id, headers):
        return self._request("GET", f"/wte/metals-recovery-batches/{batch_id}", headers=headers)

    def settle_metals_recovery_batch(self, batch_id, headers):
        return self._request("POST", f"/wte/metals-recovery-batches/{batch_id}/settle", {}, headers)

    def dispute_metals_recovery_batch(self, batch_id, headers):
        return self._request("POST", f"/wte/metals-recovery-batches/{batch_id}/dispute", {}, headers)

    def resolve_metals_recovery_batch(self, batch_id, headers):
        return self._request("POST", f"/wte/metals-recovery-batches/{batch_id}/resolve", {}, headers)

    # --- landfills / ash shipments / ash tests ---
    def create_landfill(self, payload, headers):
        return self._request("POST", "/wte/landfills", payload, headers)

    def list_landfills(self, headers, params=None):
        return self._request("GET", "/wte/landfills", headers=headers, params=params)

    def get_landfill(self, landfill_id, headers):
        return self._request("GET", f"/wte/landfills/{landfill_id}", headers=headers)

    def create_ash_shipment(self, payload, headers):
        return self._request("POST", "/wte/ash-shipments", payload, headers)

    def list_ash_shipments(self, headers, params=None):
        return self._request("GET", "/wte/ash-shipments", headers=headers, params=params)

    def get_ash_shipment(self, shipment_id, headers):
        return self._request("GET", f"/wte/ash-shipments/{shipment_id}", headers=headers)

    def submit_ash_shipment_testing(self, shipment_id, headers):
        return self._request("POST", f"/wte/ash-shipments/{shipment_id}/submit-testing", {}, headers)

    def complete_ash_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/wte/ash-shipments/{shipment_id}/complete", payload, headers)

    def reject_ash_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/wte/ash-shipments/{shipment_id}/reject", payload, headers)

    def create_ash_test(self, shipment_id, payload, headers):
        return self._request("POST", f"/wte/ash-shipments/{shipment_id}/tests", payload, headers)

    def list_ash_tests(self, shipment_id, headers, params=None):
        return self._request("GET", f"/wte/ash-shipments/{shipment_id}/tests", headers=headers, params=params)

    # --- emissions ---
    def create_emissions_permit(self, payload, headers):
        return self._request("POST", "/wte/emissions-permits", payload, headers)

    def list_emissions_permits(self, headers, params=None):
        return self._request("GET", "/wte/emissions-permits", headers=headers, params=params)

    def get_emissions_permit(self, permit_id, headers):
        return self._request("GET", f"/wte/emissions-permits/{permit_id}", headers=headers)

    def suspend_emissions_permit(self, permit_id, headers):
        return self._request("POST", f"/wte/emissions-permits/{permit_id}/suspend", {}, headers)

    def create_emissions_reading(self, payload, headers):
        return self._request("POST", "/wte/emissions-readings", payload, headers)

    def list_emissions_readings(self, headers, params=None):
        return self._request("GET", "/wte/emissions-readings", headers=headers, params=params)

    def get_emissions_reading(self, reading_id, headers):
        return self._request("GET", f"/wte/emissions-readings/{reading_id}", headers=headers)

    # --- settlements ---
    def run_put_or_pay_settlement(self, payload, headers):
        return self._request("POST", "/wte/settlements/put-or-pay/run", payload, headers)


api_client = ApiClient()
