"""In-memory data store and the logical clock.

Nothing here is ever persisted or seeded. Every boot starts from an empty store
and from the fixed startup logical time 2026-09-01T00:00:00Z; the implementation
never falls back to the host machine's wall clock.
"""

from datetime import datetime, timedelta, timezone

# Fixed startup logical instant. Real wall-clock time is never consulted.
STARTUP_UTC = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    """The current logical instant (a timezone-aware UTC datetime)."""
    return STORE.clock


def iso(dt):
    """Render an instant as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant; naive values are read as UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


class Store:
    """All persisted state. Purely in-memory; wiped by every process restart."""

    def __init__(self):
        self.clock = STARTUP_UTC
        self.accounts = {}
        self.clusters = {}
        self.links = {}
        self.trips = {}
        self.incidents = {}
        self.evidence = {}
        self.enforcement_actions = {}
        self.regulator_reports = {}
        self.background_checks = {}
        self.policies = {}
        # Books of account that the contract describes as server-side aggregates.
        self.monthly_report_cap = {}
        self.consumer_report_queue = []
        self._announcements_suppressed = ()
        self._report_windows = []

    # -- addressable lookups -------------------------------------------------
    def policy_for_region(self, region_code):
        if region_code is None:
            return None
        for policy in self.policies.values():
            if policy.get("region_code") == region_code:
                return policy
        return None

    def accounts_in_region(self, region_code):
        return [a for a in self.accounts.values()
                if a.get("home_region_code") == region_code]

    def clusters_in_region(self, region_code):
        return [c for c in self.clusters.values()
                if c.get("region_code") == region_code]

    def checks_in_region(self, region_code):
        out = []
        for check in self.background_checks.values():
            account = self.accounts.get(check.get("account_id"))
            if account and account.get("home_region_code") == region_code:
                out.append(check)
        return out

    # -- derived convenience -------------------------------------------------
    def account_incidents(self, account_id):
        return [i for i in self.incidents.values()
                if i.get("account_id") == account_id]

    def account_actions(self, account_id):
        return [a for a in self.enforcement_actions.values()
                if a.get("account_id") == account_id]

    def account_links(self, account_id):
        return [l for l in self.links.values()
                if l.get("account_id") == account_id]

    def account_checks(self, account_id):
        return [c for c in self.background_checks.values()
                if c.get("account_id") == account_id]

    def account_trips(self, account_id):
        return [t for t in self.trips.values()
                if t.get("rider_account_id") == account_id
                or t.get("driver_account_id") == account_id]

    def cluster_links(self, cluster_id):
        return [l for l in self.links.values()
                if l.get("device_cluster_id") == cluster_id]

    def cluster_member_accounts(self, cluster_id):
        """Every account observed on the cluster, whatever its link status."""
        seen = []
        for link in self.cluster_links(cluster_id):
            aid = link.get("account_id")
            if aid not in seen:
                seen.append(aid)
        return seen

    def incident_for_account_and_region(self, account_id, region_code):
        for report in self.regulator_reports.values():
            incident = self.incidents.get(report.get("incident_id"))
            if incident is None:
                continue
            if incident.get("account_id") != account_id:
                continue
            if report.get("region_code") != region_code:
                continue
            if report.get("report_status") == "FILED":
                return report
        return None

    def reports_for_incident(self, incident_id):
        return [r for r in self.regulator_reports.values()
                if r.get("incident_id") == incident_id]

    def actions_for_incident(self, incident_id):
        return [a for a in self.enforcement_actions.values()
                if a.get("incident_id") == incident_id]

    def action_for_incident(self, incident_id):
        actions = self.actions_for_incident(incident_id)
        return actions[0] if actions else None

    def region_has_policy(self, region_code):
        return self.policy_for_region(region_code) is not None

    # -- regulator filing windows -------------------------------------------
    def report_windows(self):
        return list(self._report_windows)

    def add_report_window(self, region_code, start, close):
        self._report_windows.append((region_code, start, close))

    def close_report_windows(self, region_code):
        self._report_windows = [w for w in self._report_windows
                                if w[0] != region_code]


STORE = Store()