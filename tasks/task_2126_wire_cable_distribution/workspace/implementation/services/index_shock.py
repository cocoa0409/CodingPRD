"""The copper index publication cascade (PRD Section 3.2)."""
import db
import calculations as calc
from services import allocation as allocation_svc
from services import lookup


def candidate_quotes():
    """ISSUED quotes, plus CONVERTED quotes whose order is still physically
    uncommitted.  Evaluated in ascending Quote.created_at."""
    rows = []
    for quote in db.quotes.values():
        if quote["status"] == "ISSUED":
            rows.append(quote)
        elif quote["status"] == "CONVERTED":
            orders = lookup.orders_of_quote(quote["id"])
            if any(o["fulfillment_status"] in ("PENDING_ALLOCATION", "PARTIALLY_ALLOCATED", "HELD")
                   for o in orders):
                rows.append(quote)
    return sorted(rows, key=db.sort_key)


def run_index_shock(new_entry):
    """Cascade links 1, 2 and 3 of a copper index publication."""
    voided = 0
    for quote in candidate_quotes():
        pinned = db.copper_index_entries.get(quote["copper_index_entry_id"])
        if pinned is None:
            continue
        if not calc.is_index_shock(new_entry, pinned):
            continue

        # --- Cascade link 1 ---------------------------------------------
        quote["status"] = "VOIDED"
        quote["void_reason"] = "INDEX_SHOCK"
        db.touch(quote)
        voided += 1

        # --- Cascade link 2 ---------------------------------------------
        for order in lookup.orders_of_quote(quote["id"]):
            if order["fulfillment_status"] not in ("PENDING_ALLOCATION", "PARTIALLY_ALLOCATED", "HELD"):
                continue
            order["fulfillment_status"] = "CANCELLED"
            order["billing_status"] = "VOIDED"
            db.touch(order)

            # --- Cascade link 3 -----------------------------------------
            for alloc in lookup.allocations_of_order(order["id"]):
                if alloc["status"] == "RESERVED":
                    allocation_svc.release_allocation(alloc)

    new_entry["voided_quote_count"] = voided
    return voided
