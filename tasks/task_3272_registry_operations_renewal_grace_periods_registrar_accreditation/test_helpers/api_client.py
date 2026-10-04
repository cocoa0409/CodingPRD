"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/registry/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Registrar ---
    def create_registrar(self, payload, headers):
        return self._request("POST", "/registry/registrars", payload, headers)

    def list_registrars(self, headers, params=None):
        return self._request("GET", "/registry/registrars", headers=headers, params=params)

    def get_registrar(self, registrar_id, headers):
        return self._request(
            "GET", f"/registry/registrars/{registrar_id}", headers=headers)

    def patch_registrar(self, registrar_id, payload, headers):
        return self._request(
            "PATCH", f"/registry/registrars/{registrar_id}", payload, headers)

    def accredit_registrar(self, registrar_id, headers):
        return self._request(
            "POST", f"/registry/registrars/{registrar_id}/accredit", {}, headers)

    def suspend_registrar(self, registrar_id, headers):
        return self._request(
            "POST", f"/registry/registrars/{registrar_id}/suspend", {}, headers)

    def reinstate_registrar(self, registrar_id, headers):
        return self._request(
            "POST", f"/registry/registrars/{registrar_id}/reinstate", {}, headers)

    def terminate_registrar(self, registrar_id, headers):
        return self._request(
            "POST", f"/registry/registrars/{registrar_id}/terminate", {}, headers)

    def create_ledger_topup(self, registrar_id, amount_cents, headers):
        return self._request(
            "POST", f"/registry/registrars/{registrar_id}/ledger-topups",
            {"amount_cents": amount_cents}, headers,
        )

    def list_registrar_ledger(self, registrar_id, headers, params=None):
        return self._request(
            "GET", f"/registry/registrars/{registrar_id}/ledger",
            headers=headers, params=params,
        )

    def list_registrar_domains(self, registrar_id, headers, params=None):
        return self._request(
            "GET", f"/registry/registrars/{registrar_id}/domains",
            headers=headers, params=params,
        )

    def list_registrar_accreditation_notices(self, registrar_id, headers):
        return self._request(
            "GET",
            f"/registry/registrars/{registrar_id}/accreditation-notices",
            headers=headers,
        )

    def list_accreditation_notices(self, headers, params=None):
        return self._request(
            "GET", "/registry/accreditation-notices", headers=headers, params=params)

    def get_accreditation_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/registry/accreditation-notices/{notice_id}", headers=headers)

    # --- PriceSchedule ---
    def create_price_schedule(self, payload, headers):
        return self._request("POST", "/registry/price-schedules", payload, headers)

    def list_price_schedules(self, headers, params=None):
        return self._request(
            "GET", "/registry/price-schedules", headers=headers, params=params)

    def get_price_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/registry/price-schedules/{schedule_id}", headers=headers)

    # --- Domain ---
    def create_domain(self, payload, headers):
        return self._request("POST", "/registry/domains", payload, headers)

    def list_domains(self, headers, params=None):
        return self._request("GET", "/registry/domains", headers=headers, params=params)

    def get_domain(self, domain_id, headers):
        return self._request("GET", f"/registry/domains/{domain_id}", headers=headers)

    def renew_domain(self, domain_id, years, headers):
        return self._request(
            "POST", f"/registry/domains/{domain_id}/renew", {"years": years}, headers)

    def delete_domain(self, domain_id, headers):
        return self._request(
            "POST", f"/registry/domains/{domain_id}/delete", {}, headers)

    def restore_domain(self, domain_id, headers):
        return self._request(
            "POST", f"/registry/domains/{domain_id}/restore", {}, headers)

    def lock_domain(self, domain_id, payload, headers):
        return self._request(
            "POST", f"/registry/domains/{domain_id}/lock", payload, headers)

    def link_nameserver(self, domain_id, nameserver_id, headers):
        return self._request(
            "POST", f"/registry/domains/{domain_id}/nameservers",
            {"nameserver_id": nameserver_id}, headers,
        )

    def list_domain_nameservers(self, domain_id, headers):
        return self._request(
            "GET", f"/registry/domains/{domain_id}/nameservers", headers=headers)

    # --- Nameserver ---
    def create_nameserver(self, payload, headers):
        return self._request("POST", "/registry/nameservers", payload, headers)

    def list_nameservers(self, headers, params=None):
        return self._request("GET", "/registry/nameservers", headers=headers, params=params)

    def get_nameserver(self, nameserver_id, headers):
        return self._request(
            "GET", f"/registry/nameservers/{nameserver_id}", headers=headers)

    def delete_nameserver(self, nameserver_id, headers):
        return self._request(
            "DELETE", f"/registry/nameservers/{nameserver_id}", headers=headers)

    def list_domain_nameserver_links(self, headers, params=None):
        return self._request(
            "GET", "/registry/domain-nameserver-links", headers=headers, params=params)

    def get_domain_nameserver_link(self, link_id, headers):
        return self._request(
            "GET", f"/registry/domain-nameserver-links/{link_id}", headers=headers)

    # --- Transfer ---
    def create_transfer(self, payload, headers):
        return self._request("POST", "/registry/transfers", payload, headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/registry/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/registry/transfers/{transfer_id}", headers=headers)

    def ack_transfer(self, transfer_id, auth_code, headers):
        return self._request(
            "POST", f"/registry/transfers/{transfer_id}/ack",
            {"auth_code": auth_code}, headers,
        )

    def nack_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/registry/transfers/{transfer_id}/nack", {}, headers)

    def complete_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/registry/transfers/{transfer_id}/complete", {}, headers)

    def dispute_transfer(self, transfer_id, dispute_reason, headers):
        return self._request(
            "POST", f"/registry/transfers/{transfer_id}/dispute",
            {"dispute_reason": dispute_reason}, headers,
        )

    def reverse_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/registry/transfers/{transfer_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    # --- Invoices / Ledger ---
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/registry/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/registry/invoices/{invoice_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/registry/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/registry/ledger-entries/{entry_id}", headers=headers)

    # --- Abuse reports ---
    def create_abuse_report(self, payload, headers):
        return self._request("POST", "/registry/abuse-reports", payload, headers)

    def list_abuse_reports(self, headers, params=None):
        return self._request(
            "GET", "/registry/abuse-reports", headers=headers, params=params)

    def get_abuse_report(self, report_id, headers):
        return self._request(
            "GET", f"/registry/abuse-reports/{report_id}", headers=headers)

    def review_abuse_report(self, report_id, headers):
        return self._request(
            "POST", f"/registry/abuse-reports/{report_id}/review", {}, headers)

    def requeue_abuse_report(self, report_id, headers):
        return self._request(
            "POST", f"/registry/abuse-reports/{report_id}/requeue", {}, headers)

    def resolve_abuse_report(self, report_id, action, headers):
        return self._request(
            "POST", f"/registry/abuse-reports/{report_id}/resolve",
            {"action": action}, headers,
        )

    # --- Court orders ---
    def create_court_order(self, payload, headers):
        return self._request("POST", "/registry/court-orders", payload, headers)

    def list_court_orders(self, headers, params=None):
        return self._request(
            "GET", "/registry/court-orders", headers=headers, params=params)

    def get_court_order(self, order_id, headers):
        return self._request(
            "GET", f"/registry/court-orders/{order_id}", headers=headers)

    # --- Capacity ---
    def get_capacity_summary(self, headers):
        return self._request("GET", "/registry/capacity/summary", headers=headers)


api_client = ApiClient()
