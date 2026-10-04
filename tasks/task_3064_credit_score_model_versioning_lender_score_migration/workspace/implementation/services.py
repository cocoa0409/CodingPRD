"""Business workflows, derived-field recomputation and the cascade chains."""

import hashlib
from decimal import Decimal

from core import (
    DB,
    ORDER,
    touch,
    new_record,
    store,
    now,
    now_iso,
    half_up,
    dec_out,
    ordered_rows,
)
from errors import ApiError
from calculations import (
    effective_score,
    odds_at_posted_score,
    fee_through,
    marginal_fee_cents,
    composite_scores,
    bubble_up,
    cascade_depth as compute_cascade_depth,
    window_outcome_mixture_ratio_ppm,
)

PPM_SCALE = Decimal(1000000)


# =============================================================================
# Low-level lookups (records are never mutated by these)
# =============================================================================
def model_of_variant(variant):
    return DB["score_models"][variant["score_model_id"]]


def variant_of_model(model, industry):
    for v in DB["score_variants"].values():
        if v["score_model_id"] == model["id"] and v["industry"] == industry:
            return v
    return None


def variants_of_model(model_id):
    return [DB["score_variants"][vid] for vid in ORDER["score_variants"]
            if DB["score_variants"][vid]["score_model_id"] == model_id]


def variants_of_model_ordered(model_id):
    return sorted(variants_of_model(model_id), key=lambda v: (v["created_at"], v["id"]))


def model_family_of_variant_id(variant_id):
    variant = DB["score_variants"].get(variant_id)
    if variant is None:
        return None
    model = DB["score_models"].get(variant["score_model_id"])
    return model["family_code"] if model else None


def postings_of_license(license_id):
    return [sr for sr in ordered_rows("score_results") if sr["license_id"] == license_id]


def postings_of_reference_set(reference_set_id):
    return [sr for sr in ordered_rows("score_results") if sr["reference_set_id"] == reference_set_id]


def non_voided_postings_of_license(license_id):
    return [sr for sr in ordered_rows("score_results")
            if sr["license_id"] == license_id and not sr.get("_voided")]


# =============================================================================
# Derived recomputation
# =============================================================================
def recompute_active_variant_count(model):
    count = sum(1 for v in DB["score_variants"].values()
                if v["score_model_id"] == model["id"] and v["status"] == "RELEASED")
    if model["active_variant_count"] != count:
        model["active_variant_count"] = count
        touch(model)
    return count


def recompute_cascade_depth(model):
    depth = compute_cascade_depth(model)
    if model["cascade_depth"] != depth:
        model["cascade_depth"] = depth
        touch(model)


def precompute_cascade_depth(model):
    """depth(node) = 0 if no predecessor else 1 + depth(predecessor)."""
    depth = 0
    seen = {model["id"]}
    pred = model.get("predecessor_model_id")
    while pred:
        if pred in seen:
            break
        seen.add(pred)
        depth += 1
        node = DB["score_models"].get(pred)
        if node is None:
            break
        pred = node.get("predecessor_model_id")
    return depth


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n % 2 == 1:
        return Decimal(ordered[n // 2])
    return (Decimal(ordered[n // 2 - 1]) + Decimal(ordered[n // 2])) / Decimal(2)


def recompute_distribution_shift(model):
    """PRD: for each RELEASED variant, the mean of its running scored median
    minus the predecessor model's same-industry median (in points)."""
    predecessor_id = model.get("predecessor_model_id")
    for variant in variants_of_model_ordered(model["id"]):
        if variant["status"] != "RELEASED":
            continue
        postings = [
            sr for sr in ordered_rows("score_results")
            if sr["score_variant_id"] == variant["id"] and not sr.get("_voided")
        ]
        new_shift = Decimal(0)
        if postings:
            shift = []
            running = []
            for posting in postings:
                running.append(posting["effective_score"])
                scored_median = _median(running)
                predecessor_median = Decimal(0)
                if predecessor_id:
                    peer = variant_of_model(DB["score_models"][predecessor_id], variant["industry"])
                    if peer is not None:
                        peer_postings = [
                            sr for sr in ordered_rows("score_results")
                            if sr["score_variant_id"] == peer["id"] and not sr.get("_voided")
                        ]
                        scored = [sr["effective_score"] for sr in peer_postings]
                        if scored:
                            predecessor_median = _median(scored)
                shift.append(scored_median - predecessor_median)
            new_shift = sum(shift) / Decimal(len(shift))
        variant["distribution_shift_points"] = float(new_shift)
        touch(variant)


def recompute_consumer(consumer_rec):
    postings = [sr for sr in ordered_rows("score_results")
                if sr["consumer_id"] == consumer_rec["id"] and not sr.get("_voided")]
    undecided = sum(1 for sr in postings if sr["decision"] == "UNDECIDED")
    consumer_rec["model_undecided_count"] = undecided
    if postings:
        latest = max(postings, key=lambda sr: (sr["created_at"], _neg_id_key(sr["id"])))
        consumer_rec["latest_uploaded_at"] = latest["created_at"]
    else:
        consumer_rec["latest_uploaded_at"] = None
    touch(consumer_rec)


def _neg_id_key(value):
    """Tie-break key so that 'greater created_at, then ascending id' can be
    expressed as a single max() key."""
    return tuple(-ord(c) for c in value)


def recompute_reason_code_weights(code):
    children = [rc for rc in DB["reason_codes"].values()
                if rc.get("parent_reason_code_id") == code["id"] and rc["status"] == "ARCHIVED"]
    code["weight_received_pct"] = dec_out(bubble_up(children), 4)
    code["weight_effective_pct"] = dec_out(
        half_up(Decimal(str(code["weight_pct"])) + Decimal(str(code["weight_received_pct"])), 4), 4)
    touch(code)


def recompute_license_ledger(license_rec):
    entries = [e for e in DB["fee_ledger_entries"].values() if e["license_id"] == license_rec["id"]]
    license_rec["cumulative_fee_cents"] = sum(e["fee_cents"] for e in entries)


def recompute_license_count(license_rec):
    license_rec["cumulative_score_count"] = len(non_voided_postings_of_license(license_rec["id"]))


def recompute_license_window(license_rec):
    postings = non_voided_postings_of_license(license_rec["id"])
    score_sum = sum(sr["effective_score"] for sr in postings)
    license_rec["window_outcome_mixture_ratio_ppm"] = window_outcome_mixture_ratio_ppm(
        score_sum, license_rec["cumulative_score_count"])
    credit = 0
    for event in DB["migration_events"].values():
        if event.get("_consumed_by_license_id") == license_rec["id"] and event.get("voided_at") is None:
            credit += event["credited_delta_bps"]
    license_rec["window_credited_delta_bps"] = credit


def recompute_license(license_rec, with_count=True):
    if with_count:
        recompute_license_count(license_rec)
    recompute_license_ledger(license_rec)
    recompute_license_window(license_rec)


def doc_checksum(document):
    raw = "|".join([
        str(document["score_model_id"]),
        str(document["required_version_label"]),
        str(document["doc_type"]),
        str(document["status"]),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def recompute_doc_checksum(document):
    document["checksum"] = doc_checksum(document)


# =============================================================================
# Documentation gates (PRD §2.10)
# =============================================================================
def model_risk_report_filed(model):
    for document in DB["model_documentation"].values():
        if (document["doc_type"] == "MODEL_RISK_REPORT"
                and document["required_version_label"] == model["version_label"]
                and document["status"] in ("FILED", "SUPPLEMENTED")):
            return True
    return False


def adverse_action_map_filed(model):
    for document in DB["model_documentation"].values():
        if (document["doc_type"] == "ADVERSE_ACTION_MAP"
                and document["required_version_label"] == model["version_label"]
                and document["status"] in ("FILED", "SUPPLEMENTED")):
            return True
    return False


def doc_for_model_and_type(model, doc_type):
    for document in DB["model_documentation"].values():
        if (document["doc_type"] == doc_type
                and document["score_model_id"] == model["id"]
                and document["required_version_label"] == model["version_label"]):
            return document
    return None


# =============================================================================
# Reference-set / posting binding helpers
# =============================================================================
def latest_reference_set(consumer_id, model_id):
    candidates = [rs for rs in DB["reference_sets"].values()
                  if rs["consumer_id"] == consumer_id and rs["score_model_id"] == model_id]
    if not candidates:
        return None
    return max(candidates, key=lambda rs: (rs["created_at"], _neg_id_key(rs["id"])))


def derive_posting(posting):
    variant = DB["score_variants"][posting["score_variant_id"]]
    model = DB["score_models"][variant["score_model_id"]]
    posting["effective_score"] = effective_score(model, variant, posting["raw_posted_score"])
    posting["odds_at_posted_score"] = dec_out(
        odds_at_posted_score(variant, posting["effective_score"]), 4)


def lowest_composite_primary_reason_code(variant):
    candidates = [rc for rc in DB["reason_codes"].values()
                  if rc["score_variant_id"] == variant["id"]
                  and rc["status"] == "ACTIVE"
                  and rc["depth_tier"] == "PRIMARY"]
    if not candidates:
        return None
    return min(candidates, key=lambda rc: rc["composite_code"])


def non_voided_reason_codes_in_use():
    codes = set()
    for posting in DB["score_results"].values():
        if posting.get("_voided"):
            continue
        rid = posting.get("decision_reason_code_id")
        if rid and rid in DB["reason_codes"]:
            codes.add(DB["reason_codes"][rid]["composite_code"])
    return codes


# =============================================================================
# Cascade C7 -- model supersession (PRD §2.8)
# =============================================================================
def c7_supersede(model):
    """Hop 1 for one superseded model, plus hops 2 and 3."""
    if model["status"] in ("RELEASED", "DEPRECATED"):
        model["status"] = "SUPERSEDED"
        model["retired_at"] = now_iso()
        touch(model)
    c7_hops(model)


def c7_release_predecessor(model, predecessor_id):
    """On release: designated predecessor and every model naming it supersede.

    A root release names no predecessor, so nothing supersedes (PRD §2.8).
    """
    if not predecessor_id:
        return
    targets = []
    if predecessor_id in DB["score_models"]:
        targets.append(DB["score_models"][predecessor_id])
    for other in DB["score_models"].values():
        if other["id"] != model["id"] and other.get("predecessor_model_id") == predecessor_id:
            targets.append(other)
    seen = set()
    for target in targets:
        if target["id"] == model["id"] or target["id"] in seen:
            continue
        seen.add(target["id"])
        if target["status"] in ("RELEASED", "DEPRECATED"):
            target["status"] = "SUPERSEDED"
            target["retired_at"] = now_iso()
            touch(target)
        c7_hops(target)


def c7_hops(superseded_model):
    """Hop 2: licences on superseded variants suspend. Hop 3: reference sets reconcile."""
    for variant in variants_of_model(superseded_model["id"]):
        for license_rec in DB["licenses"].values():
            if license_rec["score_variant_id"] == variant["id"] and license_rec["status"] == "ACTIVE":
                license_rec["status"] = "SUSPENDED"
                touch(license_rec)
    for refset in DB["reference_sets"].values():
        if refset["score_model_id"] == superseded_model["id"] and refset["status"] in ("COMPILED", "BOUND"):
            refset["status"] = "RECONCILED"
            refset["reason_code_id"] = None
            touch(refset)


# =============================================================================
# Cascade C10 / C11 -- catalogue cascade and its compensating actions
# =============================================================================
def c10_affected_reference_sets(code_id):
    refsets = [rs for rs in ordered_rows("reference_sets")
               if rs["reason_code_id"] == code_id and rs["status"] == "BOUND"]
    return refsets


def freeze_plan_for_archive(refsets):
    """Snapshot the pre-archive state of every affected posting."""
    frozen = {}
    for refset in refsets:
        for posting in postings_of_reference_set(refset["id"]):
            variant = DB["score_variants"][posting["score_variant_id"]]
            model = DB["score_models"][variant["score_model_id"]]
            re_derived = effective_score(model, variant, posting["raw_posted_score"])
            frozen[posting["id"]] = {
                "decision": posting["decision"],
                "reason_code_id": posting.get("decision_reason_code_id"),
                "effective_score": re_derived,
                "odds": dec_out(odds_at_posted_score(variant, re_derived), 4),
            }
    return frozen


def apply_c10(refsets, frozen):
    """Hops 1-5 of C10 plus hop 1 of C11, replayed against the frozen snapshot."""
    if not refsets:
        return
    affected_consumers = set()

    # Hop 1 + hop 2
    for refset in refsets:
        refset["status"] = "RECONCILED"
        refset["reason_code_id"] = None
        touch(refset)
        for posting in postings_of_reference_set(refset["id"]):
            posting["decision"] = "UNDECIDED"
            posting["decision_reason_code_id"] = None
            touch(posting)
            affected_consumers.add(posting["consumer_id"])

    # Hop 3
    for consumer_id in affected_consumers:
        consumer_rec = DB["consumers"].get(consumer_id)
        if consumer_rec is None:
            continue
        recompute_consumer(consumer_rec)

        # Hop 4
        if consumer_rec["model_undecided_count"] >= 3:
            for posting in ordered_rows("score_results"):
                if posting["consumer_id"] == consumer_id and posting["decision"] == "UNDECIDED":
                    posting["decision"] = "DECLINE"
                    touch(posting)

                    # Hop 5
                    variant = DB["score_variants"][posting["score_variant_id"]]
                    primary = lowest_composite_primary_reason_code(variant)
                    posting["decision_reason_code_id"] = primary["id"] if primary else None

                    # Hop 1 of C11: re-derive, effective_score numerically unchanged
                    snapshot = frozen.get(posting["id"])
                    if snapshot is not None:
                        posting["effective_score"] = snapshot["effective_score"]
                        posting["odds_at_posted_score"] = snapshot["odds"]
                    else:
                        derive_posting(posting)
        recompute_consumer(consumer_rec)


# =============================================================================
# Cascade C8 / C9 -- study completion and reversion
# =============================================================================
def c8_hop1(study):
    for model_id in study["touched_model_ids"]:
        model = DB["score_models"].get(model_id)
        if model is not None:
            recompute_distribution_shift(model)


def c8_hop2(study):
    """The completion cascade's documentation hop, shared with revert."""
    settle_study_documentation(study)


def c9_replay(study):
    """Hop 1: re-derive distribution shift in touched_model_ids order.
    Hop 2: every document attesting a model in the log -> SUPPLEMENTED.
    Then the same documentation hop the completion cascade applies."""
    for model_id in study["touched_model_ids"]:
        model = DB["score_models"].get(model_id)
        if model is not None:
            recompute_distribution_shift(model)
    for model_id in study["touched_model_ids"]:
        for document in DB["model_documentation"].values():
            if document["score_model_id"] == model_id and document["status"] in ("DRAFT", "FILED"):
                document["status"] = "SUPPLEMENTED"
                recompute_doc_checksum(document)
                touch(document)
    settle_study_documentation(study)


def c8_hop3(study):
    model = DB["score_models"][study["score_model_id"]]
    for document in DB["model_documentation"].values():
        if (document["doc_type"] == "FAIR_LENDING_REPORT"
                and document["required_version_label"] == model["version_label"]
                and document["status"] in ("DRAFT", "FILED")):
            document["status"] = "SUPPLEMENTED"
            recompute_doc_checksum(document)
            touch(document)


def stamp_validated_at(study):
    model_id = study["score_model_id"]
    others = [s for s in DB["validation_studies"].values()
              if s["score_model_id"] == model_id
              and s["status"] == "VALIDATION_COMPLETE"
              and s["id"] != study["id"]]
    if others:
        return
    for variant in variants_of_model(model_id):
        if variant["status"] == "RELEASED":
            variant["validated_at"] = now_iso()
            touch(variant)


def settle_study_documentation(study):
    """PRD §3.3: "if no ModelDocumentation with doc_type MODEL_RISK_REPORT and a
    required_version_label equal to the model's version_label exists, one is
    created in DRAFT and the study's model_doc_id is bound to it; when the studied
    model stands in RELEASED, that same hop likewise carries it into DEPRECATED."

    This is part of the completion cascade, so it is applied by both run and
    revert. The version_label is the model's own -- not the predecessor's.
    """
    model = DB["score_models"][study["score_model_id"]]
    existing = doc_for_model_and_type(model, "MODEL_RISK_REPORT")
    if existing is None:
        document = new_record()
        document.update({
            "score_model_id": model["id"],
            "study_id": study["id"],
            "doc_type": "MODEL_RISK_REPORT",
            "required_version_label": model["version_label"],
            "status": "DRAFT",
            "filed_at": None,
            "checksum": "",
        })
        recompute_doc_checksum(document)
        store("model_documentation", document)
        study["model_doc_id"] = document["id"]
    else:
        study["model_doc_id"] = existing["id"]
    if model["status"] == "RELEASED":
        model["status"] = "DEPRECATED"
        touch(model)


# =============================================================================
# Fee ledger
# =============================================================================
def append_ledger_entry(license_rec, score_result_id, kind, cumulative_count_before, fee_cents, description):
    entry = new_record(common=False)
    entry.update({
        "license_id": license_rec["id"],
        "score_result_id": score_result_id,
        "kind": kind,
        "cumulative_count_before": cumulative_count_before,
        "fee_cents": fee_cents,
        "ledger_description": description,
    })
    store("fee_ledger_entries", entry)
    return entry


def accrue_marginal(license_rec, posting):
    cb = license_rec["cumulative_score_count"]
    fee = marginal_fee_cents(cb, license_rec["entitled_count"])
    license_rec["cumulative_score_count"] = cb + 1
    license_rec["cumulative_fee_cents"] = license_rec["cumulative_fee_cents"] + fee
    append_ledger_entry(
        license_rec,
        posting["id"],
        "MARGINAL_PRICING",
        cb,
        fee,
        f"Marginal pricing accrual for score posting {posting['id']} at cumulative count {cb + 1}.",
    )
    posting["_marginal_fee_cents"] = fee
    posting["_cumulative_count_before"] = cb
    # Entitlement crossing drives ACTIVE -> SUSPENDED as a side effect.
    if license_rec["status"] == "ACTIVE" and cb + 1 > license_rec["entitled_count"]:
        license_rec["status"] = "SUSPENDED"
    return fee