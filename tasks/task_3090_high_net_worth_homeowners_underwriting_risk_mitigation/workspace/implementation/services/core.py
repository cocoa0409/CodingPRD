"""Derived-field recomputation, the ordered underwriting gate, concentration
measurement and the cascade chains (PRD §2.9, §2.10, §3.5, §3.9)."""

from datetime import timedelta
from decimal import Decimal

import calc
import db
from clock import (add_days, add_hours, add_months, days_between_exclusive_inclusive,
                   first_of_next_month, fmt_dt, months_between, parse_dt, whole_days_ago)

COMMON_TERMINAL = ("DECLINED", "WITHDRAWN")


# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
def get(collection, key, label="resource"):
    record = collection.get(key)
    if record is None:
        from errors import err
        raise err("ERR_NOT_FOUND", "No %s with id %s." % (label, key))
    return record


def touch(record):
    """Refresh updated_at / version on a record carrying the common field set."""
    if record is None or "version" not in record:
        return
    record["updated_at"] = fmt_dt(db.now())
    record["version"] = record.get("version", 0) + 1


def mark_changed(record, changes):
    """Apply ``changes``; touch the record only when a value actually moved."""
    changed = False
    for key, value in changes.items():
        if record.get(key) != value:
            record[key] = value
            changed = True
        else:
            record.setdefault(key, value)
    if changed:
        touch(record)
    return changed


def is_active_enrollment(enrollment):
    return enrollment["status"] in calc.ACTIVE_ENROLLMENT_STATUSES


# --------------------------------------------------------------------------
# property derived fields
# --------------------------------------------------------------------------
def latest_approved_appraisal(property_id):
    """Greatest appraised_on, tie-broken by created_at ASC (PRD §3.1)."""
    rows = [a for a in db.APPRAISALS.values()
            if a["property_id"] == property_id and a["status"] == "APPROVED"]
    if not rows:
        return None
    rows.sort(key=lambda a: (a["appraised_on"], a["created_at"]))
    return rows[-1]


def latest_valuation_row(property_id):
    """The carried valuation: the greatest appraised_on among the property's
    APPROVED and REVIEWED appraisals (tie-broken by created_at ASC).

    A re-opened or freshly reviewed row is the valuation the gate must weigh,
    which is what lets a deficient re-appraisal drive the property to DECLINED.
    """
    rows = [a for a in db.APPRAISALS.values()
            if a["property_id"] == property_id and a["status"] in ("APPROVED", "REVIEWED")]
    if not rows:
        return None
    rows.sort(key=lambda a: (a["appraised_on"], a["created_at"]))
    return rows[-1]


def approved_appraisals_in_currency(property_id):
    now = db.now()
    out = []
    for appraisal in db.APPRAISALS.values():
        if appraisal["property_id"] != property_id or appraisal["status"] != "APPROVED":
            continue
        if months_between(appraisal["appraised_on"], now) < calc.DWELLING_CURRENCY_MONTHS:
            out.append(appraisal)
    return out


def latest_appraised_at(property_id):
    latest = latest_approved_appraisal(property_id)
    return latest["appraised_on"] if latest else None


def has_activated_ground(property_id):
    for notice in db.NON_RENEWAL_NOTICES.values():
        if notice["property_id"] != property_id:
            continue
        if notice["ground"] == "CONCENTRATION_REVIEW" and notice["status"] in ("ISSUED", "EFFECTIVE"):
            return True
    return False


def derive_posture(prop):
    """Pinned precedence ladder (PRD §2.9)."""
    if prop["base_posture"] in ("DECLINED", "PENDING_APPRAISAL"):
        return "WRITE_FROZEN"
    zone = db.ZONES.get(prop["risk_zone_id"])
    if zone is not None and zone["freeze_active"]:
        return "WRITE_FROZEN"
    if prop["base_posture"] == "MITIGATION_REQUIRED":
        return "REFERRAL_REQUIRED"
    if (zone is not None
            and zone["exposure_band"] == "ELEVATED"
            and zone["wildland_urban_interface_band"] in ("WITHIN_WUI", "ADJACENT_WUI")
            and not prop["defense_in_progress"]):
        return "REFERRAL_REQUIRED"
    return "WRITE_ELIGIBLE"


def funding_required(property_id):
    """Whether the property still rests on an appraisal able to fund the gate.

    PRD §3.5: the gate only passes on an APPROVED appraisal, at least one of
    which is SITE_MEASURED, and a valuation that remains in currency.  When an
    approved row is re-opened for a fresh cycle — it returns to REVIEWED — none
    of those holds, so the ordered gate falls back to PENDING_APPRAISAL exactly
    as it was on registration (PRD §3.1, §3.5).
    """
    approved = [a for a in db.APPRAISALS.values()
                if a["property_id"] == property_id and a["status"] == "APPROVED"]
    if not approved:
        return False
    if not any(a["valuation_method"] == "SITE_MEASURED" for a in approved):
        return False
    return approved_appraisals_in_currency(property_id)


def recompute_property(property_id):
    """Refresh every derived field; touch only when something actually moved."""
    prop = db.PROPERTIES[property_id]
    dwelling, contents = calc.replacement_cost(property_id)
    scheduled = calc.scheduled_valuation(property_id)
    if mark_changed(prop, {
        "dwelling_replacement_cost_cents": dwelling,
        "contents_replacement_cost_cents": contents,
        "scheduled_valuation_cents": scheduled,
        "total_insured_value_cents": dwelling + contents + scheduled,
        "mitigation_band": calc.mitigation_band(property_id),
        "defense_in_progress": calc.dispatch_in_progress(property_id),
        "non_renewal_ground_activated": has_activated_ground(property_id),
        "appraised_at": latest_appraised_at(property_id),
    }):
        pass
    # A base posture of UNDERWRITABLE cannot outlive the valuation that
    # justified it: once no approved site-measured appraisal remains in
    # currency the gate has nothing to stand on (PRD §2.4, §3.1, §3.5).
    if prop["base_posture"] == "UNDERWRITABLE" and not funding_required(property_id):
        prop["base_posture"] = "PENDING_APPRAISAL"
        touch(prop)
    posture = derive_posture(prop)
    if prop.get("posture") != posture:
        prop["posture"] = posture
        touch(prop)
    return prop


def stamp_posture_if_changed(prop):
    posture = derive_posture(prop)
    if prop.get("posture") != posture:
        prop["posture"] = posture
        touch(prop)
    return prop


# --------------------------------------------------------------------------
# enrollment convenience
# --------------------------------------------------------------------------
def properties_of_zone(zone_id):
    return [p for p in db.PROPERTIES.values() if p["risk_zone_id"] == zone_id]


def enrollments_of_property(property_id):
    return [e for e in db.ENROLLMENTS.values() if e["property_id"] == property_id]


def attached_or_approved_enrollment(property_id):
    """The enrollment that stands as the policy of record for claim routing."""
    rows = [e for e in enrollments_of_property(property_id)
            if e["status"] in ("APPROVED", "ATTACHED")]
    if not rows:
        return None
    rows.sort(key=lambda e: e["created_at"])
    return rows[-1]


def property_total_insured_value(property_id):
    prop = db.PROPERTIES.get(property_id)
    return prop["total_insured_value_cents"] if prop else 0


def recompute_enrollment_reserves(enrollment):
    dwelling = enrollment["dwelling_coverage_cents"]
    contents = enrollment["contents_coverage_cents"]
    scheduled = enrollment["scheduled_coverage_cents"]
    reserve = dwelling + contents + scheduled
    terminal = enrollment["status"] in COMMON_TERMINAL
    changed = False
    if enrollment.get("stress_reserve_cents") != reserve:
        enrollment["stress_reserve_cents"] = reserve
        changed = True
    committed = 0 if terminal else reserve
    if enrollment.get("committed_reserve_cents") != committed:
        enrollment["committed_reserve_cents"] = committed
        changed = True
    if changed:
        touch(enrollment)
    return enrollment


def push_submitted_to_referred(property_id):
    for enrollment in enrollments_of_property(property_id):
        if enrollment["status"] == "SUBMITTED":
            enrollment["status"] = "REFERRED"
            touch(enrollment)


def push_draft_or_submitted_to_declined(property_id):
    for enrollment in list(enrollments_of_property(property_id)):
        if enrollment["status"] in ("DRAFT", "SUBMITTED"):
            decline_enrollment(enrollment)


# --------------------------------------------------------------------------
# decision 15: concentration measurement
# --------------------------------------------------------------------------
def _band(value, elevated, critical):
    if value >= float(critical):
        return "CRITICAL"
    if value >= float(elevated):
        return "ELEVATED"
    return "NORMAL"


def recompute_concentration():
    """Portfolio-wide recomputation (PRD §2.10).  Every zone is re-derived."""
    # The population minimum counts the book's ACTIVE enrollments and is not
    # measured in exposure.
    active = [e for e in db.ENROLLMENTS.values() if is_active_enrollment(e)]
    count = len(active)
    portfolio_total = sum(property_total_insured_value(e["property_id"]) for e in active)

    freeze_flips = []
    for zone in list(db.ZONES.values()):
        zone_active = [e for e in active if e["risk_zone_id"] == zone["id"]]
        zone_total = sum(property_total_insured_value(e["property_id"]) for e in zone_active)
        if count < calc.MIN_PORTFOLIO_ACTIVE_COUNT:
            pct = Decimal("0.00")
        else:
            pct = calc.round2(Decimal(100) * Decimal(zone_total) / Decimal(portfolio_total))
        band = _band(pct, calc.ZONE_BAND_ELEVATED_PCT, calc.ZONE_BAND_CRITICAL_PCT)
        freeze = band == "CRITICAL" and count >= calc.MIN_PORTFOLIO_ACTIVE_COUNT
        old_freeze = zone["freeze_active"]
        mark_changed(zone, {
            "concentration_ratio_pct": float(pct),
            "concentration_band": band,
            "freeze_active": freeze,
        })
        if old_freeze != freeze:
            freeze_flips.append(zone["id"])

        by_agency = {}
        for enrollment in zone_active:
            by_agency.setdefault(enrollment["agency_id"], 0)
            by_agency[enrollment["agency_id"]] += property_total_insured_value(
                enrollment["property_id"])
        for agency_id, numerator in by_agency.items():
            agency = db.AGENCIES.get(agency_id)
            if agency is None:
                continue
            # Concentration is measured at both scopes only at a population of
            # two or more active enrollments; below that the ratio is pinned to
            # 0.0 and the band to NORMAL (PRD §2.10).
            if count < calc.MIN_PORTFOLIO_ACTIVE_COUNT or zone_total == 0:
                agency_pct = Decimal("0.00")
            else:
                agency_pct = calc.round2(
                    Decimal(100) * Decimal(numerator) / Decimal(zone_total))
            mark_changed(agency, {
                "concentration_ratio_pct": float(agency_pct),
                "concentration_band": _band(agency_pct, calc.AGENCY_BAND_ELEVATED_PCT,
                                            calc.AGENCY_BAND_CRITICAL_PCT),
            })

    # Hop 3 of the declined-enrollment cascade, then hop 4.
    for zone_id in freeze_flips:
        for prop in properties_of_zone(zone_id):
            recompute_property(prop["id"])
            if prop["posture"] == "WRITE_FROZEN":
                push_submitted_to_referred(prop["id"])


# --------------------------------------------------------------------------
# decision 17: the declined-enrollment cascade
# --------------------------------------------------------------------------
def decline_enrollment(enrollment, cascade=True):
    """Drive an enrollment to DECLINED and run the four-hop cascade."""
    enrollment["status"] = "DECLINED"
    touch(enrollment)
    recompute_enrollment_reserves(enrollment)
    if not cascade:
        return enrollment

    property_id = enrollment["property_id"]
    # Hop 1: every REQUESTED defense dispatch of the property is cancelled.
    for dispatch in db.DISPATCHES.values():
        if dispatch["property_id"] == property_id and dispatch["status"] == "REQUESTED":
            dispatch["status"] = "CANCELLED"
            dispatch["vendor_ref"] = None
            dispatch["assigned_at"] = None
            touch(dispatch)
    # Hop 2 (and hops 3/4): portfolio-wide concentration re-derivation.
    recompute_concentration()
    recompute_property(property_id)
    # Third hop of the cascade: any claim of the enrollment not yet terminal.
    for claim in db.CLAIMS.values():
        if claim["enrollment_id"] == enrollment["id"] and claim["status"] in ("REPORTED", "UNDER_REVIEW"):
            claim["status"] = "REJECTED"
            claim["settlement_amount_cents"] = 0
            touch(claim)
    return enrollment


# --------------------------------------------------------------------------
# decision 22: zone event changes
# --------------------------------------------------------------------------
def apply_zone_event(zone):
    """Dropping the zone's event level cancels every dispatch that has reached
    vendor assignment (PRD §3.4, §3.6).

    A dispatch still in `REQUESTED` has not been assigned a vendor, so the drop
    leaves it queued; it is the loss of an assigned vendor that has to be
    cancelled.  Because the zone is no longer `ACTIVE`, a queued request is
    simply not eligible for a poll until the event returns.
    """
    if zone["state_event"] == "ACTIVE":
        return
    for dispatch in db.DISPATCHES.values():
        if dispatch["risk_zone_id"] != zone["id"]:
            continue
        if dispatch["status"] not in ("VENDOR_ASSIGNED", "ON_SITE"):
            continue
        dispatch["status"] = "CANCELLED"
        dispatch["vendor_ref"] = None
        dispatch["assigned_at"] = None
        touch(dispatch)
        prop = db.PROPERTIES.get(dispatch["property_id"])
        if prop is None:
            continue
        recompute_property(prop["id"])
        for enrollment in enrollments_of_property(prop["id"]):
            if enrollment["status"] == "APPROVED" and enrollment["replacement_provision"] == "GUARANTEED":
                enrollment["guaranteed_replacement_limit_cents"] = \
                    prop["dwelling_replacement_cost_cents"]
                touch(enrollment)


def _midnight(instant):
    """Anchor an instant to 00:00:00 on its own day, in the logical clock's zone."""
    if instant is None:
        return None
    instant = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    return instant


# --------------------------------------------------------------------------
# decision 10: automatic, clock-driven transitions and derived-on-read fields
# --------------------------------------------------------------------------
def refresh_appraisal_documents():
    now = db.now()
    for doc in db.APPRAISAL_DOCUMENTS.values():
        months = months_between(doc["appraisal_date"], now)
        expired = first_of_next_month(add_months(doc["appraisal_date"], 24))
        doc["currency_months"] = months
        doc["currency_status"] = calc.currency_status(months)
        doc["expires_on"] = fmt_dt(expired)


def refresh_scheduled_items():
    now = db.now()
    for item in db.SCHEDULED_ITEMS.values():
        doc = db.APPRAISAL_DOCUMENTS.get(item["appraisal_doc_id"])
        item["appraisal_currency_months"] = (
            months_between(doc["appraisal_date"], now) if doc else 0)
        item["attached_value_cents"] = (
            item["declared_value_cents"] if item["status"] in ("APPROVED", "ATTACHED") else 0)


def refresh_non_renewal_notices():
    now = db.now()
    for notice in db.NON_RENEWAL_NOTICES.values():
        # A notice not yet issued has no sealed period; the window is measured
        # from its own filing date once it is issued.
        if notice["issued_on"] is None:
            continue
        notice["notice_period_days"] = days_between_exclusive_inclusive(
            notice["issued_on"], notice["effective_on"])


def fire_consultation_no_shows():
    now = db.now()
    for consultation in db.RISK_CONSULTATIONS.values():
        if consultation["status"] != "SCHEDULED":
            continue
        if now > add_days(consultation["scheduled_for"], 7):
            consultation["status"] = "NO_SHOW"
            touch(consultation)


def fire_mitigation_lapses():
    now = db.now()
    for requirement in list(db.MITIGATION_REQUIREMENTS.values()):
        if requirement["status"] != "IMPOSED":
            continue
        if requirement["due_on"] is None or now <= requirement["due_on"]:
            continue
        requirement["status"] = "LAPSED"
        touch(requirement)
        record_managed_risk_event(requirement, "OVERDUE_WARNING")
        property_id = requirement["property_id"]
        prop = db.PROPERTIES.get(property_id)
        if prop is None:
            continue
        recompute_property(property_id)
        if prop["base_posture"] == "MITIGATION_REQUIRED" and _all_requirements_closed(property_id):
            prop["base_posture"] = "DECLINED"
            prop["posture"] = "WRITE_FROZEN"
            touch(prop)
            push_draft_or_submitted_to_declined(property_id)


def _all_requirements_closed(property_id):
    rows = [r for r in db.MITIGATION_REQUIREMENTS.values() if r["property_id"] == property_id]
    if not rows:
        return False
    return all(r["status"] in ("LAPSED", "WAIVED") for r in rows)


def fire_appraisal_lapses():
    for prop in list(db.PROPERTIES.values()):
        if prop["base_posture"] != "UNDERWRITABLE":
            continue
        if not _has_valuation_input(prop):
            prop["base_posture"] = "PENDING_APPRAISAL"
            touch(prop)
            recompute_property(prop["id"])
            push_submitted_to_referred(prop["id"])
            continue
        if approved_appraisals_in_currency(prop["id"]):
            continue
        prop["base_posture"] = "PENDING_APPRAISAL"
        touch(prop)
        recompute_property(prop["id"])
        push_submitted_to_referred(prop["id"])


def _has_valuation_input(prop):
    """Whether the property still rests on a signed valuation."""
    has_approved = any(a["property_id"] == prop["id"] and a["status"] == "APPROVED"
                       for a in db.APPRAISALS.values())
    return has_approved or prop["scheduled_valuation_cents"] > 0


def fire_non_renewal_effects():
    now = db.now()
    for notice in list(db.NON_RENEWAL_NOTICES.values()):
        if notice["status"] != "ISSUED":
            continue
        if notice["effective_on"] is None or now <= notice["effective_on"]:
            continue
        notice["status"] = "EFFECTIVE"
        touch(notice)
        enrollment = db.ENROLLMENTS.get(notice["enrollment_id"])
        if enrollment is not None and enrollment["status"] == "ATTACHED":
            decline_enrollment(enrollment)
        prop = db.PROPERTIES.get(notice["property_id"])
        if prop is not None:
            recompute_property(prop["id"])
        recompute_concentration()


def on_clock_change():
    """Every clock-derived field is refreshed and every crossed threshold fires."""
    refresh_appraisal_documents()
    refresh_scheduled_items()
    refresh_non_renewal_notices()
    fire_consultation_no_shows()
    fire_mitigation_lapses()
    fire_appraisal_lapses()
    fire_non_renewal_effects()


def impose_requirement(prop, requirement_code, band_awarded, source, due_on):
    """Impose a requirement and run the UNDERWRITABLE -> MITIGATION_REQUIRED hop."""
    now = fmt_dt(db.now())
    requirement = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "property_id": prop["id"],
        "requirement_code": requirement_code,
        "band_awarded": band_awarded,
        "source": source,
        "due_on": parse_dt(due_on, db.now()),
        "status": "IMPOSED",
        "verification_count": 0,
        "verified_on": None,
    }
    db.MITIGATION_REQUIREMENTS[requirement["id"]] = requirement
    _refresh_band(prop["id"])
    if prop["base_posture"] == "UNDERWRITABLE":
        prop["base_posture"] = "MITIGATION_REQUIRED"
        touch(prop)
        push_submitted_to_referred(prop["id"])
    stamp_posture_if_changed(prop)
    return requirement


def _refresh_band(property_id):
    prop = db.PROPERTIES.get(property_id)
    if prop is None:
        return
    band = calc.mitigation_band(property_id)
    if prop.get("mitigation_band") != band:
        prop["mitigation_band"] = band
        touch(prop)


def attach_requirement(prop, requirement_code, band_awarded, source, due_on):
    """Record a requirement WITHOUT running the UNDERWRITABLE -> MITIGATION_REQUIRED hop.

    Used for the auto-impositions that ride along with an evaluation or a
    defence completion: the requirement is recorded and the band recomputed,
    but the property's own base posture is left for the caller to derive, since
    an auto-imposed follow-up does not by itself re-gate a property that was
    just found underwritable.
    """
    now = fmt_dt(db.now())
    requirement = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "property_id": prop["id"],
        "requirement_code": requirement_code,
        "band_awarded": band_awarded,
        "source": source,
        "due_on": parse_dt(due_on, db.now()),
        "status": "IMPOSED",
        "verification_count": 0,
        "verified_on": None,
    }
    db.MITIGATION_REQUIREMENTS[requirement["id"]] = requirement
    _refresh_band(prop["id"])
    stamp_posture_if_changed(prop)
    return requirement


def record_managed_risk_event(requirement, event_type, body=None):
    """Each derived key opens exactly one letter (PRD §3.9)."""
    derived_key = "%s:%s:%s" % (requirement["property_id"], requirement["id"], event_type)
    for event in db.MANAGED_RISK_EVENTS.values():
        if event["derived_key"] == derived_key:
            return event
    event = {
        "id": db.new_id(),
        "created_at": fmt_dt(db.now()),
        "property_id": requirement["property_id"],
        "event_type": event_type,
        "source_requirement_id": requirement["id"],
        "derived_key": derived_key,
        "sent_at": fmt_dt(db.now()),
        "body_summary": body or _letter_body(requirement, event_type),
    }
    db.MANAGED_RISK_EVENTS[event["id"]] = event
    return event


def _letter_body(requirement, event_type):
    if event_type == "REPEAT_INSPECTION_NOTICE":
        return ("Repeat inspection notice for requirement %s (%s) on property %s."
                % (requirement["id"], requirement["requirement_code"],
                   requirement["property_id"]))
    return ("Overdue mitigation warning for requirement %s (%s) on property %s."
            % (requirement["id"], requirement["requirement_code"],
               requirement["property_id"]))


# --------------------------------------------------------------------------
# decision 25: enrollment snapshot block (used by approve)
# --------------------------------------------------------------------------
def snapshot_enrollment(enrollment):
    prop = recompute_property(enrollment["property_id"])
    dwelling_rc = prop["dwelling_replacement_cost_cents"]
    parts = calc.risk_score_parts(prop["id"])
    band = calc.mitigation_band(prop["id"])
    defense_active = calc.dispatch_in_progress(prop["id"])
    provision, guaranteed_limit, extended_limit = calc.provision_block(
        dwelling_rc, band, defense_active)
    _, extended_premium, contents_premium, gross = calc.premium_block(
        dwelling_rc, enrollment["dwelling_coverage_cents"],
        enrollment["contents_coverage_cents"])
    enrollment["risk_score"] = parts["risk_score"]
    enrollment["risk_tier"] = parts["risk_tier"]
    enrollment["required_dwelling_coverage_cents"] = calc.required_dwelling_coverage(dwelling_rc)
    enrollment["extended_replacement_limit_cents"] = extended_limit
    enrollment["guaranteed_replacement_limit_cents"] = guaranteed_limit
    enrollment["replacement_provision"] = provision
    enrollment["extended_replacement_premium_cents"] = extended_premium
    enrollment["gross_premium_cents"] = gross
    enrollment["valuation_fingerprint"] = calc.valuation_fingerprint(prop["id"])
    touch(enrollment)
    return enrollment