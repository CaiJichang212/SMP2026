# P10 greedy factor attribution results

## Scope

The user reports `starnet-p9-bounded-response-20260913.zip` scored **761.9467**,
the same displayed score as P8 and below the historical experimental archive's
**765.8400**. This experiment uses 26 previously consumed cases to attribute
mechanisms. It is not a new holdout, an official-score model, or production
qualification.

The full 148 MB action/candidate trace remains under `experiments/raw/` with
SHA-256 `7884e0ff57f7bcbc04b8637a74289e601a67ca4ecdcc55b2f68c50f9d43bea31`.
The committed compact JSON retains every case score, action-log hash, resource
count and first divergence classification.

## Main factor results

Across all 26 consumed cases:

| Contrast (left minus right) | Mean | W/T/L | First divergence |
|---|---:|---:|---|
| pooled vs fixed, unrestricted | +13.5261 | 13/5/8 | 26 ranking-only |
| pooled vs fixed, full gate | +10.4811 | 13/5/8 | 17 ranking-only, 9 set-changing |
| unrestricted vs direction/ROI, pooled | +16.5066 | 8/18/0 | 8 set-changing |
| unrestricted vs direction/ROI, fixed | +13.4616 | 7/19/0 | 7 set-changing |
| direction/ROI vs full positive gate, fixed | 0.0000 | 0/26/0 | no divergence |
| narrow double-negative cut vs fixed full gate | +5.4224 | 6/20/0 | 6 set-changing |

With unrestricted structure, response pooling changes ordering without changing
the candidate set at the first divergence in all 26 cases. Under the direction
and ROI filter, response estimates also change the communication ROI threshold,
so 9 first divergences change the surviving structure set. Response and
structure filtering are therefore separable in the unrestricted arms but
interact in the current gated planner.

The positive-graph structure closure itself changed no candidate set or action
in this cohort after the direction filter had already run. The current hybrid
response switch differed from fixed response in one case and reduced score by
11.5414 there. Thus this cohort gives no positive evidence for the positive-graph
closure; it only detects the associated switch back to pooling.

## Selected historical-loss cases

The 12 prior cases selected because P9 had lost to the historical archive are
selection-biased diagnostics. On them, pooled/full exceeded fixed/full in all
12, with mean +32.7791 and range +5.6636 to +70.8016. This strongly localizes
the observed failures to response allocation, but cannot estimate general
population benefit because the cases were selected using the outcome.

Direction/ROI removal also helped only a subset. The narrow arm that restored
positive-gain cuts between two publicly negative non-peace endpoints improved
all five consumed BA saturated cases and one SBM saturated case:

| Case group | Gain over fixed full gate |
|---|---:|
| BA saturated, five repetitions | +8.5348 to +42.3838 |
| SBM saturated, repetition 1001 | +35.2797 |

It had 20 ties and no losses in this consumed cohort. This supports generating
the double-negative cut as a bounded candidate; it does not establish safety on
new data.

## Persona-response axis

The persona prior used first-slot values inspired by the public starter sample:
peace 20.25, neutral 15, violent 3. It is an experimental hypothesis, not an
assumed official formula. A target's own public response always overrides it.

| Consumed group | Persona prior minus fixed | W/T/L |
|---|---:|---:|
| four independent-response seeds | -44.9529 | 0/0/4 |
| same four topologies, persona-aligned response | +52.9739 | 4/0/0 |
| legacy six | -5.1050 | 2/0/4 |
| selected prior-loss cases | -28.1679 | 1/0/11 |

This sign reversal confirms that earlier persona-independent simulation can
systematically reject a strategy that is useful when response really follows
persona. Conversely, applying a strong static persona prior to an independent
or inverse distribution is harmful. A subsequent candidate needs online
persona-stratified shrinkage and explicit correlation strata rather than a
hard-coded sample rule.

## Limits and next validation

`pooled__unrestricted` approximates the historical archive's two main policy
choices but is not a byte-for-byte replay. On the legacy six its score differs
from the unchanged archive by 0, +0.3691, +0.4594, -5.8921 and -16.1916 across
the nonzero differences. Current scoring, clipping and tie handling remain in
the injected runner, so causal claims are limited to the controlled factors.

All 11 arms had zero action failures, nonnegative remaining budget and at most
87 actions. The next frozen experiment should test pooling, online
persona-stratified shrinkage and the narrow double-negative cut on independently
generated correlation strata. These consumed cases must not serve as its
promotion set.
