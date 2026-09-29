"""Endpoint behaviours of the motor-carrier operating-authority API.

Four endpoint claims are exercised here: the transactional rollback of the
designation bulk write, the biennial update measuring its next deadline from the
update instant, the sweep reporting four zero counters when nothing is due, and
the cure endpoint admitting exactly one cure and refusing the replay.

Every chain is built through the public endpoints of PRD S4 from an empty
database, with the logical compliance clock of PRD S2.5 pinned at each step.
"""

from types import SimpleNamespace

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER,
    REGISTRY_ADMIN,
    T_ELIGIBLE,
    T_ENROLL,
    T_PUBLISH,
    assert_carrier,
    assert_designation,
    assert_insurance_filing,
    assert_operating_authority,
    assert_revocation_proceeding,
    assert_sweep_result,
    authority_for_application,
    authority_version,
    biennial_update_payload,
    cancel_filing_payload,
    create_carrier,
    create_draft_application,
    create_insurer,
    create_process_agent,
    cure_payload,
    designation_payload,
    fee_payment_payload,
    filing_payload,
    make_carrier_headers,
    make_insurer_headers,
    read_authority,
    review_application,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Local chains.  Each one walks the registry -> application -> publication ->
# designation -> insurance -> activation sequence of PRD S3 with the atomic
# steps, so every test starts from an empty database.
# ---------------------------------------------------------------------------
def _published_authority(api, *, application_kwargs=None, carrier_kwargs=None):
    """PRD S3.3 + S3.4: a PUBLISHED application and the authority it minted."""
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, **(carrier_kwargs or {}))
    env = SimpleNamespace(
        carrier=carrier,
        carrier_id=carrier["id"],
        carrier_headers=make_carrier_headers(carrier["id"]),
    )
    env.application = create_draft_application(
        api, env.carrier_id, **(application_kwargs or {})
    )
    env.application_id = env.application["id"]
    env.application = submit_application(api, env.carrier_id, env.application_id)
    set_clock(api, T_PUBLISH)
    env.application = review_application(api, env.application_id, disposition="PUBLISH")
    env.authority = authority_for_application(api, env.application_id)
    env.authority_id = env.authority["id"]
    return env


def _designate(api, env, agent_id, state_codes, **kwargs):
    """PRD S3.4: the all-or-nothing designation bulk write, as its owner."""
    return api.create_designations(
        env.authority_id,
        designation_payload(agent_id, state_codes=state_codes, **kwargs),
        env.carrier_headers,
    )


def _file_bipd(api, env, insurer_id, policy_number, effective_at, limit_cents=75000000):
    """PRD S3.5: one BIPD filing against the authority's current version."""
    return api.create_filing(
        filing_payload(
            env.authority_id,
            insurer_id,
            limit_cents,
            authority_version(api, env.authority_id),
            filing_type="BIPD",
            policy_number=policy_number,
            effective_at=effective_at,
        ),
        make_insurer_headers(insurer_id),
    )


def _active_authority(api, **kwargs):
    """PRD S3.6: an ACTIVE authority with complete coverage and a paid docket."""
    env = _published_authority(api, **kwargs)
    env.agent = create_process_agent(api, coverage_states=["TX", "OK", "NM"])
    env.insurer = create_insurer(api, authorized_states=["TX", "OK", "NM"])
    env.insurer_headers = make_insurer_headers(env.insurer["id"])
    validate_success(
        _designate(api, env, env.agent["id"], env.authority["required_jurisdictions"]),
        201,
    )
    env.filing = validate_success(
        _file_bipd(api, env, env.insurer["id"], "BIPD-53", T_PUBLISH), 201
    )
    validate_success(
        api.record_fee_payment(
            env.carrier_id, fee_payment_payload(64791), env.carrier_headers
        ),
        201,
    )
    set_clock(api, T_ELIGIBLE)
    env.authority = validate_success(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER)
    )
    return env


def test_designation_bulk_write_rolls_back_when_one_state_conflicts(api):
    """PRD S3.4: "The request is strictly all-or-nothing: if **any** requested
    state code fails either of the two checks below, no row at all is created."
    PRD S3.4: "Designation intervals are **closed** at both ends and are expanded
    by a mandatory transition buffer of one day on each end before comparison, so
    adjacency is forbidden and even a one-day gap collides."
    PRD S3.4: "If the requested low edge is at or before the existing high edge
    **and** the requested high edge is at or after the existing low edge, the two
    intervals intersect and the whole request is rejected with
    `ERR_DESIGNATION_INTERVAL_CONFLICT`."
    PRD S3.4: "One `ProcessAgentDesignation` row is created per requested state
    code, each carrying the authority from the path, the single `state_code` it
    covers, the shared `effective_from` and `effective_to`, `status` `ACTIVE` and
    `revoked_at` null."
    PRD S3.4: "Build the set of state codes covered right now: every
    `ProcessAgentDesignation` on this authority whose `status` is `ACTIVE` and
    whose closed interval contains the current logical time — that is, whose
    `effective_from` is at or before now and whose `effective_to` is either null
    or at or after now."
    PRD S3.4: "`designated_state_count` is the number of state codes that appear
    in **both** that covered set and the authority's `required_jurisdictions`."

    Design: Corner/endpoints/designation_bulk_write_rolls_back_when_one_state_conflicts
    """
    env = _published_authority(
        api, carrier_kwargs={"legal_name": "Llano Estacado Carriers LLC"}
    )
    agent = create_process_agent(api, coverage_states=["TX", "OK", "NM"])
    incumbent = validate_success(_designate(api, env, agent["id"], ["TX", "OK"]), 201)
    assert [row["state_code"] for row in incumbent] == ["TX", "OK"]
    for row in incumbent:
        assert row["effective_to"] is None, (
            f"the incumbent designation is open-ended, got {row['effective_to']}"
        )

    validate_error(
        _designate(
            api,
            env,
            agent["id"],
            ["OK", "NM"],
            effective_from="2026-09-01T00:00:00Z",
        ),
        ApiErrorId.DESIGNATION_INTERVAL_CONFLICT,
    )

    rows, meta = validate_paginated(
        api.list_designations(REGISTRY_ADMIN, authority_id=env.authority_id)
    )
    assert meta["total_count"] == 2, (
        "OK already carries an open-ended ACTIVE designation, and the rollback "
        f"discarded the non-conflicting NM half too, got {meta['total_count']}"
    )
    assert sorted(row["state_code"] for row in rows) == ["OK", "TX"]

    _nm, nm_meta = validate_paginated(
        api.list_designations(
            REGISTRY_ADMIN, authority_id=env.authority_id, state_code="NM"
        )
    )
    assert nm_meta["total_count"] == 0, (
        f"no NM row survived the rejected bulk write, got {nm_meta['total_count']}"
    )

    accepted = validate_success(
        _designate(
            api, env, agent["id"], ["NM"], effective_from="2026-09-01T00:00:00Z"
        ),
        201,
    )
    assert len(accepted) == 1, (
        f"the same NM interval succeeds when submitted on its own, got {len(accepted)}"
    )
    designation = accepted[0]
    assert_designation(designation)
    assert designation["state_code"] == "NM"
    assert designation["status"] == "ACTIVE"
    assert designation["effective_from"] == "2026-09-01T00:00:00.000Z"
    assert designation["effective_to"] is None
    assert designation["revoked_at"] is None
    assert designation["authority_id"] == env.authority_id

    after = read_authority(api, env.authority_id)
    assert_operating_authority(after)
    assert after["required_jurisdictions"] == ["NM", "OK", "TX"]
    assert after["designated_state_count"] == 2, (
        "the covered set holds only the designations whose closed interval contains "
        "the current logical time of 2026-08-05, and the NM row opens on 2026-09-01, "
        f"got {after['designated_state_count']}"
    )
    assert after["designation_coverage_complete"] is False, (
        "NM is still uncovered at the current logical time, got "
        f"{after['designation_coverage_complete']}"
    )

    total, total_meta = validate_paginated(
        api.list_designations(REGISTRY_ADMIN, authority_id=env.authority_id)
    )
    assert total_meta["total_count"] == 3, (
        f"three designation rows now exist on the authority, got "
        f"{total_meta['total_count']}"
    )
    assert sorted(row["state_code"] for row in total) == ["NM", "OK", "TX"]


def test_biennial_update_clears_delinquency_and_pushes_the_deadline_out_730_days(api):
    """PRD S3.1: "Registration also opens the MCS-150 clock:
    `biennial_update_due_at` is set to the carrier's `created_at` plus 730 days,
    `last_biennial_update_at` is null, and `biennial_delinquent` is false."
    PRD S3.8: "Step two handles registration delinquency. Every `Carrier` whose
    `biennial_update_due_at` is strictly earlier than the current logical time
    and whose `biennial_delinquent` is still false has `biennial_delinquent` set
    to true, adding one to `carriers_flagged_delinquent_count` per carrier."
    PRD S3.1: "Filing the biennial update is a `CarrierRep` action against its own
    carrier, and it does three things at once. It overwrites
    `self_reported_vehicle_count`, `self_reported_driver_count` and
    `self_reported_oos_rate_pct` with the newly submitted figures; it records
    `last_biennial_update_at` as the current logical time and pushes
    `biennial_update_due_at` out to the current logical time plus 730 days; and it
    clears `biennial_delinquent` back to false."
    PRD S3.1: "its `compliance_risk_variant` opens at `NONE` (its other values
    being `SELF_REPORTED` and `AUDITED`) with `compliance_risk_score` and
    `audited_oos_rate_pct` both null"

    Design: Corner/endpoints/biennial_update_clears_delinquency_and_pushes_the_deadline_out_730_days
    """
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, legal_name="Sabine Crossing Motor Lines LLC")
    carrier_id = carrier["id"]
    carrier_headers = make_carrier_headers(carrier_id)
    assert carrier["biennial_update_due_at"] == "2028-07-31T00:00:00.000Z", (
        "enrolment on 2026-08-01 plus 730 days lands the MCS-150 deadline on "
        f"2028-07-31, got {carrier['biennial_update_due_at']}"
    )
    assert carrier["last_biennial_update_at"] is None
    assert carrier["biennial_delinquent"] is False

    set_clock(api, "2028-08-01T00:00:00Z")
    flagging = validate_success(api.run_compliance_sweep(COMPLIANCE_OFFICER))
    assert_sweep_result(flagging)
    assert flagging["carriers_flagged_delinquent_count"] == 1, (
        "2028-08-01 is strictly past the 2028-07-31 deadline, so step two flags "
        f"this carrier, got {flagging['carriers_flagged_delinquent_count']}"
    )
    flagged = validate_success(api.get_carrier(carrier_id, REGISTRY_ADMIN))
    assert flagged["biennial_delinquent"] is True, (
        f"the sweep set the delinquency flag, got {flagged['biennial_delinquent']}"
    )

    updated = validate_success(
        api.file_biennial_update(
            carrier_id,
            biennial_update_payload(
                self_reported_vehicle_count=40,
                self_reported_driver_count=60,
                self_reported_oos_rate_pct=12.5,
            ),
            carrier_headers,
        )
    )
    assert_carrier(updated)
    assert updated["biennial_delinquent"] is False, (
        f"the update clears delinquency back to false, got "
        f"{updated['biennial_delinquent']}"
    )
    assert updated["biennial_update_due_at"] == "2030-08-01T00:00:00.000Z", (
        "the next deadline is measured from the update instant 2028-08-01 plus 730 "
        f"days, not from the missed one, got {updated['biennial_update_due_at']}"
    )
    assert updated["last_biennial_update_at"] == "2028-08-01T00:00:00.000Z", (
        f"the update instant is recorded, got {updated['last_biennial_update_at']}"
    )
    assert updated["self_reported_vehicle_count"] == 40
    assert updated["self_reported_driver_count"] == 60
    assert updated["self_reported_oos_rate_pct"] == 12.5
    assert updated["compliance_risk_variant"] == "NONE", (
        "the biennial update does not score the carrier, got "
        f"{updated['compliance_risk_variant']}"
    )
    assert updated["compliance_risk_score"] is None, (
        f"no score has been written yet, got {updated['compliance_risk_score']}"
    )

    again = validate_success(api.run_compliance_sweep(COMPLIANCE_OFFICER))
    assert again["carriers_flagged_delinquent_count"] == 0, (
        "the refreshed deadline is no longer strictly earlier than the clock, so "
        f"step two flags nobody, got {again['carriers_flagged_delinquent_count']}"
    )
    assert again["swept_at"] == "2028-08-01T00:00:00.000Z"
    still_current = validate_success(api.get_carrier(carrier_id, REGISTRY_ADMIN))
    assert still_current["biennial_delinquent"] is False
    assert still_current["biennial_update_due_at"] == "2030-08-01T00:00:00.000Z"


def test_a_sweep_with_nothing_due_returns_all_zero_counters(api):
    """PRD S3.8: "The response reports `swept_at` (the logical instant at which
    the sweep ran) alongside `audits_missed_count`,
    `carriers_flagged_delinquent_count`, `authorities_revoked_count` and
    `contracts_terminated_count`."
    PRD S3.8: "Each audit moved this way adds one to `audits_missed_count`."
    PRD S3.8: "Each proceeding revoked this way adds one to
    `authorities_revoked_count`, and the number of contracts the termination
    cascade moved in its second hop is added to `contracts_terminated_count`."
    PRD S3.8: "Exactly three steps run, in this order, and within each step rows
    are processed in `created_at` ascending order."
    PRD S3.8: "Step two handles registration delinquency. Every `Carrier` whose
    `biennial_update_due_at` is strictly earlier than the current logical time
    and whose `biennial_delinquent` is still false has `biennial_delinquent` set
    to true, adding one to `carriers_flagged_delinquent_count` per carrier.
    Nothing else about the carrier changes"
    PRD S3.1: "Registration also opens the MCS-150 clock:
    `biennial_update_due_at` is set to the carrier's `created_at` plus 730 days,
    `last_biennial_update_at` is null, and `biennial_delinquent` is false."

    Design: Corner/endpoints/a_sweep_with_nothing_due_returns_all_zero_counters
    """
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, legal_name="Nueces Bay Hauling LLC")
    assert_carrier(carrier)
    assert carrier["biennial_update_due_at"] == "2028-07-31T00:00:00.000Z", (
        "enrolment on 2026-08-01 plus 730 days, which is nearly two years beyond "
        f"the sweep instant, got {carrier['biennial_update_due_at']}"
    )
    version_before = carrier["version"]

    swept = validate_success(api.run_compliance_sweep(REGISTRY_ADMIN))
    assert_sweep_result(swept)
    assert swept["swept_at"] == "2026-08-01T00:00:00.000Z", (
        f"swept_at echoes the logical clock, got {swept['swept_at']}"
    )
    assert swept["audits_missed_count"] == 0, (
        f"no audit exists to move to MISSED, got {swept['audits_missed_count']}"
    )
    assert swept["carriers_flagged_delinquent_count"] == 0, (
        "the one carrier is well inside its biennial window, so step two flagged "
        f"nobody, got {swept['carriers_flagged_delinquent_count']}"
    )
    assert swept["authorities_revoked_count"] == 0, (
        f"no proceeding exists to expire, got {swept['authorities_revoked_count']}"
    )
    assert swept["contracts_terminated_count"] == 0, (
        "no authority was revoked, so no termination cascade ran, got "
        f"{swept['contracts_terminated_count']}"
    )

    after = validate_success(api.get_carrier(carrier["id"], REGISTRY_ADMIN))
    assert after["biennial_delinquent"] is False, (
        f"the sweep did not flag the carrier, got {after['biennial_delinquent']}"
    )
    assert after["biennial_update_due_at"] == "2028-07-31T00:00:00.000Z", (
        f"the deadline is untouched by the sweep, got "
        f"{after['biennial_update_due_at']}"
    )
    assert after["last_biennial_update_at"] is None
    assert after["version"] == version_before, (
        "step two was the only step that could have touched a carrier and it moved "
        f"nothing, so the carrier row was not written, got {after['version']} "
        f"against {version_before}"
    )


def test_cure_is_admitted_once_and_the_replay_is_rejected(api):
    """PRD S3.8: "Each proceeding records the defect that opened it in `reason` —
    one of `INSURANCE_LAPSE`, `SAFETY_AUDIT_FAILURE` or `AUDIT_WINDOW_MISSED` — a
    `status` that opens at `NOTICE_ISSUED` and ends at either `CURED` or
    `REVOKED`, the `notice_issued_at` instant, and a `cure_deadline_at` that is
    exactly 30 days after `notice_issued_at`."
    PRD S3.5: "If, after the cancellation, at least one required slot no longer
    holds an `ACTIVE` filing whose interval contains the current logical time,
    `insurance_status` moves `FILED → LAPSED`. Because it lapsed, a
    `RevocationProceeding` is opened against the authority with `reason`
    `INSURANCE_LAPSE`, `status` `NOTICE_ISSUED`, `notice_issued_at` at the current
    logical time and `cure_deadline_at` exactly 30 days later."
    PRD S3.8: "The proceeding must still be `NOTICE_ISSUED`, since `CURED` and
    `REVOKED` are both terminal and yield `ERR_PROCEEDING_NOT_OPEN`."
    PRD S3.8: "A successful cure moves the proceeding `NOTICE_ISSUED → CURED`,
    stamps `cured_at` with the current logical time and records the submitted
    `replacement_policy_number`. Because the proceeding was cured, the authority's
    `insurance_status` is recomputed to `FILED`."
    PRD S3.8: "the authority returns to `ACTIVE` with `suspension_reason` reset to
    `NONE`"
    PRD S3.5: "If the slot was empty, `supersedes_filing_id` stays null.
    `CANCELLED` filings are invisible to this comparison."

    Design: Corner/endpoints/cure_is_admitted_once_and_the_replay_is_rejected
    """
    env = _active_authority(
        api, carrier_kwargs={"legal_name": "Trinity River Freightways LLC"}
    )
    assert env.authority["authority_status"] == "ACTIVE"
    assert env.authority["insurance_status"] == "FILED"

    set_clock(api, "2026-09-10T00:00:00Z")
    cancelled = validate_success(
        api.cancel_filing(
            env.filing["id"],
            cancel_filing_payload("2026-09-10T00:00:00Z"),
            env.insurer_headers,
        )
    )
    assert cancelled["status"] == "CANCELLED"

    lapsed = read_authority(api, env.authority_id)
    assert lapsed["insurance_status"] == "LAPSED", (
        "the only BIPD filing no longer covers the current logical time, got "
        f"{lapsed['insurance_status']}"
    )
    assert lapsed["authority_status"] == "SUSPENDED", (
        f"the opened proceeding suspended the authority, got "
        f"{lapsed['authority_status']}"
    )
    assert lapsed["suspension_reason"] == "INSURANCE_LAPSE", (
        f"the defect that caused it is recorded, got {lapsed['suspension_reason']}"
    )

    proceedings, meta = validate_paginated(
        api.list_authority_proceedings(
            env.authority_id, COMPLIANCE_OFFICER, status="NOTICE_ISSUED"
        )
    )
    assert meta["total_count"] == 1, (
        f"the lapse opened exactly one proceeding, got {meta['total_count']}"
    )
    proceeding = proceedings[0]
    assert_revocation_proceeding(proceeding)
    assert proceeding["reason"] == "INSURANCE_LAPSE"
    assert proceeding["notice_issued_at"] == "2026-09-10T00:00:00.000Z"
    assert proceeding["cure_deadline_at"] == "2026-10-10T00:00:00.000Z", (
        "the cure deadline is exactly 30 days after the notice, got "
        f"{proceeding['cure_deadline_at']}"
    )
    assert proceeding["cured_at"] is None
    assert proceeding["revoked_at"] is None
    assert proceeding["replacement_policy_number"] is None

    replacement = validate_success(
        _file_bipd(
            api, env, env.insurer["id"], "BIPD-53-REPL", "2026-09-11T00:00:00Z"
        ),
        201,
    )
    assert_insurance_filing(replacement)
    assert replacement["status"] == "ACTIVE"
    assert replacement["meets_required_minimum"] is True
    assert replacement["supersedes_filing_id"] is None, (
        "the incumbent was already CANCELLED and so invisible to the slot "
        f"comparison, got {replacement['supersedes_filing_id']}"
    )

    set_clock(api, "2026-09-12T00:00:00Z")
    cured = validate_success(
        api.cure_proceeding(
            proceeding["id"], cure_payload("BIPD-53-REPL"), COMPLIANCE_OFFICER
        )
    )
    assert_revocation_proceeding(cured)
    assert cured["status"] == "CURED", (
        f"the first cure closes the proceeding, got {cured['status']}"
    )
    assert cured["cured_at"] == "2026-09-12T00:00:00.000Z", (
        f"cured_at is stamped with the current logical time, got {cured['cured_at']}"
    )
    assert cured["replacement_policy_number"] == "BIPD-53-REPL", (
        f"the submitted policy number is recorded, got "
        f"{cured['replacement_policy_number']}"
    )
    assert cured["revoked_at"] is None

    restored = read_authority(api, env.authority_id)
    assert restored["insurance_status"] == "FILED", (
        f"the cure recomputes the coverage dimension to FILED, got "
        f"{restored['insurance_status']}"
    )
    assert restored["authority_status"] == "ACTIVE", (
        f"the restoration cascade returned the authority to ACTIVE, got "
        f"{restored['authority_status']}"
    )
    assert restored["suspension_reason"] == "NONE", (
        f"the suspension reason is reset, got {restored['suspension_reason']}"
    )

    validate_error(
        api.cure_proceeding(
            proceeding["id"], cure_payload("BIPD-53-REPL"), COMPLIANCE_OFFICER
        ),
        ApiErrorId.PROCEEDING_NOT_OPEN,
    )

    replayed, replay_meta = validate_paginated(
        api.list_authority_proceedings(env.authority_id, COMPLIANCE_OFFICER)
    )
    assert replay_meta["total_count"] == 1, (
        f"the replay created no second proceeding, got {replay_meta['total_count']}"
    )
    assert replayed[0]["status"] == "CURED"
    assert replayed[0]["cured_at"] == "2026-09-12T00:00:00.000Z", (
        "the refused replay left cured_at at its first value, got "
        f"{replayed[0]['cured_at']}"
    )
    unchanged = read_authority(api, env.authority_id)
    assert unchanged["authority_status"] == "ACTIVE"
    assert unchanged["version"] == restored["version"], (
        "the refused replay ran no second restoration, so the authority's version "
        f"did not move, got {unchanged['version']} against {restored['version']}"
    )
