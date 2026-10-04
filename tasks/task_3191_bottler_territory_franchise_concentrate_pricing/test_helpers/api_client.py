"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/bottler/_clock/set_current_utc", payload, headers)

    # --- BrandOwner ---
    def create_brand_owner(self, payload, headers):
        return self._request("POST", "/bottler/brand-owners", payload, headers)

    def get_brand_owner(self, brand_owner_id, headers):
        return self._request("GET", f"/bottler/brand-owners/{brand_owner_id}", headers=headers)

    def list_brand_owners(self, headers, params=None):
        return self._request("GET", "/bottler/brand-owners", headers=headers, params=params)

    # --- Territory ---
    def create_territory(self, payload, headers):
        return self._request("POST", "/bottler/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request("GET", f"/bottler/territories/{territory_id}", headers=headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", "/bottler/territories", headers=headers, params=params)

    # --- BottlerAgreement ---
    def create_agreement(self, territory_id, payload, headers):
        return self._request("POST", f"/bottler/territories/{territory_id}/agreements", payload, headers)

    def list_territory_agreements(self, territory_id, headers, params=None):
        return self._request("GET", f"/bottler/territories/{territory_id}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/bottler/bottler-agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/bottler/bottler-agreements/{agreement_id}/activate", {}, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/bottler/bottler-agreements/{agreement_id}/suspend", {}, headers)

    def reinstate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/bottler/bottler-agreements/{agreement_id}/reinstate", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/bottler/bottler-agreements/{agreement_id}/terminate", {}, headers)

    # --- ProductLine ---
    def create_product_line(self, payload, headers):
        return self._request("POST", "/bottler/product-lines", payload, headers)

    def get_product_line(self, product_line_id, headers):
        return self._request("GET", f"/bottler/product-lines/{product_line_id}", headers=headers)

    def list_product_lines(self, headers, params=None):
        return self._request("GET", "/bottler/product-lines", headers=headers, params=params)

    def retire_product_line(self, product_line_id, headers):
        return self._request("POST", f"/bottler/product-lines/{product_line_id}/retire", {}, headers)

    # --- ConcentratePriceIndex ---
    def create_price_index(self, payload, headers):
        return self._request("POST", "/bottler/concentrate-price-indices", payload, headers)

    def get_price_index(self, index_id, headers):
        return self._request("GET", f"/bottler/concentrate-price-indices/{index_id}", headers=headers)

    def list_price_indices(self, headers, params=None):
        return self._request("GET", "/bottler/concentrate-price-indices", headers=headers, params=params)

    # --- ConcentratePurchaseOrder ---
    def create_cpo(self, payload, headers):
        return self._request("POST", "/bottler/concentrate-purchase-orders", payload, headers)

    def get_cpo(self, cpo_id, headers):
        return self._request("GET", f"/bottler/concentrate-purchase-orders/{cpo_id}", headers=headers)

    def list_cpos(self, headers, params=None):
        return self._request("GET", "/bottler/concentrate-purchase-orders", headers=headers, params=params)

    def receive_cpo(self, cpo_id, headers):
        return self._request("POST", f"/bottler/concentrate-purchase-orders/{cpo_id}/receive", {}, headers)

    def finalize_cpo(self, cpo_id, headers):
        return self._request("POST", f"/bottler/concentrate-purchase-orders/{cpo_id}/finalize", {}, headers)

    def cancel_cpo(self, cpo_id, headers):
        return self._request("POST", f"/bottler/concentrate-purchase-orders/{cpo_id}/cancel", {}, headers)

    # --- NationalCustomerAgreement ---
    def create_nca(self, payload, headers):
        return self._request("POST", "/bottler/national-customer-agreements", payload, headers)

    def get_nca(self, nca_id, headers):
        return self._request("GET", f"/bottler/national-customer-agreements/{nca_id}", headers=headers)

    def list_ncas(self, headers, params=None):
        return self._request("GET", "/bottler/national-customer-agreements", headers=headers, params=params)

    def publish_nca(self, nca_id, headers):
        return self._request("POST", f"/bottler/national-customer-agreements/{nca_id}/publish", {}, headers)

    def suspend_nca(self, nca_id, headers):
        return self._request("POST", f"/bottler/national-customer-agreements/{nca_id}/suspend", {}, headers)

    def expire_nca(self, nca_id, headers):
        return self._request("POST", f"/bottler/national-customer-agreements/{nca_id}/expire", {}, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/bottler/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/bottler/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/bottler/customers", headers=headers, params=params)

    def enroll_nca(self, customer_id, payload, headers):
        return self._request("POST", f"/bottler/customers/{customer_id}/enroll-nca", payload, headers)

    def dispute_customer(self, customer_id, headers):
        return self._request("POST", f"/bottler/customers/{customer_id}/dispute", {}, headers)

    def resolve_dispute(self, customer_id, headers):
        return self._request("POST", f"/bottler/customers/{customer_id}/resolve-dispute", {}, headers)

    # --- DsdOrder ---
    def create_dsd_order(self, payload, headers):
        return self._request("POST", "/bottler/dsd-orders", payload, headers)

    def get_dsd_order(self, order_id, headers):
        return self._request("GET", f"/bottler/dsd-orders/{order_id}", headers=headers)

    def list_dsd_orders(self, headers, params=None):
        return self._request("GET", "/bottler/dsd-orders", headers=headers, params=params)

    def deliver_dsd_order(self, order_id, headers):
        return self._request("POST", f"/bottler/dsd-orders/{order_id}/deliver", {}, headers)

    def pay_dsd_order(self, order_id, headers):
        return self._request("POST", f"/bottler/dsd-orders/{order_id}/pay", {}, headers)

    def void_dsd_order(self, order_id, headers):
        return self._request("POST", f"/bottler/dsd-orders/{order_id}/void", {}, headers)

    # --- ColdDrinkEquipment + ServiceWindow ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/bottler/cold-drink-equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/bottler/cold-drink-equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/bottler/cold-drink-equipment", headers=headers, params=params)

    def place_equipment(self, equipment_id, payload, headers):
        return self._request("POST", f"/bottler/cold-drink-equipment/{equipment_id}/place", payload, headers)

    def uninstall_equipment(self, equipment_id, headers):
        return self._request("POST", f"/bottler/cold-drink-equipment/{equipment_id}/uninstall", {}, headers)

    def create_service_window(self, equipment_id, payload, headers):
        return self._request("POST", f"/bottler/cold-drink-equipment/{equipment_id}/service-windows", payload, headers)

    def list_service_windows(self, equipment_id, headers, params=None):
        return self._request("GET", f"/bottler/cold-drink-equipment/{equipment_id}/service-windows", headers=headers, params=params)

    # --- FountainAccount + SyrupDelivery ---
    def create_fountain_account(self, payload, headers):
        return self._request("POST", "/bottler/fountain-accounts", payload, headers)

    def get_fountain_account(self, account_id, headers):
        return self._request("GET", f"/bottler/fountain-accounts/{account_id}", headers=headers)

    def list_fountain_accounts(self, headers, params=None):
        return self._request("GET", "/bottler/fountain-accounts", headers=headers, params=params)

    def create_syrup_delivery(self, account_id, payload, headers):
        return self._request("POST", f"/bottler/fountain-accounts/{account_id}/syrup-deliveries", payload, headers)

    def list_syrup_deliveries(self, account_id, headers, params=None):
        return self._request("GET", f"/bottler/fountain-accounts/{account_id}/syrup-deliveries", headers=headers, params=params)

    def record_maintenance(self, account_id, headers):
        return self._request("POST", f"/bottler/fountain-accounts/{account_id}/maintenance", {}, headers)

    # --- TerritoryTransfer ---
    def create_territory_transfer(self, payload, headers):
        return self._request("POST", "/bottler/territory-transfers", payload, headers)

    def get_territory_transfer(self, transfer_id, headers):
        return self._request("GET", f"/bottler/territory-transfers/{transfer_id}", headers=headers)

    def list_territory_transfers(self, headers, params=None):
        return self._request("GET", "/bottler/territory-transfers", headers=headers, params=params)

    def valuate_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/bottler/territory-transfers/{transfer_id}/valuate", payload, headers)

    def counter_transfer(self, transfer_id, headers):
        return self._request("POST", f"/bottler/territory-transfers/{transfer_id}/counter", {}, headers)

    def approve_transfer(self, transfer_id, headers):
        return self._request("POST", f"/bottler/territory-transfers/{transfer_id}/approve", {}, headers)

    def execute_transfer(self, transfer_id, headers):
        return self._request("POST", f"/bottler/territory-transfers/{transfer_id}/execute", {}, headers)

    def reject_transfer(self, transfer_id, headers):
        return self._request("POST", f"/bottler/territory-transfers/{transfer_id}/reject", {}, headers)

    # --- InnovationLaunch ---
    def create_innovation_launch(self, payload, headers):
        return self._request("POST", "/bottler/innovation-launches", payload, headers)

    def get_innovation_launch(self, launch_id, headers):
        return self._request("GET", f"/bottler/innovation-launches/{launch_id}", headers=headers)

    def list_innovation_launches(self, headers, params=None):
        return self._request("GET", "/bottler/innovation-launches", headers=headers, params=params)

    def schedule_changeover(self, launch_id, headers):
        return self._request("POST", f"/bottler/innovation-launches/{launch_id}/schedule-changeover", {}, headers)

    def complete_changeover(self, launch_id, headers):
        return self._request("POST", f"/bottler/innovation-launches/{launch_id}/complete-changeover", {}, headers)

    def record_sales(self, launch_id, payload, headers):
        return self._request("POST", f"/bottler/innovation-launches/{launch_id}/record-sales", payload, headers)

    def review_commitment(self, launch_id, headers):
        return self._request("POST", f"/bottler/innovation-launches/{launch_id}/review-commitment", {}, headers)

    # --- MarketingFundEntry ---
    def create_fund_entry(self, payload, headers):
        return self._request("POST", "/bottler/marketing-fund-ledger", payload, headers)

    def get_fund_entry(self, entry_id, headers):
        return self._request("GET", f"/bottler/marketing-fund-ledger/{entry_id}", headers=headers)

    def list_fund_entries(self, headers, params=None):
        return self._request("GET", "/bottler/marketing-fund-ledger", headers=headers, params=params)


api_client = ApiClient()
