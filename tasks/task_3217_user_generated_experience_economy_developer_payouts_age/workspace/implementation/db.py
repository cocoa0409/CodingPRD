"""In-memory data store. Starts empty on every boot — no seeding."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical platform clock; startup default per PRD §2.8
        self.current_utc = datetime(2026, 9, 1, tzinfo=timezone.utc)

        # Entity tables: id -> dict
        self.users = {}
        self.identity_verifications = {}
        self.tax_documents = {}
        self.parental_controls = {}  # keyed by id; also child_user_id index
        self.experiences = {}
        self.age_ratings = {}
        self.moderation_submissions = {}
        self.moderation_appeals = {}
        self.currency_purchase_orders = {}
        self.purchase_orders = {}
        self.devex_requests = {}
        self.marketplace_items = {}
        self.resale_listings = {}
        self.chat_messages = {}
        self.reports = {}
        self.account_terminations = {}
        self.engagement_snapshots = {}
        self.audit_logs = {}

        # Idempotency indexes: key -> order id
        self.cpo_idem = {}
        self.po_idem = {}


DB = Store()
