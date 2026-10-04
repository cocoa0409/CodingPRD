"""§3.7 Cold-Chain Selection and Packing."""

import rules
import store
from services import builds


def lane_posture(center_id):
    center = store.FULFILLMENT_CENTERS.get(center_id)
    if center is None:
        return "OPEN"
    return center.get("forward_posture", "OPEN")


def pack_for(order):
    """Create exactly one ColdChainPack for the order."""
    center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
    items = builds.included_items(order["id"])
    order["_forward_posture"] = lane_posture(order["fulfillment_center_id"])
    selection = rules.cold_chain_selection(order, items)
    pack = store.new_row({
        "box_order_id": order["id"],
        "lane_fulfillment_center_id": order["fulfillment_center_id"],
        "cold_item_weight_grams": selection["cold_item_weight_grams"],
        "insulation_grade": selection["insulation_grade"],
        "coolant_units": selection["coolant_units"],
        "lane_transit_days": selection["lane_transit_days"],
        "selection_status": selection["selection_status"],
    }, immutable=True)
    store.COLD_CHAIN_PACKS[pack["id"]] = pack
    return pack


def recompute_for_orders(orders, bump=True):
    """§3.5: a degraded lane recomputes transit days and re-selects the load."""
    for order in orders:
        for pack in store.COLD_CHAIN_PACKS.values():
            if pack["box_order_id"] != order["id"]:
                continue
            items = builds.included_items(order["id"])
            order["_forward_posture"] = lane_posture(order["fulfillment_center_id"])
            selection = rules.cold_chain_selection(order, items)
            for key in ("cold_item_weight_grams", "insulation_grade",
                        "coolant_units", "lane_transit_days", "selection_status"):
                pack[key] = selection[key]