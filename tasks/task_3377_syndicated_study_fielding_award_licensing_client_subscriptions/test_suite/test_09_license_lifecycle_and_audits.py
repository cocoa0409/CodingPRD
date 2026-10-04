"""License lifecycle: audit-escalation suspension cascade, reinstatement gates,
term/fee conservation, award-state gating, and half-open occupation (PRD §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    activate_license,
    audit_goto,
    file_audit,
    get_license,
    license_goto,
    publish_study,
    quote_license,
    register_client,
    set_clock,
    setup_awards_set_study,
    setup_published_study,
    validate_error,
    api_client,
    TEST_USERS,
)

LICMGR = TEST_USERS["licensing_manager_headers"]

_ONE_BRAND = [{"name": "BrandA", "responses": [{"token": "rt-1", "qual": 9, "feat": 8}]}]


def _active_license_ctx(activate_at="2026-10-20T00:00:00Z", tier="DIGITAL",
                        term_months=12, markets_count=1):
    """Published study + award + client; license activated at the given instant."""
    ctx = setup_published_study(min_sample=1, brands=_ONE_BRAND)
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    lic = quote_license(ctx["award"]["id"], client["id"], tier=tier,
                        term_months=term_months, markets_count=markets_count)
    set_clock(activate_at)
    activate_license(lic["id"])
    ctx["client"] = client
    ctx["license"] = get_license(lic["id"])
    return ctx


def test_minor_escalations_suspend_at_threshold_two(api):
    """PRD §3.7: "Escalating an audit — moving it from `OPEN` to `ESCALATED` —
    fires the suspension cascade onto its license: a `MAJOR` escalation suspends
    the license immediately if it is `ACTIVE`, and a `MINOR` escalation suspends
    an `ACTIVE` license only when it is at least the second `MINOR` audit
    currently in `ESCALATED` status on that license (the escalating audit itself
    counts toward that threshold of 2)."

    Design: Difficulty/non_linear_state_machine/license_suspend_reinstate_cycle
    """
    ctx = _active_license_ctx()
    lic_id = ctx["license"]["id"]
    au1 = file_audit(lic_id, severity="MINOR", note="missing disclaimer line")
    au2 = file_audit(lic_id, severity="MINOR", note="unapproved logo crop")

    audit_goto(au1["id"], "ESCALATED")
    assert get_license(lic_id)["status"] == "ACTIVE", "first MINOR escalation stays below threshold 2"

    audit_goto(au2["id"], "ESCALATED")
    after = get_license(lic_id)
    assert after["status"] == "SUSPENDED", "second concurrently-ESCALATED MINOR suspends"
    assert after["suspension_count"] == 1


def test_major_escalation_suspends_immediately_after_reinstate(api):
    """PRD §3.7: "a `MAJOR` escalation suspends the license immediately if it is
    `ACTIVE`"
    PRD §3.7: "That gate is the one precondition on reinstating a suspended
    license: driving a license from `SUSPENDED` back to `ACTIVE` requires zero
    usage audits of the license in `OPEN` or `ESCALATED` status, failing with
    `ERR_AUDITS_UNRESOLVED` otherwise. Reinstatement restores activity but never
    rewrites the commercial terms: `expires_at` and `fee_final_cents` must not
    change, because suspension never extends the term."

    Design: Difficulty/non_linear_state_machine/license_suspend_reinstate_cycle
    """
    ctx = _active_license_ctx()
    lic_id = ctx["license"]["id"]
    au1 = file_audit(lic_id, severity="MINOR", note="missing disclaimer line")
    au2 = file_audit(lic_id, severity="MINOR", note="unapproved logo crop")
    audit_goto(au1["id"], "ESCALATED")
    audit_goto(au2["id"], "ESCALATED")
    assert get_license(lic_id)["status"] == "SUSPENDED"

    audit_goto(au1["id"], "RESOLVED")
    audit_goto(au2["id"], "RESOLVED")
    reinstated = license_goto(lic_id, "ACTIVE")
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["expires_at"] == ctx["license"]["expires_at"], "suspension never extends the term"
    assert reinstated["fee_final_cents"] == ctx["license"]["fee_final_cents"]

    au3 = file_audit(lic_id, severity="MAJOR", note="claims rank in unapproved category")
    audit_goto(au3["id"], "ESCALATED")
    after = get_license(lic_id)
    assert after["status"] == "SUSPENDED", "a single MAJOR escalation suspends immediately"
    assert after["suspension_count"] == 2


def test_suspend_reinstate_conserves_fee_and_term(api):
    """PRD §3.7: "Reinstatement restores activity but never rewrites the
    commercial terms: `expires_at` and `fee_final_cents` must not change, because
    suspension never extends the term."
    PRD §3.6: "Activation also stamps `activated_at` with the logical clock and
    sets `expires_at` to `activated_at` plus `term_months` calendar months,
    clamping the day of month to the target month's end when necessary."

    Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_term_and_fee
    """
    ctx = _active_license_ctx(activate_at="2026-10-20T00:00:00Z")
    before = ctx["license"]
    assert before["fee_final_cents"] == 250000
    assert before["expires_at"].startswith("2027-10-20T00:00:00")

    license_goto(before["id"], "SUSPENDED")
    reinstated = license_goto(before["id"], "ACTIVE")
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["fee_final_cents"] == before["fee_final_cents"], "no repricing on reinstate"
    assert reinstated["activated_at"] == before["activated_at"], "activation instant is conserved"
    assert reinstated["expires_at"] == before["expires_at"], "term is never extended"


def test_suspension_count_is_the_only_quantity_that_moves(api):
    """PRD §3.7: "Suspension — whether from the cascade or a manual
    `LicensingManager` act — moves the license `ACTIVE` to `SUSPENDED` and
    increments its `suspension_count` by 1."
    PRD §3.7: "Reinstatement restores activity but never rewrites the commercial
    terms: `expires_at` and `fee_final_cents` must not change, because suspension
    never extends the term."

    Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_term_and_fee
    """
    ctx = _active_license_ctx(activate_at="2026-10-20T00:00:00Z")
    before = ctx["license"]
    assert before["suspension_count"] == 0

    license_goto(before["id"], "SUSPENDED")
    after = license_goto(before["id"], "ACTIVE")
    assert after["suspension_count"] == 1, "the suspend+reinstate pair nets exactly one suspension"
    for field in ("fee_quote_cents", "fee_final_cents", "activated_at", "expires_at",
                  "tier", "term_months", "markets_count", "award_id", "client_id"):
        assert after[field] == before[field], f"{field} must be conserved across the cycle"


def test_activation_rejected_while_award_embargoed(api, licensing_manager_headers):
    """PRD §3.6: "The award must be `PUBLISHED` — activating against a
    still-embargoed award fails with `ERR_AWARD_NOT_PUBLISHED`."
    PRD §3.6: "Quoting is deliberately allowed while the award is still
    `EMBARGOED` — commercial paperwork can move ahead of the press release."

    Design: Difficulty/cross_entity_state_dependency/license_activation_gated_by_award_state
    """
    ctx = setup_awards_set_study(min_sample=1, brands=_ONE_BRAND)
    award = ctx["awards"][0]
    assert award["status"] == "EMBARGOED"
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])

    lic = quote_license(award["id"], client["id"], tier="DIGITAL", term_months=12, markets_count=1)
    assert lic["status"] == "QUOTED", "quoting while EMBARGOED is allowed"

    resp = api.license_state(lic["id"], {"to_status": "ACTIVE"}, licensing_manager_headers)
    validate_error(resp, ApiErrorId.ERR_AWARD_NOT_PUBLISHED)
    after = get_license(lic["id"])
    assert after["status"] == "QUOTED" and after["fee_final_cents"] is None


def test_activation_succeeds_after_publish_cascade(api):
    """PRD §3.6: "The award must be `PUBLISHED` — activating against a
    still-embargoed award fails with `ERR_AWARD_NOT_PUBLISHED`."
    PRD §3.5: "The publish cascade flips every `EMBARGOED` award of the study to
    `PUBLISHED`, stamps each award's `published_at` with the clock, and stamps the
    study's own `published_at` the same way."

    Design: Difficulty/cross_entity_state_dependency/license_activation_gated_by_award_state
    """
    ctx = setup_awards_set_study(min_sample=1, brands=_ONE_BRAND)
    award = ctx["awards"][0]
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    lic = quote_license(award["id"], client["id"], tier="DIGITAL", term_months=12, markets_count=1)

    publish_study(ctx["study"]["id"], at="2026-10-15T00:00:00Z")
    activated = activate_license(lic["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"].startswith("2026-10-15T00:00:00"), (
        f"activated_at must be stamped with the logical clock, got {activated['activated_at']}"
    )


def test_second_activation_while_first_active_conflicts(api, licensing_manager_headers):
    """PRD §3.6: "And no other license on the same award may currently be
    `ACTIVE`: occupation is a half-open interval from `activated_at` up to but not
    including `expires_at`, so a predecessor license whose `expires_at` equals the
    new activation instant does *not* conflict, while any genuinely overlapping
    active license fails the activation with `ERR_LICENSE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/award_license_half_open_interval
    """
    ctx = setup_published_study(min_sample=1, brands=_ONE_BRAND)
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    l1 = quote_license(ctx["award"]["id"], client["id"], tier="DIGITAL", term_months=12, markets_count=1)
    l2 = quote_license(ctx["award"]["id"], client["id"], tier="NATIONAL", term_months=12, markets_count=2)

    set_clock("2026-10-20T00:00:00Z")
    activate_license(l1["id"])  # occupies [2026-10-20, 2027-10-20)

    set_clock("2026-11-01T00:00:00Z")
    resp = api.license_state(l2["id"], {"to_status": "ACTIVE"}, licensing_manager_headers)
    validate_error(resp, ApiErrorId.ERR_LICENSE_CONFLICT)
    assert get_license(l2["id"])["status"] == "QUOTED"


def test_activation_at_exact_expiry_of_predecessor_succeeds(api):
    """PRD §3.6: "a predecessor license whose `expires_at` equals the new
    activation instant does *not* conflict"
    PRD §3.7: "Expiry moves an `ACTIVE` license to `EXPIRED` and is permitted only
    when the logical clock has reached `expires_at` — equality suffices because
    the occupation interval is half-open — and a strictly earlier clock fails with
    `ERR_LICENSE_NOT_EXPIRED`."

    Design: Difficulty/resource_temporal_overlap/award_license_half_open_interval
    """
    ctx = setup_published_study(min_sample=1, brands=_ONE_BRAND)
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    l1 = quote_license(ctx["award"]["id"], client["id"], tier="DIGITAL", term_months=12, markets_count=1)
    l2 = quote_license(ctx["award"]["id"], client["id"], tier="NATIONAL", term_months=12, markets_count=2)

    set_clock("2026-10-20T00:00:00Z")
    activate_license(l1["id"])

    set_clock("2027-10-20T00:00:00Z")  # exactly L1.expires_at
    expired = license_goto(l1["id"], "EXPIRED")
    assert expired["status"] == "EXPIRED", "equality suffices for the half-open end"

    activated = license_goto(l2["id"], "ACTIVE")
    assert activated["status"] == "ACTIVE", "adjacency at the half-open boundary is no conflict"
    assert activated["activated_at"].startswith("2027-10-20T00:00:00")
    assert activated["expires_at"].startswith("2028-10-20T00:00:00")


def test_reinstate_blocked_by_open_audits(api, licensing_manager_headers):
    """PRD §3.7: "That gate is the one precondition on reinstating a suspended
    license: driving a license from `SUSPENDED` back to `ACTIVE` requires zero
    usage audits of the license in `OPEN` or `ESCALATED` status, failing with
    `ERR_AUDITS_UNRESOLVED` otherwise."

    Design: Corner/errors/reinstate_blocked_by_open_audits
    """
    ctx = setup_published_study(min_sample=1, brands=_ONE_BRAND)
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    lic = quote_license(ctx["award"]["id"], client["id"], tier="DIGITAL", term_months=12, markets_count=1)
    activate_license(lic["id"])
    file_audit(lic["id"], severity="MINOR", note="typo in award name")  # stays OPEN
    license_goto(lic["id"], "SUSPENDED")

    resp = api.license_state(lic["id"], {"to_status": "ACTIVE"}, licensing_manager_headers)
    validate_error(resp, ApiErrorId.ERR_AUDITS_UNRESOLVED)
    assert get_license(lic["id"])["status"] == "SUSPENDED"


def test_license_expire_before_expiry_returns_409(api, licensing_manager_headers):
    """PRD §3.7: "Expiry moves an `ACTIVE` license to `EXPIRED` and is permitted
    only when the logical clock has reached `expires_at` — equality suffices
    because the occupation interval is half-open — and a strictly earlier clock
    fails with `ERR_LICENSE_NOT_EXPIRED`."

    Design: Corner/errors/license_expire_before_expiry_returns_409
    """
    ctx = _active_license_ctx(activate_at="2026-10-20T00:00:00Z")
    lic_id = ctx["license"]["id"]
    set_clock("2027-01-01T00:00:00Z")  # strictly before expires_at 2027-10-20
    resp = api.license_state(lic_id, {"to_status": "EXPIRED"}, licensing_manager_headers)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_EXPIRED)
    after = get_license(lic_id)
    assert after["status"] == "ACTIVE"
    assert after["expires_at"].startswith("2027-10-20T00:00:00")
