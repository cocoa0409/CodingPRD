"""In-memory data store and logical clock."""

INITIAL_CLOCK = "2026-09-01T00:00:00Z"

# entity tables: name -> {id: record dict}
db = {
    "organizations": {},
    "admins": {},
    "end_users": {},
    "resellers": {},
    "plans": {},
    "subscriptions": {},
    "seats": {},
    "devices": {},
    "entitlements": {},
    "deployment_packages": {},
    "product_versions": {},
    "add_on_services": {},
    "assets": {},
    "transfer_requests": {},
    "reseller_orders": {},
    "compliance_audits": {},
    "cancellation_requests": {},
}

# logical clock (ISO8601 with Z suffix)
clock = {"current": INITIAL_CLOCK}
