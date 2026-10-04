"""Veterinarian, Product and PharmacySite endpoints."""

from flask import request

import db
import serializers
from errors import fail
from middleware import body, field
from routing import Arr, Obj, endpoint, resolve
from services import plans as plan_svc
from services.constants import MEDICATION_SCOPES, VET_STATUSES


# ---------------------------------------------------------------------------
# Veterinarians
# ---------------------------------------------------------------------------

@endpoint(
    "/v1/veterinarians",
    ["POST"],
    ["Customer", "CustomerService", "PharmacyTechnician", "ClinicContact", "ComplianceOfficer"],
    201,
)
def create_vet(caller, ):
    payload = body()
    row = db.mint(
        db.VETERINARIANS,
        full_name=field(payload, "full_name"),
        clinic_name=field(payload, "clinic_name"),
        clinic_phone=field(payload, "clinic_phone"),
        vet_email=field(payload, "vet_email"),
        license_number=field(payload, "license_number"),
        license_state=field(payload, "license_state"),
        vet_status="LISTED",
        registered_by=caller.id,
    )
    return Obj(serializers.veterinarian(row), 201)


@endpoint(
    "/v1/veterinarians",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "ClinicContact", "ComplianceOfficer"],
)
def list_vets(caller, ):
    rows = db.ordered(db.VETERINARIANS.values())
    status = request.args.get("vet_status")
    if status:
        rows = [r for r in rows if r.get("vet_status") == status]
    return Arr([serializers.veterinarian(r) for r in rows])


@endpoint(
    "/v1/veterinarians/<vet_id>",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "ClinicContact", "ComplianceOfficer"],
)
def read_vet(caller, vet_id):
    row = resolve(db.VETERINARIANS, vet_id, "veterinarian")
    return Obj(serializers.veterinarian(row))


@endpoint("/v1/veterinarians/<vet_id>/status", ["POST"], ["ComplianceOfficer", "PlatformAdmin"])
def set_vet_status(caller, vet_id):
    vet = resolve(db.VETERINARIANS, vet_id, "veterinarian")
    payload = body()
    new_status = field(payload, "vet_status")
    if new_status not in VET_STATUSES:
        fail("ERR_INVALID_REQUEST", "vet_status is not a declared value.")
    vet["vet_status"] = new_status
    db.touch(vet)
    plan_svc.vet_suspension_failover(vet)
    return Obj(serializers.veterinarian(vet))


@endpoint(
    "/v1/veterinarians/<vet_id>/prescriptions",
    ["GET"],
    ["PharmacyTechnician", "PharmacyManager", "ClinicContact", "ComplianceOfficer"],
)
def vet_prescriptions(caller, vet_id):
    vet = resolve(db.VETERINARIANS, vet_id, "veterinarian")
    rows = [p for p in db.PRESCRIPTIONS.values() if p.get("prescriber_id") == vet["id"]]
    return Arr([serializers.prescription(r) for r in db.ordered(rows)])


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@endpoint("/v1/products", ["POST"], ["PlatformAdmin", "ComplianceOfficer"], 201)
def create_product(caller, ):
    payload = body()
    sku = field(payload, "sku")
    if any(p.get("sku") == sku for p in db.PRODUCTS.values()):
        fail("ERR_INVALID_REQUEST", "sku must be unique across the catalog.")
    scope = field(payload, "medication_scope")
    if scope not in MEDICATION_SCOPES:
        fail("ERR_INVALID_REQUEST", "medication_scope must be OTC or PRESCRIPTION.")
    dose = payload.get("unit_dose_mg_per_kg")
    if dose is None or float(dose) <= 0:
        fail("ERR_INVALID_REQUEST", "unit_dose_mg_per_kg must be strictly greater than zero.")
    pack_size = payload.get("pack_size_units")
    if pack_size is None or int(pack_size) < 1:
        fail("ERR_INVALID_REQUEST", "pack_size_units must be at least 1.")
    row = db.mint(
        db.PRODUCTS,
        sku=sku,
        product_name=field(payload, "product_name"),
        medication_scope=scope,
        cold_pack_required=bool(payload.get("cold_pack_required", False)),
        unit_dose_mg_per_kg=dose,
        pack_size_units=int(pack_size),
        unit_price_cents=int(payload.get("unit_price_cents", 0) or 0),
    )
    return Obj(serializers.product(row), 201)


@endpoint(
    "/v1/products",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer", "PlatformAdmin"],
)
def list_products(caller, ):
    rows = db.ordered(db.PRODUCTS.values())
    scope = request.args.get("medication_scope")
    sku = request.args.get("sku")
    if scope:
        rows = [r for r in rows if r.get("medication_scope") == scope]
    if sku:
        rows = [r for r in rows if r.get("sku") == sku]
    return Arr([serializers.product(r) for r in rows])


@endpoint(
    "/v1/products/<product_id>",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer", "PlatformAdmin"],
)
def read_product(caller, product_id):
    row = resolve(db.PRODUCTS, product_id, "product")
    return Obj(serializers.product(row))


@endpoint(
    "/v1/products/<product_id>/autoship-items",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer", "PlatformAdmin"],
)
def product_items(caller, product_id):
    product = resolve(db.PRODUCTS, product_id, "product")
    rows = [i for i in db.AUTOSHIP_ITEMS.values() if i.get("product_id") == product["id"]]
    return Arr([serializers.autoship_item(r) for r in db.ordered(rows)])


@endpoint(
    "/v1/products/<product_id>/order-lines",
    ["GET"],
    ["CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer", "PlatformAdmin"],
)
def product_lines(caller, product_id):
    product = resolve(db.PRODUCTS, product_id, "product")
    rows = [l for l in db.ORDER_LINES.values() if l.get("product_id") == product["id"]]
    return Arr([serializers.order_line(r) for r in db.ordered(rows)])


@endpoint("/v1/products/<product_id>/price", ["POST"], ["PlatformAdmin", "ComplianceOfficer"])
def set_product_price(caller, product_id):
    product = resolve(db.PRODUCTS, product_id, "product")
    payload = body()
    price = payload.get("unit_price_cents")
    if price is None:
        fail("ERR_INVALID_REQUEST", "Field 'unit_price_cents' is required.")
    product["unit_price_cents"] = int(price)
    db.touch(product)
    for item in db.AUTOSHIP_ITEMS.values():
        if item.get("product_id") != product["id"]:
            continue
        item["unit_price_cents"] = int(price)
        item["protection_state"] = serializers.protection_state(item)
        db.touch(item)
    return Obj(serializers.product(product))


# ---------------------------------------------------------------------------
# Pharmacy sites
# ---------------------------------------------------------------------------

@endpoint("/v1/pharmacy-sites", ["POST"], ["PlatformAdmin", "ComplianceOfficer"], 201)
def create_site(caller, ):
    payload = body()
    site_code = field(payload, "site_code")
    if any(s.get("site_code") == site_code for s in db.PHARMACY_SITES.values()):
        fail("ERR_INVALID_REQUEST", "site_code must be unique across sites.")
    capacity = payload.get("cold_pack_capacity_units")
    if capacity is None or int(capacity) < 0:
        fail("ERR_INVALID_REQUEST", "cold_pack_capacity_units must be >= 0.")
    licensed = payload.get("licensed_states")
    if licensed is None or not isinstance(licensed, list):
        fail("ERR_INVALID_REQUEST", "licensed_states must be a list.")
    row = db.mint(
        db.PHARMACY_SITES,
        site_code=site_code,
        site_state=field(payload, "site_state"),
        licensed_states=list(licensed),
        cold_pack_capacity_units=int(capacity),
        csr_registered=bool(payload.get("csr_registered", False)),
        site_status="ACTIVE",
    )
    return Obj(serializers.pharmacy_site(row), 201)


@endpoint(
    "/v1/pharmacy-sites",
    ["GET"],
    ["PlatformAdmin", "ComplianceOfficer", "PharmacyManager", "PharmacyTechnician"],
)
def list_sites(caller, ):
    rows = db.ordered(db.PHARMACY_SITES.values())
    status = request.args.get("site_status")
    if status:
        rows = [r for r in rows if r.get("site_status") == status]
    return Arr([serializers.pharmacy_site(r) for r in rows])


@endpoint(
    "/v1/pharmacy-sites/<site_id>",
    ["GET"],
    ["PlatformAdmin", "ComplianceOfficer", "PharmacyManager", "PharmacyTechnician"],
)
def read_site(caller, site_id):
    row = resolve(db.PHARMACY_SITES, site_id, "pharmacy site")
    return Obj(serializers.pharmacy_site(row))


@endpoint(
    "/v1/pharmacy-sites/<site_id>/shipments",
    ["GET"],
    ["PharmacyTechnician", "PharmacyManager", "ComplianceOfficer", "PlatformAdmin"],
)
def site_shipments(caller, site_id):
    site = resolve(db.PHARMACY_SITES, site_id, "pharmacy site")
    rows = [s for s in db.SHIPMENTS.values() if s.get("origin_site_id") == site["id"]]
    return Arr([serializers.shipment(r) for r in db.ordered(rows)])


@endpoint(
    "/v1/pharmacy-sites/<site_id>/cold-pack-reservations",
    ["GET"],
    ["PharmacyTechnician", "PharmacyManager", "ComplianceOfficer", "PlatformAdmin"],
)
def site_reservations(caller, site_id):
    site = resolve(db.PHARMACY_SITES, site_id, "pharmacy site")
    rows = [r for r in db.COLD_PACK_RESERVATIONS.values() if r.get("site_id") == site["id"]]
    return Arr([serializers.cold_pack_reservation(r) for r in db.ordered(rows)])


@endpoint(
    "/v1/pharmacy-sites/<site_id>/restrict", ["POST"], ["ComplianceOfficer", "PlatformAdmin"]
)
def restrict_site(caller, site_id):
    site = resolve(db.PHARMACY_SITES, site_id, "pharmacy site")
    if site.get("site_status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE site can be restricted.")
    site["site_status"] = "RESTRICTED"
    return Obj(serializers.pharmacy_site(db.touch(site)))


@endpoint(
    "/v1/pharmacy-sites/<site_id>/clear-restriction",
    ["POST"],
    ["ComplianceOfficer", "PlatformAdmin"],
)
def clear_restriction(caller, site_id):
    site = resolve(db.PHARMACY_SITES, site_id, "pharmacy site")
    if site.get("site_status") != "RESTRICTED":
        fail("ERR_INVALID_STATE", "Only a RESTRICTED site can be cleared.")
    site["site_status"] = "ACTIVE"
    return Obj(serializers.pharmacy_site(db.touch(site)))


@endpoint(
    "/v1/pharmacy-sites/<site_id>/close", ["POST"], ["ComplianceOfficer", "PlatformAdmin"]
)
def close_site(caller, site_id):
    site = resolve(db.PHARMACY_SITES, site_id, "pharmacy site")
    if site.get("site_status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE site can be closed.")
    if serializers.committed_units(site["id"]) != 0:
        fail(
            "ERR_INVALID_STATE",
            "A site with committed cold-pack units cannot be closed.",
        )
    site["site_status"] = "CLOSED"
    return Obj(serializers.pharmacy_site(db.touch(site)))