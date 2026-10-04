"""In-memory data store. Keyed by id. Nothing is seeded at boot."""
import uuid
from datetime import datetime
from decimal import Decimal

from clock import CLOCK_START, fmt

FULL_SET = True
LIGHT = False


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_START
        self.publishers = {}
        self.titles = {}
        self.regions = {}
        self.tiers = {}
        self.deals = {}
        self.entries = {}
        self.maintenances = {}
        self.subscribers = {}
        self.subscriptions = {}
        self.entitlements = {}
        self.events = {}
        self.purchases = {}
        self.projections = {}
        # insertion-order ledger, used as the created_at tie-break
        self.seq = 0
        self.order = {}

    def next_seq(self):
        self.seq += 1
        return self.seq

    # ---- row construction -------------------------------------------------
    def new_row(self, full=True):
        rid = str(uuid.uuid4())
        stamp = fmt(self.clock)
        row = {"id": rid, "created_at": stamp}
        if full:
            row["updated_at"] = stamp
            row["version"] = 1
        row["_seq"] = self.next_seq()
        return row

    def touch(self, row):
        """Any mutation advances updated_at and bumps version (PRD 2.5)."""
        if "updated_at" in row:
            row["updated_at"] = fmt(self.clock)
            row["version"] = row.get("version", 0) + 1

    # ---- collections ------------------------------------------------------
    def collections(self):
        return {
            "Publisher": self.publishers,
            "Title": self.titles,
            "Region": self.regions,
            "SubscriptionTier": self.tiers,
            "LicensingDeal": self.deals,
            "CatalogEntry": self.entries,
            "CatalogMaintenance": self.maintenances,
            "Subscriber": self.subscribers,
            "Subscription": self.subscriptions,
            "Entitlement": self.entitlements,
            "EngagementEvent": self.events,
            "Purchase": self.purchases,
            "AvailabilityProjection": self.projections,
        }

    def public(self, row):
        """Render a row for the wire: drop bookkeeping keys, format instants."""
        out = {}
        for key, value in row.items():
            if key.startswith("_"):
                continue
            if isinstance(value, datetime):
                out[key] = fmt(value)
            elif isinstance(value, Decimal):
                out[key] = float(value)
            else:
                out[key] = value
        return out

    def sorted_rows(self, table):
        return sorted(table.values(), key=lambda r: (r["created_at"], r["_seq"]))


db = Store()
