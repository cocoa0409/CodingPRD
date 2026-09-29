"""Candidate pairs: scoring, triage, evidence, recommendation, resolution."""

from decimal import Decimal

from flask import Blueprint, g

from core import (
    ALL_ROLES, FRAUD_AUTO_OPEN_RAW_SCORE_MIN, MIN_EVIDENCE_COUNT, authenticate,
    base_entity, created, err, field_decimal, field_enum, field_id, field_int,
    field_string, get_body, ok, ok_list, paginate, pagination, query_filter,
    store, touch,
)
import domain
import scoring
import serializers

bp = Blueprint("pairs", __name__)

EVIDENCE_TYPES = ["PHOTO_ID", "INSURANCE_CARD", "PHONE_VERIFICATION",
                  "CLINICAL_CHART_COMPARE", "BIOMETRIC_COMPARE"]
OUTCOMES = ["SUPPORTS_SAME_PERSON", "SUPPORTS_DISTINCT", "INCONCLUSIVE"]
SCORE_VARIANTS = ["STRICT", "TOLERANT"]
RESCORE_STATES = ("NEW", "TRIAGED", "UNDER_REVIEW")


def _pair_or_404(pair_id):
    row = store.pairs.get(pair_id)
    if row is None:
        raise err("ERR_PAIR_NOT_FOUND", "No candidate pair with id %s" % pair_id)
    return row


def _require_members_clear(pair):
    """Rank 21 -- both member records clear of a fraud hold."""
    for key in ("record_a_id", "record_b_id"):
        record = store.records.get(pair[key])
        if record is not None and domain.under_fraud_hold(record):
            raise err("ERR_RECORD_UNDER_FRAUD_HOLD",
                      "Patient record %s is under a fraud hold" % record["id"])


def _require_state(pair, allowed):
    if pair["queue_state"] not in allowed:
        raise err("ERR_PAIR_INVALID_STATE",
                  "Candidate pair %s is in queue_state %s" % (pair["id"], pair["queue_state"]))


def _apply_score(pair, record_a, record_b, rule_set, variant):
    outcome = scoring.score(
        scoring.record_attrs(record_a), scoring.record_attrs(record_b), rule_set, variant
    )
    pair["rule_set_id"] = rule_set["id"]
    pair["score_variant"] = variant
    pair["raw_score"] = outcome["raw_score"]
    pair["match_score"] = outcome["match_score"]
    pair["conflict_flags"] = outcome["conflict_flags"]
    pair["classification"] = outcome["classification"]
    pair["attribute_score_breakdown"] = outcome["attribute_score_breakdown"]
    scoring.recompute_bands(pair)


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------
@bp.post("/mpi/candidate-pairs")
def create_pair():
    authenticate(["IdentityAnalyst", "MpiAdmin"])
    body = get_body()
    record_a_id = field_id(body, "record_a_id", required=True)
    record_b_id = field_id(body, "record_b_id", required=True)
    rule_set_id = field_id(body, "rule_set_id", required=True)
    variant = field_enum(body, "score_variant", SCORE_VARIANTS, default="STRICT")

    rule_set = store.rule_sets.get(rule_set_id)                          # rank 6
    if rule_set is None:
        raise err("ERR_RULE_SET_NOT_FOUND", "No match rule set with id %s" % rule_set_id)

    record_a = store.records.get(record_a_id)                            # rank 8
    if record_a is None:
        raise err("ERR_RECORD_NOT_FOUND", "No patient record with id %s" % record_a_id)
    record_b = store.records.get(record_b_id)
    if record_b is None:
        raise err("ERR_RECORD_NOT_FOUND", "No patient record with id %s" % record_b_id)

    if record_a_id == record_b_id:                                       # rank 36
        raise err("ERR_MERGE_SELF_REFERENCE", "A record cannot be paired with itself")

    members = {record_a_id, record_b_id}
    for existing in store.pairs.values():                                # rank 40
        if {existing["record_a_id"], existing["record_b_id"]} != members:
            continue
        if existing["queue_state"] not in ("RESOLVED_DISTINCT", "RESOLVED_MERGED"):
            raise err("ERR_PAIR_ALREADY_EXISTS",
                      "A live candidate pair already exists over these two records")

    # Subject: the member with the later created_at; ties broken by greater mrn.
    if (record_a["created_at"], record_a["mrn"]) >= (record_b["created_at"], record_b["mrn"]):
        subject = record_a
    else:
        subject = record_b

    pair = base_entity()
    pair.update({
        "record_a_id": record_a_id,
        "record_b_id": record_b_id,
        "rule_set_id": rule_set_id,
        "detected_at_site_id": subject["site_id"],
        "score_variant": variant,
        "match_score": Decimal("0.00"),
        "raw_score": Decimal("0.00"),
        "attribute_score_breakdown": {},
        "conflict_flags": [],
        "classification": "NON_DUPLICATE",
        "subject_record_mrn": subject["mrn"],
        "evidence_points": Decimal("0.00"),
        "base_band": "P3",
        "evidence_adjustment": Decimal("0.00"),
        "effective_score": Decimal("0.00"),
        "priority_band": "P3",
        "queue_state": "NEW",
        "triage_note": None,
        "recommended_by_user_id": None,
        "recommendation": None,
        "approved_by_user_id": None,
    })
    _apply_score(pair, record_a, record_b, rule_set, variant)
    store.pairs[pair["id"]] = pair

    flags = pair["conflict_flags"]
    fraud_branch = (
        ("BIOMETRIC_CONFLICT" in flags or "INSURANCE_CONFLICT" in flags)
        and pair["raw_score"] >= FRAUD_AUTO_OPEN_RAW_SCORE_MIN
    )
    if fraud_branch:
        pair["queue_state"] = "ESCALATED_FRAUD"
        if "BIOMETRIC_CONFLICT" in flags and "INSURANCE_CONFLICT" in flags:
            trigger = "BOTH"
        elif "BIOMETRIC_CONFLICT" in flags:
            trigger = "BIOMETRIC_CONFLICT"
        else:
            trigger = "INSURANCE_CONFLICT"
        domain.open_investigation(subject, pair["id"], trigger, "SYSTEM", None, None)
    elif pair["classification"] == "AUTO_LINK" and not flags:
        pair["queue_state"] = "RECOMMENDED_MERGE"
        pair["recommendation"] = "MERGE"
        pair["recommended_by_user_id"] = None

    return created(serializers.pair(pair))


@bp.get("/mpi/candidate-pairs/<pair_id>")
def get_pair(pair_id):
    authenticate(ALL_ROLES)
    return ok(serializers.pair(_pair_or_404(pair_id)))


@bp.get("/mpi/candidate-pairs")
def list_pairs():
    authenticate(ALL_ROLES)
    rows = list(store.pairs.values())
    rows.sort(key=lambda p: (
        p["priority_band"], -p["effective_score"], p["created_at"], p["subject_record_mrn"],
    ))
    for key in ("record_a_id", "record_b_id", "rule_set_id", "detected_at_site_id",
                "queue_state", "classification", "priority_band"):
        rows = query_filter(rows, key)
    window, page = paginate(rows)
    return ok_list([serializers.pair(p) for p in window], page)


# --------------------------------------------------------------------------
# Rescore
# --------------------------------------------------------------------------
@bp.post("/mpi/candidate-pairs/<pair_id>/rescore")
def rescore_pair(pair_id):
    authenticate(["IdentityAnalyst", "MpiAdmin"])
    body = get_body()
    rule_set_id = field_id(body, "rule_set_id", required=True)
    variant = field_enum(body, "score_variant", SCORE_VARIANTS, default="STRICT")
    expected = field_int(body, "expected_pair_version", required=True)

    rule_set = store.rule_sets.get(rule_set_id)                          # rank 6
    if rule_set is None:
        raise err("ERR_RULE_SET_NOT_FOUND", "No match rule set with id %s" % rule_set_id)
    pair = _pair_or_404(pair_id)                                         # rank 9
    if expected != pair["version"]:                                      # rank 19
        raise err("ERR_STALE_PAIR_VERSION",
                  "expected_pair_version %s does not match the pair's current version %s"
                  % (expected, pair["version"]))
    _require_state(pair, RESCORE_STATES)                                 # rank 26

    record_a = store.records.get(pair["record_a_id"])
    record_b = store.records.get(pair["record_b_id"])
    _apply_score(pair, record_a, record_b, rule_set, variant)
    touch(pair)
    return ok(serializers.pair(pair))


# --------------------------------------------------------------------------
# Triage / review
# --------------------------------------------------------------------------
@bp.post("/mpi/candidate-pairs/<pair_id>/triage")
def triage_pair(pair_id):
    authenticate(["IdentityAnalyst"])
    body = get_body()
    note = field_string(body, "triage_note", required=True)
    pair = _pair_or_404(pair_id)
    _require_members_clear(pair)
    _require_state(pair, ("NEW",))
    pair["triage_note"] = note
    pair["queue_state"] = "TRIAGED"
    scoring.recompute_bands(pair)
    touch(pair)
    return ok(serializers.pair(pair))


@bp.post("/mpi/candidate-pairs/<pair_id>/start-review")
def start_review(pair_id):
    authenticate(["IdentityAnalyst"])
    get_body()
    pair = _pair_or_404(pair_id)
    _require_members_clear(pair)
    _require_state(pair, ("TRIAGED",))
    pair["queue_state"] = "UNDER_REVIEW"
    touch(pair)
    return ok(serializers.pair(pair))


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------
@bp.post("/mpi/candidate-pairs/<pair_id>/evidence")
def add_evidence(pair_id):
    authenticate(["IdentityAnalyst"])
    body = get_body()
    evidence_type = field_enum(body, "evidence_type", EVIDENCE_TYPES, required=True)
    outcome = field_enum(body, "outcome", OUTCOMES, required=True)
    weight = field_decimal(body, "weight_points", required=True,
                           minimum=Decimal("0.00"), maximum=Decimal("10.00"))
    note = field_string(body, "note")
    pair = _pair_or_404(pair_id)
    _require_members_clear(pair)
    _require_state(pair, ("UNDER_REVIEW",))

    row = base_entity(with_audit=False)
    row.update({
        "pair_id": pair_id,
        "evidence_type": evidence_type,
        "outcome": outcome,
        "weight_points": weight,
        "note": note,
        "submitted_by_user_id": g.user_id,
    })
    store.evidence[row["id"]] = row
    scoring.recompute_bands(pair)
    touch(pair)
    return created(serializers.evidence(row))


@bp.get("/mpi/candidate-pairs/<pair_id>/evidence")
def list_evidence(pair_id):
    authenticate(ALL_ROLES)
    pagination()
    _pair_or_404(pair_id)
    rows = scoring.evidence_of_pair(pair_id)
    window, page = paginate(rows)
    return ok_list([serializers.evidence(r) for r in window], page)


# --------------------------------------------------------------------------
# Recommendation and resolution
# --------------------------------------------------------------------------
@bp.post("/mpi/candidate-pairs/<pair_id>/recommend")
def recommend_pair(pair_id):
    authenticate(["IdentityAnalyst"])
    body = get_body()
    recommendation = field_enum(body, "recommendation", ["MERGE", "DISTINCT"], required=True)
    pair = _pair_or_404(pair_id)
    _require_members_clear(pair)
    _require_state(pair, ("UNDER_REVIEW",))
    if len(scoring.evidence_of_pair(pair_id)) < MIN_EVIDENCE_COUNT:      # rank 35
        raise err("ERR_INSUFFICIENT_REVIEW_EVIDENCE",
                  "A recommendation requires at least 2 review evidence entries")
    pair["recommendation"] = recommendation
    pair["recommended_by_user_id"] = g.user_id
    pair["queue_state"] = (
        "RECOMMENDED_MERGE" if recommendation == "MERGE" else "RECOMMENDED_DISTINCT"
    )
    touch(pair)
    return ok(serializers.pair(pair))


@bp.post("/mpi/candidate-pairs/<pair_id>/return-to-review")
def return_to_review(pair_id):
    authenticate(["IdentityStewardApprover"])
    body = get_body()
    note = field_string(body, "triage_note")
    pair = _pair_or_404(pair_id)
    _require_state(pair, ("RECOMMENDED_MERGE", "RECOMMENDED_DISTINCT"))
    if note is not None:
        pair["triage_note"] = note
    pair["recommendation"] = None
    pair["recommended_by_user_id"] = None
    pair["queue_state"] = "UNDER_REVIEW"
    touch(pair)
    return ok(serializers.pair(pair))


@bp.post("/mpi/candidate-pairs/<pair_id>/resolve-distinct")
def resolve_distinct(pair_id):
    authenticate(["IdentityStewardApprover"])
    body = get_body()
    field_string(body, "resolution_note")
    pair = _pair_or_404(pair_id)
    _require_state(pair, ("RECOMMENDED_DISTINCT",))
    if pair["recommended_by_user_id"] is not None \
            and g.user_id == pair["recommended_by_user_id"]:             # rank 34
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The operator who recommended a pair may not resolve it")
    pair["queue_state"] = "RESOLVED_DISTINCT"
    pair["approved_by_user_id"] = g.user_id
    touch(pair)
    return ok(serializers.pair(pair))
