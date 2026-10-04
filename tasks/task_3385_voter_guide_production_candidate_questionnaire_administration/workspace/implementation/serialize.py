"""Entity serializers. Derived/computed fields are evaluated here, on read,
so counters and ratios are always consistent with the underlying rows.
"""
import authz
import calc
import helpers
from store import store
from timeutil import fmt_date, fmt_dt

PUBLISHED_INDICATOR = {
    "SUBMITTED": "PUBLISHED_UNEDITED",
    "NONRESPONSE_MARKED": "DID_NOT_RESPOND",
    "LATE_UNPUBLISHED": "LATE",
    "WITHDRAWN_HIDDEN": "WITHDRAWN",
    "INVITED": "PENDING",
    "OVER_LIMIT_RETURNED": "PENDING",
}


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def _counts(rows):
    out = {}
    for row in rows:
        out[row["status"]] = out.get(row["status"], 0) + 1
    return out


# --- counters -------------------------------------------------------------

def questionnaire_counters(q):
    shells = helpers.shells_of_questionnaire(q["id"])
    by_status = _counts(shells)
    return {
        "invited_count": len(shells),
        "submitted_count": by_status.get("SUBMITTED", 0),
        "nonresponse_count": by_status.get("NONRESPONSE_MARKED", 0),
        "late_count": by_status.get("LATE_UNPUBLISHED", 0),
    }


def verified_candidate_count(contest):
    return sum(1 for f in helpers.filings_of_contest(contest["id"])
               if f["status"] == "VERIFIED")


def distributed_edition_count(cycle):
    return sum(1 for e in helpers.editions_of_cycle(cycle["id"])
               if e["status"] == "DISTRIBUTED")


def measure_totals(measure):
    pro = con = 0
    for a in helpers.arguments_of_measure(measure["id"]):
        if a["status"] != "ACCEPTED":
            continue
        if a["side"] == "PRO":
            pro += a["word_count"]
        else:
            con += a["word_count"]
    return pro, con


def substantiated_incident_count(volunteer):
    return sum(1 for i in helpers.incidents_of_volunteer(volunteer["id"])
               if i["status"] == "SUBSTANTIATED")


# --- serializers ----------------------------------------------------------

def cycle_json(c):
    out = _common(c)
    out.update({
        "cycle_name": c["cycle_name"],
        "election_date": fmt_date(c["election_date"]),
        "status": c["status"],
        "distributed_edition_count": distributed_edition_count(c),
    })
    return out


def jurisdiction_json(j):
    out = _common(j)
    out.update({
        "cycle_id": j["cycle_id"],
        "jurisdiction_name": j["jurisdiction_name"],
        "fips_code": j["fips_code"],
        "supported_language_codes": list(j["supported_language_codes"]),
        "reading_level_metric": j["reading_level_metric"],
    })
    return out


def contest_json(c):
    out = _common(c)
    q = helpers.questionnaire_of_contest(c["id"])
    if q is None:
        index = 0.0
    else:
        counters = questionnaire_counters(q)
        index = calc.completion_index(counters["submitted_count"],
                                      counters["invited_count"])
    out.update({
        "jurisdiction_id": c["jurisdiction_id"],
        "kind": c["kind"],
        "office_name": c["office_name"],
        "seat_count": c["seat_count"],
        "vote_for_count": c["vote_for_count"],
        "filing_deadline": fmt_dt(c["filing_deadline"]),
        "questionnaire_word_limit": c["questionnaire_word_limit"],
        "word_count_policy": c["word_count_policy"],
        "status": c["status"],
        "verified_candidate_count": verified_candidate_count(c),
        "completion_index": index,
    })
    return out


def filing_json(f):
    out = _common(f)
    out.update({
        "contest_id": f["contest_id"],
        "candidate_name": f["candidate_name"],
        "party_label": f["party_label"],
        "filing_reference": f["filing_reference"],
        "status": f["status"],
        "filed_at": fmt_dt(f["filed_at"]),
        "verified_at": fmt_dt(f["verified_at"]),
        "withdrawal_count": f["withdrawal_count"],
    })
    return out


def questionnaire_json(q):
    out = _common(q)
    counters = questionnaire_counters(q)
    out.update({
        "contest_id": q["contest_id"],
        "due_at": fmt_dt(q["due_at"]),
        "questions": q["questions"],
        "status": q["status"],
        "invited_count": counters["invited_count"],
        "submitted_count": counters["submitted_count"],
        "nonresponse_count": counters["nonresponse_count"],
        "late_count": counters["late_count"],
    })
    return out


def response_json(r):
    out = _common(r)
    out.update({
        "questionnaire_id": r["questionnaire_id"],
        "filing_id": r["filing_id"],
        "answers": r["answers"],
        "status": r["status"],
        "submitted_at": fmt_dt(r["submitted_at"]),
        "per_answer_word_counts": r["per_answer_word_counts"],
        "over_limit_positions": r["over_limit_positions"],
        "published_indicator": PUBLISHED_INDICATOR[r["status"]],
    })
    return out


def measure_json(m):
    out = _common(m)
    pro, con = measure_totals(m)
    ratio, flag = calc.balance(pro, con)
    out.update({
        "contest_id": m["contest_id"],
        "measure_title": m["measure_title"],
        "official_text": m["official_text"],
        "explanation_text": m["explanation_text"],
        "drafter_volunteer_id": m["drafter_volunteer_id"],
        "status": m["status"],
        "review_round_count": m["review_round_count"],
        "approvals_this_round": m["approvals_this_round"],
        "pro_word_total": pro,
        "con_word_total": con,
        "balance_ratio": ratio,
        "balance_flag": flag,
        "grade_fk": m["grade_fk"],
        "grade_smog": m["grade_smog"],
    })
    return out


def argument_json(a):
    out = _common(a)
    out.update({
        "measure_id": a["measure_id"],
        "side": a["side"],
        "argument_text": a["argument_text"],
        "author_credit": a["author_credit"],
        "word_count": a["word_count"],
        "status": a["status"],
    })
    return out


def review_json(r):
    out = _common(r)
    out.update({
        "measure_id": r["measure_id"],
        "reviewer_volunteer_id": r["reviewer_volunteer_id"],
        "verdict": r["verdict"],
        "notes": r["notes"],
        "round_index": r["round_index"],
    })
    return out


def edition_json(e):
    out = _common(e)
    out.update({
        "cycle_id": e["cycle_id"],
        "language_code": e["language_code"],
        "channel": e["channel"],
        "accessibility_format": e["accessibility_format"],
        "status": e["status"],
        "snapshot_contest_ids": list(e["snapshot_contest_ids"]),
        "pinned_questionnaire_versions": dict(e["pinned_questionnaire_versions"]),
        "estimated_page_count": e["estimated_page_count"],
        "print_run_total": e["print_run_total"],
        "allocations": e["allocations"],
        "unallocated_copies": e["unallocated_copies"],
    })
    return out


def forum_json(f):
    out = _common(f)
    out.update({
        "contest_id": f["contest_id"],
        "scheduled_start": fmt_dt(f["scheduled_start"]),
        "scheduled_end": fmt_dt(f["scheduled_end"]),
        "moderator_volunteer_id": f["moderator_volunteer_id"],
        "status": f["status"],
        "eligible_candidate_count": f["eligible_candidate_count"],
        "minutes_text": f["minutes_text"],
    })
    return out


def question_json(q):
    out = _common(q)
    out.update({
        "forum_id": q["forum_id"],
        "question_text": q["question_text"],
        "source": q["source"],
        "author_volunteer_id": q["author_volunteer_id"],
        "status": q["status"],
    })
    return out


def volunteer_json(v):
    out = _common(v)
    out.update({
        "volunteer_name": v["volunteer_name"],
        "chapter_code": v["chapter_code"],
        "roles": list(v["roles"]),
        "advocacy_flag": v["advocacy_flag"],
        "attestation_status": ("CURRENT" if authz.attestation_current(v)
                               else "LAPSED"),
        "attestation_expires_at": fmt_dt(v["attestation_expires_at"]),
        "status": v["status"],
        "substantiated_incident_count": substantiated_incident_count(v),
    })
    return out


def incident_json(i):
    out = _common(i)
    out.update({
        "volunteer_id": i["volunteer_id"],
        "incident_type": i["incident_type"],
        "description": i["description"],
        "status": i["status"],
        "corrective_action": i["corrective_action"],
        "resolved_at": fmt_dt(i["resolved_at"]),
    })
    return out
