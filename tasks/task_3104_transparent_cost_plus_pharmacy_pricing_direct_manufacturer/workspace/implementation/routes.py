"""The route table, declared once and registered onto the Flask app.

Each entry is (method, rule, handler, permitted roles). The rule string is
identical to the endpoint path in PRD §4, so auth.PERMISSIONS — keyed by the
same rule — lines up exactly with what Flask matches.
"""

from auth import ROLES

ALL_ROLES = ROLES

ROUTES = [
    # --- clock / health ---
    ("POST", "/_clock/set_current_utc", "views_clock:set_clock", ("PharmacyOps",)),
    ("GET", "/_health", "views_clock:health", ALL_ROLES),

    # --- manufacturers ---
    ("POST", "/manufacturers", "views_catalog:create_manufacturer", ("PharmacyOps",)),
    ("GET", "/manufacturers", "views_catalog:list_manufacturers", ("PharmacyOps",)),
    ("GET", "/manufacturers/<manufacturer_id>", "views_catalog:get_manufacturer", ("PharmacyOps",)),
    ("POST", "/manufacturers/<manufacturer_id>/state", "views_catalog:set_manufacturer_state", ("PharmacyOps",)),
    ("GET", "/manufacturers/<manufacturer_id>/drug-prices", "views_catalog:list_manufacturer_drug_prices", ("PharmacyOps",)),

    # --- drugs ---
    ("POST", "/drugs", "views_catalog:create_drug", ("PharmacyOps",)),
    ("GET", "/drugs", "views_catalog:list_drugs", ("PharmacyOps", "Pharmacist", "Patient")),
    ("GET", "/drugs/<drug_id>", "views_catalog:get_drug", ("PharmacyOps", "Pharmacist", "Patient")),
    ("GET", "/drugs/<drug_id>/manufacturer-drug-prices", "views_catalog:list_drug_prices", ("PharmacyOps", "Pharmacist", "Patient")),
    ("GET", "/drugs/<drug_id>/prescriptions", "views_catalog:list_drug_prescriptions", ("PharmacyOps", "Pharmacist")),

    # --- formularies (a read-only computed view over Drug) ---
    ("GET", "/formularies/<drug_id>/stock-check", "views_catalog:stock_check", ("PharmacyOps", "Pharmacist", "Patient")),
    ("GET", "/formularies/<drug_id>/supply-summary", "views_catalog:supply_summary", ("PharmacyOps", "Pharmacist")),
    ("GET", "/formularies/<drug_id>/expansion-score", "views_catalog:expansion_score_view", ("PharmacyOps", "Pharmacist")),
    ("POST", "/formularies/<drug_id>/expansion", "views_catalog:expand_formulary", ("PharmacyOps",)),
    ("POST", "/formularies/<drug_id>/delist", "views_catalog:delist_formulary", ("PharmacyOps",)),

    # --- manufacturer drug prices ---
    ("POST", "/manufacturer-drug-prices", "views_catalog:create_price", ("PharmacyOps",)),
    ("GET", "/manufacturer-drug-prices", "views_catalog:list_prices", ("PharmacyOps", "Pharmacist", "Patient")),
    ("GET", "/manufacturer-drug-prices/<price_id>", "views_catalog:get_price", ("PharmacyOps", "Pharmacist", "Patient")),
    ("POST", "/manufacturer-drug-prices/<price_id>/activation", "views_catalog:activate_price", ("PharmacyOps",)),
    ("POST", "/manufacturer-drug-prices/<price_id>/sourcing", "views_catalog:move_sourcing", ("PharmacyOps",)),
    ("POST", "/manufacturer-drug-prices/<price_id>/revocation", "views_catalog:revoke_price", ("PharmacyOps",)),
    ("GET", "/manufacturer-drug-prices/<price_id>/orders", "views_orders:list_price_orders", ("PharmacyOps", "Pharmacist")),

    # --- pharmacies and licences ---
    ("POST", "/pharmacies", "views_catalog:create_pharmacy", ("PharmacyOps",)),
    ("GET", "/pharmacies", "views_catalog:list_pharmacies", ("PharmacyOps",)),
    ("GET", "/pharmacies/<pharmacy_id>", "views_catalog:get_pharmacy", ("PharmacyOps", "Pharmacist")),
    ("POST", "/pharmacies/<pharmacy_id>/licenses", "views_catalog:create_license", ("PharmacyOps",)),
    ("GET", "/pharmacies/<pharmacy_id>/licenses", "views_catalog:list_licenses", ("PharmacyOps", "Pharmacist")),
    ("GET", "/pharmacies/<pharmacy_id>/licenses/<license_id>", "views_catalog:get_license", ("PharmacyOps", "Pharmacist")),
    ("POST", "/pharmacies/<pharmacy_id>/licenses/<license_id>/state", "views_catalog:set_license_state", ("PharmacyOps",)),
    ("POST", "/pharmacies/<pharmacy_id>/licenses/<license_id>/verification", "views_catalog:verify_license", ("PharmacyOps",)),
    ("GET", "/pharmacies/<pharmacy_id>/orders", "views_catalog:list_pharmacy_orders", ("PharmacyOps", "Pharmacist")),

    # --- patients and prescribers ---
    ("POST", "/patients", "views_catalog:create_patient", ("PharmacyOps",)),
    ("GET", "/patients", "views_catalog:list_patients", ("PharmacyOps",)),
    ("GET", "/patients/<patient_id>", "views_catalog:get_patient", ("PharmacyOps", "Patient")),
    ("GET", "/patients/<patient_id>/prescriptions", "views_catalog:list_patient_prescriptions", ("PharmacyOps", "Pharmacist", "Patient")),
    ("POST", "/prescribers", "views_catalog:create_prescriber", ("PharmacyOps",)),
    ("GET", "/prescribers/<prescriber_id>", "views_catalog:get_prescriber", ("PharmacyOps", "Pharmacist")),
    ("POST", "/prescribers/<prescriber_id>/state", "views_catalog:set_prescriber_state", ("PharmacyOps",)),
    ("GET", "/prescribers/<prescriber_id>/prescriptions", "views_catalog:list_prescriber_prescriptions", ("PharmacyOps", "Pharmacist")),

    # --- prescriptions ---
    ("POST", "/prescriptions", "views_clinical:create_prescription", ("PharmacyOps",)),
    ("GET", "/prescriptions", "views_clinical:list_prescriptions", ("PharmacyOps", "Pharmacist", "Patient")),
    ("GET", "/prescriptions/<prescription_id>", "views_clinical:get_prescription", ("PharmacyOps", "Pharmacist", "Patient")),
    ("POST", "/prescriptions/<prescription_id>/intake-requests", "views_clinical:route_intake", ("PharmacyOps",)),
    ("GET", "/prescriptions/<prescription_id>/intake-requests", "views_clinical:list_prescription_requests", ("PharmacyOps", "Pharmacist")),
    ("POST", "/prescriptions/<prescription_id>/termination", "views_clinical:terminate_prescription", ("Pharmacist",)),
    ("POST", "/prescriptions/<prescription_id>/substitution", "views_clinical:substitute_prescription", ("Pharmacist",)),
    ("GET", "/prescriptions/<prescription_id>/orders", "views_clinical:list_prescription_orders", ("PharmacyOps", "Pharmacist", "Patient")),
    ("GET", "/prescriptions/<prescription_id>/claims", "views_clinical:list_prescription_claims", ("PharmacyOps", "Pharmacist", "Patient")),

    # --- prescription requests ---
    ("GET", "/prescription-requests", "views_clinical:list_requests", ("PharmacyOps", "Pharmacist")),
    ("GET", "/prescription-requests/<request_id>", "views_clinical:get_request", ("PharmacyOps", "Pharmacist")),
    ("POST", "/prescription-requests/<request_id>/review", "views_clinical:review_request", ("Pharmacist",)),
    ("POST", "/prescription-requests/<request_id>/acceptance", "views_clinical:accept_request", ("Pharmacist",)),
    ("POST", "/prescription-requests/<request_id>/rejection", "views_clinical:reject_request", ("Pharmacist",)),
    ("GET", "/prescription-requests/<request_id>/orders", "views_orders:list_request_orders", ("PharmacyOps", "Pharmacist")),
    ("GET", "/prescription-requests/<request_id>/shipments", "views_orders:list_request_shipments", ("PharmacyOps", "Pharmacist")),

    # --- claims ---
    ("GET", "/claims", "views_clinical:list_claims", ("PharmacyOps", "Pharmacist")),
    ("GET", "/claims/<claim_id>", "views_clinical:get_claim", ("PharmacyOps", "Pharmacist", "Patient")),
    ("POST", "/claims/<claim_id>/refill-authorizations", "views_clinical:authorize_refill", ("Pharmacist",)),
    ("GET", "/claim-summaries/<claim_id>", "views_clinical:get_claim_summary", ("PharmacyOps", "Pharmacist", "Patient")),

    # --- orders ---
    ("POST", "/orders", "views_orders:create_order", ("PharmacyOps",)),
    ("GET", "/orders", "views_orders:list_orders", ("PharmacyOps", "Pharmacist", "Patient")),
    ("GET", "/orders/<order_id>", "views_orders:get_order", ("PharmacyOps", "Pharmacist", "Patient")),
    ("POST", "/orders/<order_id>/payment", "views_orders:pay_order", ("PharmacyOps",)),
    ("POST", "/orders/<order_id>/fulfillment", "views_orders:fulfill_order", ("PharmacyOps",)),
    ("POST", "/orders/<order_id>/shipping", "views_orders:ship_order", ("PharmacyOps",)),
    ("POST", "/orders/<order_id>/delivery", "views_orders:deliver_order", ("PharmacyOps",)),
    ("POST", "/orders/<order_id>/cancellation", "views_orders:cancel_order_view", ("PharmacyOps",)),
    ("GET", "/orders/<order_id>/comparisons", "views_compliance:list_order_comparisons", ("PharmacyOps", "Pharmacist", "Patient")),
    ("GET", "/orders/<order_id>/comparison", "views_compliance:comparison_message", ("PharmacyOps", "Pharmacist", "Patient")),
    ("POST", "/orders/<order_id>/comparisons/<comparison_id>/refresh", "views_compliance:refresh_comparison", ("PharmacyOps",)),
    ("POST", "/orders/<order_id>/substantiation-enablement", "views_compliance:enable_substantiation", ("PharmacyOps",)),
    ("POST", "/orders/<order_id>/substantiation-disablement", "views_compliance:disable_substantiation", ("PharmacyOps",)),
    ("GET", "/orders/<order_id>/substantiation-records", "views_compliance:list_order_substantiations", ("PharmacyOps", "Pharmacist")),
    ("GET", "/orders/<order_id>/shipments", "views_orders:list_order_shipments", ("PharmacyOps", "Pharmacist", "Patient")),

    # --- shipments ---
    ("GET", "/shipments", "views_orders:list_shipments", ("PharmacyOps", "Pharmacist")),
    ("GET", "/shipment-summaries/<shipment_id>", "views_orders:get_shipment_summary", ("PharmacyOps", "Pharmacist", "Patient")),

    # --- comparisons and substantiations ---
    ("GET", "/comparisons", "views_compliance:list_comparisons", ("PharmacyOps", "Pharmacist")),
    ("POST", "/price-substantiations", "views_compliance:create_substantiation", ("PharmacyOps",)),
    ("GET", "/price-substantiations", "views_compliance:list_substantiations", ("PharmacyOps", "Pharmacist")),
    ("GET", "/price-substantiations/<substantiation_id>", "views_compliance:get_substantiation", ("PharmacyOps", "Pharmacist")),
]

# Static paths that must never be swallowed by a converter route.
STATIC_PATHS = (
    "/_health",
    "/_clock/set_current_utc",
    "/manufacturers",
    "/drugs",
    "/manufacturer-drug-prices",
    "/pharmacies",
    "/patients",
    "/prescribers",
    "/prescriptions",
    "/prescription-requests",
    "/orders",
    "/claims",
    "/shipments",
    "/comparisons",
    "/price-substantiations",
)


def resolve(dotted):
    """Resolve a 'module:function' reference inside this package."""
    module_name, function_name = dotted.split(":")
    module = __import__(module_name)
    return getattr(module, function_name)