"""API client: one method per endpoint defined in the PRD (§4 locator table).

The logical-clock endpoint is mounted OUTSIDE the /fmc business surface
(PRD §2.4), so it is addressed by its absolute path.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (platform-level, outside /fmc) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- CarrierOrganization ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/fmc/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/fmc/carriers/{carrier_id}", headers=headers)

    # --- ShipperAccount ---
    def create_shipper(self, payload, headers):
        return self._request("POST", "/fmc/shippers", payload, headers)

    def get_shipper(self, shipper_id, headers):
        return self._request("GET", f"/fmc/shippers/{shipper_id}", headers=headers)

    # --- TariffPublication ---
    def create_tariff(self, carrier_id, payload, headers):
        return self._request("POST", f"/fmc/carriers/{carrier_id}/tariff-publications",
                             payload, headers)

    def list_tariffs(self, carrier_id, headers, params=None):
        return self._request("GET", f"/fmc/carriers/{carrier_id}/tariff-publications",
                             headers=headers, params=params)

    def publish_tariff(self, tariff_id, headers):
        return self._request("POST", f"/fmc/tariff-publications/{tariff_id}/publish",
                             {}, headers)

    # --- ServiceContract ---
    def create_service_contract(self, carrier_id, payload, headers):
        return self._request("POST", f"/fmc/carriers/{carrier_id}/service-contracts",
                             payload, headers)

    def list_service_contracts(self, headers, params=None):
        return self._request("GET", "/fmc/service-contracts", headers=headers, params=params)

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"/fmc/service-contracts/{contract_id}", headers=headers)

    # --- CarrierAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/fmc/carrier-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/fmc/carrier-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/fmc/carrier-agreements/{agreement_id}", headers=headers)

    def go_effective(self, agreement_id, headers):
        return self._request("POST", f"/fmc/carrier-agreements/{agreement_id}/go-effective",
                             {}, headers)

    def append_monitoring_report(self, agreement_id, payload, headers):
        return self._request("POST",
                             f"/fmc/carrier-agreements/{agreement_id}/monitoring-reports",
                             payload, headers)

    # --- OTILicense / surety bonds ---
    def create_oti_license(self, carrier_id, payload, headers):
        return self._request("POST", f"/fmc/carriers/{carrier_id}/oti-licenses",
                             payload, headers)

    def list_oti_licenses(self, carrier_id, headers, params=None):
        return self._request("GET", f"/fmc/carriers/{carrier_id}/oti-licenses",
                             headers=headers, params=params)

    def append_surety_bond(self, license_id, payload, headers):
        return self._request("POST", f"/fmc/oti-licenses/{license_id}/surety-bonds",
                             payload, headers)

    def post_bond_draw(self, license_id, payload, headers):
        return self._request("POST", f"/fmc/oti-licenses/{license_id}/draws",
                             payload, headers)

    # --- DemurrageDetentionInvoice ---
    def create_invoice(self, carrier_id, payload, headers):
        return self._request("POST", f"/fmc/carriers/{carrier_id}/invoices",
                             payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/fmc/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/fmc/invoices/{invoice_id}", headers=headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/fmc/invoices/{invoice_id}/mark-paid", {}, headers)

    # --- InvoiceDispute ---
    def create_dispute(self, invoice_id, payload, headers):
        return self._request("POST", f"/fmc/invoices/{invoice_id}/disputes",
                             payload, headers)

    def list_disputes(self, invoice_id, headers, params=None):
        return self._request("GET", f"/fmc/invoices/{invoice_id}/disputes",
                             headers=headers, params=params)

    def respond_to_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/fmc/invoice-disputes/{dispute_id}/respond",
                             payload, headers)

    # --- Complaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/fmc/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/fmc/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/fmc/complaints/{complaint_id}", headers=headers)

    def refer_ombuds(self, complaint_id, payload, headers):
        return self._request("POST", f"/fmc/complaints/{complaint_id}/refer-ombuds",
                             payload, headers)

    def close_ombuds(self, complaint_id, payload, headers):
        return self._request("POST", f"/fmc/complaints/{complaint_id}/close-ombuds",
                             payload, headers)

    def open_adjudication(self, complaint_id, headers):
        return self._request("POST", f"/fmc/complaints/{complaint_id}/open-adjudication",
                             {}, headers)

    def decide_complaint(self, complaint_id, headers):
        return self._request("POST", f"/fmc/complaints/{complaint_id}/decide", {}, headers)

    def appeal_complaint(self, complaint_id, headers):
        return self._request("POST", f"/fmc/complaints/{complaint_id}/appeal", {}, headers)

    def resolve_appeal(self, complaint_id, payload, headers):
        return self._request("POST", f"/fmc/complaints/{complaint_id}/resolve-appeal",
                             payload, headers)

    # --- EnforcementProceeding ---
    def create_proceeding(self, payload, headers):
        return self._request("POST", "/fmc/enforcement-proceedings", payload, headers)

    def list_proceedings(self, carrier_id, headers, params=None):
        return self._request("GET", f"/fmc/carriers/{carrier_id}/enforcement-proceedings",
                             headers=headers, params=params)

    def get_proceeding(self, proceeding_id, headers):
        return self._request("GET", f"/fmc/enforcement-proceedings/{proceeding_id}",
                             headers=headers)

    def determine_proceeding(self, proceeding_id, payload, headers):
        return self._request("POST",
                             f"/fmc/enforcement-proceedings/{proceeding_id}/determine",
                             payload, headers)

    # --- PortCongestionReport ---
    def create_congestion_report(self, payload, headers):
        return self._request("POST", "/fmc/port-congestion-reports", payload, headers)


api_client = ApiClient()
