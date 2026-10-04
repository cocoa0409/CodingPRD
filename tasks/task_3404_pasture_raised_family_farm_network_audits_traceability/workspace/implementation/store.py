"""In-memory data store. Every dict starts empty at boot; entities are
created only through declared API endpoints. No seeding, no persistence."""
import itertools

farms = {}              # id -> Farm record
contracts = {}          # id -> FarmContract record
audits = {}             # id -> Audit record
corrective_actions = {}  # id -> CorrectiveAction record
incidents = {}          # id -> WelfareIncident record
routes = {}             # id -> CollectionRoute record
lots = {}               # id -> EggLot record
cartons = {}            # carton_code -> Carton record
retailers = {}          # id -> RetailerAccount record
commitments = {}        # id -> SupplyCommitment record
forecasts = {}          # id -> ProductionForecast record
settlement_runs = {}    # id -> SettlementRun record

# Global insertion sequence; stable tiebreaker for created_at-ascending sorts.
_seq = itertools.count(1)
# Human-facing lot code sequence: LOT-000001, LOT-000002, ... (PRD 3.5)
_lot_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def next_lot_code():
    return "LOT-%06d" % next(_lot_seq)
