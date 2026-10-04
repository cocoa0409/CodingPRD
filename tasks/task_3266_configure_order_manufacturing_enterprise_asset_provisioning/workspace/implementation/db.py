import threading
import uuid
from datetime import datetime, timezone


_lock = threading.RLock()


def now_wall_iso():
    """Wall-clock timestamp for created_at/updated_at metadata (3 fractional digits, Z)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.accounts = {}
        self.programs = {}
        self.chassis_models = {}
        self.components = {}
        self.compat_rules = {}
        self.templates = {}
        self.configurations = {}
        self.orders = {}
        self.order_lines = {}
        self.build_jobs = {}
        self.sub_requests = {}
        self.waves = {}
        self.assets = {}
        self.entitlements = {}
        self.recovery_requests = {}
        # logical clock: fixed startup instant, never wall clock
        self.logical_now = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.serial_counter = 0
        self.asset_tag_counter = 0

    def reset(self):
        self.__init__()


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def logical_now():
    return STORE.logical_now


def logical_now_iso():
    dt = STORE.logical_now
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def set_logical_now(dt):
    STORE.logical_now = dt


def touch(entity):
    entity["updated_at"] = now_wall_iso()
    entity["version"] = entity.get("version", 0) + 1


def new_entity():
    ts = now_wall_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
