"""Terms-of-service enforcement on the developer record: opening and adjudicating violation
cases, the fourteen-day appeal window with its one-appeal-per-case limit, the two-operator
separation the enforcement chain insists on, and how the programme's two trust-score variants
read one and the same stored enforcement data to different numbers.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_instant_equals, assert_trust_scores
from test_helpers.constants import TRUST_OFFICER_ALT_ID, TRUST_OFFICER_ID, UNKNOWN_ID
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    TRUST_OFFICER,
    TRUST_OFFICER_ALT,
    make_platform_admin_headers,
)


def test_snapshot_trust_score_ignores_pending_exposure_and_throttling(api, programme):
    """A developer with a still-running case and two throttled windows keeps the snapshot
    trust score of 71 that its certification and documentation earned: the snapshot variant
    charges neither the pending case nor the throttling, and no points are settled yet.

    PRD: "It stops there: base plus certification plus documentation plus hackathon plus clean-window points, minus settled penalty, clamped to 0 through 100. It ignores penalty exposure from cases that are still running and ignores `throttled_window_count` entirely."

    PRD: "in every other case `throttled_window_count` increments by one and `clean_window_count` is reset to 0"

    Design: Difficulty/dual_variant_calc/trust_score_snapshot_vs_audited_diverge_on_pending_case
    """
    bundle = programme.entitlement_chain(certified=True)
    developer = bundle["developer"]
    assignment = bundle["assignment"]

    programme.set_clock("2026-08-02T00:00:00Z")
    programme.record_window(assignment, "2026-08-01T00:00:00Z", 200000, 50000)
    programme.record_window(assignment, "2026-08-01T01:00:00Z", 200000, 50000)
    programme.record_window(assignment, "2026-08-01T02:00:00Z", 50000, 0)
    programme.record_window(assignment, "2026-08-01T03:00:00Z", 100000, 0)

    case = programme.open_case(
        developer,
        category="DATA_RETENTION",
        severity="HIGH",
        summary="Retention window exceeded on catalogue exports.",
        quota_assignment_id=assignment["id"],
    )
    programme.investigate_case(case)
    programme.certify(developer)

    validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN))

    stored = validate_success(api.get_developer(developer["id"], PLATFORM_ADMIN))
    assert_fields(
        stored,
        "Developer",
        throttled_window_count=2,
        clean_window_count=0,
        violation_points=0,
        trust_score=71,
    )


def test_audited_trust_score_charges_half_the_pending_exposure_and_the_throttling_penalty(
    api, programme
):
    """The audited rescoring of the same developer subtracts 30 points — half of the pending
    case's 60 — plus the 5-point throttling penalty, so the audited score reads 36 against a
    snapshot of 71 on identical stored data.

    PRD: "First, **pending exposure**: the sum of `penalty_points` across the developer's violation cases whose `state` is `OPENED`, `INVESTIGATING` or `APPEALED`, multiplied by **0.50** and rounded half up to a whole number of points. Second, a **throttling penalty** of **5 points**, charged whenever `throttled_window_count` is at least **2** and 0 points otherwise."

    Design: Difficulty/dual_variant_calc/trust_score_snapshot_vs_audited_diverge_on_pending_case
    """
    bundle = programme.entitlement_chain(certified=True)
    developer = bundle["developer"]
    assignment = bundle["assignment"]

    programme.set_clock("2026-08-02T00:00:00Z")
    programme.record_window(assignment, "2026-08-01T00:00:00Z", 200000, 50000)
    programme.record_window(assignment, "2026-08-01T01:00:00Z", 200000, 50000)
    programme.record_window(assignment, "2026-08-01T02:00:00Z", 50000, 0)
    programme.record_window(assignment, "2026-08-01T03:00:00Z", 100000, 0)

    case = programme.open_case(
        developer,
        category="DATA_RETENTION",
        severity="HIGH",
        summary="Retention window exceeded on catalogue exports.",
        quota_assignment_id=assignment["id"],
    )
    programme.investigate_case(case)
    programme.certify(developer)

    summary = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN))
    assert developer["id"] in summary["rescored_developer_ids"], (
        "the rescored developer is not reported in rescored_developer_ids"
    )

    stored_case = validate_success(api.get_violation_case(case["id"], PLATFORM_ADMIN))
    assert_fields(
        stored_case,
        "ViolationCase",
        state="INVESTIGATING",
        penalty_points=60,
        points_applied=0,
    )

    stored = validate_success(api.get_developer(developer["id"], PLATFORM_ADMIN))
    assert_trust_scores(stored, trust_score=71, audited_trust_score=36)
    assert stored["trust_score"] - stored["audited_trust_score"] == 35, (
        "the two variants should diverge by exactly 35 points on this data: "
        f"{stored['trust_score']} vs {stored['audited_trust_score']}"
    )


def test_an_upheld_case_accepts_one_appeal_and_a_second_adjudication_returns_it_to_upheld(
    api, programme
):
    """A scope-overreach case worth 30 points is upheld with a fourteen-day appeal window, the
    developer appeals once, and upholding the appeal returns the case to UPHELD without adding
    further points and without extending the deadline.

    PRD: "On success the case moves `UPHELD → APPEALED`, records `appeal_reason` and increments `appeal_count` to 1."

    PRD: "Upholding an appealed case instead moves `APPEALED → UPHELD`: the points that were already applied remain applied, nothing further is added, and `appeal_deadline` is **not** extended."

    Design: Difficulty/non_linear_state_machine/violation_case_appeal_cycle_single_appeal_only
    """
    bundle = programme.entitlement_chain()
    developer = bundle["developer"]
    developer_headers = bundle["developer_headers"]

    case = programme.open_case(
        developer,
        category="SCOPE_OVERREACH",
        severity="MEDIUM",
        summary="Requests observed against a scope that was never granted on this entitlement.",
        quota_assignment_id=bundle["assignment"]["id"],
    )
    programme.investigate_case(case)

    upheld = validate_success(
        api.adjudicate_violation_case(
            case["id"],
            f.adjudicate_payload(
                outcome="UPHELD",
                decision_note="Access logs confirm calls to an ungranted scope.",
            ),
            PLATFORM_ADMIN,
        )
    )
    assert_fields(
        upheld, "ViolationCase", state="UPHELD", penalty_points=30, points_applied=30
    )
    assert_instant_equals(upheld["appeal_deadline"], "2026-08-15T00:00:00Z", "appeal_deadline")
    assert_fields(
        programme.read_developer(developer["id"]),
        "Developer",
        violation_points=30,
        standing="UNDER_REVIEW",
    )

    appealed = validate_success(
        api.appeal_violation_case(
            case["id"],
            f.appeal_payload(
                appeal_reason=(
                    "The calls originated from a decommissioned staging client that has "
                    "since been retired."
                )
            ),
            developer_headers,
        )
    )
    assert_fields(appealed, "ViolationCase", state="APPEALED", appeal_count=1)
    assert appealed["appeal_reason"] is not None, "the filed appeal reason was not recorded"

    re_upheld = validate_success(
        api.adjudicate_violation_case(
            case["id"],
            f.adjudicate_payload(
                outcome="UPHELD",
                decision_note="The staging client used production credentials; the finding stands.",
            ),
            PLATFORM_ADMIN,
        )
    )
    assert_fields(
        re_upheld,
        "ViolationCase",
        state="UPHELD",
        appeal_count=1,
        penalty_points=30,
        points_applied=30,
    )
    assert_instant_equals(
        re_upheld["appeal_deadline"], "2026-08-15T00:00:00Z", "appeal_deadline"
    )
    assert_fields(
        programme.read_developer(developer["id"]), "Developer", violation_points=30
    )


def test_a_second_appeal_is_refused_although_the_case_sits_in_upheld_again(api, programme):
    """Once the single permitted appeal has been filed and decided, a second appeal of the very
    same UPHELD case is refused on the appeal counter rather than on state, and the refusal
    leaves the case, the penalty ledger and the entitlement exactly as they were.

    PRD: "and `appeal_count` must still be 0, otherwise `ERR_APPEAL_ALREADY_FILED` (HTTP 409)"

    Design: Difficulty/non_linear_state_machine/violation_case_appeal_cycle_single_appeal_only
    """
    bundle = programme.entitlement_chain()
    developer = bundle["developer"]
    developer_headers = bundle["developer_headers"]

    case = programme.open_case(
        developer,
        category="SCOPE_OVERREACH",
        severity="MEDIUM",
        summary="Requests observed against a scope that was never granted on this entitlement.",
        quota_assignment_id=bundle["assignment"]["id"],
    )
    programme.investigate_case(case)
    programme.adjudicate_case(case, outcome="UPHELD")
    programme.appeal_case(case, developer)
    programme.adjudicate_case(
        case,
        outcome="UPHELD",
        decision_note="The staging client used production credentials; the finding stands.",
    )

    refused = api.appeal_violation_case(
        case["id"],
        f.appeal_payload(appeal_reason="We would like the finding reviewed once more."),
        developer_headers,
    )
    validate_error(refused, ApiError.APPEAL_ALREADY_FILED)

    stored = validate_success(api.get_violation_case(case["id"], PLATFORM_ADMIN))
    assert_fields(
        stored, "ViolationCase", state="UPHELD", appeal_count=1, points_applied=30
    )
    assert_fields(
        programme.read_developer(developer["id"]), "Developer", violation_points=30
    )
    assert_fields(
        programme.read_entitlement(bundle["assignment"]["id"]),
        "QuotaAssignment",
        entitlement_state="ACTIVE",
    )


def test_evidence_citing_an_unknown_usage_window_is_refused_as_not_found(api, programme):
    """Cited evidence is resolved before anything else about it is judged: an identifier that
    names no usage window at all is refused as not found, and no case is left behind.

    PRD: "Each cited identifier must reference an existing usage window, failing with `ERR_USAGE_WINDOW_NOT_FOUND` (HTTP 404), and each must belong to an entitlement of the *target developer*, failing with `ERR_EVIDENCE_NOT_ATTRIBUTABLE` (HTTP 422)"

    Design: Corner/validations/evidence_existence_is_checked_before_attributability
    """
    bundle = programme.entitlement_chain()
    developer = bundle["developer"]

    programme.set_clock("2026-08-02T00:00:00Z")
    programme.record_window(bundle["assignment"], "2026-08-01T00:00:00Z", 100000)

    refused = api.create_violation_case(
        f.violation_case_payload(
            developer["id"],
            category="RATE_ABUSE",
            severity="MEDIUM",
            summary="Sustained call rate far above the entitled ceiling.",
            quota_assignment_id=bundle["assignment"]["id"],
            evidence_window_ids=[UNKNOWN_ID],
        ),
        TRUST_OFFICER,
    )
    validate_error(refused, ApiError.USAGE_WINDOW_NOT_FOUND)

    cases, meta = validate_paginated(
        api.list_violation_cases(TRUST_OFFICER, {"developer_id": developer["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused case must not have been stored, but total_count is {meta['total_count']}"
    )
    assert cases == [], f"no case should exist for this developer, got {cases}"


def test_a_usage_window_of_another_developer_is_refused_as_not_attributable(api, programme):
    """A real usage window that belongs to a different developer's entitlement cannot serve as
    evidence against this developer, while its own window is accepted and stored on the case.

    PRD: "Each cited identifier must reference an existing usage window, failing with `ERR_USAGE_WINDOW_NOT_FOUND` (HTTP 404), and each must belong to an entitlement of the *target developer*, failing with `ERR_EVIDENCE_NOT_ATTRIBUTABLE` (HTTP 422)"

    PRD: "The case is created in `state` `OPENED` with `points_applied` 0, `appeal_count` 0, `opened_by_user_id` taken from `X-User-ID`, and `investigator_user_id`, `adjudicator_user_id`, `remediation_deadline`, `appeal_deadline`, `outcome`, `appeal_reason` and `decision_note` all null."

    Design: Corner/validations/evidence_existence_is_checked_before_attributability
    """
    first = programme.entitlement_chain()
    second = programme.entitlement_chain(product=first["product"])

    programme.set_clock("2026-08-02T00:00:00Z")
    own_window = programme.record_window(first["assignment"], "2026-08-01T00:00:00Z", 100000)
    other_window = programme.record_window(second["assignment"], "2026-08-01T00:00:00Z", 100000)

    refused = api.create_violation_case(
        f.violation_case_payload(
            first["developer"]["id"],
            category="RATE_ABUSE",
            severity="MEDIUM",
            summary="Sustained call rate far above the entitled ceiling.",
            quota_assignment_id=first["assignment"]["id"],
            evidence_window_ids=[other_window["id"]],
        ),
        TRUST_OFFICER,
    )
    validate_error(refused, ApiError.EVIDENCE_NOT_ATTRIBUTABLE)

    opened = validate_success(
        api.create_violation_case(
            f.violation_case_payload(
                first["developer"]["id"],
                category="RATE_ABUSE",
                severity="MEDIUM",
                summary="Sustained call rate far above the entitled ceiling.",
                quota_assignment_id=first["assignment"]["id"],
                evidence_window_ids=[own_window["id"]],
            ),
            TRUST_OFFICER,
        ),
        expected_status=201,
    )
    assert_fields(
        opened,
        "ViolationCase",
        state="OPENED",
        penalty_points=20,
        points_applied=0,
        appeal_count=0,
        opened_by_user_id=TRUST_OFFICER_ID,
    )
    assert opened["evidence_window_ids"] == [own_window["id"]], (
        "only the target developer's own window should be cited on the stored case: "
        f"{opened['evidence_window_ids']}"
    )
    assert opened["investigator_user_id"] is None, "a freshly opened case has no investigator"

    _, meta = validate_paginated(
        api.list_violation_cases(TRUST_OFFICER, {"developer_id": first["developer"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"exactly one case should have been stored, but total_count is {meta['total_count']}"
    )


def test_an_appeal_filed_after_the_deadline_is_refused(api, programme):
    """The fourteen-day appeal window closes: with the clock moved a day past the recorded
    appeal deadline the developer's appeal is refused, and the case keeps its unappealed shape.

    PRD: "the logical clock must be at or before the case's `appeal_deadline`, otherwise `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422)"

    PRD: "sets `appeal_deadline` to the logical clock advanced by the **14-day** appeal window"

    Design: Corner/errors/appeal_after_the_deadline_is_refused
    """
    developer = programme.register_developer()

    case = programme.open_case(
        developer,
        category="RATE_ABUSE",
        severity="MEDIUM",
        summary="Sustained call rate far above the entitled ceiling.",
    )
    programme.investigate_case(case)
    upheld = validate_success(
        api.adjudicate_violation_case(
            case["id"], f.adjudicate_payload(outcome="UPHELD"), PLATFORM_ADMIN
        )
    )
    assert_fields(
        upheld, "ViolationCase", state="UPHELD", penalty_points=20, points_applied=20
    )
    assert_instant_equals(upheld["appeal_deadline"], "2026-08-15T00:00:00Z", "appeal_deadline")
    assert_fields(
        programme.read_developer(developer["id"]), "Developer", violation_points=20
    )

    programme.set_clock("2026-08-16T00:00:00Z")

    refused = api.appeal_violation_case(
        case["id"],
        f.appeal_payload(appeal_reason="We only learned of the finding this morning."),
        programme.headers_for(developer),
    )
    validate_error(refused, ApiError.APPEAL_WINDOW_CLOSED)

    stored = validate_success(api.get_violation_case(case["id"], PLATFORM_ADMIN))
    assert_fields(
        stored, "ViolationCase", state="UPHELD", appeal_count=0, points_applied=20
    )
    assert stored["appeal_reason"] is None, (
        f"the refused appeal must not have been recorded: {stored['appeal_reason']}"
    )


def test_the_investigating_officer_may_not_adjudicate_the_case_it_investigated(api, programme):
    """The officer recorded as investigator is barred from deciding the same case even when
    acting with administrator authority; the case waits in INVESTIGATING until a different
    operator adjudicates it.

    PRD: "The case must be in `INVESTIGATING` or `APPEALED`, otherwise `ERR_CASE_STATE_INVALID`, and the acting operator's `X-User-ID` must differ from the recorded `investigator_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_investigator_may_neither_adjudicate_nor_revoke
    """
    developer = programme.register_developer()
    case = programme.open_case(
        developer,
        category="RATE_ABUSE",
        severity="MEDIUM",
        summary="Sustained call rate far above the entitled ceiling.",
    )
    investigating = programme.investigate_case(case, headers=TRUST_OFFICER)
    assert_fields(
        investigating,
        "ViolationCase",
        state="INVESTIGATING",
        investigator_user_id=TRUST_OFFICER_ID,
    )

    refused = api.adjudicate_violation_case(
        case["id"],
        f.adjudicate_payload(outcome="UPHELD"),
        make_platform_admin_headers(TRUST_OFFICER_ID),
    )
    validate_error(refused, ApiError.SEGREGATION_OF_DUTIES)

    untouched = validate_success(api.get_violation_case(case["id"], PLATFORM_ADMIN))
    assert_fields(
        untouched, "ViolationCase", state="INVESTIGATING", points_applied=0
    )
    assert untouched["outcome"] is None, "the refused decision must not have been recorded"
    assert untouched["adjudicator_user_id"] is None, (
        "the refused operator must not have been recorded as adjudicator"
    )
    assert_fields(
        programme.read_developer(developer["id"]), "Developer", violation_points=0
    )

    upheld = validate_success(
        api.adjudicate_violation_case(
            case["id"], f.adjudicate_payload(outcome="UPHELD"), PLATFORM_ADMIN
        )
    )
    assert_fields(
        upheld, "ViolationCase", state="UPHELD", penalty_points=20, points_applied=20
    )
    assert_fields(
        programme.read_developer(developer["id"]), "Developer", violation_points=20
    )


def test_an_officer_who_investigated_any_case_of_the_developer_may_not_revoke_it(api, programme):
    """Two upheld resale findings put the developer at 150 points and RESTRICTED standing, which
    is grounds for revocation — but the officer who investigated the second case is barred from
    revoking, while an operator who investigated nothing succeeds.

    PRD: "The revoking operator must not be the recorded investigator of *any* of that developer's cases, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "On success `standing` moves `RESTRICTED → REVOKED`, which is terminal, and `revoked_at` is set from the logical clock."

    Design: Corner/rbac/the_investigator_may_neither_adjudicate_nor_revoke
    """
    developer = programme.register_developer()
    first_case = programme.open_case(
        developer,
        category="RESALE",
        severity="HIGH",
        summary="Entitled catalogue data resold through an unauthorised reseller portal.",
    )
    second_case = programme.open_case(
        developer,
        category="RESALE",
        severity="HIGH",
        summary="A second reseller portal found serving the same entitled catalogue data.",
    )
    programme.investigate_case(first_case, headers=TRUST_OFFICER)
    programme.investigate_case(second_case, headers=TRUST_OFFICER_ALT)
    programme.adjudicate_case(first_case, outcome="UPHELD")
    programme.adjudicate_case(second_case, outcome="UPHELD")

    restricted = programme.read_developer(developer["id"])
    assert_fields(
        restricted, "Developer", violation_points=150, standing="RESTRICTED"
    )

    refused = api.revoke_developer_access(
        developer["id"],
        f.revoke_access_payload(),
        make_platform_admin_headers(TRUST_OFFICER_ALT_ID),
    )
    validate_error(refused, ApiError.SEGREGATION_OF_DUTIES)

    still_restricted = validate_success(api.get_developer(developer["id"], PLATFORM_ADMIN))
    assert_fields(still_restricted, "Developer", standing="RESTRICTED")
    assert still_restricted["revoked_at"] is None, (
        "the refused revocation must not have stamped revoked_at"
    )

    revoked = validate_success(
        api.revoke_developer_access(
            developer["id"], f.revoke_access_payload(), PLATFORM_ADMIN
        )
    )
    assert_fields(revoked, "Developer", standing="REVOKED", violation_points=150)
    assert_instant_equals(revoked["revoked_at"], "2026-08-01T00:00:00Z", "revoked_at")
