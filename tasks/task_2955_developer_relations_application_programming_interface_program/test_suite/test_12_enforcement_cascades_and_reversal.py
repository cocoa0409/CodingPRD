"""What an upheld violation reaches across the programme, and what a dismissal puts back.

The concern here is the enforcement fan-out and its partial reversal: upholding a case worth
enough points to restrict a developer suspends its entitlement and returns the reservations,
revokes its sandbox lease and delists its directory entry, while dismissing the appeal that
follows restores the ledger, the standing and the entitlement — but deliberately not
everything the cascade touched.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import assert_fields, assert_instant_equals, assert_nulls
from test_helpers.test_users import PLATFORM_ADMIN

_RETENTION_SUMMARY = "Catalog records retained well past the disclosed fourteen-day purge window."
_UPHELD_NOTE = "Retention breach confirmed against the disclosed policy."
_DISMISSAL_NOTE = "Legal-hold exemption verified; the finding is withdrawn."
_APPEAL_REASON = (
    "The retained records were held in an encrypted legal-hold vault mandated by our "
    "regulator, not in the serving path."
)


# --------------------------------------------------------------------------- builders
def _listed_partner_under_investigation(programme) -> Dict[str, Any]:
    """A fully invested developer with a 60-point case already under investigation.

    The developer is PROFESSIONAL-certified, has validated a sandbox lease that still runs to
    2026-08-15, holds an ACTIVE PARTNER entitlement of 3000 sustained rpm and 500000 monthly
    calls against the 20000 / 50000000 pools, is LISTED in the public directory, and is the
    target of a DATA_RETENTION HIGH case investigated by the trust officer.
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"], semver="1.0.0", breaking_change=False)
    developer = programme.register_developer()
    programme.acknowledge(developer)
    programme.certify(developer)
    lease = programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=14)
    programme.validate_lease(lease, developer)
    application = programme.approved_application(developer, version)
    assignment = programme.provision_entitlement(application, product["id"])
    assignment = programme.activate_entitlement(assignment)
    programme.submit_directory(developer)
    programme.review_directory(developer, decision="APPROVE", review_note="Listing copy approved.")
    case = programme.open_case(
        developer,
        category="DATA_RETENTION",
        severity="HIGH",
        summary=_RETENTION_SUMMARY,
        quota_assignment_id=assignment["id"],
    )
    programme.investigate_case(case)
    return {
        "product": product,
        "version": version,
        "developer": developer,
        "lease": lease,
        "assignment": assignment,
        "case": case,
    }


def _appealed_case_after_restriction(programme) -> Dict[str, Any]:
    """The same developer once the case has been upheld and the developer has appealed.

    Standing is RESTRICTED, the entitlement is SUSPENDED for STANDING_RESTRICTION, the lease
    is REVOKED, the directory entry is DELISTED, and the appeal was filed on 2026-08-02,
    inside the 14-day window that closes on 2026-08-15.
    """
    built = _listed_partner_under_investigation(programme)
    programme.adjudicate_case(built["case"], outcome="UPHELD", decision_note=_UPHELD_NOTE)
    programme.set_clock("2026-08-02T00:00:00Z")
    programme.appeal_case(built["case"], built["developer"], appeal_reason=_APPEAL_REASON)
    return built


def _uphold(api, case) -> Dict[str, Any]:
    return validate_success(
        api.adjudicate_violation_case(
            case["id"], f.adjudicate_payload(outcome="UPHELD", decision_note=_UPHELD_NOTE),
            PLATFORM_ADMIN,
        ),
        expected_status=200,
    )


def _dismiss(api, case) -> Dict[str, Any]:
    return validate_success(
        api.adjudicate_violation_case(
            case["id"], f.adjudicate_payload(outcome="DISMISSED", decision_note=_DISMISSAL_NOTE),
            PLATFORM_ADMIN,
        ),
        expected_status=200,
    )


# ----------------------------------------- what an upheld sixty-point case reaches
def test_upholding_a_sixty_point_case_restricts_the_developer_and_books_the_points(
    api, programme, clock_at_default
):
    """A HIGH-severity data-retention finding is worth 60 points, which lands on the
    developer's ledger, records the same figure on the case and pushes standing to RESTRICTED.

    PRD: "Upholding a case from `INVESTIGATING` moves it `INVESTIGATING → UPHELD`, adds its `penalty_points` to the developer's `violation_points` ledger, records the same figure as the case's own `points_applied` so the contribution can later be reversed exactly, and sets `appeal_deadline` to the logical clock advanced by the **14-day** appeal window."

    PRD: "If that addition brings `violation_points` to **50 or more** — the comparison is inclusive — the developer's `standing` moves `UNDER_REVIEW → RESTRICTED` and a four-part cascade fires."

    Design: Difficulty/transitive_cascade/upheld_violation_cascades_restriction_suspension_pool_and_delisting
    """
    built = _listed_partner_under_investigation(programme)

    upheld = _uphold(api, built["case"])

    assert_fields(
        upheld,
        "ViolationCase",
        state="UPHELD",
        outcome="UPHELD",
        penalty_points=60,
        points_applied=60,
    )
    assert_instant_equals(upheld["appeal_deadline"], "2026-08-15T00:00:00Z", "appeal_deadline")
    assert_fields(
        programme.read_developer(built["developer"]["id"]),
        "Developer",
        violation_points=60,
        standing="RESTRICTED",
    )


def test_the_restriction_cascade_suspends_the_entitlement_and_returns_both_reservations(
    api, programme, clock_at_default
):
    """Restriction suspends the developer's ACTIVE entitlement for STANDING_RESTRICTION and
    hands its 3000 sustained rpm and 500000 monthly calls back to the product's pools.

    PRD: "Every entitlement of the developer in `entitlement_state` `ACTIVE` becomes `SUSPENDED` with `suspension_reason` `STANDING_RESTRICTION`, and its `sustained_rpm` and `monthly_call_allowance` are returned to the product's allocated counters."

    Design: Difficulty/transitive_cascade/upheld_violation_cascades_restriction_suspension_pool_and_delisting
    """
    built = _listed_partner_under_investigation(programme)
    assert_fields(
        programme.read_product(built["product"]["id"]),
        "ApiProduct",
        allocated_sustained_rpm=3000,
        available_sustained_rpm=17000,
        allocated_monthly_calls=500000,
        available_monthly_calls=49500000,
    )

    _uphold(api, built["case"])

    suspended = programme.read_entitlement(built["assignment"]["id"])
    assert_fields(
        suspended,
        "QuotaAssignment",
        entitlement_state="SUSPENDED",
        suspension_reason="STANDING_RESTRICTION",
        sustained_rpm=3000,
        monthly_call_allowance=500000,
    )
    assert_instant_equals(suspended["suspended_at"], "2026-08-01T00:00:00Z", "suspended_at")
    assert_fields(
        programme.read_product(built["product"]["id"]),
        "ApiProduct",
        allocated_sustained_rpm=0,
        available_sustained_rpm=20000,
        allocated_monthly_calls=0,
        available_monthly_calls=50000000,
    )


def test_the_restriction_cascade_revokes_the_still_running_sandbox_lease(
    api, programme, clock_at_default
):
    """The developer's ACTIVE sandbox lease is taken away by the same adjudication, closed as
    a standing cascade rather than as a developer release or a checkpoint expiry.

    PRD: "And every `SandboxLease` of the developer in `state` `ACTIVE` becomes `REVOKED` with `closed_reason` `STANDING_CASCADE`."

    Design: Difficulty/transitive_cascade/upheld_violation_cascades_restriction_suspension_pool_and_delisting
    """
    built = _listed_partner_under_investigation(programme)
    assert_fields(programme.read_lease(built["lease"]["id"]), "SandboxLease", state="ACTIVE")

    _uphold(api, built["case"])

    revoked = programme.read_lease(built["lease"]["id"])
    assert_fields(revoked, "SandboxLease", state="REVOKED", closed_reason="STANDING_CASCADE")
    assert revoked["released_at"] is not None, "a revoked lease must carry released_at"


def test_the_restriction_cascade_delists_the_public_directory_entry(
    api, programme, clock_at_default
):
    """A developer that was LISTED in the public ecosystem directory is delisted by the
    restriction, which is the only way a listing ever comes down.

    PRD: "A `directory_state` of `LISTED` becomes `DELISTED`."

    Design: Difficulty/transitive_cascade/upheld_violation_cascades_restriction_suspension_pool_and_delisting
    """
    built = _listed_partner_under_investigation(programme)
    assert_fields(
        programme.read_developer(built["developer"]["id"]), "Developer", directory_state="LISTED"
    )

    _uphold(api, built["case"])

    assert_fields(
        programme.read_developer(built["developer"]["id"]), "Developer", directory_state="DELISTED"
    )


def test_the_restriction_cascade_leaves_onboarding_progress_alone(
    api, programme, clock_at_default
):
    """Standing and onboarding are independent dimensions, so the developer that reached
    PRODUCTION_ACTIVE stays there even as restriction strips everything else away.

    PRD: "A transition on one dimension never implies a transition on another unless an explicit cascade in §3 says so; in particular, restriction does not roll back onboarding progress."

    Design: Difficulty/transitive_cascade/upheld_violation_cascades_restriction_suspension_pool_and_delisting
    """
    built = _listed_partner_under_investigation(programme)
    assert_fields(
        programme.read_developer(built["developer"]["id"]),
        "Developer",
        onboarding_state="PRODUCTION_ACTIVE",
    )

    _uphold(api, built["case"])

    assert_fields(
        programme.read_developer(built["developer"]["id"]),
        "Developer",
        onboarding_state="PRODUCTION_ACTIVE",
        standing="RESTRICTED",
    )


# ------------------------------------------- what a dismissed appeal puts back
def test_dismissing_an_appealed_case_zeroes_the_applied_points_and_the_ledger(
    api, programme, clock_at_default
):
    """The second adjudication of an appealed case withdraws the finding: the 60 points come
    back off the developer's ledger, the case keeps no reversible balance, and standing
    recovers from RESTRICTED to GOOD_STANDING.

    PRD: "Dismissing it moves `APPEALED → DISMISSED` and compensates in full: `points_applied` is subtracted from the developer's `violation_points` and zeroed on the case."

    PRD: "If that leaves `violation_points` below 50 and standing was `RESTRICTED`, the developer's `standing` moves `RESTRICTED → GOOD_STANDING`, and every entitlement of that developer sitting at `SUSPENDED` **whose `suspension_reason` is `STANDING_RESTRICTION`** is restored to `ACTIVE`, re-deducting its `sustained_rpm` and `monthly_call_allowance` from the product's counters."

    Design: Difficulty/compensating_invariant/appeal_dismissal_restores_violation_points_ledger
    """
    built = _appealed_case_after_restriction(programme)
    assert_fields(
        programme.read_case(built["case"]["id"]),
        "ViolationCase",
        state="APPEALED",
        points_applied=60,
        appeal_count=1,
    )
    assert_fields(
        programme.read_developer(built["developer"]["id"]),
        "Developer",
        violation_points=60,
        standing="RESTRICTED",
    )

    dismissed = _dismiss(api, built["case"])

    assert_fields(
        dismissed,
        "ViolationCase",
        state="DISMISSED",
        outcome="DISMISSED",
        penalty_points=60,
        points_applied=0,
    )
    assert_fields(
        programme.read_developer(built["developer"]["id"]),
        "Developer",
        violation_points=0,
        standing="GOOD_STANDING",
    )


def test_dismissing_an_appealed_case_restores_the_entitlement_and_re_deducts_its_reservations(
    api, programme, clock_at_default
):
    """The entitlement the restriction suspended comes back to ACTIVE with its suspension
    marks cleared, and its 3000 sustained rpm and 500000 monthly calls are taken out of the
    product's pools again.

    PRD: "If that leaves `violation_points` below 50 and standing was `RESTRICTED`, the developer's `standing` moves `RESTRICTED → GOOD_STANDING`, and every entitlement of that developer sitting at `SUSPENDED` **whose `suspension_reason` is `STANDING_RESTRICTION`** is restored to `ACTIVE`, re-deducting its `sustained_rpm` and `monthly_call_allowance` from the product's counters."

    PRD: "On success `suspended_at` and `suspension_reason` are cleared and both reservations are re-deducted from the product's counters."

    PRD: "Reinstatement can also arrive as a cascade, when an appeal dismissal restores a developer's standing."

    Design: Difficulty/compensating_invariant/appeal_dismissal_restores_violation_points_ledger
    """
    built = _appealed_case_after_restriction(programme)
    assert_fields(
        programme.read_entitlement(built["assignment"]["id"]),
        "QuotaAssignment",
        entitlement_state="SUSPENDED",
        suspension_reason="STANDING_RESTRICTION",
    )
    assert_fields(
        programme.read_product(built["product"]["id"]),
        "ApiProduct",
        allocated_sustained_rpm=0,
        available_sustained_rpm=20000,
        allocated_monthly_calls=0,
        available_monthly_calls=50000000,
    )

    _dismiss(api, built["case"])

    restored = programme.read_entitlement(built["assignment"]["id"])
    assert_fields(
        restored,
        "QuotaAssignment",
        entitlement_state="ACTIVE",
        sustained_rpm=3000,
        monthly_call_allowance=500000,
    )
    assert_nulls(restored, ["suspended_at", "suspension_reason"], "QuotaAssignment")
    assert_fields(
        programme.read_product(built["product"]["id"]),
        "ApiProduct",
        allocated_sustained_rpm=3000,
        available_sustained_rpm=17000,
        allocated_monthly_calls=500000,
        available_monthly_calls=49500000,
    )


def test_the_dismissal_does_not_give_back_the_sandbox_lease_the_cascade_revoked(
    api, programme, clock_at_default
):
    """Compensation stops at the sandbox: the lease the restriction revoked stays revoked as a
    standing cascade even once the developer is back in good standing.

    PRD: "Sandbox leases revoked by the cascade are explicitly **not** restored."

    PRD: "Not everything is reversible, however, and where it is not, this document says so explicitly: sandbox leases revoked by a standing cascade are **not** restored when standing recovers."

    Design: Difficulty/compensating_invariant/appeal_dismissal_restores_violation_points_ledger
    """
    built = _appealed_case_after_restriction(programme)
    assert_fields(
        programme.read_lease(built["lease"]["id"]),
        "SandboxLease",
        state="REVOKED",
        closed_reason="STANDING_CASCADE",
    )

    _dismiss(api, built["case"])

    assert_fields(
        programme.read_developer(built["developer"]["id"]), "Developer", standing="GOOD_STANDING"
    )
    assert_fields(
        programme.read_lease(built["lease"]["id"]),
        "SandboxLease",
        state="REVOKED",
        closed_reason="STANDING_CASCADE",
    )


def test_the_dismissal_leaves_the_delisted_directory_entry_delisted(
    api, programme, clock_at_default
):
    """A recovered developer is not silently relisted: the delisted entry only re-enters
    review when the developer resubmits its blurb itself.

    PRD: "Only a standing cascade can take a listing down: `LISTED → DELISTED` fires when standing moves to `RESTRICTED` or `REVOKED`, and there is no operator action that delists directly."

    PRD: "On success `directory_state` moves `NOT_LISTED → PENDING_REVIEW` on a first submission, or `DELISTED → PENDING_REVIEW` on a resubmission after standing has recovered; both transitions record the supplied `directory_summary`, and the two are governed by exactly the same prerequisites."

    Design: Difficulty/compensating_invariant/appeal_dismissal_restores_violation_points_ledger
    """
    built = _appealed_case_after_restriction(programme)
    assert_fields(
        programme.read_developer(built["developer"]["id"]), "Developer", directory_state="DELISTED"
    )

    _dismiss(api, built["case"])

    recovered = programme.read_developer(built["developer"]["id"])
    assert_fields(recovered, "Developer", standing="GOOD_STANDING", directory_state="DELISTED")

    programme.submit_directory(built["developer"])
    assert_fields(
        programme.read_developer(built["developer"]["id"]),
        "Developer",
        directory_state="PENDING_REVIEW",
    )
