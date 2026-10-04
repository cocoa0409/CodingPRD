"""Compliance track: removal-order windows, the apply/reverse cascades across
document visibility, citing references, citator signals and headnotes, and the
independent ingestion/visibility axes (PRD §3.1, §3.8)."""
from test_helpers import (
    CLOCK_SEP_05,
    CLOCK_SEP_15,
    ApiErrorId,
    apply_removal_order,
    create_citing_document,
    create_document,
    create_published_document,
    create_published_headnote,
    create_removal_order,
    get_document,
    get_headnote,
    list_citing_references,
    publish_document,
    removal_order_payload,
    reverse_removal_order,
    seal_document,
    set_clock,
    validate_error,
    validate_success,
)


def _setup_sealed_citing_pair():
    """B published; A published citing B OVERRULED/EXAMINED (B: score 100, RED);
    SEAL order docketed on A. Returns (doc_b, doc_a, order)."""
    set_clock(CLOCK_SEP_05)
    doc_b = create_published_document(
        source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
        title="B v. Cited", raw_citation_string="700 F.3d 10", decision_date="2026-01-10",
    )
    doc_a = create_citing_document(
        doc_b["id"], "OVERRULED", "EXAMINED",
        source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
        title="A v. Sealed", raw_citation_string="701 F.3d 20", decision_date="2026-02-10",
    )
    set_clock(CLOCK_SEP_15)
    order = create_removal_order(doc_a["id"], scope="SEAL", reason="Seal order")
    return doc_b, doc_a, order


def test_seal_applies_while_received(api):
    """PRD §3.1: "These axes are independent — a document may be sealed while still
    `RECEIVED` and later published into the combination of `PUBLISHED` ingestion
    and `SEALED` visibility."

    Design: Difficulty/non_linear_state_machine/document_parallel_ingestion_visibility_axes
    """
    set_clock(CLOCK_SEP_15)
    doc = create_document(
        source_type="LEGISLATURE", jurisdiction_code="US", document_type="STATUTE",
        title="Parallel Act", raw_citation_string="15 U.S.C. 7001", decision_date="2026-01-01",
    )
    order = create_removal_order(
        doc["id"], scope="SEAL", effective_from="2026-09-01",
        effective_until="2026-09-30", reason="Court order 26-991",
    )
    apply_removal_order(order["id"])
    sealed = get_document(doc["id"])
    assert sealed["ingestion_status"] == "RECEIVED", "sealing does not require publication"
    assert sealed["visibility_status"] == "SEALED"

    published = publish_document(doc["id"], references=[])
    assert published["ingestion_status"] == "PUBLISHED"
    assert published["visibility_status"] == "SEALED", (
        "publish moved only the ingestion axis"
    )


def test_reverse_restores_public_after_publish(api):
    """PRD §3.1: "These axes are independent — a document may be sealed while still
    `RECEIVED` and later published into the combination of `PUBLISHED` ingestion
    and `SEALED` visibility."
    PRD §3.8: "Moving an `APPLIED` order to `REVERSED` — the order's terminal state
    — restores the document's visibility from `SEALED` or `REMOVED` back to
    `PUBLIC`"

    Design: Difficulty/non_linear_state_machine/document_parallel_ingestion_visibility_axes
    """
    set_clock(CLOCK_SEP_15)
    doc = create_document(
        source_type="LEGISLATURE", jurisdiction_code="US", document_type="STATUTE",
        title="Parallel Act", raw_citation_string="15 U.S.C. 7001", decision_date="2026-01-01",
    )
    order = create_removal_order(
        doc["id"], scope="SEAL", effective_from="2026-09-01",
        effective_until="2026-09-30", reason="Court order 26-991",
    )
    apply_removal_order(order["id"])
    publish_document(doc["id"], references=[])
    reverse_removal_order(order["id"])
    restored = get_document(doc["id"])
    assert restored["ingestion_status"] == "PUBLISHED", "reverse moved only the visibility axis"
    assert restored["visibility_status"] == "PUBLIC"


def test_removal_apply_seals_document_and_deactivates_references(api):
    """PRD §3.8: "Every CitingReference whose `citing_document_id` is the target
    document and whose `status` is still `ACTIVE` flips to `INACTIVE`, recording
    the order's id in `deactivated_by_order_id` and bumping its own `version`; each
    such flip recomputes the cited document's `citator_score` and `citator_signal`
    under §2.6; every `PUBLISHED` Headnote on the target document is retracted to
    `RETRACTED`, permanently"

    Design: Difficulty/transitive_cascade/removal_apply_depth3_citator_collapse
    """
    doc_b, doc_a, order = _setup_sealed_citing_pair()
    apply_removal_order(order["id"])

    doc_a = get_document(doc_a["id"])
    assert doc_a["visibility_status"] == "SEALED"

    refs = list_citing_references(doc_a["id"], direction="FROM")
    assert len(refs) == 1
    assert refs[0]["status"] == "INACTIVE"
    assert refs[0]["deactivated_by_order_id"] == order["id"]


def test_removal_apply_collapses_cited_score_and_retracts_headnote(api):
    """PRD §3.8: "Every CitingReference whose `citing_document_id` is the target
    document and whose `status` is still `ACTIVE` flips to `INACTIVE`, recording
    the order's id in `deactivated_by_order_id` and bumping its own `version`; each
    such flip recomputes the cited document's `citator_score` and `citator_signal`
    under §2.6; every `PUBLISHED` Headnote on the target document is retracted to
    `RETRACTED`, permanently"

    Design: Difficulty/transitive_cascade/removal_apply_depth3_citator_collapse
    """
    set_clock(CLOCK_SEP_05)
    doc_b = create_published_document(
        source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
        title="B v. Cited", raw_citation_string="700 F.3d 10", decision_date="2026-01-10",
    )
    doc_a = create_citing_document(
        doc_b["id"], "OVERRULED", "EXAMINED",
        source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
        title="A v. Sealed", raw_citation_string="701 F.3d 20", decision_date="2026-02-10",
    )
    headnote = create_published_headnote(doc_a["id"], "ed-author-1", "ed-reviewer-1")
    assert headnote["status"] == "PUBLISHED"
    set_clock(CLOCK_SEP_15)
    order = create_removal_order(doc_a["id"], scope="SEAL", reason="Seal order")
    apply_removal_order(order["id"])

    doc_b = get_document(doc_b["id"])
    assert doc_b["citator_score"] == 0, "the deactivation, not the order, caused the recompute"
    assert doc_b["citator_signal"] == "GREEN"
    assert get_headnote(headnote["id"])["status"] == "RETRACTED"


def test_apply_deactivates_references_and_zeroes_score(api):
    """PRD §3.8: "Every CitingReference whose `citing_document_id` is the target
    document and whose `status` is still `ACTIVE` flips to `INACTIVE`, recording
    the order's id in `deactivated_by_order_id` and bumping its own `version`; each
    such flip recomputes the cited document's `citator_score` and `citator_signal`
    under §2.6"

    Design: Difficulty/compensating_invariant/removal_apply_reverse_restores_citator_quantities
    """
    doc_b, doc_a, order = _setup_sealed_citing_pair()
    baseline_refs = list_citing_references(doc_b["id"], direction="TO", status="ACTIVE")
    assert len(baseline_refs) == 1
    assert get_document(doc_b["id"])["citator_score"] == 100

    apply_removal_order(order["id"])
    active_refs = list_citing_references(doc_b["id"], direction="TO", status="ACTIVE")
    assert len(active_refs) == 0
    doc_b = get_document(doc_b["id"])
    assert doc_b["citator_score"] == 0
    assert doc_b["citator_signal"] == "GREEN"
    assert get_document(doc_a["id"])["visibility_status"] == "SEALED"


def test_reverse_restores_reference_set_and_signal(api):
    """PRD §3.8: "every CitingReference whose `deactivated_by_order_id` equals this
    order's id flips back to `ACTIVE`, clears the field to null, and bumps its
    `version`, and each reactivation recomputes the cited document's citator
    fields, restoring the pre-apply values."

    Design: Difficulty/compensating_invariant/removal_apply_reverse_restores_citator_quantities
    """
    doc_b, doc_a, order = _setup_sealed_citing_pair()
    apply_removal_order(order["id"])
    reverse_removal_order(order["id"])

    active_refs = list_citing_references(doc_b["id"], direction="TO", status="ACTIVE")
    assert len(active_refs) == 1, "reversal restores exactly the pre-apply reference set"
    assert active_refs[0]["deactivated_by_order_id"] is None
    doc_b = get_document(doc_b["id"])
    assert doc_b["citator_score"] == 100, "restored to the exact pre-apply value"
    assert doc_b["citator_signal"] == "RED"
    assert get_document(doc_a["id"])["visibility_status"] == "PUBLIC"


def test_empty_reference_set_score_collapses_to_zero(api):
    """PRD §2.6: "References that fail any leg of that test contribute nothing. When
    no reference qualifies, the score is 0."

    Design: Difficulty/boundary_precision_check/citator_empty_reference_set_collapses_to_green
    """
    doc_b, doc_a, order = _setup_sealed_citing_pair()
    assert get_document(doc_b["id"])["citator_score"] == 100
    apply_removal_order(order["id"])
    doc_b = get_document(doc_b["id"])
    assert doc_b["citator_score"] == 0, "empty eligible set -> 0, not the stale 100"


def test_empty_reference_set_signal_green(api):
    """PRD §2.6: "References that fail any leg of that test contribute nothing. When
    no reference qualifies, the score is 0."
    PRD §2.6: "When the score reaches at least 80 the signal is `RED`; below that,
    a score of at least 40 yields `YELLOW`; anything lower — including negative
    scores — yields `GREEN`."

    Design: Difficulty/boundary_precision_check/citator_empty_reference_set_collapses_to_green
    """
    doc_b, doc_a, order = _setup_sealed_citing_pair()
    apply_removal_order(order["id"])
    active_refs = list_citing_references(doc_b["id"], direction="TO", status="ACTIVE")
    assert len(active_refs) == 0, "the sole reference flipped to INACTIVE"
    doc_b = get_document(doc_b["id"])
    assert doc_b["citator_signal"] == "GREEN"


def test_adjacent_removal_order_rejected_closed_interval(api):
    """PRD §3.8: "Orders on the same document must not crowd each other: among
    orders still in `RECEIVED` or `APPLIED` status, any overlap of their closed
    windows is rejected with `ERR_REMOVAL_WINDOW_OVERLAP` (HTTP 409), and because
    the interval is closed, even adjacency — one order's `effective_until` equaling
    the next order's `effective_from` — already counts as overlap."

    Design: Difficulty/resource_temporal_overlap/removal_order_closed_interval_adjacency_rejected
    """
    set_clock(CLOCK_SEP_05)
    doc = create_published_document(
        title="Window v. Order", raw_citation_string="900 So.3d 1", jurisdiction_code="FL",
        decision_date="2026-02-01",
    )
    create_removal_order(doc["id"], scope="SEAL", effective_from="2026-09-01",
                         effective_until="2026-09-30", reason="O1")
    resp = api.create_removal_order(
        removal_order_payload(doc["id"], scope="REMOVE", effective_from="2026-09-30",
                              effective_until="2026-10-15", reason="O2 adjacent"),
        headers={"X-User-ID": "co-1", "X-User-Role": "ComplianceOfficer"},
    )
    validate_error(resp, ApiErrorId.ERR_REMOVAL_WINDOW_OVERLAP, 409)


def test_disjoint_removal_order_accepted(api):
    """PRD §3.8: "Orders on the same document must not crowd each other: among
    orders still in `RECEIVED` or `APPLIED` status, any overlap of their closed
    windows is rejected with `ERR_REMOVAL_WINDOW_OVERLAP` (HTTP 409), and because
    the interval is closed, even adjacency — one order's `effective_until` equaling
    the next order's `effective_from` — already counts as overlap."

    Design: Difficulty/resource_temporal_overlap/removal_order_closed_interval_adjacency_rejected
    """
    set_clock(CLOCK_SEP_05)
    doc = create_published_document(
        title="Window v. Order", raw_citation_string="900 So.3d 1", jurisdiction_code="FL",
        decision_date="2026-02-01",
    )
    create_removal_order(doc["id"], scope="SEAL", effective_from="2026-09-01",
                         effective_until="2026-09-30", reason="O1")
    resp = api.create_removal_order(
        removal_order_payload(doc["id"], scope="REMOVE", effective_from="2026-10-01",
                              effective_until="2026-10-31", reason="O3 disjoint"),
        headers={"X-User-ID": "co-1", "X-User-Role": "ComplianceOfficer"},
    )
    data = validate_success(resp, 201)
    assert data["status"] == "RECEIVED"
    assert data["effective_from"] == "2026-10-01"


def test_reverse_received_order_rejected(api):
    """PRD §3.8: "Each order transition increments the order's own `version` by one,
    and any transition outside the `RECEIVED`-to-`APPLIED`-to-`REVERSED` chain —
    re-applying an applied order, reversing a merely received one — fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reverse_received_order_rejected
    """
    set_clock(CLOCK_SEP_15)
    doc = create_published_document(
        title="Skip v. Apply", raw_citation_string="30 P.3d 5", jurisdiction_code="WA",
    )
    order = create_removal_order(doc["id"], scope="SEAL", reason="early reverse")
    resp = api.transition_removal_order(
        order["id"], {"target_status": "REVERSED"},
        headers={"X-User-ID": "co-1", "X-User-Role": "ComplianceOfficer"},
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    order_after = validate_success(api.get_removal_order(
        order["id"], headers={"X-User-ID": "co-1", "X-User-Role": "ComplianceOfficer"},
    ))
    assert order_after["status"] == "RECEIVED"
    assert get_document(doc["id"])["visibility_status"] == "PUBLIC"


def test_removed_document_read_returns_document_removed(api, content_ingester_headers):
    """PRD §3.8: "A `REMOVE` scope adds one further consequence: subsequent
    single-document reads of the target fail with `ERR_DOCUMENT_REMOVED`, and the
    document vanishes from list results unless the caller explicitly filters
    `visibility_status` to `REMOVED` (§2.10)."

    Design: Corner/errors/removed_document_read_returns_document_removed
    """
    set_clock(CLOCK_SEP_15)
    doc = create_published_document(
        title="Gone v. Read", raw_citation_string="90 P.3d 1", jurisdiction_code="AZ",
    )
    seal_document(doc["id"], scope="REMOVE", reason="withdraw")
    resp = api.get_document(doc["id"], content_ingester_headers)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_REMOVED, 404)


def test_licensing_manager_cannot_docket_removal_order(api, licensing_manager_headers):
    """PRD §2.1: "Each endpoint admits a specific subset of these roles; a request
    whose role is not on that list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/licensing_manager_cannot_docket_removal_order
    """
    set_clock(CLOCK_SEP_05)
    doc = create_document(
        title="Role v. Order", raw_citation_string="97 P.3d 5", jurisdiction_code="UT",
    )
    resp = api.create_removal_order(
        removal_order_payload(doc["id"], scope="SEAL", reason="nope"),
        licensing_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
