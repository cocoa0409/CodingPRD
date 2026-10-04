"""In-memory data stores.

A fresh process boots with completely empty stores: no seeding, no
preloading, no hardcoded entities. All data arrives through the API.
"""

contracts = {}
studies = {}
design_plans = {}
irb_protocols = {}
sites = {}
participants = {}
waves = {}
records = {}
analysis_plans = {}
reports = {}
restricted_use_files = {}
dissemination_activities = {}

_seq = [0]


def next_seq():
    """Monotonic insertion sequence; stable sort tiebreak for equal timestamps."""
    _seq[0] += 1
    return _seq[0]
