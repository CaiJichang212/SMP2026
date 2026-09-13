# P9 bounded candidate: Python 3.9 release-seal evidence

Candidate P8 source SHA-256:
`30326ab80cee936c6feb57ec01722eafa0994e2d171d606e6f439a3106f334ca`.
The temporary assembled single-file model SHA-256 was
`a262f364ee2ce83f6aeaeff990386f2429bce4df87a3714f7dedc2ca2af33b9f`.

## Evidence chain

1. The public custom-seed probe recorded 108 communication updates across
   positive and negative prompts, response factors 0.2 and 1.5, three slots,
   and initial opinions from -110 to 110. Independent test code recomputed
   every update from `previous_w`, prompt strength, factor, and turn. All 108
   matched per-action clipping to `[-100,100]`; all scans preserved their
   original value. Probe SHA-256:
   `0cc68a7bf2e7d5c71ddb3ed4f324e881ad9d37cf5f6dff3bb3b22208bfa8627c`.
2. CPython 3.9.25 with NetworkX 3.1 passed 52 focused bounded-policy tests,
   including cumulative communication slots and connected-fast/general
   budget-plan equivalence at saturation. After separating latent scenario
   response from the realized public observation, the 14 P8 tests also passed
   under that interpreter. The lower-bound regression produces the correct
   `-97.75` terminal value for `w=-110`, `r=0.2`, and three prompt-1 uses;
   an initially unknown second slot at `w=95` realizes delta 5.
3. `scripts/check_p9_bounded_entry.py` temporarily assembled the frozen source
   and ran default `ba_resampled/901/saturated_hubs` through real local CaseVO
   orchestration and the capped local environment. The Python 3.9 report has
   `bounded_estimator_active=true`, `entry_gate_passed=true`, conservative P8,
   zero planning errors, and zero action failures. It completed 84 steps with
   score `2071.3959395744687` and action SHA-256
   `9485faabecbae8cc13ea2c1dc56e884caa074aee21d1a00f5b183b69d66f5733`.
   The report itself records Python `3.9.25`, NetworkX `3.1`, and framework
   model module `casevo.model_base`.
4. The same entry check in the modern development environment produced the
   same model hash, score, action hash, counters, and action sequence. After
   deleting `seconds` and the intentionally different `python_version` and
   `networkx_version` fields, both JSON reports have SHA-256
   `515d9ff6b3393ab66385fa0f590376960916064baae428cf58df913a46c1fd22`.

Machine-readable entry reports:

- `experiments/reports/p9-bounded-entry-python39-20260913.json`
- `experiments/reports/p9-bounded-entry-modern-20260913.json`
- `experiments/reports/p9-bounded-python39-audit-20260913.json`

## Runtime scope

The Python 3.9 entry command used the clean local CaseVO 0.3.19 checkout at
commit `d3b8d1f81fe0b3d41ff80908351bd5ebd6809155` and tree
`a8d332f3dee00e2986ef53eae4dd458948b0a38d`, with `mesa==2.3.2`,
`chromadb==0.5.5`, `networkx==3.1`, `numpy==1.24.3`, `scipy==1.11.1`,
`Jinja2==3.1.2`, and `requests==2.29.0`. The resolver selected
`typing_extensions==4.16.0`, Pydantic 2.13.5, and FastAPI 0.128.8. This is a
real CaseVO compatibility run, not a full reproduction of every evaluator
transitive pin. The check used forced exception fallback locally; it did not
request a real LLM or remote environment.

The registered confirmation generators start all opinions within
`[-100,100]` and all nodes with `comm_left=3`. A real controller cannot recover
the latent response from a first return censored because an initial opinion
was already outside the bounds; that API-permitted edge remains an estimation
limitation outside the registered cohort. The P8 scenario rollout now keeps
its sampled latent value separately and no longer introduces that avoidable
simulation error. No confirmation result was read or modified by these entry
checks.
