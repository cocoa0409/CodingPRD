"""One error per request, and always the right one.

The ladder promises that exactly one failure is reported and that no lower check
masks a higher one. These tests walk families of refusals that are easy to
collapse into a single generic code — four authorisation conditions, thirteen
not-found codes, three uniqueness registers, six pilot and manifest guards — and
insist that each one keeps its own identity and its own place in the order.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_APPLICATION_STATE_INVALID,
    ERR_AWARD_EXCEEDS_PROJECT_COST,
    ERR_AWARD_EXCEEDS_REQUEST,
    ERR_CLAIM_NOT_FOUND,
    ERR_CLAIM_STATE_INVALID,
    ERR_CONTAMINANT_NOT_FOUND,
    ERR_DELIVERY_METHOD_INSUFFICIENT,
    ERR_DETERMINATION_NOT_FOUND,
    ERR_DETERMINATION_STATE_INVALID,
    ERR_DUPLICATE_CERTIFICATION_ID,
    ERR_DUPLICATE_CONTAMINANT_CODE,
    ERR_DUPLICATE_ENTRY_POINT_LABEL,
    ERR_EFFLUENT_EXCEEDS_INFLUENT,
    ERR_ENTRY_POINT_NOT_FOUND,
    ERR_EVALUATION_NOT_FOUND,
    ERR_EVALUATION_STATE_INVALID,
    ERR_FORBIDDEN_ROLE,
    ERR_FUNDING_NOT_SECURED,
    ERR_INSUFFICIENT_MONITORING_HISTORY,
    ERR_INSUFFICIENT_PILOT_EVIDENCE,
    ERR_LABORATORY_ASSIGNMENT_MISMATCH,
    ERR_LABORATORY_NOT_FOUND,
    ERR_LABORATORY_NOT_OWNED,
    ERR_LAB_RESULT_NOT_FOUND,
    ERR_MANIFEST_NOT_FOUND,
    ERR_MANIFEST_STATE_INVALID,
    ERR_MASS_EXCEEDS_SPENT_MEDIA,
    ERR_MEDIA_TYPE_MISMATCH,
    ERR_MONITORING_STATE_INVALID,
    ERR_NOTIFICATION_CONTENT_INCOMPLETE,
    ERR_NOTIFICATION_NOT_FOUND,
    ERR_NOTIFICATION_REVISION_LIMIT,
    ERR_NOTIFICATION_STATE_INVALID,
    ERR_OPEN_VIOLATION_BLOCKS_REDUCTION,
    ERR_PILOT_NOT_COMPLETED,
    ERR_PILOT_NOT_FOUND,
    ERR_PILOT_STATE_INVALID,
    ERR_PROJECT_NOT_FOUND,
    ERR_PROJECT_STATE_INVALID,
    ERR_RECOVERY_EXCEEDS_CLAIM,
    ERR_SAMPLE_NOT_FOUND,
    ERR_TRIENNIAL_HISTORY_INSUFFICIENT,
    ERR_UNAUTHENTICATED,
    ERR_VIOLATION_PENDING_BLOCKS_REDUCTION,
)
from test_helpers.assertions import (
    assert_allocation_buckets,
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_instant_equals,
    assert_is_null,
    assert_money_cents,
    assert_rate_ladder,
    assert_status,
    assert_total_count,
)
from test_helpers.constants import (
    DEFAULT_CLOCK,
    DELIVERY_BROADCAST_MEDIA,
    DELIVERY_MAIL,
    DELIVERY_POSTING,
    MANDATORY_CONTENT_ELEMENTS,
)
from test_helpers.fixtures import (
    accepted_quarters,
    apply_for_funding,
    build_registry,
    collect_sample,
    complete_pilot,
    draft_determination,
    issued_violation,
    open_claim,
    open_evaluation,
    read_application,
    read_claim,
    read_determination,
    read_entry_point,
    read_evaluation,
    read_lab_result,
    read_manifest,
    read_notification,
    read_pilot,
    read_project,
    read_sample,
    register_contaminant,
    register_entry_point,
    register_laboratory,
    register_pilot,
    selected_project,
    ship_sample,
    start_pilot,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    OFFICER_2_USER_ID,
    OFFICER_USER_ID,
    SAMPLING_TECHNICIAN_HEADERS,
    STATE_REGULATOR_HEADERS,
    TREATMENT_ENGINEER_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    UTILITY_ADMIN_HEADERS,
    headers_blank_role,
    make_laboratory_manager_headers,
)


def test_the_authentication_and_ownership_gates_each_keep_their_own_code(api):
    """Four refusals on two endpoints, four different codes, in ladder order.

    A blank role and an unrecognised role are both unauthenticated, a recognised
    but unlisted role is forbidden, and neither leaves an entry point behind. On
    the custody endpoint the two laboratory gates are distinct and ordered: an
    identifier that is no laboratory at all fails the ownership check, while the
    identifier of the wrong laboratory gets past ownership and fails the
    assignment check. The sample stays in transit through both, and the assigned
    laboratory receives it.

    PRD: "**Laboratory identity** — an `X-User-Role` of `LaboratoryManager` whose
    `X-User-ID` is not a laboratory `id`: `ERR_LABORATORY_NOT_OWNED`. This applies
    to exactly four endpoints: sample receipt, lab-result creation, the
    lab-result list, and the sample list."

    Design: Corner/errors/the_authentication_and_ownership_gates_each_return_their_own_code
    """
    registry = build_registry(api)
    other_laboratory = register_laboratory(
        api, name="Southbank Labs", certification_id="CERT-002"
    )
    sample = collect_sample(
        api, registry["entry_point_id"], [registry["contaminant_id"]], preservative_lot="LOT-A1"
    )
    ship_sample(api, sample["id"], registry["laboratory_id"])
    intruder = f.entry_point_payload(label="EPTDS-09", population_served=45000)

    validate_error(
        api.create_entry_point(intruder, headers_blank_role()), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.create_entry_point(intruder, UNKNOWN_ROLE_HEADERS), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.create_entry_point(intruder, SAMPLING_TECHNICIAN_HEADERS), ERR_FORBIDDEN_ROLE, 403
    )
    assert_total_count(api.list_entry_points(COMPLIANCE_OFFICER_HEADERS), 1)

    receipt = f.receive_sample_payload()
    validate_error(
        api.receive_sample(
            sample["id"], receipt, make_laboratory_manager_headers("not-a-registered-laboratory")
        ),
        ERR_LABORATORY_NOT_OWNED,
        403,
    )
    validate_error(
        api.receive_sample(
            sample["id"], receipt, make_laboratory_manager_headers(other_laboratory["id"])
        ),
        ERR_LABORATORY_ASSIGNMENT_MISMATCH,
        403,
    )
    assert_status(read_sample(api, sample["id"]), "IN_TRANSIT")

    received = validate_success(
        api.receive_sample(sample["id"], receipt, registry["lab_headers"])
    )
    assert_status(received, "RECEIVED")


def test_every_path_id_family_reports_its_own_not_found_code(api):
    """Thirteen empty collections, thirteen distinct 404s, no generic fallback.

    Each read addresses a different collection with a syntactically valid
    identifier that resolves to nothing, and each must answer with the not-found
    code of the collection named in its own URL rather than a shared one. No two
    of the thirteen responses may carry the same identifier, and every body
    explains itself.

    PRD: "**Path existence** — any `{id}` path segment that does not resolve to a
    live row: the not-found identifier of the addressed collection
    (`ERR_ENTRY_POINT_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`,
    `ERR_LAB_RESULT_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`,
    `ERR_NOTIFICATION_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`,
    `ERR_PILOT_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_CONTAMINANT_NOT_FOUND`, `ERR_LABORATORY_NOT_FOUND`), always HTTP 404."

    Design: Corner/errors/every_path_id_family_reports_its_own_not_found_code
    """
    reads = [
        (api.get_contaminant, ERR_CONTAMINANT_NOT_FOUND),
        (api.get_laboratory, ERR_LABORATORY_NOT_FOUND),
        (api.get_entry_point, ERR_ENTRY_POINT_NOT_FOUND),
        (api.get_sample, ERR_SAMPLE_NOT_FOUND),
        (api.get_lab_result, ERR_LAB_RESULT_NOT_FOUND),
        (api.get_determination, ERR_DETERMINATION_NOT_FOUND),
        (api.get_notification, ERR_NOTIFICATION_NOT_FOUND),
        (api.get_treatment_evaluation, ERR_EVALUATION_NOT_FOUND),
        (api.get_pilot_test, ERR_PILOT_NOT_FOUND),
        (api.get_residuals_manifest, ERR_MANIFEST_NOT_FOUND),
        (api.get_capital_project, ERR_PROJECT_NOT_FOUND),
        (api.get_funding_application, ERR_APPLICATION_NOT_FOUND),
        (api.get_cost_recovery_claim, ERR_CLAIM_NOT_FOUND),
    ]

    reported = []
    for read, expected_error in reads:
        response = read(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS)
        validate_error(response, expected_error, 404)
        body = response.json()["data"]
        assert body.get("message"), f"{expected_error} carried no message: {body!r}"
        reported.append(body["error_id"])

    assert len(set(reported)) == len(reads), (
        f"Expected thirteen distinct not-found codes, got {reported}"
    )


def test_re_registering_a_code_certification_id_or_label_is_refused(api):
    """Three registers, three codes, and every other field deliberately different.

    Each duplicate repeats only the one column that must be unique — the
    contaminant code, the certification identifier, the entry-point label — and
    differs everywhere else, so uniqueness cannot be mistaken for a whole-row
    comparison. All three are refused, all three registries still hold exactly one
    row, and the incumbents are untouched.

    PRD: "a state `certification_id` of one to forty characters that must be
    unique across all laboratories — a repeat is refused with
    `ERR_DUPLICATE_CERTIFICATION_ID`"

    Design: Corner/errors/re_registering_a_code_certification_id_or_label_is_rejected
    """
    contaminant = register_contaminant(api)
    laboratory = register_laboratory(api)
    entry_point = register_entry_point(api)

    validate_error(
        api.create_contaminant(
            f.contaminant_payload(
                code="PFOA",
                mcl_ng_per_l=10.00,
                trigger_level_ng_per_l=5.00,
                required_mrl_ng_per_l=4.00,
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_CONTAMINANT_CODE,
        422,
    )
    validate_error(
        api.create_laboratory(
            f.laboratory_payload(
                name="Westbrook Testing",
                certification_id="CERT-001",
                certified_methods=["METHOD_1633"],
                lowest_achievable_dl_ng_per_l=0.50,
                certification_expires_on="2029-06-30T00:00:00.000Z",
                daily_analysis_capacity=12,
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_CERTIFICATION_ID,
        422,
    )
    validate_error(
        api.create_entry_point(
            f.entry_point_payload(
                label="EPTDS-01", source_type="SURFACE_WATER", population_served=9000
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_ENTRY_POINT_LABEL,
        422,
    )

    assert_total_count(api.list_entry_points(COMPLIANCE_OFFICER_HEADERS), 1)
    assert_decimal(
        validate_success(api.get_contaminant(contaminant["id"], COMPLIANCE_OFFICER_HEADERS))[
            "mcl_ng_per_l"
        ],
        4.00,
        label="mcl_ng_per_l",
    )
    assert_equals(
        validate_success(api.get_laboratory(laboratory["id"], COMPLIANCE_OFFICER_HEADERS)),
        "name",
        "Northgate Analytical",
    )
    assert_equals(
        validate_success(api.get_entry_point(entry_point["id"], COMPLIANCE_OFFICER_HEADERS)),
        "source_type",
        "GROUNDWATER",
    )


def test_the_notification_submission_gates_fire_in_ladder_order(api):
    """Content before delivery, then the endpoint closes behind the accepted notice.

    An average of 4.50 against a limit of 4.00 is an exceedance but not an acute
    one, so the auto-created notice is TIER_2 with thirty days to run. A submission
    short one mandatory disclosure and a submission short one tier-required channel
    fail on different codes and neither touches the draft. The complete submission,
    carrying an extra channel the tier never asked for, is accepted and records its
    author; repeating it is refused as a state error. The regulator approves, and a
    different officer certifies distribution on the deadline day itself, so the
    notice lands DISTRIBUTED with nothing late about it.

    PRD: "The `delivery_methods` array must contain every channel the tier demands:
    `TIER_1` requires both `BROADCAST_MEDIA` and `POSTING`, `TIER_2` requires both
    `MAIL` and `POSTING`, and `TIER_3` requires `ANNUAL_REPORT`; additional
    channels beyond the required set are always allowed, but an incomplete set is
    refused with `ERR_DELIVERY_METHOD_INSUFFICIENT`."

    Design: Corner/errors/the_notification_submission_gates_fire_in_ladder_order
    """
    registry = build_registry(api)
    violation = issued_violation(api, registry, reported_ng_per_l=4.50)
    determination = violation["determination"]
    notification = violation["notification"]
    assert_equals(determination, "determination", "MCL_VIOLATION")
    assert_equals(determination, "violation_type", "NON_ACUTE")
    assert_equals(notification, "tier", "TIER_2")
    assert_instant_equals(
        notification["required_by_at"], "2026-08-31T00:00:00.000Z", label="required_by_at"
    )

    validate_error(
        api.submit_notification(
            notification["id"],
            f.notification_submit_payload(content_elements=MANDATORY_CONTENT_ELEMENTS[:5]),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_NOTIFICATION_CONTENT_INCOMPLETE,
        422,
    )
    validate_error(
        api.submit_notification(
            notification["id"],
            f.notification_submit_payload(delivery_methods=[DELIVERY_MAIL]),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_DELIVERY_METHOD_INSUFFICIENT,
        422,
    )
    still_draft = read_notification(api, notification["id"])
    assert_status(still_draft, "DRAFT")
    assert_equals(still_draft, "revision_count", 0)
    assert_equals(still_draft, "content_elements", [])

    submitted = validate_success(
        api.submit_notification(
            notification["id"],
            f.notification_submit_payload(
                delivery_methods=[DELIVERY_MAIL, DELIVERY_POSTING, DELIVERY_BROADCAST_MEDIA]
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    assert_status(submitted, "SUBMITTED")
    assert_equals(submitted, "drafted_by_user_id", OFFICER_USER_ID)
    assert_equals(
        submitted, "delivery_methods", [DELIVERY_MAIL, DELIVERY_POSTING, DELIVERY_BROADCAST_MEDIA]
    )

    validate_error(
        api.submit_notification(
            notification["id"], f.notification_submit_payload(), COMPLIANCE_OFFICER_HEADERS
        ),
        ERR_NOTIFICATION_STATE_INVALID,
        422,
    )
    assert_equals(read_notification(api, notification["id"]), "revision_count", 0)

    approved = validate_success(
        api.review_notification(
            notification["id"],
            f.notification_review_payload(
                approve=True, review_note="Content and delivery plan accepted"
            ),
            STATE_REGULATOR_HEADERS,
        )
    )
    assert_status(approved, "APPROVED")
    assert_equals(approved, "revision_count", 0)

    distributed = validate_success(
        api.certify_notification_distribution(
            notification["id"],
            f.certify_distribution_payload(delivery_evidence_ref="MAILING-2026-0801"),
            COMPLIANCE_OFFICER_2_HEADERS,
        )
    )
    assert_status(distributed, "DISTRIBUTED")
    assert_equals(distributed, "late_by_hours", 0)
    assert_instant_equals(distributed["distributed_at"], DEFAULT_CLOCK, label="distributed_at")
    assert_equals(distributed, "certified_by_user_id", OFFICER_2_USER_ID)


def test_a_fifth_submission_after_four_rejected_reviews_is_refused(api):
    """The bound is three revisions, so the fourth submission is still legal.

    Four rounds of submit-and-reject drive the revision counter to one, two, three
    and four, and each rejection empties both arrays so the officer must rebuild the
    notice. The fourth submission happens at a counter of exactly three and is
    accepted; only the fifth, at four, is refused. The refusal stores nothing at
    all — the notice is still a DRAFT at four revisions with no content on it.

    PRD: "The `revision_count` must be no greater than three; a notification sent
    back for revision a fourth time can no longer be submitted, and the attempt is
    refused with `ERR_NOTIFICATION_REVISION_LIMIT`."

    Design: Corner/errors/a_fifth_submission_after_four_rejected_reviews_is_rejected
    """
    registry = build_registry(api)
    violation = issued_violation(api, registry, reported_ng_per_l=4.50)
    notification_id = violation["notification"]["id"]

    for revision in (1, 2, 3, 4):
        submitted = validate_success(
            api.submit_notification(
                notification_id, f.notification_submit_payload(), COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert_status(submitted, "SUBMITTED")
        assert_equals(submitted, "revision_count", revision - 1)
        rejected = validate_success(
            api.review_notification(
                notification_id,
                f.notification_review_payload(
                    approve=False, review_note=f"Revision {revision} requested"
                ),
                STATE_REGULATOR_HEADERS,
            )
        )
        assert_status(rejected, "DRAFT")
        assert_equals(rejected, "revision_count", revision)
        assert_equals(rejected, "content_elements", [])
        assert_equals(rejected, "delivery_methods", [])

    validate_error(
        api.submit_notification(
            notification_id, f.notification_submit_payload(), COMPLIANCE_OFFICER_HEADERS
        ),
        ERR_NOTIFICATION_REVISION_LIMIT,
        422,
    )

    stored = read_notification(api, notification_id)
    assert_status(stored, "DRAFT")
    assert_equals(stored, "revision_count", 4)
    assert_equals(stored, "content_elements", [])


def test_issuing_an_issued_determination_and_rescinding_a_draft_share_one_code(api):
    """The same code guards both ends of the three-state machine.

    One determination is already issued and a second for the same period is still a
    draft. Issuing the issued one and rescinding the draft one are opposite
    mistakes, and both are refused with the determination state code — a handler
    that only checks for a rescission would let the double issue through, and one
    that only checks for an issuance would let the premature rescind through.
    Nothing moves: the violation counter is still one and the issued determination
    still has exactly one notice behind it.

    PRD: "Issuance requires `DRAFT` status, else `ERR_DETERMINATION_STATE_INVALID`,
    and requires `quarters_used` to be at least one"

    Design: Corner/errors/issuing_an_issued_determination_and_rescinding_a_draft_are_both_rejected
    """
    registry = build_registry(api)
    violation = issued_violation(api, registry, reported_ng_per_l=4.50)
    issued = violation["determination"]
    draft = draft_determination(
        api, registry["entry_point_id"], registry["contaminant_id"], period_end="2026Q2"
    )
    assert_status(draft, "DRAFT")

    validate_error(
        api.issue_determination(issued["id"], {}, COMPLIANCE_OFFICER_HEADERS),
        ERR_DETERMINATION_STATE_INVALID,
        422,
    )
    validate_error(
        api.rescind_determination(
            draft["id"],
            f.rescind_payload(rescind_reason="Filed against the wrong period"),
            STATE_REGULATOR_HEADERS,
        ),
        ERR_DETERMINATION_STATE_INVALID,
        422,
    )

    assert_status(read_determination(api, issued["id"]), "ISSUED")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]), open_violation_count=1
    )
    assert_total_count(
        api.list_notifications(
            COMPLIANCE_OFFICER_HEADERS, params={"determination_id": issued["id"]}
        ),
        1,
    )
    still_draft = read_determination(api, draft["id"])
    assert_status(still_draft, "DRAFT")
    assert_is_null(still_draft, "rescind_reason")


def test_the_pilot_and_manifest_guards_each_refuse_their_own_way(api):
    """Six refusals along one carbon skid, and not a kilogram leaks.

    A manifest against a still-running pilot has nothing to ship, an effluent of
    60.00 against an influent of 50.00 would have the skid manufacturing
    contaminant, and a second completion is a state error — each is refused on its
    own code and the run keeps its measurements. Once the 800.00 kilograms are on
    the ledger, resin from a carbon pilot is a media mismatch and 900.00 kilograms
    is over the remaining mass, and after both refusals the ledger still reads the
    full 800.00: an implementation that debits the mass before validating either
    condition would have leaked 1000 kilograms it never had. The legal manifest for
    exactly the remainder empties the ledger, and shipping it straight from draft
    without a regulator's classification is refused with nothing charged.

    PRD: "The mass may not exceed the pilot's remaining `unmanifested_media_kg`,
    else `ERR_MASS_EXCEEDS_SPENT_MEDIA`; a mass exactly equal to the remainder is
    permitted and empties the ledger."

    Design: Corner/errors/the_pilot_and_manifest_guards_each_refuse_their_own_way
    """
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=500000)
    pilot = register_pilot(api, f.gac_pilot_payload(evaluation["id"]))
    start_pilot(api, pilot["id"])

    validate_error(
        api.create_residuals_manifest(
            f.manifest_payload(pilot["id"], media_type="GAC_CARBON", mass_kg=100.00),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_PILOT_NOT_COMPLETED,
        422,
    )
    validate_error(
        api.complete_pilot_test(
            pilot["id"],
            f.complete_pilot_payload(
                influent_ng_per_l=50.00,
                effluent_ng_per_l=60.00,
                bed_volumes_treated=25000.00,
                spent_media_kg=800.00,
            ),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_EFFLUENT_EXCEEDS_INFLUENT,
        422,
    )
    assert_status(read_pilot(api, pilot["id"]), "RUNNING")

    completed = complete_pilot(
        api,
        pilot["id"],
        influent_ng_per_l=50.00,
        effluent_ng_per_l=1.85,
        bed_volumes_treated=25000.00,
        spent_media_kg=800.00,
    )
    assert_status(completed, "COMPLETED")
    assert_decimal(completed["removal_pct"], 96.30, label="removal_pct")
    assert_decimal(
        completed["unmanifested_media_kg"], 800.00, label="unmanifested_media_kg"
    )

    validate_error(
        api.complete_pilot_test(
            pilot["id"],
            f.complete_pilot_payload(
                influent_ng_per_l=50.00,
                effluent_ng_per_l=1.85,
                bed_volumes_treated=25000.00,
                spent_media_kg=800.00,
            ),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_PILOT_STATE_INVALID,
        422,
    )
    unchanged = read_pilot(api, pilot["id"])
    assert_decimal(unchanged["effluent_ng_per_l"], 1.85, label="effluent_ng_per_l")
    assert_decimal(unchanged["spent_media_kg"], 800.00, label="spent_media_kg")
    assert_decimal(unchanged["removal_pct"], 96.30, label="removal_pct")

    validate_error(
        api.create_residuals_manifest(
            f.manifest_payload(pilot["id"], media_type="IX_RESIN", mass_kg=100.00),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_MEDIA_TYPE_MISMATCH,
        422,
    )
    validate_error(
        api.create_residuals_manifest(
            f.manifest_payload(pilot["id"], media_type="GAC_CARBON", mass_kg=900.00),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_MASS_EXCEEDS_SPENT_MEDIA,
        422,
    )
    assert_decimal(
        read_pilot(api, pilot["id"])["unmanifested_media_kg"],
        800.00,
        label="unmanifested_media_kg",
    )

    manifest = validate_success(
        api.create_residuals_manifest(
            f.manifest_payload(pilot["id"], media_type="GAC_CARBON", mass_kg=800.00),
            TREATMENT_ENGINEER_HEADERS,
        ),
        201,
    )
    assert_status(manifest, "DRAFT")
    assert_decimal(
        read_pilot(api, pilot["id"])["unmanifested_media_kg"],
        0.00,
        label="unmanifested_media_kg",
    )

    validate_error(
        api.ship_residuals_manifest(
            manifest["id"],
            f.ship_manifest_payload("REACTIVATION", carrier_ref="CARRIER-77"),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_MANIFEST_STATE_INVALID,
        422,
    )
    assert_is_null(read_manifest(api, manifest["id"]), "disposal_method")
    assert_money_cents(
        read_evaluation(api, evaluation["id"])["residuals_spent_cents"],
        0,
        "residuals_spent_cents",
    )


def test_the_evaluation_decision_needs_the_state_before_it_needs_the_evidence(api):
    """Zero pilots fails on the state, not on the count that is also zero.

    A screening evaluation with no pilots at all fails both conditions on paper, so
    the order is observable: the refusal must name the evaluation state and must not
    name the pilot evidence. Registering the first skid moves the study to piloting
    and the entry point to pilot, and completing it clears the removal floor at
    96.30 percent, which leaves the count as the only remaining deficiency — and the
    second attempt now names exactly that. No technology is selected and no capital
    project is created by either refusal.

    PRD: "The evaluation must be in `PILOTING` status, else
    `ERR_EVALUATION_STATE_INVALID`. At least two of its pilots must have reached
    `COMPLETED` status, else `ERR_INSUFFICIENT_PILOT_EVIDENCE` — one data point is
    never enough to choose a technology, and this floor applies to both actions, so
    an evaluation cannot even be abandoned until two pilots have run."

    Design: Corner/errors/the_evaluation_decision_needs_the_state_before_it_needs_the_evidence
    """
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=500000)
    assert_status(evaluation, "SCREENING")

    premature = api.decide_treatment_evaluation(
        evaluation["id"],
        f.evaluation_decision_payload(action="SELECT", decision_note="Premature selection attempt"),
        TREATMENT_ENGINEER_HEADERS,
    )
    validate_error(premature, ERR_EVALUATION_STATE_INVALID, 422)
    assert premature.json()["data"]["error_id"] != ERR_INSUFFICIENT_PILOT_EVIDENCE, (
        "the state gate must be reported ahead of the evidence gate"
    )
    assert_status(read_evaluation(api, evaluation["id"]), "SCREENING")
    assert_equals(read_entry_point(api, entry_point["id"]), "treatment_status", "NONE")

    pilot = register_pilot(api, f.gac_pilot_payload(evaluation["id"]))
    assert_status(read_evaluation(api, evaluation["id"]), "PILOTING")
    assert_equals(read_entry_point(api, entry_point["id"]), "treatment_status", "PILOT")
    start_pilot(api, pilot["id"])
    completed = complete_pilot(
        api,
        pilot["id"],
        influent_ng_per_l=50.00,
        effluent_ng_per_l=1.85,
        bed_volumes_treated=25000.00,
        spent_media_kg=800.00,
    )
    assert_decimal(completed["removal_pct"], 96.30, label="removal_pct")

    validate_error(
        api.decide_treatment_evaluation(
            evaluation["id"],
            f.evaluation_decision_payload(
                action="SELECT", decision_note="Only one technology was piloted"
            ),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_INSUFFICIENT_PILOT_EVIDENCE,
        422,
    )

    stored = read_evaluation(api, evaluation["id"])
    assert_status(stored, "PILOTING")
    assert_is_null(stored, "selected_technology")
    assert_total_count(
        api.list_capital_projects(
            FINANCE_OFFICER_HEADERS, params={"treatment_evaluation_id": evaluation["id"]}
        ),
        0,
    )


def test_the_funding_and_construction_money_guards_are_refused_in_ladder_order(api):
    """Two award ceilings, probed one at a time, plus the two gates around them.

    Bidding without an award is refused for want of funding, while jumping straight
    to construction is refused as a state error even though the funding is missing
    too — the successor rule sits above the funding gate. A 500000000-cent award
    against a 400000000-cent request breaches the per-application ceiling and leaves
    the application submitted; the honest 400000000 is awarded with no forgiveness at
    all, which is why the ladder does not budge from 7.18 percent. A second
    400000000 award would carry the project past its own 680000000-cent cost and is
    refused on the project ceiling instead, and repeating the award already made is a
    state error. With one award on the record the very first request now succeeds.

    PRD: "An award requires `awarded_cents`, which may not exceed the application's
    own `amount_requested_cents`, else `ERR_AWARD_EXCEEDS_REQUEST`; and the
    project's existing `funding_awarded_cents` plus the new award may not exceed the
    project's `capital_cost_cents`, else `ERR_AWARD_EXCEEDS_PROJECT_COST` — the
    project cannot be funded beyond its own cost even across several programs."

    Design: Corner/errors/the_funding_and_construction_money_guards_are_rejected_in_ladder_order
    """
    entry_point = register_entry_point(api)
    selected = selected_project(api, entry_point["id"], residuals_budget_cents=500000)
    project = selected["project"]
    assert_money_cents(project["capital_cost_cents"], 680000000, "capital_cost_cents")
    assert_equals(project, "funding_status", "NOT_APPLIED")
    assert_equals(project, "construction_status", "PLANNED")

    validate_error(
        api.advance_construction(
            project["id"], f.construction_status_payload("BIDDING"), FINANCE_OFFICER_HEADERS
        ),
        ERR_FUNDING_NOT_SECURED,
        422,
    )
    validate_error(
        api.advance_construction(
            project["id"], f.construction_status_payload("CONSTRUCTION"), FINANCE_OFFICER_HEADERS
        ),
        ERR_PROJECT_STATE_INVALID,
        422,
    )

    application = apply_for_funding(
        api,
        project["id"],
        program="SRF_LOAN",
        amount_requested_cents=400000000,
        disadvantaged_community=False,
    )
    validate_error(
        api.decide_funding_application(
            application["id"],
            f.award_payload(500000000, decision_note="Over-award attempt"),
            STATE_REGULATOR_HEADERS,
        ),
        ERR_AWARD_EXCEEDS_REQUEST,
        422,
    )
    assert_status(read_application(api, application["id"]), "SUBMITTED")

    awarded = validate_success(
        api.decide_funding_application(
            application["id"],
            f.award_payload(400000000, decision_note="Standard SRF loan, no forgiveness"),
            STATE_REGULATOR_HEADERS,
        )
    )
    assert_status(awarded, "AWARDED")
    assert_decimal(awarded["forgiveness_pct"], 0.00, label="forgiveness_pct")
    assert_money_cents(awarded["forgiven_cents"], 0, "forgiven_cents")
    funded = read_project(api, project["id"])
    assert_money_cents(funded["funding_awarded_cents"], 400000000, "funding_awarded_cents")
    assert_equals(funded, "funding_status", "AWARDED")
    assert_rate_ladder(funded, rate_impact_pct=7.18)

    second = apply_for_funding(
        api,
        project["id"],
        program="EC_GRANT",
        amount_requested_cents=400000000,
        disadvantaged_community=False,
    )
    validate_error(
        api.decide_funding_application(
            second["id"],
            f.award_payload(400000000, decision_note="Second award attempt"),
            STATE_REGULATOR_HEADERS,
        ),
        ERR_AWARD_EXCEEDS_PROJECT_COST,
        422,
    )
    assert_status(read_application(api, second["id"]), "SUBMITTED")
    assert_money_cents(
        read_project(api, project["id"])["funding_awarded_cents"],
        400000000,
        "funding_awarded_cents",
    )

    validate_error(
        api.decide_funding_application(
            application["id"],
            f.award_payload(400000000, decision_note="Repeat of an award already made"),
            STATE_REGULATOR_HEADERS,
        ),
        ERR_APPLICATION_STATE_INVALID,
        422,
    )

    bidding = validate_success(
        api.advance_construction(
            project["id"], f.construction_status_payload("BIDDING"), FINANCE_OFFICER_HEADERS
        )
    )
    assert_equals(bidding, "construction_status", "BIDDING")


def test_the_cost_recovery_claim_refuses_every_out_of_order_resolution(api):
    """One code for three illegal moves, and the ceiling is the filed figure.

    The informational basis is 341000000 cents — half of the project cost plus the
    investigation spend — but only 300000000 is ever filed, and that filed figure is
    what bounds a settlement. Settling before filing, filing a second time and
    settling a claim already dismissed are three different mistakes on the same row
    and all three answer with the claim state code, while the over-recovery answers
    with its own. The dismissal zeroes the recovery and all four buckets and leaves
    the project entirely alone, so nothing was ever recovered and the ladder still
    reads 7.18 percent.

    PRD: "A settlement is permitted only from `CLAIM_FILED` status, else
    `ERR_CLAIM_STATE_INVALID`, requires `recovered_cents`, and that recovery may not
    exceed the `claimed_cents` on the claim, else `ERR_RECOVERY_EXCEEDS_CLAIM`."

    Design: Corner/errors/the_cost_recovery_claim_refuses_every_out_of_order_resolution
    """
    entry_point = register_entry_point(api)
    selected = selected_project(api, entry_point["id"], residuals_budget_cents=500000)
    project = selected["project"]
    claim = open_claim(
        api,
        entry_point["id"],
        project["id"],
        responsible_party_name="Ridgeline Coatings",
        investigation_basis="UPSTREAM_DISCHARGER",
        allocation_pct=50.00,
        investigation_cost_cents=2000000,
    )
    assert_status(claim, "INVESTIGATING")
    assert_money_cents(claim["claim_basis_cents"], 341000000, "claim_basis_cents")

    validate_error(
        api.resolve_cost_recovery_claim(
            claim["id"],
            f.settle_claim_payload(100000000, resolution_note="Settling before filing"),
            FINANCE_OFFICER_HEADERS,
        ),
        ERR_CLAIM_STATE_INVALID,
        422,
    )

    filed = validate_success(
        api.file_cost_recovery_claim(
            claim["id"], f.file_claim_payload(300000000), COMPLIANCE_OFFICER_HEADERS
        )
    )
    assert_status(filed, "CLAIM_FILED")
    assert_money_cents(filed["claimed_cents"], 300000000, "claimed_cents")
    assert_instant_equals(filed["filed_at"], DEFAULT_CLOCK, label="filed_at")

    validate_error(
        api.file_cost_recovery_claim(
            claim["id"], f.file_claim_payload(250000000), COMPLIANCE_OFFICER_HEADERS
        ),
        ERR_CLAIM_STATE_INVALID,
        422,
    )
    assert_money_cents(
        read_claim(api, claim["id"])["claimed_cents"], 300000000, "claimed_cents"
    )

    validate_error(
        api.resolve_cost_recovery_claim(
            claim["id"],
            f.settle_claim_payload(400000000, resolution_note="Over-recovery attempt"),
            FINANCE_OFFICER_HEADERS,
        ),
        ERR_RECOVERY_EXCEEDS_CLAIM,
        422,
    )
    assert_status(read_claim(api, claim["id"]), "CLAIM_FILED")

    dismissed = validate_success(
        api.resolve_cost_recovery_claim(
            claim["id"],
            f.dismiss_claim_payload(resolution_note="Responsible party dissolved"),
            FINANCE_OFFICER_HEADERS,
        )
    )
    assert_status(dismissed, "DISMISSED")
    assert_allocation_buckets(
        dismissed,
        investigation=0,
        capital=0,
        om_reserve=0,
        rate_stabilization=0,
        recovered=0,
    )
    untouched = read_project(api, project["id"])
    assert_money_cents(untouched["recovered_cents"], 0, "recovered_cents")
    assert_rate_ladder(untouched, local_share_cents=680000000, rate_impact_pct=7.18)

    validate_error(
        api.resolve_cost_recovery_claim(
            claim["id"],
            f.settle_claim_payload(100000000, resolution_note="Reviving a dismissed claim"),
            FINANCE_OFFICER_HEADERS,
        ),
        ERR_CLAIM_STATE_INVALID,
        422,
    )


def test_the_reduction_request_checks_the_state_then_the_open_violation_count(api):
    """A recovered posture is not a cleared violation, and the two gates prove it.

    An entry point that was never sampled is still at INITIAL, so both halves of the
    reduction protocol refuse it on the monitoring state. On the sampled entry point
    the invalidation of the quarter behind the violation supersedes its result and
    re-derives the posture all the way back to COMPLIANT with a ratio of zero, which
    is exactly what makes the ordering visible: the posture gate now passes, so the
    refusal must be the open-violation gate and not the posture one. Only the
    rescission clears the counter, voiding the notice that was never distributed, and
    the very same request then advances one rung further to fail on the history it
    no longer has.

    PRD: "Its `open_violation_count` must be zero, else
    `ERR_OPEN_VIOLATION_BLOCKS_REDUCTION`; an unrescinded exceedance blocks relief
    even after the posture itself has recovered, which is why the two checks are
    separate."

    Design: Corner/errors/the_reduction_request_checks_the_state_then_the_open_violation_count
    """
    registry = build_registry(api)
    fresh = register_entry_point(
        api, label="EPTDS-04", source_type="PURCHASED", population_served=12000
    )
    violation = issued_violation(api, registry, reported_ng_per_l=4.50)
    determination = violation["determination"]
    assert_entry_point_posture(
        read_entry_point(api, fresh["id"]), monitoring_status="INITIAL"
    )

    validate_error(
        api.request_monitoring_reduction(
            fresh["id"],
            f.reduction_request_payload(
                target_status="ANNUAL", justification="Never sampled, no history at all"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_MONITORING_STATE_INVALID,
        422,
    )
    validate_error(
        api.decide_monitoring_reduction(
            fresh["id"],
            f.reduction_decision_payload(
                approve=True, decision_note="Deciding a request that was never opened"
            ),
            STATE_REGULATOR_HEADERS,
        ),
        ERR_MONITORING_STATE_INVALID,
        422,
    )
    still_initial = read_entry_point(api, fresh["id"])
    assert_entry_point_posture(still_initial, monitoring_status="INITIAL")
    assert_is_null(still_initial, "requested_monitoring_status")

    invalidated = validate_success(
        api.invalidate_sample(
            violation["quarter"]["sample_id"],
            f.invalidate_sample_payload(invalidation_reason="OPERATOR_ERROR"),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    assert_status(invalidated, "INVALIDATED")
    assert_status(read_lab_result(api, violation["quarter"]["result_id"]), "SUPERSEDED")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        posture="COMPLIANT",
        monitoring_status="QUARTERLY",
        accepted_result_count=0,
        max_compliance_ratio=0.0000,
        consecutive_qualifying_quarters=0,
        consecutive_invalidated_samples=1,
        open_violation_count=1,
    )

    blocked = api.request_monitoring_reduction(
        registry["entry_point_id"],
        f.reduction_request_payload(
            target_status="ANNUAL", justification="Posture has returned to compliant"
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(blocked, ERR_OPEN_VIOLATION_BLOCKS_REDUCTION, 422)
    assert blocked.json()["data"]["error_id"] != ERR_VIOLATION_PENDING_BLOCKS_REDUCTION, (
        "the posture gate passed, so the open-violation gate must be the refusal"
    )

    rescinded = validate_success(
        api.rescind_determination(
            determination["id"],
            f.rescind_payload(
                rescind_reason="Underlying sample invalidated for operator error"
            ),
            STATE_REGULATOR_HEADERS,
        )
    )
    assert_status(rescinded, "RESCINDED")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]), open_violation_count=0
    )
    assert_status(read_notification(api, violation["notification"]["id"]), "VOIDED")

    validate_error(
        api.request_monitoring_reduction(
            registry["entry_point_id"],
            f.reduction_request_payload(
                target_status="ANNUAL", justification="Violation rescinded, requesting reduction"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_INSUFFICIENT_MONITORING_HISTORY,
        422,
    )
    final = read_entry_point(api, registry["entry_point_id"])
    assert_entry_point_posture(final, monitoring_status="QUARTERLY")
    assert_is_null(final, "requested_monitoring_status")


def test_a_triennial_request_backed_by_only_four_quarters_is_refused(api):
    """Four qualifying quarters clear one target and fail the other on the same row.

    Every one of the four accepted readings is 1.00 against a trigger of 2.00, so
    all four quarters qualify and the frozen ratio is 0.2500 with the posture
    compliant and no violations open. That record is exactly the ANNUAL floor and
    exactly half the TRIENNIAL one, so the TRIENNIAL request must be refused on the
    triennial code and not on the general history code, and the refusal leaves the
    entry point quarterly with nothing requested. The identical request for ANNUAL
    then opens the reduction and the regulator's approval lands the entry point on
    the status the request recorded.

    PRD: "`consecutive_qualifying_quarters` must be at least four, else
    `ERR_INSUFFICIENT_MONITORING_HISTORY`. And a `TRIENNIAL` request demands a
    longer record still: at least eight consecutive qualifying quarters, else
    `ERR_TRIENNIAL_HISTORY_INSUFFICIENT`."

    Design: Corner/errors/a_triennial_request_backed_by_only_four_quarters_is_rejected
    """
    registry = build_registry(api, entry_point_overrides={"label": "EPTDS-05"})
    accepted_quarters(
        api,
        registry,
        [("2025Q3", 1.00), ("2025Q4", 1.00), ("2026Q1", 1.00), ("2026Q2", 1.00)],
    )

    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        posture="COMPLIANT",
        monitoring_status="QUARTERLY",
        accepted_result_count=4,
        max_compliance_ratio=0.2500,
        consecutive_qualifying_quarters=4,
        open_violation_count=0,
    )

    triennial = api.request_monitoring_reduction(
        registry["entry_point_id"],
        f.reduction_request_payload(
            target_status="TRIENNIAL", justification="Four clean quarters on record"
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(triennial, ERR_TRIENNIAL_HISTORY_INSUFFICIENT, 422)
    assert triennial.json()["data"]["error_id"] != ERR_INSUFFICIENT_MONITORING_HISTORY, (
        "four quarters clears the annual floor, so the triennial code is the refusal"
    )
    refused = read_entry_point(api, registry["entry_point_id"])
    assert_entry_point_posture(refused, monitoring_status="QUARTERLY")
    assert_is_null(refused, "requested_monitoring_status")

    pending = validate_success(
        api.request_monitoring_reduction(
            registry["entry_point_id"],
            f.reduction_request_payload(
                target_status="ANNUAL", justification="Four clean quarters on record"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    assert_equals(pending, "monitoring_status", "REDUCTION_PENDING")
    assert_equals(pending, "requested_monitoring_status", "ANNUAL")

    decided = validate_success(
        api.decide_monitoring_reduction(
            registry["entry_point_id"],
            f.reduction_decision_payload(approve=True, decision_note="Annual monitoring approved"),
            STATE_REGULATOR_HEADERS,
        )
    )
    assert_equals(decided, "monitoring_status", "ANNUAL")
    assert_is_null(decided, "requested_monitoring_status")
