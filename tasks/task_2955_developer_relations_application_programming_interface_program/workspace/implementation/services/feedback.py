"""Feedback roadmap prioritisation: raw impact, demand index, re-scoring."""
from decimal import Decimal

from constants import (
    COUNTED_FEEDBACK_STATES,
    DEMAND_INDEX_DIVISOR,
    DEMAND_INDEX_UPLIFT_CAP,
    FEEDBACK_CERT_BONUS,
    FEEDBACK_SEVERITY_WEIGHT,
    FEEDBACK_TIER_WEIGHT,
)
from db import store

from .common import money2


def raw_impact_for(item, developer):
    severity = FEEDBACK_SEVERITY_WEIGHT[item["category"]]
    tier_weight = FEEDBACK_TIER_WEIGHT[item["author_top_tier"]]
    bonus = FEEDBACK_CERT_BONUS[developer["certification_level"]]
    return money2(severity * tier_weight + bonus)


def counted_items(product_id):
    return [
        item
        for item in store.ordered(store.feedback_items)
        if item["api_product_id"] == product_id
        and item["state"] in COUNTED_FEEDBACK_STATES
    ]


def demand_index_for(product_id):
    total = Decimal(0)
    for item in counted_items(product_id):
        if item["raw_impact"] is not None:
            total += Decimal(item["raw_impact"])
    return money2(total)


def demand_factor(demand_index):
    uplift = Decimal(demand_index) / DEMAND_INDEX_DIVISOR
    if uplift > DEMAND_INDEX_UPLIFT_CAP:
        uplift = DEMAND_INDEX_UPLIFT_CAP
    return Decimal(1) + uplift


def rescore_product(product, exclude_item_id=None):
    """Ledger-wide recomputation of demand_index and every priority_score."""
    index = demand_index_for(product["id"])
    if product["demand_index"] != index:
        product["demand_index"] = index
        store.touch(product)
    factor = demand_factor(index)
    for item in counted_items(product["id"]):
        score = money2(Decimal(item["raw_impact"]) * factor)
        if item["priority_score"] != score:
            item["priority_score"] = score
            if item["id"] != exclude_item_id:
                store.touch(item)
    return index


def roadmap_ordered(product_id):
    items = counted_items(product_id)
    items.sort(
        key=lambda i: (
            -Decimal(i["priority_score"] if i["priority_score"] is not None else 0),
            -Decimal(i["raw_impact"] if i["raw_impact"] is not None else 0),
            i["created_at"],
            i["_seq"],
        )
    )
    return items
