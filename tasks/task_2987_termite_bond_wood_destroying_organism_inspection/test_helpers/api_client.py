"""Typed HTTP client: one method per endpoint of PRD section 4."""

from prd_bench_local_runner.testing import GenericApiClient


def _query(params=None, **extra):
    """Merge explicit pagination/filter kwargs into a single query dict."""
    merged = {}
    if params:
        merged.update(params)
    for key, value in extra.items():
        if value is not None:
            merged[key] = value
    return merged or None


class ApiClient(GenericApiClient):
    """One method per endpoint in the PRD endpoint table."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers=None):
        return self._request("GET", "/_clock/current", None, headers)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    def create_property(self, payload, headers=None):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers=None):
        return self._request("GET", "/properties/%s" % property_id, None, headers)

    def list_properties(self, headers=None, params=None, **filters):
        return self._request("GET", "/properties", _query(params, **filters), headers)

    # ------------------------------------------------------------------
    # Inspectors
    # ------------------------------------------------------------------

    def create_inspector(self, payload, headers=None):
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers=None):
        return self._request("GET", "/inspectors/%s" % inspector_id, None, headers)

    def list_inspectors(self, headers=None, params=None, **filters):
        return self._request("GET", "/inspectors", _query(params, **filters), headers)

    def set_license_status(self, inspector_id, payload, headers=None):
        return self._request(
            "POST", "/inspectors/%s/license-status" % inspector_id, payload, headers
        )

    # ------------------------------------------------------------------
    # Inspections (graphs)
    # ------------------------------------------------------------------

    def create_inspection(self, payload, headers=None):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers=None):
        return self._request("GET", "/inspections/%s" % inspection_id, None, headers)

    def list_inspections(self, headers=None, params=None, **filters):
        return self._request("GET", "/inspections", _query(params, **filters), headers)

    def create_finding(self, inspection_id, payload, headers=None):
        return self._request(
            "POST", "/inspections/%s/findings" % inspection_id, payload, headers
        )

    def list_findings(self, inspection_id, headers=None, params=None, **filters):
        return self._request(
            "GET",
            "/inspections/%s/findings" % inspection_id,
            _query(params, **filters),
            headers,
        )

    def graph_complete(self, inspection_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/inspections/%s/graph-complete" % inspection_id,
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Treatment plans
    # ------------------------------------------------------------------

    def create_treatment_plan(self, payload, headers=None):
        return self._request("POST", "/treatment-plans", payload, headers)

    def get_treatment_plan(self, plan_id, headers=None):
        return self._request("GET", "/treatment-plans/%s" % plan_id, None, headers)

    def list_treatment_plans(self, headers=None, params=None, **filters):
        return self._request(
            "GET", "/treatment-plans", _query(params, **filters), headers
        )

    def approve_treatment_plan(self, plan_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/treatment-plans/%s/approve" % plan_id,
            payload if payload is not None else {},
            headers,
        )

    def abandon_treatment_plan(self, plan_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/treatment-plans/%s/abandon" % plan_id,
            payload if payload is not None else {},
            headers,
        )

    def create_application(self, plan_id, payload, headers=None):
        return self._request(
            "POST", "/treatment-plans/%s/applications" % plan_id, payload, headers
        )

    def list_applications(self, plan_id, headers=None, params=None, **filters):
        return self._request(
            "GET",
            "/treatment-plans/%s/applications" % plan_id,
            _query(params, **filters),
            headers,
        )

    def complete_treatment_plan(self, plan_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/treatment-plans/%s/complete" % plan_id,
            payload if payload is not None else {},
            headers,
        )

    def list_bait_stations(self, plan_id, headers=None, params=None, **filters):
        return self._request(
            "GET",
            "/treatment-plans/%s/bait-stations" % plan_id,
            _query(params, **filters),
            headers,
        )

    # ------------------------------------------------------------------
    # Bait stations
    # ------------------------------------------------------------------

    def get_bait_station(self, station_id, headers=None):
        return self._request("GET", "/bait-stations/%s" % station_id, None, headers)

    def create_station_service(self, station_id, payload, headers=None):
        return self._request(
            "POST", "/bait-stations/%s/services" % station_id, payload, headers
        )

    def list_station_services(self, station_id, headers=None, params=None, **filters):
        return self._request(
            "GET",
            "/bait-stations/%s/services" % station_id,
            _query(params, **filters),
            headers,
        )

    # ------------------------------------------------------------------
    # Bonds
    # ------------------------------------------------------------------

    def create_bond(self, payload, headers=None):
        return self._request("POST", "/bonds", payload, headers)

    def get_bond(self, bond_id, headers=None):
        return self._request("GET", "/bonds/%s" % bond_id, None, headers)

    def list_bonds(self, headers=None, params=None, **filters):
        return self._request("GET", "/bonds", _query(params, **filters), headers)

    def term_review(self, bond_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/bonds/%s/term-review" % bond_id,
            payload if payload is not None else {},
            headers,
        )

    def reinstate_bond(self, bond_id, payload, headers=None):
        return self._request("POST", "/bonds/%s/reinstate" % bond_id, payload, headers)

    def create_renewal(self, bond_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/bonds/%s/renewals" % bond_id,
            payload if payload is not None else {},
            headers,
        )

    def list_bond_renewals(self, bond_id, headers=None, params=None, **filters):
        return self._request(
            "GET",
            "/bonds/%s/renewals" % bond_id,
            _query(params, **filters),
            headers,
        )

    # ------------------------------------------------------------------
    # Renewal invoices
    # ------------------------------------------------------------------

    def get_renewal(self, renewal_id, headers=None):
        return self._request("GET", "/bond-renewals/%s" % renewal_id, None, headers)

    def list_renewals(self, headers=None, params=None, **filters):
        return self._request("GET", "/bond-renewals", _query(params, **filters), headers)

    def complete_renewal(self, renewal_id, payload, headers=None):
        return self._request(
            "POST", "/bond-renewals/%s/complete" % renewal_id, payload, headers
        )

    # ------------------------------------------------------------------
    # Statutory WDO reports
    # ------------------------------------------------------------------

    def create_wdo_report(self, payload, headers=None):
        return self._request("POST", "/wdo-reports", payload, headers)

    def get_wdo_report(self, report_id, headers=None):
        return self._request("GET", "/wdo-reports/%s" % report_id, None, headers)

    def list_wdo_reports(self, headers=None, params=None, **filters):
        return self._request("GET", "/wdo-reports", _query(params, **filters), headers)

    def issue_wdo_report(self, report_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/wdo-reports/%s/issue" % report_id,
            payload if payload is not None else {},
            headers,
        )

    def amend_wdo_report(self, report_id, payload, headers=None):
        return self._request(
            "POST", "/wdo-reports/%s/amend" % report_id, payload, headers
        )

    # ------------------------------------------------------------------
    # Damage claims
    # ------------------------------------------------------------------

    def create_damage_claim(self, payload, headers=None):
        return self._request("POST", "/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers=None):
        return self._request("GET", "/damage-claims/%s" % claim_id, None, headers)

    def list_damage_claims(self, headers=None, params=None, **filters):
        return self._request("GET", "/damage-claims", _query(params, **filters), headers)

    def attach_verification(self, claim_id, payload, headers=None):
        return self._request(
            "POST", "/damage-claims/%s/attach-verification" % claim_id, payload, headers
        )

    def adjudicate_claim(self, claim_id, payload, headers=None):
        return self._request(
            "POST", "/damage-claims/%s/adjudicate" % claim_id, payload, headers
        )

    def withdraw_claim(self, claim_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/damage-claims/%s/withdraw" % claim_id,
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
