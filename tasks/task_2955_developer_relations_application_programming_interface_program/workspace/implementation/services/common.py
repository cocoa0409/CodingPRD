"""Shared lookups, rounding helpers and the reusable eligibility gates."""
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from constants import (
    CURRENT_DOCS_VERSION,
    ESCALATION_ENTITLED_TIERS,
    GRANTABLE_TIERS_BY_LIFECYCLE,
    SCOPE_FACTOR_FINANCIAL_STEP,
    SCOPE_FACTOR_FLOOR,
    SCOPE_FACTOR_PERSONAL_STEP,
    TIER_RANK,
)
from db import store
from errors import ApiError


# ------------------------------------------------------------------- rounding
def round_half_up(value, places=0):
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(round_half_up(value, 0))


def money2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    value = Decimal(value)
    floored = value.to_integral_value(rounding=ROUND_FLOOR)
    return int(floored) if floored == value else int(floored) + 1


# -------------------------------------------------------------------- lookups
def version_of(version_id):
    return store.api_versions.get(version_id)


def product_of_version(version):
    return store.api_products.get(version["api_product_id"])


def product_of_assignment(assignment):
    version = store.api_versions.get(assignment["pinned_api_version_id"])
    if version is None:
        return None
    return store.api_products.get(version["api_product_id"])


def scope_sensitivity(product, scope):
    for entry in product["scope_catalog"]:
        if entry["scope"] == scope:
            return entry["sensitivity"]
    return None


def catalog_scopes(product):
    return [entry["scope"] for entry in product["scope_catalog"]]


def scope_factor(product, scopes):
    personal = 0
    financial = 0
    for scope in scopes:
        sensitivity = scope_sensitivity(product, scope)
        if sensitivity == "PERSONAL":
            personal += 1
        elif sensitivity == "FINANCIAL":
            financial += 1
    factor = (
        Decimal(1)
        - SCOPE_FACTOR_PERSONAL_STEP * personal
        - SCOPE_FACTOR_FINANCIAL_STEP * financial
    )
    if factor < SCOPE_FACTOR_FLOOR:
        factor = SCOPE_FACTOR_FLOOR
    return factor


def assignments_of_developer(developer_id):
    return [
        a
        for a in store.ordered(store.quota_assignments)
        if a["developer_id"] == developer_id
    ]


def assignments_pinned_to_version(version_id):
    return [
        a
        for a in store.ordered(store.quota_assignments)
        if a["pinned_api_version_id"] == version_id
    ]


def assignments_of_product(product_id):
    result = []
    for a in store.ordered(store.quota_assignments):
        version = store.api_versions.get(a["pinned_api_version_id"])
        if version is not None and version["api_product_id"] == product_id:
            result.append(a)
    return result


def has_active_tier(developer_id, tiers):
    for a in store.quota_assignments.values():
        if (
            a["developer_id"] == developer_id
            and a["entitlement_state"] == "ACTIVE"
            and a["tier"] in tiers
        ):
            return True
    return False


def top_active_tier(developer_id):
    best = "NONE"
    best_rank = 0
    for a in store.quota_assignments.values():
        if a["developer_id"] != developer_id or a["entitlement_state"] != "ACTIVE":
            continue
        rank = TIER_RANK.get(a["tier"], 0)
        if rank > best_rank:
            best_rank = rank
            best = a["tier"]
    return best


def is_entitled_for_escalation(developer_id):
    return has_active_tier(developer_id, ESCALATION_ENTITLED_TIERS)


# ---------------------------------------------------------------------- gates
def require_good_standing(developer):
    """Rung 20."""
    if developer["standing"] != "GOOD_STANDING":
        raise ApiError(
            "ERR_DEVELOPER_STANDING_BLOCKED",
            "The developer's standing is %s; GOOD_STANDING is required."
            % developer["standing"],
        )


def require_target_not_revoked(developer):
    """Rung 21 applied to an explicitly named target developer."""
    if developer["standing"] == "REVOKED":
        raise ApiError("ERR_DEVELOPER_REVOKED")


def require_tos_current(developer, product):
    """Rung 22 -- accepted ToS version at least the product's requirement."""
    accepted = developer["tos_version_accepted"]
    if accepted is None or accepted < product["required_tos_version"]:
        raise ApiError(
            "ERR_TOS_VERSION_STALE",
            "The developer must accept terms-of-service version %d."
            % product["required_tos_version"],
        )


def require_docs_acknowledged(developer):
    """Rung 23 -- acknowledged docs revision equals the current revision."""
    if developer["docs_version_acknowledged"] != CURRENT_DOCS_VERSION:
        raise ApiError(
            "ERR_DOCS_NOT_ACKNOWLEDGED",
            "The developer must acknowledge documentation revision %d."
            % CURRENT_DOCS_VERSION,
        )


def require_scope_sensitivity_permitted(product, scopes, tier):
    """Rung 24 -- PERSONAL needs STANDARD, FINANCIAL needs PARTNER."""
    rank = TIER_RANK.get(tier, 0)
    for scope in scopes:
        sensitivity = scope_sensitivity(product, scope)
        if sensitivity == "PERSONAL" and rank < TIER_RANK["STANDARD"]:
            raise ApiError(
                "ERR_SCOPE_SENSITIVITY_NOT_PERMITTED",
                "Scope %s carries PERSONAL sensitivity and requires at least STANDARD."
                % scope,
            )
        if sensitivity == "FINANCIAL" and rank < TIER_RANK["PARTNER"]:
            raise ApiError(
                "ERR_SCOPE_SENSITIVITY_NOT_PERMITTED",
                "Scope %s carries FINANCIAL sensitivity and requires at least PARTNER."
                % scope,
            )


def require_version_grantable(version, tier):
    """Rung 41 -- the version's lifecycle state must permit this tier."""
    grantable = GRANTABLE_TIERS_BY_LIFECYCLE.get(version["lifecycle_state"], [])
    if tier not in grantable:
        raise ApiError(
            "ERR_VERSION_NOT_GRANTABLE",
            "A %s version cannot be granted at tier %s."
            % (version["lifecycle_state"], tier),
        )


def require_version_not_sunset(version):
    """Activation and reinstatement both refuse a sunset pinned version."""
    if version is None or version["lifecycle_state"] == "SUNSET":
        raise ApiError(
            "ERR_VERSION_NOT_GRANTABLE",
            "The pinned API version has been sunset.",
        )


def certification_active(developer):
    expires = developer["certification_expires_at"]
    if expires is None:
        return False
    return expires >= store.now()
