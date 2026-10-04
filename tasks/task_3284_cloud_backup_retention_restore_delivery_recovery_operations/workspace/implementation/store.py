"""In-memory state.  Nothing is seeded: every boot starts empty (PRD 2.4).

All twelve entity collections are plain dicts keyed by the server-minted raw
UUID `id`.  FileVersion is immutable and carries no version/updated_at.
"""

import uuid
from datetime import datetime, timezone

from util import DEFAULT_CLOCK_UTC, parse_instant


class Store(object):
    def __init__(self):
        self.reset()

    # -- lifecycle -----------------------------------------------------------
    def reset(self):
        self.clock = parse_instant(DEFAULT_CLOCK_UTC)   # PRD 2.5 default
        self.clock_set = False
        self.clock_token = 0          # bumped on every clock move
        self.refreshed_token = -1     # last token the derived state reflects
        self.request_counter = 0

        self.accounts = {}
        self.groups = {}
        self.policies = {}
        self.agents = {}
        self.sets = {}
        self.versions = {}
        self.restores = {}
        self.shipments = {}
        self.periods = {}
        self.pods = {}
        self.retention_changes = {}
        self.deletions = {}

        # monotonic sequence sources (created_seq, not a global orderer)
        self.group_seq = {}
        self.set_seq = {}
        self.pod_seq = 0
        self.order = 0        # insertion order used as the created_at tie-break

    # -- clock ---------------------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, instant):
        self.clock = instant
        self.clock_token += 1

    def tick(self):
        """Advance the internal insertion counter; keeps created_at ordering
        monotonic inside a single logical instant so the `earliest created_at`
        tie-breaks are deterministic."""
        self.order += 1
        return self.order

    def next_group_seq(self, account_id):
        nxt = self.group_seq.get(account_id, 0) + 1
        self.group_seq[account_id] = nxt
        return nxt

    def next_set_seq(self, agent_id):
        nxt = self.set_seq.get(agent_id, 0) + 1
        self.set_seq[agent_id] = nxt
        return nxt

    def next_pod_seq(self):
        self.pod_seq += 1
        return self.pod_seq

    def new_id(self):
        return str(uuid.uuid4())

    def request_id(self):
        self.request_counter += 1
        return "req_" + uuid.uuid4().hex[:20].upper()

    # -- collection helpers --------------------------------------------------
    def all_versions_of_set(self, set_id):
        rows = [v for v in self.versions.values() if v["backup_set_id"] == set_id]
        return sorted(rows, key=lambda v: (v["_order"], v["_seq"]))

    def all_versions_of_account(self, account_id):
        set_ids = {s["id"] for s in self.sets.values() if s["account_id"] == account_id}
        return [v for v in self.versions.values() if v["backup_set_id"] in set_ids]

    def sets_of_account(self, account_id):
        return [s for s in self.sets.values() if s["account_id"] == account_id]

    def sets_of_agent(self, agent_id):
        return [s for s in self.sets.values() if s["agent_id"] == agent_id]

    def groups_of_account(self, account_id):
        rows = [g for g in self.groups.values() if g["account_id"] == account_id]
        # PRD 3.2: ascending created_seq, ties by earliest created_at, never id.
        return sorted(rows, key=lambda g: (g["created_seq"], g["created_at"], g["_order"]))

    def agents_of_group(self, group_id):
        return [a for a in self.agents.values() if a["group_id"] == group_id]

    def agents_of_account(self, account_id):
        return [a for a in self.agents.values() if a["account_id"] == account_id]

    def policies_of_group(self, group_id):
        return [p for p in self.policies.values() if p["group_id"] == group_id]

    def active_policy(self, group_id, kind="RETENTION"):
        for p in self.policies.values():
            if p["group_id"] == group_id and p["policy_kind"] == kind and p["status"] == "ACTIVE":
                return p
        return None

    def periods_of_account(self, account_id):
        return [p for p in self.periods.values() if p["account_id"] == account_id]

    def shipments_of_account(self, account_id):
        return [s for s in self.shipments.values() if s["account_id"] == account_id]

    def shipments_of_restore(self, restore_id):
        return [s for s in self.shipments.values()
                if s["restore_request_id"] == restore_id]


store = Store()


def new_common(store, created=True):
    """Field block shared by the eleven mutable entities (PRD 2.4)."""
    return {}