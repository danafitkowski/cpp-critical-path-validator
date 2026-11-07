# CPP DCMA-14: the one definition

Version 1, 7 November 2026. Every CPP engine that reports a DCMA-14 result measures it exactly as written here:

- the validator (`critical-path-validator/scripts/dcma14.py`; the `critical_path_validator` MCP tool, the claude.ai skill and the public cpp-critical-path-validator copy),
- the health dashboard (`schedule-health-review/template/Schedule_Health_Dashboard_v7_Obsidian.html`; the website demo, the analyst-delivered assessment and the `dcma14_health_check` MCP tool),
- CPP Lens DCMA Lite (`cpp-lens-viewer/src/sections/dcma-lite.js`; the free browser screen).

The constants are in `dcma_definition.json` beside this file. The parity fixtures in `_cpp_common/tests/fixtures/dcma_parity/` carry expected results worked out from this text, and each engine's suite checks itself against them. A change to this definition is made here first, then in all three engines in the same release.

The source is the DCMA EVMS Program Analysis Pamphlet, DCMA-EA PAM 200.1 (October 2012), section 4. Where the pamphlet leaves a choice open, the choice CPP makes is marked **CPP reading**. The thresholds are DCMA's; the A to F grade is CPP's own convention.

## Common rules

**D0 One project.** A file with several PROJECT rows is scored on one: the only row; else the latest `last_recalc_date`, ties broken by the most TASK rows, then file order. Its activities, the relationships with both ends in them, the resource assignments on them and its own data date are used; nothing else in the file is read. The result names the project scored when the file holds more than one. A file with one PROJECT row is read whole, whatever project ID its activities carry. The project is chosen first and its data date (D14) is then read; every entry point (a direct call, a report, a tool) uses this one choice.

**D1 Activity types.** Ordinary activities: `TT_Task`, `TT_Rsrc` (and any type not listed here). Milestones: `TT_Mile`, `TT_FinMile`. Level of effort and WBS summary (`TT_LOE`, `TT_WBS`) are never counted, and a relationship with either end on one is never counted.

**D2 Status.** Complete means `status_code = TK_Complete`; everything else is incomplete.

**D3 Working days.** Hours divided by the hours per day of the activity's own calendar. A blank activity calendar is the project calendar (`PROJECT.clndr_id`), else the default calendar (`default_flag = Y`), else 8 hours, and the fallback is disclosed.

**D4 Relationships.** *Logic relationships*: both ends in the scored project, neither end LOE or WBS. *Live relationships*: logic relationships whose successor is incomplete (**CPP reading**: a relationship between finished activities is history and is not graded).

**D5 Dates.**
- Validity (#9) and lateness (#11) are compared by **calendar day**.
- An activity is *due* (#11, #14) when its baseline finish is at or before the data date **to the minute**: a baseline finish later on the data date itself is not yet due (data date 08:00, baseline finish 16:00).
- *Complete as of the data date* (#14): complete, and its actual finish (if any) on or before the data date's day.

**D6 Not scored.** A check whose population is empty, or whose inputs are missing (no data date, no baseline, no computed float, no resource assignments, unreadable forecasts), is NOT SCORED. It stays out of the score's numerator and denominator, and the result gives the reason. Nothing is ever a PASS for want of something to measure.

**D7 Exact counts.** A percentage threshold is tested on the counts (count x 100 against threshold x total), never on a rounded percentage. An index (#13, #14) is compared after rounding to six decimal places, so a CPLI of exactly 0.95 passes.

**D8 Activity ID matching** (baseline to current). `task_code` with surrounding spaces trimmed, case ignored. An ID that appears more than once in either the scored project or the baseline project is ambiguous (every activity row counts, level of effort and WBS summary included): activities carrying it are left out of #8's baseline basis and of both counts of #11 and #14, and the number left out is disclosed. No alias matching (A1234 to 1234) and no matching by name.

**D9 Baseline project.** When the baseline file holds several projects: the one with the same `proj_id`, else the same `proj_short_name`, else the one sharing the most Activity IDs with the scored project (ties broken as D0 breaks them). Whatever rule chose it, and however many projects the baseline file holds, a baseline project that shares no Activity ID with the scored project is not used: #11, #13 and #14 are NOT SCORED, #8 reads current durations, and the result says why.

**D10 Network start and finish** (#1). The network starts at the earliest start (actual, else early, else planned) of any ordinary or milestone activity, complete included. It finishes at the latest finish (actual, else early, else planned) of the incomplete ones. Both are compared to the minute.

**D11 Completion activity** (#12, #13). The ordinary or milestone activity, complete or not, with the latest early finish (read per activity: its early finish, else its planned finish). On a tie: a finish milestone, then an activity of zero original duration (a completion typed as a task), else the first in the file.

**D12 Baseline finish** (#11, #13, #14). A baseline activity's finish is its planned finish (`target_end_date`), else its early finish. On an unprogressed baseline the two are the same.

**D13 Working time** (#13). Measured on the calendar's own shift times: the part of a day before the data date's clock time is not counted, nor the part after a finish's clock time. A data date at the start of a working day and a finish at the end of a working day five working days later is 5.0 working days.

**D14 Data date.** The scored project's `last_recalc_date`. Blank, it is the project's planned start (`plan_start_date`); on a day before a later planned start, it is lifted to the planned start. Both are what P6 does when it opens the project, and the result discloses either.

## The fourteen checks

| # | Check | Population | Counts as a finding | Passes when | Not scored when |
|---|---|---|---|---|---|
| 1 | Logic | incomplete ordinary activities and incomplete milestones | no logic relationship in (missing predecessor) or out (missing successor). A `TT_Mile` with no predecessor starting at or before the network start (D10), and a `TT_FinMile` with no successor finishing at or after the network finish, are not findings; the exemption covers only the missing side named (**CPP reading**: a dangling mid-network milestone is the defect #1 exists to find) | activities with either finding (each counted once) are at most 5% | population empty |
| 2 | Leads | live relationships | lag below 0 | none | no live relationships |
| 3 | Lags | live relationships | lag above 0 | at most 5% (a lag over 44 working days on the successor's calendar is listed for information; it decides nothing) | no live relationships |
| 4 | Relationship types | live relationships | Finish-to-Start | at least 90% are FS | no live relationships |
| 5 | Hard constraints | incomplete ordinary activities | `CS_MSO`, `CS_MEO`, `CS_MSOB`, `CS_MEOB`, `CS_MANDSTART` or `CS_MANDFIN` as the primary or the secondary constraint (DCMA's Must Start On, Must Finish On, Start No Later Than, Finish No Later Than; P6's mandatory pair is harder than any of them). Constrained milestones are listed for information | at most 5% | population empty |
| 6 | High float | incomplete ordinary activities with a computed total float | total float above 44 working days | at most 5% | no incomplete ordinary activity carries a computed float (a blank float is left out and counted) |
| 7 | Negative float | as #6 | total float below 0 | none | as #6 |
| 8 | High duration | incomplete ordinary activities with a readable original duration (a blank one is left out and the count disclosed) | duration above 44 working days. The duration is the baseline's original duration of the same activity (on the baseline activity's calendar) when a baseline is supplied and the activity is in it, else (or when the baseline's is blank) the current original duration (`target_drtn_hr_cnt`); the result says how many were read on each basis. The pamphlet's detail-planning-window restriction is not applied | at most 5% | population empty |
| 9 | Invalid dates | ordinary activities and milestones, complete included | an actual start or actual finish on a day after the data date's day; or, on incomplete work, a forecast before it: not started, an early start or early finish on a day before the data date's day; started, an early finish on a day before it | none | no data date. When the incomplete work carries no early dates the forecasts cannot be read: the actual dates are still judged, and the result says so |
| 10 | Resources | incomplete ordinary activities with an original duration of at least 1 working day (a blank duration is left out) | no resource assignment carrying hours or cost (`target_qty`, `target_cost`, `remain_qty` or `remain_cost` above 0) | every one is resourced (100%) | the scored project carries no resource assignments at all; population empty |
| 11 | Missed tasks | baseline ordinary activities due by the data date (D5), matched to the current schedule (D8) | not in the current schedule (deleted or renumbered); not complete; or complete with an actual finish on a day after its baseline finish. Complete with no actual finish: lateness unknown, out of both counts | at most 5% | no baseline; no data date; nothing due; fewer than 80% of the due activities match the current schedule |
| 12 | Critical path test | the network | the test (a large delay, commonly 600 working days, inserted on the critical path, and the completion moving by the same amount) needs a CPM recalculation, which CPP’s DCMA tools do not yet run. Until they do, it is decided only where the answer is certain: FAIL on a logic cycle, or on a completion activity (D11) pinned by `CS_MANDSTART` or `CS_MANDFIN` as its primary or secondary constraint. Network screens (orphans, an unreachable finish, a split critical network) are reported for information | (not decided) | in every other case |
| 13 | CPLI | the completion activity (D11) | (critical path length + float) / critical path length. Critical path length: the working time (D13) from the data date to its early finish on the project calendar, in working days. Float: with a baseline, the working time from that early finish to the baseline finish (D12) of the same activity, measured the same way (else the baseline's own completion activity, disclosed); without one, its P6 total float, where the file has a deadline (Must Finish By, or `CS_MEO` or `CS_MEOB` on it) or that float is not zero | at least 0.95 | no data date; a completion activity pinned by `CS_MANDSTART` or `CS_MANDFIN` (P6 sets its finish and float from the constraint, so CPLI would read 1.000 by construction; #12 fails it instead); a baseline supplied but not used (D9); no baseline and no deadline and a zero float (1.000 by construction); finish at or before the data date |
| 14 | BEI | baseline ordinary activities due by the data date, including those no longer in the current schedule | the current ordinary activities complete as of the data date (D5), every one counted (ambiguous IDs aside, D8), so the index can exceed 1.0 (**CPP reading**: the pamphlet's extra denominator term for tasks with no baseline finish is not added) | at least 0.95 | no baseline; no data date; nothing due |

CPP Lens scores checks 1 to 11 (11 needs a baseline). #12 needs a CPM recalculation and #13 the critical path length, neither of which Lens computes, and Lens leaves #14 to the full assessment, so it reports all three as not scored, except that #12 is a FAIL there too on a logic cycle or a mandatory-constrained completion.

## Results and the grade

- Every result is PASS, FAIL or NOT SCORED, with the counts behind it (numerator and denominator). There is no intermediate band.
- The validator reports passed / scored. The dashboard also gives a letter: pass rate = passed / scored, rounded to the whole percent shown; A at 90 and above, B 75, C 60, D 45, else F; band GREEN at 85 and above, YELLOW 65, else RED. It is CPP's convention, not DCMA's, it is printed with "n of 14 scored", and no letter or band is given when fewer than 10 of the 14 could be scored.
- The validator's nuclear and mining profiles change some thresholds; a result graded on one names the profile and says the threshold is CPP's, derived from the DCMA check. The published numbers above are the default (commercial) profile.
