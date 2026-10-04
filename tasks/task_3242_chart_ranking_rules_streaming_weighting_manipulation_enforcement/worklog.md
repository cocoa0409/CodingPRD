# Worklog — task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement

## Step 1: Create Task Directory — 2026-09-30T13:30:00.000Z

Verified pre-allocated task directory `./tasks/task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement/` exists with `workspace/` inside (per command-args instruction; no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T13:56:00.000Z

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement/SCAFFOLD.yaml` — §1.0–§1.7 plus preamble
- `/home/ubuntu/github/CodingPRD/tasks/task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

## Counts

- **Endpoints: 67** (52 business/test-driving + 15 FK reverse-reachability GETs added during the §1.5 audit pass)
- **Entities: 14** (Chart, MethodologyVersion, ChartWeek, Provider, TitleProduct, LabelAccount, RecurrentRule, ConsumptionReport, SaleBatch, ManipulationSignal, Investigation, ChartEntry, GenreDispute, ChartFreeze)
- **§1.8 instances: 18** (all nine rules × 2 instances each, all differentiation clauses honored — e.g. dual-variant calcs span chart-points vs album-unit domains; combinatorial instances hit modes (a) and (c); cascades trigger from investigation-resolve vs dispute-resolve; priority conflicts use state-vs-temporal and safety-vs-fiscal pairs)
- **§1.9 instances: 49** (40 full test recipes + 9 `excluded_because` stubs citing §1.8 instances)
- Errors: 24; roles: 6 (segregation-of-duties model: ChartOps files/escalates but only an assigned Investigator resolves); state machines: 10; calculations: 3

## Difficulty escalation ("harder than expert")

Beyond the expert band's structural counts, the scaffold layers: a compliance/audit archetype with segregation of duties; OCC on Chart for activation and freeze writes; a 4-hop enforcement cascade (investigation → title disqualification → entry removal + report exclusion → label strike → label suspension); a methodology freeze/supersession diamond that invalidates computed weeks; holiday-adjusted reporting cutoffs with half-open boundary precision; per-buyer waterfall cap allocation with pinned evaluation order; and TEA-vs-SEA dual-variant points arithmetic with floor-before-weighting (fixtures computed: 515.4000 vs 510.4000 on identical inputs).

## Constraint confirmations

- SCAFFOLD.yaml contains **neither** `scaffold_difficulty_design` nor `scaffold_corner_design` keys (verified programmatically).
- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (705 calls scanned; OCC version inputs all `${var}`-bound; all names unique across the union of both design files.)
- No sibling task directories were read at any point; the scaffold was derived solely from the scenario text and the skill spec.
- One deliberate deviation to note: `api_prefix` is `""` (empty) because the lint's FK reverse-reachability check requires endpoint paths to begin with the declared prefix; paths are written in natural root form (e.g. `/charts/{id}/weeks`) consistently across all three files.

## Step 3: Copy Shared Files — 2026-09-30T13:57:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T14:05:00.000Z

- **Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement/workspace/PRD.md` — 278 lines, 17 section headers (§1 Introduction; §2.1–2.9; §3.1–3.7; §4 endpoint table with 68 rows; §5 error catalogue with 24 rows). Written incrementally across 8 append calls; tail verified non-truncated.
- **Withheld files**: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + endpoint input/query/path identifiers: 80 required, 80 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: expressed as explicit ordered list in §2.8
- concurrency_rules[] OCC: 2 checked, 2 expressed (expected_chart_version + ERR_STALE_VERSION 412 named for activate and freeze)
- state_machines[].transitions: all 10 machines expressed (methodology DRAFT/ACTIVE/FROZEN/SUPERSEDED incl. both freeze-resolution branches; week OPEN→LOCKED→COMPUTED→PUBLISHED + holiday self-loop; report triage + system REJECTED/EXCLUDED; signal/sale-batch/investigation/entry/dispute/label/title transitions with preconditions and side effects)
- calculations[]: 3 checked, 3 expressed (chart_points both SINGLES/ALBUMS-TEA variants with floor-before-weighting and round-half-up final-only; countable_album_units waterfall with cap 4, created_at ASC + quantity ASC tie-break, exact-multiple edge case, SALES-report uncapped variant; recurrent weeks/peak/removal/re-entry with provisional vs final variant)
- validations[] conditions: 24 checked, 24 matchable to error_id in §2/§3 prose
- endpoints[].side_effects / applies_to: expressed (freeze gate's 5-endpoint scope, accept guards, escalation cascades per signal_kind, finding cascades, re-entry cascade)
- entities[].fields[] structured content: defaults/initials covered (DRAFT, OPEN, RECEIVED, CLEARED, ACTIVE, ELIGIBLE, FILED, strike_count 0, holiday_adjusted false, reentries_processed false)
- sibling-branch symmetry: freeze-resolution FROZEN→ACTIVE vs FROZEN→SUPERSEDED, and all three investigation findings rendered at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 387
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-09-30T14:30:00.000Z

**Task:** task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement — generated complete test infrastructure and test suite.

**test_helpers/ (9 files):** `__init__.py` (barrel export of framework + PRD-specific), `types.py` (all 13 entities, status enums, role enum), `api_client.py` (`ApiClient(GenericApiClient)` with one method per PRD endpoint, including all reverse-reachability listings), `api_errors.py` (all 24 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `constants.py` (cap 4, price floor 300, canonical methodology from the PRD narrative), `test_users.py` (shared constants + per-instance builders for entity-backed `DataProvider`/`LabelRep` and opaque-role identity control), `factories.py`, `fixtures.py` (composite builders: `setup_open_week_scenario`, `setup_locked_week_with_sales`, `setup_chart_with_active_methodology`, freeze/escalate/resolve/disqualify helpers, identity-threaded LabelRep/DataProvider headers).

**test_suite/ (8 files, 80 tests):** `test_01_chart_points_and_caps.py` (12), `test_02_methodology_and_freeze.py` (13), `test_03_weekly_cycle.py` (17), `test_04_manipulation_enforcement.py` (13), `test_05_disputes_providers_rbac.py` (14), `test_06_freeze_priority.py` (2), `test_07_enforcement_extra.py` (2), plus `conftest.py`.

**Coverage audit:**
- Queue A (§1.8 difficulty): all 18 instances have ≥2 tests each — 36 tests total.
- Queue B (§1.9 corner): all 33 non-stub instances have ≥1 test — 44 tests total. The 9 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.
- No skipped instances: every instance passed the PRD-first two-condition filter (the PRD carries all asserted rules verbatim, including the validation-priority ordering in §2.8 and error statuses).
- Verbatim-citation audit: all 80 docstrings contain a ≥6-word quote surviving literal `grep` against PRD.md; every docstring ends with exactly one `Design:` tag resolving to a real instance; no bogus or duplicate-free tags.
- Checks: all files `py_compile` clean; `pytest --collect-only` collects 80 tests with no errors.

**Note on process:** an initial docstring-normalization script over-mangled citations; I repaired it in place (the task dir is untracked) and re-verified with the audit above — final state passes all three sweeps. No instances were skipped.

(Orchestrator verification: 9 test_helpers files + 7 test files + conftest confirmed on disk; `grep -c "def test_"` totals exactly 80 across test_suite/.)

## Step 6: Generate Implementation — 2026-09-30T14:45:00.000Z

The full pipeline works end-to-end: chart creation, methodology activation (with OCC), week creation, lock, compute, publish. Isolation rule honored — I read only INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md, and did not run the test suite.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement/workspace/implementation/`):

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 11 | Foreground launcher with guarded pip install |
| `requirements.txt` | 1 | Flask dependency |
| `app.py` | 53 | Flask app, error handlers, blueprint registration |
| `db.py` | 25 | In-memory store (empty at boot) |
| `errors.py` | 131 | Error ID constants + `ApiError` |
| `helpers.py` | 180 | Clock, UUIDs, ISO-8601 w/ 3-digit ms, envelope, pagination, auth |
| `services.py` | 575 | Serializers, cascades, points calc, per-buyer cap allocation, eligibility gates |
| `routes/__init__.py` | 0 | Package marker |
| `routes/charts.py` | 632 | Charts, methodology versions, weeks, freezes, recurrent rules, clock |
| `routes/providers.py` | 238 | Providers, consumption reports, report review actions |
| `routes/labels.py` | 90 | Label accounts, reinstatement, label-scoped listings |
| `routes/titles.py` | 246 | Title products, sale batches, title-centric reverse lookups |
| `routes/enforcement.py` | 346 | Manipulation signals, investigations, finding cascades |
| `routes/misc.py` | 177 | Genre disputes, reclassification cascade, chart dispute listing |

**Total**: ~2,700 lines.

**Endpoint count**: 57 endpoints implemented (all 57 from the SCAFFOLD endpoint table). [Orchestrator note: independent grep of route decorators on disk finds 67 registrations, matching the scaffold's 67 endpoints — the subagent's "57" appears to be a miscount of its own route table.]

**Verification**:
- `python3 -m py_compile` on all 12 Python files: OK
- `start.sh` present and executable (`chmod +x` applied)
- Smoke boot on port 18123: server booted, `POST /_clock/set_current_utc` returned correct envelope, empty `GET /charts` returned proper pagination metadata
- End-to-end smoke flow on port 18124: recurrent rule → chart (with rule FK) → methodology version → activate (OCC `expected_chart_version=1` succeeded, chart version bumped to 2, MV became ACTIVE) → week → clock advance → lock → compute → publish — all returned 200/201 with expected state transitions

**Key fidelity notes**:
- Envelope: `{meta:{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}, response_type, data}` — matches scaffold
- Logical clock starts at `2026-09-01T00:00:00Z`, never wall-clock
- Points calc uses `Decimal` with round-half-up at the final step only, integer floor per component before weighting; TEA conversion only on `ALBUMS` chart + `ALBUM` title; ad-supported streams excluded from album points
- Per-buyer cap allocation: 4 units/buyer/week, fill-in-order by `created_at ASC, _seq, quantity ASC`, with re-allocation after escalation/dismissal cycles
- Validation order followed: auth → RBAC/ownership → existence → OCC → freeze gate → state → standing → temporal → business → duty segregation → posture → fiscal
- Publish-time entry status recorded on the entry so subsequent `weeks_on_chart` counts exclude entries that were `RECURRENT_REMOVED` at their own publish
- No seeding at startup; store starts empty

**Isolation rule honored**: I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/`, and did not run the test suite.

**Process safety**: Only the two PIDs I started (`$!` captured) were killed; no `pkill`/`killall`/`pgrep|xargs kill` used.

## Step 7: Run Tests and Iterate — 2026-09-30T14:57:00.000Z

All 8 rounds pass 80/80. Clean sweep achieved. (Orchestrator verified on disk: all 8 `results.{1..8}.json` files present, each `passed: 80, failed: 0, total: 80, errors: 0`.)

**Iterations run:** 3 (initial sweep + 2 fix-sweeps)

**Tests deleted:** none — all three failures were test-artifact bugs; every asserted rule traces verbatim to PRD.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_03_weekly_cycle.py` — `test_recurrent_sweep_removes_overstay_entry`: changed `create_recurrent_rule(..., max_weeks=1, ...)` to `max_weeks=2` (and updated the inline assert message). Why: with `max_weeks=1` the loser entry is already swept at week 1, so its week-1 publish (status `RECURRENT_REMOVED`) is excluded from the week-2 `weeks_on_chart` count per PRD §3.5 ("count of published entries ... whose own publish-time status was not `RECURRENT_REMOVED` ... plus one"), yielding 1, not the asserted 2. The implementation was PRD-correct; `max_weeks=2` restores the intended "overstay at week 2" scenario with all original assertions intact.

2. `test_suite/test_04_manipulation_enforcement.py` — `test_disqualify_cascade_depth`: added missing `create_week` to the top-level `test_helpers` import (was `NameError`).

3. Same file — `test_publish_rejected_when_entry_title_disqualified`: (a) added missing `get_week` import; (b) re-anchored the disqualification signal from a second week of the *same* chart to a week of a *different* chart. Why: PRD §3.6's enforcement cascades invalidate `COMPUTED` weeks of the signal's chart back to `LOCKED` ("any week of the chart in `COMPUTED` status is invalidated back to `LOCKED`"), so w1 legitimately left `COMPUTED` and publish surfaced `ERR_INVALID_STATE` before the `ERR_TITLE_DISQUALIFIED` gate — the setup could never exercise the gate it asserts. Filing the signal on another chart's week leaves w1 `COMPUTED`, letting the PRD §3.5 publish gate fire as the test intends.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in all three cases.

**Final state:** 8/8 parallel rounds, 80/80 passed each, zero flakiness.

## Step 8: Finalize PRD — 2026-09-30T14:59:00.000Z

Done. No edits were warranted — all three Step 7 items trace to behavior the PRD already pins verbatim, and the implementation was confirmed PRD-faithful at every site involved.

**File stats:** PRD.md and PRD_FINALIZED.md are both 278 lines, 0% delta, byte-identical (md5 `abb4631e2f6dc46f9318757d7c9f55b3` — orchestrator re-verified on disk). PRD_FINALIZED.md is a pure copy at `/home/ubuntu/github/CodingPRD/tasks/task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement/workspace/PRD_FINALIZED.md`.

**Per-item verification (why no patch was made):**

1. **Recurrent sweep / `weeks_on_chart` counting** — `prior_published_count` at `implementation/services.py:542-559` excludes published entries whose `publish_status == "RECURRENT_REMOVED"` and counts weeks with smaller `week_index`; publish stores `prior + 1` at `routes/charts.py:478-479`. This is exactly PRD §3.5's sentence "the count of published entries ... whose own publish-time status was not `RECURRENT_REMOVED`, over weeks with a smaller `week_index`, plus one for the current entry". The `max_weeks=1` test failure was a pure fixture bug; PRD already determines the behavior.

2. **Missing `create_week` import in the test** — pure test-artifact bug (`NameError`), no behavioral content. Nothing to pin.

3. **Enforcement cascade invalidation vs. publish gate** — `resolve_investigation` calls `invalidate_computed_weeks(chart_id)` for both `QUARANTINE_REPORTS` and `DISQUALIFY` (`routes/enforcement.py:273,310`); the helper (`services.py:378-389`) resets *every* `COMPUTED` week of the signal's chart to `LOCKED`. PRD §3.6 states "any week of the chart in `COMPUTED` status is invalidated back to `LOCKED`" — chart-scoped wording that fully covers the impl. The original test setup (signal on the same chart's week) therefore legitimately surfaced `ERR_INVALID_STATE` before the `ERR_TITLE_DISQUALIFIED` publish gate; re-anchoring the signal to another chart's week was the correct test fix. PRD already determines both behaviors.

**NO-NEW-MISMATCH check (performed even though no edit landed):** I also verified the one PRD phrase that is looser than the impl — §3.6's "affected COMPUTED weeks" and "Any report moved `ACCEPTED → EXCLUDED` by an investigation also invalidates computed weeks of its chart" — against all `invalidate_computed_weeks` callsites (methodology activation, freeze resolution, `QUARANTINE_REPORTS`, `DISQUALIFY`). The impl invalidates chart-wide in every case, including cross-week COMPUTED weeks untouched by the signal; since this is the union of what the loose phrases permit and the cascade sentence pins, any tightening edit I could have made risked introducing a false claim, and none was needed. No wording change was committed.

## Step 9: Complete PRD — 2026-09-30T15:13:00.000Z

All edits landed. The file is complete and non-truncated (279 lines, ends with the full error catalogue).

**Source:** `PRD_FINALIZED.md` (byte-identical to `PRD.md`) → `PRD_COMPLETED.md`
**Line counts:** 278 → 279 (+1 line from the added `ERR_VALIDATION` catalogue row); **char delta:** 43,366 → 48,606 (+5,240 chars).
**Counts:** 19 ambiguity-pins (inserts), 2 mismatch-revisions.

Changes (section — insert/revise — ambiguity/mismatch — what changed — impl reference):

- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, out of 1–100, negative) rejected with `ERR_VALIDATION` HTTP 400; list tie-break is server creation sequence — helpers.py:125–156
- §2.4 — insert — ambiguity — payload timestamps normalized to canonical ISO-3ms on storage — helpers.py:49–61, routes/charts.py:145
- §2.4 — insert — ambiguity — uniqueness constraints (chart_code, rule_code, provider_code, account_code, upc, week_index per chart) and field-shape violations rejected with `ERR_VALIDATION` HTTP 422 — routes/charts.py:89,320,599; providers.py:43; labels.py:36; titles.py:55,62,72
- §2.8 — insert — ambiguity — uniqueness checks listed among business-constraint step — routes/charts.py:87–89,318–320
- §2.8 — insert — ambiguity — multi-identifier payload lookups surface in payload-field order; catalogue pins only step-level ordering — providers.py:115–120
- §3.1 — insert — ambiguity — chart creation with unresolvable `recurrent_rule_id` is `ERR_NOT_FOUND`; chart list accepts `current_methodology_version_id` filter — routes/charts.py:82–84,117–120
- §3.2 — revise — mismatch — activation accepts only `DRAFT` revisions (non-DRAFT, incl. FROZEN, is `ERR_INVALID_STATE`); `effective_from` null also `ERR_INVALID_STATE` — routes/charts.py:193–196
- §3.2 — insert — ambiguity — repeated freezes mint additional `ACTIVE` freezes without error — routes/charts.py:206–231
- §3.2 — insert — ambiguity — freeze resource carries `expected_chart_version` echoing the creation payload — routes/charts.py:225, services.py:255
- §3.3 — insert — ambiguity — report submission: unresolvable `title_product_id`/`chart_week_id` is `ERR_NOT_FOUND`; week need not be `OPEN` at submit; suspended provider's RECEIVED reports remain triageable (only acceptance checks standing) — providers.py:104–158, 195–197
- §3.3 — insert — ambiguity — acceptance leaves stored `review_reason` untouched; quarantine/reject are not freeze-gated — providers.py:168–203
- §3.4 — insert — ambiguity — LabelRep batch ownership check (`ERR_UNAUTHORIZED`); unresolvable `chart_week_id` is `ERR_NOT_FOUND`; no week-OPEN gate at batch recording — titles.py:131–168
- §3.4 — insert — ambiguity — only `UNDER_REVIEW` batches are moved to `REJECTED` by quarantine/disqualify findings — enforcement.py:264–272, 294–302
- §3.5 — insert — ambiguity — lock requires week `OPEN` (else `ERR_INVALID_STATE`) — routes/charts.py:364–365
- §3.5 — insert — ambiguity — compute requires week `LOCKED` (else `ERR_INVALID_STATE`) — routes/charts.py:388–389
- §3.5 — insert — ambiguity — publish requires week `COMPUTED`; pinned-methodology drift is `ERR_INVALID_STATE` — routes/charts.py:455–458
- §3.5 — insert — mismatch-avoidance pin — recurrent sweep at publish is removal-only; re-entry occurs only via the §3.7 reclassification cascade — routes/charts.py:487–502
- §3.6 — revise — ambiguity — holiday-adjust on a non-OPEN week is `ERR_HOLIDAY_WINDOW_INVALID` (not `ERR_INVALID_STATE`) — routes/charts.py:511–512
- §3.6 — insert — ambiguity — escalate requires signal `OPEN`, checked first (`ERR_INVALID_STATE`); "three guards" → "four guards" — enforcement.py:102–103
- §3.6 — insert — ambiguity — TICKET_BUNDLE_ABUSE moves bundle batches to `UNDER_REVIEW` as audit trail despite zero countable units — enforcement.py:142–152
- §3.6 — insert — ambiguity — investigation resolution closes `OPEN → CLOSED`; invalid `finding` is `ERR_VALIDATION` 422 — enforcement.py:213–227
- §3.7 — insert — ambiguity — dispute filing resolves the three payload identifiers first (`ERR_NOT_FOUND`) before ownership/validity — misc.py:39–47
- §3.7 — insert — ambiguity — invalid dispute `resolution` is `ERR_VALIDATION` 422 — misc.py:119–120
- §3.7 — revise — mismatch — reclassification cascade skips the release-date gate (re-entrant, `first_entry=False`); final sentence no longer implies publish-time re-entry evaluation — misc.py:156–161
- §4 preamble — insert — ambiguity — escalate returns 201 (creates Investigation); three methodology reverse-lookups return unpaginated arrays; read endpoints have no ownership restriction; enumerated all list-endpoint query filters — enforcement.py:166; routes/charts.py:557–585; titles.py:95–104 etc.
- §4 table — revise — mismatch — activate endpoint description: "DRAFT methodology version" (was "DRAFT or FROZEN") — routes/charts.py:193
- §5 — insert — ambiguity — added `ERR_VALIDATION` row (400 for pagination, 422 for field-shape/uniqueness) — helpers.py:135 and field checks above

Output file verified on disk: `/home/ubuntu/github/CodingPRD/tasks/task_3242_chart_ranking_rules_streaming_weighting_manipulation_enforcement/workspace/PRD_COMPLETED.md` (279 lines, ends with the complete §5 error table, non-truncated). (Orchestrator re-verified: 279 lines, 48,606 chars; `ERR_VALIDATION` row present at line 257; tail intact.)
