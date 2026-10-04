"""Domain thresholds: business numbers used by the PRD's calculations."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Logical clock: the server's logical time at start-up.
CLOCK_START = "2026-09-01T00:00:00Z"

# Warehouse sizing and metering.
SIZE_FACTORS = {
    "XSMALL": 1,
    "SMALL": 2,
    "MEDIUM": 4,
    "LARGE": 8,
    "XLARGE": 16,
    "XXLARGE": 32,
    "XXXLARGE": 64,
    "X4LARGE": 128,
}
SECONDS_PER_HOUR = 3600
DEFAULT_AUTO_SUSPEND_SECONDS = 600
MIN_AUTO_SUSPEND_SECONDS = 60
MAX_AUTO_SUSPEND_SECONDS = 3600
DEFAULT_CLUSTERS_MIN = 1
DEFAULT_CLUSTERS_MAX = 1
MAX_CLUSTERS = 10
DEFAULT_LATENCY_SLO_MS = 1000

# Demand-driven cluster scaling.
QUERIES_PER_CLUSTER = 8
PROJECTED_SECONDS = 900

# Contract drawdowns.
SINGLE_DRAWDOWN_CEILING = 1000
OVERAGE_ROUNDING_DECIMALS = 2

# Storage billing.
STORAGE_DAYS_MIN = 0
STORAGE_DAYS_MAX = 90
FAIL_SAFE_DAYS = 7
DAYS_IN_MONTH = 30
STORAGE_RATES = {"ACTIVE": 0.77, "TIME_TRAVEL": 0.84, "FAIL_SAFE": 1.01}

# Resource monitors.
NOTIFY_PCT = 50.0
SUSPEND_PCT = 100.0

# Marketplace payouts.
PLATFORM_COMMISSION_PCT = 0.15
FREE_LISTING_COMMISSION_PCT = 0.0

# Replication pricing.
COST_PER_TB = 5.0
REGION_FACTORS = {
    "us-east-1": 1.00,
    "us-west-2": 1.10,
    "eu-central-1": 1.20,
    "ap-southeast-1": 1.30,
}
CLOUD_FACTORS = {"SAME_CLOUD": 1.00, "CROSS_CLOUD": 1.35}
REGIONS = ["us-east-1", "us-west-2", "eu-central-1", "ap-southeast-1"]

# Six-decimal credit precision; two-decimal dollar precision.
CREDIT_DECIMALS = 6
DOLLAR_DECIMALS = 2