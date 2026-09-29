"""Collective onboarding, reads, and the entity-structure restructure cascade."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("collectives", __name__)

HOME_STATE_CODES = ["AL", "CA", "FL", "OH", "TX"]
ASSOCIATION_RULESETS = ["NCAA_2024", "NCAA_2026", "NAIA"]
ENTITY_STRUCTURES = ["NONPROFIT_501C3", "FOR_PROFIT_LLC", "DONOR_ADVISED_CONDUIT"]
COMMUNICATION_POLICIES = ["STRICT_SEPARATION", "MONITORED_CONTACT"]
FUNDING_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]


@bp.route("/nil/collectives", methods=["POST"])
def create_collective():
    auth.authenticate([auth.PLATFORM_ADMIN])
    body = shape.body()
    name = shape.string_field(body, "name", required=True)
    institution_name = shape.string_field(body, "institution_name", required=True)
    ipeds = shape.string_field(body, "institution_ipeds_code", required=True)
    home_state = shape.enum_field(body, "home_state_code", HOME_STATE_CODES, required=True)
    ruleset = shape.enum_field(body, "association_ruleset", ASSOCIATION_RULESETS, required=True)
    structure = shape.enum_field(body, "entity_structure", ENTITY_STRUCTURES,
                                default="FOR_PROFIT_LLC")
    policy = shape.enum_field(body, "communication_policy", COMMUNICATION_POLICIES,
                              default="STRICT_SEPARATION")

    for existing in store.collectives.values():
        if existing["institution_ipeds_code"] == ipeds:
            raise ApiError("ERR_DUPLICATE_IPEDS_CODE")

    now = clock.now()
    row = {
        "id": store.new_id(),
        "_order": store.next_seq("collective_order"),
        "name": name,
        "institution_name": institution_name,
        "institution_ipeds_code": ipeds,
        "home_state_code": home_state,
        "association_ruleset": ruleset,
        "entity_structure": structure,
        "communication_policy": policy,
        "charitable_deduction_enabled": structure == "NONPROFIT_501C3",
        "structure_effective_at": now,
        "structure_change_count": 0,
        "funding_posture": "OPEN",
        "settled_net_funds_cents": 0,
        "committed_unreleased_cents": 0,
        "released_total_cents": 0,
        "reversed_total_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.collectives[row["id"]] = row
    return envelope.object_response(serialize.collective(row), 201)


@bp.route("/nil/collectives/<collective_id>", methods=["GET"])
def read_collective(collective_id):
    auth.authenticate(auth.ALL_ROLES)
    row = lookup.collective(collective_id)
    return envelope.object_response(serialize.collective(row))


@bp.route("/nil/collectives", methods=["GET"])
def list_collectives():
    auth.authenticate(auth.ALL_ROLES)
    limit, offset = envelope.read_pagination(request.args)
    posture = envelope.enum_filter(request.args, "funding_posture", FUNDING_POSTURES)
    structure = envelope.enum_filter(request.args, "entity_structure", ENTITY_STRUCTURES)
    rows = store.ordered_collectives(store.collectives.values())
    if posture is not None:
        rows = [r for r in rows if r["funding_posture"] == posture]
    if structure is not None:
        rows = [r for r in rows if r["entity_structure"] == structure]
    return envelope.list_response([serialize.collective(r) for r in rows], limit, offset)


@bp.route("/nil/collectives/<collective_id>/entity-structure", methods=["PATCH"])
def change_entity_structure(collective_id):
    auth.authenticate([auth.PLATFORM_ADMIN])
    body = shape.body()
    structure = shape.enum_field(body, "entity_structure", ENTITY_STRUCTURES, required=True)
    expected = shape.int_field(body, "expected_collective_version", required=True)

    collective = lookup.collective(collective_id)

    if expected != collective["version"]:
        raise ApiError("ERR_STALE_COLLECTIVE_VERSION")
    if collective["structure_change_count"] >= calc.MAX_STRUCTURE_CHANGES:
        raise ApiError("ERR_STRUCTURE_CHANGE_LIMIT")
    if structure == collective["entity_structure"]:
        raise ApiError("ERR_STRUCTURE_UNCHANGED")

    collective["entity_structure"] = structure
    collective["charitable_deduction_enabled"] = structure == "NONPROFIT_501C3"
    collective["structure_effective_at"] = clock.now()
    collective["structure_change_count"] += 1
    derive.bump(collective)

    # Level 1 — close every DRAFT or OPEN tier, in ascending tier sequence_no.
    closed_tier_ids = []
    for tier in derive.tiers_of_collective(collective["id"]):
        if tier["tier_status"] in ("DRAFT", "OPEN"):
            tier["tier_status"] = "CLOSED"
            derive.touch(tier)
            closed_tier_ids.append(tier["id"])

    # Level 2 — pause the live commitments sitting on those tiers,
    # in ascending commitment sequence_no.
    donor_index = {d["id"]: d for d in derive.donors_of_collective(collective["id"])}
    for commitment in store.ordered(store.commitments.values()):
        donor = donor_index.get(commitment["donor_member_id"])
        if donor is None or donor["membership_tier_id"] not in closed_tier_ids:
            continue
        if commitment["status"] in ("ACTIVE", "PAST_DUE"):
            commitment["status"] = "PAUSED"
            commitment["pause_reason"] = "STRUCTURE_RESTRUCTURE"
            derive.touch(commitment)

    # Level 3 — lapse every donor left holding only dormant commitments,
    # in ascending donor member sequence_no.
    for donor in derive.donors_of_collective(collective["id"]):
        derive.maybe_lapse_donor(donor)

    return envelope.object_response(serialize.collective(collective))


@bp.route("/nil/collectives/<collective_id>/billing-runs", methods=["POST"])
def billing_run(collective_id):
    auth.authenticate([auth.TREASURY_OFFICER])
    body = shape.body()
    run_kind = shape.enum_field(body, "run_kind",
                                ["SUBSCRIPTION_CHARGE_CYCLE", "YEAR_END_TAX_RECOMPUTE"],
                                required=True)
    collective = lookup.collective(collective_id)

    charged = 0
    settled = 0
    failed = 0
    recomputed = 0
    delta = 0

    if run_kind == "SUBSCRIPTION_CHARGE_CYCLE":
        import routes.contributions as contributions_mod
        donor_index = {d["id"]: d for d in derive.donors_of_collective(collective["id"])}
        targets = []
        for commitment in store.ordered(store.commitments.values()):
            donor = donor_index.get(commitment["donor_member_id"])
            if donor is None:
                continue
            if commitment["kind"] != "RECURRING_SUBSCRIPTION":
                continue
            if commitment["status"] not in ("ACTIVE", "PAST_DUE"):
                continue
            targets.append((commitment, donor))
        for commitment, donor in targets:
            row = contributions_mod.record_contribution_row(
                donor=donor,
                commitment=commitment,
                gross_amount_cents=commitment["amount_cents"],
                source_kind="SUBSCRIPTION_CHARGE",
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            )
            charged += 1
            contributions_mod.settle_contribution(row, "APPROVE", collective)
            if row["status"] == "SETTLED":
                settled += 1
            elif row["status"] == "FAILED":
                failed += 1
        derive.sync_collective(collective)
    else:
        year = clock.tax_year()
        for donor in derive.donors_of_collective(collective["id"]):
            rows = [c for c in derive.contributions_of_donor(donor["id"])
                    if c["status"] == "SETTLED" and clock.tax_year(c["received_at"]) == year]
            if not rows:
                continue
            recomputed += len(rows)
            delta += derive.attribute_deductibility(donor, "YEAR_END_RECOMPUTE")
            derive.sync_donor_lifetime(donor)

    return envelope.object_response({
        "collective_id": collective["id"],
        "run_kind": run_kind,
        "executed_at": clock.format_ts(clock.now()),
        "charged_commitment_count": charged,
        "settled_contribution_count": settled,
        "failed_contribution_count": failed,
        "recomputed_contribution_count": recomputed,
        "deduction_delta_cents": delta,
    })
