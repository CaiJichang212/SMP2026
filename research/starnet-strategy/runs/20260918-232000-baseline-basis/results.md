# Baseline results

38 official sandbox evaluations completed, no failures. 0 actions / LLM calls,
76 HTTP requests, 100 unused budget each. All six graph families agree with
`|C| * (degree+1) / sum_C(degree+1)` to score rounding (~0.005).
Example: path5 coefficients 0.769,1.154,1.154,1.154,0.769; star6 center 2.25,
leaves 0.75. Raw evidence: raw/basis.jsonl. Peak RSS 37160 KiB.

This rejects unnormalized degree+1 as an absolute score proxy on these graphs.
Connected-graph communication ranking is unchanged; structural marginal score
and comparisons across disconnected components change substantially.

Next: held-out 50-node arbitrary weights and post-intervention topology checks.
