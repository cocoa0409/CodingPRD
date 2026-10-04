"""Flask entry point: route registration, auth wiring, error handlers."""

import os

from flask import Flask

from util import ApiError, err_response
import routes as R

app = Flask(__name__)

BASE = "/field-force"


def add(method, path, roles, handler):
    """Register a route with auth handled uniformly.

    `handler` may accept no args, the path ids, or (ids..., uid, role).
    """
    def view(**kwargs):
        uid, role = R.auth(roles)
        params = list(kwargs.values())
        # Handlers that need identity declare trailing (uid, role) params.
        needs_identity = handler.__code__.co_argcount == len(params) + 2
        if needs_identity:
            return handler(*params, uid, role)
        return handler(*params)
    view.__name__ = handler.__name__
    app.add_url_rule(BASE + path, handler.__name__, view, methods=[method])


# --- Clock ---
add("POST", "/_clock/set_current_utc", ["PlatformAdmin"], R.clock_set)

# --- Regions ---
add("POST", "/regions", ["PlatformAdmin"], R.regions_create)
add("GET", "/regions", R.GET_ALL, R.regions_list)
add("GET", "/regions/<region_id>", R.GET_ALL, R.regions_get)

# --- Territories ---
add("POST", "/regions/<region_id>/territories", ["PlatformAdmin"], R.territories_create)
add("GET", "/territories", R.GET_ALL, R.territories_list)
add("GET", "/regions/<region_id>/territory-list", R.GET_ALL, R.territories_in_region)
add("GET", "/territories/<tid>", R.GET_ALL, R.territories_get)

# --- Representatives ---
add("POST", "/territories/<territory_id>/representatives", ["PlatformAdmin"], R.reps_create)
add("GET", "/territories/<territory_id>/representatives", R.GET_REPS, R.reps_in_territory)
add("GET", "/representatives", R.GET_REPS, R.reps_list)
add("GET", "/representatives/<rid>", R.GET_NO_QA, R.reps_get)

# --- Prescribers ---
add("POST", "/prescribers", ["PlatformAdmin"], R.prescribers_create)
add("GET", "/prescribers", R.GET_NO_QA, R.prescribers_list)
add("GET", "/prescribers/<pid>", R.GET_NO_QA, R.prescribers_get)
add("POST", "/prescribers/<pid>/verify-eligibility", ["ComplianceOfficer"], R.prescribers_verify)

# --- Products ---
add("POST", "/products", ["PlatformAdmin"], R.products_create)
add("GET", "/products", R.GET_ALL, R.products_list)
add("GET", "/products/<pid>", R.GET_ALL, R.products_get)

# --- Sample lots ---
add("POST", "/products/<product_id>/sample-lots", ["PlatformAdmin"], R.lots_create)
add("GET", "/sample-lots", R.GET_ALL, R.lots_list)
add("GET", "/products/<product_id>/sample-lot-list", R.GET_ALL, R.lots_in_product)
add("GET", "/sample-lots/<lid>", R.GET_ALL, R.lots_get)

# --- Rep lot balances ---
add("POST", "/representatives/<rep_id>/lot-balances", ["PlatformAdmin"], R.balances_issue)
add("GET", "/representatives/<rep_id>/lot-balances", R.GET_NO_QA, R.balances_for_rep)
add("GET", "/lot-balances", R.GET_NO_QA, R.balances_list)
add("GET", "/lot-balances/<bid>", R.GET_NO_QA, R.balances_get)

# --- Target list entries ---
add("POST", "/territories/<territory_id>/target-list-entries", ["DistrictManager"], R.entries_create)
add("GET", "/territories/<territory_id>/target-list-entries", R.GET_NO_QA, R.entries_in_territory)
add("GET", "/target-list-entries", R.GET_NO_QA, R.entries_list)
add("GET", "/target-list-entries/<eid>", R.GET_NO_QA, R.entries_get)

# --- Call plans ---
add("POST", "/call-plans", ["DistrictManager"], R.plans_create)
add("GET", "/call-plans", R.GET_NO_QA, R.plans_list)
add("GET", "/call-plans/<pid>", R.GET_NO_QA, R.plans_get)
add("POST", "/call-plans/<pid>/publish", ["DistrictManager"], R.plans_publish)

# --- Call visits ---
add("POST", "/call-visits", ["FieldRep"], R.visits_create)
add("GET", "/call-visits", R.GET_NO_QA, R.visits_list)
add("GET", "/call-visits/<vid>", R.GET_NO_QA, R.visits_get)
add("POST", "/call-visits/<vid>/complete", ["FieldRep"], R.visits_complete)
add("POST", "/call-visits/<vid>/cancel", ["FieldRep", "DistrictManager"], R.visits_cancel)
add("POST", "/call-visits/<vid>/mark-no-show", ["FieldRep"], R.visits_no_show)

# --- Sample disbursements ---
add("POST", "/sample-disbursements", ["FieldRep"], R.disbursements_create)
add("GET", "/sample-disbursements", R.GET_NO_QA, R.disbursements_list)
add("GET", "/sample-disbursements/<did>", R.GET_NO_QA, R.disbursements_get)
add("POST", "/sample-disbursements/<did>/capture-signature", ["FieldRep"], R.disbursements_capture)
add("POST", "/sample-disbursements/<did>/reject-signature", ["FieldRep", "ComplianceOfficer"], R.disbursements_reject)
add("GET", "/call-visits/<vid>/sample-disbursements", R.GET_NO_QA, R.disbursements_of_visit)

# --- Count lines ---
add("GET", "/count-lines", R.GET_NO_QA, R.count_lines_list)
add("GET", "/count-lines/<cid>", R.GET_NO_QA, R.count_lines_get)

# --- Sample transfers ---
add("POST", "/sample-transfers", ["FieldRep"], R.transfers_create)
add("GET", "/sample-transfers", R.GET_NO_QA, R.transfers_list)
add("GET", "/sample-transfers/<tid>", R.GET_NO_QA, R.transfers_get)
add("POST", "/sample-transfers/<tid>/accept", ["FieldRep"], R.transfers_accept)
add("POST", "/sample-transfers/<tid>/reject", ["FieldRep"], R.transfers_reject)
add("POST", "/sample-transfers/<tid>/cancel", ["FieldRep"], R.transfers_cancel)
add("POST", "/sample-transfers/<tid>/reverse", ["ComplianceOfficer"], R.transfers_reverse)

# --- Inventory count sessions ---
add("POST", "/inventory-count-sessions", ["DistrictManager"], R.sessions_create)
add("GET", "/inventory-count-sessions", R.GET_NO_QA, R.sessions_list)
add("GET", "/inventory-count-sessions/<sid>", R.GET_NO_QA, R.sessions_get)
add("GET", "/inventory-count-sessions/<sid>/count-lines", R.GET_NO_QA, R.sessions_count_lines)
add("POST", "/inventory-count-sessions/<sid>/submit-count", ["FieldRep"], R.sessions_submit_count)
add("POST", "/inventory-count-sessions/<sid>/reconcile", ["DistrictManager"], R.sessions_reconcile)
add("POST", "/inventory-count-sessions/<sid>/reopen", ["ComplianceOfficer"], R.sessions_reopen)
add("POST", "/inventory-count-sessions/<sid>/close", ["ComplianceOfficer"], R.sessions_close)
add("POST", "/inventory-count-sessions/<sid>/void", ["DistrictManager", "ComplianceOfficer"], R.sessions_void)

# --- Temperature excursions ---
add("POST", "/temperature-excursions", ["FieldRep"], R.excursions_create)
add("GET", "/temperature-excursions", R.GET_ALL, R.excursions_list)
add("GET", "/temperature-excursions/<eid>", R.GET_ALL, R.excursions_get)
add("POST", "/temperature-excursions/<eid>/assess", ["QualityAssurance"], R.excursions_assess)
add("POST", "/temperature-excursions/<eid>/resolve", ["QualityAssurance"], R.excursions_resolve)

# --- Sample returns ---
add("POST", "/sample-returns", ["FieldRep"], R.returns_create)
add("GET", "/sample-returns", R.GET_NO_QA, R.returns_list)
add("GET", "/sample-returns/<rid>", R.GET_NO_QA, R.returns_get)
add("POST", "/sample-returns/<rid>/submit", ["FieldRep"], R.returns_submit)
add("POST", "/sample-returns/<rid>/confirm-destruction", ["ComplianceOfficer"], R.returns_confirm)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    return err_response("ERR_INVALID_REQUEST", 400, str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
