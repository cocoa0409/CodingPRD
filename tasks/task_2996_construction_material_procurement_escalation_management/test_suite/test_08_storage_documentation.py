"""Compliance tests for bailment documentation on an off-site storage arrangement.

Covers PRD §3.7 — filing evidence against an arrangement, the distinct-mandatory-type
completeness count that ignores duplicates and inventory photographs, the
server-derived arrangement status that bubbles up from its document children,
insurance coverage sufficiency, the stored-value ceiling against the commitment, and
the revocation cascade that reaches the commitment's delivery posture.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    arrange_storage,
    assert_instant_equals,
    assert_purchase_commitment,
    assert_storage_arrangement,
    assert_storage_document,
    build_fabricating_scenario,
    build_released_scenario,
    build_stored_offsite_scenario,
    file_document,
    list_documents,
    make_supplier_rep_headers,
    read_arrangement,
    read_commitment,
    read_package,
    revoke_document,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_storage_arrangement_payload,
    create_storage_document_payload,
    delivery_posture_payload,
)

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]

_STEEL_READINGS_FULL = (
    ("2026-07", 310.00),
    ("2026-08", 322.00),
    ("2026-09", 331.00),
    ("2026-12", 344.50),
)
_STEEL_READINGS_JUL_AUG = (("2026-07", 310.00), ("2026-08", 322.00))

_CLAUSE_TERMS = {
    "baseline_index_period": "2026-07",
    "cap_pct": 8.0,
    "contractor_share_pct": 40.0,
    "deadband_pct": 2.0,
}

_DOC_EXPIRES_AT = "2027-06-01T00:00:00.000Z"


# ─── setup helpers (not tests: no Design tag) ─────────────────────────────

def _find_document(documents, doc_type, *, revoked=False):
    """The one document of `doc_type` on the list with the requested revoked flag."""
    matches = [
        doc for doc in documents if doc["doc_type"] == doc_type and doc["revoked"] is revoked
    ]
    assert len(matches) == 1, f"expected exactly one {doc_type} with revoked={revoked}"
    return matches[0]


def _setup_documented_storage():
    """An early-buyout steel commitment at STORED_OFFSITE with all three documents on file."""
    return build_stored_offsite_scenario(
        release_at="2026-09-10T00:00:00.000Z",
        stored_from="2026-09-20T00:00:00.000Z",
        planned_release_date="2026-12-31T00:00:00.000Z",
        stored_value=862500.00,
        monthly_storage_rate_pct=0.1875,
        warehouse_name="Harbor Yard 7",
        doc_effective_date="2026-09-01T00:00:00.000Z",
        doc_expires_at=_DOC_EXPIRES_AT,
        readings=_STEEL_READINGS_FULL,
        project_overrides={"escalation_contingency_budget": 500000.00},
        package_overrides={"estimated_cost": 1200000.00},
        quote_overrides={"base_price": 1150000.00},
        clause_overrides=dict(_CLAUSE_TERMS),
    )


def _setup_early_buyout_fabricating(*, release_at, readings):
    """An early-buyout steel commitment carried to FABRICATING at `release_at`."""
    return build_fabricating_scenario(
        release_at=release_at,
        readings=readings,
        project_overrides={"escalation_contingency_budget": 500000.00},
        package_overrides={"estimated_cost": 1200000.00},
        quote_overrides={"base_price": 1150000.00},
        clause_overrides=dict(_CLAUSE_TERMS),
        commitment_overrides={"is_early_buyout": True},
    )


def _setup_early_buyout_released(*, release_at, readings, base_price=1150000.00):
    """An early-buyout steel commitment sitting at RELEASED_FOR_FAB."""
    return build_released_scenario(
        release_at=release_at,
        readings=readings,
        project_overrides={"escalation_contingency_budget": 500000.00},
        package_overrides={"estimated_cost": 1200000.00},
        quote_overrides={"base_price": base_price},
        clause_overrides=dict(_CLAUSE_TERMS),
        commitment_overrides={"is_early_buyout": True},
    )


def _setup_undocumented_arrangement():
    """A FABRICATING early buyout whose arrangement carries only two mandatory types."""
    scenario = _setup_early_buyout_fabricating(
        release_at="2026-09-10T00:00:00.000Z", readings=_STEEL_READINGS_FULL
    )
    arrangement = arrange_storage(
        scenario["commitment"]["id"],
        warehouse_name="Harbor Yard 7",
        stored_value=862500.00,
        monthly_storage_rate_pct=0.1875,
        stored_from="2026-09-20T00:00:00.000Z",
        planned_release_date="2026-12-31T00:00:00.000Z",
    )
    for doc_type, reference in (
        ("BAILMENT_AGREEMENT", "BAIL-2996-001"),
        ("LIEN_WAIVER", "LW-2996-001"),
    ):
        file_document(
            arrangement["id"],
            doc_type=doc_type,
            reference_number=reference,
            effective_date="2026-09-01T00:00:00.000Z",
            expires_at=_DOC_EXPIRES_AT,
            verified=True,
        )
    set_clock("2026-09-20T00:00:00.000Z")
    scenario["arrangement"] = read_arrangement(arrangement["id"])
    return scenario


def _setup_draft_arrangement(*, release_at, readings, doc_effective_date, filings):
    """A RELEASED_FOR_FAB early buyout with a DRAFT arrangement and `filings` on file."""
    scenario = _setup_early_buyout_released(release_at=release_at, readings=readings)
    arrangement = arrange_storage(
        scenario["commitment"]["id"],
        warehouse_name="Harbor Yard 7",
        stored_value=862500.00,
        monthly_storage_rate_pct=0.1875,
        stored_from="2026-09-20T00:00:00.000Z",
        planned_release_date="2026-12-31T00:00:00.000Z",
    )
    for filing in filings:
        file_document(
            arrangement["id"],
            effective_date=doc_effective_date,
            expires_at=_DOC_EXPIRES_AT,
            **filing,
        )
    scenario["arrangement"] = read_arrangement(arrangement["id"])
    return scenario


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / document_revocation_suspends_arrangement_and_flags_posture
# ---------------------------------------------------------------------------

_REVOCATION_REASON = "Carrier cancelled the certificate for non-payment"


def test_storage_document_revocation_marks_the_document_and_suspends_the_arrangement():
    """Revoking the insurance certificate stamps the document and drops the arrangement.

    The revocation records the supplied reason and stamps `revoked_at` with the
    2026-09-20 clock. A revoked document no longer qualifies, so the mandatory set
    falls from three distinct types to two, the derived `documentation_status` becomes
    INCOMPLETE and the ACTIVE arrangement drops to SUSPENDED.

    PRD §3.7: "Revoking a document records the supplied `revocation_reason`, sets `revoked` to true and stamps `revoked_at` with the current clock."
    PRD §3.7: "If losing that document leaves the mandatory set incomplete, the arrangement drops from `ACTIVE` to `SUSPENDED`, its `documentation_status` becomes `INCOMPLETE` and its `verified_doc_type_count` decrements accordingly"
    PRD §3.7: "A document qualifies when it is not revoked, its `verified` flag is true, the current logical clock is at or after its `effective_date` and strictly before its `expires_at`, and — for an insurance certificate only — its `coverage_amount` is at least the arrangement's `stored_value`."
    PRD §3.7: "`documentation_status` is `COMPLETE` when that count is exactly 3, and `INCOMPLETE` otherwise."

    Design: Difficulty/transitive_cascade/document_revocation_suspends_arrangement_and_flags_posture
    """
    scenario = _setup_documented_storage()
    arrangement_id = scenario["arrangement"]["id"]
    assert scenario["arrangement"]["status"] == "ACTIVE"
    assert scenario["arrangement"]["verified_doc_type_count"] == 3

    certificate = _find_document(list_documents(arrangement_id), "INSURANCE_CERTIFICATE")
    revoked = revoke_document(certificate["id"], revocation_reason=_REVOCATION_REASON)
    assert_storage_document(revoked)
    assert revoked["revoked"] is True
    assert revoked["revocation_reason"] == _REVOCATION_REASON
    assert_instant_equals(revoked["revoked_at"], "2026-09-20T00:00:00.000Z")

    suspended = read_arrangement(arrangement_id)
    assert_storage_arrangement(suspended)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["documentation_status"] == "INCOMPLETE"
    assert suspended["verified_doc_type_count"] == 2


def test_storage_document_revocation_flags_the_posture_without_unwinding_the_order():
    """The third hop of the cascade reaches the commitment's physical axis only.

    Because the commitment was sitting at STORED_OFFSITE when the certificate was
    revoked, its `delivery_posture` moves to STORAGE_NONCOMPLIANT — but the
    contractual axis is deliberately left at COMMITTED and the scope package stays
    BOUGHT_OUT, since lapsed paperwork does not unwind a purchase order.

    PRD §3.7: "and if the commitment holding that material is sitting at `STORED_OFFSITE`, its `delivery_posture` moves to `STORAGE_NONCOMPLIANT` while its `commitment_status` is deliberately left at `COMMITTED` — the paperwork lapsing does not unwind the purchase order"
    PRD §2.10: "Revoking a storage document runs a three-hop chain: the document is marked revoked, its arrangement falls from `ACTIVE` to `SUSPENDED`, and the commitment holding that material moves its delivery posture from `STORED_OFFSITE` to `STORAGE_NONCOMPLIANT` — while its `commitment_status` is deliberately left alone."

    Design: Difficulty/transitive_cascade/document_revocation_suspends_arrangement_and_flags_posture
    """
    scenario = _setup_documented_storage()
    arrangement_id = scenario["arrangement"]["id"]
    commitment_id = scenario["commitment"]["id"]
    assert scenario["commitment"]["delivery_posture"] == "STORED_OFFSITE"

    certificate = _find_document(list_documents(arrangement_id), "INSURANCE_CERTIFICATE")
    revoke_document(certificate["id"], revocation_reason=_REVOCATION_REASON)

    flagged = read_commitment(commitment_id)
    assert_purchase_commitment(flagged)
    assert flagged["delivery_posture"] == "STORAGE_NONCOMPLIANT"
    assert flagged["commitment_status"] == "COMMITTED"
    assert flagged["delivered_at"] is None

    package = read_package(scenario["package"]["id"])
    assert package["status"] == "BOUGHT_OUT"


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / posture_stored_offsite_blocked_by_undocumented_arrangement
# ---------------------------------------------------------------------------

def test_storage_posture_stored_offsite_blocked_while_the_arrangement_is_undocumented():
    """FABRICATING → STORED_OFFSITE is refused when the bailment paperwork is short a type.

    Only a bailment agreement and a lien waiver are on file, so the arrangement is
    still DRAFT and INCOMPLETE even though the clock has reached its `stored_from`.
    The posture move consults that other row and is refused, leaving the commitment
    at FABRICATING on a contractual axis that is still COMMITTED.

    PRD §3.6: "**Moving into storage** takes the posture from `FABRICATING` to `STORED_OFFSITE`, and it requires that a storage arrangement for this commitment already be `ACTIVE` with a `documentation_status` of `COMPLETE`, and that the current logical clock have reached that arrangement's `stored_from`. Either failure is `ERR_STORAGE_NOT_DOCUMENTED`."
    PRD §3.7: "`documentation_status` is `COMPLETE` when that count is exactly 3, and `INCOMPLETE` otherwise."

    Design: Difficulty/cross_entity_state_dependency/posture_stored_offsite_blocked_by_undocumented_arrangement
    """
    scenario = _setup_undocumented_arrangement()
    commitment_id = scenario["commitment"]["id"]
    assert scenario["arrangement"]["documentation_status"] == "INCOMPLETE"

    validate_error(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("STORED_OFFSITE"), BUYOUT_MANAGER
        ),
        ApiErrorId.ERR_STORAGE_NOT_DOCUMENTED.value,
        409,
    )

    unchanged = read_commitment(commitment_id)
    assert_purchase_commitment(unchanged)
    assert unchanged["delivery_posture"] == "FABRICATING"
    assert unchanged["commitment_status"] == "COMMITTED"
    assert unchanged["requires_storage_arrangement"] is True
    assert unchanged["delivered_at"] is None


def test_storage_refused_posture_move_leaves_the_draft_arrangement_exactly_as_it_was():
    """The refused move mutates nothing on the arrangement it consulted.

    Two of the three mandatory types qualify, so the count stays at 2 and the
    arrangement never climbs out of DRAFT. Carrying cost reads 0.00 both because the
    arrangement is still DRAFT and because the clock has only just reached
    `stored_from`, so no whole month has elapsed.

    PRD §3.7: "A new arrangement starts in `DRAFT` with `documentation_status` `INCOMPLETE`, `verified_doc_type_count` 0 and `carrying_cost_frozen_at` null."
    PRD §3.7: "The moment the mandatory document set becomes complete, the arrangement climbs from `DRAFT` to `ACTIVE`; the moment it falls out of completeness, an `ACTIVE` arrangement drops to `SUSPENDED`; a replacement document restores it from `SUSPENDED` to `ACTIVE`; and when the commitment's material is finally accepted on site, the `ACTIVE` arrangement moves to the terminal `RELEASED` with its carrying cost frozen."
    PRD §3.7: "Suspended periods are **not** deducted — the bailee charges for possession whether or not the contractor's paperwork is in order — and an arrangement still in `DRAFT`, or one whose `stored_from` the clock has not yet reached, reports 0.00."

    Design: Difficulty/cross_entity_state_dependency/posture_stored_offsite_blocked_by_undocumented_arrangement
    """
    scenario = _setup_undocumented_arrangement()
    arrangement_id = scenario["arrangement"]["id"]

    validate_error(
        api_client.set_delivery_posture(
            scenario["commitment"]["id"],
            delivery_posture_payload("STORED_OFFSITE"),
            BUYOUT_MANAGER,
        ),
        ApiErrorId.ERR_STORAGE_NOT_DOCUMENTED.value,
        409,
    )

    arrangement = read_arrangement(arrangement_id)
    assert_storage_arrangement(arrangement)
    assert arrangement["status"] == "DRAFT"
    assert arrangement["documentation_status"] == "INCOMPLETE"
    assert arrangement["verified_doc_type_count"] == 2
    assert arrangement["carrying_cost_frozen_at"] is None
    assert arrangement["carrying_cost_accrued"] == pytest.approx(0.00, abs=0.005)

    documents = list_documents(arrangement_id)
    assert len(documents) == 2
    assert {doc["doc_type"] for doc in documents} == {"BAILMENT_AGREEMENT", "LIEN_WAIVER"}


# ---------------------------------------------------------------------------
# Queue B: state_machines / bubble_up_arrangement_status_derives_from_its_document_children
# ---------------------------------------------------------------------------

def test_storage_arrangement_status_bubbles_up_from_its_document_children():
    """Filing the third mandatory type is what lifts the arrangement from DRAFT to ACTIVE.

    The caller never supplies a status. With a verified bailment agreement and lien
    waiver already on file the arrangement is DRAFT and INCOMPLETE; the moment a
    verified insurance certificate covering the 862500.00 stored value is filed the
    count reaches 3, `documentation_status` becomes COMPLETE and the server moves the
    arrangement to ACTIVE — without touching the commitment's posture.

    PRD §3.7: "Its `status` is compound — the server, not the caller, decides it, purely as a function of the arrangement's documents."
    PRD §3.7: "The moment the mandatory document set becomes complete, the arrangement climbs from `DRAFT` to `ACTIVE`; the moment it falls out of completeness, an `ACTIVE` arrangement drops to `SUSPENDED`; a replacement document restores it from `SUSPENDED` to `ACTIVE`; and when the commitment's material is finally accepted on site, the `ACTIVE` arrangement moves to the terminal `RELEASED` with its carrying cost frozen."
    PRD §3.7: "`documentation_status` is `COMPLETE` when that count is exactly 3, and `INCOMPLETE` otherwise."
    PRD §3.7: "an arrangement still in `DRAFT`, or one whose `stored_from` the clock has not yet reached, reports 0.00"

    Design: Corner/state_machines/bubble_up_arrangement_status_derives_from_its_document_children
    """
    scenario = _setup_draft_arrangement(
        release_at="2026-09-10T00:00:00.000Z",
        readings=_STEEL_READINGS_FULL,
        doc_effective_date="2026-09-01T00:00:00.000Z",
        filings=(
            {"doc_type": "BAILMENT_AGREEMENT", "reference_number": "BAIL-2996-001", "verified": True},
            {"doc_type": "LIEN_WAIVER", "reference_number": "LW-2996-001", "verified": True},
        ),
    )
    arrangement_id = scenario["arrangement"]["id"]
    assert scenario["arrangement"]["status"] == "DRAFT"
    assert scenario["arrangement"]["documentation_status"] == "INCOMPLETE"
    assert scenario["arrangement"]["verified_doc_type_count"] == 2

    certificate = validate_success(
        api_client.create_storage_document(
            arrangement_id,
            create_storage_document_payload(
                doc_type="INSURANCE_CERTIFICATE",
                reference_number="INS-2996-001",
                effective_date="2026-09-01T00:00:00.000Z",
                expires_at=_DOC_EXPIRES_AT,
                coverage_amount=900000.00,
                verified=True,
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert_storage_document(certificate)
    assert certificate["storage_arrangement_id"] == arrangement_id

    arrangement = read_arrangement(arrangement_id)
    assert_storage_arrangement(arrangement)
    assert arrangement["status"] == "ACTIVE"
    assert arrangement["documentation_status"] == "COMPLETE"
    assert arrangement["verified_doc_type_count"] == 3
    assert arrangement["carrying_cost_accrued"] == pytest.approx(0.00, abs=0.005)

    commitment = read_commitment(scenario["commitment"]["id"])
    assert commitment["delivery_posture"] == "RELEASED_FOR_FAB"


# ---------------------------------------------------------------------------
# Queue B: calculations / input_set_filtering_distinct_doc_types_ignore_duplicates_and_inventory_tags
# ---------------------------------------------------------------------------

def _document_by_reference(documents, reference_number):
    """The single document on the list carrying `reference_number`."""
    matches = [doc for doc in documents if doc["reference_number"] == reference_number]
    assert len(matches) == 1, f"expected exactly one document numbered {reference_number}"
    return matches[0]


def test_storage_distinct_type_count_ignores_duplicates_inventory_tags_and_unverified_filings():
    """Completeness counts distinct mandatory types, not documents.

    Four documents are already on file — two qualifying lien waivers, a qualifying
    inventory tag photograph and an unverified bailment agreement — yet the count is
    1, because duplicates collapse to one type, the photograph is never counted and an
    unverified filing does not qualify at all. A verified bailment agreement lifts the
    count to 2, and a verified insurance certificate whose coverage exactly equals the
    862500.00 stored value lifts it to 3 and the arrangement to ACTIVE.

    PRD §3.7: "`verified_doc_type_count` is then the number of *distinct* `doc_type` values, drawn from the three mandatory types `BAILMENT_AGREEMENT`, `INSURANCE_CERTIFICATE` and `LIEN_WAIVER`, for which at least one qualifying document exists."
    PRD §3.7: "Two qualifying lien waivers still count as one type, and a qualifying `INVENTORY_TAG_PHOTO` is never counted at all, because an inventory photograph is useful evidence but not a mandatory instrument."
    PRD §3.7: "A document qualifies when it is not revoked, its `verified` flag is true, the current logical clock is at or after its `effective_date` and strictly before its `expires_at`, and — for an insurance certificate only — its `coverage_amount` is at least the arrangement's `stored_value`."
    PRD §3.7: "A document filed as an `INSURANCE_CERTIFICATE` must carry a `coverage_amount` of at least the arrangement's `stored_value`; a lower figure, or an omitted one, is rejected outright with `ERR_INSURANCE_COVERAGE_INSUFFICIENT`."

    Design: Corner/calculations/input_set_filtering_distinct_doc_types_ignore_duplicates_and_inventory_tags
    """
    scenario = _setup_draft_arrangement(
        release_at="2026-08-05T00:00:00.000Z",
        readings=_STEEL_READINGS_JUL_AUG,
        doc_effective_date="2026-08-01T00:00:00.000Z",
        filings=(
            {"doc_type": "LIEN_WAIVER", "reference_number": "LW-2996-001", "verified": True},
            {"doc_type": "LIEN_WAIVER", "reference_number": "LW-2996-002", "verified": True},
            {
                "doc_type": "INVENTORY_TAG_PHOTO",
                "reference_number": "TAG-2996-001",
                "verified": True,
            },
            {
                "doc_type": "BAILMENT_AGREEMENT",
                "reference_number": "BAIL-2996-DRAFT",
                "verified": False,
            },
        ),
    )
    arrangement_id = scenario["arrangement"]["id"]
    assert len(list_documents(arrangement_id)) == 4
    assert scenario["arrangement"]["verified_doc_type_count"] == 1
    assert scenario["arrangement"]["documentation_status"] == "INCOMPLETE"
    assert scenario["arrangement"]["status"] == "DRAFT"

    file_document(
        arrangement_id,
        doc_type="BAILMENT_AGREEMENT",
        reference_number="BAIL-2996-001",
        effective_date="2026-08-01T00:00:00.000Z",
        expires_at=_DOC_EXPIRES_AT,
        verified=True,
    )
    two_types = read_arrangement(arrangement_id)
    assert_storage_arrangement(two_types)
    assert two_types["verified_doc_type_count"] == 2
    assert two_types["documentation_status"] == "INCOMPLETE"
    assert two_types["status"] == "DRAFT"

    file_document(
        arrangement_id,
        doc_type="INSURANCE_CERTIFICATE",
        reference_number="INS-2996-001",
        effective_date="2026-08-01T00:00:00.000Z",
        expires_at=_DOC_EXPIRES_AT,
        coverage_amount=862500.00,
        verified=True,
    )
    complete = read_arrangement(arrangement_id)
    assert_storage_arrangement(complete)
    assert complete["verified_doc_type_count"] == 3
    assert complete["documentation_status"] == "COMPLETE"
    assert complete["status"] == "ACTIVE"

    documents = list_documents(arrangement_id)
    assert len(documents) == 6
    unverified = _document_by_reference(documents, "BAIL-2996-DRAFT")
    assert unverified["verified"] is False
    assert unverified["revoked"] is False


# ---------------------------------------------------------------------------
# Queue B: validations / violation_error_insurance_certificate_one_cent_short_of_the_stored_value
# ---------------------------------------------------------------------------

def test_storage_insurance_certificate_one_cent_short_of_the_stored_value_is_rejected():
    """Coverage of 862499.99 against a stored value of 862500.00 is refused, as is no coverage.

    The requirement is an inclusive floor, so a single cent short fails exactly as an
    omitted figure does. Both filings are rejected outright, so neither is stored: the
    arrangement still lists only its two original documents and stays DRAFT.

    PRD §3.7: "A document filed as an `INSURANCE_CERTIFICATE` must carry a `coverage_amount` of at least the arrangement's `stored_value`; a lower figure, or an omitted one, is rejected outright with `ERR_INSURANCE_COVERAGE_INSUFFICIENT`."
    PRD §3.7: "Two optional inputs complete the filing: a `coverage_amount` of at least zero with at most 2 decimal places, defaulting to 0, which records insured value; and a `verified` boolean, false by default, asserting that the procurement group has checked the filing against the original."
    PRD §3.7: "`documentation_status` is `COMPLETE` when that count is exactly 3, and `INCOMPLETE` otherwise."

    Design: Corner/validations/violation_error_insurance_certificate_one_cent_short_of_the_stored_value
    """
    scenario = _setup_draft_arrangement(
        release_at="2026-08-05T00:00:00.000Z",
        readings=_STEEL_READINGS_JUL_AUG,
        doc_effective_date="2026-08-01T00:00:00.000Z",
        filings=(
            {"doc_type": "BAILMENT_AGREEMENT", "reference_number": "BAIL-2996-001", "verified": True},
            {"doc_type": "LIEN_WAIVER", "reference_number": "LW-2996-001", "verified": True},
        ),
    )
    arrangement_id = scenario["arrangement"]["id"]
    assert scenario["arrangement"]["stored_value"] == pytest.approx(862500.00, abs=0.005)

    validate_error(
        api_client.create_storage_document(
            arrangement_id,
            create_storage_document_payload(
                doc_type="INSURANCE_CERTIFICATE",
                reference_number="INS-2996-SHORT",
                effective_date="2026-08-01T00:00:00.000Z",
                expires_at=_DOC_EXPIRES_AT,
                coverage_amount=862499.99,
                verified=True,
            ),
            BUYOUT_MANAGER,
        ),
        ApiErrorId.ERR_INSURANCE_COVERAGE_INSUFFICIENT.value,
        422,
    )

    omitted = create_storage_document_payload(
        doc_type="INSURANCE_CERTIFICATE",
        reference_number="INS-2996-NONE",
        effective_date="2026-08-01T00:00:00.000Z",
        expires_at=_DOC_EXPIRES_AT,
        verified=True,
    )
    omitted.pop("coverage_amount")
    validate_error(
        api_client.create_storage_document(arrangement_id, omitted, BUYOUT_MANAGER),
        ApiErrorId.ERR_INSURANCE_COVERAGE_INSUFFICIENT.value,
        422,
    )

    documents, meta = validate_paginated(
        api_client.list_storage_documents(arrangement_id, BUYOUT_MANAGER)
    )
    assert meta["total_count"] == 2
    assert {doc["doc_type"] for doc in documents} == {"BAILMENT_AGREEMENT", "LIEN_WAIVER"}

    arrangement = read_arrangement(arrangement_id)
    assert_storage_arrangement(arrangement)
    assert arrangement["verified_doc_type_count"] == 2
    assert arrangement["documentation_status"] == "INCOMPLETE"
    assert arrangement["status"] == "DRAFT"

    commitment = read_commitment(scenario["commitment"]["id"])
    assert commitment["delivery_posture"] == "RELEASED_FOR_FAB"


# ---------------------------------------------------------------------------
# Queue B: validations / aggregate_validation_stored_value_may_equal_but_not_exceed_the_committed_base_cost
# ---------------------------------------------------------------------------

def test_storage_stored_value_may_equal_but_not_exceed_the_committed_base_cost():
    """1150000.01 against a 1150000.00 commitment is refused; 1150000.00 exactly is accepted.

    The contractor cannot insure more material than it bought, and the ceiling is the
    commitment's `committed_base_cost` — an inclusive one, so the equal figure creates
    a DRAFT arrangement with no documents and no carrying cost while the figure one
    cent above it creates nothing at all.

    PRD §3.7: "The declared `stored_value` may not exceed the commitment's `committed_base_cost` — the contractor cannot insure more material than it bought — and a breach is `ERR_STORED_VALUE_EXCEEDS_COMMITMENT`."
    PRD §3.7: "A new arrangement starts in `DRAFT` with `documentation_status` `INCOMPLETE`, `verified_doc_type_count` 0 and `carrying_cost_frozen_at` null."
    PRD §3.5: "`committed_base_cost` is copied from the quote's `base_price` at this instant and is immune to any subsequent revision of that quote"

    Design: Corner/validations/aggregate_validation_stored_value_may_equal_but_not_exceed_the_committed_base_cost
    """
    scenario = _setup_early_buyout_released(
        release_at="2026-08-05T00:00:00.000Z", readings=_STEEL_READINGS_JUL_AUG
    )
    commitment_id = scenario["commitment"]["id"]
    assert scenario["commitment"]["committed_base_cost"] == pytest.approx(1150000.00, abs=0.005)
    assert scenario["commitment"]["requires_storage_arrangement"] is True

    def _payload(stored_value):
        return create_storage_arrangement_payload(
            purchase_commitment_id=commitment_id,
            warehouse_name="Harbor Yard 7",
            stored_value=stored_value,
            monthly_storage_rate_pct=0.1875,
            stored_from="2026-09-20T00:00:00.000Z",
            planned_release_date="2026-12-31T00:00:00.000Z",
        )

    validate_error(
        api_client.create_storage_arrangement(_payload(1150000.01), BUYOUT_MANAGER),
        ApiErrorId.ERR_STORED_VALUE_EXCEEDS_COMMITMENT.value,
        422,
    )

    arrangement = validate_success(
        api_client.create_storage_arrangement(_payload(1150000.00), BUYOUT_MANAGER), 201
    )
    assert_storage_arrangement(arrangement)
    assert arrangement["purchase_commitment_id"] == commitment_id
    assert arrangement["stored_value"] == pytest.approx(1150000.00, abs=0.005)
    assert arrangement["status"] == "DRAFT"
    assert arrangement["documentation_status"] == "INCOMPLETE"
    assert arrangement["verified_doc_type_count"] == 0
    assert arrangement["carrying_cost_frozen_at"] is None
    assert arrangement["carrying_cost_accrued"] == pytest.approx(0.00, abs=0.005)

    assert list_documents(arrangement["id"]) == []


# ---------------------------------------------------------------------------
# Queue B: endpoints / conditional_action_a_supplier_rep_may_file_documents_on_its_own_arrangement
# ---------------------------------------------------------------------------

def test_storage_supplier_rep_may_file_a_document_on_its_own_arrangement():
    """The SupplierRep behind the material may file evidence, not only the BuyoutManager.

    With the bailment agreement and the insurance certificate already filed by the
    buyer, the supplier's own representative files the lien waiver against the
    addressed arrangement. The filing is accepted, its `storage_arrangement_id` comes
    from the path, and the third mandatory type lifts the arrangement to ACTIVE.

    PRD §3.7: "Evidence is filed as **StorageDocument** rows against a specific arrangement, and either a `BuyoutManager` or the `SupplierRep` behind that material may file one. The arrangement is taken from the addressed resource and recorded as `storage_arrangement_id`."
    PRD §2.9: "filing a storage document (`POST /procurement/storage-arrangements/{id}/documents`, where the `supplier_id` of the quote behind the arrangement's commitment must equal `X-User-ID`)"
    PRD §3.7: "`documentation_status` is `COMPLETE` when that count is exactly 3, and `INCOMPLETE` otherwise."

    Design: Corner/endpoints/conditional_action_a_supplier_rep_may_file_documents_on_its_own_arrangement
    """
    scenario = _setup_draft_arrangement(
        release_at="2026-08-05T00:00:00.000Z",
        readings=_STEEL_READINGS_JUL_AUG,
        doc_effective_date="2026-08-01T00:00:00.000Z",
        filings=(
            {"doc_type": "BAILMENT_AGREEMENT", "reference_number": "BAIL-2996-001", "verified": True},
            {
                "doc_type": "INSURANCE_CERTIFICATE",
                "reference_number": "INS-2996-001",
                "coverage_amount": 900000.00,
                "verified": True,
            },
        ),
    )
    arrangement_id = scenario["arrangement"]["id"]
    assert scenario["arrangement"]["verified_doc_type_count"] == 2

    waiver = validate_success(
        api_client.create_storage_document(
            arrangement_id,
            create_storage_document_payload(
                doc_type="LIEN_WAIVER",
                reference_number="LW-2996-SUP",
                effective_date="2026-08-01T00:00:00.000Z",
                expires_at=_DOC_EXPIRES_AT,
                verified=True,
            ),
            make_supplier_rep_headers(scenario["supplier"]["id"]),
        ),
        201,
    )
    assert_storage_document(waiver)
    assert waiver["doc_type"] == "LIEN_WAIVER"
    assert waiver["storage_arrangement_id"] == arrangement_id
    assert waiver["revoked"] is False

    arrangement = read_arrangement(arrangement_id)
    assert_storage_arrangement(arrangement)
    assert arrangement["verified_doc_type_count"] == 3
    assert arrangement["documentation_status"] == "COMPLETE"
    assert arrangement["status"] == "ACTIVE"

    commitment = read_commitment(scenario["commitment"]["id"])
    assert commitment["delivery_posture"] == "RELEASED_FOR_FAB"
