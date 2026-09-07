"""Compatibility support for submission hosts that omit ``sys.modules`` registration.

``dataclasses`` resolves postponed annotations through ``sys.modules`` while a
class decorator is running.  Some submission hosts execute a dynamically
loaded module without registering it first, which otherwise fails during the
first ``@dataclass`` declaration.
"""

from __future__ import annotations


LOADER_COMPAT_MARKER = "# submission-loader-compat"
LOADER_COMPAT_PREAMBLE = f'''{LOADER_COMPAT_MARKER}
import sys as _submission_sys
import types as _submission_types

# A conforming import has already registered this module.  The fallback only
# applies to hosts that call ``exec_module`` without doing so first.
if _submission_sys.modules.get(__name__) is None:
    _submission_module = _submission_types.ModuleType(__name__)
    _submission_module.__dict__.update(globals())
    _submission_sys.modules[__name__] = _submission_module
'''


def inject_loader_compat(source: str) -> tuple[str, bool]:
    """Insert the idempotent compatibility preamble after a future import."""
    if LOADER_COMPAT_MARKER in source:
        return source, False

    future_import = "from __future__ import annotations\n"
    if source.startswith(future_import):
        return source.replace(future_import, future_import + "\n" + LOADER_COMPAT_PREAMBLE + "\n", 1), True
    return LOADER_COMPAT_PREAMBLE + "\n" + source, True


FRAMEWORK_COMPAT_MARKER = "# starnet-framework-compat-v2"
LEGACY_FRAMEWORK_COMPAT_MARKER = "# starnet-framework-compat"
FRAMEWORK_COMPAT_IMPORT = f'''{FRAMEWORK_COMPAT_MARKER}
import importlib as _starnet_importlib

try:
    _starnet_runtime = _starnet_importlib.import_module("case" + "vo")
    _starnet_framework = "documented"
except ModuleNotFoundError as _starnet_framework_error:
    if _starnet_framework_error.name != "case" + "vo":
        raise
    # The originally published Starter Kit used this legacy runtime name.
    _starnet_runtime = _starnet_importlib.import_module("agent_" + "mesa")
    _starnet_framework = "legacy"
AgentBase = _starnet_runtime.AgentBase
ModelBase = _starnet_runtime.ModelBase
'''
FRAMEWORK_COMPAT_IMPORT_WITH_JSON_STEP = f'''{FRAMEWORK_COMPAT_MARKER}
import importlib as _starnet_importlib

try:
    _starnet_runtime = _starnet_importlib.import_module("case" + "vo")
    _starnet_framework = "documented"
except ModuleNotFoundError as _starnet_framework_error:
    if _starnet_framework_error.name != "case" + "vo":
        raise
    _starnet_runtime = _starnet_importlib.import_module("agent_" + "mesa")
    _starnet_framework = "legacy"
AgentBase = _starnet_runtime.AgentBase
JsonStep = _starnet_runtime.JsonStep
ModelBase = _starnet_runtime.ModelBase
'''
_FRAMEWORK_IMPORT_TEMPLATES = (
    (
        "from casevo import AgentBase, ModelBase\n",
        FRAMEWORK_COMPAT_IMPORT,
    ),
    (
        "from casevo import AgentBase, JsonStep, ModelBase\n",
        FRAMEWORK_COMPAT_IMPORT_WITH_JSON_STEP,
    ),
)
_CASEVO_MODEL_INIT = (
    '        super().__init__(agent_graph, llm, prompt_path=str(prompt_path.resolve()), '
    'reflect_file="reflect.txt")\n'
)
_COMPATIBLE_MODEL_INIT = '''        if _starnet_framework == "documented":
            super().__init__(agent_graph, llm, prompt_path=str(prompt_path.resolve()), reflect_file="reflect.txt")
        else:
            # The legacy agent_mesa API from the published Starter Kit only
            # accepts the graph and injected LLM.
            super().__init__(agent_graph, llm)
'''
_MALFORMED_NESTED_MODEL_INIT = '''        if _starnet_framework == "documented":
            if _starnet_framework == "documented":
            super().__init__(agent_graph, llm, prompt_path=str(prompt_path.resolve()), reflect_file="reflect.txt")
        else:
            # The legacy agent_mesa API from the published Starter Kit only
            # accepts the graph and injected LLM.
            super().__init__(agent_graph, llm)
        else:
            # The legacy agent_mesa API from the published Starter Kit only
            # accepts the graph and injected LLM.
            super().__init__(agent_graph, llm)
'''


def inject_framework_compat(source: str) -> tuple[str, bool]:
    """Support both the documented and legacy official framework import names."""
    if FRAMEWORK_COMPAT_MARKER in source:
        repaired = source.replace(_MALFORMED_NESTED_MODEL_INIT, _COMPATIBLE_MODEL_INIT, 1)
        return repaired, repaired != source
    if LEGACY_FRAMEWORK_COMPAT_MARKER in source:
        start = source.index(LEGACY_FRAMEWORK_COMPAT_MARKER)
        legacy_end_line = '    _starnet_framework = "agent_mesa"\n'
        end = source.index(legacy_end_line, start) + len(legacy_end_line)
        legacy_block = source[start:end]
        replacement = (
            FRAMEWORK_COMPAT_IMPORT_WITH_JSON_STEP
            if "JsonStep" in legacy_block
            else FRAMEWORK_COMPAT_IMPORT
        )
        patched = source[:start] + replacement + source[end:]
        upgraded_legacy_block = True
    else:
        upgraded_legacy_block = False
        for old_import, replacement in _FRAMEWORK_IMPORT_TEMPLATES:
            if old_import in source:
                patched = source.replace(old_import, replacement, 1)
                break
        else:
            raise ValueError("提交文件中未找到框架 ModelBase 导入")
    patched = patched.replace(
        'if _starnet_framework == "casevo":',
        'if _starnet_framework == "documented":',
    )
    if not upgraded_legacy_block and _CASEVO_MODEL_INIT in patched:
        patched = patched.replace(_CASEVO_MODEL_INIT, _COMPATIBLE_MODEL_INIT, 1)
    return patched, True


_CMG_CUT_CANDIDATES_DEFINITION = "def _cut_candidates(board: Blackboard, limit: int) -> list[Action]:"
_CMG_CUT_CANDIDATES_CALL = "actions.extend(_cut_candidates(board, cut_limit))"


def inject_cmg_symbol_collision_fix(source: str) -> tuple[str, bool]:
    """Rename CMG's private cut helper after single-file inlining.

    ``candidates.py`` already owns ``_cut_candidates`` with a five-argument
    signature.  The CMG helper used the same global name with two arguments,
    so the later inline definition overwrote the candidate generator.
    """
    if "def _cmg_cut_candidates(board: Blackboard, limit: int) -> list[Action]:" in source:
        return source, False
    has_definition = _CMG_CUT_CANDIDATES_DEFINITION in source
    has_call = _CMG_CUT_CANDIDATES_CALL in source
    if not has_definition and not has_call:
        return source, False
    if not has_definition or not has_call:
        raise ValueError("提交文件中未找到可修补的 CMG cut helper")
    patched = source.replace(
        _CMG_CUT_CANDIDATES_DEFINITION,
        "def _cmg_cut_candidates(board: Blackboard, limit: int) -> list[Action]:",
        1,
    )
    patched = patched.replace(
        _CMG_CUT_CANDIDATES_CALL,
        "actions.extend(_cmg_cut_candidates(board, cut_limit))",
        1,
    )
    return patched, True
