"""What makes an access application admissible: the tier-scaled justification floor checked at
submission rather than at drafting, the scope-sensitivity and tier-rank bounds that constrain both
the request and the decision, the currency of the developer's accepted terms, and the fixed order in
which two simultaneous refusals resolve to exactly one error.
"""
from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_instant_equals
from test_helpers.constants import CANONICAL_SCOPE, JUSTIFICATION_PARTNER
from test_helpers.test_users import DEV_REL_MANAGER, PLATFORM_ADMIN
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

JUSTIFICATION_ONE_SHORT = (
    "Partner tier is required for our nightly settlement reconciliation runs across twelve "
    "regulated market venues in Europe"
)
JUSTIFICATION_AT_MINIMUM = JUSTIFICATION_ONE_SHORT + "."

FINANCIAL_SCOPE = "payments.read"
PERSONAL_SCOPE = "profile.read"


def _payments_product(programme):
    """A financial product whose catalogue spans all three sensitivities."""
    return programme.create_product(
        name="Payments API",
        data_sensitivity="FINANCIAL",
        scope_catalog=[
            f.scope_entry(CANONICAL_SCOPE, "PUBLIC"),
            f.scope_entry(PERSONAL_SCOPE, "PERSONAL"),
            f.scope_entry(FINANCIAL_SCOPE, "FINANCIAL"),
        ],
    )


def test_stale_terms_outrank_the_ungrantable_version_when_one_submission_breaks_both(
    api, programme
):
    """A submission that simultaneously carries an out-of-date terms acceptance and names a version
    that has been deprecated out of grantability is refused for the terms, because that check sits in
    an earlier band; neither breach was visible when the draft was written.

    PRD: "When a single request violates several rules at once, exactly one error is returned, and
    which one is fully determined. The server evaluates checks in the fixed order below, from the
    top, and returns the first failure it finds."
    PRD: "The developer's `tos_version_accepted` is at least the target product's
    `required_tos_version` — `ERR_TOS_VERSION_STALE`, 422, on application submission, entitlement
    provisioning and sandbox-lease creation."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_submit_with_stale_tos_and_deprecated_version
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.draft_application(developer, version)
    programme.adjust_product(
        product["id"],
        required_tos_version=2,
        adjustment_reason="New data-processing addendum published as terms revision 2.",
    )
    programme.announce_deprecation(version["id"], notice_days=30)

    validate_error(
        api.submit_access_application(
            application["id"], f.submit_application_payload(), programme.headers_for(developer)
        ),
        ApiError.TOS_VERSION_STALE,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication",
        state="DRAFT", revision_round=0,
    )


def test_both_conflicting_conditions_hold_at_the_moment_the_submission_is_refused(api, programme):
    """The refusal is genuinely a conflict and not a single breach: the product now demands the later
    terms revision the developer never accepted, and the pinned version has moved out of
    grantability with its notice period and sunset instant recorded.

    PRD: "Pools are resizable through a **programme adjustment**, which accepts any combination of a
    new `sustained_rpm_pool`, a new `monthly_call_pool` and a new `required_tos_version`, together
    with a mandatory `adjustment_reason`."
    PRD: "A version in `DEPRECATION_ANNOUNCED` or `SUNSET` is grantable to no tier at all. Any
    mismatch is rejected with `ERR_VERSION_NOT_GRANTABLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_submit_with_stale_tos_and_deprecated_version
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.draft_application(developer, version)
    programme.adjust_product(
        product["id"],
        required_tos_version=2,
        adjustment_reason="New data-processing addendum published as terms revision 2.",
    )
    announced = programme.announce_deprecation(version["id"], notice_days=30)

    validate_error(
        api.submit_access_application(
            application["id"], f.submit_application_payload(), programme.headers_for(developer)
        ),
        ApiError.TOS_VERSION_STALE,
    )

    assert_fields(programme.read_product(product["id"]), "ApiProduct", required_tos_version=2)
    assert_fields(
        programme.read_developer(developer["id"]), "Developer", tos_version_accepted=1
    )
    assert_fields(
        announced, "ApiVersion",
        lifecycle_state="DEPRECATION_ANNOUNCED", required_notice_days=30,
    )
    assert_instant_equals(announced["sunset_at"], "2026-08-31T00:00:00Z", "sunset_at")


def test_the_ungrantable_version_surfaces_once_the_terms_acceptance_is_current(api, programme):
    """The later rule is not lost, only masked: a developer who accepted the revised terms breaches
    only the version's grantability, and that is the error its submission receives.

    PRD: "A version in `DEPRECATION_ANNOUNCED` or `SUNSET` is grantable to no tier at all. Any
    mismatch is rejected with `ERR_VERSION_NOT_GRANTABLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_submit_with_stale_tos_and_deprecated_version
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    programme.adjust_product(
        product["id"],
        required_tos_version=2,
        adjustment_reason="New data-processing addendum published as terms revision 2.",
    )
    programme.announce_deprecation(version["id"], notice_days=30)
    current = programme.register_developer()
    programme.acknowledge(current, docs_version=2, tos_version=2)
    assert_fields(
        programme.read_developer(current["id"]), "Developer", tos_version_accepted=2
    )
    application = programme.draft_application(current, version)

    validate_error(
        api.submit_access_application(
            application["id"], f.submit_application_payload(), programme.headers_for(current)
        ),
        ApiError.VERSION_NOT_GRANTABLE,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication", state="DRAFT",
    )


def test_a_partner_justification_one_character_short_is_stored_but_not_submittable(api, programme):
    """The tier-scaled floor bites at submission and not at drafting, so a partner application whose
    justification is one character short of the partner minimum is created happily and only its
    submission is refused, leaving the draft in place to be fixed.

    PRD: "Submission also applies the tier-scaled justification floor: the length of
    `justification_text` must be at least **0 characters** for `SANDBOX`, **40 characters** for
    `STANDARD`, **120 characters** for `PARTNER` and **240 characters** for `PRIVILEGED`, with
    `ERR_JUSTIFICATION_INSUFFICIENT` (HTTP 422) when it falls short."

    Design: Corner/validations/justification_one_character_short_is_refused
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()

    draft = validate_success(
        api.create_access_application(
            f.access_application_payload(
                developer["id"], version["id"],
                requested_tier="PARTNER",
                justification_text=JUSTIFICATION_ONE_SHORT,
            ),
            programme.headers_for(developer),
        ),
        201,
    )
    assert_fields(draft, "AccessApplication", state="DRAFT")

    validate_error(
        api.submit_access_application(
            draft["id"], f.submit_application_payload(), programme.headers_for(developer)
        ),
        ApiError.JUSTIFICATION_INSUFFICIENT,
    )

    assert_fields(
        programme.read_application(draft["id"]), "AccessApplication",
        state="DRAFT", justification_text=JUSTIFICATION_ONE_SHORT,
    )
    _rows, meta = validate_paginated(
        api.list_access_applications(PLATFORM_ADMIN, {"state": "SUBMITTED"})
    )
    assert meta["total_count"] == 0, f"no application should have been submitted, meta was {meta}"


def test_a_replacement_justification_exactly_at_the_partner_minimum_is_accepted(api, programme):
    """The floor is inclusive, and the submission's optional justification replaces the stored one,
    so a revision of exactly the partner minimum carries the same draft through.

    PRD: "The developer submits the draft for review, optionally supplying a revised
    `justification_text` alongside."
    PRD: "Submission also applies the tier-scaled justification floor: the length of
    `justification_text` must be at least **0 characters** for `SANDBOX`, **40 characters** for
    `STANDARD`, **120 characters** for `PARTNER` and **240 characters** for `PRIVILEGED`, with
    `ERR_JUSTIFICATION_INSUFFICIENT` (HTTP 422) when it falls short."

    Design: Corner/validations/justification_exactly_at_the_minimum_is_accepted
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    draft = programme.draft_application(
        developer, version, requested_tier="PARTNER",
        justification_text=JUSTIFICATION_ONE_SHORT,
    )

    submitted = validate_success(
        api.submit_access_application(
            draft["id"],
            f.submit_application_payload(justification_text=JUSTIFICATION_AT_MINIMUM),
            programme.headers_for(developer),
        )
    )

    assert_fields(
        submitted, "AccessApplication",
        state="SUBMITTED", justification_text=JUSTIFICATION_AT_MINIMUM,
    )
    _rows, meta = validate_paginated(
        api.list_access_applications(PLATFORM_ADMIN, {"state": "SUBMITTED"})
    )
    assert meta["total_count"] == 1, f"expected one submitted application, meta was {meta}"


def test_resubmitting_a_decided_application_is_refused_for_its_state_not_its_justification(
    api, programme
):
    """A resubmission of an already approved application carrying a token justification breaks both
    the state rule and the length floor; the state rule sits in the earlier band, so the developer
    learns the request was impossible rather than being sent to write more prose.

    PRD: "The ladder runs in eight bands, and within each band in the listed order."
    PRD: "The application must be in `DRAFT` or `CHANGES_REQUESTED`, otherwise
    `ERR_APPLICATION_STATE_INVALID` (HTTP 409); the acting developer must own it; the developer's
    `standing` must be `GOOD_STANDING`; its `tos_version_accepted` must reach the target version's
    product `required_tos_version`; and the target version's `lifecycle_state` must be grantable for
    the `requested_tier`."

    Design: Corner/validations/application_state_outranks_justification_length
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.draft_application(developer, version)
    programme.submit_application(application, developer)
    programme.claim_application(application)
    approved = programme.decide_application(
        application, decision="APPROVE", approved_tier="PARTNER",
        granted_scopes=[CANONICAL_SCOPE],
    )
    assert_fields(approved, "AccessApplication", state="APPROVED")

    validate_error(
        api.submit_access_application(
            application["id"],
            f.submit_application_payload(justification_text="more please"),
            programme.headers_for(developer),
        ),
        ApiError.APPLICATION_STATE_INVALID,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication",
        state="APPROVED", justification_text=JUSTIFICATION_PARTNER,
    )


def _financial_draft(programme):
    """A financial product with a generally available version and one onboarded developer."""
    product = _payments_product(programme)
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    return product, version, developer


def _reviewed_financial_application(programme):
    """The same financial application, submitted and claimed so a decision can be attempted."""
    _product, version, developer = _financial_draft(programme)
    application = programme.draft_application(
        developer, version,
        requested_tier="PARTNER",
        requested_scopes=[CANONICAL_SCOPE, FINANCIAL_SCOPE],
    )
    programme.submit_application(application, developer)
    programme.claim_application(application)
    return developer, application


def test_a_financial_scope_requested_at_standard_tier_is_refused_at_draft_time(api, programme):
    """Sensitivity must match ambition at the moment the draft is written: a standard-tier request
    naming a financial scope is refused and no application row survives the attempt.

    PRD: "Sensitivity must match ambition: a scope whose catalogue `sensitivity` is `PERSONAL` may
    only be requested at `tier` `STANDARD` or above, and a scope whose `sensitivity` is `FINANCIAL`
    may only be requested at `tier` `PARTNER` or above, with `ERR_SCOPE_SENSITIVITY_NOT_PERMITTED`
    (HTTP 422) otherwise."

    Design: Corner/errors/scope_sensitivity_and_tier_grant_bounds
    """
    _product, version, developer = _financial_draft(programme)

    validate_error(
        api.create_access_application(
            f.access_application_payload(
                developer["id"], version["id"],
                requested_tier="STANDARD",
                requested_scopes=[CANONICAL_SCOPE, FINANCIAL_SCOPE],
                requested_monthly_calls=200000,
                justification_text="Our reconciliation widget needs the payments feed hourly.",
            ),
            programme.headers_for(developer),
        ),
        ApiError.SCOPE_SENSITIVITY_NOT_PERMITTED,
    )

    _rows, meta = validate_paginated(
        api.list_access_applications(PLATFORM_ADMIN, {"developer_id": developer["id"]})
    )
    assert meta["total_count"] == 0, f"the refused draft must not persist, meta was {meta}"


def test_the_same_financial_scope_is_admissible_once_partner_tier_is_requested(api, programme):
    """The refusal is driven by the pairing and not by the scope itself: the identical financial
    scope is accepted as soon as the request is pitched at partner tier.

    PRD: "Sensitivity must match ambition: a scope whose catalogue `sensitivity` is `PERSONAL` may
    only be requested at `tier` `STANDARD` or above, and a scope whose `sensitivity` is `FINANCIAL`
    may only be requested at `tier` `PARTNER` or above, with `ERR_SCOPE_SENSITIVITY_NOT_PERMITTED`
    (HTTP 422) otherwise."

    Design: Corner/errors/scope_sensitivity_and_tier_grant_bounds
    """
    _product, version, developer = _financial_draft(programme)

    draft = validate_success(
        api.create_access_application(
            f.access_application_payload(
                developer["id"], version["id"],
                requested_tier="PARTNER",
                requested_scopes=[CANONICAL_SCOPE, FINANCIAL_SCOPE],
            ),
            programme.headers_for(developer),
        ),
        201,
    )

    assert_fields(
        draft, "AccessApplication",
        state="DRAFT",
        requested_tier="PARTNER",
        requested_scopes=[CANONICAL_SCOPE, FINANCIAL_SCOPE],
    )


def test_an_approved_tier_outranking_the_requested_tier_is_refused(api, programme):
    """A decision may be generous in wording but not in rank: approving at privileged tier what was
    requested at partner tier is refused, and the application stays awaiting its decision.

    PRD: "The `approved_tier` may equal or sit below the `requested_tier` in rank — the ranks running
    `SANDBOX` 1, `STANDARD` 2, `PARTNER` 3, `PRIVILEGED` 4 — but may never outrank it; and
    `granted_scopes` must be a subset of both `requested_scopes` and the product's `scope_catalog`.
    Either breach is `ERR_TIER_ESCALATION_NOT_PERMITTED` (HTTP 422)."

    Design: Corner/errors/scope_sensitivity_and_tier_grant_bounds
    """
    _developer, application = _reviewed_financial_application(programme)

    validate_error(
        api.decide_access_application(
            application["id"],
            f.decide_application_payload(
                decision="APPROVE",
                approved_tier="PRIVILEGED",
                granted_scopes=[CANONICAL_SCOPE, FINANCIAL_SCOPE],
            ),
            PLATFORM_ADMIN,
        ),
        ApiError.TIER_ESCALATION_NOT_PERMITTED,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication",
        state="UNDER_REVIEW", approved_tier=None,
    )


def test_granting_a_catalogue_scope_that_was_never_requested_is_refused(api, programme):
    """The second limb of the same bound is the scope set: a personal scope that lives in the
    product's catalogue but was never asked for cannot be handed over by the decision.

    PRD: "The `approved_tier` may equal or sit below the `requested_tier` in rank — the ranks running
    `SANDBOX` 1, `STANDARD` 2, `PARTNER` 3, `PRIVILEGED` 4 — but may never outrank it; and
    `granted_scopes` must be a subset of both `requested_scopes` and the product's `scope_catalog`.
    Either breach is `ERR_TIER_ESCALATION_NOT_PERMITTED` (HTTP 422)."

    Design: Corner/errors/scope_sensitivity_and_tier_grant_bounds
    """
    _developer, application = _reviewed_financial_application(programme)

    validate_error(
        api.decide_access_application(
            application["id"],
            f.decide_application_payload(
                decision="APPROVE",
                approved_tier="PARTNER",
                granted_scopes=[CANONICAL_SCOPE, PERSONAL_SCOPE],
            ),
            PLATFORM_ADMIN,
        ),
        ApiError.TIER_ESCALATION_NOT_PERMITTED,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication",
        state="UNDER_REVIEW", granted_scopes=None,
    )


def test_a_downgraded_tier_that_keeps_the_financial_scope_is_refused_for_sensitivity(
    api, programme
):
    """The sensitivity rule is enforced a second time against the approved tier, so quietly
    downgrading the grant to standard while keeping the financial scope is refused as a sensitivity
    breach rather than as an escalation.

    PRD: "The granted scopes' sensitivities must also be permitted at the `approved_tier` under the
    same `PERSONAL`-needs-`STANDARD`, `FINANCIAL`-needs-`PARTNER` rule, which at decision time
    surfaces as `ERR_SCOPE_SENSITIVITY_NOT_PERMITTED`."

    Design: Corner/errors/scope_sensitivity_and_tier_grant_bounds
    """
    _developer, application = _reviewed_financial_application(programme)

    validate_error(
        api.decide_access_application(
            application["id"],
            f.decide_application_payload(
                decision="APPROVE",
                approved_tier="STANDARD",
                granted_scopes=[CANONICAL_SCOPE, FINANCIAL_SCOPE],
            ),
            PLATFORM_ADMIN,
        ),
        ApiError.SCOPE_SENSITIVITY_NOT_PERMITTED,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication",
        state="UNDER_REVIEW", approved_tier=None,
    )


def test_the_decision_that_respects_both_bounds_approves_the_financial_grant(api, programme):
    """None of the refused decisions moved the application, and the decision that respects both the
    rank bound and the sensitivity rule approves it at the requested tier with the financial ceiling.

    PRD: "On approval the application moves `UNDER_REVIEW → APPROVED`, records `approver_user_id`
    from `X-User-ID`, stores `approved_tier` and `granted_scopes`, sets `decided_at` from the logical
    clock, and computes `data_access_limit` — the highest data sensitivity the approved tier may
    touch, which is `PUBLIC` at `SANDBOX`, `PERSONAL` at `STANDARD`, and `FINANCIAL` at both
    `PARTNER` and `PRIVILEGED`."

    Design: Corner/errors/scope_sensitivity_and_tier_grant_bounds
    """
    _developer, application = _reviewed_financial_application(programme)

    decided = validate_success(
        api.decide_access_application(
            application["id"],
            f.decide_application_payload(
                decision="APPROVE",
                approved_tier="PARTNER",
                granted_scopes=[CANONICAL_SCOPE, FINANCIAL_SCOPE],
                decision_reason="Regulated settlement use case verified.",
            ),
            PLATFORM_ADMIN,
        )
    )

    assert_fields(
        decided, "AccessApplication",
        state="APPROVED",
        approved_tier="PARTNER",
        granted_scopes=[CANONICAL_SCOPE, FINANCIAL_SCOPE],
        data_access_limit="FINANCIAL",
    )
    assert_instant_equals(decided["decided_at"], "2026-08-01T00:00:00Z", "decided_at")


def test_a_certification_expiring_exactly_at_the_clock_is_refused(api, programme):
    """The expiry comparison is strict, so a certification whose lapse instant is exactly the current
    clock reading is refused, and the developer keeps neither the level nor the expiry.

    PRD: "Whenever a certification level is recorded, `certification_expires_at` must be **strictly
    after** the current logical clock — recording a certification that has already lapsed is refused
    with `ERR_CERTIFICATION_EXPIRED` (HTTP 422)."

    Design: Corner/errors/developer_gate_errors_docs_certification_and_revocation
    """
    programme.create_product()
    developer = programme.onboarded_developer()
    assert_fields(developer, "Developer", certification_level="NONE", trust_score=56)

    validate_error(
        api.record_ecosystem_participation(
            developer["id"],
            f.ecosystem_participation_payload(
                certification_level="ASSOCIATE",
                certification_expires_at="2026-08-01T00:00:00Z",
            ),
            DEV_REL_MANAGER,
        ),
        ApiError.CERTIFICATION_EXPIRED,
    )

    assert_fields(
        programme.read_developer(developer["id"]), "Developer",
        certification_level="NONE", certification_expires_at=None, trust_score=56,
    )
