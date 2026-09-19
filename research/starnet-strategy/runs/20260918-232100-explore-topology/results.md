# Explore results

Six50-node paired official sandbox seeds120-125, budget100, zeroLLM controls.
Natural mean -330.5267; incumbent-candidate heuristic122.4167; completion-aware
topology policy168.9583. Candidate6/6wins, mean+46.5417 (+38.0191%), worst+8.15.
Max steps77(candidate),86(incumbent); remaining budget0-1; peakRSS38076KiB.
No failures. Full metrics and per-state errors in metadata.json, traces in raw/.
Empirical proxyMAE0.5106, maximum absolute error2.1513 over18 natural/final states.
This is not exact engine recovery and not an official hidden score.

Simulator development means: incumbent122.3051, greedy170.0370,
completion168.6632. Greedy narrowly wins aggregate but candidate completion has
budget opportunity estimates directly useful to LLM. Both improve all6 controls.
Completion official execution validated; retain it for holdout, no tuned weights.

Low-degree calibration ablation: 2wins/4losses relative to completion, including
negative-hub regression; reject automatic low-degree calibration. Shield-only
matches5cases and loses~4.72 on disconnected seed125; retain legal cuts as
single-step candidates with explicit marginal and budget-completion estimates.

Next Compare: freeze completion defaults and use preregistered holdout126-143,
then official remote subset126,127,134,135,142,143. All simulations kept separate.
Final application still requires decision and realLLM paired verification.
