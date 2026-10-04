"""Pinned PRD/SCAFFOLD constants. Every value here traces to the spec."""
from decimal import Decimal

# Rate complaint market dominance threshold (PRD 3.2, SCAFFOLD calculations)
MARKET_DOMINANCE_RVC_THRESHOLD = Decimal('1.8000')

# Revenue adequacy (PRD 3.1)
COST_OF_CAPITAL_BPS = 1140

# Prescription floors (PRD 3.3)
ADEQUACY_FLOOR_RVC_ADEQUATE = Decimal('1.0000')
ADEQUACY_FLOOR_RVC_INADEQUATE = Decimal('1.1000')

# Evidentiary track selection and relief caps (PRD 3.2 / 3.3)
THREE_BENCHMARK_RELIEF_CAP_CENTS = 100000000
SIMPLIFIED_SAC_RELIEF_CAP_CENTS = 400000000

# Temporal windows (PRD 3.5 / 3.6 / 3.7 / 3.8)
MERGER_COMMENT_PERIOD_DAYS = 45
ESO_DURATION_DAYS = 60
NITU_WINDOW_DAYS = 180
SERVICE_FAILURE_WINDOW_DAYS = 84

# Reciprocal switching capacity (PRD 3.8)
INTERCHANGE_DISTANCE_LIMIT_MILES = 30
INTERCHANGE_SLOT_CAPACITY = 4

# Merger public interest score (PRD 3.6)
WEIGHT_COMPETITION = Decimal('0.40')
WEIGHT_SERVICE = Decimal('0.30')
WEIGHT_SHIPPER_IMPACT = Decimal('0.30')
APPROVE_THRESHOLD = Decimal('60.00')
CONDITIONS_THRESHOLD = Decimal('45.00')

# Role names (PRD 2.1)
ROLE_PLATFORM_ADMIN = 'PlatformAdmin'
ROLE_BOARD_ADJUDICATOR = 'BoardAdjudicator'
ROLE_SHIPPER = 'Shipper'
ROLE_CARRIER_OPERATOR = 'CarrierOperator'
ALL_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_BOARD_ADJUDICATOR, ROLE_SHIPPER, ROLE_CARRIER_OPERATOR)
