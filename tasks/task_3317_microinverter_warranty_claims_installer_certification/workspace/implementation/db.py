"""In-memory data store.

Everything lives in plain dicts keyed by entity id.  There is no database, no
file, no cache directory and no persistence of any kind: re-running start.sh
yields a process whose store is empty, because the store is only ever what this
process built during its own lifetime.

Nothing here is seeded.  The module defines the collections and nothing else --
every row that ever exists is created through a declared endpoint.
"""


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.installers = {}          # id -> Installer
        self.design_projects = {}     # id -> DesignProject
        self.production_lots = {}     # id -> ProductionLot
        self.systems = {}             # id -> SystemRegistration
        self.units = {}               # id -> Unit
        self.claims = {}              # id -> WarrantyClaim
        self.reimbursements = {}      # id -> LaborReimbursement
        self.transfers = {}           # id -> WarrantyTransfer
        self.campaigns = {}           # id -> ProactiveCampaign
        self.replacement_orders = {}  # id -> ReplacementOrder
        self.entitlements = {}        # id -> BillingEntitlement
        self.share_links = {}         # id -> ShareLink
        self.billing_corrections = {} # id -> BillingCorrection
        self.lot_allow_lists = {}     # installer_id -> set(lot_id)


DB = Store()


# ------------------------------------------------------------------ selectors


def all_units_of_system(system_id):
    return [u for u in DB.units.values() if u.get("system_id") == system_id]


def all_units_of_lot(lot_id):
    return [u for u in DB.units.values() if u.get("production_lot_id") == lot_id]


def claims_of_installer(installer_id):
    return [c for c in DB.claims.values() if c.get("installer_id") == installer_id]


def orders_of_claim(claim_id):
    return [o for o in DB.replacement_orders.values() if o.get("claim_id") == claim_id]


def orders_of_campaign(campaign_id):
    return [o for o in DB.replacement_orders.values() if o.get("campaign_id") == campaign_id]


def reimbursements_of_claim(claim_id):
    return [r for r in DB.reimbursements.values() if r.get("claim_id") == claim_id]


def entitlements_of_unit(unit_id):
    return [e for e in DB.entitlements.values() if e.get("unit_id") == unit_id]


def live_orders_of_unit(unit_id):
    """Orders on a unit that have not been canceled -- the duplicate guard."""
    return [o for o in DB.replacement_orders.values()
            if o.get("unit_id") == unit_id and o.get("status") != "CANCELED"]


def active_campaign_for_lot(lot_id):
    for c in DB.campaigns.values():
        if c.get("lot_id") == lot_id and c.get("status") in ("DRAFT", "DISPATCHING"):
            return c
    return None


def by_created_at(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))