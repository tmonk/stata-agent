"""pystata client — all Stata operations via SFI.

This module wraps pystata/SFI calls. It never runs in the daemon
process — only inside worker subprocesses.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

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
            # If pystata hasn't been configured yet (config.stlib is None),
            # try to auto-discover and initialise it via stata_setup.
            from pystata import config as _pystata_config

            if _pystata_config.stlib is None:
                import stata_setup
                from stata_agent.discovery import find_stata_path

                # find_stata_path returns the binary path; we need the root
                # directory that contains utilities/ for stata_setup.config().
                bin_path, edition = find_stata_path()
                bin_dir = os.path.dirname(os.path.abspath(bin_path))
                root = bin_dir
                for _ in range(5):
                    if os.path.isdir(os.path.join(root, "utilities")):
                        break
                    parent = os.path.dirname(root)
                    if parent == root:
                        root = None
                        break
                    root = parent
                if root is None:
                    raise ValueError(
                        f"Cannot find Stata root directory (with utilities/) "
                        f"from binary path: {bin_path}"
                    )
                stata_setup.config(root, edition, splash=False)

            from sfi import Macro, Data  # noqa: F401
            self._sfi_available = True
        except Exception as exc:
            self._sfi_available = False
            raise ImportError(
                "pystata/SFI not available. Run this worker inside Stata's "
                "Python or install pystata via stata_setup. Error: " + str(exc)
            )

        # Open a text-mode log
        self._log_path = self._rotator.current_path

        self._stata_run(
            f'cap log close _agent_session',
            echo=False,
        )
        self._stata_run(
            f'log using "{self._log_path}", replace text name(_agent_session)',
            echo=False,
        )

        self._initialised = True

    def close(self) -> None:
        """Clean up Stata resources."""
        if self._initialised:
            try:
                self._stata_run('cap log close _agent_session', echo=False)
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
        """Execute Stata code and return structured result.

        Uses StataSO_Execute() directly to get the return code from Stata's
        C API — no log-file parsing needed for error detection.
        """
        self._ensure_initialised()
        self._rotate_if_needed()
        if pre_allocated_log:
            self._log_path = Path(pre_allocated_log)

        # Snapshot graphs before
        before = self.snapshot_graphs()

        # Execute code directly (capture wrapper removed — StataSO_Execute
        # returns the rc directly for the outermost command). If code has
        # multiple lines and one fails, Stata stops at the first error.
        stdout, rc = self._stata_run(code, echo=echo)

        # Snapshot graphs after
        after = self.snapshot_graphs()
        delta = compute_graph_delta(before, after)

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

        # Run do-file directly — StataSO_Execute returns the rc
        cmd = f'do "{path}"'
        stdout, rc = self._stata_run(cmd, echo=echo)
        after = self.snapshot_graphs()
        delta = compute_graph_delta(before, after)

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
        return {
            "variables": vars_info,
            "obs_count": Data.getObsTotal(),
            "var_count": Data.getVarCount(),
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
        obs_clause = self._get_obs_range_clause(obs_range) if obs_range else ""

        if format == "csv":
            # `export delimited` syntax: [varlist] using filename [, options]
            # Variables go before `using`, not after options.
            vl_part = varlist if varlist else ""
            cmd = f'export delimited {vl_part} using "{out_path}", replace{obs_clause}'
            self._stata_run(cmd.strip(), echo=False)
        elif format == "json":
            self._stata_run(f'jsonio set output "{out_path}", replace', echo=False)
            vl_part = varlist if varlist else "_all"
            self._stata_run(f"jsonio export {vl_part}{obs_clause}", echo=False)
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
        self._stata_run(f'graph export "{out_path}", replace as({fmt})', echo=False)
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
        # Use tail-only error extraction
        log_path_str = str(self._log_path) if self._log_path else ""
        if log_path_str:
            error = self._extractor.extract_from_tail(log_path_str)
        else:
            error = None
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

    def _stata_run(self, code: str, echo: bool = False) -> tuple[str, int]:
        """Execute code in Stata and capture output + return code directly.

        Gets the rc from Stata's C API via StataSO_Execute() instead of
        parsing the log file. Temporarily switches streamout to off so we
        can use the non-streaming output path with RedirectOutput.

        For multi-line code, writes a temporary do-file and uses
        ``include`` — ``StataSO_Execute`` propagates the do-file's exit
        code through the include command's return value. For single-line
        code, executes directly.

        Returns:
            (output_text, return_code)
        """
        import io
        import os
        import tempfile
        from pathlib import Path
        from pystata import config
        from pystata.core import stout

        # Split into lines to determine approach
        lines = code.splitlines()
        # Remove blank/whitespace-only lines for detection
        non_blank = [ln for ln in lines if ln.strip()]

        capture = io.StringIO()
        original_stoutputf = config.stoutputf
        config.stoutputf = capture

        # Switch to non-streaming mode for clean output capture
        original_streamout = config.stconfig.get('streamout', 'on')
        config.stconfig['streamout'] = 'off'

        config.stlib.StataSO_ClearOutputBuffer()
        rc = 0

        def _flush_output():
            """Flush remaining output from Stata's buffer to our StringIO."""
            from pystata.stata import _print_no_streaming_output
            output = config.get_output()
            while len(output) != 0:
                _print_no_streaming_output(output, False)
                output = config.get_output()

        try:
            if len(non_blank) == 1:
                # Single line — execute directly via StataSO_Execute
                with stout.RedirectOutput(stout.StataDisplay(), stout.StataError()):
                    rc = config.stlib.StataSO_Execute(
                        config.get_encode_str(code), echo
                    )
                _flush_output()
            else:
                # Multi-line code — write temp do-file and include.
                # StataSO_Execute propagates the do-file's error code back
                # through the include command's return value.
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".do", delete=False, encoding="utf-8"
                ) as f:
                    f.write(code)
                    tmp_path = f.name

                try:
                    with stout.RedirectOutput(
                        stout.StataDisplay(), stout.StataError(),
                        echo if echo else None,
                    ):
                        rc = config.stlib.StataSO_Execute(
                            config.get_encode_str(f'include "{tmp_path}"'),
                            False,
                        )
                    _flush_output()

                    # rc from StataSO_Execute on include already propagates
                    # the do-file exit code correctly
                finally:
                    try:
                        Path(tmp_path).unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception as exc:
            # If anything goes wrong, preserve whatever output we have
            pass
        finally:
            config.stoutputf = original_stoutputf
            config.stconfig['streamout'] = original_streamout

        return capture.getvalue().strip(), rc

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
                f'cap log close _agent_session',
                echo=False,
            )
            self._log_path = new_path
            self._stata_run(
                f'log using "{self._log_path}", replace text name(_agent_session)',
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
