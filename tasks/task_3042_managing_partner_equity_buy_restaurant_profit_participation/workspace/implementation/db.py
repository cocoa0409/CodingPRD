"""In-memory data store. The store starts empty on every boot; nothing is seeded."""

from datetime import datetime, timezone

# Logical clock — fixed startup default per PRD §2.4.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

logical_clock = DEFAULT_CLOCK


def clock_now():
    return logical_clock


def set_clock(dt):
    global logical_clock
    logical_clock = dt


def utcnow():
    """Real wall-clock time, used only for meta.api_request_timestamp."""
    return datetime.now(timezone.utc)


partners = {}           # id -> Partner
market_groups = {}      # id -> MarketGroup
restaurants = {}        # id -> Restaurant
contracts = {}          # id -> ManagingPartnerContract
buy_in_payments = {}    # id -> BuyInPayment
agreements = {}         # id -> MarketPartnerAgreement
periods = {}            # id -> ProfitPeriod
line_items = {}         # id -> ProfitStatementLineItem
yield_standards = {}    # id -> YieldStandard
batches = {}            # id -> MeatCutBatch
award_programs = {}     # id -> AwardProgram
award_grants = {}       # id -> AwardGrant
disputes = {}           # id -> DisputeCase
buyout_orders = {}      # id -> BuyoutOrder
