# P11 public prompt calibration development

## Result

The public-feedback calibration identified the true unique best prompt ID in
all 72 declared development cases. It used two probe nodes and six successful
communications per case, costing exactly 12 budget. There were no failed,
clipped, tied or conflicting calibrations.

| Metric | Result |
| --- | ---: |
| Prompt identification | 72 / 72 |
| Confident two-node calibrations | 72 / 72 |
| Cases with censored observations | 0 |
| Failed probe actions | 0 |
| Maximum probe budget | 12 |
| Calibrated vs fixed prompt 1 | 48 / 24 / 0 |
| Mean terminal gain | +287.390954 |
| Minimum / maximum terminal gain | 0 / +1312.512704 |

The 24 ties are exactly the configurations where prompt 1 was already best.
Every candidate/control pair performed the same full scans, the same two-node
prompt probes, and the same continuation target sequence. Only the prompt ID
used after calibration differed, so the terminal comparison is not confounded
by target allocation or budget.

## Public algorithm

For each selected node, the probe sequence is prompt 1, 2 and 3. A successful
public delta is divided by the published turn multiplier `1`, `0.5` or `0.25`.
Within one node this gives `prompt_strength * node_response`, so the positive
node-specific response factor cancels when prompt IDs are ranked. A second
complete node must report the same unique winner.

The ledger receives only node ID, prompt ID, turn number, public `before_w` and
returned `new_w`. It has no seed, hidden prompt value or response-factor input.
Successful observations ending at an opinion bound are censored. Finite zero
and negative deltas remain valid ordering evidence. Failed environment actions
do not advance the probe sequence.

Probe nodes are fully scanned, alive, unused peace/neutral nodes with opinions
strictly inside `[-60,60]`. They are ordered by lowest public initial degree,
then distance from the opinion bounds and ID. At most two nodes are selected.

## Development design

The matrix used the six consumed legacy repetition-1 graphs. Prompt strengths
covered all six permutations of `[15,10,-5]`, three rotations of
`[24,7,-12]`, and three rotations of `[6,5,4]`, totaling 72 cases. It is a
mechanism and implementation test on local custom seeds, not an official-score
estimate or a production qualification.

The result demonstrates why fixing `prompt_id=1` is a large strategic blind
spot when prompt values are hidden and their ordering changes. A runtime still
needs to schedule the six probe actions one per host step, preserve failed-call
semantics, expose the calibrated prompt in legal candidates, and validate on a
separate prompt-order holdout before production.

## Ledger boundary review

A tied best set no longer discards known information. With hidden strengths
`[-5,15,15]`, two informative nodes produce calibrated best IDs `{2,3}` and
`best_or_default()` deterministically chooses 2 instead of the known harmful
default 1. When one complete node has zero response to all prompts and another
is informative, the zero node does not contradict the informative ranking:
`confident` remains false, but the provisional winner is used. Conflicting
informative rankings still fail closed to the default.

An additional preregistered cost comparison used the same 72 unclipped cases.
Single-node and two-node calibration both identified 72/72 winners. Relative to
equal-probe-cost fixed-prompt controls, their mean gains were +305.233893 and
+287.390954. Single-node calibration beat two-node calibration in all 72 cases
by +24.486712 on average (range +2.657878 to +60.456242), reflecting three
additional continuation actions. This deterministic no-clip result measures
exploration cost; it does not remove the second-node value after an
uninformative, clipped or conflicting first probe and does not directly change
the runtime selection rule.
