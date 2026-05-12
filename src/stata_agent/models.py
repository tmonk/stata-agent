"""Pydantic models for internal use only.

These are plain dataclasses — no Pydantic dependency required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LogFormat(Enum):
    TEXT = "text"
    SMCL = "smcl"


class TaskStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StructuredError:
    rc: int
    message: str
    context: str
    marker_found: bool
    source: str  # "marker" | "r_code" | "assertion" | "mata" | "fallback"


@dataclass
class GraphDelta:
    created: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    current: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)


@dataclass
class TaskRecord:
    task_id: str = ""
    session_id: str = "default"
    code: str = ""
    is_file: bool = False
    echo: bool = True
    status: TaskStatus = TaskStatus.QUEUED
    created_at: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    rc: Optional[int] = None
    percent: float = 0.0
    eta_seconds: Optional[float] = None
    log_path: Optional[str] = None
    error: Optional[str] = None
    stdout: Optional[str] = None


@dataclass
class RunResult:
    ok: bool
    rc: int
    stdout: str = ""
    log_path: str = ""
    graphs: Optional[GraphDelta] = None
    task_id: Optional[str] = None
    error: Optional[str] = None
    error_context: Optional[str] = None
    truncated: bool = False
