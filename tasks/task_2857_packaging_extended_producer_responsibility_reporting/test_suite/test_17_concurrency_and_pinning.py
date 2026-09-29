"""Optimistic concurrency on the two pinned versions, and what the pin buys.

A publish pins the organisation's version and a membership creation pins the
registration's, so a version consumed elsewhere makes the pinned value stale; and
because the membership keeps pointing at the schedule it pinned, a later
publication cannot reprice a report that was already covered.
"""

from test_helpers import (
    ApiErrorId,
    DecisionReason,
    FeePaymentStatus,
    FeeScheduleStatus,
    FeeVariant,
    MembershipStatus,
    REGULATOR_HEADERS,
    ReportFeeStatus,
    SubmissionStatus,
    assert_cents,
    assert_exact_cents,
    assert_fee_schedule,
    assert_membership,
    assert_no_version_movement,
    assert_report,
    assert_report_line,
    assert_weight,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The organisation's version is consumed by the first publish
# ---------------------------------------------------------------------------
def test_a_stale_expected_organisation_version_blocks_the_second_publish(api):
    """The version read once cannot pay for two publications.

    Two drafts on disjoint closed windows are authored while the organisation
    still sits at version one; the first publication consumes that version and the
    second, still carrying it, is refused at 412 without advancing anything. A
    fresh read pays for the retry, and the earlier closed window is not truncated
    by the later publication.

    Design: Corner/cross_cutting_complexity_layers/fee_schedule_publish_rejects_a_stale_expected_pro_version
    """
    program = fx.make_breadth_program(api)
    pro = fx.make_pro(
        api, name="Concurrency Stewardship", contact_email="ops@occ.example"
    )
    admin_headers = fx.admin(pro)
    first = fx.make_fee_schedule(
        api, pro, program["id"], effective_from="2026-01-01", effective_to="2026-06-30"
    )
    second = fx.make_fee_schedule(
        api,
        pro,
        program["id"],
        effective_from="2026-07-01",
        effective_to="2026-12-31",
        membership_fee_cents=260000,
        material_rates=[f.material_rate("GLASS", 0, None, 11)],
    )
    read_once = fx.read_pro_version(api, pro)
    assert read_once == 1

    published = validate_success(
        api.publish_fee_schedule(
            first["id"], f.publish_payload(read_once), admin_headers
        )
    )
    assert_fee_schedule(published, status=FeeScheduleStatus.PUBLISHED, version=2)
    assert fx.read_pro_version(api, pro) == 2

    validate_error(
        api.publish_fee_schedule(
            second["id"], f.publish_payload(read_once), admin_headers
        ),
        ApiErrorId.STALE_PRO_VERSION,
        412,
    )

    assert_fee_schedule(
        validate_success(api.get_fee_schedule(second["id"], admin_headers)),
        status=FeeScheduleStatus.DRAFT,
        version=1,
    )
    assert fx.read_pro_version(api, pro) == 2

    retried = fx.publish_fee_schedule(api, pro, second)

    assert_fee_schedule(retried, status=FeeScheduleStatus.PUBLISHED, version=2)
    assert fx.read_pro_version(api, pro) == 3
    assert_fee_schedule(
        validate_success(api.get_fee_schedule(first["id"], admin_headers)),
        status=FeeScheduleStatus.PUBLISHED,
        version=2,
        effective_to="2026-06-30",
    )


# ---------------------------------------------------------------------------
# The registration's version is advanced behind the applicant's back
# ---------------------------------------------------------------------------
def test_a_stale_expected_registration_version_blocks_the_membership_create(api):
    """A close-out between the read and the write invalidates the applicant's pin.

    The report is priced, billed and finalised, which advances the registration
    past the version the applicant had already read, so the application carrying
    that value is refused at 412; the paid coverage is untouched and no second
    membership row exists until the applicant re-reads, after which the new
    application starts pending and supersedes the old one.

    Design: Corner/cross_cutting_complexity_layers/membership_create_rejects_a_stale_expected_registration_version
    """
    chain = fx.base_ca_chain(api)
    officer_headers = chain["officer_headers"]
    fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.FINAL)
    fx.issue_invoice(api, chain["pro"], chain["report"], chain["membership"])
    read_once = fx.read_registration_version(
        api, chain["producer"], chain["registration"]["id"]
    )

    closed = validate_success(
        api.close_report(
            chain["report"]["id"], f.decision_payload("FINALIZE"), REGULATOR_HEADERS
        )
    )
    assert_report(closed, submission_status=SubmissionStatus.FINALIZED)
    after_close = validate_success(
        api.get_registration(chain["registration"]["id"], officer_headers)
    )
    assert after_close["version"] > read_once

    validate_error(
        api.create_membership(
            f.membership_payload(
                chain["registration"]["id"],
                chain["pro"]["id"],
                chain["schedule"]["id"],
                read_once,
            ),
            officer_headers,
        ),
        ApiErrorId.STALE_REGISTRATION_VERSION,
        412,
    )

    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], officer_headers)),
        status=MembershipStatus.ACTIVE,
        fee_payment_status=FeePaymentStatus.PAID,
    )
    memberships, meta = validate_paginated(
        api.list_memberships(
            officer_headers, {"registration_id": chain["registration"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in memberships] == [chain["membership"]["id"]]
    assert_no_version_movement(
        after_close,
        validate_success(
            api.get_registration(chain["registration"]["id"], officer_headers)
        ),
        "registration",
    )

    retried = fx.apply_for_membership(
        api, chain["producer"], chain["registration"], chain["pro"], chain["schedule"]
    )

    assert_membership(
        retried,
        status=MembershipStatus.PENDING,
        membership_fee_cents=0,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
        fee_schedule_version_pinned=None,
    )
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], officer_headers)),
        status=MembershipStatus.TERMINATED,
        decision_reason=DecisionReason.SUPERSEDED_BY_NEW_MEMBERSHIP,
    )


# ---------------------------------------------------------------------------
# What the pinned schedule buys the producer once rates rise
# ---------------------------------------------------------------------------
def test_the_pinned_schedule_still_prices_the_report_after_a_later_publish(api):
    """A new schedule at twice the rate does not reach a report already covered.

    The registration moves to an organisation whose 2026 schedule is a closed
    window at nine cents a kilogram, and the membership records that schedule's
    version at approval; when the same organisation later publishes a 2027 schedule
    at twenty cents, the closed window is not truncated and the assessment still
    prices the 5.500 kg at the pinned rate — fifty cents, not the hundred and ten
    the new schedule would have produced.

    Design: Corner/cross_cutting_complexity_layers/pinned_fee_schedule_prices_the_report_after_a_later_schedule_is_published
    """
    chain = fx.base_ca_chain(api)
    officer_headers = chain["officer_headers"]
    pro = fx.make_pro(
        api, name="Longhorizon Stewardship", contact_email="ops@longhorizon.example"
    )
    admin_headers = fx.admin(pro)
    pinned_schedule = fx.published_fee_schedule(
        api,
        pro,
        chain["program"]["id"],
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    membership = fx.paid_membership(
        api, chain["producer"], chain["registration"], pro, pinned_schedule
    )
    assert_membership(
        membership,
        status=MembershipStatus.ACTIVE,
        fee_payment_status=FeePaymentStatus.PAID,
        fee_schedule_id=pinned_schedule["id"],
        fee_schedule_version_pinned=2,
    )
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], officer_headers)),
        status=MembershipStatus.TERMINATED,
    )

    later = validate_success(
        api.create_fee_schedule(
            f.fee_schedule_payload(
                pro["id"],
                chain["program"]["id"],
                effective_from="2027-01-01",
                effective_to=None,
                membership_fee_cents=400000,
                material_rates=[f.material_rate("GLASS", 0, None, 20)],
            ),
            admin_headers,
        ),
        201,
    )
    published_later = fx.publish_fee_schedule(api, pro, later)
    assert_fee_schedule(published_later, status=FeeScheduleStatus.PUBLISHED, version=2)
    assert_fee_schedule(
        validate_success(api.get_fee_schedule(pinned_schedule["id"], admin_headers)),
        status=FeeScheduleStatus.PUBLISHED,
        version=2,
        effective_to="2026-12-31",
    )

    assessed = validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), admin_headers
        )
    )

    assert_report(
        assessed,
        fee_status=ReportFeeStatus.FINAL,
        fee_variant_applied=FeeVariant.FINAL,
        fee_subtotal_cents=50,
    )
    assert_weight(assessed["tier_basis_kg"], 5.500, "tier_basis_kg")
    assert_cents(assessed["fee_subtotal_cents"], 50, "fee_subtotal_cents")
    assert assessed["fee_subtotal_cents"] != 110

    line = validate_success(api.get_report_line(chain["line"]["id"], officer_headers))
    assert_report_line(line, line_fee_cents=50)
    assert_exact_cents(line["line_fee_exact_cents"], 49.5000, "line_fee_exact_cents")
