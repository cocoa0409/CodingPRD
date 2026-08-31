"""Cascade chains and derived-value reconciliation."""
from decimal import Decimal

import calc
import clock
import db


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def campaign_sites(campaign_id):
    return sorted([s for s in db.sites.values() if s["campaign_id"] == campaign_id],
                  key=db.order_key)


def campaign_observations(campaign_id):
    return [o for o in db.observations.values() if o["campaign_id"] == campaign_id]


def protocol_of_campaign(campaign):
    return db.protocols.get(campaign["protocol_id"])


def observation_photos(observation_id):
    return sorted([p for p in db.photos.values() if p["observation_id"] == observation_id],
                  key=db.order_key)


def observation_votes(observation_id):
    return sorted([v for v in db.votes.values() if v["observation_id"] == observation_id],
                  key=db.order_key)


def volunteer_certifications(volunteer_id):
    return sorted([c for c in db.certifications.values() if c["volunteer_id"] == volunteer_id],
                  key=db.order_key)


def bound_observations(publication_id):
    return sorted([o for o in db.observations.values() if o["publication_id"] == publication_id],
                  key=db.order_key)


# --------------------------------------------------------------------------
# campaign_coverage_score  (two-stage, order pinned)
# --------------------------------------------------------------------------
def recompute_coverage(campaign):
    target = campaign["target_observations_per_site"]
    sites = campaign_sites(campaign["id"])

    ratios = []
    for site in sites:
        count = sum(1 for o in db.observations.values()
                    if o["site_id"] == site["id"] and o["review_status"] == "ACCEPTED")
        ratio = Decimal(count) / Decimal(target)
        if ratio > Decimal("1.0"):
            ratio = Decimal("1.0")
        ratio = calc.rnd(ratio, 2)

        if ratio < calc.GAP_RATIO_CEILING:
            status = "GAP"
        elif count >= calc.SATURATION_MULTIPLIER * target:
            status = "SATURATED"
        elif ratio == Decimal("1.00"):
            status = "MET"
        else:
            status = "UNDER"

        changed = (site["accepted_observation_count"] != count
                   or calc.dec(site["coverage_ratio"]) != ratio
                   or site["coverage_status"] != status)
        site["accepted_observation_count"] = count
        site["coverage_ratio"] = ratio
        site["coverage_status"] = status
        if changed:
            db.touch(site)
        ratios.append(ratio)

    site_count = len(sites)
    if site_count == 0:
        coverage_score = calc.rnd(Decimal("0.0"), 4)
    else:
        coverage_score = calc.rnd(sum(ratios, Decimal(0)) / Decimal(site_count), 4)
    gap_count = sum(1 for r in ratios if r < calc.GAP_RATIO_CEILING)
    accepted = sum(1 for o in campaign_observations(campaign["id"])
                   if o["review_status"] == "ACCEPTED")

    changed = (campaign["site_count"] != site_count
               or calc.dec(campaign["coverage_score"]) != coverage_score
               or campaign["gap_count"] != gap_count
               or campaign["accepted_observation_count"] != accepted)
    campaign["site_count"] = site_count
    campaign["coverage_score"] = coverage_score
    campaign["gap_count"] = gap_count
    campaign["accepted_observation_count"] = accepted
    if changed:
        db.touch(campaign)
    return gap_count


# --------------------------------------------------------------------------
# recognition ledger
# --------------------------------------------------------------------------
def append_award(volunteer, observation_id, award_type, points, reason):
    row = db.new_row({
        "volunteer_id": volunteer["id"],
        "observation_id": observation_id,
        "award_type": award_type,
        "points_awarded": int(points),
        "reason": reason,
    }, common=False)
    db.awards[row["id"]] = row
    volunteer["lifetime_points"] = volunteer["lifetime_points"] + int(points)
    return row


def refresh_scores(volunteer):
    volunteer["quality_score"] = calc.rolling_quality_score(volunteer["id"])
    volunteer["lifetime_quality_score"] = calc.lifetime_quality_score(volunteer["id"])


# --------------------------------------------------------------------------
# CASCADE-A — acceptance
# --------------------------------------------------------------------------
def apply_acceptance(observation):
    campaign = db.campaigns[observation["campaign_id"]]
    protocol = protocol_of_campaign(campaign)
    site = db.sites[observation["site_id"]]
    volunteer = db.volunteers[observation["volunteer_id"]]

    # link 1
    observation["review_status"] = "ACCEPTED"
    observation["final_quality_points"] = calc.final_points(observation, protocol, site)
    if observation["publication_status"] == "UNPUBLISHED":
        observation["publication_status"] = "QUEUED"
    db.touch(observation)

    # link 2 — the tier multiplier reads the PRE-acceptance lifetime score
    multiplier = calc.tier_multiplier(volunteer["lifetime_quality_score"])
    base_points = int((calc.dec(observation["final_quality_points"]) * multiplier)
                      .to_integral_value(rounding="ROUND_FLOOR"))
    volunteer["accepted_observation_count"] += 1
    volunteer["consecutive_accepted"] += 1
    volunteer["consecutive_rejections"] = 0
    append_award(volunteer, observation["id"], "OBSERVATION_ACCEPTED", base_points,
                 "Observation accepted by expert consensus.")

    # link 3 — streak, after the increment
    if volunteer["consecutive_accepted"] > 0 and volunteer["consecutive_accepted"] % calc.STREAK_LENGTH == 0:
        append_award(volunteer, observation["id"], "STREAK_BONUS", calc.STREAK_BONUS_POINTS,
                     "Streak of %d consecutive accepted observations." % volunteer["consecutive_accepted"])

    # link 4 — scores, tier, milestone
    old_tier = volunteer["recognition_tier"]
    refresh_scores(volunteer)
    new_tier = calc.tier_for(volunteer["lifetime_quality_score"])
    volunteer["recognition_tier"] = new_tier
    if calc.TIER_RANK[new_tier] > calc.TIER_RANK[old_tier]:
        append_award(volunteer, None, "MILESTONE", calc.TIER_MILESTONE_POINTS,
                     "Recognition tier advanced to %s." % new_tier)
    db.touch(volunteer)

    # coverage arithmetic
    recompute_coverage(campaign)


# --------------------------------------------------------------------------
# CASCADE-R — rejection
# --------------------------------------------------------------------------
def apply_rejection(observation):
    volunteer = db.volunteers[observation["volunteer_id"]]

    # link 1
    observation["review_status"] = "REJECTED"
    db.touch(observation)

    # link 2
    volunteer["rejected_observation_count"] += 1
    volunteer["consecutive_rejections"] += 1
    volunteer["consecutive_accepted"] = 0
    refresh_scores(volunteer)
    db.touch(volunteer)

    # link 3 / probation escalation
    if volunteer["status"] == "ACTIVE" and calc.dec(volunteer["quality_score"]) < calc.PROBATION_FLOOR:
        volunteer["status"] = "PROBATION"
        db.touch(volunteer)
        # link 4 — ADVANCED / EXPERT credentials only
        for cert in volunteer_certifications(volunteer["id"]):
            if cert["status"] == "CERTIFIED" and cert["level"] in ("ADVANCED", "EXPERT"):
                cert["status"] = "SUSPENDED"
                cert["suspended_reason"] = "QUALITY_PROBATION"
                db.touch(cert)
        # link 5 — forward commitments
        for loan in db.loans.values():
            if loan["volunteer_id"] == volunteer["id"] and loan["status"] == "REQUESTED":
                loan["status"] = "CANCELLED"
                db.touch(loan)
    elif volunteer["status"] == "PROBATION" and volunteer["consecutive_rejections"] >= 3:
        volunteer["status"] = "SUSPENDED"
        db.touch(volunteer)
        for cert in volunteer_certifications(volunteer["id"]):
            if cert["status"] == "CERTIFIED":
                cert["status"] = "SUSPENDED"
                cert["suspended_reason"] = "QUALITY_PROBATION"
                db.touch(cert)


# --------------------------------------------------------------------------
# CASCADE-T — retraction
# --------------------------------------------------------------------------
def apply_retraction(observation):
    campaign = db.campaigns[observation["campaign_id"]]
    volunteer = db.volunteers[observation["volunteer_id"]]
    deciding_round = observation["revision_round"]
    gap_before = campaign["gap_count"]

    # link 1
    observation["review_status"] = "RETRACTED"

    # link 2
    if observation["publication_status"] in ("QUEUED", "PUBLISHED"):
        observation["publication_status"] = "WITHDRAWN"
    db.touch(observation)
    pub_id = observation["publication_id"]
    if pub_id and pub_id in db.publications:
        publication = db.publications[pub_id]
        remaining = [o for o in bound_observations(pub_id)
                     if o["publication_status"] in ("QUEUED", "PUBLISHED")]
        publication["record_count"] = max(0, publication["record_count"] - 1)
        if remaining:
            total = sum((calc.dec(o["final_quality_points"]) for o in remaining), Decimal(0))
            publication["mean_quality"] = calc.rnd(total / Decimal(len(remaining)), 2)
        else:
            publication["mean_quality"] = calc.rnd(Decimal("0.00"), 2)
        db.touch(publication)

    # link 3
    recompute_coverage(campaign)

    # link 4
    if campaign["gap_count"] > gap_before and campaign["status"] == "CLOSED":
        campaign["status"] = "OPEN"
        db.touch(campaign)
        recompute_coverage(campaign)

    # ledger compensation
    prior = sum(a["points_awarded"] for a in db.awards.values()
                if a["observation_id"] == observation["id"])
    append_award(volunteer, observation["id"], "REVERSAL", -prior,
                 "Reversal of awards for a retracted observation.")

    volunteer["accepted_observation_count"] = max(0, volunteer["accepted_observation_count"] - 1)
    volunteer["rejected_observation_count"] += 1
    volunteer["consecutive_accepted"] = 0
    refresh_scores(volunteer)
    db.touch(volunteer)

    # experts who confirmed in the deciding round
    for vote in observation_votes(observation["id"]):
        if vote["round_number"] != deciding_round or vote["decision"] != "CONFIRM":
            continue
        expert = db.experts.get(vote["expert_id"])
        if expert is None:
            continue
        expert["retracted_confirm_count"] += 1
        if (expert["retracted_confirm_count"] >= calc.RETRACTED_CONFIRM_SUSPEND_THRESHOLD
                and expert["status"] == "ACTIVE"):
            expert["status"] = "SUSPENDED"
        db.touch(expert)


# --------------------------------------------------------------------------
# publication_release_metrics
# --------------------------------------------------------------------------
def candidate_observations(campaign_id):
    rows = [o for o in db.observations.values()
            if o["campaign_id"] == campaign_id
            and o["review_status"] == "ACCEPTED"
            and o["publication_id"] is None
            and o["publication_status"] in ("QUEUED", "UNPUBLISHED")]
    return sorted(rows, key=db.order_key)


def prior_publication(campaign_id):
    rows = [p for p in db.publications.values()
            if p["campaign_id"] == campaign_id
            and p["status"] in ("DRAFT", "EMBARGOED", "RELEASED")]
    if not rows:
        return None
    rows.sort(key=db.order_key)
    return rows[-1]


def supersede_publication(prior):
    """STEP 1 of publication assembly."""
    prior["status"] = "WITHDRAWN"
    for obs in bound_observations(prior["id"]):
        if obs["publication_status"] == "QUEUED":
            obs["publication_id"] = None
            obs["publication_status"] = "UNPUBLISHED"
            db.touch(obs)
        elif obs["publication_status"] == "PUBLISHED":
            obs["publication_status"] = "WITHDRAWN"
            db.touch(obs)
    db.touch(prior)


def compute_publication_metrics(publication, candidates):
    """STEPS 2-4: floor, inclusion, record_count, mean_quality."""
    if not candidates:
        publication["quality_floor"] = calc.rnd(Decimal("0.00"), 2)
        included = []
    else:
        ordered = sorted(candidates,
                         key=lambda o: (calc.dec(o["final_quality_points"]),
                                        o["created_at"], o["_seq"]))
        median = ordered[(len(ordered) - 1) // 2]
        publication["quality_floor"] = calc.rnd(
            calc.dec(median["final_quality_points"]) * calc.FLOOR_FRACTION, 2)
        floor = calc.dec(publication["quality_floor"])
        included = [o for o in candidates if calc.dec(o["final_quality_points"]) >= floor]

    publication["record_count"] = len(included)
    if included:
        total = sum((calc.dec(o["final_quality_points"]) for o in included), Decimal(0))
        publication["mean_quality"] = calc.rnd(total / Decimal(len(included)), 2)
    else:
        publication["mean_quality"] = calc.rnd(Decimal("0.00"), 2)
    return included


# --------------------------------------------------------------------------
# publication release / withdrawal
# --------------------------------------------------------------------------
def release_publication(publication):
    publication["status"] = "RELEASED"
    publication["released_at"] = clock.now()
    for obs in bound_observations(publication["id"]):
        if obs["publication_status"] == "QUEUED":
            obs["publication_status"] = "PUBLISHED"
            db.touch(obs)
    campaign = db.campaigns.get(publication["campaign_id"])
    if campaign is not None and campaign["status"] == "CLOSED":
        campaign["status"] = "PUBLISHED"
        db.touch(campaign)
    db.touch(publication)


def withdraw_publication(publication):
    """CASCADE-W."""
    publication["status"] = "WITHDRAWN"

    # link 1
    for obs in bound_observations(publication["id"]):
        if obs["publication_status"] == "PUBLISHED":
            obs["publication_status"] = "WITHDRAWN"
            db.touch(obs)
        elif obs["publication_status"] == "QUEUED":
            obs["publication_status"] = "UNPUBLISHED"
            obs["publication_id"] = None
            db.touch(obs)

    # link 2
    zeroed = []
    grants = sorted([g for g in db.grants.values() if g["publication_id"] == publication["id"]],
                    key=db.order_key)
    for grant in grants:
        if grant["status"] == "APPROVED":
            grant["status"] = "REVOKED"
            grant["denied_reason"] = "PUBLICATION_WITHDRAWN"
            db.touch(grant)
            partner = db.partners.get(grant["partner_id"])
            if partner is not None:
                partner["active_grant_count"] = max(0, partner["active_grant_count"] - 1)
                db.touch(partner)
                if partner["active_grant_count"] == 0 and partner not in zeroed:
                    zeroed.append(partner)
        elif grant["status"] == "REQUESTED":
            grant["status"] = "DENIED"
            grant["denied_reason"] = "PUBLICATION_WITHDRAWN"
            db.touch(grant)

    # link 3
    for partner in zeroed:
        if partner["status"] == "APPROVED":
            partner["status"] = "SUSPENDED"
            db.touch(partner)

    # campaign returns to CLOSED when no RELEASED publication remains
    campaign = db.campaigns.get(publication["campaign_id"])
    if campaign is not None and campaign["status"] == "PUBLISHED":
        still_released = any(p["status"] == "RELEASED" and p["campaign_id"] == campaign["id"]
                             for p in db.publications.values())
        if not still_released:
            campaign["status"] = "CLOSED"
            db.touch(campaign)

    db.touch(publication)


# --------------------------------------------------------------------------
# protocol supersession chain (CASCADE-P)
# --------------------------------------------------------------------------
def retire_protocol(protocol):
    protocol["status"] = "RETIRED"
    db.touch(protocol)

    affected_volunteers = []
    certs = sorted([c for c in db.certifications.values()
                    if c["protocol_id"] == protocol["id"]], key=db.order_key)
    for cert in certs:
        if cert["status"] in ("ENROLLED", "TRAINED", "CERTIFIED", "SUSPENDED"):
            lost_certified = cert["status"] == "CERTIFIED"
            cert["status"] = "REVOKED"
            db.touch(cert)
            if lost_certified:
                volunteer = db.volunteers.get(cert["volunteer_id"])
                if volunteer is not None and volunteer not in affected_volunteers:
                    affected_volunteers.append(volunteer)

    for volunteer in affected_volunteers:
        if volunteer["status"] != "ACTIVE":
            continue
        holds = any(c["status"] == "CERTIFIED" for c in volunteer_certifications(volunteer["id"]))
        if not holds:
            volunteer["status"] = "PENDING"
            db.touch(volunteer)


# --------------------------------------------------------------------------
# equipment occupancy (half-open regime)
# --------------------------------------------------------------------------
def occupied_intervals(equipment_id):
    out = []
    for loan in db.loans.values():
        if loan["equipment_id"] != equipment_id:
            continue
        if loan["status"] in ("REQUESTED", "ISSUED", "OVERDUE"):
            out.append((loan["start_at"], loan["due_at"]))
        elif loan["status"] == "RETURNED" and loan["returned_at"] is not None:
            out.append((loan["start_at"],
                        clock.plus_hours(loan["returned_at"], calc.QUARANTINE_HOURS)))
    return out


def interval_conflicts(equipment_id, start_at, due_at):
    for occ_start, occ_end in occupied_intervals(equipment_id):
        if start_at < occ_end and occ_start < due_at:
            return True
    return False


def cancel_requested_loans(equipment_id):
    for loan in sorted(db.loans.values(), key=db.order_key):
        if loan["equipment_id"] == equipment_id and loan["status"] == "REQUESTED":
            loan["status"] = "CANCELLED"
            db.touch(loan)
