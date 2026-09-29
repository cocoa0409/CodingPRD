"""Field-level contracts of the declared entities: defaults, shapes and parents.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only_resource,
    assert_cents,
    assert_collection,
    assert_empty_collection,
    assert_error,
    assert_fields,
    assert_id_set,
    assert_instant_equals,
    assert_is_none,
    assert_score,
    assert_versioned_resource,
)
from test_helpers.constants import (
    MISSING_UUID,
    AppliedTo,
    BenefitCategory,
    CapStatus,
    CompliancePosture,
    CooperationStatus,
    FundingArrangement,
    NetworkTier,
    NoticeSource,
    NoticeType,
    NqtlType,
    PlanYearStatus,
    RemedyType,
    SubClassification,
)
from test_helpers.factories import OMIT


def test_registering_an_administrator_applies_the_declared_defaults_and_counters(api, sponsor_headers):
    """A minimal registration comes back fully initialised.

    Only the legal name and the contact address are supplied.  The contractual
    term falls back to 45 days, all four obligation counters start at 0, both
    cooperation scores start perfect and the status starts cooperative.

    PRD: "A freshly registered administrator starts with all four obligation
    counters — `outstanding_request_count`, `late_request_count`, `breach_count` and
    `regulator_reportable_late_count` — at 0, with both `cooperation_score` and
    `regulatory_basis_cooperation_score` at 100.00, and with `cooperation_status` at
    `COOPERATIVE`."

    Design: Corner/entities/administrator_create_returns_every_declared_field_with_defaults_applied
    """
    admin = validate_success(
        api.create_administrator(
            f.administrator_payload(contractual_production_days=OMIT), sponsor_headers
        ),
        201,
    )

    assert_versioned_resource(admin)
    assert admin["version"] == 1
    assert_instant_equals(admin["created_at"], admin["updated_at"], "created_at vs updated_at")
    assert admin["contractual_production_days"] == 45
    assert_fields(
        admin,
        outstanding_request_count=0,
        late_request_count=0,
        breach_count=0,
        regulator_reportable_late_count=0,
        cooperation_status=CooperationStatus.COOPERATIVE,
    )
    assert_score(admin["cooperation_score"], 100.00, "cooperation_score")
    assert_score(
        admin["regulatory_basis_cooperation_score"], 100.00, "regulatory_basis_cooperation_score"
    )


def test_reading_a_plan_year_echoes_its_inputs_and_its_freshly_derived_verdict(api, regulator_headers):
    """The read returns the stored row, inputs and derived fields alike.

    A regulator reads back a plan year the sponsor just opened: every supplied
    field comes back unchanged, the lifecycle status is OPEN, and the posture of an
    empty plan year under a cooperative TPA has already been computed as COMPLIANT
    with all four counters at zero.

    PRD: "A new plan year is written with `status` `OPEN`, with
    `open_violation_count`, `notified_violation_count`, `failing_parity_test_count`
    and `remediation_liability_cents` all at 0, and with `compliance_posture`
    computed immediately: an empty plan year under a `COOPERATIVE` administrator is
    `COMPLIANT`."

    Design: Corner/entities/plan_year_get_by_id_returns_the_stored_row
    """
    admin = fx.register_administrator(api)
    created = fx.open_plan_year(api, admin["id"])

    plan_year = validate_success(api.get_plan_year(created["id"], regulator_headers))

    assert_fields(
        plan_year,
        plan_name="Acme Group Health Plan",
        plan_year_label="2026",
        administrator_id=admin["id"],
        funding_arrangement=FundingArrangement.SELF_FUNDED,
        covered_participant_count=1200,
        status=PlanYearStatus.OPEN,
        compliance_posture=CompliancePosture.COMPLIANT,
        open_violation_count=0,
        notified_violation_count=0,
        failing_parity_test_count=0,
    )
    assert_cents(plan_year["remediation_liability_cap_cents"], 5000000, "liability cap")
    assert_cents(plan_year["remediation_liability_cents"], 0, "remediation_liability_cents")


def test_the_item_list_windows_three_rows_into_two_pages(api, sponsor_headers):
    """`total_count` counts the matches and `has_more` describes the window.

    Three limitations of three distinct types are inventoried.  A window of two
    reports three matches with more to come; the next window returns the remaining
    row and closes.  The two pages together are exactly the three rows, and a
    window size of zero is a payload-shape failure.

    PRD: "List responses populate four fields in the envelope's `meta` object:
    `limit` and `offset` echo the effective values used for the page, `total_count`
    reports how many rows match the filters before the page window is applied, and
    `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/nqtl_item_list_paginates_with_total_count_and_has_more
    """
    scenario = fx.classified_plan(api, sub_classification=SubClassification.OFFICE_VISITS)
    expected = {
        fx.inventory_item(
            api,
            scenario.plan_year_id,
            scenario.classification_id,
            nqtl_type=nqtl_type,
            applied_to=AppliedTo.BOTH,
            description=f"{nqtl_type} for outpatient office visits.",
        )["id"]
        for nqtl_type in (
            NqtlType.PRIOR_AUTHORIZATION,
            NqtlType.CONCURRENT_REVIEW,
            NqtlType.STEP_THERAPY,
        )
    }

    first, meta = assert_collection(
        api.list_nqtl_items(
            {"plan_year_id": scenario.plan_year_id, "limit": 2, "offset": 0}, sponsor_headers
        ),
        3,
        2,
        True,
    )
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    second, meta = assert_collection(
        api.list_nqtl_items(
            {"plan_year_id": scenario.plan_year_id, "limit": 2, "offset": 2}, sponsor_headers
        ),
        3,
        1,
        False,
    )
    assert meta["offset"] == 2
    assert_id_set(first + second, expected)

    assert_error(
        api.list_nqtl_items({"plan_year_id": scenario.plan_year_id, "limit": 0}, sponsor_headers),
        ApiErrorId.VALIDATION,
    )


def test_every_read_endpoint_reports_its_own_not_found_code_for_an_unused_id(api, officer_headers):
    """Nine reads, nine entity-specific 404s.

    The identifier is a well-formed UUID that was never minted, so each read fails
    at the path-existence rung rather than on shape — and each one names the entity
    its own path addresses rather than a generic code.

    PRD: "Every identifier in the request path exists, checked left to right, each
    reported with the 404 code specific to the entity that identifier addresses."

    Design: Corner/entities/get_plan_year_with_unknown_id_returns_plan_year_not_found
    """
    assert_error(
        api.get_plan_year(MISSING_UUID, officer_headers), ApiErrorId.PLAN_YEAR_NOT_FOUND
    )
    assert_error(
        api.get_nqtl_item(MISSING_UUID, officer_headers), ApiErrorId.NQTL_ITEM_NOT_FOUND
    )
    assert_error(api.get_analysis(MISSING_UUID, officer_headers), ApiErrorId.ANALYSIS_NOT_FOUND)
    assert_error(
        api.get_vendor_request(MISSING_UUID, officer_headers),
        ApiErrorId.VENDOR_REQUEST_NOT_FOUND,
    )
    assert_error(
        api.get_data_submission(MISSING_UUID, officer_headers),
        ApiErrorId.DATA_SUBMISSION_NOT_FOUND,
    )
    assert_error(
        api.get_corrective_action_plan(MISSING_UUID, officer_headers), ApiErrorId.CAP_NOT_FOUND
    )
    assert_error(
        api.get_regulator_request(MISSING_UUID, officer_headers),
        ApiErrorId.REGULATOR_REQUEST_NOT_FOUND,
    )
    assert_error(
        api.get_administrator(MISSING_UUID, officer_headers), ApiErrorId.ADMINISTRATOR_NOT_FOUND
    )
    assert_error(
        api.get_classification(MISSING_UUID, officer_headers),
        ApiErrorId.CLASSIFICATION_NOT_FOUND,
    )


def test_a_plan_year_without_a_funding_arrangement_is_refused_and_nothing_is_stored(
    api, sponsor_headers
):
    """An input field with no declared default cannot be omitted.

    The funding arrangement is required and has no fallback, so the create is a
    payload-shape failure; no plan year is left behind, and supplying the field —
    here on the INSURED leg of the enumeration — makes the identical payload work.

    PRD: "Payload shape: every required field present, types as specified, enum
    values inside their declared sets, numeric ranges honoured, string lengths
    honoured, arrays non-empty and free of duplicates, dates written as
    `YYYY-MM-DD`, instants written as ISO 8601 UTC, and pagination values in range —
    otherwise `ERR_VALIDATION`."

    Design: Corner/entities/plan_year_create_missing_required_field_rejected
    """
    admin = fx.register_administrator(api)

    assert_error(
        api.create_plan_year(
            f.plan_year_payload(admin["id"], funding_arrangement=OMIT), sponsor_headers
        ),
        ApiErrorId.VALIDATION,
    )
    assert_empty_collection(
        api.list_plan_years({"administrator_id": admin["id"]}, sponsor_headers)
    )

    plan_year = validate_success(
        api.create_plan_year(
            f.plan_year_payload(admin["id"], funding_arrangement=FundingArrangement.INSURED),
            sponsor_headers,
        ),
        201,
    )
    assert plan_year["funding_arrangement"] == FundingArrangement.INSURED


def test_an_inpatient_classification_takes_the_declared_optional_defaults(api, sponsor_headers):
    """The two optional fields fall back to NONE and true, not to null.

    Neither the outpatient split nor the coverage flag is supplied.  The stored row
    reports the sub-classification as NONE and the coverage flag as true, and it
    belongs to the plan year taken from the path rather than from the body.

    PRD: "A `PlanSponsor` creates a benefit classification under a plan year —
    `plan_year_id` is taken from the path, not from the body — stating a
    `benefit_category` of `INPATIENT`, `OUTPATIENT`, `EMERGENCY_CARE` or
    `PRESCRIPTION_DRUGS`, a `network_tier` of `IN_NETWORK`, `OUT_OF_NETWORK` or
    `NOT_APPLICABLE`, an optional `sub_classification` of `NONE`, `OFFICE_VISITS` or
    `ALL_OTHER_OUTPATIENT` that defaults to `NONE`, the inclusive first and last
    dates of the claims measurement period the row covers as
    `measurement_period_start` and `measurement_period_end` (both written
    `YYYY-MM-DD`), and an optional `mh_su_benefits_covered` boolean that defaults to
    true and records whether mental-health and substance-use-disorder benefits are
    offered at all in this slice of the plan."

    Design: Corner/entities/classification_defaults_applied_when_optional_fields_omitted
    """
    admin = fx.register_administrator(api)
    plan_year = fx.open_plan_year(api, admin["id"])

    classification = validate_success(
        api.create_classification(
            plan_year["id"],
            f.classification_payload(
                benefit_category=BenefitCategory.INPATIENT,
                network_tier=NetworkTier.OUT_OF_NETWORK,
            ),
            sponsor_headers,
        ),
        201,
    )

    assert classification["sub_classification"] == SubClassification.NONE
    assert classification["mh_su_benefits_covered"] is True
    assert classification["plan_year_id"] == plan_year["id"]
    assert classification["version"] == 1


def test_a_corrective_plans_status_and_liability_come_from_the_server_not_the_payload(
    api, sponsor_headers
):
    """The status, the frozen amount and the approver stamp are all server-owned.

    A clean draft is written as DRAFT with the amount the server computed — 880
    claims at 3,125 cents at the process-change rate — and no approver.  The same
    payload extended with a status of APPROVED and a liability of 1 cent is either
    refused for carrying unknown fields or accepted with those values discarded.

    PRD: "Derived fields are never client-supplied and are never trusted from a
    previous computation when their inputs may have moved."

    Design: Corner/entities/system_and_computed_fields_ignore_client_supplied_values
    """
    scenario = fx.item_in_violation(api, sub_classification=SubClassification.OFFICE_VISITS)
    payload = f.cap_payload(
        scenario.item_id,
        remedy_type=RemedyType.PROCESS_CHANGE,
        affected_claims_count=880,
        average_claim_cents=3125,
    )

    cap = validate_success(api.create_corrective_action_plan(payload, sponsor_headers), 201)
    assert_versioned_resource(cap)
    assert cap["version"] == 1
    assert cap["status"] == CapStatus.DRAFT
    assert_cents(cap["reprocessing_liability_cents"], 275000, "reprocessing_liability_cents")
    assert_is_none(cap["approved_by_user_id"], "approved_by_user_id")

    polluted = dict(payload, status=CapStatus.APPROVED, reprocessing_liability_cents=1)
    response = api.create_corrective_action_plan(polluted, sponsor_headers)
    if response.status_code == 201:
        stored = validate_success(response, 201)
        assert stored["status"] == CapStatus.DRAFT
        assert_cents(
            stored["reprocessing_liability_cents"], 275000, "reprocessing_liability_cents"
        )
        assert_is_none(stored["approved_by_user_id"], "approved_by_user_id")
    else:
        assert_error(response, ApiErrorId.VALIDATION)


def test_the_three_classification_agreement_rules_each_report_their_own_code(api, sponsor_headers):
    """Tier, split and period are three independent rules with three codes.

    NOT_APPLICABLE on an outpatient row fails the tier rule; OFFICE_VISITS on an
    inpatient row fails the split rule; a reversed period fails the internal date
    rule.  A well-formed emergency-care row then succeeds, and a category outside
    the enumeration is a plain shape failure.

    PRD: "Second, the outpatient split is only meaningful for outpatient benefits:
    `sub_classification` may be `OFFICE_VISITS` or `ALL_OTHER_OUTPATIENT` only when
    `benefit_category` is `OUTPATIENT`, and must be `NONE` for every other category;
    otherwise the row is rejected with `ERR_SUB_CLASSIFICATION_MISMATCH` (HTTP 422)."

    Design: Corner/entities/classification_enum_and_pairing_constraints_enforced
    """
    admin = fx.register_administrator(api)
    plan_year = fx.open_plan_year(api, admin["id"])

    assert_error(
        api.create_classification(
            plan_year["id"],
            f.classification_payload(
                network_tier=NetworkTier.NOT_APPLICABLE,
                sub_classification=SubClassification.OFFICE_VISITS,
            ),
            sponsor_headers,
        ),
        ApiErrorId.NETWORK_TIER_MISMATCH,
    )
    assert_error(
        api.create_classification(
            plan_year["id"],
            f.classification_payload(
                benefit_category=BenefitCategory.INPATIENT,
                sub_classification=SubClassification.OFFICE_VISITS,
            ),
            sponsor_headers,
        ),
        ApiErrorId.SUB_CLASSIFICATION_MISMATCH,
    )
    assert_error(
        api.create_classification(
            plan_year["id"],
            f.classification_payload(
                benefit_category=BenefitCategory.EMERGENCY_CARE,
                network_tier=NetworkTier.NOT_APPLICABLE,
                measurement_period_start="2026-06-30",
                measurement_period_end="2026-01-01",
            ),
            sponsor_headers,
        ),
        ApiErrorId.MEASUREMENT_PERIOD_INVALID,
    )

    accepted = validate_success(
        api.create_classification(
            plan_year["id"],
            f.classification_payload(
                benefit_category=BenefitCategory.EMERGENCY_CARE,
                network_tier=NetworkTier.NOT_APPLICABLE,
            ),
            sponsor_headers,
        ),
        201,
    )
    assert accepted["network_tier"] == NetworkTier.NOT_APPLICABLE
    assert accepted["sub_classification"] == SubClassification.NONE

    assert_error(
        api.create_classification(
            plan_year["id"],
            f.classification_payload(benefit_category="OUTPATIENT_SURGERY"),
            sponsor_headers,
        ),
        ApiErrorId.VALIDATION,
    )


def test_the_disclosure_notice_is_append_only_and_reads_as_a_composed_summary(
    api, regulator_headers
):
    """The notice carries the six system-stamped fields and no version pair.

    Exactly one notice exists, its summary is composed by the server from the item
    and its classification, and its instant is the logical clock's start value to
    three fractional digits.  There is no create, edit or delete route for it — a
    client can only read it.

    PRD: "Each notice records the `nqtl_item_id` it concerns, a `notice_type` of
    either `VIOLATION_DISCLOSURE` or `CORRECTION_COMPLETED` naming which cascade
    produced it, a `source` of either `DETERMINATION_CASCADE` or
    `CAP_CLOSURE_CASCADE` naming the cascade itself, a `recipient_count` copied from
    the owning plan year's `covered_participant_count` at the moment of issuance, an
    `issued_at` instant taken from the logical clock, and a system-composed
    `disclosure_summary` built from the item and its classification as the item's
    `nqtl_type`, then the word "in", then the classification's `benefit_category` and
    `network_tier` separated by a forward slash, then a colon and a space, then the
    `notice_type` — for example, `PRIOR_AUTHORIZATION in OUTPATIENT/IN_NETWORK:
    VIOLATION_DISCLOSURE`."

    Design: Corner/entities/participant_notice_is_immutable_and_read_only
    """
    scenario = fx.item_in_violation(api, sub_classification=SubClassification.OFFICE_VISITS)

    rows, _ = assert_collection(
        api.list_participant_notices(
            scenario.item_id, {"notice_type": NoticeType.VIOLATION_DISCLOSURE}, regulator_headers
        ),
        1,
        1,
        False,
    )
    notice = rows[0]
    assert_append_only_resource(notice)
    assert_fields(
        notice,
        nqtl_item_id=scenario.item_id,
        notice_type=NoticeType.VIOLATION_DISCLOSURE,
        source=NoticeSource.DETERMINATION_CASCADE,
        recipient_count=1200,
        disclosure_summary="PRIOR_AUTHORIZATION in OUTPATIENT/IN_NETWORK: VIOLATION_DISCLOSURE",
    )
    assert_instant_equals(notice["issued_at"], "2026-08-01T00:00:00.000Z", "issued_at")


def test_inventorying_against_another_plan_years_classification_is_refused(api, officer_headers):
    """Both parents exist, so the failure is coherence rather than existence.

    The classification belongs to the second plan year while the payload names the
    first, and the create is refused for incoherence.  Naming a classification that
    does not exist at all fails earlier, at the foreign-key existence rung, and the
    first plan year's inventory stays empty throughout.

    PRD: "The named classification must belong to the named plan year; a payload that
    pairs a classification from one plan year with another plan year's identifier is
    rejected with `ERR_CROSS_PLAN_YEAR_REFERENCE` (HTTP 409)."

    Design: Corner/entities/nqtl_item_rejects_a_classification_from_another_plan_year
    """
    admin = fx.register_administrator(api)
    plan_year_a = fx.open_plan_year(api, admin["id"], plan_year_label="2026-A")
    plan_year_b = fx.open_plan_year(
        api, admin["id"], plan_year_label="2026-B", covered_participant_count=900
    )
    classification_b = fx.create_classification(
        api, plan_year_b["id"], sub_classification=SubClassification.OFFICE_VISITS
    )

    assert_error(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                plan_year_a["id"],
                classification_b["id"],
                applied_to=AppliedTo.BOTH,
                description="Prior authorization recorded against the wrong plan year.",
            ),
            officer_headers,
        ),
        ApiErrorId.CROSS_PLAN_YEAR_REFERENCE,
    )
    assert_error(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                plan_year_a["id"],
                MISSING_UUID,
                applied_to=AppliedTo.BOTH,
                description="Prior authorization against a classification that does not exist.",
            ),
            officer_headers,
        ),
        ApiErrorId.CLASSIFICATION_NOT_FOUND,
    )
    assert_empty_collection(
        api.list_nqtl_items({"plan_year_id": plan_year_a["id"]}, officer_headers)
    )


def test_inventorying_where_no_mh_benefits_are_offered_is_refused(api, sponsor_headers):
    """A classification that covers no MH/SUD benefits has no parity to protect.

    The parent exists and belongs to the right plan year, so this is a coherence
    failure of its own: the coverage flag is false.  Nothing is inventoried and the
    plan year's verdict is untouched.

    PRD: "The classification must also actually offer the benefits being protected:
    when its `mh_su_benefits_covered` is false, inventorying an NQTL there is
    rejected with `ERR_MH_BENEFITS_NOT_COVERED` (HTTP 409)."

    Design: Corner/entities/nqtl_item_in_a_classification_without_mh_benefits_rejected
    """
    admin = fx.register_administrator(api)
    plan_year = fx.open_plan_year(api, admin["id"])
    classification = fx.create_classification(
        api,
        plan_year["id"],
        benefit_category=BenefitCategory.PRESCRIPTION_DRUGS,
        network_tier=NetworkTier.NOT_APPLICABLE,
        mh_su_benefits_covered=False,
    )

    assert_error(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                plan_year["id"],
                classification["id"],
                nqtl_type=NqtlType.STEP_THERAPY,
                applied_to=AppliedTo.BOTH,
                description="Step therapy in a classification that offers no MH/SUD benefits.",
            ),
            sponsor_headers,
        ),
        ApiErrorId.MH_BENEFITS_NOT_COVERED,
    )
    assert_empty_collection(
        api.list_nqtl_items({"classification_id": classification["id"]}, sponsor_headers)
    )
    assert (
        fx.read_plan_year(api, plan_year["id"])["compliance_posture"]
        == CompliancePosture.COMPLIANT
    )
