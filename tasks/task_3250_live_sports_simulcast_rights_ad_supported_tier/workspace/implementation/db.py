"""In-memory data store. Empty at boot; tests build all state via the API."""

COLLECTIONS = [
    "properties",
    "windows",
    "territory_rules",
    "viewers",
    "view_grants",
    "capacity_pools",
    "capacity_reservations",
    "ad_campaigns",
    "ad_slots",
    "impressions",
    "partners",
    "promo_codes",
    "entitlements",
    "replay_assets",
]


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})


db = Store()
