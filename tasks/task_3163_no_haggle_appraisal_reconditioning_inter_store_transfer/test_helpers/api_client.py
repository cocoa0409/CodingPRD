"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Store ---
    def create_store(self, payload, headers):
        return self._request("POST", "/v1/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/v1/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/v1/stores/{store_id}", headers=headers)

    def list_ledger_entries(self, store_id, headers, params=None):
        return self._request("GET", f"/v1/stores/{store_id}/ledger-entries",
                             headers=headers, params=params)

    # --- CustomerAccount ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/v1/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/v1/customers/{customer_id}", headers=headers)

    # --- Associate ---
    def create_associate(self, payload, headers):
        return self._request("POST", "/v1/associates", payload, headers)

    def list_associates(self, headers, params=None):
        return self._request("GET", "/v1/associates", headers=headers, params=params)

    def get_associate(self, associate_id, headers):
        return self._request("GET", f"/v1/associates/{associate_id}", headers=headers)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/v1/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/v1/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/v1/vehicles/{vehicle_id}/list", {}, headers)

    def create_pricing_event(self, vehicle_id, payload, headers):
        return self._request("POST", f"/v1/vehicles/{vehicle_id}/pricing-events",
                             payload, headers)

    def list_pricing_events(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/pricing-events",
                             headers=headers, params=params)

    def list_vehicle_appraisals(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/appraisals",
                             headers=headers, params=params)

    def list_vehicle_inspections(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/inspections",
                             headers=headers, params=params)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/v1/inspections", headers=headers, params=params)

    def list_vehicle_transfer_requests(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/transfer-requests",
                             headers=headers, params=params)

    def list_vehicle_auction_lots(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/auction-lots",
                             headers=headers, params=params)

    # --- Appraisal ---
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/v1/appraisals", payload, headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/v1/appraisals", headers=headers, params=params)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/v1/appraisals/{appraisal_id}", headers=headers)

    def void_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/v1/appraisals/{appraisal_id}/void", {}, headers)

    # --- ReconditioningInspection / RepairLineItem ---
    def open_inspection(self, vehicle_id, payload, headers):
        return self._request("POST", f"/v1/vehicles/{vehicle_id}/inspections",
                             payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/v1/inspections/{inspection_id}", headers=headers)

    def add_line_item(self, inspection_id, payload, headers):
        return self._request("POST", f"/v1/inspections/{inspection_id}/line-items",
                             payload, headers)

    def list_line_items(self, inspection_id, headers, params=None):
        return self._request("GET", f"/v1/inspections/{inspection_id}/line-items",
                             headers=headers, params=params)

    def approve_line_item(self, inspection_id, line_item_id, headers):
        return self._request(
            "POST",
            f"/v1/inspections/{inspection_id}/line-items/{line_item_id}/approve",
            {}, headers)

    def reject_line_item(self, inspection_id, line_item_id, headers):
        return self._request(
            "POST",
            f"/v1/inspections/{inspection_id}/line-items/{line_item_id}/reject",
            {}, headers)

    def complete_inspection(self, inspection_id, headers):
        return self._request("POST", f"/v1/inspections/{inspection_id}/complete",
                             {}, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/v1/inspections/{inspection_id}/cancel",
                             {}, headers)

    # --- TransferRequest ---
    def create_transfer_request(self, payload, headers):
        return self._request("POST", "/v1/transfer-requests", payload, headers)

    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", "/v1/transfer-requests",
                             headers=headers, params=params)

    def get_transfer_request(self, transfer_id, headers):
        return self._request("GET", f"/v1/transfer-requests/{transfer_id}",
                             headers=headers)

    def pay_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/v1/transfer-requests/{transfer_id}/pay",
                             {}, headers)

    def ship_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/v1/transfer-requests/{transfer_id}/ship",
                             {}, headers)

    def deliver_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/v1/transfer-requests/{transfer_id}/deliver",
                             {}, headers)

    def cancel_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/v1/transfer-requests/{transfer_id}/cancel",
                             {}, headers)

    # --- Sale ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/v1/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/v1/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/v1/sales/{sale_id}", headers=headers)

    def complete_sale(self, sale_id, headers):
        return self._request("POST", f"/v1/sales/{sale_id}/complete", {}, headers)

    def cancel_sale(self, sale_id, headers):
        return self._request("POST", f"/v1/sales/{sale_id}/cancel", {}, headers)

    # --- Financing ---
    def submit_financing_application(self, sale_id, headers):
        return self._request("POST", f"/v1/sales/{sale_id}/financing-applications",
                             {}, headers)

    def list_sale_financing_applications(self, sale_id, headers, params=None):
        return self._request("GET", f"/v1/sales/{sale_id}/financing-applications",
                             headers=headers, params=params)

    def list_financing_applications(self, headers, params=None):
        return self._request("GET", "/v1/financing-applications",
                             headers=headers, params=params)

    def get_financing_application(self, application_id, headers):
        return self._request("GET", f"/v1/financing-applications/{application_id}",
                             headers=headers)

    def list_financing_offers(self, application_id, headers, params=None):
        return self._request("GET",
                             f"/v1/financing-applications/{application_id}/offers",
                             headers=headers, params=params)

    def accept_financing(self, application_id, payload, headers):
        return self._request("POST",
                             f"/v1/financing-applications/{application_id}/accept",
                             payload, headers)

    def withdraw_financing(self, application_id, headers):
        return self._request("POST",
                             f"/v1/financing-applications/{application_id}/withdraw",
                             {}, headers)

    # --- ReturnRequest ---
    def create_return(self, payload, headers):
        return self._request("POST", "/v1/returns", payload, headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/v1/returns", headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/v1/returns/{return_id}", headers=headers)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/v1/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/v1/returns/{return_id}/reject", {}, headers)

    def settle_return(self, return_id, headers):
        return self._request("POST", f"/v1/returns/{return_id}/settle", {}, headers)

    # --- AuctionLot ---
    def create_auction_lot(self, payload, headers):
        return self._request("POST", "/v1/auction-lots", payload, headers)

    def list_auction_lots(self, headers, params=None):
        return self._request("GET", "/v1/auction-lots", headers=headers, params=params)

    def get_auction_lot(self, lot_id, headers):
        return self._request("GET", f"/v1/auction-lots/{lot_id}", headers=headers)

    def close_auction_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/v1/auction-lots/{lot_id}/close",
                             payload, headers)


api_client = ApiClient()
