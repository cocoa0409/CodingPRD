"""In-memory entity store.

State lives only in this process: every collection starts empty on boot and
nothing is ever written to disk. The service never seeds an entity — every row
is produced by a declared endpoint.
"""

import uuid

import clock

# Ordered collections. Insertion order is the tie-break order for the rules
# that rank on created_at alone.
franchisees = {}
routes = {}
shops = {}
technicians = {}
applications = {}
accounts = {}
charges = {}
payments = {}
sales_orders = {}
claims = {}
products = {}
positions = {}
product_orders = {}
pledges = {}
launch_allocations = {}

# Internal ledgers that are not part of any resource representation.
# payment_id -> {"charges": {charge_id: cents}, "principal": cents}
payment_applications = {}
# technician_id -> shop_location_id the technician worked at before a pending move
technician_prior_shop = {}


def new_id():
    """A server-minted UUID string with no type prefix."""
    return str(uuid.uuid4())


def reset():
    for collection in (franchisees, routes, shops, technicians, applications,
                       accounts, charges, payments, sales_orders, claims,
                       products, positions, product_orders, pledges,
                       launch_allocations, payment_applications,
                       technician_prior_shop):
        collection.clear()
    _stamped.clear()
    clock.reset()


# Rows already modified by the request currently being served. A row is
# stamped at most once per unit of work, so version advances by exactly one
# for a modification no matter how many of its fields that modification moves.
_stamped = set()


def begin_unit():
    _stamped.clear()


def stamp(row):
    """Refresh updated_at and bump version by exactly one."""
    if row.get("id") in _stamped:
        return
    _stamped.add(row.get("id"))
    row["updated_at"] = clock.fmt(clock.now())
    row["version"] = row.get("version", 1) + 1


def create(collection, **fields):
    """Insert a new row carrying the four system-managed common fields."""
    row = {
        "id": new_id(),
        "created_at": clock.fmt(clock.now()),
        "updated_at": clock.fmt(clock.now()),
        "version": 1,
    }
    row.update(fields)
    collection[row["id"]] = row
    return row


def set_field(row, name, value):
    """Write a derived attribute, bumping the row only when it really moved."""
    if row.get(name) != value:
        row[name] = value
        stamp(row)
        return True
    return False


def ordered(collection):
    """Rows in creation order (insertion order == created_at order here)."""
    return list(collection.values())


def find(collection, row_id):
    return collection.get(row_id)
