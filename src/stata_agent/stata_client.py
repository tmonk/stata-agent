"""pystata client — all Stata operations via SFI.

This module wraps pystata/SFI calls. It never runs in the daemon
process — only inside worker subprocesses.
"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from stata_agent.error_extractor import ErrorExtractor
from stata_agent.log_manager import (
    LogRotator,
    tail_file,
    truncate_for_agent,
    truncate_for_error,
    search_in_log,
    paginated_read,
)
from stata_agent.models import RunResult, GraphDelta

LOG_DIR_DEFAULT = Path.home() / ".cache" / "stata-agent" / "logs"


class StataClient:
    """Wrapper around pystata for all Stata operations.

    This must be initialised inside a Python process that has pystata
    available (Stata's bundled Python, or after stata_setup).
    """

    def __init__(self, session_name: str = "default", log_dir: str | Path | None = None):
        self.session_name = session_name
        self.log_dir = Path(log_dir) if log_dir else LOG_DIR_DEFAULT
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._rotator = LogRotator(session_name, log_dir=self.log_dir)
        self._extractor = ErrorExtractor()
        self._initialised = False
        self._sfi_available = False

    def init(self) -> None:
        """Initialise pystata. Call this once at worker startup."""
        if self._initialised:
            return

        try:
            from sfi import Macro, Data  # noqa: F401
            self._sfi_available = True
        except ImportError:
            self._sfi_available = False
            raise ImportError(
                "pystata/SFI not available. Run this worker inside Stata's "
                "Python or install pystata via stata_setup."
            )

        # Initialise Stata engine
        try:
            import pystata
            pystata.config.init("none")
        except Exception:
            pass

        # Open a text-mode log
        self._log_path = self._rotator.current_path

        self._stata_run(
            f'cap log close _mcp_session',
            echo=False,
        )
        self._stata_run(
            f'log using "{self._log_path}", replace text name(_mcp_session)',
            echo=False,
        )

        self._initialised = True

    def close(self) -> None:
        """Clean up Stata resources."""
        if self._initialised:
            try:
                self._stata_run('cap log close _mcp_session', echo=False)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Core command execution
    # ------------------------------------------------------------------

    def run(
        self,
        code: str,
        echo: bool = True,
        max_output_tokens: int = 1000,
        strict: bool = False,
        pre_allocated_log: str | None = None,
    ) -> RunResult:
        """Execute Stata code and return structured result."""
        self._ensure_initialised()
        self._rotate_if_needed()
        if pre_allocated_log:
            self._log_path = Path(pre_allocated_log)

        # Snapshot graphs before
        before = self.snapshot_graphs()

        if strict:
            cmd = code
        else:
            # Wrap in capture noisily with structured markers
            escaped = code.replace('"', '""')
            cmd = (
                f'capture noisily {{\n'
                f'    {code}\n'
                f'}}\n'
                f'if _rc != 0 {{\n'
                f'    display as error "[MCP-ERROR] rc=" _rc\n'
                f'    display as error "[MCP-MSG] `:display _rc[message]\\\'\n'
                f'}}'
            )

        stdout = self._stata_run(cmd, echo=echo)

        # Snapshot graphs after
        after = self.snapshot_graphs()
        delta = compute_graph_delta(before, after)

        # Read log and check for errors
        log_text = self._read_log_tail()
        error = self._extractor.extract(log_text)

        rc = error.rc if error else 0
        ok = rc == 0

        if ok:
            output, truncated = truncate_for_agent(stdout, max_output_tokens * 4)
        else:
            output = truncate_for_error(stdout)
            truncated = True

        return RunResult(
            ok=ok,
            rc=rc,
            stdout=output,
            log_path=str(self._log_path),
            graphs=delta,
            truncated=truncated,
        )

    def run_file(
        self,
        path: str,
        echo: bool = True,
        strict: bool = False,
    ) -> RunResult:
        """Execute a do-file and return structured result."""
        self._ensure_initialised()
        self._rotate_if_needed()

        before = self.snapshot_graphs()

        if strict:
            cmd = f'do "{path}"'
        else:
            cmd = (
                f'capture noisily {{\n'
                f'    do "{path}"\n'
                f'}}\n'
                f'if _rc != 0 {{\n'
                f'    display as error "[MCP-ERROR] rc=" _rc\n'
                f'    display as error "[MCP-MSG] `:display _rc[message]\\\'\n'
                f'}}'
            )

        stdout = self._stata_run(cmd, echo=echo)
        after = self.snapshot_graphs()
        delta = compute_graph_delta(before, after)

        log_text = self._read_log_tail()
        error = self._extractor.extract(log_text)
        rc = error.rc if error else 0
        ok = rc == 0

        if ok:
            output, truncated = truncate_for_agent(stdout, 4000)
        else:
            output = truncate_for_error(stdout)
            truncated = True

        return RunResult(
            ok=ok,
            rc=rc,
            stdout=output,
            log_path=str(self._log_path),
            graphs=delta,
            truncated=truncated,
        )

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def inspect_describe(self, varlist: str | None = None, fullnames: bool = False) -> dict:
        self._ensure_initialised()
        fn_opt = ", fullnames" if fullnames else ""
        vl = varlist or ""
        self._stata_run(f"describe {vl}{fn_opt}", echo=False)
        from sfi import Data
        vars_info = []
        for i in range(Data.getVarCount()):
            name = Data.getVarName(i)
            lbl = Data.getVarLabel(i)
            typ = Data.getVarType(i)
            vars_info.append({"name": name, "label": lbl, "type": typ})
        dataset_name = ""
        try:
            dataset_name = Data.getDataset() or ""
        except AttributeError:
            # sfi.Data.getDataset() not available in all Stata versions
            pass
        return {
            "variables": vars_info,
            "obs_count": Data.getObsTotal(),
            "var_count": Data.getVarCount(),
            "dataset_name": dataset_name,
        }

    def inspect_summary(self, varlist: str | None = None) -> dict:
        self._ensure_initialised()
        vl = varlist or ""
        self._stata_run(f"summarize {vl}, detail", echo=False)
        # Return the logged output as text
        log_text = self._read_log_tail()
        return {"text": log_text}

    def inspect_codebook(self, varlist: str | None = None) -> dict:
        self._ensure_initialised()
        vl = varlist or ""
        self._stata_run(f"codebook {vl}", echo=False)
        log_text = self._read_log_tail()
        return {"text": log_text}

    def inspect_list(
        self,
        varlist: str | None = None,
        from_row: int | None = None,
        count: int | None = None,
    ) -> dict:
        self._ensure_initialised()
        vl = varlist or ""
        in_clause = ""
        if from_row is not None and count is not None:
            in_clause = f" in {from_row}/{from_row + count - 1}"
        self._stata_run(f"list {vl}{in_clause}", echo=False)
        log_text = self._read_log_tail()
        return {"text": log_text}

    def inspect_get(
        self,
        format: str = "csv",
        out_path: str | None = None,
        varlist: str | None = None,
        obs_range: str | None = None,
    ) -> dict:
        self._ensure_initialised()
        if out_path is None:
            fd, out_path = tempfile.mkstemp(suffix=f".{format}")
            os.close(fd)
        vl = varlist or "_all"
        obs_clause = self._get_obs_range_clause(obs_range) if obs_range else ""

        if format == "csv":
            self._stata_run(f'export delimited using "{out_path}", replace {vl}{obs_clause}', echo=False)
        elif format == "json":
            self._stata_run(f'jsonio set output "{out_path}", replace', echo=False)
            self._stata_run(f"jsonio export {vl}{obs_clause}", echo=False)
        elif format == "arrow":
            try:
                import pyarrow as pa
                from sfi import Data

                # Build pyarrow table from SFI
                var_count = Data.getVarCount()
                var_names = [Data.getVarName(i) for i in range(var_count)]

                # Select requested variables
                selected = var_names
                if varlist:
                    if isinstance(varlist, str):
                        varlist = varlist.split()
                    selected = [v for v in var_names if v in varlist]

                # Determine obs range
                obs_total = Data.getObsTotal()
                if obs_range:
                    parts = obs_range.split(":")
                    obs_start = max(0, int(parts[0]) - 1)
                    obs_end = min(int(parts[1]), obs_total)
                else:
                    obs_start = 0
                    obs_end = obs_total

                # Build columns
                arrays = []
                for name in selected:
                    idx = Data.getVarIndex(name)
                    col = []
                    for obs_idx in range(obs_start, obs_end):
                        val = Data.get(idx, obs_idx)
                        col.append(val)
                    arrays.append(pa.array(col))

                schema = pa.schema([
                    (name, pa.float64() if arrays[i].type == pa.null() else arrays[i].type)
                    for i, name in enumerate(selected)
                ])
                table = pa.Table.from_arrays(arrays, schema=schema)

                with pa.OSFile(str(out_path), "wb") as sink:
                    with pa.ipc.new_file(sink, table.schema) as writer:
                        writer.write_table(table)

                size = os.path.getsize(out_path)
                return {"path": out_path, "size_bytes": size}
            except ImportError:
                raise ValueError("pyarrow not installed; use --format csv or json instead")
        else:
            raise ValueError(f"Unsupported format: {format}")
        size = os.path.getsize(out_path)
        return {"path": out_path, "size_bytes": size}

    def _get_obs_range_clause(self, obs_range: str) -> str:
        """Parse 'start:end' obs_range into a Stata in clause."""
        if not obs_range:
            return ""
        try:
            parts = obs_range.split(":")
            start = int(parts[0])
            end = int(parts[1])
            return f" in {start}/{end}"
        except (ValueError, IndexError):
            return ""
    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def get_results(self, result_class: str = "r") -> dict:
        """Retrieve stored results (r(), e(), s())."""
        self._ensure_initialised()
        from sfi import Macro
        result_class = result_class.lower()
        if result_class not in ("r", "e", "s"):
            raise ValueError(f"Invalid result class: {result_class} (use r, e, or s)")
        # Use Stata's return list to retrieve results, then read via Macro
        cmd_map = {"r": "return list", "e": "ereturn list", "s": "sreturn list"}
        self._stata_run(cmd_map[result_class], echo=False)
        log_text = self._read_log_tail()
        # Also try to read specific r-class macros via sfi
        stored = {}
        try:
            for name in ("N", "mean", "sd", "min", "max", "sum", "Var", "level", "se", "t", "df_r", "F", "p", "ll", "ll_0", "chi2", "r2", "r2_a", "N_missing", "N_present", "N_total"):
                val = Macro.getGlobal(f"{result_class}({name})")
                if val is not None and val != "":
                    stored[name] = val
        except Exception:
            pass
        return {"class": result_class, "stored_results": stored, "log": log_text}

    # ------------------------------------------------------------------
    # Graphs
    # ------------------------------------------------------------------

    def snapshot_graphs(self) -> set[str]:
        """Return the set of graph names currently in memory."""
        if not self._sfi_available:
            return set()
        try:
            from sfi import Macro
            self._stata_run("quietly graph dir, memory", echo=False)
            raw = Macro.getGlobal("r(list)")
            if raw is not None and raw.strip() and raw.strip() != " ":
                return set(raw.split())
            return set()
        except Exception:
            return set()

    def export_graph(self, name: str | None, fmt: str, out_path: str) -> dict:
        """Export a graph to a file."""
        self._ensure_initialised()
        if name:
            self._stata_run(f'graph display "{name}"', echo=False)
        self._stata_run(f'graph export "{out_path}", replace {fmt}', echo=False)
        size = os.path.getsize(out_path)
        return {"file_path": out_path, "size_bytes": size}

    # ------------------------------------------------------------------
    # Log access
    # ------------------------------------------------------------------

    def read_log_tail(self, lines: int = 50, bytes: int = 0) -> str:
        """Read the tail of the current log file."""
        if bytes > 0:
            return tail_file(self._log_path, lines=0, bytes=bytes)
        return tail_file(self._log_path, lines=lines)

    def get_log_errors(self, context_lines: int = 20) -> dict:
        """Extract errors from the current log."""
        log_text = self._read_log_tail()
        error = self._extractor.extract(log_text)
        if error is None:
            return {"rc": None, "message": None, "context": None, "source": None}
        return {
            "rc": error.rc,
            "message": error.message,
            "context": error.context,
            "source": error.source,
            "marker_found": error.marker_found,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_initialised(self) -> None:
        if not self._initialised:
            raise RuntimeError("StataClient not initialised. Call init() first.")

    def _stata_run(self, code: str, echo: bool = False) -> str:
        """Execute code in Stata and capture output."""
        from sfi import Data  # noqa: F401 — ensure SFI is loaded
        try:
            import pystata
            from IPython.utils.capture import capture_output

            with capture_output() as cap:
                pystata.stata.run(code, quietly=not echo)
            return cap.stdout
        except ImportError:
            # Fallback if IPython capture isn't available
            import pystata
            pystata.stata.run(code, quietly=not echo)
            # Read the last N lines from log
            return self._read_log_tail()

    def _read_log_tail(self) -> str:
        """Read recent log content for error extraction."""
        try:
            if self._log_path and Path(self._log_path).exists():
                return Path(self._log_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        return ""

    def _rotate_if_needed(self) -> None:
        """Rotate log if the current one exceeds size/command limits."""
        old_path = self._log_path
        new_path = self._rotator.rotate_if_needed()
        if new_path != old_path:
            self._stata_run(
                f'cap log close _mcp_session',
                echo=False,
            )
            self._log_path = new_path
            self._stata_run(
                f'log using "{self._log_path}", replace text name(_mcp_session)',
                echo=False,
            )


# ------------------------------------------------------------------
# Graph delta computation (pure function, no Stata needed)
# ------------------------------------------------------------------

def compute_graph_delta(before: set[str], after: set[str]) -> dict:
    """Compare pre- and post-execution graph snapshots.

    Returns: {"created": [...], "dropped": [...], "current": [...]}
    """
    return {
        "created": sorted(after - before),
        "dropped": sorted(before - after),
        "current": sorted(after),
    }
