"""The two bubble-up rules of PRD 2.8.

They run at the end of every request that could satisfy them rather than being
triggered by a particular endpoint.
"""

from store import db, set_field
from util import parse_date

TERMINAL_DONATION = ("PASTEURIZED", "RECALLED", "DISCARDED")


def bubble_up():
    for shipment in db.rows("shipments"):
        if shipment["status"] != "ACCEPTED":
            continue
        containers = [d for d in db.rows("donations") if d["shipment_id"] == shipment["id"]]
        if containers and all(d["status"] in TERMINAL_DONATION for d in containers):
            set_field(shipment, "status", "CLOSED")

    today = db.clock_date()
    for lot in db.rows("lots"):
        status = lot["release_status"]
        if status == "RELEASED" and lot["available_ml"] <= 0:
            set_field(lot, "release_status", "EXHAUSTED")
        elif status == "EXHAUSTED" and lot["available_ml"] > 0:
            expiry = parse_date(lot["expiration_date"])
            if expiry is not None and expiry >= today:
                set_field(lot, "release_status", "RELEASED")
