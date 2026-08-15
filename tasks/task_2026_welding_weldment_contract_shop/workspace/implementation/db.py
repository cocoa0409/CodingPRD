"""In-memory data store. Starts completely empty on every boot — no seeding."""

import itertools
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.shops = {}
        self.welders = {}
        self.ndt_vendors = {}
        self.ovens = {}
        self.pqrs = {}
        self.wps = {}
        self.qualifications = {}
        self.lots = {}
        self.issues = {}
        self.fixtures = {}
        self.orders = {}
        self.weldments = {}
        self.joints = {}
        self.weld_passes = {}
        self.distortion_reports = {}
        self.inspections = {}
        self.sign_offs = {}
        # monotonic insertion sequence for stable created_at tie-breaking
        self.seq = itertools.count(1)


db = Store()
