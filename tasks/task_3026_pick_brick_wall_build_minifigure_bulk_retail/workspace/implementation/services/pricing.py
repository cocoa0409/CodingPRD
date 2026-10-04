"""Cup pricing: inference, the two models, the bucket bands and member pricing.

Every formula is the one in SCAFFOLD.yaml §1.3, and the rounding points are the
ones PRD §2.8 says are pinned (the discount is rounded, then the surcharge is
rounded again on the result; the piece inferer forms a product, divides, then
rounds exactly once).
"""

from decimal import Decimal

from db import (
    CUP_CAPACITY_GRAMS,
    CUP_REFERENCE_MASS_GRAMS,
    CUP_VOLUME_ML,
    INCLUDED_PIECES,
    LAUNCH_SURCHARGE_PCT,
    OVERAGE_BAND_CENTS,
    PER_PIECE_SURCHARGE_BAND,
    PER_PIECE_SURCHARGE_THRESHOLD,
    PER_PIECE_UNIT_CENTS,
    RESTRICTED_SURCHARGE_DIVISOR,
    STANDARD_CUP_CAPACITY_GRAMS,
    STANDARD_DISCOUNT_PCT,
    VIP_DISCOUNT_PCT,
)
from services.core import rh


def inferred_pieces(order, variant):
    """cup_fill_inferred_pieces: product, then division, then one rounding."""
    size = order["cup_size"]
    if variant == "VOLUME":
        numerator = (
            Decimal(str(order.get("measured_volume_ml") or 0))
            * Decimal(CUP_REFERENCE_MASS_GRAMS[size])
        )
        base_mass = numerator / Decimal(CUP_VOLUME_ML[size])
    else:
        base_mass = Decimal(str(order["declared_mass_grams"]))
    return rh(base_mass * Decimal(INCLUDED_PIECES[size])
              / Decimal(CUP_REFERENCE_MASS_GRAMS[size]))


def overage_band(order, pieces):
    """cup_fill_overage_band: exactly INCLUDED_PIECES is inside the flat price."""
    size = order["cup_size"]
    included = INCLUDED_PIECES[size]
    if pieces <= included:
        return 0
    overage_pieces = pieces - included
    return rh(Decimal(overage_pieces) * Decimal(OVERAGE_BAND_CENTS[size])
              / Decimal(included))


def cup_fill_set_price(order, pieces, store):
    """cup_fill_set_price: bucket base + band, halved at a RESTRICTED store."""
    size = order["cup_size"]
    included = INCLUDED_PIECES[size]
    if pieces <= included:
        bucket = included
    else:
        bucket = included + overage_band(order, pieces)
    if store["stage"] == "RESTRICTED":
        bucket = rh(Decimal(bucket) / Decimal(RESTRICTED_SURCHARGE_DIVISOR))
    return bucket


def per_piece_price(order):
    """per_piece_price: subtotal, then the band keyed on the declared count, then sum."""
    count = int(order.get("declared_piece_count") or 0)
    subtotal = count * PER_PIECE_UNIT_CENTS
    band = PER_PIECE_SURCHARGE_BAND if count >= PER_PIECE_SURCHARGE_THRESHOLD else 0
    return subtotal + band


def base_price(order, store, variant):
    if order["pricing_model"] == "PER_PIECE":
        return per_piece_price(order)
    return cup_fill_set_price(order, inferred_pieces(order, variant), store)


def member_price(base, member, has_launch, variant):
    """member_price_with_launch_surcharge -- round after the discount, again after the surcharge."""
    rate = VIP_DISCOUNT_PCT if member["tier"] == "VIP" else STANDARD_DISCOUNT_PCT
    member_discount = rh(Decimal(base) * Decimal(str(rate)))
    discounted = base - member_discount
    if not has_launch:
        return member_discount, discounted
    if variant == "PRE_DISCOUNT":
        gross = rh(Decimal(base) * (Decimal("1") + Decimal(str(LAUNCH_SURCHARGE_PCT))))
        return member_discount, gross - member_discount
    return member_discount, rh(Decimal(discounted) * (Decimal("1") + Decimal(str(LAUNCH_SURCHARGE_PCT))))


def price_order(order, store, member, variant, has_launch):
    """Compute priced_piece_count / base / discount / final for a checkout."""
    if order["pricing_model"] == "PER_PIECE":
        pieces = int(order.get("declared_piece_count") or 0)
    else:
        pieces = inferred_pieces(order, variant)
    base = base_price(order, store, variant)
    discount, final = member_price(base, member, has_launch, variant)
    return {"priced_piece_count": pieces,
            "base_price_cents": base,
            "member_discount_cents": discount,
            "final_price_cents": final}


def cup_capacity_breach(order, store):
    """Which capacity ceiling a CUP_FILL cup breaches, if any.

    Returns "RESTRICTED" when the cup is over the narrow envelope a restricted
    store enforces, "CAPACITY" when it is over its size's own build capacity,
    and None when the weighed mass is admissible.
    """
    if order["pricing_model"] != "CUP_FILL":
        return None
    size = order["cup_size"]
    mass = order["declared_mass_grams"]

    if store["stage"] == "RESTRICTED":
        narrow = CUP_CAPACITY_GRAMS.get(size)
        if narrow is not None and mass > narrow:
            return "RESTRICTED"
        return None

    standard = STANDARD_CUP_CAPACITY_GRAMS.get(size)
    if standard is not None and mass > standard:
        return "CAPACITY"
    return None