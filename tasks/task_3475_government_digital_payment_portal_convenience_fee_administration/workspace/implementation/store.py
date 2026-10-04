"""In-memory data store.

All state lives in module-level dicts and is rebuilt on every process boot.
Nothing is seeded: the store starts empty and every entity is constructed
through the declared API surface.
"""
import itertools
import uuid

_seq = itertools.count(1)

agencies = {}          # Agency
accounts = {}          # AgencySettlementAccount
tiers = {}             # ContractPricingTier
attestations = {}      # ComplianceAttestation
services = {}          # ServiceCatalogItem
authorizations = {}    # StatutoryAuthorization
payers = {}            # Payer
instruments = {}       # PaymentInstrument
quotes = {}            # FeeQuote
transactions = {}      # PaymentTransaction
batches = {}           # SettlementBatch
exceptions = {}        # ReconciliationException
refunds = {}           # Refund
chargebacks = {}       # ChargebackCase
ledger = []            # SelfFundingLedgerEntry rows, in creation order


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic creation counter: stable tiebreak for created_at ASC sorting
    when the logical clock is frozen across several creates."""
    return next(_seq)
