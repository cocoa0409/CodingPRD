"""Static rule book and numeric constants (PRD 2.5, 2.6 and the calculation tables)."""
from decimal import Decimal, ROUND_HALF_UP

API_PREFIX = "/advocacy"

ROLES = [
    "AssociationAdmin",
    "GovAffairsDirector",
    "ComplianceOfficer",
    "BoardTrustee",
    "MemberDelegate",
]
ALL_ROLES = list(ROLES)
STAFF_ROLES = ["AssociationAdmin", "GovAffairsDirector", "ComplianceOfficer", "BoardTrustee"]

JURISDICTIONS = ["FEDERAL", "STATE_CA", "STATE_NY"]
JURISDICTION_SCOPES = ["FEDERAL", "STATE_CA", "STATE_NY", "MULTI"]
MEMBERSHIP_TIERS = ["ASSOCIATE", "FULL", "PREMIER"]
MEMBER_STATUSES = ["ACTIVE", "LAPSED", "SUSPENDED"]
SEAT_ROLES = ["CHAIR", "MEMBER"]
BALLOTS = ["SUPPORT", "OPPOSE", "ABSTAIN"]
ACTIVITY_KINDS = ["DIRECT_LOBBYING", "COALITION_CONTRIBUTION", "THIRD_PARTY_ADVOCACY", "GRASSROOTS_SUPPORT"]
REPORT_BASES = ["METHOD_A", "METHOD_B"]
CHAMBERS = ["US_HOUSE", "US_SENATE", "STATE_ASSEMBLY"]
OFFICES = ["US_HOUSE", "US_SENATE", "STATE_ASSEMBLY"]
INCUMBENCIES = ["INCUMBENT", "CHALLENGER", "OPEN_SEAT"]

JURISDICTION_RULES = {
    "FEDERAL": {
        "registration_threshold_cents": 1400000,
        "report_cadence": "QUARTERLY",
        "per_candidate_election_limit_cents": 500000,
        "grassroots_disclosure_threshold_cents": 250000,
        "deductibility_method": "RATIO",
    },
    "STATE_CA": {
        "registration_threshold_cents": 200000,
        "report_cadence": "QUARTERLY",
        "per_candidate_election_limit_cents": 250000,
        "grassroots_disclosure_threshold_cents": 100000,
        "deductibility_method": "FLAT_FLOOR",
    },
    "STATE_NY": {
        "registration_threshold_cents": 500000,
        "report_cadence": "SEMIANNUAL",
        "per_candidate_election_limit_cents": 100000,
        "grassroots_disclosure_threshold_cents": 400000,
        "deductibility_method": "RATIO",
    },
}

TIER_WEIGHT = {"ASSOCIATE": 1, "FULL": 2, "PREMIER": 3}
MIN_SEATS = 3
MIN_ROSTER_WEIGHT = 6
MAX_BALLOT_ROUNDS = 3
DISSENT_DAMPING_STRIKES = 2

STAFF_HOURLY_RATE_CENTS = 8500
FILING_LAG_DAYS = {"QUARTERLY": 20, "SEMIANNUAL": 30}
COALITION_DISCLOSURE_FLOOR_CENTS = 500000

ASSOCIATION_ANNUAL_BUDGET_CENTS = 120000000
FLAT_FLOOR_MIN_PCT = Decimal("25.00")
FLAT_FLOOR_EXEMPT_BASE_CENTS = 25000

INCUMBENCY_FACTOR = {"INCUMBENT": 100, "CHALLENGER": 60, "OPEN_SEAT": 80}
ENGAGEMENT_PER_ACTION = 10
SCORE_WEIGHT_ALIGNMENT = Decimal("0.45")
SCORE_WEIGHT_RELEVANCE = Decimal("0.25")
SCORE_WEIGHT_INCUMBENCY = Decimal("0.20")
SCORE_WEIGHT_ENGAGEMENT = Decimal("0.10")
SCORE_TIER_FULL = Decimal("85.00")
SCORE_TIER_HALF = Decimal("70.00")
SCORE_TIER_QUARTER = Decimal("55.00")

ALERT_COOLING_HOURS = 48

FILING_FEE_BASE_CENTS = 15000
RESTRICTED_SURCHARGE_CENTS = 5000
LATE_PENALTY_CENTS = 25000


def round_half_up(value, places=0):
    """Round half up (away from zero on the exact half) to `places` decimals."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def pct(value):
    """Two-decimal percentage as a JSON number."""
    return float(round_half_up(value, 2))


def hours3(value):
    """Three-decimal hour quantity as a JSON number."""
    return float(round_half_up(value, 3))
