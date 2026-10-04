"""Role-based access control.

Header scheme (PRD section 2.1, SCAFFOLD validations priority 1): every
request carries exactly two headers, `X-User-ID` and `X-User-Role`. Both must
be present and `X-User-Role` must name one of the five declared roles.

The operation -> permitted-roles matrix below is read straight from
SCAFFOLD.yaml section 1.5 (`roles` on each endpoint), cross-checked against
PRD section 4.
"""

from errors import unauthenticated, unauthorized

ROLES = (
    "PlatformAdmin",
    "CatalogCurator",
    "CustomerAccount",
    "WarehousePicker",
    "DCManager",
)

ALL_ROLES = set(ROLES)
READ_ALL = ALL_ROLES

# key = (METHOD, path template)
PERMISSIONS = {
    # ---- clock ----
    ("POST", "/_clock/set_current_utc"): {"PlatformAdmin"},

    # ---- distribution centers ----
    ("POST", "/distribution-centers"): {"PlatformAdmin"},
    ("GET", "/distribution-centers"): READ_ALL,
    ("GET", "/distribution-centers/<dc_id>"): READ_ALL,
    ("POST", "/distribution-centers/<dc_id>/roll_cutoff"): {"DCManager"},
    ("POST", "/distribution-centers/<dc_id>/reeducate"): {"DCManager"},
    ("GET", "/distribution-centers/<dc_id>/order-lines"): {
        "PlatformAdmin", "CustomerAccount", "DCManager", "WarehousePicker"},
    ("GET", "/distribution-centers/<dc_id>/stock"): {"PlatformAdmin", "DCManager"},

    # ---- suppliers ----
    ("POST", "/suppliers"): {"PlatformAdmin"},
    ("GET", "/suppliers"): {"PlatformAdmin", "CatalogCurator", "DCManager"},
    ("GET", "/suppliers/<supplier_id>"): {"PlatformAdmin", "CatalogCurator", "DCManager"},
    ("GET", "/suppliers/<supplier_id>/availability-reports"): {
        "PlatformAdmin", "CatalogCurator", "DCManager"},
    ("POST", "/suppliers/<supplier_id>/availability-reports"): {"PlatformAdmin"},

    # ---- items / curation ----
    ("POST", "/items"): {"CatalogCurator"},
    ("GET", "/items"): READ_ALL,
    ("GET", "/items/<item_id>"): READ_ALL,
    ("GET", "/items/<item_id>/order-lines"): {
        "PlatformAdmin", "CustomerAccount", "DCManager", "WarehousePicker"},
    ("GET", "/items/<item_id>/availability-reports"): {
        "PlatformAdmin", "CatalogCurator", "DCManager"},
    ("POST", "/items/<item_id>/attributes"): {"CatalogCurator"},
    ("GET", "/items/<item_id>/attributes"): READ_ALL,
    ("POST", "/items/<item_id>/cross-references"): {"CatalogCurator"},
    ("GET", "/items/<item_id>/cross-references"): READ_ALL,
    ("GET", "/items/<item_id>/curation-review-items"): {"PlatformAdmin", "CatalogCurator"},
    ("POST", "/curation-reviews"): {"CatalogCurator"},
    ("GET", "/curation-reviews"): {"PlatformAdmin", "CatalogCurator"},
    ("GET", "/curation-reviews/<review_id>"): {"PlatformAdmin", "CatalogCurator"},
    ("GET", "/curation-reviews/<review_id>/items"): {"PlatformAdmin", "CatalogCurator"},
    ("POST", "/curation-reviews/<review_id>/revoke"): {"CatalogCurator"},

    # ---- inventory ----
    ("POST", "/stock"): {"DCManager"},
    ("GET", "/stock"): {"PlatformAdmin", "CustomerAccount", "DCManager", "WarehousePicker"},
    ("GET", "/stock/<stock_id>"): {"PlatformAdmin", "CustomerAccount", "DCManager", "WarehousePicker"},

    # ---- accounts ----
    ("POST", "/accounts"): {"PlatformAdmin"},
    ("GET", "/accounts"): {"PlatformAdmin", "CustomerAccount", "DCManager"},
    ("GET", "/accounts/<account_id>"): {"PlatformAdmin", "CustomerAccount", "DCManager"},

    # ---- orders ----
    ("POST", "/orders"): {"CustomerAccount"},
    ("GET", "/orders"): {"PlatformAdmin", "CustomerAccount", "DCManager", "WarehousePicker"},
    ("GET", "/orders/<order_id>"): {"PlatformAdmin", "CustomerAccount", "DCManager", "WarehousePicker"},
    ("POST", "/orders/<order_id>/release"): {"CustomerAccount"},
    ("POST", "/orders/<order_id>/allocate"): {"CustomerAccount"},
    ("POST", "/orders/<order_id>/cancel"): {"CustomerAccount"},
    ("GET", "/orders/<order_id>/lines"): {"PlatformAdmin", "CustomerAccount", "DCManager", "WarehousePicker"},
    ("POST", "/orders/<order_id>/lines/<line_id>/pick"): {"WarehousePicker"},
    ("POST", "/orders/<order_id>/lines/<line_id>/pick_complete"): {"WarehousePicker"},
    ("POST", "/orders/<order_id>/confirm_cutoff"): {"DCManager"},
    ("GET", "/order-lines"): {"PlatformAdmin", "CustomerAccount", "DCManager", "WarehousePicker"},

    # ---- pick tasks / shipments ----
    ("GET", "/pick-tasks"): {"PlatformAdmin", "DCManager", "WarehousePicker"},
    ("GET", "/pick-tasks/<pick_id>"): {"PlatformAdmin", "DCManager", "WarehousePicker"},
    ("GET", "/shipments"): {"PlatformAdmin", "DCManager", "CustomerAccount"},
    ("GET", "/shipments/<shipment_id>"): {"PlatformAdmin", "DCManager", "CustomerAccount"},
    ("POST", "/shipments/<shipment_id>/dispatch"): {"DCManager"},

    # ---- returns ----
    ("POST", "/returns"): {"CustomerAccount", "DCManager"},
    ("GET", "/returns"): {"PlatformAdmin", "DCManager", "CustomerAccount"},
    ("GET", "/returns/<return_id>"): {"PlatformAdmin", "DCManager", "CustomerAccount"},
    ("POST", "/returns/<return_id>/approve"): {"DCManager"},
    ("POST", "/returns/<return_id>/receive"): {"DCManager"},
    ("POST", "/returns/<return_id>/cancel"): {"DCManager"},

    # ---- damage claims ----
    ("GET", "/damage-claims"): {"PlatformAdmin", "DCManager", "WarehousePicker", "CustomerAccount"},
    ("GET", "/damage-claims/<claim_id>"): {"PlatformAdmin", "DCManager", "WarehousePicker", "CustomerAccount"},
    ("POST", "/damage-claims/<claim_id>/resume_fulfillment"): {"WarehousePicker"},
    ("POST", "/damage-claims/<claim_id>/resolve"): {"DCManager"},
    ("POST", "/damage-claims/<claim_id>/reject"): {"DCManager"},
    ("POST", "/damage-claims/<claim_id>/void"): {"DCManager"},

    # ---- square footage ----
    ("POST", "/square-footage-requests"): {"CustomerAccount"},
    ("GET", "/square-footage-requests"): {"PlatformAdmin", "CustomerAccount", "WarehousePicker"},
    ("GET", "/square-footage-requests/<request_id>"): {"PlatformAdmin", "CustomerAccount", "WarehousePicker"},
    ("GET", "/square-footage-requests/<request_id>/lines"): {"PlatformAdmin", "CustomerAccount", "WarehousePicker"},
    ("GET", "/square-footage-lines"): {"PlatformAdmin", "CustomerAccount", "WarehousePicker"},
    ("POST", "/square-footage-requests/<request_id>/cut"): {"WarehousePicker"},
}


def identify():
    """Priority 1: both headers present and the role declared."""
    user_id = request_header("X-User-ID")
    role = request_header("X-User-Role")
    if not user_id or not role:
        raise unauthenticated()
    if role not in ALL_ROLES:
        raise unauthenticated("X-User-Role '%s' is not a declared role." % role)
    return user_id, role


def request_header(name):
    from flask import request
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def authorize(role, method, path_template):
    """Priority 2: the calling role must be permitted to invoke the operation."""
    permitted = PERMISSIONS.get((method, path_template))
    if permitted is None:
        return
    if role not in permitted:
        raise unauthorized(
            "Role '%s' may not invoke %s %s." % (role, method, path_template)
        )