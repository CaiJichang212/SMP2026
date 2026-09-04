"""Starter Kit 的本地运行时导入契约。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
import unittest

from casevo import LLM_INTERFACE


STARTER_KIT = Path(__file__).resolve().parents[2] / "SMP_Starter_Kit"
sys.path.insert(0, str(STARTER_KIT))


class StarterKitImportTests(unittest.TestCase):
    def test_zhipu_adapter_uses_casevo_llm_interface(self) -> None:
        zhipu = importlib.import_module("zhipu")

        self.assertIs(zhipu.LLM_INTERFACE, LLM_INTERFACE)
        self.assertTrue(issubclass(zhipu.ZhipuLLM, LLM_INTERFACE))
