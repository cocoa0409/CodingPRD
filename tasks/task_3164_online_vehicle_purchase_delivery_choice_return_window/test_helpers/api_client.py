"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/vehicle-hub/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/vehicle-hub/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/vehicle-hub/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/customers", headers=headers, params=params)

    # --- Reconditioning centers ---
    def create_center(self, payload, headers):
        return self._request("POST", "/vehicle-hub/reconditioning-centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/vehicle-hub/reconditioning-centers/{center_id}", headers=headers)

    def list_centers(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/reconditioning-centers", headers=headers, params=params)

    # --- Vehicles ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicle-hub/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicle-hub/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/vehicles", headers=headers, params=params)

    def start_recon(self, vehicle_id, headers):
        return self._request("POST", f"/vehicle-hub/vehicles/{vehicle_id}/start-recon", headers=headers)

    def list_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicle-hub/vehicles/{vehicle_id}/list", headers=headers)

    def remove_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicle-hub/vehicles/{vehicle_id}/remove", headers=headers)

    def create_annotation(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/vehicles/{vehicle_id}/annotations", payload, headers)

    def list_annotations(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/vehicles/{vehicle_id}/annotations", headers=headers, params=params)

    def retract_annotation(self, annotation_id, headers):
        return self._request("POST", f"/vehicle-hub/annotations/{annotation_id}/retract", headers=headers)

    # --- Financing ---
    def prequalify(self, payload, headers):
        return self._request("POST", "/vehicle-hub/financing/prequalify", payload, headers)

    def get_prequal(self, prequal_id, headers):
        return self._request("GET", f"/vehicle-hub/financing/{prequal_id}", headers=headers)

    def list_prequals(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/financing", headers=headers, params=params)

    # --- Trade-ins ---
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/vehicle-hub/trade-ins", payload, headers)

    def get_trade_in(self, offer_id, headers):
        return self._request("GET", f"/vehicle-hub/trade-ins/{offer_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/trade-ins", headers=headers, params=params)

    def inspect_trade_in(self, offer_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/trade-ins/{offer_id}/inspect", payload, headers)

    def confirm_trade_in(self, offer_id, headers):
        return self._request("POST", f"/vehicle-hub/trade-ins/{offer_id}/confirm", headers=headers)

    def decline_trade_in(self, offer_id, headers):
        return self._request("POST", f"/vehicle-hub/trade-ins/{offer_id}/decline", headers=headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/vehicle-hub/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/vehicle-hub/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/orders", headers=headers, params=params)

    def switch_fulfillment(self, order_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/orders/{order_id}/fulfillment-choice", payload, headers)

    def reserve_order(self, order_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/orders/{order_id}/reserve", payload, headers)

    def structure_order(self, order_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/orders/{order_id}/structure", payload, headers)

    def book_appointment(self, order_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/orders/{order_id}/appointments", payload, headers)

    def complete_order(self, order_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/orders/{order_id}/complete", payload, headers)

    def return_order(self, order_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/orders/{order_id}/return", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/vehicle-hub/orders/{order_id}/cancel", headers=headers)

    # --- Appointments ---
    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/vehicle-hub/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/appointments", headers=headers, params=params)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/vehicle-hub/appointments/{appointment_id}/cancel", headers=headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/vehicle-hub/appointments/{appointment_id}/no-show", headers=headers)

    # --- Returns ---
    def schedule_pickup(self, order_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/returns/{order_id}/schedule-pickup", payload, headers)

    def get_return_transit(self, order_id, headers):
        return self._request("GET", f"/vehicle-hub/orders/{order_id}/return-transit", headers=headers)

    def transit_pickup(self, order_id, headers):
        return self._request("POST", f"/vehicle-hub/returns/{order_id}/transit/pickup", headers=headers)

    def transit_arrive(self, order_id, headers):
        return self._request("POST", f"/vehicle-hub/returns/{order_id}/transit/arrive", headers=headers)

    def return_intake(self, order_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/returns/{order_id}/intake", payload, headers)

    # --- Title registrations ---
    def file_title_registration(self, reg_id, headers):
        return self._request("POST", f"/vehicle-hub/title-registrations/{reg_id}/file", headers=headers)

    def register_title_registration(self, reg_id, headers):
        return self._request("POST", f"/vehicle-hub/title-registrations/{reg_id}/register", headers=headers)

    def get_title_registration(self, reg_id, headers):
        return self._request("GET", f"/vehicle-hub/title-registrations/{reg_id}", headers=headers)

    def list_title_registrations(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/title-registrations", headers=headers, params=params)

    def get_order_title_registration(self, order_id, headers):
        return self._request("GET", f"/vehicle-hub/orders/{order_id}/title-registration", headers=headers)

    # --- Defect claims ---
    def create_defect_claim(self, payload, headers):
        return self._request("POST", "/vehicle-hub/defect-claims", payload, headers)

    def get_defect_claim(self, claim_id, headers):
        return self._request("GET", f"/vehicle-hub/defect-claims/{claim_id}", headers=headers)

    def list_defect_claims(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/defect-claims", headers=headers, params=params)

    def review_defect_claim(self, claim_id, headers):
        return self._request("POST", f"/vehicle-hub/defect-claims/{claim_id}/review", headers=headers)

    def authorize_defect_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/defect-claims/{claim_id}/authorize", payload, headers)

    def deny_defect_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/defect-claims/{claim_id}/deny", payload, headers)

    def complete_repair(self, claim_id, headers):
        return self._request("POST", f"/vehicle-hub/defect-claims/{claim_id}/complete-repair", headers=headers)

    def get_order_defect_claims(self, order_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/orders/{order_id}/defect-claims", headers=headers, params=params)

    def get_vehicle_defect_claims(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/vehicles/{vehicle_id}/defect-claims", headers=headers, params=params)

    # --- Repair authorizations ---
    def get_repair_authorization(self, auth_id, headers):
        return self._request("GET", f"/vehicle-hub/repair-authorizations/{auth_id}", headers=headers)

    def list_repair_authorizations(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/repair-authorizations", headers=headers, params=params)

    def void_repair_authorization(self, auth_id, payload, headers):
        return self._request("POST", f"/vehicle-hub/repair-authorizations/{auth_id}/void", payload, headers)

    def get_claim_repair_authorizations(self, claim_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/defect-claims/{claim_id}/repair-authorizations", headers=headers, params=params)

    # --- Recon intakes ---
    def create_recon_intake(self, payload, headers):
        return self._request("POST", "/vehicle-hub/recon-intakes", payload, headers)

    def get_recon_intake(self, intake_id, headers):
        return self._request("GET", f"/vehicle-hub/recon-intakes/{intake_id}", headers=headers)

    def list_recon_intakes(self, headers, params=None):
        return self._request("GET", "/vehicle-hub/recon-intakes", headers=headers, params=params)

    def arrive_recon_intake(self, intake_id, headers):
        return self._request("POST", f"/vehicle-hub/recon-intakes/{intake_id}/arrive", headers=headers)

    def start_work_recon_intake(self, intake_id, headers):
        return self._request("POST", f"/vehicle-hub/recon-intakes/{intake_id}/start-work", headers=headers)

    def complete_recon_intake(self, intake_id, headers):
        return self._request("POST", f"/vehicle-hub/recon-intakes/{intake_id}/complete", headers=headers)

    def cancel_recon_intake(self, intake_id, headers):
        return self._request("POST", f"/vehicle-hub/recon-intakes/{intake_id}/cancel", headers=headers)

    # --- Reverse reachability ---
    def get_customer_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/customers/{customer_id}/orders", headers=headers, params=params)

    def get_customer_financing(self, customer_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/customers/{customer_id}/financing", headers=headers, params=params)

    def get_customer_trade_ins(self, customer_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/customers/{customer_id}/trade-ins", headers=headers, params=params)

    def get_vehicle_recon_intakes(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/vehicles/{vehicle_id}/recon-intakes", headers=headers, params=params)

    def get_vehicle_return_transits(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/vehicles/{vehicle_id}/return-transits", headers=headers, params=params)

    def get_center_recon_intakes(self, center_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/reconditioning-centers/{center_id}/recon-intakes", headers=headers, params=params)

    def get_center_vehicles(self, center_id, headers, params=None):
        return self._request("GET", f"/vehicle-hub/reconditioning-centers/{center_id}/vehicles", headers=headers, params=params)


api_client = ApiClient()
