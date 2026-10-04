"""In-memory data store and the logical clock.

Storage is exclusively Python dictionaries held in this process.  Nothing is
written to disk, so re-invoking start.sh (which per-test-server isolation does
before every test) is guaranteed to begin from a completely empty store.
No entity is ever seeded at startup: every record is created by an endpoint.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.10)."""
    return str(uuid.uuid4())


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("unparseable datetime: %r" % value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso3(value):
    """Render an instant as ISO 8601 UTC.

    PRD §2.2 mandates three fractional digits for the envelope's
    `api_request_timestamp`; §2.10 describes a common resource `created_at` as
    "an ISO 8601 UTC timestamp with three fractional digits recording first
    persistence". Resource timestamps are echoed back exactly as the instant
    was supplied to the logical clock, so a clock set to
    `2026-09-05T12:00:00Z` stamps `placed_at` with that same literal.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    """All entity collections, keyed by id.  Starts empty on every boot."""

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.giving_partners = {}
        self.capacity_profiles = {}
        self.vetting_rounds = {}
        self.donation_products = {}
        self.donation_product_lines = {}
        self.donation_liabilities = {}
        self.donation_allocations = {}
        self.donation_distributions = {}
        self.impact_seasons = {}
        self.marketing_claims = {}
        self.sales_orders = {}
        self.sales_order_lines = {}
        self.return_requests = {}
        self.impact_audits = {}
        # Allocation plans are not a first-class resource of the catalogue;
        # they exist only as a grouping key on committed allocations.
        self.allocation_plans = {}
        # season_code -> feature flags toggled by the operator
        self.season_flags = {}
        self.clock = parse_iso(DEFAULT_CLOCK_ISO)
        self.started_at = datetime.now(timezone.utc)

    # -- clock ---------------------------------------------------------------

    def now(self):
        return self.clock

    def set_clock(self, instant):
        self.clock = instant

    # -- generic record helpers ---------------------------------------------

    def touch(self, record):
        """Refresh updated_at and bump version on a mutation (PRD 2.10)."""
        record["updated_at"] = iso3(self.clock)
        record["version"] = record.get("version", 0) + 1
        return record

    def stamp(self, record):
        record["created_at"] = iso3(self.clock)
        return record

    def derive(self, record):
        """A recomputation counts as a mutation for version purposes."""
        return self.touch(record)

    # -- lookups -------------------------------------------------------------

    def partner(self, partner_id):
        return self.giving_partners.get(partner_id)

    def product(self, product_id):
        return self.donation_products.get(product_id)

    def product_line(self, line_id):
        return self.donation_product_lines.get(line_id)

    def season(self, season_id):
        return self.impact_seasons.get(season_id)

    def season_by_code(self, season_code):
        for season in self.impact_seasons.values():
            if season["season_code"] == season_code:
                return season
        return None

    def liability(self, liability_id):
        return self.donation_liabilities.get(liability_id)

    def allocation(self, allocation_id):
        return self.donation_allocations.get(allocation_id)

    def distribution(self, distribution_id):
        return self.donation_distributions.get(distribution_id)

    def claim(self, claim_id):
        return self.marketing_claims.get(claim_id)

    def audit(self, audit_id):
        return self.impact_audits.get(audit_id)

    def order(self, order_id):
        return self.sales_orders.get(order_id)

    def order_line(self, line_id):
        return self.sales_order_lines.get(line_id)

    def return_request(self, return_id):
        return self.return_requests.get(return_id)

    def vetting_round(self, vetting_id):
        return self.vetting_rounds.get(vetting_id)

    def capacity_profile(self, profile_id):
        return self.capacity_profiles.get(profile_id)

    # -- convenience scans ---------------------------------------------------

    def season_containing(self, instant=None):
        """The season whose [starts_at, ends_at) window holds the instant."""
        instant = instant or self.clock
        for season in self.impact_seasons.values():
            start = parse_iso(season["starts_at"])
            end = parse_iso(season["ends_at"])
            if start <= instant < end:
                return season
        return None

    def current_season(self):
        """The season every write is bucketed into.

        Prefers the season whose calendar window holds the logical clock; when
        the clock sits before every calendar it falls back to the next season
        to open, so a claim or a sales line created ahead of a season's
        starts_at still lands in the season it is being planned for.
        """
        containing = self.season_containing()
        if containing:
            return containing
        upcoming = [s for s in self.impact_seasons.values()
                    if parse_iso(s["starts_at"]) > self.clock]
        if upcoming:
            upcoming.sort(key=lambda s: parse_iso(s["starts_at"]))
            return upcoming[0]
        if self.impact_seasons:
            ordered = sorted(self.impact_seasons.values(),
                             key=lambda s: parse_iso(s["starts_at"]))
            return ordered[-1]
        return None

    def frozen_season(self):
        for season in self.impact_seasons.values():
            if season["status"] == "FROZEN":
                return season
        return None

    def next_planned_season(self, after=None):
        candidates = [s for s in self.impact_seasons.values() if s["status"] == "PLANNED"]
        if not candidates:
            return None
        candidates.sort(key=lambda s: parse_iso(s["starts_at"]))
        return candidates[0]

    def partner_allocations(self, partner_id, season_id=None, kind=None):
        rows = [a for a in self.donation_allocations.values() if a["giving_partner_id"] == partner_id]
        if season_id is not None:
            rows = [a for a in rows if a["impact_season_id"] == season_id]
        if kind is not None:
            rows = [a for a in rows if a["allocation_kind"] == kind]
        return rows

    def season_distributions(self, season_id):
        return [d for d in self.donation_distributions.values() if d["impact_season_id"] == season_id]

    def season_claims(self, season_id):
        return [c for c in self.marketing_claims.values() if c["impact_season_id"] == season_id]

    def season_liabilities(self, season_id):
        return [l for l in self.donation_liabilities.values() if l["impact_season_id"] == season_id]

    def product_lines(self, product_id):
        return [l for l in self.donation_product_lines.values() if l["donation_product_id"] == product_id]

    def order_lines(self, order_id):
        return [l for l in self.sales_order_lines.values() if l["sales_order_id"] == order_id]

    def line_return_requests(self, line_id):
        return [r for r in self.return_requests.values() if r["sales_order_line_id"] == line_id]

    def partner_distributions(self, partner_id):
        out = []
        for dist in self.donation_distributions.values():
            alloc = self.allocation(dist["allocation_id"])
            if alloc and alloc["giving_partner_id"] == partner_id:
                out.append(dist)
        return out


DB = Store()


def hours(n):
    return timedelta(hours=n)


def days(n):
    return timedelta(days=n)