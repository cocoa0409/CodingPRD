"""Core primitives: in-memory store, logical clock, integer arithmetic helpers.

There is no floating point arithmetic anywhere in this domain (PRD 2.5) and no
persistence: every dict below starts empty on every process boot.
"""
import datetime
import itertools
import random
import string
import uuid

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD 1.3 constants / PRD 2.8, 2.9)
# ---------------------------------------------------------------------------
REGION_FREIGHT_UPLIFT_BPS = {"NE": 600, "SE": 250, "MW": 0, "WEST": 450}
REGION_CAP_MULTIPLIER_BPS = {"NE": 11500, "SE": 10500, "MW": 11000, "WEST": 12000}
REGION_COMPETITOR_INDEX_CENTS = {"NE": 1750, "SE": 1450, "MW": 1500, "WEST": 1900}
REFERENCE_REGION_CODE = "MW"
PLATE_WASTE_BPS = 200
GARNISH_BPS = 150
GARNISH_FLOOR_MICROS = 8000
MAX_SINGLE_INCREASE_BPS = 1200
CAP_RELIEF_BPS = 300
MARGIN_FLOOR_CENTS = 300
DEFAULT_BASELINE_UNITS = 1000
MAX_RECIPE_DEPTH = 4
MAX_REVISION_ROUNDS = 2
POPULARITY_FACTOR_BPS = 7000
COOLING_OFF_DAYS = 14
VARIANCE_TOLERANCE_BPS = 300
WEIGHTED_AVG_WINDOW_DAYS = 90
KIDS_MENU_SODIUM_CAP_MCG = 640000
LTO_SUPPORT_BPS = 300
LTO_MIN_CONTRIBUTION_CENTS = 0
LTO_MIN_ATTAINMENT_BPS = 8000
MAX_CONCURRENT_LTO_PER_REGION = 2

REGIONS = ("NE", "SE", "MW", "WEST")
UOMS = ("GRAM", "MILLILITER", "EACH")
DISTRIBUTORS = ("BROADLINE", "PRODUCE", "PROTEIN")
ROLES = ("PlatformAdmin", "RecipeDeveloper", "CulinaryDirector", "CostAnalyst",
         "UnitManager")
COST_BASES = ("LATEST_PUBLISHED", "WEIGHTED_AVG_90D")
REVIEW_BASES = ("SALES_MIX_BASED", "USAGE_BASED")
MARGIN_CLASSES = ("STAR", "PLOWHORSE", "PUZZLE", "DOG", "UNCLASSIFIED")

INITIAL_CLOCK = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Integer arithmetic (PRD 2.5)
# ---------------------------------------------------------------------------
def rhu(numerator, divisor):
    """Round half up, sign-symmetric (magnitude rounded, sign restored)."""
    if divisor < 0:
        numerator, divisor = -numerator, -divisor
    if numerator < 0:
        return -rhu(-numerator, divisor)
    q, r = divmod(numerator, divisor)
    if 2 * r >= divisor:
        q += 1
    return q


def ceil_div(numerator, divisor):
    """Ceiling division for non-negative numerators."""
    return -((-numerator) // divisor)


def floor_div(numerator, divisor):
    return numerator // divisor


def sign(value):
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_instant(text):
    """Parse an ISO 8601 instant. Returns None when malformed."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


DAY = datetime.timedelta(days=1)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.units = {}
        self.ingredients = {}
        self.price_feeds = {}
        self.ingredient_prices = {}
        self.recipes = {}
        self.recipe_components = {}
        self.prep_guides = {}
        self.menu_items = {}
        self.proposals = {}
        self.spec_change_orders = {}
        self.period_reviews = {}
        self.mix_lines = {}
        self.count_lines = {}
        self.lto_campaigns = {}
        self.clock = INITIAL_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def stamp_new(row):
    """Attach the four common system-managed properties (PRD 2.4)."""
    now = db.now()
    row["id"] = new_id()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Every mutation increments version by exactly one and refreshes updated_at."""
    row["version"] = row.get("version", 0) + 1
    row["updated_at"] = db.now()
    return row


def order_key(row):
    return (row["created_at"], row["_seq"])
