"""API client: one method per endpoint defined in the PRD (§4 index)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Store ---
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def list_store_staff(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/staff", headers=headers, params=params)

    def list_store_stations(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/stations", headers=headers, params=params)

    def list_store_workshops(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/workshops", headers=headers, params=params)

    def list_store_parties(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/parties", headers=headers, params=params)

    def list_store_appointment_blocks(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/appointment-blocks", headers=headers, params=params)

    def list_store_consumables(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/consumables", headers=headers, params=params)

    def list_store_build_ship_orders(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/build-ship-orders", headers=headers, params=params)

    def run_consignment_settlement(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/consignments/run", payload, headers)

    # --- StaffMember ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    def list_staff_appointment_blocks(self, staff_id, headers, params=None):
        return self._request("GET", f"/staff/{staff_id}/appointment-blocks", headers=headers, params=params)

    # --- Station ---
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_station_workshops(self, station_id, headers, params=None):
        return self._request("GET", f"/stations/{station_id}/workshops", headers=headers, params=params)

    # --- PlushModel ---
    def create_plush_model(self, payload, headers):
        return self._request("POST", "/plush-models", payload, headers)

    def get_plush_model(self, model_id, headers):
        return self._request("GET", f"/plush-models/{model_id}", headers=headers)

    def list_plush_model_workshops(self, model_id, headers, params=None):
        return self._request("GET", f"/plush-models/{model_id}/workshops", headers=headers, params=params)

    def list_plush_model_collection_drops(self, model_id, headers, params=None):
        return self._request("GET", f"/plush-models/{model_id}/collection-drops", headers=headers, params=params)

    def list_plush_model_build_ship_orders(self, model_id, headers, params=None):
        return self._request("GET", f"/plush-models/{model_id}/build-ship-orders", headers=headers, params=params)

    def list_plush_model_animals(self, model_id, headers, params=None):
        return self._request("GET", f"/plush-models/{model_id}/animals", headers=headers, params=params)

    # --- Consumable ---
    def create_consumable(self, payload, headers):
        return self._request("POST", "/consumables", payload, headers)

    def get_consumable(self, consumable_id, headers):
        return self._request("GET", f"/consumables/{consumable_id}", headers=headers)

    def restock_consumable(self, consumable_id, payload, headers):
        return self._request("POST", f"/consumables/{consumable_id}/restock", payload, headers)

    # --- CollectionDrop ---
    def create_collection_drop(self, payload, headers):
        return self._request("POST", "/collection-drops", payload, headers)

    def get_collection_drop(self, drop_id, headers):
        return self._request("GET", f"/collection-drops/{drop_id}", headers=headers)

    def list_collection_drop_workshops(self, drop_id, headers, params=None):
        return self._request("GET", f"/collection-drops/{drop_id}/workshops", headers=headers, params=params)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_workshops(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/workshops", headers=headers, params=params)

    def list_customer_animals(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/animals", headers=headers, params=params)

    def list_customer_registries(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/registries", headers=headers, params=params)

    def list_customer_parties(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/parties", headers=headers, params=params)

    def list_customer_build_ship_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/build-ship-orders", headers=headers, params=params)

    # --- WorkshopSession ---
    def create_workshop(self, payload, headers):
        return self._request("POST", "/workshops", payload, headers)

    def get_workshop(self, session_id, headers):
        return self._request("GET", f"/workshops/{session_id}", headers=headers)

    def advance_workshop(self, session_id, headers):
        return self._request("POST", f"/workshops/{session_id}/advance-step", {}, headers)

    def abandon_workshop(self, session_id, headers):
        return self._request("POST", f"/workshops/{session_id}/abandon", {}, headers)

    def pay_workshop(self, session_id, payload, headers):
        return self._request("POST", f"/workshops/{session_id}/payment", payload, headers)

    def list_workshop_animals(self, session_id, headers, params=None):
        return self._request("GET", f"/workshops/{session_id}/animals", headers=headers, params=params)

    def list_workshop_party_guests(self, session_id, headers, params=None):
        return self._request("GET", f"/workshops/{session_id}/party-guests", headers=headers, params=params)

    def list_workshop_build_ship_orders(self, session_id, headers, params=None):
        return self._request("GET", f"/workshops/{session_id}/build-ship-orders", headers=headers, params=params)

    # --- StuffedAnimal ---
    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/animals/{animal_id}", headers=headers)

    def list_animal_workshops(self, animal_id, headers, params=None):
        return self._request("GET", f"/animals/{animal_id}/workshops", headers=headers, params=params)

    def personalize_birth_certificate(self, animal_id, payload, headers):
        return self._request("POST", f"/animals/{animal_id}/birth-certificate", payload, headers)

    def report_animal_lost(self, animal_id, headers):
        return self._request("POST", f"/animals/{animal_id}/report-lost", {}, headers)

    def mark_animal_recovered(self, animal_id, headers):
        return self._request("POST", f"/animals/{animal_id}/mark-recovered", {}, headers)

    def mark_animal_found_cancel(self, animal_id, headers):
        return self._request("POST", f"/animals/{animal_id}/mark-found-cancel", {}, headers)

    # --- PartyReservation ---
    def create_party(self, payload, headers):
        return self._request("POST", "/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/parties/{party_id}", headers=headers)

    def pay_party_deposit(self, party_id, payload, headers):
        return self._request("POST", f"/parties/{party_id}/pay-deposit", payload, headers)

    def pay_party_balance(self, party_id, payload, headers):
        return self._request("POST", f"/parties/{party_id}/pay-balance", payload, headers)

    def finalize_party(self, party_id, headers):
        return self._request("POST", f"/parties/{party_id}/finalize", {}, headers)

    def cancel_party(self, party_id, headers):
        return self._request("POST", f"/parties/{party_id}/cancel", {}, headers)

    def reschedule_party(self, party_id, payload, headers):
        return self._request("POST", f"/parties/{party_id}/reschedule", payload, headers)

    def list_party_guests(self, party_id, headers, params=None):
        return self._request("GET", f"/parties/{party_id}/guests", headers=headers, params=params)

    def list_party_workshops(self, party_id, headers, params=None):
        return self._request("GET", f"/parties/{party_id}/workshops", headers=headers, params=params)

    def list_party_appointment_blocks(self, party_id, headers, params=None):
        return self._request("GET", f"/parties/{party_id}/appointment-blocks", headers=headers, params=params)

    # --- PartyGuest ---
    def create_party_guest(self, payload, headers):
        return self._request("POST", "/party-guests", payload, headers)

    def get_party_guest(self, guest_id, headers):
        return self._request("GET", f"/party-guests/{guest_id}", headers=headers)

    def confirm_party_guest(self, guest_id, headers):
        return self._request("POST", f"/party-guests/{guest_id}/confirm", {}, headers)

    def cancel_party_guest(self, guest_id, headers):
        return self._request("POST", f"/party-guests/{guest_id}/cancel", {}, headers)

    # --- BuildShipOrder ---
    def create_build_ship_order(self, payload, headers):
        return self._request("POST", "/build-ship-orders", payload, headers)

    def get_build_ship_order(self, order_id, headers):
        return self._request("GET", f"/build-ship-orders/{order_id}", headers=headers)

    def list_build_ship_order_workshops(self, order_id, headers, params=None):
        return self._request("GET", f"/build-ship-orders/{order_id}/workshops", headers=headers, params=params)

    def start_build_ship_assembly(self, order_id, headers):
        return self._request("POST", f"/build-ship-orders/{order_id}/start-assembly", {}, headers)

    def handoff_build_ship_order(self, order_id, payload, headers):
        return self._request("POST", f"/build-ship-orders/{order_id}/handoff", payload, headers)

    def cancel_build_ship_order(self, order_id, headers):
        return self._request("POST", f"/build-ship-orders/{order_id}/cancel", {}, headers)

    # --- GiftCard ---
    def create_gift_card(self, payload, headers):
        return self._request("POST", "/gift-cards", payload, headers)

    def get_gift_card(self, card_id, headers):
        return self._request("GET", f"/gift-cards/{card_id}", headers=headers)

    def disable_gift_card(self, card_id, headers):
        return self._request("POST", f"/gift-cards/{card_id}/disable", {}, headers)

    # --- Registry ---
    def create_registry(self, payload, headers):
        return self._request("POST", "/registries", payload, headers)

    def get_registry(self, registry_id, headers):
        return self._request("GET", f"/registries/{registry_id}", headers=headers)

    def link_registry_animal(self, registry_id, payload, headers):
        return self._request("POST", f"/registries/{registry_id}/link-animal", payload, headers)

    def link_registry_gift_card(self, registry_id, payload, headers):
        return self._request("POST", f"/registries/{registry_id}/link-gift-card", payload, headers)


api_client = ApiClient()
