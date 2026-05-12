"""Unit tests for statest models."""
from __future__ import annotations

from stata_agent.statest.models import AssertionFailure, TestResult, TestSuiteSummary


class TestAssertionFailure:
    def test_construct_with_float_values(self):
        f = AssertionFailure(
            test="test_foo.do",
            assertion_index=1,
            command="st_assert_scalar",
            variable="",
            expected=5000.0,
            actual=6165.257,
            tolerance=0.001,
            rc=9,
        )
        assert f.test == "test_foo.do"
        assert f.assertion_index == 1
        assert f.expected == 5000.0
        assert f.actual == 6165.257
        assert f.tolerance == 0.001
        assert f.rc == 9

    def test_construct_with_string_values(self):
        f = AssertionFailure(
            test="test_bar.do",
            assertion_index=1,
            command="st_assert_macro",
            variable="e(cmd)",
            expected="regress",
            actual="summarize",
            rc=9,
        )
        assert f.expected == "regress"
        assert f.actual == "summarize"
        assert f.tolerance is None

    def test_to_dict_roundtrip(self):
        f = AssertionFailure(
            test="t.do", assertion_index=2, command="st_assert_rc",
            variable="", expected="0", actual="601", rc=9,
        )
        d = f.model_dump()
        assert d["test"] == "t.do"
        assert d["assertion_index"] == 2
        assert d["rc"] == 9
        # Roundtrip
        f2 = AssertionFailure.model_validate(d)
        assert f2.assertion_index == f.assertion_index


class TestTestResult:
    def test_success_result(self):
        r = TestResult(
            test_path="tests/test_foo.do",
            success=True,
            rc=0,
            duration_seconds=1.5,
            log_path="/tmp/foo.log",
        )
        assert r.success is True
        assert r.rc == 0
        assert r.failure is None
        assert r.assertion_index is None

    def test_failure_result(self):
        f = AssertionFailure(
            test="test_foo.do", assertion_index=1, command="st_assert_scalar",
            variable="", expected="5000", actual="6165.257", rc=9,
        )
        r = TestResult(
            test_path="tests/test_foo.do",
            success=False,
            rc=9,
            assertion_index=1,
            failure=f,
            duration_seconds=2.0,
        )
        assert r.success is False
        assert r.failure is not None
        assert r.failure.expected == "5000"

    def test_to_dict_roundtrip(self):
        r = TestResult(
            test_path="t.do", success=True, rc=0, duration_seconds=0.5,
        )
        d = r.model_dump()
        r2 = TestResult.model_validate(d)
        assert r2.success == r.success


class TestTestSuiteSummary:
    def test_empty_summary(self):
        s = TestSuiteSummary(
            path="tests/", total_tests=0, passed=0, failed=0,
            results=[], summary_text="No tests found.",
        )
        assert s.total_tests == 0
        assert s.passed == 0
        assert s.failed == 0

    def test_summary_with_results(self):
        r1 = TestResult(test_path="a.do", success=True, rc=0, duration_seconds=1.0)
        r2 = TestResult(test_path="b.do", success=False, rc=9, duration_seconds=2.0)
        s = TestSuiteSummary(
            path="tests/", total_tests=2, passed=1, failed=1,
            results=[r1, r2], summary_text="Ran 2 tests. 1 passed, 1 failed.",
        )
        assert s.passed == 1
        assert s.failed == 1
        assert len(s.results) == 2

    def test_to_dict_roundtrip(self):
        r = TestResult(test_path="a.do", success=True, rc=0, duration_seconds=1.0)
        s = TestSuiteSummary(
            path="tests/", total_tests=1, passed=1, failed=0,
            results=[r], summary_text="Ran 1 test. 1 passed, 0 failed.",
        )
        d = s.model_dump()
        s2 = TestSuiteSummary.model_validate(d)
        assert s2.total_tests == 1
