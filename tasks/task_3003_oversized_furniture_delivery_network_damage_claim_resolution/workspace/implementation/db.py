"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.suppliers = {}
        self.items = {}
        self.hubs = {}
        self.customers = {}
        self.orders = {}
        self.freight_lanes = {}
        self.shipments = {}
        self.linehauls = {}
        self.appointments = {}
        self.damage_claims = {}
        self.chargebacks = {}
        self.return_authorizations = {}


db = Store()
