"""Entity serialization. Strips internal (underscore-prefixed) fields and
adds computed fields: CountryProgram.slots_remaining is a live aggregation,
and AlumniProfile's engagement indices / residency_status / follow_on_eligible
are recomputed on every read (PRD 3.9)."""

import domain


def _clean(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def cycle_out(cycle):
    return _clean(cycle)


def program_out(program):
    data = _clean(program)
    data["slots_remaining"] = domain.slots_remaining(program)
    return data


def applicant_out(applicant):
    return _clean(applicant)


def application_out(application):
    return _clean(application)


def score_out(score):
    return _clean(score)


def round_out(rnd):
    return _clean(rnd)


def grant_out(grant):
    return _clean(grant)


def visa_out(visa):
    return _clean(visa)


def ledger_out(ledger):
    return _clean(ledger)


def report_out(report):
    return _clean(report)


def incident_out(incident):
    return _clean(incident)


def alumni_out(profile):
    data = _clean(profile)
    data.update(domain.alumni_live_fields(profile))
    return data
