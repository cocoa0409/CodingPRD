"""Shared lookups and the gate helpers that several workflows re-use."""

import constants as K
from calc import export_control_classification
from error import (
    CatalogError,
    ERR_ALLOCATED_UNITS_CHANGED,
    ERR_BLUEPRINT_NOT_FOUND,
    ERR_EXPORT_CONTROL_RESTRICTED,
    ERR_EXPORT_LICENSE_REQUIRED,
    ERR_HOLD_TIER_EXCEEDS_BAND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NDA_NOT_BOUND,
    ERR_NODE_NOT_OPEN_FOR_ALLOCATION,
    ERR_NO_OPEN_EPOCH,
    ERR_PARTNER_NOT_FOUND,
    ERR_QUALIFICATION_NOT_MET,
    ERR_RESOURCE_NOT_FOUND,
    ERR_STALE_PARTNER_VERSION,
    ERR_STALE_SUBSCRIPTION_VERSION,
)
from store import DB

# Accepting natural keys alongside uuids makes the surface tolerant of a
# harness that addresses a pool by node_code; every documented path uses ids.
_NATURAL_KEYS = {
    "products": ("sku_code",),
    "nodes": ("node_code",),
    "blueprints": ("blueprint_code",),
    "stack_licenses": ("license_code",),
}


# --------------------------------------------------------------- lookups ---
def resolve(collection, ident):
    if ident is None:
        return None
    table = getattr(DB, collection)
    row = table.get(ident)
    if row is not None:
        return row
    for key_field in _NATURAL_KEYS.get(collection, ()):
        for candidate in table.values():
            if candidate.get(key_field) == ident:
                return candidate
    return None


def partner_or_404(partner_id):
    partner = resolve("partners", partner_id)
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    return partner


def resource_or_404(collection, ident, label="resource"):
    row = resolve(collection, ident)
    if row is None:
        raise CatalogError(ERR_RESOURCE_NOT_FOUND, "The %s does not exist." % label)
    return row


def blueprint_or_404(blueprint_id):
    blueprint = resolve("blueprints", blueprint_id)
    if blueprint is None:
        raise CatalogError(ERR_BLUEPRINT_NOT_FOUND)
    return blueprint


# ------------------------------------------------------------------ gates --
def require_open_epoch():
    if DB.open_epoch() is None:
        raise CatalogError(ERR_NO_OPEN_EPOCH)


def check_node_open(node):
    if node.get("stage") in ("DRAINING", "BINDING"):
        raise CatalogError(ERR_NODE_NOT_OPEN_FOR_ALLOCATION)


def check_tier_within_band(tier, ceiling):
    if K.TIER_INDEX[tier] > K.TIER_INDEX[ceiling]:
        raise CatalogError(ERR_HOLD_TIER_EXCEEDS_BAND)


def check_allocated_units(product, expected):
    if expected is None:
        raise CatalogError(ERR_INVALID_REQUEST, "expected_allocated_units is required.")
    if int(expected) != int(product.get("allocated_units", 0) or 0):
        raise CatalogError(ERR_ALLOCATED_UNITS_CHANGED)


def check_partner_version(partner, expected):
    if expected is None:
        raise CatalogError(ERR_INVALID_REQUEST, "expected_partner_version is required.")
    if int(expected) != int(partner.get("version", 1)):
        raise CatalogError(ERR_STALE_PARTNER_VERSION)


def check_subscription_version(sub, expected):
    if expected is None:
        raise CatalogError(ERR_INVALID_REQUEST, "expected_subscription_version is required.")
    if int(expected) != int(sub.get("version", 1)):
        raise CatalogError(ERR_STALE_SUBSCRIPTION_VERSION)


def check_product_version(product, expected):
    if expected is None:
        raise CatalogError(ERR_INVALID_REQUEST, "expected_product_version is required.")
    if int(expected) != int(product.get("version", 1)):
        raise CatalogError(ERR_INVALID_STATE, "The product version supplied is stale.")


def check_qualified(partner):
    if partner.get("qualification_status") != "QUALIFIED":
        raise CatalogError(ERR_QUALIFICATION_NOT_MET)


def check_state(row, expected):
    if row.get("state") != expected:
        raise CatalogError(ERR_INVALID_STATE, "Expected state %s but found %s." % (expected, row.get("state")))


def check_status(row, expected):
    if row.get("status") != expected:
        raise CatalogError(ERR_INVALID_STATE, "Expected status %s but found %s." % (expected, row.get("status")))


# ----------------------------------------------------------------- export --
def classification_for(product, destination_code):
    band = product.get("export_performance_density_band", "LOW")
    return export_control_classification(destination_code, band)


def active_export_grant(product, destination_code):
    for grant in DB.export_grants.values():
        if grant.get("product_sku_id") != product.get("id"):
            continue
        if grant.get("destination_country_code") != destination_code:
            continue
        if grant.get("grant_status") != "ACTIVE":
            continue
        return grant
    return None


def check_export_gate(product, destination_code):
    classification = classification_for(product, destination_code)
    if classification == "TIER_3_PROHIBITED":
        raise CatalogError(ERR_EXPORT_CONTROL_RESTRICTED)
    if classification == "TIER_2_LICENSE_REQUIRED":
        if active_export_grant(product, destination_code) is None:
            raise CatalogError(ERR_EXPORT_LICENSE_REQUIRED)
    return classification


# -------------------------------------------------------------------- NDA --
def bound_ack_for(partner_id, stack_license_id):
    for ack in DB.acks.values():
        if ack.get("partner_id") != partner_id:
            continue
        if ack.get("stack_license_id") != stack_license_id:
            continue
        if ack.get("ack_status") == "BOUND":
            return ack
    return None


def check_nda_bound(partner_id, stack_license_id):
    if bound_ack_for(partner_id, stack_license_id) is None:
        raise CatalogError(ERR_NDA_NOT_BOUND)