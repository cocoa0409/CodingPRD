"""Withdrawal notices: publication cooling-off and sweep enforcement.

Covers the publish-time stamping (published_on now, effective_on +14 days) and
the depth-3 enforcement cascade the clock sweep drives once the effective date
arrives: notice EFFECTIVE, certification WITHDRAWN, licenses REVOKED, and their
ISSUED batches VOIDED — with quota recomputed and serials never rewound.
"""

from test_helpers import (
    BASE_CLOCK_ISO,
    canonical_instant,
    create_withdrawal_notice,
    issue_label_batch,
    publish_withdrawal_notice,
    refresh_certification,
    refresh_mark_license,
    set_clock,
    setup_certified,
    setup_certified_with_license,
    validate_paginated,
)


def test_withdrawal_notice_publish_sets_cooling_off_dates(api, officer_headers):
    """PRD §3.9: "Publishing — allowed while the certification is `ACTIVE` or
    `SUSPENDED` — stamps `published_on` with the current logical time, sets
    `effective_on` to 14 days after `published_on` as a cooling-off period
    before enforcement, and moves the notice to `PUBLISHED`."

    Design: Corner/endpoints/withdrawal_notice_publish_sets_cooling_off_dates
    """
    ctx = setup_certified(api)
    notice = create_withdrawal_notice(
        api,
        ctx["certification"]["id"],
        reason_code="SAFETY",
        public_text="Listing withdrawn: shock hazard.",
    )
    published = publish_withdrawal_notice(api, notice["id"])
    assert published["status"] == "PUBLISHED"
    assert canonical_instant(published["published_on"]) == canonical_instant(
        BASE_CLOCK_ISO
    )
    assert canonical_instant(published["effective_on"]) == canonical_instant(
        "2026-09-15T00:00:00Z"
    )
    # The cooling-off has not elapsed: the certification is untouched.
    certification = refresh_certification(api, ctx["certification"]["id"])
    assert certification["status"] == "ACTIVE"


def test_withdrawal_enforcement_cascades_through_license_to_batches(api, officer_headers):
    """PRD §3.9: "When a clock sweep finds a `PUBLISHED` notice whose
    `effective_on` is at or before the current time, the notice becomes
    `EFFECTIVE` — terminal — and its certification, whether `ACTIVE` or
    `SUSPENDED`, becomes `WITHDRAWN`. Withdrawal cascades two levels deep: every
    non-`REVOKED` mark license of the certification becomes `REVOKED`, and on
    each revoked license every `ISSUED` label batch becomes `VOIDED`, with
    `used_quantity` recomputed on each affected license."

    Design: Difficulty/transitive_cascade/withdrawal_enforcement_cascades_notice_cert_license_batch
    """
    ctx = setup_certified_with_license(api)
    cert_id = ctx["certification"]["id"]
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    first = issue_label_batch(api, lic_id, mfr_id, 100)  # serials 1..100
    second = issue_label_batch(api, lic_id, mfr_id, 50)  # serials 101..150

    notice = create_withdrawal_notice(
        api,
        cert_id,
        reason_code="NONCONFORMITY",
        public_text="Listing withdrawn due to factory nonconformity.",
    )
    publish_withdrawal_notice(api, notice["id"])

    # effective_on is 2026-09-15; the sweep at that instant enforces it.
    set_clock(api, "2026-09-15T00:00:00Z")

    notices, _meta = validate_paginated(
        api.list_withdrawal_notices(cert_id, officer_headers)
    )
    notice_view = next(n for n in notices if n["id"] == notice["id"])
    assert notice_view["status"] == "EFFECTIVE"

    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "WITHDRAWN"
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["status"] == "REVOKED"

    batches, _meta = validate_paginated(
        api.list_label_batches(lic_id, officer_headers)
    )
    by_id = {batch["id"]: batch for batch in batches}
    assert by_id[first["id"]]["status"] == "VOIDED"
    assert by_id[second["id"]]["status"] == "VOIDED"


def test_withdrawal_enforcement_recomputes_usage_without_rewinding_serials(
    api, officer_headers
):
    """PRD §3.9: "on each revoked license every `ISSUED` label batch becomes
    `VOIDED`, with `used_quantity` recomputed on each affected license."
    PRD §3.7: "The license's `next_serial` is never rewound: serials are never
    reused, and a voided range is simply skipped."
    PRD §3.7: "`used_quantity` always equals the sum of `quantity` over the
    license's `ISSUED` (non-`VOIDED`) batches."

    Design: Difficulty/transitive_cascade/withdrawal_enforcement_cascades_notice_cert_license_batch
    """
    ctx = setup_certified_with_license(api)
    cert_id = ctx["certification"]["id"]
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    issue_label_batch(api, lic_id, mfr_id, 100)
    issue_label_batch(api, lic_id, mfr_id, 50)
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["used_quantity"] == 150
    assert license_view["next_serial"] == 151

    notice = create_withdrawal_notice(
        api,
        cert_id,
        reason_code="NONCONFORMITY",
        public_text="Listing withdrawn due to factory nonconformity.",
    )
    publish_withdrawal_notice(api, notice["id"])
    set_clock(api, "2026-09-15T00:00:00Z")

    license_view = refresh_mark_license(api, lic_id)
    assert license_view["status"] == "REVOKED"
    assert license_view["used_quantity"] == 0, (
        "no ISSUED batches remain, so usage recomputes to zero"
    )
    assert license_view["next_serial"] == 151, "serials are never rewound"
