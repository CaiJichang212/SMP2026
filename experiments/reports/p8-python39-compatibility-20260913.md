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
  CPython 3.9.25 and `networkx==3.1`.
- Confirm every `nx.*` name referenced by the generated submission exists in
  NetworkX 3.1.
- Check the ZIP root contains only `config.json`, `prompt/`, and
  `starnet_model.py`, with no bytecode or cache files.

The full 208-test repository suite passed before the final clean build. The
submission build and validator passed after it. The generated-entry behavior
smoke test retained the expected scores: enabled conservative P8
`303.6875601323529`, unqualified fallback `274.76497219117647` on the fixed
development case.

Corrected artifact:
`artifacts/submission/starnet-p8-mean-20260913.zip`

SHA-256:
`067d232f5360e67114d1bf0f1937a574f71b743cd2049cf6d20372a45eb06c50`
