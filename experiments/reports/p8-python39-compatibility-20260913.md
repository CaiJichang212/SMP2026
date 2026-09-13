# P8 evaluator Python 3.9 compatibility correction

The first `starnet-p8-mean-20260913.zip` failed during import with:

```text
cannot import name 'TypeAlias' from 'typing' (/usr/local/lib/python3.9/typing.py)
```

The source was `src/starnet/policy/fast_settlement_experiment.py`. `TypeAlias`
was used only to mark a static type alias; it had no runtime or scoring role.
The corrected source uses a plain assignment:

```python
TopologyKey = tuple[tuple[int, ...], frozenset[tuple[int, int]]]
```

The provided `SMP2026常见问题解答.docx` lists the evaluator packages, including
`networkx==3.1`, `mesa==2.3.2`, and `typing_extensions==4.5.0`. It does not state
the Python minor version, while the platform traceback identifies Python 3.9.
No backport is needed for this alias.

Validation added:

- Parse generated `starnet_model.py` with `ast` feature version 3.9.
- Reject imports from `typing` that Python 3.9 does not provide.
- Compile the generated file with CPython 3.9.25.
- Dynamically load the generated file and directly import it from the ZIP with
  CPython 3.9.25 and `networkx==3.1`. **Evidence correction:** that original
  probe supplied empty temporary framework classes. It was only a module
  import probe, not validation of real CaseVO, controller execution, or P8
  activation. It must not be repeated or cited as end-to-end compatibility.
- Confirm every `nx.*` name referenced by the generated submission exists in
  NetworkX 3.1.
- Check the ZIP root contains only `config.json`, `prompt/`, and
  `starnet_model.py`, with no bytecode or cache files.

The full 208-test repository suite passed before the final clean build. The
submission build and validator passed after it. The generated-entry behavior
smoke test retained the expected scores: enabled conservative P8
`303.6875601323529`, unqualified fallback `274.76497219117647` on the fixed
development case.
Those behavior smoke tests used the modern development runtime, not the
complete Python 3.9 evaluator dependency stack.

## Post-score execution diagnosis

After the corrected ZIP scored `761.9467`, the planner and the unchanged ZIP
were exercised again under CPython 3.9.25. This used real local CaseVO 0.3.19
source (rather than temporary framework classes) together with the FAQ-pinned
`mesa==2.3.2`, `chromadb==0.5.5`, `networkx==3.1`, `numpy==1.24.3`,
`scipy==1.11.1`, `Jinja2==3.1.2`, and `requests==2.29.0`. The local CaseVO
checkout is the development copy and is not evidence that its implementation
is byte-for-byte identical to the evaluator's private installation.
The complete commands, dependency identities, source hashes, and machine-readable
results are in `p8-python39-execution-20260913.json`.

The reusable policy runner was invoked with Python 3.9 and Python 3.12:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --no-project --python 3.9 \
  --with 'networkx==3.1' -- python -B scripts/run_p8_search.py \
  --families er_balanced sbm_negative_bridges three_sparse_components watts_strogatz_mixed \
  --repetitions 502 --variants conservative --output /tmp/p8-py39.json

PYTHONDONTWRITEBYTECODE=1 uv run python -B scripts/run_p8_search.py \
  --families er_balanced sbm_negative_bridges three_sparse_components watts_strogatz_mixed \
  --repetitions 502 --variants conservative --output /tmp/p8-py312.json
```

After removing only elapsed-time fields, the reports were byte-equivalent.
All four cases had zero action failures. Their candidate deltas were `0.0`,
`11.959305501858807`, `0.0`, and `0.0`; rollout counts and full deviation
records also matched. A separate `ba_negative_hubs/501` run matched exactly at
`303.6875601323529`, with two deviations, 126 rollouts, and zero failures.

The real CaseVO controller path on that latter case also matched across the two
interpreters: score `303.6875601323529`, two P8 proposals, zero P8 planning
errors, 75 accepted mock-ranker choices, and zero fallbacks or action failures.
Finally, `scripts/compare_submission_archives.py` loaded the exact corrected
ZIP in Python 3.9. On its `ba_negative_hubs` archive-comparison seed it created
`P8RuntimeController`, retained effective P8 mode `conservative`, exposed three
P8 proposals, reported zero planning errors, and produced the same action hash
and score (`590.240586484472`) as Python 3.12.

Those successful CaseVO runs resolved `typing_extensions==4.16.0`. An explicit
`typing_extensions==4.5.0` pin, as listed by the FAQ, resolved Pydantic 1.10.26
and FastAPI 0.103.2 in the present public package index, then failed inside
ChromaDB with `Collection object has no attribute model_fields` before the P8
controller was constructed. Therefore the successful runs cover the listed
direct packages and Python/NetworkX compatibility, but do not claim a complete
reproduction of every evaluator transitive dependency. The failed exact-pin
command and resolved versions are retained in the JSON report.

One additional source-only defect was found: `p8_qualification.py` used
`str | None` annotations without postponing annotation evaluation. Direct
source-package import therefore raised `TypeError` on Python 3.9. The generated
single-file ZIP already postponed annotations at its first line, so this defect
did not affect that ZIP or explain its unchanged platform score. The source
module now imports `annotations` from `__future__` so source and bundle behavior
agree.

These tests reproduce P8 activation and rule out a general Python 3.9 or
NetworkX 3.1 planner fallback on the covered cases. They do not identify the
platform's hidden case mix or prove that every evaluator case exposed a P8
proposal.

Corrected artifact:
`artifacts/submission/starnet-p8-mean-20260913.zip`

SHA-256:
`067d232f5360e67114d1bf0f1937a574f71b743cd2049cf6d20372a45eb06c50`
