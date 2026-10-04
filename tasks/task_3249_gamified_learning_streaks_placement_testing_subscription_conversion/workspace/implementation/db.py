"""In-memory data store. Every collection is a dict keyed by entity id.

The store starts empty on every boot: nothing is seeded, preloaded or hardcoded.
Every entity a caller needs is constructed through a declared endpoint.
"""


class Store:
    def __init__(self):
        self.learners = {}
        self.subscriptions = {}
        self.family_memberships = {}
        self.course_units = {}
        self.lesson_nodes = {}
        self.practice_attempts = {}
        self.streak_states = {}
        self.placement_tests = {}
        self.leagues = {}
        self.league_standings = {}
        self.certification_exams = {}
        self.score_reports = {}
        self.engagement_offers = {}


STORE = Store()