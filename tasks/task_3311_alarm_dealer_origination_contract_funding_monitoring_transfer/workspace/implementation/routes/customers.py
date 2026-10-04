"""Customer routes."""

from flask import request

import db
import middleware
import response
import serializers
from errors import ApiError
from routes._common import endpoint, q
from services import factory, queries

CUSTOMER_READERS = ["FundingAnalyst", "ChannelManager", "ComplianceOfficer",
                    "Customer", "PlatformAdmin"]


def register(app):

    @endpoint(app, "POST", "/alarm-funding/customers",
              ["ChannelManager", "FundingAnalyst", "PlatformAdmin"])
    def create_customer(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "full_name", "email", "phone")
        full_name = middleware.as_str(body["full_name"], "full_name")
        email = middleware.as_str(body["email"], "email")
        phone = middleware.as_str(body["phone"], "phone")
        for customer in db.state.customers.values():
            if customer.get("email") == email:
                raise ApiError("ERR_NATURAL_KEY_DUPLICATE")
        customer = factory.make_customer(full_name, email, phone)
        return response.envelope_object(serializers.serialize("customer", customer)), 201

    @endpoint(app, "GET", "/alarm-funding/customers", CUSTOMER_READERS)
    def list_customers(actor):
        rows = db.state.all("customers")
        email = q("email")
        status = q("status")
        if email is not None:
            rows = [r for r in rows if r.get("email") == email]
        if status is not None:
            rows = [r for r in rows if r.get("status") == status]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("customer", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/customers/<id>", CUSTOMER_READERS)
    def read_customer(actor, id):
        customer = middleware.resolve("customers", id)
        return response.envelope_object(serializers.serialize("customer", customer)), 200

    @endpoint(app, "GET", "/alarm-funding/customers/<id>/contract-owners", CUSTOMER_READERS)
    def customer_owners(actor, id):
        middleware.resolve("customers", id)
        rows = [o for o in db.state.contract_owners.values() if o.get("customer_id") == id]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("contract_owner", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/customers/<id>/assumption-requests",
              ["Customer", "FundingAnalyst", "ServiceCoordinator", "PlatformAdmin"])
    def customer_assumptions(actor, id):
        middleware.resolve("customers", id)
        rows = [a for a in db.state.assumption_requests.values()
                if a.get("incoming_customer_id") == id]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("assumption_request", page), limit, offset, total), 200