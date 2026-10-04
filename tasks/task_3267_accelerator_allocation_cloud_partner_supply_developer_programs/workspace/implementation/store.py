"""In-memory data store, logical clock and common-field minting.

The store starts empty on every boot.  The only row created at start-up is the
first AllocationEpoch, which is the system's posture: the scaffold's epoch
collection opens at index 0 with no prior advance, and the PRD makes an open
epoch a precondition of every allocation-creating call (PRD 2.12 item 11), so a
forest of harnesses that never call /_ops/advance_epoch still has one.
"""

from util import format_utc, initial_clock, new_id, parse_utc


class Store(object):
    def __init__(self):
        self.clock = initial_clock()
        self.seq = 0
        self.partners = {}
        self.products = {}
        self.nodes = {}
        self.blueprints = {}
        self.holds = {}
        self.evidences = {}
        self.subscriptions = {}
        self.deployments = {}
        self.stack_licenses = {}
        self.memberships = {}
        self.grants = {}
        self.acks = {}
        self.forecasts = {}
        self.loans = {}
        self.milestones = {}
        self.commitments = {}
        self.penalties = {}
        self.epochs = {}
        self.audits = {}
        self.export_grants = {}
        self.contracts = {}
        self.license_hold_groups = {}
        self.license_holds = {}
        self.deployment_groups = {}

        epoch = self.mint(
            {
                "epoch_index": 0,
                "opened_at": format_utc(self.clock),
                "half_life_next": "COOL",
                "epoch_status": "OPEN",
            }
        )
        self.epochs[epoch["id"]] = epoch

    # ------------------------------------------------------------- clock ---
    def now_text(self):
        return format_utc(self.clock)

    def set_clock(self, value):
        self.clock = parse_utc(value)
        return self.clock

    # --------------------------------------------------------- row minting --
    def mint(self, fields):
        """Build a row with the full common-field set (PRD 2.10)."""
        self.seq += 1
        row = {"id": new_id(), "_seq": self.seq}
        stamp = self.now_text()
        row["created_at"] = stamp
        row["updated_at"] = stamp
        row["version"] = 1
        row.update(fields)
        return row

    def touch(self, row, bump=True):
        """Refresh updated_at, and version unless the caller already bumped it."""
        row["updated_at"] = self.now_text()
        if bump:
            row["version"] = int(row.get("version", 1)) + 1
        return row

    def bump(self, row):
        """Record an explicit version increment; touch() will not double it."""
        row["version"] = int(row.get("version", 1)) + 1
        row["updated_at"] = self.now_text()
        return row

    # ------------------------------------------------------------ lookups --
    def open_epoch(self):
        for epoch in self.epochs.values():
            if epoch.get("epoch_status") == "OPEN":
                return epoch
        return None

    def current_epoch_index(self):
        open_epoch = self.open_epoch()
        if open_epoch is not None:
            return int(open_epoch.get("epoch_index", 0))
        if self.epochs:
            return max(int(e.get("epoch_index", 0)) for e in self.epochs.values())
        return 0

    def find(self, collection, row_id):
        return getattr(self, collection).get(row_id)


DB = Store()


def reset():
    """Used by nothing at runtime; kept for local experimentation only."""
    global DB
    DB = Store()
    return DB