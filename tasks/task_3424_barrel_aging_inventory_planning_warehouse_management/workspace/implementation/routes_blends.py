"""Routes: labels, blend batches, blend components, batch lifecycle."""

from flask import Blueprint, request

import calc
import envelope
import serializers
import store
import validation as v

bp = Blueprint("blends", __name__)

SPIRIT_TYPES = {"BOURBON", "RYE", "TENNESSEE", "SINGLE_MALT"}


def _get_label_or_404(lid):
    label = store.labels.get(lid)
    if label is None:
        raise envelope.err_not_found("Label not found")
    return label


def _get_batch_or_404(bid):
    batch = store.batches.get(bid)
    if batch is None:
        raise envelope.err_not_found("Blend batch not found")
    return batch


def _batch_components(batch_id):
    comps = [c for c in store.components.values() if c["blend_batch_id"] == batch_id]
    comps.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return comps


def _check_age_statement(batch, label):
    """Every component barrel's age at the scheduled bottling date must be
    >= the label's age statement (inclusive boundary)."""
    for c in _batch_components(batch["id"]):
        barrel = store.barrels.get(c["barrel_id"])
        if barrel is None:
            continue
        if calc.age_years_at(barrel, batch["scheduled_bottling_date"]) < label["age_statement_years"]:
            raise envelope.err_age_statement()


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

@bp.route("/barrel-aging/labels", methods=["POST"])
def create_label():
    _, role = v.authenticate()
    v.require_role(role, ["MasterBlender"])
    body = v.get_body()
    v.check_allowed_fields(body, {"name", "age_statement_years", "spirit_type"})
    name = v.req_str(body, "name")
    age_years = v.req_int(body, "age_statement_years", min_v=0)
    spirit_type = v.req_enum(body, "spirit_type", SPIRIT_TYPES)

    now = store.now()
    label = {
        "id": store.new_id(),
        "name": name,
        "age_statement_years": age_years,
        "spirit_type": spirit_type,
        "state": "REGISTERED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.labels[label["id"]] = label
    return envelope.ok_object(serializers.serialize_label(label), status=201)


@bp.route("/barrel-aging/labels/<lid>", methods=["GET"])
def get_label(lid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    return envelope.ok_object(serializers.serialize_label(_get_label_or_404(lid)))


@bp.route("/barrel-aging/labels/<lid>/activate", methods=["POST"])
def activate_label(lid):
    _, role = v.authenticate()
    v.require_role(role, ["MasterBlender"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    label = _get_label_or_404(lid)
    if label["state"] != "REGISTERED":
        raise envelope.err_invalid_state("Label is not REGISTERED")
    label["state"] = "ACTIVE"
    label["version"] += 1
    label["updated_at"] = store.now()
    return envelope.ok_object(serializers.serialize_label(label))


# ---------------------------------------------------------------------------
# Blend batches
# ---------------------------------------------------------------------------

@bp.route("/barrel-aging/blend-batches", methods=["POST"])
def create_batch():
    _, role = v.authenticate()
    v.require_role(role, ["MasterBlender"])
    body = v.get_body()
    v.check_allowed_fields(body, {"label_id", "scheduled_bottling_date"})
    label_id = v.req_str(body, "label_id")
    bottling = v.req_datetime(body, "scheduled_bottling_date")
    if not (bottling > store.now()):
        raise envelope.err_validation(
            "scheduled_bottling_date must be strictly after the current clock"
        )

    label = store.labels.get(label_id)
    if label is None:
        raise envelope.err_not_found("Label not found")

    now = store.now()
    batch = {
        "id": store.new_id(),
        "label_id": label["id"],
        "scheduled_bottling_date": bottling,
        "state": "PROPOSED",
        "validated_at": None,
        "committed_at": None,
        "final_blend_volume_liters": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
        "_commit_seq": None,
        "_aborted_at": None,
        "_abort_seq": None,
    }
    store.batches[batch["id"]] = batch
    return envelope.ok_object(serializers.serialize_batch(batch), status=201)


@bp.route("/barrel-aging/blend-batches/<bid>", methods=["GET"])
def get_batch(bid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    return envelope.ok_object(serializers.serialize_batch(_get_batch_or_404(bid)))


@bp.route("/barrel-aging/blend-batches", methods=["GET"])
def list_batches():
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    limit, offset = v.parse_pagination()
    label_filter = request.args.get("label_id")
    state_filter = request.args.get("state")
    items = []
    for b in sorted(store.batches.values(), key=lambda b: (b["created_at"], b["_seq"])):
        if label_filter is not None and b["label_id"] != label_filter:
            continue
        if state_filter is not None and b["state"] != state_filter:
            continue
        items.append(serializers.serialize_batch(b))
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/blend-batches/<bid>/components", methods=["POST"])
def add_component(bid):
    _, role = v.authenticate()
    v.require_role(role, ["MasterBlender"])
    body = v.get_body()
    v.check_allowed_fields(body, {
        "barrel_id", "drawn_volume_liters", "expected_blend_batch_version",
    })
    barrel_id = v.req_str(body, "barrel_id")
    drawn = v.req_number(body, "drawn_volume_liters", min_v=0, exclusive_min=True)
    expected = v.req_int(body, "expected_blend_batch_version")

    batch = _get_batch_or_404(bid)
    barrel = store.barrels.get(barrel_id)
    if barrel is None:
        raise envelope.err_not_found("Barrel not found")

    # Gate 5: OCC on the batch version.
    if expected != batch["version"]:
        raise envelope.err_stale_blend_batch()

    # Gate 6: components are added only while PROPOSED.
    if batch["state"] != "PROPOSED":
        raise envelope.err_invalid_state("Batch is not PROPOSED")

    # Gate 8: a barrel may appear at most once per batch.
    if any(c["barrel_id"] == barrel_id for c in _batch_components(bid)):
        raise envelope.err_duplicate_component()

    # Gate 10: draw may not exceed the barrel's current ledger volume.
    calc.refresh_barrel(barrel)
    if calc.to_dec(drawn) > calc.ledger_at(barrel):
        raise envelope.err_insufficient_volume()

    now = store.now()
    component = {
        "id": store.new_id(),
        "blend_batch_id": bid,
        "barrel_id": barrel_id,
        "drawn_volume_liters": calc.to_dec(drawn),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.components[component["id"]] = component
    batch["version"] += 1
    batch["updated_at"] = now
    return envelope.ok_object(serializers.serialize_component(component), status=201)


@bp.route("/barrel-aging/blend-batches/<bid>/components", methods=["GET"])
def list_components(bid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    _get_batch_or_404(bid)
    limit, offset = v.parse_pagination()
    items = [serializers.serialize_component(c) for c in _batch_components(bid)]
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/blend-batches/<bid>/validate", methods=["POST"])
def validate_batch(bid):
    _, role = v.authenticate()
    v.require_role(role, ["MasterBlender"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    batch = _get_batch_or_404(bid)

    if batch["state"] != "PROPOSED":
        raise envelope.err_invalid_state("Batch is not PROPOSED")
    components = _batch_components(bid)
    if not components:
        raise envelope.err_validation("Batch has no components")
    label = store.labels.get(batch["label_id"])
    if label is None or label["state"] != "ACTIVE":
        raise envelope.err_label_not_active()
    # Compliance: age statement first (inclusive), then spirit match.
    _check_age_statement(batch, label)
    for c in components:
        barrel = store.barrels.get(c["barrel_id"])
        if barrel is not None and barrel["spirit_type"] != label["spirit_type"]:
            raise envelope.err_validation("Component spirit type does not match the label")

    batch["state"] = "VALIDATED"
    batch["validated_at"] = store.now()
    batch["version"] += 1
    batch["updated_at"] = store.now()
    return envelope.ok_object(serializers.serialize_batch(batch))


@bp.route("/barrel-aging/blend-batches/<bid>/revise", methods=["POST"])
def revise_batch(bid):
    _, role = v.authenticate()
    v.require_role(role, ["MasterBlender"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    batch = _get_batch_or_404(bid)
    if batch["state"] != "VALIDATED":
        raise envelope.err_invalid_state("Batch is not VALIDATED")
    batch["state"] = "PROPOSED"
    batch["version"] += 1
    batch["updated_at"] = store.now()
    return envelope.ok_object(serializers.serialize_batch(batch))


@bp.route("/barrel-aging/blend-batches/<bid>/commit", methods=["POST"])
def commit_batch(bid):
    _, role = v.authenticate()
    v.require_role(role, ["MasterBlender"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    batch = _get_batch_or_404(bid)

    if batch["state"] != "VALIDATED":
        raise envelope.err_invalid_state("Batch is not VALIDATED")
    label = store.labels.get(batch["label_id"])
    if label is None or label["state"] != "ACTIVE":
        raise envelope.err_label_not_active()
    components = _batch_components(bid)

    # Re-checks (all before any mutation — the commit is atomic).
    _check_age_statement(batch, label)
    for c in components:
        barrel = store.barrels.get(c["barrel_id"])
        if barrel is None:
            continue
        calc.refresh_barrel(barrel)
        if calc.to_dec(c["drawn_volume_liters"]) > calc.ledger_at(barrel):
            raise envelope.err_insufficient_volume()

    now = store.now()
    batch["_commit_seq"] = store.next_seq()
    batch["committed_at"] = now
    total = calc.to_dec(0)
    for c in components:
        barrel = store.barrels.get(c["barrel_id"])
        if barrel is None:
            continue
        total += calc.to_dec(c["drawn_volume_liters"])
        barrel["version"] += 1
        barrel["updated_at"] = now
    batch["final_blend_volume_liters"] = total
    batch["state"] = "COMMITTED"
    batch["version"] += 1
    batch["updated_at"] = now
    return envelope.ok_object(serializers.serialize_batch(batch))


@bp.route("/barrel-aging/blend-batches/<bid>/abort", methods=["POST"])
def abort_batch(bid):
    _, role = v.authenticate()
    v.require_role(role, ["MasterBlender"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    batch = _get_batch_or_404(bid)

    if batch["state"] not in ("VALIDATED", "COMMITTED"):
        raise envelope.err_invalid_state("Batch is not VALIDATED or COMMITTED")

    now = store.now()
    if batch["state"] == "COMMITTED":
        # Compensation: restore every component's drawn volume exactly.
        batch["_aborted_at"] = now
        batch["_abort_seq"] = store.next_seq()
        for c in _batch_components(bid):
            barrel = store.barrels.get(c["barrel_id"])
            if barrel is None:
                continue
            barrel["version"] += 1
            barrel["updated_at"] = now
    batch["state"] = "ABORTED"
    batch["version"] += 1
    batch["updated_at"] = now
    return envelope.ok_object(serializers.serialize_batch(batch))
