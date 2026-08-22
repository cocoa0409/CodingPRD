"""Locating the money: skip traces, asset findings and the two recoverability variants."""

from test_helpers import (
    ApiErrorId,
    create_enforcement_action_payload,
    create_open_finding,
    create_verified_finding,
    draft_enforcement_action,
    locate_debtor,
    make_asset_investigator_headers,
    make_case_manager_headers,
    make_enforcement_officer_headers,
    read_debtor,
    read_finding,
    read_judgment,
    record_county_filing,
    setup_judgment,
    setup_served_examination,
    skip_trace_payload,
    validate_error,
    validate_success,
)

CM = make_case_manager_headers()
INV = make_asset_investigator_headers("inv-1")
EO = make_enforcement_officer_headers("eo-1")


def _located_debtor_with_two_findings():
    """A LOCATED CA debtor whose judgment carries one VERIFIED and one OPEN
    finding, each worth 2,000,000 cents, on a lien-perfected judgment."""
    ctx = setup_judgment(
        court_case_number="CV-2026-0002",
        debtor_overrides={"weekly_disposable_earnings_cents": 100_000},
    )
    ctx["debtor"] = locate_debtor(ctx["debtor"]["id"], "inv-1", hits_count=3)
    ctx["filing"] = record_county_filing(ctx["judgment"]["id"], fee_cents=0)
    ctx["bank_finding"] = create_verified_finding(
        ctx["judgment"]["id"], "inv-1", estimated_value_cents=2_000_000
    )
    ctx["property_finding"] = create_open_finding(
        ctx["judgment"]["id"], "inv-1",
        asset_type="REAL_PROPERTY", institution_name="LA County Recorder",
        identifier_last4="0042", estimated_value_cents=2_000_000,
    )
    return ctx


def test_preliminary_score_discounts_the_open_finding_to_sixty_percent(api):
    """PRD §3.3: "Under the **preliminary** variant, which is the one written to
    `recoverability_score` on every investigative event, the weighted asset total
    is the sum, over findings whose status is `OPEN` or `VERIFIED`, of each
    finding's `estimated_value_cents` taken at full weight when the finding is
    `VERIFIED` and at sixty percent when it is merely `OPEN`."
    PRD §3.3: "The asset component is sixty multiplied by that weighted total,
    divided by a target asset value of fifty thousand dollars — five million cents
    — with the result rounded down to a whole number and then capped at 60."
    PRD §3.3: "The locate component is 20 when the debtor's `locate_status` is
    `LOCATED` and 0 otherwise."
    PRD §3.3: "The cooperation component starts at 20 and loses 10 points for each
    recorded no-show, counting at most two no-shows, so it is 20 at zero no-shows,
    10 at one, and 0 at two or more."

    Design: Difficulty/dual_variant_calc/recoverability_preliminary_vs_certified_on_debtor_risk
    """
    ctx = _located_debtor_with_two_findings()

    debtor = validate_success(api.get_debtor(ctx["debtor"]["id"], INV))
    assert debtor["recoverability_score"] == 78, (
        "2,000,000 verified at full weight plus 2,000,000 open at 60% gives an "
        "asset component of 38, plus 20 locate and 20 cooperation"
    )
    assert debtor["locate_status"] == "LOCATED"
    assert debtor["no_show_count"] == 0


def test_certified_score_excludes_the_open_finding_outright(api):
    """PRD §3.3: "The **certified** variant is stricter, and it is computed and
    written to `certified_recoverability_score` at exactly one moment: when a writ
    is requested."
    PRD §3.3: "Its weighted asset total counts only findings whose status is
    `VERIFIED`, at full weight — `OPEN` findings are excluded outright rather than
    discounted, as are `STALE` and `EXHAUSTED` ones."
    PRD §3.3: "Identical asset and examination data therefore produce a certified
    score that is never higher, and usually strictly lower, than the preliminary
    one."

    Design: Difficulty/dual_variant_calc/recoverability_preliminary_vs_certified_on_debtor_risk
    """
    ctx = _located_debtor_with_two_findings()
    action = draft_enforcement_action(
        ctx["judgment"]["id"], ctx["bank_finding"]["id"], "BANK_LEVY"
    )

    validate_success(api.request_writ(action["id"], EO))

    debtor = validate_success(api.get_debtor(ctx["debtor"]["id"], INV))
    assert debtor["recoverability_score"] == 78
    assert debtor["certified_recoverability_score"] == 64, (
        "only the verified 2,000,000 counts, giving an asset component of 24"
    )
    assert debtor["certified_recoverability_score"] < debtor["recoverability_score"]
    assert read_finding(ctx["bank_finding"]["id"])["status"] == "VERIFIED"
    assert read_finding(ctx["property_finding"]["id"])["status"] == "OPEN"


def test_verifying_an_already_verified_finding_is_an_invalid_transition(api):
    """PRD §3.3: "Verifying moves a finding `OPEN → VERIFIED`, or `STALE →
    VERIFIED` when a superseding trace had staled it, and in both cases the
    judgment must be `ACTIVE`."
    PRD §3.3: "Verification stamps `verified_by_user_id` with the calling
    investigator's `X-User-ID` and `verified_on` with the current clock date,
    re-stamping both on a re-verification, and recomputes the preliminary
    recoverability score."
    PRD §2.8: "The target resource sits in one of the states from which the
    requested transition is legal — otherwise `ERR_INVALID_STATE` and HTTP 409.
    This applies to every state-transition endpoint."

    Design: Corner/state_machines/verify_already_verified_finding_rejected_as_invalid_state
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    finding = create_verified_finding(
        ctx["judgment"]["id"], "inv-1", estimated_value_cents=900_000
    )
    assert finding["status"] == "VERIFIED"
    assert finding["verified_by_user_id"] == "inv-1"
    assert finding["verified_on"] == "2026-08-01"

    validate_error(
        api.verify_asset_finding(
            finding["id"], make_asset_investigator_headers("inv-2")
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )
    assert read_finding(finding["id"])["verified_by_user_id"] == "inv-1"


def test_a_new_trace_stales_only_the_skip_trace_sourced_findings(api):
    """PRD §3.3: "Every asset finding whose `source` is `SKIP_TRACE`, which hangs
    off a judgment whose `debtor_id` is the traced debtor, and whose own status is
    `OPEN` or `VERIFIED`, is moved to `STALE` — `OPEN → STALE` or `VERIFIED →
    STALE` as the case may be — in `created_at` ascending order."
    PRD §3.3: "Findings sourced from `PUBLIC_RECORD`, `CREDIT_HEADER` or
    `DEBTOR_EXAM` are untouched by a trace, and a finding already `STALE` or
    `EXHAUSTED` stays where it is."
    PRD §3.3: "Findings that are `STALE` or `EXHAUSTED` contribute nothing."

    Design: Corner/cross_cutting_complexity_layers/skip_trace_supersede_stales_only_skip_trace_sourced_findings
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    locate_debtor(ctx["debtor"]["id"], "inv-1", hits_count=3)

    trace_sourced = create_verified_finding(
        ctx["judgment"]["id"], "inv-1",
        estimated_value_cents=2_000_000, source="SKIP_TRACE",
    )
    public_sourced = create_verified_finding(
        ctx["judgment"]["id"], "inv-1",
        asset_type="REAL_PROPERTY", institution_name="LA County Recorder",
        identifier_last4="0042", estimated_value_cents=2_000_000,
        source="PUBLIC_RECORD",
    )
    before = read_debtor(ctx["debtor"]["id"])
    assert before["recoverability_score"] == 88

    after = validate_success(
        api.skip_trace(
            ctx["debtor"]["id"],
            skip_trace_payload(before["version"], vendor="IDI", hits_count=7),
            INV,
        )
    )
    assert after["skip_trace_count"] == 2
    assert after["recoverability_score"] == 64

    assert read_finding(trace_sourced["id"])["status"] == "STALE"
    assert read_finding(public_sourced["id"])["status"] == "VERIFIED"


def test_a_recorded_no_show_lowers_the_cooperation_component(api):
    """PRD §3.4: "`NO_SHOW` moves it `SERVED → NO_SHOW`, stamps
    `outcome_recorded_on`, increments the debtor's `no_show_count` by one, and —
    because that counter feeds the cooperation component — recomputes the debtor's
    preliminary recoverability score and increments the debtor's `version` by one."
    PRD §3.3: "The cooperation component starts at 20 and loses 10 points for each
    recorded no-show, counting at most two no-shows, so it is 20 at zero no-shows,
    10 at one, and 0 at two or more."

    Design: Corner/calculations/recoverability_score_drops_after_an_examination_no_show
    """
    ctx = setup_served_examination(
        interest_rate_bps=0, filing_costs_cents=0,
    )
    create_verified_finding(
        ctx["judgment"]["id"], "inv-1",
        asset_type="REAL_PROPERTY", institution_name="LA County Recorder",
        identifier_last4="0042", estimated_value_cents=2_000_000,
        source="PUBLIC_RECORD",
    )
    assert read_debtor(ctx["debtor"]["id"])["recoverability_score"] == 64

    examination = validate_success(
        api.record_examination_outcome(
            ctx["examination"]["id"], {"outcome": "NO_SHOW"}, CM
        )
    )
    assert examination["status"] == "NO_SHOW"

    debtor = read_debtor(ctx["debtor"]["id"])
    assert debtor["no_show_count"] == 1
    assert debtor["recoverability_score"] == 54


def test_a_skip_trace_replaying_a_stale_debtor_version_is_rejected(api):
    """PRD §2.7: "**Running a skip trace** — `POST /debtors/{debtor_id}/skip-trace`
    — must carry `expected_debtor_version` holding the client's last observed
    `version` of that debtor."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_DEBTOR_VERSION` and HTTP 412."
    PRD §3.3: "Every trace increments `skip_trace_count` by one, sets
    `last_skip_trace_on` to the current clock date, recomputes the debtor's
    `recoverability_score` under the preliminary variant, and increments the
    debtor's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_debtor_version_on_skip_trace_returns_412
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    original_version = ctx["debtor"]["version"]

    first = validate_success(
        api.skip_trace(
            ctx["debtor"]["id"], skip_trace_payload(original_version), INV
        )
    )
    assert first["locate_status"] == "LOCATED"
    assert first["skip_trace_count"] == 1

    validate_error(
        api.skip_trace(
            ctx["debtor"]["id"],
            skip_trace_payload(
                original_version, vendor="IDI", located=False, hits_count=4
            ),
            INV,
        ),
        ApiErrorId.ERR_STALE_DEBTOR_VERSION.value,
        412,
    )

    debtor = read_debtor(ctx["debtor"]["id"])
    assert debtor["locate_status"] == "LOCATED"
    assert debtor["skip_trace_count"] == 1


def test_drafting_against_an_unverified_finding_is_refused(api):
    """PRD §3.5: "The referenced finding must be in status `VERIFIED` at that
    moment, and a finding that is `OPEN`, `STALE` or `EXHAUSTED` draws
    `ERR_FINDING_NOT_VERIFIED`."

    Design: Corner/validations/enforcement_action_on_an_unverified_finding_is_rejected
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    version = ctx["judgment"]["version"]
    finding = create_open_finding(
        ctx["judgment"]["id"], "inv-1", estimated_value_cents=900_000
    )

    validate_error(
        api.create_enforcement_action(
            create_enforcement_action_payload(
                ctx["judgment"]["id"], finding["id"], version
            ),
            CM,
        ),
        ApiErrorId.ERR_FINDING_NOT_VERIFIED.value,
        409,
    )

    validate_success(api.verify_asset_finding(finding["id"], INV))
    action = validate_success(
        api.create_enforcement_action(
            create_enforcement_action_payload(
                ctx["judgment"]["id"], finding["id"], version
            ),
            CM,
        ),
        201,
    )
    assert action["status"] == "DRAFT"


def test_a_wage_garnishment_cannot_reach_a_bank_account_finding(api):
    """PRD §3.5: "The instrument must also match the asset class:
    `WAGE_GARNISHMENT` demands a finding whose `asset_type` is `EMPLOYMENT` and
    `BANK_LEVY` demands one whose `asset_type` is `BANK_ACCOUNT`, and any other
    pairing is `ERR_ACTION_ASSET_TYPE_MISMATCH`."

    Design: Corner/validations/wage_garnishment_against_a_bank_account_finding_is_rejected
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    finding = create_verified_finding(
        ctx["judgment"]["id"], "inv-1", estimated_value_cents=900_000
    )
    judgment = read_judgment(ctx["judgment"]["id"])

    validate_error(
        api.create_enforcement_action(
            create_enforcement_action_payload(
                ctx["judgment"]["id"], finding["id"], judgment["version"],
                action_type="WAGE_GARNISHMENT",
            ),
            CM,
        ),
        ApiErrorId.ERR_ACTION_ASSET_TYPE_MISMATCH.value,
        409,
    )
