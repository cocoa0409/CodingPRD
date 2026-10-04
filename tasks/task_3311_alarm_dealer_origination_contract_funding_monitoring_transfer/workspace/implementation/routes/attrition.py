"""Attrition sweep routes."""

from flask import request

import db
import middleware
import response
import serializers
from errors import ApiError
from routes._common import endpoint, q
from services import factory, queries, workflows

SWEEP_READERS = ["FundingAnalyst", "ChannelManager", "PlatformAdmin"]


def register(app):

    @endpoint(app, "POST", "/alarm-funding/attrition-sweeps/run", ["FundingAnalyst"])
    def run_sweep(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "sweep_month")
        sweep_month = middleware.as_str(body["sweep_month"], "sweep_month")
        for existing in db.state.attrition_sweeps.values():
            if existing.get("sweep_month") == sweep_month:
                raise ApiError("ERR_SWEEP_MONTH_DUPLICATE")
        sweep = workflows.run_attrition_sweep(sweep_month)
        return response.envelope_object(serializers.serialize("attrition_sweep", sweep)), 201

    @endpoint(app, "GET", "/alarm-funding/attrition-sweeps", SWEEP_READERS)
    def list_sweeps(actor):
        rows = db.state.all("attrition_sweeps")
        month = q("sweep_month")
        if month is not None:
            rows = [r for r in rows if r.get("sweep_month") == month]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("attrition_sweep", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/attrition-sweeps/<id>", SWEEP_READERS)
    def read_sweep(actor, id):
        sweep = middleware.resolve("attrition_sweeps", id)
        return response.envelope_object(serializers.serialize("attrition_sweep", sweep)), 200

    @endpoint(app, "GET", "/alarm-funding/attrition-sweeps/<id>/flags", SWEEP_READERS)
    def sweep_flags(actor, id):
        middleware.resolve("attrition_sweeps", id)
        rows = [f for f in db.state.attrition_flags.values() if f.get("attrition_sweep_id") == id]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("attrition_flag", page), limit, offset, total), 200