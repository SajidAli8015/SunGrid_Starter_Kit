"""Clean-clone check: does a fresh clone install, test and run offline commands?

Clones the committed state of this repo into a temporary folder, creates a fresh venv, installs, runs
pytest, then runs `ingest`, `search` and `check-llm` with LLM_PROVIDER=fake. Prints PASS/FAIL and the
elapsed time per step. Cross-platform (Windows, macOS, Linux); needs git and network access for pip and
the embedding model.

It never reads `.env` (the clone has none, since it is git-ignored) and strips provider credentials from
the environment it passes on, so no real key can be used.

Usage:
    python scripts/clean_clone_check.py [--keep] [--reuse-model-cache]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CREDENTIAL_PREFIXES = ("AZURE_OPENAI_", "OPENAI_", "ANTHROPIC_", "GEMINI_")
STEP_TIMEOUT_S = 1800
TAIL_LINES = 15


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def clean_env(model_cache: Path | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(CREDENTIAL_PREFIXES)}
    env["LLM_PROVIDER"] = "fake"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("VIRTUAL_ENV", None)
    if model_cache is not None:
        env["FASTEMBED_CACHE_PATH"] = str(model_cache)
    return env


def run_step(name: str, cmd: list[str], cwd: Path, env: dict[str, str], results: list) -> bool:
    print(f"\n--- {name}: {' '.join(cmd)}", flush=True)
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=STEP_TIMEOUT_S,
        )
        ok, output = proc.returncode == 0, proc.stdout + proc.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        ok, output = False, f"{type(e).__name__}: {e}"
    elapsed = time.perf_counter() - start
    tail = "\n".join(output.strip().splitlines()[-TAIL_LINES:])
    if tail:
        print(tail)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  ({elapsed:.1f}s)", flush=True)
    results.append((name, ok, elapsed))
    return ok


def _remove(path: Path) -> None:
    def make_writable(func, p, _exc):  # git object files are read-only on Windows
        os.chmod(p, 0o700)
        func(p)

    shutil.rmtree(path, onerror=make_writable)


def main() -> int:
    # Child output (e.g. download progress bars) may not fit the console code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="Keep the temporary folder")
    parser.add_argument(
        "--reuse-model-cache", action="store_true",
        help="Use the normal fastembed cache instead of downloading the model into a fresh one",
    )
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="sungrid_clean_clone_"))
    clone, venv = workdir / "repo", workdir / "venv"
    model_cache = None if args.reuse_model_cache else workdir / "fastembed_cache"
    env = clean_env(model_cache)
    results: list[tuple[str, bool, float]] = []
    print(f"Repo:    {REPO}\nWorkdir: {workdir}")

    setup = [
        ("git clone", ["git", "clone", "--quiet", str(REPO), str(clone)], workdir),
        ("create venv", [sys.executable, "-m", "venv", str(venv)], workdir),
        ("pip install -r requirements.txt",
         [str(venv_python(venv)), "-m", "pip", "install", "-q", "-r", "requirements.txt"], clone),
        ("pip install -e .", [str(venv_python(venv)), "-m", "pip", "install", "-q", "-e", "."], clone),
    ]
    py = str(venv_python(venv))
    cli = [py, "-m", "sungrid_copilot.cli"]
    checks = [
        ("pytest", [py, "-m", "pytest", "-q"], clone),
        ("ingest (fake LLM)", [*cli, "ingest"], clone),
        ("search (fake LLM)",
         [*cli, "search", "How long do I have to appeal a rebate decision?", "--top-k", "3"], clone),
        ("check-llm (fake LLM)", [*cli, "check-llm"], clone),
    ]

    setup_ok = all(run_step(name, cmd, cwd, env, results) for name, cmd, cwd in setup)
    if setup_ok:
        for name, cmd, cwd in checks:
            run_step(name, cmd, cwd, env, results)
    else:
        results += [(name, False, 0.0) for name, _, _ in checks]
        print("\nSetup failed; later steps not run.")

    print("\n=== Clean-clone check summary")
    for name, ok, elapsed in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<34} {elapsed:7.1f}s")
    passed = all(ok for _, ok, _ in results)
    print(f"OVERALL: {'PASS' if passed else 'FAIL'}")

    if args.keep:
        print(f"Kept: {workdir}")
    else:
        try:
            _remove(workdir)
        except OSError as e:
            print(f"Could not remove {workdir}: {e}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
