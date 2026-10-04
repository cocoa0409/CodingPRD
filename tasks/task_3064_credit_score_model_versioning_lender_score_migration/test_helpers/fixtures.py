"""Composite setup helpers for the multi-step preconditions the tests need.

Every helper builds its state from scratch through the API — each test starts
against a fresh, empty store. `get_success_data()` is used internally so a
broken setup surfaces as a clear "setup failed" error rather than as a
confusing assertion failure inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CREDIT_DUAL_AUTO, PRIME_SHIFT_AUTO, CREDIT_DUAL_LABEL, PRIME_SHIFT_LABEL
from .factories import (
    create_bureau_payload,
    create_score_model_payload,
    create_variant_payload,
    prime_shift_variant_payload,
    create_consumer_payload,
    create_archive_sample_payload,
    create_validation_study_payload,
    create_reference_set_payload,
    create_score_result_payload,
    create_reason_code_payload,
    create_license_payload,
    create_model_documentation_payload,
    create_migration_event_payload,
    unique,
)
from .test_users import TEST_USERS, make_score_consumer_headers

ADMIN = TEST_USERS["bureau_admin_headers"]
DEVELOPER = TEST_USERS["model_developer_headers"]
ANALYST = TEST_USERS["validation_analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
FAIR_LENDING = TEST_USERS["fair_lending_officer_headers"]
REASON_ADMIN = TEST_USERS["reason_code_admin_headers"]

# PRD §3.3 caps a sample's window_end_month at 2026-09, so the "touching at one
# endpoint month" case (half-open intervals, a legal adjacency) and the
# "two samples on one model" case must both live below that cap. DEV-A covers
# [2024-01, 2025-01); DEV-C opens at 2025-01, which is DEV-A's exclusive end, so
# the two windows touch without overlapping.
SAMPLE_BASE_START = "2024-01"
SAMPLE_BASE_END = "2025-01"
SAMPLE_TOUCHING_START = "2025-01"
SAMPLE_TOUCHING_END = "2026-01"


# ═══════════════════════════════════════════════════════
# Tier 1: Primitive builders
# ═══════════════════════════════════════════════════════

def register_bureau(bureau_code="TUC", display_name="TransUnion"):
    """Idempotent: a bureau_code is unique across the registry (PRD §2.3), so a
    helper that re-registers an existing code returns the existing row rather than
    tripping ERR_DUPLICATE_BUREAU_CODE. Lets two fixtures compose over one store."""
    res = api_client.create_bureau(
        create_bureau_payload(bureau_code=bureau_code, display_name=display_name), ADMIN)
    if res.status_code == 409 and res.json()["data"]["error_id"] == "ERR_DUPLICATE_BUREAU_CODE":
        existing = get_success_data(
            api_client.list_bureaus(ADMIN, params={"bureau_code": bureau_code}), 200)
        return existing[0]
    return get_success_data(res, 201)


def register_three_bureaus():
    return (
        register_bureau("TUC", "TransUnion"),
        register_bureau("EXP", "Experian"),
        register_bureau("EQF", "Equifax"),
    )


def create_model(version_label=CREDIT_DUAL_LABEL, family_code="FICO_CORE",
                 predecessor_model_id=None, min_input_count=100,
                 score_floor=None, score_ceiling=None):
    res = api_client.create_score_model(
        create_score_model_payload(
            family_code=family_code,
            version_label=version_label,
            predecessor_model_id=predecessor_model_id,
            min_input_count=min_input_count,
            score_floor=score_floor,
            score_ceiling=score_ceiling,
        ), DEVELOPER)
    return get_success_data(res, 201)


def author_variant(model_id, **overrides):
    res = api_client.create_variant(model_id, create_variant_payload(**overrides), DEVELOPER)
    return get_success_data(res, 201)


def release_variant(variant_id):
    return get_success_data(api_client.release_variant(variant_id, DEVELOPER), 200)


def recall_variant(variant_id):
    return get_success_data(api_client.recall_variant(variant_id, DEVELOPER), 200)


def create_consumer(consumer_ref=None, age_years=40, is_protected_class=None):
    res = api_client.create_consumer(
        create_consumer_payload(consumer_ref=consumer_ref, age_years=age_years,
                                is_protected_class=is_protected_class), DEVELOPER)
    return get_success_data(res, 201)


def file_risk_report(model_id, required_version_label):
    """Create a MODEL_RISK_REPORT and file it, unlocking the release gate."""
    md = get_success_data(api_client.create_model_documentation(
        create_model_documentation_payload(score_model_id=model_id,
                                           doc_type="MODEL_RISK_REPORT",
                                           required_version_label=required_version_label),
        COMPLIANCE), 201)
    filed = get_success_data(
        api_client.file_model_documentation(md["id"], md["version"], COMPLIANCE), 200)
    return filed


def release_model_with_doc(model_id, version_label):
    """File the risk report for `version_label`, then release the version."""
    file_risk_report(model_id, version_label)
    current = get_success_data(api_client.get_score_model(model_id, DEVELOPER), 200)
    released = get_success_data(
        api_client.release_model(model_id, current["version"], DEVELOPER), 200)
    return released


def refresh(entity_getter, entity_id, headers):
    """Re-read an entity so the caller holds its current version."""
    return get_success_data(entity_getter(entity_id, headers), 200)


def create_license(variant_id, lender_code="LEND-NORTH", **overrides):
    res = api_client.create_license(
        create_license_payload(score_variant_id=variant_id, lender_code=lender_code,
                               **overrides), COMPLIANCE)
    return get_success_data(res, 201)


def create_and_activate_license(variant_id, **overrides):
    lic = create_license(variant_id, **overrides)
    activated = get_success_data(
        api_client.activate_license(lic["id"], lic["version"], COMPLIANCE), 200)
    return activated


def licence_headers(license_id):
    """ScoreConsumer headers bound to the licence that will cover the write."""
    return make_score_consumer_headers(license_id)


def post_score(license_id, consumer_id, variant_id, bureau_id, raw_posted_score,
               migration_event_id=None, discovery_tag=None):
    """Post a score as the ScoreConsumer backing `license_id`, using the
    licence's current version so the OCC check passes."""
    current = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
    payload = create_score_result_payload(
        consumer_id=consumer_id, score_variant_id=variant_id, bureau_id=bureau_id,
        license_id=license_id, raw_posted_score=raw_posted_score,
        expected_license_version=current["version"],
        migration_event_id=migration_event_id, discovery_tag=discovery_tag)
    return get_success_data(
        api_client.create_score_result(payload, licence_headers(license_id)), 201)


def create_reason_code(variant_id, **overrides):
    res = api_client.create_reason_code(
        create_reason_code_payload(score_variant_id=variant_id, **overrides),
        REASON_ADMIN)
    return get_success_data(res, 201)


def create_reference_set(consumer_id, model_id, score_result_id=None):
    res = api_client.create_reference_set(
        create_reference_set_payload(consumer_id=consumer_id, score_model_id=model_id,
                                     score_result_id=score_result_id), FAIR_LENDING)
    return get_success_data(res, 201)


def attach_reason_code(reference_set_id, reason_code_id):
    current = get_success_data(
        api_client.get_reference_set(reference_set_id, FAIR_LENDING), 200)
    return get_success_data(
        api_client.attach_reason_code(reference_set_id, reason_code_id,
                                      current["version"], FAIR_LENDING), 200)


def create_archive_sample(model_id, **overrides):
    res = api_client.create_archive_sample(
        create_archive_sample_payload(score_model_id=model_id, **overrides), ANALYST)
    return get_success_data(res, 201)


def schedule_study(model_id, sample_id, study_path="CROSS_BUREAU", performed_by="va-001"):
    res = api_client.create_validation_study(
        create_validation_study_payload(score_model_id=model_id, sample_id=sample_id,
                                        study_path=study_path, performed_by=performed_by),
        ANALYST)
    return get_success_data(res, 201)


def run_study(study_id):
    current = get_success_data(api_client.get_validation_study(study_id, ANALYST), 200)
    return get_success_data(
        api_client.run_validation_study(study_id, current["version"], ANALYST), 200)


def acknowledge_study(study_id, finalized_by="flo-001", evidence_ref="EV-001"):
    current = get_success_data(api_client.get_validation_study(study_id, FAIR_LENDING), 200)
    return get_success_data(
        api_client.acknowledge_validation_study(study_id, finalized_by, evidence_ref,
                                                current["version"], FAIR_LENDING), 200)


def record_migration_event(from_variant_id, to_variant_id, event_type="RECALIBRATED",
                           **overrides):
    res = api_client.create_migration_event(
        create_migration_event_payload(from_score_variant_id=from_variant_id,
                                       to_score_variant_id=to_variant_id,
                                       event_type=event_type, **overrides), COMPLIANCE)
    return get_success_data(res, 201)


# ═══════════════════════════════════════════════════════
# Tier 2: The standard CREDIT-DUAL-V1 AUTO release
# ═══════════════════════════════════════════════════════

def setup_released_dual_auto(version_label=CREDIT_DUAL_LABEL, family_code="FICO_CORE",
                             variant_overrides=None, min_input_count=100):
    """One bureau + a RELEASED version carrying one RELEASED AUTO variant.

    Returns (bureau, model, variant).
    """
    bureau = register_bureau()
    model = create_model(version_label=version_label, family_code=family_code,
                         min_input_count=min_input_count)
    variant = author_variant(model["id"], **(variant_overrides or {}))
    release_variant(variant["id"])
    model = release_model_with_doc(model["id"], version_label)
    return bureau, model, variant


def setup_licensed_auto():
    """Released M1 + an ACTIVE licence + a consumer, ready to post.

    Returns a dict with keys: bureau, model, variant, license, consumer.
    """
    bureau, model, variant = setup_released_dual_auto()
    license_ = create_and_activate_license(variant["id"])
    consumer = create_consumer()
    return {"bureau": bureau, "model": model, "variant": variant,
            "license": license_, "consumer": consumer}


def setup_released_dual_auto_three_variants():
    """Released M1 carrying AUTO (0.42) / BANKCARD (0.33) / MORTGAGE (0.25).

    Returns (bureau, model, {industry: variant}).
    """
    bureau = register_bureau()
    model = create_model()
    variants = {}
    for industry, weight in (("AUTO", 0.42), ("BANKCARD", 0.33), ("MORTGAGE", 0.25)):
        v = author_variant(model["id"], industry=industry, aggregate_weight_pct=weight)
        release_variant(v["id"])
        variants[industry] = v
    model = release_model_with_doc(model["id"], CREDIT_DUAL_LABEL)
    return bureau, model, variants


# ═══════════════════════════════════════════════════════
# Tier 3: The two-version migration landscape
# ═══════════════════════════════════════════════════════

def setup_two_versions_same_family(supersede=False, second_variant_overrides=None):
    """Release M1, then create M2 in the same family.

    With `supersede=True` M2 names M1 as its predecessor and is released, which
    drives M1 to SUPERSEDED. Returns (bureau, m1, v1_auto, m2, v2_auto).
    """
    bureau = register_bureau()
    m1 = create_model(version_label=CREDIT_DUAL_LABEL)
    v1 = author_variant(m1["id"])
    release_variant(v1["id"])
    m1 = release_model_with_doc(m1["id"], CREDIT_DUAL_LABEL)

    m2 = create_model(version_label=PRIME_SHIFT_LABEL,
                      predecessor_model_id=m1["id"] if supersede else None)
    v2 = author_variant(m2["id"], **(second_variant_overrides or dict(PRIME_SHIFT_AUTO)))
    release_variant(v2["id"])
    if supersede:
        m2 = release_model_with_doc(m2["id"], PRIME_SHIFT_LABEL)
    return bureau, m1, v1, m2, v2


def setup_two_versions_released_sequentially():
    """M1 released, then a same-family M2 (no predecessor) also released.

    Both versions stay RELEASED. Returns (bureau, m1, v1, m2, v2).
    """
    bureau = register_bureau()
    m1 = create_model(version_label=CREDIT_DUAL_LABEL)
    v1 = author_variant(m1["id"])
    release_variant(v1["id"])
    m1 = release_model_with_doc(m1["id"], CREDIT_DUAL_LABEL)

    m2 = create_model(version_label=PRIME_SHIFT_LABEL)
    v2 = author_variant(m2["id"], **PRIME_SHIFT_AUTO)
    release_variant(v2["id"])
    m2 = release_model_with_doc(m2["id"], PRIME_SHIFT_LABEL)
    return bureau, m1, v1, m2, v2


def setup_two_released_variants_across_two_models():
    """M1 released with an AUTO variant; M9 (VANTAGE_STYLE) released with an AUTO
    variant. Used where a cross-model reference-set binding must be refused.

    Returns (bureau, m1, v1_auto, m9, v9_auto).
    """
    bureau = register_bureau()
    m1 = create_model(version_label=CREDIT_DUAL_LABEL, family_code="FICO_CORE")
    v1 = author_variant(m1["id"])
    release_variant(v1["id"])
    m1 = release_model_with_doc(m1["id"], CREDIT_DUAL_LABEL)

    m9 = create_model(version_label="VANTAGE-STYLE-V1", family_code="VANTAGE_STYLE")
    v9 = author_variant(m9["id"])
    release_variant(v9["id"])
    m9 = release_model_with_doc(m9["id"], "VANTAGE-STYLE-V1")
    return bureau, m1, v1, m9, v9

# ═══════════════════════════════════════════════════════
# Tier 4: Accumulation / threshold targeting
# ═══════════════════════════════════════════════════════

def setup_three_bureau_capture(consumer_ref="cons-901", sample_ref="XFER-01",
                               sample_kind="VALIDATION", study_path="CROSS_BUREAU"):
    """Three bureaus; a released M1 with AUTO/BANKCARD/MORTGAGE variants; three
    ACTIVE licences under one lender; three postings for one consumer, one per
    bureau; a VALIDATION archive sample; and a scheduled CROSS_BUREAU study.

    Returns a dict with the whole capture plus the effective scores.
    """
    tuc, exp, eqf = register_three_bureaus()
    _, m1, variants = setup_released_dual_auto_three_variants()
    consumer = create_consumer(consumer_ref=consumer_ref, age_years=44)

    lic = {}
    for industry in ("AUTO", "BANKCARD", "MORTGAGE"):
        lic[industry] = create_and_activate_license(
            variants[industry]["id"], lender_code="LEND-NORTH", entitled_count=500)

    sr = {}
    sr["AUTO"] = post_score(lic["AUTO"]["id"], consumer["id"], variants["AUTO"]["id"],
                            tuc["id"], 715)
    sr["BANKCARD"] = post_score(lic["BANKCARD"]["id"], consumer["id"],
                                variants["BANKCARD"]["id"], exp["id"], 717)
    sr["MORTGAGE"] = post_score(lic["MORTGAGE"]["id"], consumer["id"],
                                variants["MORTGAGE"]["id"], eqf["id"], 712)

    sample = create_archive_sample(m1["id"], sample_ref=sample_ref,
                                   record_count=5000, segment_name="PRIME",
                                   sample_kind=sample_kind,
                                   observation_window_months=24,
                                   window_start_month="2024-01",
                                   window_end_month="2026-01")
    study = schedule_study(m1["id"], sample["id"], study_path=study_path)
    return {"bureaus": (tuc, exp, eqf), "model": m1, "variants": variants,
            "licenses": lic, "consumer": consumer, "results": sr,
            "sample": sample, "study": study}


def setup_cross_bureau_study(consumer_ref="cons-902", sample_ref="XFER-02"):
    """A CROSS_BUREAU study that has already run, over a three-bureau capture.

    Returns (capture, study_after_run) where capture is the dict from
    setup_three_bureau_capture.
    """
    capture = setup_three_bureau_capture(consumer_ref=consumer_ref, sample_ref=sample_ref)
    study = run_study(capture["study"]["id"])
    return capture, study


def setup_license_with_postings(num_postings=2, entitled_count=500,
                                volume_tier="VOLUME_TIER_1", lender_code="LEND-NORTH",
                                consumer_ref="cons-770", raw_posted_score=715,
                                postings_at_boundary=False):
    """Released M1 variant + ACTIVE licence + consumer + N settled postings.

    Returns a dict with bureau, model, variant, license (current), consumer,
    and the list of settled postings.
    """
    bureau, model, variant = setup_released_dual_auto()
    license_ = create_and_activate_license(variant["id"], lender_code=lender_code,
                                           entitled_count=entitled_count,
                                           volume_tier=volume_tier)
    consumer = create_consumer(consumer_ref=consumer_ref, age_years=51)

    results = []
    for _ in range(num_postings):
        results.append(post_score(license_["id"], consumer["id"], variant["id"],
                                  bureau["id"], raw_posted_score))
    license_ = get_success_data(api_client.get_license(license_["id"], COMPLIANCE), 200)
    return {"bureau": bureau, "model": model, "variant": variant,
            "license": license_, "consumer": consumer, "results": results}


def setup_cost_cascade_fixture(consumer_ref="cons-502", num_postings=3):
    """The C10 archive cascade fixture.

    M1 released with a released AUTO variant; three ACTIVE reason codes
    (PRIMARY SEGMENT_ZERO 0.30, PRIMARY CUTOFF_EDGE 0.20, SECONDARY TOGGLE_A
    0.03); an ACTIVE licence; a consumer; ONE reference set bound to TOGGLE_A; and
    `num_postings` postings at raw 715, which lands on effective 700 -- exactly
    the cut-off -- so they begin UNDECIDED.

    Only one reference set is created: PRD §3.8 binds a posting to "the most
    recently created ReferenceSet belonging to the same consumer whose
    score_model_id equals the posting variant's model version", and the logical
    clock is frozen, so two same-instant sets would leave that choice to the
    ascending-id tie-break and make the fixture nondeterministic.

    Returns a dict with the pieces plus the TOGGLE_A reason code.
    """
    bureau, model, variant = setup_released_dual_auto()
    rc_seg = create_reason_code(variant["id"], depth_tier="PRIMARY",
                                trigger_feature_code="SEGMENT_ZERO",
                                code_label="rc-seg-zero", weight_pct=0.30)
    rc_edge = create_reason_code(variant["id"], depth_tier="PRIMARY",
                                 trigger_feature_code="CUTOFF_EDGE",
                                 code_label="rc-cutoff-edge", weight_pct=0.20)
    rc_tog = create_reason_code(variant["id"], depth_tier="SECONDARY",
                                trigger_feature_code="TOGGLE_A",
                                code_label="rc-toggle-a", weight_pct=0.03)

    consumer = create_consumer(consumer_ref=consumer_ref, age_years=36,
                               is_protected_class=True)
    license_ = create_and_activate_license(variant["id"])

    rs_a = create_reference_set(consumer["id"], model["id"])
    attach_reason_code(rs_a["id"], rc_tog["id"])

    results = []
    for _ in range(num_postings):
        results.append(post_score(license_["id"], consumer["id"], variant["id"],
                                  bureau["id"], 715))

    return {"bureau": bureau, "model": model, "variant": variant,
            "license": license_, "consumer": consumer, "results": results,
            "rs_a": rs_a,
            "rc_seg": rc_seg, "rc_edge": rc_edge, "rc_toggle": rc_tog}


def setup_migration_calibration_fixture(supersede=False):
    """M1 (CREDIT-DUAL-V1) released; M2 (PRIME-SHIFT-V2) in the same family with
    a released AUTO variant. Nothing is posted.

    Returns (bureau, m1, v1_auto, m2, v2_auto).
    """
    return setup_two_versions_same_family(supersede=supersede)


def setup_migration_credit_fixture():
    """M1 released with a same-family M2 variant, plus a licence held on M2's
    variant and a consumer. A RECALIBRATED migration event walks the lender from
    M1's variant onto M2's variant and carries -20 basis points.

    PRD §3.8: a supplied migration_event_id "must match the consumer, the
    licence, the model family and the from/to variant pair of the earliest
    unconsumed eligible event for this lender", so the consuming licence must be
    the one licensed on the event's target variant (a lender is walked *onto* the
    target, then posts under it).

    Returns a dict with the pieces and the recorded event.
    """
    bureau, m1, v1, m2, v2 = setup_two_versions_released_sequentially()
    consumer = create_consumer(consumer_ref="cons-902", age_years=38)
    license_ = create_and_activate_license(v2["id"], entitled_count=500)
    event = record_migration_event(v1["id"], v2["id"], event_type="RECALIBRATED",
                                   lender_code="LEND-NORTH",
                                   old_cutoff_score=640, evidence_ref="WS-2026-201")
    return {"bureau": bureau, "m1": m1, "v1": v1, "m2": m2, "v2": v2,
            "consumer": consumer, "license": license_, "event": event}


def setup_protected_class_partition(protected_approve=6, protected_decline=4,
                                    reference_approve=18, reference_decline=2,
                                    study_path="PROTECTED_CLASS"):
    """Released M1 with one ACTIVE PRIMARY reason code, a DEVELOPMENT sample, a
    PROTECTED_CLASS study, and postings partitioned into the approve/decline
    counts supplied.

    Values on the CREDIT-DUAL-V1 AUTO curve: raw 716 -> effective 701 (above the
    700 cut-off, APPROVE) and raw 714 -> effective 699 (below, DECLINE).

    Returns (capture_dict, study_after_run).
    """
    bureau, model, variant = setup_released_dual_auto()
    create_reason_code(variant["id"], depth_tier="PRIMARY",
                       trigger_feature_code="SEGMENT_ZERO", code_label="rc-di",
                       weight_pct=0.30)
    protected = create_consumer(consumer_ref="cons-di-P", age_years=34,
                                is_protected_class=True)
    reference = create_consumer(consumer_ref="cons-di-Q", age_years=45,
                                is_protected_class=False)
    license_ = create_and_activate_license(variant["id"], entitled_count=5000,
                                           volume_tier="VOLUME_TIER_3")
    sample = create_archive_sample(model["id"], sample_ref="DEV-DI", record_count=6000,
                                   segment_name="PRIME", sample_kind="DEVELOPMENT",
                                   observation_window_months=24,
                                   window_start_month="2024-01", window_end_month="2026-01")
    study = schedule_study(model["id"], sample["id"], study_path=study_path,
                           performed_by="va-di")

    plan = ([(protected, 716)] * protected_approve
            + [(protected, 714)] * protected_decline
            + [(reference, 716)] * reference_approve
            + [(reference, 714)] * reference_decline)
    for consumer, raw in plan:
        post_score(license_["id"], consumer["id"], variant["id"], bureau["id"], raw)

    study = run_study(study["id"])
    return {"bureau": bureau, "model": model, "variant": variant, "license": license_,
            "protected": protected, "reference": reference, "sample": sample}, study


def setup_archive_sample_containment():
    """Released M1 with one existing DEVELOPMENT sample DEV-A over
    [2024-01, 2025-01).

    Returns (bureau, model, variant, existing_sample).
    """
    bureau, model, variant = setup_released_dual_auto()
    sample = create_archive_sample(model["id"], sample_ref="DEV-A", record_count=8000,
                                   segment_name="PRIME", sample_kind="DEVELOPMENT",
                                   observation_window_months=12,
                                   window_start_month=SAMPLE_BASE_START,
                                   window_end_month=SAMPLE_BASE_END)
    return bureau, model, variant, sample


def setup_license_window_conflict():
    """Released M1 with an ACTIVE LEND-NORTH term [2026-01, 2027-01) and a PENDING
    LEND-SOUTH term on a later, non-colliding window [2027-01, 2028-01).

    The overlap rule is keyed on the (lender_code, variant) pair (PRD §3.7), so a
    *different* lender may open a term inside another lender's window; only a
    same-lender overlap is refused. Returns (bureau, model, variant, north, south).
    """
    bureau, model, variant = setup_released_dual_auto()
    north = create_and_activate_license(variant["id"], lender_code="LEND-NORTH",
                                        window_start_month="2026-01",
                                        window_end_month="2027-01")
    south = create_license(variant["id"], lender_code="LEND-SOUTH",
                           window_start_month="2027-01", window_end_month="2028-01")
    return bureau, model, variant, north, south


# ═══════════════════════════════════════════════════════
# Tier 5: Finalization / terminal state
# ═══════════════════════════════════════════════════════

def setup_retired_model(lender_code="LEND-LATE"):
    """Release M1, deprecate it with no ACTIVE licence, then retire it.

    Returns (bureau, retired_model, variant).
    """
    bureau, model, variant = setup_released_dual_auto()
    current = get_success_data(api_client.get_score_model(model["id"], COMPLIANCE), 200)
    api_client.deprecate_model(model["id"], current["version"], COMPLIANCE)
    current = get_success_data(api_client.get_score_model(model["id"], COMPLIANCE), 200)
    retired = get_success_data(
        api_client.retire_model(model["id"], current["version"], COMPLIANCE), 200)
    return bureau, retired, variant


def setup_deprecation_blocked():
    """Released M1 with an ACTIVE licence on its variant and a FILED
    ADVERSE_ACTION_MAP carrying the model's version label, so a termination can
    unlock the deprecation gate.

    Returns (bureau, model, variant, active_license).
    """
    bureau, model, variant = setup_released_dual_auto()
    license_ = create_and_activate_license(variant["id"])
    file_risk_report_for_termination(model["id"], CREDIT_DUAL_LABEL)
    return bureau, model, variant, license_


def file_risk_report_for_termination(model_id, version_label):
    """A FILED ADVERSE_ACTION_MAP carrying the licensed version label."""
    md = get_success_data(api_client.create_model_documentation(
        create_model_documentation_payload(score_model_id=model_id,
                                           doc_type="ADVERSE_ACTION_MAP",
                                           required_version_label=version_label),
        COMPLIANCE), 201)
    return get_success_data(
        api_client.file_model_documentation(md["id"], md["version"], COMPLIANCE), 200)


def setup_occ_posting_target(consumer_ref="cons-occ-1"):
    """Released M1, an ACTIVE licence with entitled_count 500, and one consumer.

    Returns (bureau, model, variant, license, consumer) with the licence in ACTIVE.
    """
    bureau, model, variant = setup_released_dual_auto()
    license_ = create_and_activate_license(variant["id"], entitled_count=500)
    consumer = create_consumer(consumer_ref=consumer_ref, age_years=37)
    return bureau, model, variant, license_, consumer


def setup_discovery_slot_consumed(tag="DISC-1", consumer_ref="cons-dt-1"):
    """Released M1, an ACTIVE licence, a consumer, one REGISTERED slot, and the
    first posting that consumes it.

    Returns a dict with the pieces plus the consumed posting.
    """
    bureau, model, variant = setup_released_dual_auto()
    license_ = create_and_activate_license(variant["id"])
    consumer = create_consumer(consumer_ref=consumer_ref, age_years=35)
    slot = get_success_data(
        api_client.create_discovery_request(tag, licence_headers(license_["id"])), 201)
    result = post_score(license_["id"], consumer["id"], variant["id"], bureau["id"],
                        715, discovery_tag=tag)
    return {"bureau": bureau, "model": model, "variant": variant, "license": license_,
            "consumer": consumer, "slot": slot, "result": result}


def setup_migration_event_list():
    """M1 and M2 released in the same family, each with a released AUTO variant,
    plus one RECALIBRATED crossing event and one SNAPSHOT_COMPILED self event.

    Returns (bureau, m1, v1, m2, v2, crossing_event, snapshot_event).
    """
    bureau, m1, v1, m2, v2 = setup_two_versions_released_sequentially()
    crossing = record_migration_event(v1["id"], v2["id"], event_type="RECALIBRATED",
                                      old_cutoff_score=640, evidence_ref="WS-FLT-1")
    snapshot = record_migration_event(v1["id"], v1["id"], event_type="SNAPSHOT_COMPILED",
                                      lender_code="LEND-SOUTH", evidence_ref="WS-FLT-2")
    return bureau, m1, v1, m2, v2, crossing, snapshot


def setup_reason_code_catalogue_tree():
    """Released M1 with a released AUTO variant and a three-node catalogue: a
    PRIMARY root, a SECONDARY child of it, and a TERTIARY child of the root.

    Returns (bureau, model, variant, root, child_a, child_b).
    """
    bureau, model, variant = setup_released_dual_auto()
    root = create_reason_code(variant["id"], depth_tier="PRIMARY",
                              trigger_feature_code="ROOT", code_label="rc-root",
                              weight_pct=0.20)
    child_a = create_reason_code(variant["id"], depth_tier="SECONDARY",
                                 trigger_feature_code="CHILD-A", code_label="rc-child-a",
                                 weight_pct=0.20, parent_reason_code_id=root["id"])
    child_b = create_reason_code(variant["id"], depth_tier="TERTIARY",
                                 trigger_feature_code="CHILD-B", code_label="rc-child-b",
                                 weight_pct=0.30, parent_reason_code_id=root["id"])
    return bureau, model, variant, root, child_a, child_b


def setup_bubble_up_tree():
    """A three-level catalogue: A (0.20, root), B (0.20, child of A), C (0.03,
    child of B) and a sibling D (0.30, child of B).

    Returns (bureau, model, variant, a, b, c, d).
    """
    bureau, model, variant = setup_released_dual_auto()
    a = create_reason_code(variant["id"], depth_tier="PRIMARY",
                           trigger_feature_code="A-ROOT", code_label="rc-a",
                           weight_pct=0.20)
    b = create_reason_code(variant["id"], depth_tier="SECONDARY",
                           trigger_feature_code="B-MID", code_label="rc-b",
                           weight_pct=0.20, parent_reason_code_id=a["id"])
    c = create_reason_code(variant["id"], depth_tier="TERTIARY",
                           trigger_feature_code="C-LEAF", code_label="rc-c",
                           weight_pct=0.03, parent_reason_code_id=b["id"])
    d = create_reason_code(variant["id"], depth_tier="TERTIARY",
                           trigger_feature_code="D-LEAF", code_label="rc-d",
                           weight_pct=0.30, parent_reason_code_id=b["id"])
    return bureau, model, variant, a, b, c, d


def setup_reference_set_bound_to_active_code(consumer_ref="cons-rs-1"):
    """Released M1 with one ACTIVE reason code and a consumer whose reference set
    has been attached to that code (status BOUND).

    Returns (bureau, model, variant, reason_code, consumer, reference_set).
    """
    bureau, model, variant = setup_released_dual_auto()
    rc = create_reason_code(variant["id"], depth_tier="PRIMARY",
                            trigger_feature_code="SEGMENT_ZERO", code_label="rc-active",
                            weight_pct=0.30)
    consumer = create_consumer(consumer_ref=consumer_ref, age_years=39)
    rs = create_reference_set(consumer["id"], model["id"])
    rs = attach_reason_code(rs["id"], rc["id"])
    return bureau, model, variant, rc, consumer, rs


def setup_reference_set_reconciled(consumer_ref="cons-601"):
    """Released M1 with an ACTIVE PRIMARY code and a consumer whose reference set
    was attached to a low-weight code and then reconciled.

    Returns (bureau, model, variant, resolvable_code, consumer, reference_set).
    """
    bureau, model, variant = setup_released_dual_auto()
    rc_seg = create_reason_code(variant["id"], depth_tier="PRIMARY",
                                trigger_feature_code="SEGMENT_ZERO",
                                code_label="rc-seg", weight_pct=0.30)
    rc_tog = create_reason_code(variant["id"], depth_tier="SECONDARY",
                                trigger_feature_code="TOGGLE", code_label="rc-toggle",
                                weight_pct=0.03)
    consumer = create_consumer(consumer_ref=consumer_ref, age_years=41)
    rs = create_reference_set(consumer["id"], model["id"])
    rs = attach_reason_code(rs["id"], rc_tog["id"])
    # Archiving the bound code is itself the C10 cascade: it reconciles the set
    # (PRD §3.6, hop one). Reconcile is the terminal move for a bound set, so no
    # separate reconcile call is needed or legal here.
    api_client.archive_reason_code(rc_tog["id"], REASON_ADMIN)
    rs = get_success_data(api_client.get_reference_set(rs["id"], FAIR_LENDING), 200)
    return bureau, model, variant, rc_seg, consumer, rs


# ═══════════════════════════════════════════════════════
# Tier 6: Scenario-specific composites
# ═══════════════════════════════════════════════════════

def setup_deprecated_version_with_blocked_study():
    """Release M1, schedule a CROSS_BUREAU study, deprecate M1 (no ACTIVE
    licence blocks it), then recall the variant so the study blocks.

    Returns a dict with model, variant, sample and study.
    """
    bureau, model, variant = setup_released_dual_auto()
    sample = create_archive_sample(model["id"], sample_ref="DEV-01", record_count=5000,
                                   segment_name="PRIME", sample_kind="VALIDATION",
                                   observation_window_months=24,
                                   window_start_month="2024-01", window_end_month="2026-01")
    study = schedule_study(model["id"], sample["id"], study_path="CROSS_BUREAU",
                           performed_by="va-001")
    current = get_success_data(api_client.get_score_model(model["id"], COMPLIANCE), 200)
    deprecated = get_success_data(
        api_client.deprecate_model(model["id"], current["version"], COMPLIANCE), 200)
    recall_variant(variant["id"])
    study_after = get_success_data(api_client.get_validation_study(study["id"], ANALYST), 200)
    return {"bureau": bureau, "model": deprecated, "variant": variant,
            "sample": sample, "study": study, "study_after": study_after}


def setup_reason_code_archive_cycle():
    """Released M1 with a released AUTO variant and two catalogue nodes: a
    SECONDARY root 'DUAL-DECISION' (weight 0.20) and a TERTIARY child
    'UNDECIDED-ESCALATED' (weight 0.03) parented to it.

    Returns (bureau, model, variant, root, child).
    """
    bureau, model, variant = setup_released_dual_auto()
    root = create_reason_code(variant["id"], depth_tier="SECONDARY",
                              trigger_feature_code="DUAL-DECISION",
                              code_label="root-dual-decision", weight_pct=0.20)
    child = create_reason_code(variant["id"], depth_tier="TERTIARY",
                               trigger_feature_code="UNDECIDED-ESCALATED",
                               code_label="child-undecided", weight_pct=0.03,
                               parent_reason_code_id=root["id"])
    return bureau, model, variant, root, child


def setup_reference_set_dependency():
    """Released M1 (AUTO + BANKCARD variants) and released M9 (VANTAGE_STYLE,
    AUTO variant), each carrying an ACTIVE PRIMARY reason code, plus one consumer
    holding a COMPILED reference set on each model.

    Returns a dict with the pieces and both reference sets.
    """
    bureau, m1, v1_auto, m9, v9_auto = setup_two_released_variants_across_two_models()
    rc_m1 = create_reason_code(v1_auto["id"], depth_tier="PRIMARY",
                               trigger_feature_code="SEGMENT_ZERO",
                               code_label="rc-m1-auto", weight_pct=0.30)
    rc_m9 = create_reason_code(v9_auto["id"], depth_tier="PRIMARY",
                               trigger_feature_code="SEGMENT_ZERO",
                               code_label="rc-m9-auto", weight_pct=0.30)
    consumer = create_consumer(consumer_ref="cons-801", age_years=44)
    rs1 = create_reference_set(consumer["id"], m1["id"])
    rs9 = create_reference_set(consumer["id"], m9["id"])
    return {"bureau": bureau, "m1": m1, "v1_auto": v1_auto, "m9": m9,
            "v9_auto": v9_auto, "rc_m1": rc_m1, "rc_m9": rc_m9,
            "consumer": consumer, "rs1": rs1, "rs9": rs9}


def setup_probationary_and_retired_licences():
    """M1 released; M2 releases naming M1 as predecessor (M1 → SUPERSEDED).
    Two PENDING licences sit on M1's variant, plus one reference set on M1.

    Returns a dict with the pieces.
    """
    bureau = register_bureau()
    m1 = create_model(version_label=CREDIT_DUAL_LABEL)
    v1 = author_variant(m1["id"])
    release_variant(v1["id"])
    m1 = release_model_with_doc(m1["id"], CREDIT_DUAL_LABEL)

    lic_w = create_license(v1["id"], lender_code="LEND-WEST")
    lic_e = create_license(v1["id"], lender_code="LEND-EAST")
    consumer = create_consumer(consumer_ref="cons-401", age_years=47)
    rs = create_reference_set(consumer["id"], m1["id"])

    m2 = create_model(version_label=PRIME_SHIFT_LABEL, predecessor_model_id=m1["id"])
    v2 = author_variant(m2["id"], **PRIME_SHIFT_AUTO)
    release_variant(v2["id"])
    m2 = release_model_with_doc(m2["id"], PRIME_SHIFT_LABEL)

    m1_after = get_success_data(api_client.get_score_model(m1["id"], COMPLIANCE), 200)
    return {"bureau": bureau, "m1": m1_after, "v1": v1, "m2": m2, "v2": v2,
            "lic_w": lic_w, "lic_e": lic_e, "consumer": consumer, "rs": rs}


def setup_retirement_blocked_by_reference_set():
    """M1 released carrying one live COMPILED reference set, then deprecated with
    no ACTIVE licence anywhere.

    Retirement is the terminal model move and is only permitted out of DEPRECATED
    (PRD §3.2): "A ComplianceOfficer may retire a deprecated version only when no
    reference set on it sits outside RECONCILED; a live compiled or bound
    reference set blocks the move with ERR_RETIREMENT_BLOCKED." The version is
    therefore left DEPRECATED, the reference set still COMPILED.

    Returns (bureau, deprecated_m1, m1_variant, reference_set).
    """
    bureau, model, variant = setup_released_dual_auto()
    consumer = create_consumer(consumer_ref="cons-402", age_years=47)
    refset = create_reference_set(consumer["id"], model["id"])

    current = get_success_data(api_client.get_score_model(model["id"], COMPLIANCE), 200)
    deprecated = get_success_data(
        api_client.deprecate_model(model["id"], current["version"], COMPLIANCE), 200)
    return bureau, deprecated, variant, refset


def setup_cascade_release_fixture():
    """M1 released with an ACTIVE licence and a BOUND reference set carrying one
    settled posting; M2 sits in the same family naming M1 as predecessor with its
    own released variant and a FILED risk report.

    Returns a dict with the pieces (M2 not yet released).
    """
    bureau = register_bureau()
    m1 = create_model(version_label=CREDIT_DUAL_LABEL)
    v1 = author_variant(m1["id"])
    release_variant(v1["id"])
    m1 = release_model_with_doc(m1["id"], CREDIT_DUAL_LABEL)

    consumer = create_consumer(consumer_ref="cons-401", age_years=47)
    rs = create_reference_set(consumer["id"], m1["id"])
    rc = create_reason_code(v1["id"], depth_tier="PRIMARY",
                            trigger_feature_code="SEGMENT_ZERO",
                            code_label="rc-seg-zero", weight_pct=0.30)
    license_ = create_and_activate_license(v1["id"])
    post_score(license_["id"], consumer["id"], v1["id"], bureau["id"], 715)
    rs = attach_reason_code(rs["id"], rc["id"])

    m2 = create_model(version_label=PRIME_SHIFT_LABEL, predecessor_model_id=m1["id"])
    v2 = author_variant(m2["id"], **PRIME_SHIFT_AUTO)
    release_variant(v2["id"])
    file_risk_report(m2["id"], PRIME_SHIFT_LABEL)
    return {"bureau": bureau, "m1": m1, "v1": v1, "m2": m2, "v2": v2,
            "license": license_, "consumer": consumer, "rs": rs, "rc": rc}


def setup_probationary_licences_two_versions():
    """Same shape as setup_probationary_and_retired_licences, kept separate so
    the retirement-gate test owns its own fixture name."""
    return setup_probationary_and_retired_licences()
