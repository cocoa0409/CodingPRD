"""In-memory data store.

Storage is process-local only: plain dictionaries keyed by id.  There is no
SQLite file, no JSON dump, no /tmp cache and no external persistence of any
kind, so re-invoking `start.sh` yields a completely empty store.

Nothing is seeded here.  `STORE` starts empty on every boot and every entity is
constructed by a client through the declared API surface.
"""

import threading
import uuid

from clock import LogicalClock

class Store:
    """All server state, held in dictionaries keyed by id."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = LogicalClock()

        # --- entity collections (id -> row) ---
        self.industry_categories = {}
        self.merchants = {}
        self.declined_attempts = {}
        self.acceptance_gaps = {}
        self.sweep_index_stamps = {}
        self.offers = {}
        self.cardmembers = {}
        self.offer_acceptances = {}
        self.offer_redemption_pools = {}
        self.annual_fee_statements = {}
        self.value_fund_ledger_entries = {}
        self.settlements = {}
        self.disputes = {}
        self.acceptance_complaints = {}
        self.merchant_risk_states = {}

        # --- secondary indexes ---
        self.merchants_by_name = {}
        self.industry_categories_by_code = {}
        self.risk_states_by_merchant = {}
        self.pools_by_offer = {}

        # --- monotone counters (deterministic ordering, never a wall clock) ---
        self.created_seq_counter = 0
        self.next_funding_batch_seq = {}
        self.last_finalized_batch_seq = {}
        self.last_batch_discount_fee_cents = {}
        # The LATEST stamped sweep generation (PRD §3.2), not the maximum: the
        # stamp supplied most recently is the generation the engine reads.
        self.latest_sweep_index = 0

    # -- id / common field minting -----------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_created_seq(self):
        self.created_seq_counter += 1
        return self.created_seq_counter

    def output_fields(self, row):
        """The fields returned for a row.

        Every field the client may see is returned, with two deliberate
        omissions.  Keys prefixed with an underscore are private bookkeeping (the
        creation-sequence tie-break) and never leave the server.  `version` and
        `updated_at` are omitted on the append-only evidence records
        (DeclinedAttempt and SweepIndexStamp), which are never modified after
        creation and therefore never carry either.  Date fields are rendered as
        ISO 8601 UTC strings.
        """
        out = {}
        for key, value in row.items():
            if key.startswith("_"):
                continue
            out[key] = value
        # The two append-only evidence records carry only `id` and `created_at`:
        # neither has an `updated_at` and neither has a `version`, because
        # neither is ever modified after creation (PRD §2.4).
        if row.get("_append_only"):
            out.pop("version", None)
            out.pop("updated_at", None)
        for stamp in ("created_at", "updated_at", "occurred_at", "rolled_at",
                      "live_start_utc", "live_end_utc", "window_start", "window_end"):
            if out.get(stamp) is not None and not isinstance(out[stamp], str):
                out[stamp] = _iso(out[stamp])
        return out

    # -- merchant-scoped accessors -----------------------------------------
    def risk_state_for(self, merchant_id):
        return self.merchant_risk_states.get(self.risk_states_by_merchant.get(merchant_id))

    def pool_for_offer(self, offer_id):
        return self.offer_redemption_pools.get(self.pools_by_offer.get(offer_id))

    def settlements_for(self, merchant_id):
        return [s for s in self.settlements.values() if s["merchant_id"] == merchant_id]

    def offers_for(self, merchant_id):
        return [o for o in self.offers.values() if o["merchant_id"] == merchant_id]


def _iso(dt):
    from clock import format_iso

    return format_iso(dt)


# The one and only store.  Empty at import time.
STORE = Store()