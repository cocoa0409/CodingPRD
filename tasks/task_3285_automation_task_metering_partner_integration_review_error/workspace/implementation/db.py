"""In-memory data store.

Starts empty on every boot (no seeding). Every entity a test needs is built
through the declared API surface.
"""
import uuid


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        # Ordered dicts: insertion order == created_at ascending order.
        self.accounts = {}
        self.members = {}
        self.folders = {}
        self.folder_grants = {}
        self.folder_folder_grants = {}
        self.workflows = {}
        self.actions = {}
        self.runs = {}
        self.integrations = {}
        self.integration_endpoints = {}
        self.integration_versions = {}
        self.connections = {}
        self.workflow_versions = {}
        self.job_events = {}
        self.refund_grants = {}
        self.lapse_incidents = {}
        # account_id -> {"OPENING": bool, "CLOSING": bool} for the current epoch
        self.epoch_steps = {}
        # connection_id -> {"attempt_no": int, "charged_cents": int} for latest RUNNING cycle
        self.attempt_state = {}
        # workflow_version_id -> consecutive BROKEN-eligible migration attempts
        self.migration_attempts = {}

    def reset(self):
        self.__init__()


db = Store()