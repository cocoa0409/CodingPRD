"""In-memory data store. Empty on every boot — no seeding ever."""

# Entity collections, keyed by id. Insertion order preserves created_at ordering
# (with identical timestamps ties) because dicts are insertion-ordered.
stations = {}
routes = {}
season_windows = {}
schedule_publications = {}
aircraft = {}
flight_instances = {}
crew_bases = {}
crew_members = {}
crew_assignments = {}
supplier_offers = {}
bookings = {}
package_bundles = {}
ancillary_purchases = {}
disruption_events = {}
supplier_settlements = {}

# Logical clock state. Starts exactly at 2026-09-01T00:00:00Z; never falls
# back to wall-clock time; moves only when explicitly set.
CLOCK_INITIAL = "2026-09-01T00:00:00Z"
current_utc = CLOCK_INITIAL
