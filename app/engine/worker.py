"""Run file analysis in isolated worker processes.

Parsing untrusted files is the riskiest thing this system does, so it never
happens inside the web server process:
  * each analysis runs in a separate OS process (pebble pool),
  * it is killed if it takes longer than ANALYSIS_TIMEOUT seconds,
  * on Linux the worker's memory and CPU time are capped,
  * workers are recycled after a number of jobs so a corrupted state can't persist.
"""
from __future__ import annotations

import asyncio
import multiprocessing
import os
from concurrent.futures import TimeoutError as FutTimeout

from pebble import ProcessPool

_pool: ProcessPool | None = None


def _limit_resources():
    try:
        import resource
        mem = int(os.environ.get("WORKER_MAX_MEMORY_MB", "1536")) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        cpu = int(os.environ.get("WORKER_MAX_CPU_SECONDS", "300"))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:  # Windows: no rlimits; timeouts still apply
        pass


def _run(data: bytes, filename: str, context: dict, config: dict) -> dict:
    from .pipeline import analyse
    return analyse(data, filename, context, config)


def start(workers: int = 2):
    global _pool
    if _pool is None:
        _pool = ProcessPool(max_workers=workers, max_tasks=25, initializer=_limit_resources,
                            context=multiprocessing.get_context("spawn"))


def stop():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool.join(timeout=5)
        _pool = None


async def analyse_isolated(data: bytes, filename: str, context: dict, config: dict, timeout: int = 90) -> dict:
    if _pool is None:
        start()
    future = _pool.schedule(_run, args=(data, filename, context, config), timeout=timeout)
    try:
        return await asyncio.wrap_future(future)
    except FutTimeout:
        return {"status": "error", "error": "Analysis took too long and was stopped", "suggested_name": None,
                "fields": {}, "confidence": 0.0, "warnings": ["Timed out"]}
    except Exception as e:   # worker crashed (e.g. memory limit hit by a hostile file)
        return {"status": "error", "error": f"File could not be analysed safely ({type(e).__name__})",
                "suggested_name": None, "fields": {}, "confidence": 0.0, "warnings": ["Worker stopped"]}
