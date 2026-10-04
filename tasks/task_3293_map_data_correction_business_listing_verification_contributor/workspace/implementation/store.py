"""In-memory data store. Fresh and empty on every process boot."""

regions = {}
contributors = {}
grants = {}
listings = {}
attempts = {}
edits = {}
tickets = {}
reviews = {}
flags = {}
cases = {}
hours = {}
imagery = {}
routing = {}

# insertion-ordered id lists to keep created_at-stable ordering trivially
def all_items(store):
    return list(store.values())
