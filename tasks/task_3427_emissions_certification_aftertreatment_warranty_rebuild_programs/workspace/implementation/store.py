"""In-memory data store: plain dicts keyed by id. No persistence, no seeding.

The store starts empty on every boot; every entity is created through the
declared API surface.
"""
import itertools
import uuid

standards = {}        # RegulationStandard
families = {}         # EngineFamily
specs = {}            # AftertreatmentSpec
test_runs = {}        # CertificationTestRun
fleets = {}           # Fleet
units = {}            # EngineUnit
maintenance = {}      # MaintenanceRecord (append-only)
snapshots = {}        # TelematicsSnapshot (append-only)
centers = {}          # ServiceCenter
technicians = {}      # Technician
tools = {}            # DiagnosticTool
claims = {}           # WarrantyClaim
campaigns = {}        # FieldCampaign
work_orders = {}      # CampaignWorkOrder
reman_orders = {}     # RemanOrder
in_use_results = {}   # InUseComplianceResult (append-only)

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)
