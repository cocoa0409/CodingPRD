"""Rate benchmark endpoints (PRD section 3.1)."""
from flask import Blueprint

import db as store
import enums
import lookup
import middleware
import response
import serializers
import validate
from db import db
from errors import ApiError

bp = Blueprint("benchmarks", __name__)


@bp.route("/sourcing/rate-benchmarks", methods=["POST"])
@middleware.roles(middleware.ROLE_PROGRAM_ADMIN)
def create_benchmark():
    data = validate.body()
    destination_tier = validate.req_enum(data, "destination_tier",
                                         enums.DESTINATION_TIERS)
    program_type = validate.req_enum(data, "program_type", enums.PROGRAM_TYPES)
    adr = validate.req_money(data, "benchmark_adr_usd", exclusive_min=True)
    service_charge_pct = validate.req_pct(data, "benchmark_service_charge_pct",
                                          high=1)
    tax_pct = validate.req_pct(data, "benchmark_tax_pct", high=1)

    if lookup.find_benchmark(destination_tier, program_type) is not None:
        raise ApiError(
            "ERR_BENCHMARK_DUPLICATE",
            "A benchmark already exists for this tier and program type",
        )

    row = store.base_row(versioned=False)
    row.update({
        "destination_tier": destination_tier,
        "program_type": program_type,
        "benchmark_adr_usd": adr,
        "benchmark_service_charge_pct": service_charge_pct,
        "benchmark_tax_pct": tax_pct,
    })
    db.benchmarks[row["id"]] = row
    return response.obj(serializers.benchmark(row), 201)


@bp.route("/sourcing/rate-benchmarks/<benchmark_id>", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def get_benchmark(benchmark_id):
    return response.obj(serializers.benchmark(lookup.benchmark(benchmark_id)))


@bp.route("/sourcing/rate-benchmarks", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def list_benchmarks():
    destination_tier = validate.enum_filter("destination_tier",
                                            enums.DESTINATION_TIERS)
    program_type = validate.enum_filter("program_type", enums.PROGRAM_TYPES)
    limit, offset = validate.pagination()
    rows = store.ordered(db.benchmarks.values())
    if destination_tier:
        rows = [r for r in rows if r["destination_tier"] == destination_tier]
    if program_type:
        rows = [r for r in rows if r["program_type"] == program_type]
    return validate.page(rows, limit, offset, serializers.benchmark)
