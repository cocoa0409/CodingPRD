# Worklog — task_2111_union_grievance_arbitration

## Step 1: Create task directory — 2026-08-16T00:00:00.000Z

Created `tasks/task_2111_union_grievance_arbitration/` and `tasks/task_2111_union_grievance_arbitration/workspace/`. Index 2111 chosen as max(2110)+1 under `./tasks/`.

## Step 3: Copy shared files — 2026-08-16T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2111_union_grievance_arbitration/workspace/INSTRUCTION.md` (1424 bytes). Run out of order relative to Step 2 (no dependency); Step 2 scaffold generation was in flight.

## Step 2: Generate scaffold — 2026-08-16T00:00:00.000Z

All three artifacts are written and pass the skill's own linter cleanly.

## Files

| Path | Lines |
|---|---|
| `.../task_2111_union_grievance_arbitration/SCAFFOLD.yaml` | 2,969 |
| `.../task_2111_union_grievance_arbitration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2,614 |
| `.../task_2111_union_grievance_arbitration/SCAFFOLD_CORNER_DESIGN.yaml` | 9,476 |

`SCAFFOLD.yaml` carries only §1.0–§1.7 keys; the two design keys are the sole top-level key of their own files.

## Scaffold surface (§1.1–§1.7)

13 entities · 8 state machines / 53 transitions · 2 OCC concurrency rules · 10 calculations · 41 ordered validations · 48 endpoints · 57 error codes · 6 roles.

Profile: `compliance_audit` × `multi_party_negotiation`, **flat** topology, **cyclic** machine shape, **segregation_of_duties** role model, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / selector_policy`. `api_prefix: /labor-relations`, logical clock defaulting to `2026-08-01T00:00:00Z`.

Difficulty carriers, all mechanically grounded:
- **Two independent state dimensions on one row** — `ArbitrationDemand.status` × `prep_status`, which gate each other at award time; `Grievance.status` is a true 4-node cycle (ANSWERED→APPEALED→STEP_MEETING_SCHEDULED→AWAITING_RESPONSE), `SettlementOffer` a second cycle via COUNTER.
- **Pinned evaluation orders** — settlement exposure (multiplier → clause cap → tier → precedent escalation), cost allocation (share tier keyed on *base* total, never on the admin-fee-inclusive grand total), witness release (quarter-hour + money rounding per assignment, then sum), award interest (on the post-fraction, pre-mitigation figure).
- **Two dual-variant calcs on different entities** — estimated vs actual arbitration cost (ArbitrationDemand), gross vs net remedy (Award).
- **Two interval geometries** — arbitrator hearings are closed intervals expanded by a travel buffer (touching = conflict); witness slots are half-open with no buffer plus an aggregate 10-hour daily cap.
- **Ordered-precedence derived posture** — `timeliness_state` with BARRED > UNION_DEFAULT > EMPLOYER_DEFAULT > TOLLED.
- **Deterministic selector** — panel ranking `active_case_count ASC, per_diem_cents ASC, created_at ASC`; no `id` participates in any ordering, tie-break or allocation anywhere in the scaffold.

## Design files

- **§1.8**: 9 rule_ids × 2 = **18 instances**, every one with a full structured `setup_api_calls` chain (some 40+ calls) and literal assertions computed by executing the §1.3 formulas (e.g. `estimated_cost_cents == 863250` vs `actual_cost_cents == 400000`; `gross 255141 / net 165141`; `total 1384800 = 240000 + 1144800`).
- **§1.9**: **9 sections, 78 instances** (63 with recipes, 15 `excluded_because` stubs pointing at named §1.8 instances).

## Verification

`scaffold_lint.py` verdict, pasted verbatim from a clean first-and-final run:

```
Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1371

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

I also ran an additional audit script (not part of the skill) confirming: all 96 `grounds` refs resolve into §1.1–§1.7; zero unbound `${var}` across 1,371 calls; instance names unique across both files; every one of the 57 error codes is bound to a §1.4 row or OCC rule *and* referenced in a design instance; every endpoint role is declared in §1.7; both OCC rules satisfy the §1.2.1 contract; and none of the forbidden concurrency vocabulary appears.

One §1.5 addition was made through the priority ladder: `PATCH /labor-relations/arbitrators/{id}` (roster maintenance), because `ERR_ARBITRATOR_INACTIVE` was otherwise unreachable after selection.

Note: `worklog.md` and `workspace/INSTRUCTION.md` already existed in the directory from the pipeline's Step 1/Step 3 and were left untouched. Per your constraint, no sibling task under `tasks/` or `tasks-batch-*/` was read.

## Step 4: Generate PRD — 2026-08-16T00:00:00.000Z

## Output

`workspace/PRD.md` — 468 lines, ~14,100 words, 101 KB. Written in seven appends (title/§1/§2.1–2.2, §2.3–2.9, §2.10–2.11, §3.1–3.3, §3.4–3.6, §3.7–3.9, §4+§5 generated programmatically from the scaffold) so no section was lost to output-length pressure.

## Section list

- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Money, Hours and Rounding · 2.7 Optimistic Concurrency on the Grievance Record · 2.8 Cascade Discipline and Version Semantics · 2.9 Nested Resource Retrieval · 2.10 Order of Evaluation and Error Precedence · 2.11 Segregation of Duties
- §3 Business Logic — 3.1 Standing Up an Agreement, a Roster and a Precedent Library · 3.2 Grievance Intake and the Filing Window · 3.3 The Step Ladder and the Timeliness Posture · 3.4 Settlement Offers, Precedent Review and the Authority Ladder · 3.5 Withdrawal, Consolidation and the Terminal Cascade · 3.6 Demanding Arbitration, Issuing the Panel and the Alternate Strike · 3.7 Building the Case File and Coordinating Witnesses · 3.8 The Hearing, the Award and Remedy Implementation · 3.9 The Case Cost Ledger, Allocation and Trend Analysis
- §4 Endpoint Definitions (4 columns) · §5 Error Code Catalogue (2 columns). Document ends at §5 — no audit footer.

## Mechanical coverage verification (found / expected)

| Item | Expected | Found |
|---|---|---|
| Entities (all `fields[].name` in backticks) | 13 / 149 field names | 13 / 149, 0 missing |
| State transitions | 53 across 8 machines | 53 audited from/to + preconditions + side effects, 0 missing |
| State enumeration values | 45 | 45, 0 missing |
| Enum-type field values | 104 | 104, 0 missing |
| Concurrency rules | 2 | 2 (both name write op + `expected_grievance_version` + `ERR_STALE_GRIEVANCE_VERSION` + 412) |
| Calculations | 10 | 10 fully expressed; all 24 named constants embedded in prose (verified individually) |
| Validations | 41 | 41 as an explicit ordered precedence ladder in §2.10, each paired with its error ID |
| Endpoints | 48 | 48 table rows |
| Error codes | 57 | 57 table rows; all 57 also referenced in §2/§3 prose |
| Roles | 6 | 6, each with its `identity:` translated (2 entity-backed, 4 opaque) |

Hard contracts: **Contract 1** field-name coverage — 149 entity fields / 97 body params / 23 query params / 1 path param, 0 missing (two passes). **Contract 2** rule coverage — priorities, OCC, cross-entity cascades, `applies_to` scopes, field defaults, sibling-branch symmetry all expressed. **Contract 3** §3 path purity — 929 backtick tokens scanned, 0 slash-prefixed, 0 bare HTTP methods, 0 method+path. §2.2 confirmed byte-identical to `section-2.2-response-structure.md`. Scans for fuzzy words ("approximately", "roughly", "conservatively") and pseudocode operators in §1–§3 returned zero hits.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

Orchestrator verification: `wc -l` = 468, `wc -c` = 101626, document terminates cleanly on the final `ERR_OVERPAYMENT` row of the §5 catalogue (no truncation).

## Step 6: Generate implementation — 2026-08-16T00:00:00.000Z

(Recorded before Step 5; Steps 5 and 6 ran concurrently and Step 6 returned first.)

Implementation complete and verified.

## Files written

`workspace/implementation/`

| File | Lines | Contents |
|---|---|---|
| `core.py` | 572 | In-memory store + logical clock, error catalogue (57 IDs → HTTP), envelope helpers, auth/RBAC, body validators, pagination, total-ordering helper |
| `derive.py` | 817 | All 10 calculations, derived read-time fields, enum tables, 13 serializers |
| `services.py` | 206 | Resource lookups (per-resource 404s), filing-steward/participant guards, cost-entry posting/voiding, arbitrator engage/release, terminal cascades |
| `routes_config.py` | 362 | Agreements, clauses, people, precedents, arbitrator roster, strike history, `/_clock/set_current_utc` |
| `routes_grievance.py` | 415 | Intake, step ladder (schedule/hold/respond), appeal, withdraw/consolidate, cost ledger |
| `routes_settlement.py` | 244 | Offer drafting, authority ladder, response cycle (ACCEPT/REJECT/COUNTER) |
| `routes_arbitration.py` | 619 | Demand, panel, alternate strike, hearing, prep filings, witnesses, award, implementation |
| `app.py` | 62 | Blueprint registration, error handlers, `0.0.0.0:$PORT` |
| `start.sh` | 13 | Guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=3.0.0` |

Total **3311** lines.

## Coverage

- **48 / 48 endpoints** implemented (verified by enumerating `url_map`; 47 under `/labor-relations` + `POST /_clock/set_current_utc`).
- Error precedence follows PRD §2.10 positions 1–41 literally in each handler (notably: OCC at 8 ahead of every state check at 9+; segregation of duties at 13 ahead of the authority ceiling at 39; `ERR_AWARD_STATE_INVALID` checked before `ERR_DEMAND_STATE_INVALID` on a second award).
- Both status dimensions on `ArbitrationDemand` (`status` / `prep_status`) are independent and gate each other.
- Calculation evaluation orders implemented as written: multiplier→cap→tier→precedent escalation; halving-then-ceiling before adding `extension_days`; split fraction before interest, mitigation/settlement offset after; sharing tier keyed on base total (never the grand total); per-assignment quarter-hour ceiling before summing.
- Two interval geometries kept distinct: half-open witness slots (touching does not conflict) vs. closed buffered arbitrator hearings expanded on both sides (touching does conflict).
- Timeliness posture uses the seven ordered branches with `BARRED` outranking `UNION_DEFAULT`, frozen once the grievance is terminal.
- Storage is Python dicts in `core.Store` only. An audit grep found no `sqlite`, `open(`, `json.dump`, `/tmp`, `seed_*`, or module-level store writes — the store is empty on every boot.

## Boot verification

`PORT=18211 bash start.sh` launched cleanly and answered HTTP within ~1s:
- `GET /labor-relations/employees` (authed) → `200` with the correct paginated envelope (`limit/offset/total_count/has_more` in `meta`, `response_type: "array"`, empty `data`).
- Same route unauthenticated → `401`.
- `POST /_clock/set_current_utc` → `200 {"current_utc":"2026-09-09T12:00:00.000Z"}`.
- `POST /labor-relations/bargaining-units` → `201` with all defaults and derived `status: "ACTIVE"`.

Process was then killed; port 18211 confirmed closed.

Three functional smoke suites (~200 assertions across intake windows, expedited halving, tolling, deemed-denied appeal and demand routes, UNION_DEFAULT/BARRED precedence, authority tiers incl. unauthorizable BOARD, segregation of duties, OCC 412, LAPSED cascade, offer expiry boundary, panel ranking/pool insufficiency, buffered hearing conflict, witness slot/cap rules, NO_SHOW cost void, zero-net auto-close, reinstatement, compliance dispute, consolidation analytics, cost allocation and void restoration) all pass with 0 failures.

One judgement call worth flagging: `limit`/`offset` outside their declared bounds return `ERR_INVALID_REQUEST` (400) rather than being clamped — PRD §2.3's "minimum/maximum **accepted** value" phrasing, with no clamping language anywhere.

## Step 5: Generate unit tests — 2026-08-16T00:00:00.000Z

Generation complete and audited. Summary:

## Files written

**`test_helpers/`** (1,875 lines)
| File | Lines | Contents |
|---|---|---|
| `types.py` | 494 | 13 entity TypedDicts + 25 enums; `PrecedentCase`/`PanelStrike` correctly omit `updated_at`/`version` (PRD §2.5) |
| `api_client.py` | 259 | `ApiClient(GenericApiClient)`, one method per PRD §4 endpoint incl. the un-prefixed `/_clock/set_current_utc` |
| `api_errors.py` | 150 | 57-member `ApiErrorId` + HTTP map, registered via `set_error_http_status_map` |
| `assertions.py` | 275 | Per-entity assertions, `assert_common_fields` / `assert_immutable_record_fields`, `parse_instant`/`assert_instant` (instant-equality, not string equality), `assert_cost_allocation`/`assert_cost_identity` |
| `factories.py` | 170 | 16 payload factories, input fields only |
| `constants.py` | 83 | Clock start, agreement/arbitrator defaults, settlement, cost, witness and arbitration constants |
| `test_users.py` | 60 | Opaque-role shared headers + `make_steward_headers`/`make_grievant_headers` builders for the two `entity_backed:Employee` roles |
| `fixtures.py` | 542 | 6 tiers: clock/creates → `setup_base` → grievances → step ladder (`run_step`, `advance_to_step3_answered`) → offers → arbitration (`setup_demanded_case`, `setup_selected_arbitrator_case`, `setup_hearing_scheduled_case`, `setup_award_ready_case`, `setup_split_award_case`) → witnesses/cost ledger |
| `__init__.py` | 42 | Barrel export |

**`test_suite/`** (5,146 lines): `conftest.py` + 11 domain-named files (`test_01_agreement_and_registry` … `test_11_access_control`).

## Coverage

- **141 test functions** (151 collected — one parametrized 11-way not-found family). Every test carries exactly one `Design:` tag.
- **Queue A (Difficulty): 18/18 instances emitted, 0 skipped**, 46 tests — every instance has >=2 (range 2–4).
- **Queue B (Corner): 63/63 non-stub instances emitted, 0 skipped**, 95 tests. All 15 `excluded_because` stubs verified to resolve to a real difficulty instance and produce no test.

## Audits run

- 216 PRD citations checked: **all survive a whitespace-normalized literal match against PRD.md**; every test has at least one >=8-word rule-bearing citation.
- No `skip`/`skipif`/`xfail`; no "scaffold"/§1.x references in generated code; pyflakes clean; pytest collection succeeds.

## One deliberate deviation

`Corner/entities/cost_entry_creation_defaults_origin_manual_and_status_posted` asserts `total_cost_cents == 13500 / employer 1000` for a single 12,500-cent UNION `FILING` entry. That contradicts PRD §3.9 ("the administrative fee is 800 basis points … of the **employer's base side**"), which uniquely derives 12,500 / 12,500 / 0 — the design's figure applies the 8% fee to a base with a zero employer side. The instance is still covered (origin `MANUAL`, status `POSTED`, `incurred_at`, null void fields, category filter), asserting the PRD-derived union share plus the allocation identity instead of the yaml's arithmetic. Worth flagging upstream as a corner-design bug.

## Step 7: Run tests and iterate — 2026-08-16T00:00:00.000Z

All 8 parallel rounds pass 151/151. Exiting clean.

## Summary

**Iterations run:** 2 (sweep 1 → diagnose/fix → sweep 2, all green).

**Sweep 1 result:** 148/151 passed in every one of the 8 rounds. The same 3 tests failed in all 8 rounds — no flakiness, a deterministic defect.

**Sweep 2 result:** 151/151 passed in all 8 rounds (~198s per round).

**Tests deleted:** None. No failing test was found to assert a rule on which the PRD is silent, and none collapsed under the unique-derivability check — all three failures shared a single upstream defect in `test_helpers`, exactly the pattern the triage hint warns about.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `file_grievance()`. The helper passed `ctx`'s four foreign keys positionally into `grievance_payload()` while also forwarding `**overrides`, so any caller supplying a foreign key by keyword crashed with `TypeError: grievance_payload() got multiple values for argument 'grievant_id'` before a request was ever issued. Fixed by having the four foreign keys default from `ctx` but be overridable by keyword (`overrides.pop(...)`). This is a test-layer bug, not an implementation bug: the tests were constructing a PRD-legitimate precondition — a second grievance in the same bargaining unit naming a *different* `grievant_id` (PRD §3.2 makes `grievant_id` a per-grievance foreign key, and §2.1 scopes a `Grievant`'s read to grievances whose `grievant_id` equals their `X-User-ID`) — and the helper simply could not express it.

**Fixes applied to `test_suite/`:** None.

**Fixes applied to `implementation/`:** None. The implementation passed all 151 assertions unchanged in both sweeps; no PRD-required check was removed or weakened, and no endpoint, field or side effect was added.

**On the flagged upstream note (PRD §3.9 administrative fee):** Applied the protocol from scratch rather than assuming either side. PRD §3.9 states verbatim that "the administrative fee is 800 basis points — eight percent — of the **employer's base side**, rounded half up." Every cost-allocation test is written to that figure and all pass against the implementation's `ADMIN_FEE_BPS = 800`. Independently verified across four scenarios in `test_10_case_costs_and_analytics.py` — e.g. base 490,000 → union 200,000, employer base 290,000, fee 23,200, total 513,200; base 6,300,000 → union 280,000 at the 7,000 bps tier, fee 481,600, total 6,781,600. PRD, tests and implementation agree; there was nothing to correct.

Orchestrator verification: re-read all 8 `results.{1..8}.json` — every round reports `passed=151 / total=151 / failed=0`.

## Step 8: Finalize PRD — 2026-08-16T00:00:00.000Z

`workspace/PRD_FINALIZED.md` is created and is **byte-identical to PRD.md** (468 lines vs 468 lines, 0% delta, same md5 `f261e73edcb9e3a21dd9d07270296a1d`).

## Changes

**None.** The single `<step_7_diff>` item is a pure test-layer defect with no PRD consequence.

The item is a Python keyword-argument collision inside `test_helpers/fixtures.py::file_grievance()` — it forwarded `ctx`'s four foreign keys positionally into `grievance_payload()` while also splatting `**overrides`, so any caller naming a foreign key by keyword raised `TypeError` before an HTTP request was ever issued. The three deterministic failures (`test_suite/test_11_access_control.py:140` and the two tests sharing `test_suite/test_07_hearing_and_case_file.py:217`'s `_two_demands_sharing_one_arbitrator` helper) never reached the server, so no implementation behavior was ever in question. Zero implementation fixes, zero test deletions, zero `test_suite/` fixes.

## Substantive check the item raises (the two subjects, verified against impl)

Both subjects the fixture repair unblocked turn out to be **uniquely determined by PRD.md already**, so patching would have injected new text with no PRD gap behind it.

**(a) `grievant_id` as a per-grievance foreign key on filing.** PRD §3.2 (line 211) names `grievant_id` in the intake payload as the aggrieved member; §2.10 rung 7 (line 151) requires it to resolve or yield the not-found error; §3.2 requires the grievant to belong to the named unit (`ERR_UNIT_MEMBERSHIP_MISMATCH`). `routes_grievance.py:35` (`req_id`), `:47` (`services.find_employee`), `:56-59` (membership test) and `:84` (stamped onto the record) match verbatim. Nothing in PRD or impl constrains one grievance per grievant or forbids two grievances in one unit naming different grievants — no uniqueness check exists anywhere in `implementation/`. The case-number ordinal for the second grievance is pinned by §3.2 and matches `routes_grievance.py:79-80` (`count of unit's grievances + 1`, zero-padded to four digits); since no path ever deletes a grievance, count+1 is identical to "position in ascending `created_at` order".

**(b) Grievant read scoping.** PRD §2.1 (line 22) and §2.10 rung 4 (line 148) both state the rule, and the §4 table pins the role list per endpoint: `Grievant` appears on `GET /grievances/{id}` and `GET /grievances/{id}/steps` only, and is absent from `GET /grievances`. Impl matches exactly: `routes_grievance.py:23` (`GRIEVANCE_READ_ROLES = READ_ROLES + (ROLE_GRIEVANT,)`), `:106-109` and `:190-193` (participant check after path resolution), `:113` (`list_grievances` authenticates `READ_ROLES` only, so a Grievant gets `ERR_ROLE_NOT_PERMITTED`), and `services.py:112-114` raising `ERR_NOT_CASE_PARTICIPANT` on `grievance["grievant_id"] != user_id`. Ladder order also matches: `core.py:325-338` yields 401 then 403, then `find_grievance` (rung 3), then the participant check (rung 4).

## Pre-edit search log

No edit was committed, so no wording had to be reconciled. The mandatory enumeration was still performed for each candidate subject before deciding not to edit:

- **Subject: `grievant_id` foreign key on grievance filing.** Paths enumerated/read: `routes_grievance.py:29-101` (intake), `:113-131` (`list_grievances`, `grievant_id` as a filter), `services.py:find_employee` / `find_grievance` / `require_case_participant`, plus a repo-wide grep for `grievant_id` across `implementation/*.py` (hits only in intake, the listing filter, and the participant check — no cascade, no analytics counter keyed on it; supervisor-side counters key on `respondent_supervisor_id`). Wording adjustment: none — no edit; PRD §3.2 + §2.10 rungs 7/17-18 already determine every enumerated path.
- **Subject: Grievant role read scoping.** Paths enumerated/grepped: `ROLE_GRIEVANT` and `ERR_NOT_CASE_PARTICIPANT` across all of `implementation/` (`core.py:26,34,70`, `routes_grievance.py:12,23,108,192`, `services.py:114`), `core.py:43-49` (`READ_ROLES` excludes Grievant, so every other read endpoint in `routes_config.py`, `routes_settlement.py`, `routes_arbitration.py` 403s a Grievant), and `core.py:325-338` (`authenticate`). Confirmed the Grievant appears on exactly the two endpoints §4 lists and that no serializer redacts fields by role (both Grievant-visible endpoints reuse the same `ser_grievance` / `ser_step`). Wording adjustment: none — no edit; PRD §2.1, §2.10 rung 4 and the §4 role column already determine all enumerated paths.

Also re-confirmed the note in the diff: PRD §3.9's 800-bps administrative fee matches `ADMIN_FEE_BPS = 800` in the implementation, so nothing was touched there either.

Orchestrator verification: `md5sum` + `diff -q` confirm PRD.md and PRD_FINALIZED.md are byte-identical.

## Step 9: Complete PRD — 2026-08-16T00:00:00.000Z

`workspace/PRD_COMPLETED.md` is written.

## Scale

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| Lines | 468 | 468 (unchanged) |
| Chars | 101,626 | 109,089 (**+7,463**) |
| Diff shape | — | 27 lines, all `NcN` in-paragraph substitutions; 0 lines added/removed, 0 new sections, headings and all 48+57 table rows byte-identical |

**Counts: 22 ambiguity-pins, 5 mismatch-revisions (27 total).**

## Changes

- **§2.2** — revise — mismatch — `api_request_timestamp` is the one value read from the host wall clock, not the logical clock of §2.4 (which claims nothing reads wall time); envelope metadata only, never compared against — `core.py:295`
- **§2.3** — revise — ambiguity — pagination bounds are **rejected, never clamped**: `limit`<1 or >100, `offset`<0, or a non-integer → `ERR_INVALID_REQUEST` 400; empty param = absent → default; `offset` past `total_count` returns an empty array, not an error; `has_more` = `offset` + rows returned < `total_count` — `core.py:523-549`, `core.py:309`
- **§2.3** — insert — ambiguity — what makes every ordering total: an implicit final tie-break on insertion order (created-earlier first), which also settles every ranking and single-row selection rule; filters are exact string equality, unvalidated against enums, empty = absent — `core.py:562-569`, `core.py:552-556`
- **§2.4** — revise — ambiguity — `to_iso8601` is mandatory and the clock is *set*, so it may move backwards; response is 200 with `data` holding only `current_utc` — `routes_config.py:356-362`
- **§2.5** — insert — ambiguity — every date-typed field (`hire_date`, `seniority_date`, `incident_date`, `discovery_date`, `decided_on`) is normalized to UTC and returned in the same full ISO-8601 three-fractional-digit form as `*_at`; valueless fields return explicit `null`, never omitted — `core.py:162-170`, `derive.py:567-817`
- **§2.8** — insert — ambiguity — one version increment per request, not per named consequence: a zero-net-remedy award that records *and* closes bumps the grievance by exactly 1; the demand's `HEARING_SCHEDULED`→`HEARD`→`AWARDED` walk bumps it by exactly 1 — `routes_arbitration.py:516-517,545-551`
- **§2.10 (rung 9)** — insert — ambiguity — sub-order when two state errors collide: step before grievance; `ERR_AWARD_STATE_INVALID` before `ERR_DEMAND_STATE_INVALID`; assignment before demand; withdrawing grievance's terminality before the survivor's — `routes_grievance.py:208-212,243-247,347-351`, `routes_arbitration.py:428-433,476-480`
- **§3.1** — insert — ambiguity — `cancellation_fee_cents` is mandatory at arbitrator registration and inert thereafter (never posted anywhere) — `routes_config.py:289`
- **§3.1** — insert — ambiguity — roster maintenance reads only its four fields; other body fields ignored, not rejected; `updated_at`/`version` refresh even on a no-op PATCH — `routes_config.py:318-338`
- **§3.2** — revise — mismatch — `case_number` ordinal is one greater than the count of grievances already filed under the unit (filing order), not a position in ascending `created_at`, and is never re-minted — `routes_grievance.py:78-87`
- **§3.2** — insert — ambiguity — `filed_by_steward_employee_id` is recorded verbatim, never resolved against the people registry — `routes_grievance.py:92`
- **§3.3** — revise — ambiguity — `granted_amount_cents` is itself optional, defaulting to 0; a `DENIED` step always reads 0 — `routes_grievance.py:237-241,255`
- **§3.3** — revise — ambiguity — a `GRANTED` answer runs the *full* §3.5 terminal cascade (offers voided, open steps cancelled, live demand → `SETTLED_PRE_HEARING` with arbitrator released), not just offer voiding — `routes_grievance.py:259-262`, `services.py:189-198`
- **§3.3** — insert — ambiguity — latest-step tie-break past `created_at` is insertion order; the step-3 record the arbitration deadline reads is selected the same way — `derive.py:218-231`
- **§3.3** — insert — ambiguity — `appeal_statement` is mandatory, validated non-empty, persisted nowhere — `routes_grievance.py:280`
- **§3.4** — insert — ambiguity — re-verification at authorization overwrites stored `exposure_cents` / `authority_tier` / `precedent_deviation_bps`; reads return stored figures, never recompute — `routes_settlement.py:41-46,160`
- **§3.4** — insert — ambiguity — `authorization_note` validated but persisted nowhere — `routes_settlement.py:142`
- **§3.4** — revise — ambiguity — `response_note` likewise unpersisted; `counter_back_pay_hours`/`counter_remedy_terms`/`counter_precedent_setting` defaults (0 / `NONE` / false) stated — `routes_settlement.py:208-211`
- **§3.4** — revise — mismatch — `ACCEPT` also settles a grievance sitting at `AWARDED`; no grievance-state test is applied beyond the terminality bar at drafting — `routes_settlement.py:228-233`
- **§3.4** — insert — ambiguity — the counter-created draft never carries a precedent (`precedent_case_id` and `precedent_deviation_bps` both null) and is priced from the counter terms at creation — `routes_settlement.py:240-242`
- **§3.5** — revise — ambiguity — consolidation-target errors and their order: missing → `ERR_GRIEVANCE_NOT_FOUND`; self / unit / clause mismatch → `ERR_INVALID_REQUEST` 400, all tested before either status; withdrawing grievance's terminality reported before the survivor's — `routes_grievance.py:332-351`
- **§3.6** — insert — ambiguity — on the overdue route the grievance's `arbitration_deadline_at` still derives null, so the timeliness test and `demand_deadline_at` read step-3 `response_due_at` + `arbitration_demand_days`, computed before the step is deemed denied — `routes_arbitration.py:82-90`
- **§3.7** — revise — ambiguity — `BRIEF`/`STIPULATION` read only the preparation dimension (no procedural gate) and never record `exhibit_count`; a stipulation without a confirmed witness also yields `ERR_DEMAND_STATE_INVALID` — `routes_arbitration.py:299-336`
- **§3.7** — insert — ambiguity — `slot_end_at` not strictly after `slot_start_at` → `ERR_INVALID_REQUEST` — `routes_arbitration.py:354-355`
- **§3.7** — insert — ambiguity — confirming a non-`INVITED` assignment or a wrongly-stated demand both give `ERR_DEMAND_STATE_INVALID` 409, assignment status first — `routes_arbitration.py:428-433`
- **§3.8** — insert × 4 — ambiguity — second-award check precedes the demand-status check; `interest_accrual_start` <= `issued_at` is enforced whenever supplied (even at rate 0, where it is still stored but yields 0 interest days); the no-show cascade void leaves `void_reason` null too; `reinstatement_effective_date` bumps the grievant's `updated_at`/`version` and is then discarded, stored nowhere — `routes_arbitration.py:470-484,533-535,595-597`
- **§3.8** — insert — ambiguity — implementation branches run completion → past-deadline → partial, and the past-deadline branch reads a *money* shortfall only: money-complete-but-reinstatement-outstanding past the deadline lands at `PARTIALLY_IMPLEMENTED` with no counsel charge. Plus: closure runs a reduced cascade (open offers voided; steps and demand untouched) — `routes_arbitration.py:599-617`, `services.py:201-206`
- **§3.9** — revise — ambiguity — cascade voids leave both `voided_by_user_id` and `void_reason` null — `routes_arbitration.py:535`, `services.py:137-142`

## Verification
- All 57 catalogue codes are raised by the implementation; no implementation-raised code is missing from the catalogue.
- All 48 routes match the endpoint table 1:1.
- All 41 ladder rungs, all 10 calculation orderings, both interval geometries, both concurrency rules and every optional-field default were walked; the residual gaps are the 27 above.
- `PRD.md` and `PRD_FINALIZED.md` are untouched (identical md5).

Orchestrator verification: `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 27 change hunks / 54 changed lines (27 out, 27 in), line count steady at 468, chars 101,626 → 109,089; `md5sum` confirms PRD.md and PRD_FINALIZED.md unmodified.

---

# PIPELINE COMPLETE — all 9 steps finished. Final state: 151/151 tests passing in all 8 parallel stability rounds under `--isolation per-test-server`.
