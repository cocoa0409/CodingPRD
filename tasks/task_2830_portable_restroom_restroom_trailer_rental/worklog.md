# Worklog — task_2830_portable_restroom_restroom_trailer_rental

## Step 1: Create task directory — 2026-09-05T03:18:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2830_portable_restroom_restroom_trailer_rental` and its `workspace/` subdirectory. Index 2830 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-05T04:48:00.000Z

All three scaffold artifacts for task 2830 are complete and lint-clean.

**Output files** (`/home/ubuntu/github/CodingPRD/tasks/task_2830_portable_restroom_restroom_trailer_rental/`):

| file | lines | bytes | top-level key |
|---|---|---|---|
| `SCAFFOLD.yaml` | 2476 | 125310 | §1.0–§1.7 only (neither design key present) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1789 | 122735 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3926 | 259333 | `scaffold_corner_design` |

**Lint verdict (final run, verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     49
  Calls scanned (§1.8+§1.9):  990

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Scaffold shape.** 13 entities, 53 endpoints (`api_prefix: ""`, flat topology), 8 state machines (cyclic shape; RentalContract is a parallel fulfillment/billing pair), 9 calculations (2 dual-variant), 24 validation priorities, 36 error ids, 7 roles under a `segregation_of_duties` role model, complexity layers `dual_variant_calculation` / `rate_threshold_triggers` / `cascading_side_effects` / `optimistic_concurrency`, `immediate` consistency, plus a `POST /_clock/set_current_utc` test-driving endpoint (startup default `2026-08-01T00:00:00Z`).

**§1.8:** 9 rule_ids × 2 = 18 instances, 310 calls.

**§1.9:** 75 instances across all nine claim-extraction-guide sections — entities 12, state_machines 15, calculations 12, validations 12, endpoints 5, errors 8, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. 49 carry full `test_recipe`s (680 calls); 26 are `excluded_because` stubs, every one citing a `difficulty_instance` that exists by name in the difficulty file, and none carrying a `test_recipe`. All names unique; all `claim_type` values are snake_cased guide row labels.

**Verified by hand, not just by lint:** every stub's cited difficulty instance resolves (18 names); every real instance has all four recipe sub-keys plus `distinguishing_aspect` and `grounds`; every numeric literal is derived from constants actually declared in §1.3 (quotes 91500 / 181500 / 14500, relocation 21275 / 41625 / 56194 / 97819, damage strike ladder 12800 / 12800 / 19200 / 25600, tip-over 27500, ADA total-loss 48000, missed credit 33746 and 67492 against the 60000 hold threshold, densities 35 / 65 / 100, manifest gallons 380 / 760); every §1.6 error id is triggered somewhere in §1.8 ∪ §1.9 (the twelve 404s swept in one instance, the two 412s in the OCC instances, the four header/identity codes in rbac, the rest in validations or stubbed to §1.8).

**Bugs found and fixed during generation** (all in §1.9, all mine): claim_types copied with spaces/hyphens from the guide; a precision assert referencing a relocation with no backing call; a TOTAL_LOSS retirement recipe that tried to retire an `IN_YARD` unit (no such transition — now activates first); captures of a non-existent `PlacementPermit.authority_decision_ref`; a ground citing a `pagination_with_filtering` layer this scaffold does not declare; and two list reads (`GET /service-sites`, `GET /rental-accounts`) that §1.5 simply does not declare — those two entities have single-row reads only, so the recipes now read by id.

**One thing for you to decide.** `SCAFFOLD.yaml`'s `scenario:` key opens with the literal line `Generate task harder than expert level!`, because the scenario description was embedded verbatim as instructed. That directive is a known leak path into `PRD.md` and normally gets stripped after Step 2 — I left it in place rather than deviate from the "verbatim, unmodified" constraint, so strip that single line before Step 3 if your pipeline hasn't already.

**Orchestrator post-step action (Step 2.5):** stripped the difficulty-directive leak. `sed -i '7,8d' SCAFFOLD.yaml` removed the `Generate task harder than expert level!` line plus its trailing blank line from the `scenario:` block; re-verified with `grep -c "harder than expert" SCAFFOLD.yaml` -> 0 and `yaml.safe_load` -> parses, 13 top-level keys intact. The directive appears in neither design yaml. SCAFFOLD.yaml now 125267 bytes.

## Step 3: Copy shared files — 2026-09-05T04:49:00.000Z

`cp /home/ubuntu/github/CodingPRD/INSTRUCTION.md .../workspace/INSTRUCTION.md` — 1424 bytes.

## Step 4: Generate PRD — 2026-09-05T05:02:00.000Z

PRD generated at `.../workspace/PRD.md` (463 lines, ~12.8k words), built incrementally with 8 chunked appends. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, and all sibling task directories were never opened.

## Structure (all planned sections verified present)

- **§1 Introduction** — 3 paragraphs (business-pain angle -> system scope -> the two shaping properties: integer cents with pinned rounding order, and a server-owned logical clock).
- **§2** — 11 domain-derived subsections: 2.1 Operating Roles and Request Identity, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Site Posture: The Gate Over Every Field Operation, 2.6 Money, Gallons and Rounding Discipline, 2.7 The Contract Ledger and Cascade Ordering, 2.8 Flat Collections and Reference Resolution, 2.9 Common Resource Properties, 2.10 Optimistic Concurrency Control, 2.11 Validation Precedence.
- **§3** — 9 subsections grouped by business-process timeline: standing up the branch -> permitting -> contracting/quote -> committing iron -> route density -> surge staging & missed service -> waste hauling -> charge adjudication -> reconciliation, escalation, closing.
- **§4** — 53-row table, exactly 4 columns. **§5** — 36-row table, exactly 2 columns.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 96 required, 96 present, 0 missing
- endpoints[].request_body/input: 81 required, 81 present, 0 missing
- endpoints[].query_params (folded into input): included above, 0 missing
- clock endpoint response keys (current_utc, expired_permit_count, blocked_site_count, suspended_schedule_count): 4 required, 4 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 25 checked, 25 expressed as an explicit numbered precedence list in §2.11, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_contract_version / expected_route_version + error_id + HTTP 412 all named), 0 missing
- state_machines[].transitions: 34 checked, 34 fully expressed (from/to, every precondition paired with its error_id, every side effect incl. the 4-hop permit-reject and 4-hop missed-credit cascades with causal attribution and created_at ASC ordering), 0 missing
- calculations[]: 11 checked, 11 fully expressed in prose with every constant embedded (250 person-hours, 12/10 peak factor, 9-hour shift, headcount floor 400, ADA divisor 20 with minimum 1, handwash divisor 4, all five term rates, all five damage bases, tip-over 27500, severity 40/75/100, strike 100/150/200, access 100/115/140/225, same-day 35, density tiers 40/12, 75/6, 100/0, per-visit class costs, credit 115, escalation 8.5/3.25/0 + 0/4.75/2.5/0 + 1.75 fuel, hold threshold 60000, buffer 20 min, revision cap 3, strike threshold 3, dispute window 14 days), 0 missing
- validations[] conditions: 25 checked, 25 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 53 endpoints checked, all side-effect sets and all applies_to scopes enumerated (posture BLOCKED = 4 operations, RESTRICTED = 3 with relocation exempt; disposal-closed on seal + accept; access-window and route-window on visit-create + rerun; billing hold on activate + invoice), 0 missing
- entities[].fields[] structured content: 96 checked, all defaults/initials/ranges/enum members/null-until semantics reconstructible; QuoteLine explicitly stated to lack updated_at and version, 0 missing
- sibling-branch symmetry: 9 groups checked (permit submit DRAFT vs REJECTED; approve vs reject; UPHELD from ASSESSED vs DISPUTED; WAIVED from ASSESSED vs DISPUTED; MISSED from PLANNED vs EN_ROUTE incl. the asymmetric schedule-ACTIVE guard; TERMINATED from ACTIVE vs SUSPENDED; INVOICED from UNBILLED vs REBILL_REQUIRED; unit_mix_quote provisional vs reconciled; density planned vs realized), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 826
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Other verifications
- §2.2 is byte-identical to `section-2.2-response-structure.md` (substring match confirmed, including `req_RANDOMALPHANUM123456` and `"data": { }`).
- Zero pseudocode operators (`>=`, `==`, `+=`, `floor(`, `ceil(`, `round(`, ...) anywhere in the file; zero fuzzy words (`approximately`, `roughly`, `conservatively`, `around`, `~`, ...).
- §3 contains no tables and no schema/field lists (0 table rows in the §3 span).
- Two judgement calls flagged for the record: (1) the relocate precondition "destination site belongs to the same account" carries no `error_id` in the scaffold, so it is expressed as falling under `ERR_INVALID_STATE_TRANSITION` (validations priority 20); (2) `schedule_units_on_route` is worded as "every non-superseded quote line, which in practice are the provisional lines," reconciling the calculation body (all non-superseded) with the field description (non-superseded PROVISIONAL) — the two are equivalent at schedule-creation time.

**Orchestrator truncation guard (mandated by the invoking command):** verified independently of the subagent's own report. `wc -l` -> 463; `grep -n '^#'` -> all 28 planned headings present in order through `## 5. Error Code Catalogue`; `tail -25` ends on the complete final table row `| ERR_DISPUTE_WINDOW_CLOSED | 409 |` — a real section boundary, not mid-sentence. Row counts confirmed: §5 has exactly 36 `ERR_` rows, §4 has 55 pipe lines = 53 endpoints + header + separator. Difficulty-directive leak check: `grep -ic "harder than expert" PRD.md` -> 0. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T05:32:00.000Z

(Launched concurrently with Step 5 in a single assistant message, per the skill's Concurrency requirement — this also gives the impl generator physical isolation from `test_suite/`, which did not exist when it started.)

Implementation complete, verified, and the smoke server is shut down.

## Location
`.../workspace/implementation/`

## Files written (2853 lines total, all pass `python3 -m py_compile`)

Launcher / infra
- `start.sh` (10, executable) — `cd "$(dirname "$0")"`, guarded `if ! python3 -c "import flask"` install, `exec python3 app.py`
- `requirements.txt` (1) — Flask
- `app.py` (62) — registers 11 blueprints, `ApiError` handler plus 404 / 405 / generic-exception envelope handlers, `app.run(host="0.0.0.0", port=$PORT or 10000, threaded=False, use_reloader=False)`

Foundation
- `clock.py` (59) — logical clock, default exactly `2026-08-01T00:00:00Z`, never wall clock
- `errors.py` (98) — 36-entry error catalog with HTTP statuses and default messages
- `responses.py` (59) — `meta`/`response_type`/`data` envelope, `req_` + 20 uppercase alnum request id, ISO-8601 3-decimal timestamps
- `db.py` (102) — in-memory `Store`, 13 empty dict collections, `insert`/`touch` (one `version` bump per row per request), `(created_at, _seq)` ordering, `serialize` strips internals
- `auth.py` (53) — `X-User-ID` / `X-User-Role`, 7 roles, `@endpoint([...])` RBAC decorator
- `validation.py` (212) — field/query coercion, uniqueness, ordering, pagination (limit 1..100 default 20, offset >= 0)
- `constants.py` (134) — rate cards, tier tables, enums, precedence lists
- `calculations.py` (184) — `Decimal` + ROUND_HALF_UP money, floor/ceil sizing, sequential (never collapsed) roundings
- `services.py` (435) — posture roll-up, 4-hop BLOCKED cascade, route/contract/account/manifest recomputes, strike recompute, permit expiry sweep

Routes (`routes/`, 53 endpoints)
- `common.py` (32), `accounts.py` (50), `sites.py` (73), `permits.py` (117), `refdata.py` (106: asset-units, disposal-sites, routes), `contracts.py` (276: quote/activate/demobilize/invoice/settle), `deployments.py` (132), `schedules.py` (86), `visits.py` (238), `manifests.py` (122), `charges.py` (183), `clock_api.py` (29)

## Verification
- `ls -la` clean; `__pycache__` removed so the delivered tree is source-only.
- 53 registered routes, matching PRD §4 exactly.
- No seeding/persistence: the only `seed`/`preload` hits are comments; no sqlite, no file I/O, no `json.dump`.

## Smoke test (PID 3429148 on `PORT=21437`, killed by exact PID, port confirmed closed)
Three scenarios over ~120 curl calls confirmed the envelope and error shapes per PRD §2.2 plus:
- Quotes: EVENT `906500`, CONSTRUCTION `159000`; invoice subtotal `999417` (per-line half-up at 10.25%); missed-service credit `55586` (`assessed_by_user_id: "SYSTEM"`, `source_visit_id` set); same-day GATED relocation `28721`; DAMAGE MODERATE trailer `292500`; strike multipliers `12800 / 12800 / 19200`; TIP_OVER `41250`.
- Cascades: permit rejection -> site `BLOCKED`, schedule `SUSPENDED`, route `committed_units 0 / density_planned_pct 0` with `density_realized_pct` preserved, 1 future visit `CANCELLED`. Strike 3 -> unit `IN_REPAIR`; waive -> strikes 2 and back to `IN_YARD`; `TOTAL_LOSS` -> unit `RETIRED`, deployment `RETURNED`, site `deployed_unit_count` 2 -> 1.
- Gates: `ERR_STALE_ROUTE_VERSION` 412, `ERR_UNIT_DOUBLE_BOOKED` 409, `ERR_DISPOSAL_CAP_EXCEEDED` / `ERR_DISPOSAL_CLASS_NOT_ACCEPTED` 422 with the exact-cap seal accepted at 200, `ERR_ACCOUNT_BILLING_HOLD` 402 on both invoice and activate, `ERR_ACCOUNT_SCOPE_VIOLATION` 403, `ERR_SEGREGATION_OF_DUTIES` 403, `ERR_PERMIT_REVISION_LIMIT` 409, `ERR_DISPUTE_WINDOW_CLOSED` 409 (open at exactly +14d, closed 1 ms later), `ERR_INVALID_REQUEST` 400 for bad `service_day` and out-of-range `limit`, plus 404/405 envelopes.
- Clock sweep returns `{expired_permit_count, blocked_site_count, suspended_schedule_count}`.

Two apparent failures during scenario 1 were script bugs, not implementation bugs (a hardcoded stale `expected_route_version`, and an empty shell variable producing `/service-visits//mark-missed`); both resolved in scenario 2.

## Step 5: Generate unit tests — 2026-09-05T06:32:00.000Z

(Launched concurrently with Step 6 in the same assistant message. Reported after Step 6 because it finished later; no ordering significance.)

Generation is complete. Both stages are written, audited and compiling.

## Files written (all at the TASK ROOT, nothing under `workspace/`)

`.../test_helpers/` — 9 files, 2639 lines
`types.py` 424, `api_errors.py` 87, `api_client.py` 334, `constants.py` 114, `test_users.py` 95, `factories.py` 384, `assertions.py` 439, `fixtures.py` 716, `__init__.py` 46

`.../test_suite/` — 11 files, 5704 lines, **87 tests**

| file | lines | tests |
|---|---|---|
| `conftest.py` | 57 | — |
| `test_01_accounts_sites_and_request_shape.py` | 671 | 11 |
| `test_02_permitting_and_site_posture.py` | 597 | 9 |
| `test_03_quoting_and_unit_mix.py` | 381 | 7 |
| `test_04_invoicing_and_contract_closeout.py` | 541 | 9 |
| `test_05_deployments_and_relocation.py` | 720 | 11 |
| `test_06_routes_schedules_and_visit_windows.py` | 662 | 10 |
| `test_07_missed_service_and_credits.py` | 359 | 7 |
| `test_08_waste_manifests_and_disposal.py` | 496 | 7 |
| `test_09_charges_and_adjudication.py` | 511 | 7 |
| `test_10_identity_concurrency_and_consistency.py` | 709 | 9 |

`ls -d` confirms both dirs at the task root; `workspace/test_helpers` and `workspace/test_suite` do not exist. `python3 -m py_compile` passes on all 20 .py files; `__pycache__` removed. Every fixture/api_client/factory/assertion symbol referenced by the suite was resolved by importing `test_helpers` and probing it (0 missing).

## Coverage — zero gaps, zero skips

**Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 18 instances, 18 covered, every one with >=2 tests.** Counts: `trailer_tier_boundary_at_headcount_400...` 3; all 17 others exactly 2. Nothing skipped, no `pytest.mark.skip/xfail` anywhere.

**Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 75 instances = 49 live + 26 `excluded_because:` stubs. All 49 live instances covered (>=1 test each); zero stubs tagged.** `demobilize_cascades_down_to_deployments_schedules_and_planned_visits` drew 2 tests, the other 48 one each. Section spread: entities 12, state_machines 9, calculations 5, validations 10, endpoints 3, errors 1, rbac 5, cross_cutting_complexity_layers 3, consistency_model 1.

**No instance from either queue was skipped** — the PRD-first two-condition filter passed on all 67 distinct instances that were in scope.

## Audits (scripted, `/tmp/task_2830_scratch/audit.py`)

- **PRD-citation pass: 237 quoted sentences, 237 found verbatim in `workspace/PRD.md`** after whitespace normalisation. The first run found 7 defects, all now fixed: six were cosmetic corruption of the source (five dropped `§` before a section reference, one dropped the `**` bold markers on "**Step four — restroom equivalents actually placed.**"); one, in `test_05_deployments_and_relocation.py`, was a genuine paraphrase — `"The account's billing_hold is then set to true when that balance is 60000 cents or more and false otherwise."` did not exist in the PRD and was replaced with the real §3.6 hop-four sentence.
- **Scaffold-citation pass: 87 tests, 87 with exactly one `Design:` line as the last line of the docstring, all 87 resolving to a real non-stub instance.** No untagged, dual-tagged, dangling or stub-pointing tags.

## One design/PRD contradiction, flagged not encoded

`Corner/consistency_model/every_derived_value_is_visible_in_the_same_response_or_the_next_read` pins `net_billable_cents == 181500` in the quote write response and `== 209000` (181500 + 27500) on the read after a tip-over. Both contradict PRD §2.7: "`net_billable_cents` is `invoice_subtotal_cents` plus `charge_debits_cents` minus `credit_accrued_cents`". Nothing has been invoiced at either point, so the PRD-derived values are **0** after the quote and **27500** after the charge. `test_10::test_09` asserts the PRD values (with an inline comment at each site explaining why), because a correct implementation would fail the design's numbers. `quoted_cents` is still asserted at 181500 and `amount_cents` at 27500, so the instance's real intent — same-response/next-read visibility of every derived field — is fully exercised. `test_03` and `test_04` already depend on the same PRD reading (`net_billable_cents == 0` after a quote), so the suite is internally consistent.

Fixture discipline held throughout: all money literals are integer-cent JSON numbers, all instant literals are full ISO-8601 instants with sub-second canonicalisation done in `api_client.canonical_instant` / `assert_instants_equal` rather than raw string equality. No broad `pkill` was ever issued and no server was started.

**Orchestrator post-step verification:** `ls -d test_helpers test_suite` -> both present at the task root; `ls workspace/` -> only `INSTRUCTION.md`, `PRD.md`, `implementation/` (no stray test dirs to move); test count re-counted independently at 87.

## Step 7: Run tests and iterate — 2026-09-05T06:43:00.000Z

**Iterations run:** 2 (iteration 1 diagnosed, iteration 2 verified clean).

**Final result:** all 8 parallel rounds pass **87/87**, 0 failed, 0 errors, 0 skipped, ~160s per round. Evidence left in place at `workspace/implementation/results.{1..8}.json`.

**Tests deleted:** none. Both failures traced to a test-side arithmetic mis-translation, not PRD silence.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Fixes applied to `test_suite/`** — `test_suite/test_04_invoicing_and_contract_closeout.py`:
- `test_06_demobilizing_with_no_field_deployments_is_refused` (line 316): live quote-line count `== 3` -> `== 2`.
- `test_08_reconciled_lines_replace_the_provisional_set_at_closeout` (lines 421, 426): pre-demobilization live count and post-demobilization superseded count `== 3` -> `== 2`.

**Diagnosis.** Both tests use the `SEVEN_UNIT` shape (`factories.rental_contract_payload`: CONSTRUCTION, headcount 40, `service_frequency_per_week` 3, `ada_required` false). Walking PRD §3.3's pinned seven-step projection: interval `ceil(7/3)=3`; demand `40x9x3=1080`; base capacity `ceil(1080/250)=5`; headcount 40 < 400 so 5 `STANDARD_PORTABLE` and no trailers; `ada_required` false so no `ADA_PORTABLE`; handwash `ceil(5/4)=2`. With PRD's "any class whose computed quantity is zero produces no row at all", that is exactly **2** lines (72500 + 19000 = 91500 cents).

The "3" was copied from the thirteen-unit shape, which genuinely emits three lines (9 SP + 1 ADA + 3 HW = 181500). Three independent corroborations that 2 is correct, all of which were already passing: the factory's own docstring ("five standard portables plus two handwash stations"), `quoted_cents == 91500` asserted in the same two tests, and `sum(escalated) == 93102` in `test_03` of the same file — which only reconciles as `73769 + 19333` over two lines at the 1.75% fuel-only escalation. So this was STEP 2 (assertion mis-translation in `test_suite/`), and the correction makes the tests *more* faithful to PRD, not less: both still assert exact line counts, exact quote-variant transitions, and the exact reconciled line set.

Two notes worth flagging: no assertion was weakened, no `skip`/`xfail` was added, and the implementation was not touched — its quote projection was already PRD-correct. I read `PRD.md` only; `SCAFFOLD*.yaml` were never opened.

**Orchestrator independent verification of the sweep artifacts** (mandated because a Step 7 subagent can report a clean sweep while leaving no evidence behind): `json.load` on all 8 files -> 8/8 with `passed=87 total=87 failed=0 errors=0 skipped=0`. Freshness confirmed by mtime ordering — the fixed `test_04_invoicing_and_contract_closeout.py` is stamped `06:30:36Z` and every `results.$i.json` is stamped `06:33:23Z`, i.e. the passing sweep ran strictly after the fix, so these are the iteration-2 artifacts and not stale iteration-1 leftovers. `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` -> no matches. Suite still holds 87 tests, so nothing was dropped.

**Step 8 skip-condition adjudication (orchestrator):** NOT skipped. The skip rule requires all four counters at zero; Step 7 ran 2 iterations and applied 3 assertion corrections in `test_suite/`. Step 8 therefore runs. Noted for the record that `implementation/` fixes are 0, so a byte-identical `PRD_FINALIZED.md` would be a legitimate Step 8 outcome here — the `<step_7_diff>` contains no impl behavioural choice that PRD left open, only a test-side arithmetic error. Only Step 9 is required to differ from its source.

## Step 8: Finalize PRD — 2026-09-05T06:45:00.000Z

## Result

`.../workspace/PRD_FINALIZED.md` is a **byte-identical** copy of `PRD.md` (md5 `8419d922518f6a66b6dfea067905d9dc` for both).

- **Line counts:** PRD.md 463 / PRD_FINALIZED.md 463 — **0.0% delta**.
- **Changes:** none. Zero edits.

### Why zero edits is the correct outcome

`<step_7_diff>` contains no `implementation/` fixes, no `test_helpers/` fixes, and no test deletions. Its only items are three `test_suite/` integer literals (`3` -> `2`) in `test_suite/test_04_invoicing_and_contract_closeout.py` at lines 316, 421, 426. I verified against the implementation that PRD.md already uniquely determines the corrected value, so there is nothing to pin.

Verification of the single subject (provisional unit-mix line count for the `SEVEN_UNIT` shape), walking PRD §3.3's seven pinned steps against `implementation/calculations.py:26-75` and `implementation/constants.py:62-78`:

| PRD §3.3 step | PRD text | impl |
|---|---|---|
| 1 (CONSTRUCTION) | ceil(7 / freq) days x headcount x 9 | `ceil_div(7, service_frequency_per_week)`, `x CONSTRUCTION_SHIFT_HOURS=9` (calculations.py:36-39) |
| 2 | ceil(demand / 250) | `ceil_div(..., STANDARD_SERVICE_PERSON_HOURS=250)` (:42) |
| 3 | hard headcount threshold 400 | `TRAILER_HEADCOUNT_FLOOR=400`, `>=` (:45) |
| 4 | std + 2x2stall + 8x8stall | (:56) |
| 5 | `ada_required` false -> no ADA rows | `ada_qty = 0` (:61-62) |
| 6 | ceil((restrooms + ada) / 4) | `ceil_div(..., 4)` (:65) |
| 7 | fixed class order, zero-quantity classes emit no row | `[... for uc in UNIT_CLASSES if quantities[uc] >= 1]` (:74-75) |

Factory shape (`test_helpers/factories.py:125-146`): CONSTRUCTION, headcount 40, freq 3, `ada_required` false. Projection: interval `ceil(7/3)=3`; demand `40*9*3=1080`; base `ceil(1080/250)=5`; 40 < 400 so 5 `STANDARD_PORTABLE`, no trailers; no ADA; handwash `ceil(5/4)=2`. Exactly **2** rows, `72500+19000 = 91500` cents. The old `3` came from the thirteen-unit shape. PRD's step-seven sentence ("any class whose computed quantity is zero produces no row at all") is already unambiguous — this was a pure test-side arithmetic mis-translation, i.e. neither PRD silence nor PRD/impl divergence.

### Pre-edit search log

No edits were committed, but the mandatory enumeration was performed for the one candidate subject before concluding no edit was warranted:

- **(a) Subject:** provisional quote-line emission — which unit classes produce rows, in what order, and the resulting live/superseded line counts.
- **(b) impl paths enumerated (read or grepped):**
  - `implementation/calculations.py:26-87` — `provisional_mix` (all seven steps, EVENT and CONSTRUCTION branches, both trailer branches, ADA on/off) and the parallel `reconciled_mix`, which uses the same `>= 1` zero-skip and the same `UNIT_CLASSES` order.
  - `implementation/constants.py:17-23, 62-78` — `UNIT_CLASSES` tuple order and every projection constant / per-class rate.
  - `grep -rn "provisional_mix|reconciled_mix|quoted_cents"` across `implementation/` — only three callsites: `routes/contracts.py:124` (quote), `:195` (demobilize reconciled), `:58` (creation zeroing).
  - `implementation/routes/contracts.py:111-135` — quote run: stale-version guard, `DRAFT`/`QUOTED` state gate, empty-projection guard, `supersede_lines(variant="PROVISIONAL")` re-quote self-loop, `quoted_cents = total`, `recompute_net_billable`.
  - `implementation/routes/contracts.py:173-209` — demobilize: `ERR_RECONCILIATION_NO_DEPLOYMENTS` fires at :186 *before* `supersede_lines` at :193, so a refused demobilization leaves the live provisional set intact (the exact off-Step-7-site path the `test_06` assertion touches); then `supersede_lines()` with no variant filter supersedes provisional lines too, matching PRD §3.9's "provisional lines included".
  - `implementation/routes/contracts.py:138-170` — `activate`, confirming nothing between quote and demobilize mutates the line set.
- **(c) Wording adjustment:** none needed — every enumerated path is already correctly described by PRD.md's existing prose, so the correct minimal patch is the empty patch.

Residual ambiguity elsewhere in the PRD was deliberately not touched (Step 9's scope). `worklog.md` and `SCAFFOLD*.yaml` were not read or modified; no stray files were left in `workspace/`.

**Orchestrator verification:** `md5sum` re-run independently -> both files `8419d922518f6a66b6dfea067905d9dc`, both 463 lines. Confirmed as the legitimate identical-output case (Step 7 made 0 `implementation/` fixes, so `<step_7_diff>` held no impl behavioural choice for PRD to pin). Step 9, by contrast, must NOT come out identical to its source — it runs the full impl scan.

## Step 9: Complete PRD — 2026-09-05T07:15:00.000Z

**Orchestrator design decision (recorded per the AUTONOMY directive).** Step 9 was NOT run as one subagent. A single agent asked to scan 2842 lines of implementation against a 463-line PRD reliably runs out of working context and returns a `PRD_COMPLETED.md` that is byte-identical to its source — i.e. the scan silently never happened. So Step 9 was split into **three sequential passes partitioned by implementation module**, all writing to one shared `PRD_COMPLETED.md` with targeted `Edit` replacements (never a whole-file rewrite, which would clobber the previous pass). Pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from running it and were told exactly what the earlier passes had already settled, so they would not re-litigate the same prose. Partition:

- **Pass 1 — foundation / envelope / identity / CRUD shell:** `app.py`, `responses.py`, `errors.py`, `auth.py`, `validation.py`, `db.py`, `clock.py`, `routes/{common,clock_api,accounts,sites}.py`
- **Pass 2 — domain math and the contract/permit spine:** `constants.py`, `calculations.py`, `services.py`, `routes/{permits,refdata,contracts}.py`
- **Pass 3 — field operations:** `routes/{deployments,schedules,visits,manifests,charges}.py`, plus the final structural check

Every one of the 2842 implementation lines falls in exactly one partition; `calculations.py`/`services.py` helper internals were assigned to pass 2 while their route-level triggers in pass 3's flows were assigned to pass 3, so the two never wrote overlapping prose.

### Pass 1 (foundation) — 13 ambiguity-pins, 2 mismatch-revisions, 463 -> 464 lines, +5,449 chars

`cp PRD_FINALIZED.md PRD_COMPLETED.md` performed by pass 1 only. Claims verified against a live server on port 18734 (booted and stopped by pid, no broad kills): 404/405 without headers, `req_`+20 chars, `.000Z` logical-clock timestamp, `version` 1 on create, extra body field ignored, 2-key object `meta`, `limit=0`->400, `offset=-1` on an unknown account->400 (shape before path resolution), `offset` past end->empty page with full `total_count`, bad enum filter->400, empty role header->401, cross-account read allowed.

- §2.1 identity — revise — ambiguity — headers that are present but empty also yield `ERR_UNAUTHENTICATED`; role match is exact/case-sensitive — auth.py:24
- §2.1 identity — insert — ambiguity — contract creation and charge dispute are the *only* account-scope checks; `X-User-ID` is never resolved against the account collection — auth.py:21-26, routes/accounts.py:37,45
- §2.2 envelope — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`-`Z`/`0`-`9` — responses.py:9,13
- §2.2 envelope — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — responses.py:19
- §2.2 envelope — insert — ambiguity — a computed action payload (clock repositioning) also reports `response_type` `"object"` — responses.py:29, routes/clock_api.py:24
- §2.2 envelope — insert — ambiguity — pagination `meta` keys are absent from single-object responses (exactly two keys) — responses.py:16-23,41-46
- §2.2 error format — insert (2 bullets, the +1 line) — mismatch — `message` wording is non-contractual; unknown path -> `ERR_INVALID_REQUEST` at **404** and disallowed method -> `ERR_INVALID_REQUEST` at **405** (the only two non-400 uses of that id, reconciling §5); both decided by routing ahead of the §2.11 header checks; trailing slash accepted — app.py:27,39-46
- §2.3 pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected as `ERR_INVALID_REQUEST`, never clamped, evaluated before path-identifier resolution; over-range `offset` returns an empty page with full `total_count` — validation.py:145-165
- §2.3 ordering — insert — ambiguity — `created_at` ties (routine under a logical clock) are broken by a monotonic server-minted creation sequence, for list windows and cascades alike; that sequence never appears in responses — db.py:78-84,91-92
- §2.4 clock — revise — mismatch — the pre-reposition instant renders as `2026-08-01T00:00:00.000Z` — clock.py:8,13-19
- §2.4 clock — insert — ambiguity — `to_iso8601` accepts `Z` or numeric offset, treats a zoneless value as UTC, truncates sub-millisecond precision, rejects unparseable/non-string with `ERR_INVALID_REQUEST`; backwards moves allowed; `current_utc` uses the standard 3-digit form — clock.py:36-55, routes/clock_api.py:17-22
- §2.9 common properties — revise — ambiguity — `created_at` from the logical clock; `updated_at` equals `created_at` at creation; `version` starts at **1** and increments **at most once per row per request** regardless of how many derived fields that request rewrites — db.py:47-75
- §2.11 step 3 — insert — ambiguity — unknown body fields ignored; JSON `null` treated as absent; a JSON boolean never satisfies an integer field; absent/empty body read as `{}` while a non-object body is rejected here; uniqueness violations reported here as `ERR_INVALID_REQUEST` — validation.py:21-33,74,137-140
- §3.1 site registration — insert — ambiguity — the posture roll-up at registration confirms rather than changes `NONE`/`RESTRICTED`, so a fresh site returns `version` 1 with `updated_at == created_at` — routes/sites.py:36-50
- §4 list note — insert — ambiguity — filters conjunctive; non-member enum filter rejected not ignored; boolean filters accept `true`/`false`/`1`/`0` case-insensitively; date filters must be 10-char `YYYY-MM-DD`; identifier filters matched literally (unknown id -> empty page, not 404); unrecognised query params ignored — validation.py:168-206, routes/sites.py:64-72

Left unedited (already pinned): all 36 error ids and statuses in §5 vs `errors.py`; the seven role names and every `@endpoint(...)` role set; §2.8's twelve 404 codes vs `routes/common.py:7-20`; the quote-line `version`/`updated_at` absence vs `db.touch`'s early return; every account and site field rule (ranges, defaults, initial derived zeros); permit list filters; clock response field names; `has_more`/`total_count` semantics; bare-UUID `id`; 201-on-create/200-on-modify. Deliberately excluded: host/port/threading (a deployment contract owned by INSTRUCTION.md, not API behaviour) and the HTTP 500 fallback (`app.py:48-52`, not a deterministically specifiable path).

### Pass 2 (domain math, contract/permit spine) — 14 ambiguity-pins, 1 mismatch-revision, 464 -> 464 lines, +5,493 chars

Confirmed no `cp`; 15 in-paragraph `Edit` replacements.

- §2.5 — insert — ambiguity — any posture recomputation that *lands on* `BLOCKED` (not just one newly becoming blocked) re-runs the schedule-suspension cascade, so a confirm-only recompute sweeps up schedules created since; schedule creation is not posture-gated, making it reachable — services.py:126
- §2.5 — insert — ambiguity — "latest filing of a kind" breaks identical-`created_at` ties by the §2.3 creation sequence — services.py:86
- §2.7 — insert — ambiguity — a derived-field recomputation that finds every value already correct writes nothing: no `updated_at`, no `version`. Enumerated the guarded field sets (site roll-up, route densities/`committed_units`, `deployed_unit_count`, contract ledger, account balance/hold, strike counters, open-manifest gallons, facility committed volume) — services.py:117,179,192,207,225,237,256,275,347,369
- §2.10 — insert — ambiguity — both `expected_contract_version` and `expected_route_version` must be JSON integers >= 0, checked at §2.11 step 3; only a well-formed non-negative mismatch yields 412 — contracts.py:115, manifests.py:69
- §2.11 step 3 — insert — ambiguity — a uniqueness comparison runs only after every field clears its own shape check; all nine optional note/reason fields must be non-empty strings with no maximum length — refdata.py:26,57,87, validation.py:42
- §3.2 — insert — ambiguity — `rejection_reason` is never written back to null, so an eventually-approved filing still carries the old reason text — permits.py:89-96
- §3.2 — insert — ambiguity — approval after `effective_to` is `ERR_INVALID_STATE_TRANSITION` (previously unnamed) — permits.py:85-87
- §3.2 — insert — ambiguity — sweep counter semantics: `blocked_site_count` counts *distinct* sites newly entering `BLOCKED` (already-blocked excluded though their cascade still runs; a site with two expiring filings counted once); `suspended_schedule_count` totals transitions actually performed — services.py:416-435
- §3.3 — **revise** — **mismatch** — PRD said "any other combination" of `contract_kind`/`construction_phase` is rejected; impl only rejects `EVENT` + non-`EVENT_NA`. Revised to a one-directional rule stating `CONSTRUCTION` + `EVENT_NA` is accepted and draws 0% phase escalation — contracts.py:35
- §3.3 — insert — ambiguity — an empty projected line set is refused with `ERR_INVALID_STATE_TRANSITION` — contracts.py:126
- §3.4 (mobilization only) — insert — ambiguity — the `IN_YARD -> DEPLOYED` unit write is conditional; a reserved deployment whose unit is `IN_REPAIR`/`RETIRED` still advances while the unit's status is left alone, and mobilization is not refused — contracts.py:166
- §3.5 (termination sentence) — insert — ambiguity — a schedule terminated out of `SUSPENDED` cancels no visits either, so a `PLANNED` visit dated before the suspension's cut-off survives on a `TERMINATED` schedule — services.py:161-168
- §3.6 (credit step 3) — insert — ambiguity — an empty non-superseded line set gives base 0 and a zero-cent credit; the declaration is not refused and a zero-cent credit row is still created — calculations.py:134-139, visits.py:176-191
- §3.9 (demobilization) — insert — ambiguity — the `DEPLOYED -> IN_YARD` unit write is conditional on the unit being `DEPLOYED`; `deployed_unit_count` is recomputed once per distinct affected site after the whole run — contracts.py:206-213
- §3.9 (escalation) — insert — ambiguity — a superseded line is never revisited by an invoice run and keeps the `escalated_cents` it carried when superseded (0 if never escalated); that figure never enters `invoice_subtotal_cents` — contracts.py:242,251-254

Left unedited (already pinned): every `constants.py` rate/tier/threshold table, all enum member sets, `PERMIT_STATUS_PRECEDENCE`/`PERMIT_STATUS_MAP`; all seven projection steps and their floor/ceil disposals, reconciled-mix counting and no-overlay rule, class order and zero-quantity skip, `combined_escalation_pct` and per-line escalation, `density_pct` floor and zero-capacity fallback, the three density-surcharge tiers, strike multiplier bands, damage/tip-over single-rounding-at-the-end, relocation's two pinned roundings; required-permit-kind derivation, per-kind status mapping, worst-of precedence walk, open-tip-over test, posture derivation, `blocked_site_cascade` ordering, `suspend_schedule`'s three effects and their order, planned/realized density definitions, contract ledger definitions and `flag_rebill_required`, `recompute_account` input set and the 60000-cent threshold, strike input sets, `apply_charge_state_effects` ordering, `manifest_rollup`/`refresh_open_manifests`/`committed_for_date` input sets, `gate_window_contained` and the 20-minute buffered overlap formula, `expire_permits_sweep` candidate set and ordering; all permit field ranges, `DRAFT`/`revision_round` 0 seeding, submit's two-state origin and `revision_round < 3` cap, `submitted_by_user_id` stamping, approve/reject required fields, approval not resuming suspended schedules; all asset-unit/disposal-site/route field ranges, defaults, uniqueness scopes, seeded derived zeros, `committed_gallons_today` read against the current clock date; contract creation defaults and zeroed ledger, filter sets on all three list endpoints, OCC-before-state ordering on quote, `PROVISIONAL`-only supersession on quote vs all-variants on demobilize, the four mobilization gates in §2.11 order, demobilize's `ERR_RECONCILIATION_NO_DEPLOYMENTS` input set and reconcile-then-unwind order, invoice's two origins / non-superseded-line requirement / billing-hold gate / `created_at`-ascending line order, settle's `INVOICED -> SETTLED` and the two `CLOSED` join paths.

### Pass 3 (field operations) — 16 ambiguity-pins, 3 mismatch-revisions, 464 -> 464 lines, +5,419 chars

Confirmed no `cp`; `PRD.md` and `PRD_FINALIZED.md` verified byte-unchanged (both still 87440 bytes, mtimes unchanged).

- §3.4 (reservation) — insert — ambiguity — nothing beyond the three named constraints is examined: unit `status` never consulted (an `IN_REPAIR`/`RETIRED` unit is reservable), `unit_class` need not appear in the quote lines, contract `fulfillment_state` not examined — deployments.py:38-53
- §3.4 (relocation) — insert — ambiguity — `relocation_reason` validated then discarded; `effective_date` not persisted and unconstrained relative to the `deploy_from`–`deploy_to` interval — deployments.py:88-89,111
- §3.4 (relocation) — insert — ambiguity — destination need not differ from the current site; a self-move is permitted, counts and bills — deployments.py:96-108,130
- §3.4 (relocation effects) — insert — ambiguity — the RELOCATION charge carries `severity`/`source_visit_id` null and `assessed_by_user_id` = the acting DispatchPlanner's `X-User-ID` (not `SYSTEM`), exposing it to segregation of duties; on a self-move the two count recomputes collapse to one no-op — deployments.py:113-131
- §3.5 (schedule creation) — **revise** — **mismatch** — the `service_day` equality rule cannot be a step-3 check; it is evaluated after body identifiers resolve, so an unresolvable `route_id` reports `ERR_ROUTE_NOT_FOUND` — schedules.py:28-32
- §3.5 (`units_on_route`) — insert — ambiguity — a contract with no non-superseded line yields `units_on_route` 0 and still creates the schedule; neither contract `fulfillment_state` nor route `status` is gated — schedules.py:34-47
- §3.5 (suspend) — insert — ambiguity — `suspension_reason` validated then discarded — schedules.py:79
- §3.6 (visit planning) — insert — ambiguity — planning consults neither the schedule's `state` (a `SUSPENDED`/`TERMINATED` schedule still accepts a `PLANNED` visit) nor the calendar (`scheduled_date` need not match `service_day` or the term); the `visit_kind` list filter accepts all four kinds incl. `RERUN` — visits.py:43-50,83
- §3.6 (gate window) — insert — ambiguity — the schedule's nominal window is not a second containment; the visit window is measured only against the gate window and other route windows — visits.py:19-28
- §3.6 (dispatch) — insert — ambiguity — dispatch carries no request body of its own — visits.py:103
- §3.6 (dispatch) — insert — ambiguity — the `last_run_date` write is skipped when the stored value is already later; dispatch does not recompute `density_realized_pct` — visits.py:118-122
- §3.6 (completion) — insert — ambiguity — completion consults no other row's state (suspended/terminated schedule or suspended route do not block it) — visits.py:126-140
- §3.6 (re-run) — insert — ambiguity — site posture is not re-examined at re-run booking; `rerun_date` unconstrained, may precede the missed visit's date — visits.py:212-221
- §3.6 (re-run) — insert — ambiguity — the 201 body carries the new re-run visit, not the `RERUN_SCHEDULED` original — visits.py:238
- §3.7 (manifest opening) — insert — ambiguity — opening is unconditional (facility status, accepted classes and serviced-visit existence are seal-time checks); several manifests may share route+date+facility — manifests.py:18-36
- §3.7 (seal) — insert — ambiguity — `seal_note` and `acceptance_note` validated then discarded — manifests.py:70,109
- §3.8 (assessment) — insert — ambiguity — no relationship required between `contract_id` and `asset_unit_id` — charges.py:63-64
- §3.8 (assessment) — **revise** — **mismatch** — `RELOCATION` is also never accepted from a client; the endpoint admits only `DAMAGE` and `TIP_OVER` — charges.py:56, constants.py:46
- §3.8 (dispute) — **revise** — **mismatch** — a dispute does not rewrite the strike counters (they are rewritten only at assessment and at waiver), so the counters stay stale between dispute and resolution and the next assessment's strike ladder prices against that unrefreshed total; upholding needs no rewrite — charges.py:151,170, services.py:281-293

Left unedited (already pinned): reservation gate ordering (BLOCKED -> RESTRICTED -> infeasible -> double-booked) and the closed-inclusive overlap rule incl. shared-endpoint conflict and `RETURNED` exclusion; relocation's `DEPLOYED`-only precondition, `RESTRICTED`-destination exemption, cross-account rejection as `ERR_INVALID_STATE_TRANSITION`, origin-site irrelevance, `relocation_count` monotonicity, two-rounding price; schedule capacity gate (`<=` allowed, strictly greater refused), `units_on_route` freeze semantics, planned-density definition, suspend's three effects, termination asymmetry; visit row defaults, denormalized `route_id`, `RERUN` refused on create, gate-window containment inequality, the 20-minute buffered route-window rule and its candidate-state set; dispatch's schedule-`ACTIVE` and `ERR_ROUTE_SUSPENDED` gates and their §2.11 relative order, `last_run_date` max-with-null rule, completion writing `units_serviced` from the frozen schedule count, realized-density definition; mark-missed's two entry states and their differing schedule guards, the pre-write `density_planned_pct` snapshot, the four-hop credit cascade, `SYSTEM` as `assessed_by_user_id`, credit-then-realized-density ordering; manifest roll-up input set, refresh-only-while-OPEN, seal's five checks in §2.11 order, the cap keyed on `manifest_date` excluding the sealing manifest, route `version` increment, acceptance re-checking only facility status; charge strike ladder read-before-count, per-class bases, `TOTAL_LOSS` retire vs threshold repair paths and their `deployed_unit_count` recomputes, dispute window inclusive-at-deadline, segregation of duties before the state check, uphold/waive reachable from either live state and their compensation sets; all response codes and role assignments in the §4 table.

### Step 9 totals and structural verification

**43 ambiguity-pins + 6 mismatch-revisions = 49 edits.** `PRD_FINALIZED.md` 463 lines / 87,440 chars -> `PRD_COMPLETED.md` 464 lines / 103,801 chars (**+1 line, +16,361 chars, +18.7%**). The single added line is pass 1's two-bullet insert in §2.2's error-format subsection; every other edit is in-paragraph, and no new sections were created.

Pass 3's structural check: 464 lines, `## 1.` through `## 5.` present and in order (lines 3, 11, 197, 363, 425), `### 2.1`–`### 2.11` and `### 3.1`–`### 3.9` plus both `####` response-format subheads present and correctly ordered, §4 table 53 endpoint rows, §5 catalogue 36 `ERR_` rows, file ending at the final table row with no mid-sentence truncation.

**Orchestrator independent re-verification:** `md5sum` -> `PRD.md` and `PRD_FINALIZED.md` both `8419d922518f6a66b6dfea067905d9dc` (untouched by all three passes), `PRD_COMPLETED.md` `5d1585f60462c18e2999f5618269ec6a` — **not** identical to its source, so the scan demonstrably ran. `wc -lc` -> 464 / 103,801. Re-counted independently: 5 `## ` headings, 20 `### ` subsections, 53 endpoint rows in the §4 span, 36 `ERR_` rows in the §5 span; `tail -3` ends on a complete table row. Leak sweep `grep -ic "harder than expert\|SCAFFOLD"` -> 0, so neither the difficulty directive nor any scaffold reference reached the completed PRD.

## Pipeline complete — 2026-09-05T07:16:00.000Z

All nine steps done. Final deliverables in place: `SCAFFOLD.yaml` + both design indices at the task root; `test_helpers/` (9 files) and `test_suite/` (11 files, 87 tests) at the task root; `workspace/` holding `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` (24 source files) and the passing `results.{1..8}.json` evidence at 87/87 in all 8 rounds.
