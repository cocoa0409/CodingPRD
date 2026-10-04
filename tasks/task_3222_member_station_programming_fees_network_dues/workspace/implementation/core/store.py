"""In-memory storage. Every collection starts empty on a fresh boot.

No seeding, no preloading, no module-level records: the harness restarts the
server before each test and every precondition is built through the API.
"""


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.member_stations = {}
        self.schedules = {}
        self.agreements = {}
        self.windows = {}
        self.feeds = {}
        self.slots = {}
        self.underwriting = {}
        self.contributions = {}
        self.drives = {}
        self.audience_reports = {}
        self.programs = {}
        self.elections = {}
        self.candidates = {}
        self.seats = {}
        self.proposals = {}
        self.votes = {}
        self.assessments = {}
        self.projections = {}
        # Discretionary bookkeeping the API does not expose as a resource.
        self.frozen_stations = set()
        self.matched_budget = {}

    # -- generic accessors ---------------------------------------------------
    def coll(self, name):
        return getattr(self, name)

    def get(self, name, ident):
        return getattr(self, name).get(ident)

    def put(self, name, rec):
        getattr(self, name)[rec["id"]] = rec
        return rec

    def all(self, name):
        return list(getattr(self, name).values())

    def by(self, name, **filters):
        out = []
        for rec in getattr(self, name).values():
            ok = True
            for key, want in filters.items():
                if want is None:
                    continue
                if rec.get(key) != want:
                    ok = False
                    break
            if ok:
                out.append(rec)
        return out

    # -- domain helpers ------------------------------------------------------
    def window(self, window_id):
        return self.windows.get(window_id)

    def windows_of(self, agreement_id):
        return [
            w for w in self.windows.values()
            if w.get("parent_agreement_id") == agreement_id
        ]

    def slots_of(self, feed_id):
        return [
            s for s in self.slots.values()
            if s.get("parent_feed_id") == feed_id
        ]

    def slots_for_window(self, window_id):
        return [
            s for s in self.slots.values()
            if s.get("window_id") == window_id
        ]

    def projection_for(self, station_id, fiscal_year=None):
        rows = [
            p for p in self.projections.values()
            if p.get("station_id") == station_id
            and (fiscal_year is None or p.get("fiscal_year") == fiscal_year)
        ]
        if not rows:
            return None
        rows.sort(key=lambda p: p.get("last_projected_at") or "")
        return rows[-1]

    def proposals_for_station_region(self, station):
        out = []
        for prop in self.proposals.values():
            scope = prop.get("board_region")
            if scope is None or scope == station.get("board_seat_region"):
                out.append(prop)
        return out

    def eligible_voter_count(self):
        count = 0
        for st in self.member_stations.values():
            if projection_eligible(st):
                count += 1
        return count

    def active_proposals(self):
        return [
            p for p in self.proposals.values()
            if p.get("proposal_status") in ("OPEN", "TABLED", "PASSED")
        ]


def projection_eligible(station):
    """The derived dues_vote_eligible mirror: ELIGIBLE/PROBATION and in force."""
    from core import config as C
    if station is None:
        return False
    if station.get("eligibility_status") not in ("ELIGIBLE", "PROBATION"):
        return False
    ef = C.parse_dt(station.get("eligible_from"))
    if ef is None:
        return False
    return ef <= C.now()


STORE = Store()