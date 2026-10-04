"""In-memory data store. Starts empty on every boot; no seeding."""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.charts = {}
        self.methodology_versions = {}
        self.chart_weeks = {}
        self.providers = {}
        self.title_products = {}
        self.label_accounts = {}
        self.recurrent_rules = {}
        self.consumption_reports = {}
        self.sale_batches = {}
        self.manipulation_signals = {}
        self.investigations = {}
        self.chart_entries = {}
        self.genre_disputes = {}
        self.chart_freezes = {}


db = Store()
