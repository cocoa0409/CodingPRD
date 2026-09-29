"""In-memory data store and the logical plant clock (PRD sections 2.4, 2.5).

Storage is plain Python dicts, process-local, and starts completely empty on
every boot.  Nothing is seeded, preloaded or persisted.
"""

import itertools
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from envelope import iso_millis
from errors import ApiError

# ---------------------------------------------------------------- logical clock

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_ISO_INSTANT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class LogicalClock(object):
    """Single logical clock.  Never falls back to wall-clock time."""

    def __init__(self):
        self.current = CLOCK_DEFAULT
        self.raw = "2026-08-01T00:00:00Z"

    def now(self):
        return self.current

    def today(self):
        return self.current.astimezone(timezone.utc).date()

    def year(self):
        return self.today().year

    def today_str(self):
        return self.today().isoformat()

    def set(self, dt, raw):
        self.current = dt.astimezone(timezone.utc)
        self.raw = raw


def parse_instant(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_INSTANT.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzs = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tzs in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if tzs[0] == "+" else -1
    body = tzs[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * offset).replace(tzinfo=timezone.utc)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date.  Returns None when invalid."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ------------------------------------------------------------------- the store

ENTITY_NOT_FOUND = {
    "standard": "ERR_STANDARD_NOT_FOUND",
    "model": "ERR_MODEL_NOT_FOUND",
    "project": "ERR_PROJECT_NOT_FOUND",
    "area": "ERR_PLAY_AREA_NOT_FOUND",
    "placement": "ERR_PLACEMENT_NOT_FOUND",
    "rendering": "ERR_RENDERING_NOT_FOUND",
    "quote": "ERR_QUOTE_NOT_FOUND",
    "pledge": "ERR_PLEDGE_NOT_FOUND",
    "order": "ERR_ORDER_NOT_FOUND",
    "installer": "ERR_INSTALLER_NOT_FOUND",
    "job": "ERR_JOB_NOT_FOUND",
    "claim": "ERR_CLAIM_NOT_FOUND",
}

_COLLECTIONS = (
    "standard",
    "model",
    "project",
    "area",
    "placement",
    "rendering",
    "quote",
    "pledge",
    "order",
    "installer",
    "job",
    "inspection",
    "claim",
)


class Store(object):
    def __init__(self):
        self.clock = LogicalClock()
        self._seq = itertools.count(1)
        self.data = {}
        for name in _COLLECTIONS:
            self.data[name] = {}

    # -- creation / mutation helpers -------------------------------------

    def new_id(self):
        return str(uuid.uuid4())

    def stamp_now(self):
        return iso_millis(datetime.now(timezone.utc))

    def insert(self, kind, fields, versioned=True):
        row = {"id": self.new_id()}
        now = self.stamp_now()
        row["created_at"] = now
        if versioned:
            row["updated_at"] = now
            row["version"] = 1
        row.update(fields)
        row["_seq"] = next(self._seq)
        row["_kind"] = kind
        self.data[kind][row["id"]] = row
        return row

    def touch(self, row):
        """One version increment plus a refreshed updated_at (PRD section 2.4)."""
        if "version" in row:
            row["version"] = row["version"] + 1
            row["updated_at"] = self.stamp_now()
        return row

    def delete(self, kind, row_id):
        self.data[kind].pop(row_id, None)

    # -- lookups ---------------------------------------------------------

    def get(self, kind, row_id):
        if not isinstance(row_id, str):
            return None
        return self.data[kind].get(row_id)

    def require(self, kind, row_id):
        row = self.get(kind, row_id)
        if row is None:
            raise ApiError(ENTITY_NOT_FOUND[kind])
        return row

    def all(self, kind):
        """Every row of a collection in created_at ascending order."""
        return sorted(self.data[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))

    def where(self, kind, **equals):
        rows = []
        for row in self.all(kind):
            if all(row.get(k) == v for k, v in equals.items()):
                rows.append(row)
        return rows

    # -- domain-specific traversals -------------------------------------

    def active_standard(self):
        for row in self.all("standard"):
            if row["status"] == "ACTIVE":
                return row
        return None

    def project_areas(self, project_id):
        return self.where("area", project_id=project_id)

    def area_placements(self, area_id):
        return self.where("placement", play_area_id=area_id)

    def project_placements(self, project_id):
        area_ids = set(a["id"] for a in self.project_areas(project_id))
        return [p for p in self.all("placement") if p["play_area_id"] in area_ids]

    def placement_project(self, placement):
        area = self.get("area", placement["play_area_id"])
        if area is None:
            return None
        return self.get("project", area["project_id"])

    def project_renderings(self, project_id):
        return self.where("rendering", project_id=project_id)

    def project_quotes(self, project_id):
        return self.where("quote", project_id=project_id)

    def project_pledges(self, project_id):
        return self.where("pledge", project_id=project_id)

    def project_orders(self, project_id):
        out = []
        for order in self.all("order"):
            quote = self.get("quote", order["quote_id"])
            if quote is not None and quote["project_id"] == project_id:
                out.append(order)
        return out

    def order_project(self, order):
        quote = self.get("quote", order["quote_id"])
        if quote is None:
            return None
        return self.get("project", quote["project_id"])

    def order_jobs(self, order_id):
        return self.where("job", order_id=order_id)

    def installer_jobs(self, installer_id):
        return self.where("job", installer_id=installer_id)

    def job_inspections(self, job_id):
        rows = self.where("inspection", job_id=job_id)
        return sorted(rows, key=lambda r: r["sequence_number"])

    def job_project(self, job):
        order = self.get("order", job["order_id"])
        if order is None:
            return None
        return self.order_project(order)


store = Store()


def public(row):
    """Public JSON representation: every field except the internal bookkeeping."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]
