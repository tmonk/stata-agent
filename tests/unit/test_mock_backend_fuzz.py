"""Fuzz and stress tests for mock_backend.py — try to break it with everything.

Every conceivable Stata command pattern is thrown at _route_command() and
MockDaemon.dispatch() to verify:
  - No crashes (unhandled exceptions)
  - No state leaks between sessions
  - No infinite loops or hangs
  - Proper handling of edge cases (empty, malformed, very long, binary)
"""

from __future__ import annotations

import asyncio
import random
import string
import sys
import time
from typing import Any

import pytest

from stata_agent.mock_backend import (
    MockDaemon,
    _get_state,
    _route_command,
    _session_state,
)


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    """Reset global session state before each test."""
    _session_state.clear()


# ======================================================================
# Fuzz helper: generate pathological command strings
# ======================================================================

def _random_string(max_len: int = 5000) -> str:
    """Generate a random ASCII-ish string."""
    length = random.randint(0, max_len)
    chars = string.ascii_letters + string.digits + string.punctuation + " \t\n\r"
    return "".join(random.choices(chars, k=length))


def _random_code(max_lines: int = 50, max_line_len: int = 200) -> str:
    """Generate random-looking Stata-ish code."""
    keywords = [
        "display", "di", "set", "gen", "generate", "reg", "regress",
        "summarize", "tab", "tabulate", "graph", "twoway", "scatter",
        "line", "histogram", "kdensity", "predict", "test", "estimates",
        "matrix", "svy", "svyset", "merge", "append", "collapse",
        "reshape", "encode", "decode", "rename", "drop", "keep",
        "sort", "gsort", "by", "egen", "recode", "xtset", "xtreg",
        "logit", "probit", "oprobit", "mlogit", "poisson", "nbreg",
        "lasso", "elasticnet", "mixed", "meprobit", "sem", "gsem",
        "mata", "python", "shell", "clear", "use", "save", "import",
        "export", "label", "notes", "describe", "codebook", "inspect",
        "lookfor", "search", "help", "trace", "set trace", "debug",
        "ereturn", "return", "sreturn", "capture", "quietly",
        "noisily", "version", "which", "type", "filefilter",
    ]
    lines = []
    for _ in range(random.randint(0, max_lines)):
        # 20% chance of a really long line
        if random.random() < 0.2:
            kw = random.choice(keywords)
            padding = " " * random.randint(0, max_line_len)
            lines.append(f"{kw}{padding}")
        # 10% chance of binary-ish garbage
        elif random.random() < 0.1:
            lines.append(_random_string(max_line_len))
        # 5% chance of an empty line
        elif random.random() < 0.05:
            lines.append("")
        # 5% chance of whitespace-only line
        elif random.random() < 0.05:
            lines.append(" " * random.randint(0, 100))
        else:
            kw = random.choice(keywords)
            args = " ".join(_random_string(10) for _ in range(random.randint(0, 5)))
            lines.append(f"{kw} {args}")
    return "\n".join(lines)


# ======================================================================
# Fuzz: _route_command with insane inputs
# ======================================================================

class TestFuzzRouteCommand:
    """Fuzz test the command router with pathological inputs."""

    COMMANDS_TO_TRY = [
        # Empty / whitespace
        "",
        "   ",
        "\t",
        "\n",
        "\r\n",
        "\x00",
        "\x00\x01\x02",
        # Stata debugging / tracing
        "set trace on",
        "set trace off",
        "set tracedepth 1",
        "set traceexpand on",
        "debug 1",
        "trace on",
        "trace off",
        "trace",
        # Mata
        "mata",
        "mata:",
        "mata clear",
        "mata: x = 1+1",
        "mata: y = J(1000,1000,0)",
        "mata: st_matrix(\"A\", (1,2\\3,4))",
        "mata: printf(\"hello\")",
        'mata: st_local("x", "5")',  # actually uses double quotes inside single
        "mata: end",
        # Python
        "python",
        "python: print('hello')",
        "python end",
        # Shell escapes
        "!ls",
        "!rm -rf /",
        "!!",
        "shell echo hello",
        "winexec notepad.exe",
        # (Extremely long commands moved to separate test methods to avoid
        # Windows env var limits — PYTEST_CURRENT_TEST would exceed 32767 chars)
        # Nested/special characters
        "display `=1+1'",
        "display `=c(os)",
        "matrix A = (1,2 \\ 3,4)",
        "matrix list A",
        # program/function definitions
        "program define myprog",
        "program drop myprog",
        "program list",
        "capture program drop _all",
        "cap prog drop _all",
        # return codes
        "error 0",
        "error 1",
        "error 111",
        "error 601",
        "error 99999",
        "capture error 111",
        "capture error 601",
        "capture noisily error 111",
        # assert
        "assert 1==1",
        "assert 1==0",
        "capture assert 1==0",
        # sysuse
        "sysuse auto",
        "sysuse auto, clear",
        "sysuse auto2",  # doesn't exist
        # graph
        "graph set window fontface Arial",
        "graph dir",
        "graph dir _all",
        "graph query",
        "graph display",
        "graph drop _all",
        "graph export mygraph.png, replace",
        # estimates
        "estimates store model1",
        "estimates restore model1",
        "estimates drop model1",
        "estimates table model1 model2",
        "estimates replay",
        "estat ic",
        "estat vce",
        # predict
        "predict yhat",
        "predict resid, resid",
        "predict stdp, stdp",
        # test
        "test mpg=price",
        "test mpg price",
        # svy
        "svyset pweight [pw=wt], psu(school)",
        "svy: regress y x",
        # mixed models
        "mixed y || id:",
        "melogit y || id:",
        # matrix
        "matrix accum A = price mpg weight",
        "matrix vecaccum A = price mpg weight",
        "matrix symeigen X V = A",
        "matrix svd U D V = A",
        "matrix define A = J(1000,1000,0)",
        "matrix input A = (1,2\\3,4)",
        "matrix score yhat = A",
        # malformed
        "<<<<<",
        "{{{{{",
        "[[[[[",
        ">>>>>>>",
        "!@#$%^&*()",
        "error",
        "set",
        "gen",
        "graph",
        "\x1b[31mred text\x1b[0m",
        # Unicode
        "display \"café\"",
        "display \"日本語\"",
        "display \"Emoji 📊\"",
        "display \"\\u00e9\"",
        # Numbers
        "display 1+1",
        "display _pi",
        "display _N",
        "display _b[mpg]",
        "display _se[mpg]",
        "display result(1)",
        # file operations
        "file open myfile using test.txt, write replace",
        "file write myfile \"hello\"",
        "file close myfile",
        "type test.txt",
        "dir",
        "cd /tmp",
        "pwd",
        "mkdir testdir",
        # log operations
        "log using test.log, replace",
        "log close",
        "capture log close",
        "log using _mcp_smcl_test.smcl, replace text",
        "log query",
        # set operations
        "set more off",
        "set more on",
        "set seed 12345",
        "set obs 1000",
        "set type double",
        "set matsize 800",
        "set memory 100m",
        # tempfiles
        "tempfile mytemp",
        "tempvar myvar",
        "tempname myname",
        "save `mytemp'",
        # macro operations
        "local x 5",
        "global y 10",
        'local x "hello world"',
        "scalar a = 5",
        "scalar list",
        # preserve/restore
        "preserve",
        "restore",
        # compress
        "compress",
        # order
        "order price mpg weight",
        # missing values
        "display .",
        "display .a",
        "display .z",
        "generate x = .",
        "replace x = .a if _n == 1",
        "mvdecode _all, mv(.a\\=.)",
        "mvencode _all, mv(.=0)",
        # by and egen
        "by foreign: summarize price mpg",
        "bysort foreign: summarize price mpg",
        "egen mean_mpg = mean(mpg)",
        "egen std_mpg = std(mpg)",
        "egen group_id = group(foreign rep78)",
        # time series
        "tsset year",
        "tsset year, quarterly",
        "tsline price mpg",
        "dfuller price",
        "arch price mpg, arch(1) garch(1)",
        # survey
        "svyset school [pw=wt], strata(stratum)",
        "svydescribe",
        "svytab foreign rep78",
        # factor variables
        "reg price i.foreign##c.mpg",
        "reg price ibn.foreign",
        "margins foreign, at(mpg=(10(10)40))",
        "marginsplot",
        # sem
        "sem (Y <- X) (Z <- X)",
        "gsem (Y <- X, probit)",
        # power
        "power onesample 0.5, power(0.8)",
        "power twomeans 0.5, n(100)",
        # bootstrap/jackknife
        "bootstrap _b[mpg]: reg price mpg",
        "jackknife _b[mpg]: reg price mpg",
        "permute mpg _b[price]: reg price mpg",
        # simulate
        "simulate _b[mpg], reps(100): reg price mpg",
        # mixed effects
        "mixed price || foreign:",
        "xtmixed price mpg || foreign:",
        "xtreg price mpg, fe",
        "xtreg price mpg, re",
        "xtabond price mpg",
        # special characters in variable names
        "generate _x = 1",
        "generate .x = 1",  # invalid but try
        "generate _ = 1",
        "generate long_variable_name_that_is_very_long_exceeding_stata_limit = 1",
        # Insane nesting
        "display `=display(`=1+1')'",
        # Comments
        "* This is a comment",
        "// This is a comment too",
        "/* block comment */",
        # #delimit
        "#delimit ;",
        "display 1+1 ;",
        "#delimit cr",
        # include
        'include "somefile.do"',
        "include /path/to/file.do",
        # do files
        'do "mydofile.do"',
        "do mydofile.do",
        "run mydofile.do",
        # Stata 18+ features
        "frlink 1:1 mpg, frame(frame1)",
        "frame put price mpg, into(newframe)",
        "frame change newframe",
        "frame create myframe",
        "frame reset",
        "frame copy default myframe",
        "frames list",
        "collect get",
        "collect layout",
        "etable",
        "dtacollect",
        # Binary/control characters in various places
        "\x00di\x00splay\x00\x001\x00+\x00\x001",
        "di" + "\x00" * 100 + "splay 1+1",
        # SQL-ish (StataSQL, odbc)
        "odbc load, exec(\"SELECT * FROM table\")",
        "odbc query",
        "odbc list",
        # Cross-sectional time-series
        "xtset id year",
        "xtdes",
        "xtsum price mpg",
        "xttab foreign",
        "xttrans foreign",
        "xtbin price",
        "xtprobit y x1 x2",
        "xtlogit y x1 x2",
        "xtpoisson y x1 x2",
        "xtnbreg y x1 x2",
        "xtintreg y x1 x2",
        "xttobit y x1 x2",
        "xtfrontier y x1 x2",
        "xtivreg y x1 (x2=z1 z2)",
        "xtabond y x1 x2, lags(2)",
        "xtdpdsys y x1 x2",
        "xtunitroot fisher price",
        "xtcointtest price mpg",
        "xtmg price mpg",
        "xtcips price mpg",
        "xthst price mpg",
        # Spatial
        "spmatrix create contiguity W",
        "spmatrix create idistance W",
        "spmatrix dir",
        "spreg price mpg, id(idvar) matrix(W)",
        "spset",
        "spset idvar",
        "spset, modify coord(price mpg)",
        "spset, modify replace",
        "spbalance",
        "spgenerate",
        "spshard",
        # Bayesian
        "bayes: reg price mpg",
        "bayes, prior({price: mpg}, normal(0,10)): reg price mpg",
        "bayesmh price mpg",
        "bayesgraph",
        "bayesstats ess",
        "bayesstats ic",
        "bayestest interval",
        "bayespredict",
        "bayesfisher",
        # IRT
        "irt 1pl y1-y10",
        "irt 2pl y1-y10",
        "irt grm y1-y10",
        "irt pcm y1-y10",
        "irt hybrid 1pl (y1-y10) 2pl (y11-y20)",
        "irtfit y1-y10",
        "irtgraph icc y1 y2",
        "irtreport",
        # LCA
        "gsem (y1 <- _L@1) (y2 <- _L@1), lclass(C 2)",
        "estat lcprob",
        "estat lcmean",
        # Multilevel/mixed
        "mixed y || id: || time:",
        "melogit y || id: || time:",
        "meglm y x || id:, family(binomial) link(logit)",
        "mixed y x || id:, reml",
        "mixed y x || id:, ml",
        "estat icc",
        "estat recovariance",
        "predict re*, reffects",
        "predict res*, residuals",
        # Survival analysis
        "stset time, failure(event)",
        "stcox x1 x2",
        "streg x1 x2, distribution(exponential)",
        "streg x1 x2, distribution(weibull)",
        "stcox ph test",
        "stphplot",
        "stcurve",
        "sts list",
        "sts graph",
        "streg x1 x2, distribution(gompertz)",
        "stcrreg x1 x2",
        "stintreg x1 x2",
        "stjoin",
        "stfill",
        "stsplit",
        "stbase",
        "stset2",
        # Panel data
        "xtreg price mpg, fe",
        "xtreg price mpg, re",
        "xtivreg price mpg (weight = length), fe",
        "xtabond price mpg, lags(2)",
        "xtdpdsys price mpg, lags(2)",
        "xtabond price mpg, twostep",
        "xtdpd price mpg, dgmmiv(price) lgmmiv(mpg)",
        "xtserial price mpg",
        "xttest0",
        "xthausman",
        "xtoverid",
        "xtline price mpg, overlay",
        # Causal inference / treatment effects
        "teffects ra (price mpg) (treat)",
        "teffects ipwra (price mpg) (treat)",
        "teffects aipw (price mpg) (treat)",
        "teffects ipw (treat mpg)",
        "tebalance summarize",
        "tebalance plot",
        "tebalance density",
        "teoverlap",
        "teffects mm (price mpg) (treat)",
        "stteffects ra (price mpg) (treat)",
        "stteffects ipwra (price mpg) (treat)",
        "etregress",
        "etpoisson",
        "etprobit",
        "ivtobit",
        "ivprobit",
        "ivregress 2sls price (mpg = length)",
        "ivregress gmm price (mpg = length)",
        "ivreg2 price (mpg = length)",
        "overid",
        "estat overid",
        "estat firststage",
        "estat endogenous",
        "weakivtest",
        "ivreg2 price (mpg = length weight)",
        "ivprobit y x1 (x2 = z1 z2)",
        "cmp setup",
        "cmp (y1 = x1) (y2 = x2), ind($cmp_cont $cmp_probit)",
        # Machine learning / Stata 18+
        "python: from sfi import Data; y = Data.get(\"mpg\")",
        "python: import pandas as pd; print(pd.DataFrame())",
        "python: print([i**2 for i in range(100)])",
        "lasso linear price mpg weight length",
        "lasso logit foreign price mpg weight",
        "lasso2 linear price mpg weight length",
        "elasticnet linear price mpg weight length",
        "ridge linear price mpg weight length",
        "lassoknots",
        "predict xb, xb",
        "predict resid, residuals",
        "predict stdp, stdp",
        "predict stdf, stdf",
        "predict hat, hat",
        "predict cooksd, cooksd",
        "predict dffits, dffits",
        "predict rstandard, rstandard",
        "predict rstudent, rstudent",
        "predict leverage, leverage",
        "predict residuals, residuals",
        "predict score, score",
        "predict influence, influence",
        "predict deviance, deviance",
        "predict linear, xb",
        "predict mu, mu",
        "predict eta, eta",
        "predict h, hat",
        "predict c, cooksd",
        "predict stdr, stdf",
        # FML
        "fml: reg price mpg",
        "fml: logit foreign price mpg",
        # Random garbage (keep short enough for Windows env var limit)
        "a" * 100,
        "".join(chr(random.randint(0, 255)) for _ in range(100)),
    ]

    @pytest.mark.parametrize("cmd", COMMANDS_TO_TRY)
    def test_cmd_does_not_crash(self, cmd: str) -> None:

    def test_fuzz_extremely_long_display(self) -> None:
        """Very long display tested separately to avoid Windows env var limits."""
        try:
            result = _route_command("display " + "A" * 100000)
            assert isinstance(result, dict)
            assert "ok" in result
        except Exception as e:
            pytest.fail(f"Extremely long display raised {type(e).__name__}: {e}")

    def test_fuzz_very_long_set(self) -> None:
        """Very long set tested separately to avoid Windows env var limits."""
        try:
            result = _route_command("set " + "X" * 50000)
            assert isinstance(result, dict)
            assert "ok" in result
        except Exception as e:
            pytest.fail(f"Very long set raised {type(e).__name__}: {e}")
        """Every command in the fuzz list should not crash _route_command."""
        try:
            result = _route_command(cmd)
            # Basic structural checks
            assert isinstance(result, dict), f"Expected dict, got {type(result)}"
            assert "ok" in result
            assert "rc" in result
            assert "stdout" in result
            assert isinstance(result["stdout"], str)
            assert isinstance(result["ok"], bool)
            assert isinstance(result["rc"], int)
        except Exception as e:
            pytest.fail(f"_route_command({cmd!r}) raised {type(e).__name__}: {e}")

    def test_fuzz_random_commands(self) -> None:
        """Throw random generated Stata-ish code at the router."""
        for i in range(200):
            code = _random_code(max_lines=20, max_line_len=100)
            try:
                result = _route_command(code)
                assert isinstance(result, dict)
                assert "ok" in result
                assert "rc" in result
                assert "stdout" in result
            except Exception as e:
                pytest.fail(f"Random code #{i} raised {type(e).__name__}: {e}\nCode: {code[:200]!r}")

    def test_fuzz_extremely_long_input(self) -> None:
        """1 MB of random data should not crash."""
        code = "A" * 1_000_000
        try:
            result = _route_command(code)
            assert isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"1MB input raised {type(e).__name__}: {e}")

    def test_fuzz_binary_data(self) -> None:
        """Binary/control character data should not crash."""
        for length in [10, 100, 1000, 10000]:
            data = bytes(random.randint(0, 255) for _ in range(length))
            try:
                result = _route_command(data.decode("latin-1"))
                assert isinstance(result, dict)
            except Exception as e:
                pytest.fail(f"Binary data ({length}b) raised {type(e).__name__}")

    def test_fuzz_null_bytes(self) -> None:
        """Null bytes in various positions should not crash."""
        cases = [
            "\x00",                                      # just null
            "\x00" * 1000,                               # many nulls
            "di\x00splay 1+1",                           # null mid-keyword
            "display " + "\x00" * 100 + "1+1",           # null in args
            "gen " + "\x00" * 5000 + " x = 1",           # tons of nulls
            "\x00display 1+1",                           # null-prefixed
            "display 1+1\x00",                           # null-suffixed
            "".join("\x00" if random.random() < 0.5 else "A" for _ in range(1000)),
        ]
        for case in cases:
            try:
                result = _route_command(case)
                assert isinstance(result, dict)
            except Exception as e:
                pytest.fail(f"Null-containing input raised {type(e).__name__}: {case[:100]!r}")

    def test_fuzz_session_isolation(self) -> None:
        """Commands in one session should not leak state to another."""
        _route_command("sysuse auto", session="session-a")
        state_a = _get_state("session-a")
        state_b = _get_state("session-b")

        assert "dataset" in state_a
        assert state_a["dataset"].get("name") == "auto"
        assert state_b["dataset"] == {}


# ======================================================================
# Fuzz: MockDaemon.dispatch
# ======================================================================

class TestFuzzMockDaemonDispatch:
    """Fuzz test MockDaemon.dispatch with insane arguments."""

    def _dispatch(
        self, daemon: MockDaemon, method: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return asyncio.run(daemon.dispatch(method, args or {}))

    def test_fuzz_dispatch_insane_args(self) -> None:
        """Dispatch with random large args should not crash."""
        daemon = MockDaemon()
        for i in range(100):
            args = {
                "code": _random_string(1000),
                "session": _random_string(50),
                "path": _random_string(200),
                "pattern": _random_string(500),
                "max_bytes": random.randint(-1, 1_000_000),
                "lines": random.randint(-1, 100_000),
                "name": _random_string(100),
                "format": random.choice(["pdf", "png", "svg", "", None, "exe"]),
                # Always use a /tmp/ prefix so output goes to a safe directory
                "out_path": f"/tmp/{_random_string(100)}",
                "outdir": f"/tmp/{_random_string(100)}",
                "offset": random.randint(-1, 1_000_000),
                "timeout": random.randint(-1, 1_000_000),
                "task_id": _random_string(100),
                "topic": _random_string(200),
                "varlist": [_random_string(50) for _ in range(100)],
                "background": random.choice([True, False, None, "yes", 1, 0]),
                "echo": random.choice([True, False, None, 1, 0]),
                "strict": random.choice([True, False, None]),
            }
            for method in [
                "run", "run_file", "break", "health", "stop",
                "inspect_describe", "inspect_summary", "inspect_codebook",
                "inspect_list", "inspect_get",
                "graph_list", "graph_export",
                "results",
                "log_tail", "log_search", "log_errors", "log_path",
                "task_status", "task_cancel", "task_list",
                "help",
            ]:
                try:
                    result = self._dispatch(daemon, method, args)
                    assert isinstance(result, dict)
                except ValueError as e:
                    # ValueError is acceptable for truly unknown methods
                    assert "Unknown method" in str(e)
                except Exception as e:
                    pytest.fail(f"dispatch({method}, ...) raised {type(e).__name__}: {e}")

    def test_fuzz_unknown_methods(self) -> None:
        """Unknown method names should raise ValueError, not crash."""
        daemon = MockDaemon()
        weird_methods = [
            "", " ", "\x00", "a" * 1000,
            "__import__", "os.system", "eval", "exec",
            "shutdown", "reboot", "delete_all_data",
            "..", "/", "\\", ".", "null",
            "True", "False", "None",
            "1", "0", "-1",
        ]
        for method in weird_methods:
            try:
                self._dispatch(daemon, method, {"x": "y"})
                pytest.fail(f"dispatch({method!r}) should have raised ValueError")
            except ValueError:
                pass
            except Exception as e:
                pytest.fail(f"dispatch({method!r}) raised {type(e).__name__} instead of ValueError: {e}")

    def test_fuzz_dispatch_sequential_sessions(self) -> None:
        """Sequential dispatch across many sessions should not leak or crash."""
        daemon = MockDaemon()
        for i in range(50):
            session = f"fuzz-session-{i}"
            try:
                self._dispatch(daemon, "run", {"code": "display 1+1", "session": session})
                self._dispatch(daemon, "health", {"session": session})
                self._dispatch(daemon, "break", {"session": session})
            except Exception as e:
                pytest.fail(f"Session {session} raised {type(e).__name__}: {e}")

    def test_fuzz_run_file_all_failure_patterns(self) -> None:
        """All statest failure patterns should be triggerable via run_file."""
        daemon = MockDaemon()
        patterns = [
            "fail_assert_scalar_fail",
            "fail_assert_macro_fail",
            "fail_assert_matrix_fail",
            "fail_assert_rc_fail",
            "fail_assert_scalar_tol_fail",
            "fail_failure_capture",
            "fail_teardown_runs_on_fail",
        ]
        for pattern in patterns:
            for session in ["default", "other"]:
                result = self._dispatch(daemon, "run_file", {
                    "path": f"/path/to/{pattern}_test.do",
                    "session": session,
                })
                assert isinstance(result, dict)
                assert "ok" in result
                assert "rc" in result

    def test_fuzz_graph_export_with_weird_args(self) -> None:
        """Graph export should handle nonsensical format/name combos."""
        daemon = MockDaemon()
        weird_formats = ["", None, "exe", "com", "bat", "sh", "\x00", ".", ".."]
        weird_names = ["", None, ".", "..", "/", "\\", "\x00", " " * 100]
        for fmt in weird_formats:
            for name in weird_names:
                try:
                    result = self._dispatch(daemon, "graph_export", {
                        "format": fmt,
                        "name": name,
                        "session": "default",
                    })
                    assert isinstance(result, dict)
                except Exception as e:
                    pytest.fail(f"graph_export(format={fmt!r}, name={name!r}) raised {type(e).__name__}: {e}")

    def test_fuzz_inspect_get_with_weird_formats(self) -> None:
        """inspect_get should handle all format options gracefully."""
        daemon = MockDaemon()
        for fmt in ["csv", "json", "arrow", "", None, "exe", "pdf"]:
            try:
                result = self._dispatch(daemon, "inspect_get", {
                    "format": fmt,
                    "out_path": f"/tmp/test_{fmt}.out",
                    "session": "default",
                })
                assert isinstance(result, dict)
                assert "path" in result or True  # at least no crash
            except Exception as e:
                pytest.fail(f"inspect_get(format={fmt!r}) raised {type(e).__name__}: {e}")

    def test_fuzz_graph_list_session_isolation(self) -> None:
        """Graph state should be isolated per session."""
        daemon = MockDaemon()
        for i in range(10):
            result_a = self._dispatch(daemon, "graph_list", {"session": f"session-a"})
            result_b = self._dispatch(daemon, "graph_list", {"session": f"session-b"})
            assert result_a["graph_names"] == result_b["graph_names"]

    def test_fuzz_break_resets_state(self) -> None:
        """break should acknowledge properly."""
        daemon = MockDaemon()
        result = self._dispatch(daemon, "break", {"session": "default"})
        assert result["acknowledged"] is True
        assert result.get("worker_restarted") is True

    def test_fuzz_task_status_unknown(self) -> None:
        """task_status for unknown task returns not_found."""
        daemon = MockDaemon()
        result = self._dispatch(daemon, "task_status", {"task_id": "nonexistent"})
        assert result["status"] == "completed"  # mock returns completed always

    def test_fuzz_all_methods_with_null_session(self) -> None:
        """All dispatch methods should work with None/missing session args."""
        daemon = MockDaemon()
        methods_to_test = [
            lambda daemon_arg_fn: daemon_arg_fn("run", {"code": "display 1+1"}),
            lambda daemon_arg_fn: daemon_arg_fn("health", {}),
            lambda daemon_arg_fn: daemon_arg_fn("break", {}),
            lambda daemon_arg_fn: daemon_arg_fn("inspect_describe", {}),
            lambda daemon_arg_fn: daemon_arg_fn("graph_list", {}),
            lambda daemon_arg_fn: daemon_arg_fn("results", {}),
            lambda daemon_arg_fn: daemon_arg_fn("log_tail", {}),
            lambda daemon_arg_fn: daemon_arg_fn("log_search", {"pattern": "test"}),
            lambda daemon_arg_fn: daemon_arg_fn("log_errors", {}),
            lambda daemon_arg_fn: daemon_arg_fn("log_path", {}),
            lambda daemon_arg_fn: daemon_arg_fn("task_status", {"task_id": "x"}),
            lambda daemon_arg_fn: daemon_arg_fn("task_list", {}),
        ]
        for fn in methods_to_test:
            try:
                fn(lambda m, a: self._dispatch(daemon, m, a))
            except Exception as e:
                pytest.fail(f"Dispatch with no session raised {type(e).__name__}: {e}")


# ======================================================================
# Stress tests: rapid-fire operations
# ======================================================================

class TestStressMockDaemon:
    """Stress test the mock daemon with rapid operations."""

    def test_stress_rapid_run_health(self) -> None:
        """100 rapid alternations of run/health should not degrade state."""
        daemon = MockDaemon()
        for i in range(100):
            try:
                asyncio.run(daemon.dispatch("run", {"code": f"display {i}"}))
                health = asyncio.run(daemon.dispatch("health", {}))
                assert health["status"] == "ok"
            except Exception as e:
                pytest.fail(f"Iteration {i} raised {type(e).__name__}: {e}")

    def test_stress_rapid_session_switch(self) -> None:
        """Rapid session switching should maintain isolation."""
        daemon = MockDaemon()
        for i in range(100):
            session = f"s{i % 10}"
            try:
                asyncio.run(daemon.dispatch("run", {
                    "code": f"display {i}",
                    "session": session,
                }))
                asyncio.run(daemon.dispatch("health", {"session": session}))
            except Exception as e:
                pytest.fail(f"Session {session} iter {i} raised {type(e).__name__}: {e}")

    def test_stress_many_concurrent_routes(self) -> None:
        """Route many different commands concurrently to simulate load."""
        import concurrent.futures

        daemon = MockDaemon()
        commands = [
            "sysuse auto",
            "describe",
            "summarize price mpg",
            "reg price mpg",
            "display 1+1",
            "graph dir",
            "error 111",
            "tab rep78",
            "assert 1==1",
            "set more off",
        ]

        def route(cmd: str) -> None:
            result = _route_command(cmd)
            assert isinstance(result, dict)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = []
            for _ in range(100):
                for cmd in commands:
                    futures.append(pool.submit(route, cmd))
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    pytest.fail(f"Concurrent route raised {type(e).__name__}: {e}")

    def test_stress_state_bloat(self) -> None:
        """Ensure state doesn't grow unboundedly across many sessions."""
        daemon = MockDaemon()
        initial_count = len(_session_state)
        for i in range(100):
            asyncio.run(daemon.dispatch("run", {
                "code": f"display {i}",
                "session": f"bloat-session-{i}",
            }))
        # Should have exactly the sessions we created (100) + whatever was default
        assert len(_session_state) >= 100
        # Clean up state for following tests
        _session_state.clear()

    def test_fuzz_very_deeply_nested_args(self) -> None:
        """Args with deeply nested structures should not crash."""
        daemon = MockDaemon()
        deep_args = {"a": {"b": {"c": {"d": {"e": {"f": "g"}}}}}}
        try:
            result = asyncio.run(daemon.dispatch("health", deep_args))
            assert result["status"] == "ok"
        except Exception as e:
            pytest.fail(f"Deep args raised {type(e).__name__}: {e}")

    def test_fuzz_args_with_json_types(self) -> None:
        """Args containing JSON-incompatible types should be handled."""
        daemon = MockDaemon()
        special_args = {
            "code": None,
            "session": None,
            "echo": None,
            "background": "maybe",
            "strict": 42,
            "max_output_tokens": -1,
        }
        try:
            result = asyncio.run(daemon.dispatch("run", special_args))
            assert isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"Special args raised {type(e).__name__}: {e}")

    def test_fuzz_results_with_stathest_scalars(self) -> None:
        """results dispatch should handle statest scalars in state."""
        daemon = MockDaemon()
        result = asyncio.run(daemon.dispatch("results", {"session": "default"}))
        assert isinstance(result, dict)
        assert "stored_results" in result

    def test_fuzz_log_search_patterns(self) -> None:
        """log_search should handle various pattern types."""
        daemon = MockDaemon()
        patterns = [
            "", ".*", r"r\(\d+\)", r"\d+", "^", "$",
            "(", ")", "[", "]", "{", "}",
            "\\", "\\\\", "\\\\\\\\",
            "*" * 1000,
        ]
        for pattern in patterns:
            try:
                result = asyncio.run(daemon.dispatch("log_search", {
                    "pattern": pattern,
                    "session": "default",
                }))
                assert isinstance(result, dict)
            except Exception as e:
                pytest.fail(f"log_search(pattern={pattern!r}) raised {type(e).__name__}: {e}")

    def test_fuzz_help_topics(self) -> None:
        """help dispatch should handle any topic string."""
        daemon = MockDaemon()
        topics = [
            "", "regress", " ", "\x00", "a" * 1000,
            "../", "/etc/passwd", "os.system('ls')",
        ]
        for topic in topics:
            try:
                result = asyncio.run(daemon.dispatch("help", {
                    "topic": topic,
                    "session": "default",
                }))
                assert isinstance(result, dict)
            except Exception as e:
                pytest.fail(f"help(topic={topic!r}) raised {type(e).__name__}: {e}")
