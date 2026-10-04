"""API client: one method per endpoint defined in the PRD.

All routes are mounted beneath the /membership prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/membership"


class ApiClient(GenericApiClient):

    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------ eligibility cases
    def create_eligibility_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/eligibility-cases", payload, headers)

    def list_eligibility_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/eligibility-cases", headers=headers, params=params
        )

    def get_eligibility_case(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/eligibility-cases/{case_id}", headers=headers
        )

    def create_service_record(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/service-records",
            payload, headers,
        )

    def list_case_service_records(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/eligibility-cases/{case_id}/service-records",
            headers=headers,
        )

    def upload_evidence(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/evidence", payload, headers
        )

    def list_case_evidence(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/eligibility-cases/{case_id}/evidence", headers=headers
        )

    def submit_case(self, case_id, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/submit", {}, headers
        )

    def decide_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/decide", payload, headers
        )

    def record_reconstruction(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-cases/{case_id}/record-reconstruction",
            payload, headers,
        )

    # ------------------------------------------------- flat record listings
    def list_service_records(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-records", headers=headers, params=params
        )

    def get_service_record(self, record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/service-records/{record_id}", headers=headers
        )

    def list_evidence(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/evidence", headers=headers, params=params
        )

    def get_evidence(self, doc_id, headers):
        return self._request(
            "GET", f"{PREFIX}/evidence/{doc_id}", headers=headers
        )

    # ------------------------------------------------------------- members
    def list_members(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    def get_product_matrix(self, member_id, headers):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/product-matrix", headers=headers
        )

    def record_eligibility_loss(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/eligibility-loss", payload, headers
        )

    def reinstate_member(self, member_id, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/reinstate", {}, headers
        )

    def mark_deceased(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/deceased", payload, headers
        )

    def link_household(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/link-household", payload, headers
        )

    def delink_household(self, member_id, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/delink-household", {}, headers
        )

    # ------------------------------------------------------------ addresses
    def create_address(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/addresses", payload, headers
        )

    def list_member_addresses(self, member_id, headers):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/addresses", headers=headers
        )

    def list_addresses(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/addresses", headers=headers, params=params
        )

    def get_address(self, address_id, headers):
        return self._request(
            "GET", f"{PREFIX}/addresses/{address_id}", headers=headers
        )

    def patch_address(self, address_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/addresses/{address_id}", payload, headers
        )

    # ------------------------------------------------------ deployment orders
    def create_deployment_order(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/deployment-orders",
            payload, headers,
        )

    def list_member_deployment_orders(self, member_id, headers):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/deployment-orders", headers=headers
        )

    def patch_deployment_order(self, order_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/deployment-orders/{order_id}", payload, headers
        )

    def list_deployment_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/deployment-orders", headers=headers, params=params
        )

    def get_deployment_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/deployment-orders/{order_id}", headers=headers
        )

    def complete_deployment_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/deployment-orders/{order_id}/complete", {}, headers
        )

    def cancel_deployment_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/deployment-orders/{order_id}/cancel", {}, headers
        )

    # ------------------------------------------------------ protection claims
    def create_protection_claim(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/protection-claims",
            payload, headers,
        )

    def list_member_protection_claims(self, member_id, headers):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/protection-claims", headers=headers
        )

    def list_protection_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/protection-claims", headers=headers, params=params
        )

    def get_protection_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/protection-claims/{claim_id}", headers=headers
        )

    def decide_protection_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protection-claims/{claim_id}/decide", payload, headers
        )

    # ----------------------------------------------- product offerings
    def create_product_offering(self, payload, headers):
        return self._request("POST", f"{PREFIX}/product-offerings", payload, headers)

    def list_product_offerings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/product-offerings", headers=headers, params=params
        )

    def get_product_offering(self, offering_id, headers):
        return self._request(
            "GET", f"{PREFIX}/product-offerings/{offering_id}", headers=headers
        )

    def patch_product_offering(self, offering_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/product-offerings/{offering_id}", payload, headers
        )

    # ----------------------------------------------------------- entitlements
    def create_entitlement(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/entitlements", payload, headers
        )

    def list_member_entitlements(self, member_id, headers):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/entitlements", headers=headers
        )

    def list_entitlements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/entitlements", headers=headers, params=params
        )

    def get_entitlement(self, entitlement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/entitlements/{entitlement_id}", headers=headers
        )

    def close_entitlement(self, member_id, entitlement_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/members/{member_id}/entitlements/{entitlement_id}/close",
            {}, headers,
        )

    # ------------------------------------------------------------- households
    def create_household(self, payload, headers):
        return self._request("POST", f"{PREFIX}/households", payload, headers)

    def list_households(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/households", headers=headers, params=params
        )

    def get_household(self, household_id, headers):
        return self._request(
            "GET", f"{PREFIX}/households/{household_id}", headers=headers
        )

    def dissolve_household(self, household_id, headers):
        return self._request(
            "POST", f"{PREFIX}/households/{household_id}/dissolve", {}, headers
        )

    # --------------------------------------------------------- survivor cases
    def list_member_survivor_cases(self, member_id, headers):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/survivor-cases", headers=headers
        )

    def list_survivor_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/survivor-cases", headers=headers, params=params
        )

    def get_survivor_case(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/survivor-cases/{case_id}", headers=headers
        )

    def grant_survivor_case(self, case_id, headers):
        return self._request(
            "POST", f"{PREFIX}/survivor-cases/{case_id}/grant", {}, headers
        )

    def close_survivor_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/survivor-cases/{case_id}/close", payload, headers
        )


api_client = ApiClient()
