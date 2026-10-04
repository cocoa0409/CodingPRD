"""In-memory data store + logical clock.

The store starts EMPTY on every boot (per-test-server isolation re-launches
start.sh before every test). No seeding, no file persistence.
"""
from datetime import datetime, timezone

# constants.CLOCK_DEFAULT_UTC — logical clock value at server start.
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.suppliers = {}          # Supplier.id -> Supplier
        self.lots = {}               # RawLot.id -> RawLot
        self.tests = {}              # SafetyTest.id -> SafetyTest (append-only)
        self.formulas = {}           # BlendFormula.id -> BlendFormula
        self.formula_lines = {}      # FormulaLine.id -> FormulaLine
        self.blend_runs = {}         # BlendRun.id -> BlendRun
        self.production_lines = {}   # ProductionLine.id -> ProductionLine
        self.production_runs = {}    # ProductionRun.id -> ProductionRun
        self.batches = {}            # FinishedBatch.id -> FinishedBatch
        self.recall_cases = {}       # RecallCase.id -> RecallCase
        self.agreements = {}         # PrivateLabelAgreement.id -> PrivateLabelAgreement
        self.reservations = {}       # CapacityReservation.id -> CapacityReservation
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0                 # global monotonic counter (creation order)

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()
