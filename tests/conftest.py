from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


@pytest.fixture
def load_app():
    loaded_paths: list[str] = []

    def load(relative_path: str) -> ModuleType:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]

        service_path = str(ROOT / relative_path)
        sys.path.insert(0, service_path)
        loaded_paths.append(service_path)
        try:
            return importlib.import_module("app.main")
        finally:
            sys.path.remove(service_path)

    yield load

    for service_path in loaded_paths:
        if service_path in sys.path:
            sys.path.remove(service_path)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
