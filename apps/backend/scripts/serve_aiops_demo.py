"""Serve the backend with the local mock demonstration configuration.

The tracked configuration keeps the development defaults, including the timeout
budget the tests pin, and `config/user.project.json` stays a plain local
override. The demonstration values live in the ignored
`config/demo.project.json`; they are merged on top of the two local files here
and written next to the runtime logs, so no tracked file carries demo values or
secrets.

Run from `apps/backend`:

    uv run python scripts/serve_aiops_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import uvicorn

from super_ai.api.app import create_app
from super_ai.project_config import load_project_config

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEMO_OVERRIDES_PATH = BACKEND_ROOT.parents[1] / "config" / "demo.project.json"
MERGED_CONFIG_PATH = BACKEND_ROOT / "var" / "demo.project.json"


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge(current, value)
        else:
            merged[key] = value
    return merged


def main() -> int:
    if not DEMO_OVERRIDES_PATH.exists():
        print(f"缺少演示覆盖配置：{DEMO_OVERRIDES_PATH}", file=sys.stderr)
        print("请先创建该文件并写入 llm 与 aiopsDiagnosis 的演示值。", file=sys.stderr)
        return 1
    overrides: dict[str, Any] = json.loads(DEMO_OVERRIDES_PATH.read_text(encoding="utf-8"))
    merged = _merge(dict(load_project_config()), overrides)
    MERGED_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MERGED_CONFIG_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"演示配置：{MERGED_CONFIG_PATH}")
    uvicorn.run(
        create_app(project_config_path=str(MERGED_CONFIG_PATH)),
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
