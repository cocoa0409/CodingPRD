"""Per-entity response projections.

Mostly a thin pass over ``serializer.serialize``, but the environment carries
two clock-derived projections (``next_refresh_at`` and ``permission_layer_total``)
that are recomputed on read — without moving the row's updated_at or version —
so that a clock advance is observable immediately (PRD §3.2, §3.8).
"""

import serializer
from services import environments as environment_service


def environment(env):
    # Clock-dependent projections, recomputed for the read.
    env["next_refresh_at"] = environment_service.refresh_window_next_at(env)
    env["release_window_index"] = environment_service.release_window_index(env)
    environment_service.payment_layer_total(env)
    return serializer.serialize(env)


def refresh_job(row):
    return serializer.serialize(row)


def package_version(row):
    return serializer.serialize(row)


def installed_package(row):
    return serializer.serialize(row)


def permission_assignment(row):
    return serializer.serialize(row)


def change_set(row):
    return serializer.serialize(row)


def deployment_job(row):
    return serializer.serialize(row)


def governor_request(row):
    return serializer.serialize(row)


def storage_ledger(row):
    return serializer.serialize(row)


def access_audit(row):
    return serializer.serialize(row)