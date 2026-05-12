"""Unit tests for statest JUnit XML serialisation."""
from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET

from stata_agent.statest.models import TestResult, TestSuiteSummary
from stata_agent.statest.junit import write_junit_xml


class TestWriteJunitXml:
    def test_empty_suite(self):
        summary = TestSuiteSummary(
            path="tests/", total_tests=0, passed=0, failed=0,
            results=[], summary_text="No tests.",
        )
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            out = f.name

        try:
            write_junit_xml(summary, out)
            tree = ET.parse(out)
            root = tree.getroot()
            assert root.tag == "testsuites"
            suite = root.find("testsuite")
            assert suite is not None
            assert suite.get("tests") == "0"
            assert suite.get("failures") == "0"
        finally:
            os.unlink(out)

    def test_suite_with_results(self):
        r1 = TestResult(test_path="a.do", success=True, rc=0, duration_seconds=1.0)
        r2 = TestResult(test_path="b.do", success=False, rc=9, duration_seconds=2.0)
        summary = TestSuiteSummary(
            path="tests/", total_tests=2, passed=1, failed=1,
            results=[r1, r2], summary_text="Ran 2 tests. 1 passed, 1 failed.",
        )

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            out = f.name

        try:
            write_junit_xml(summary, out)
            tree = ET.parse(out)
            root = tree.getroot()
            suite = root.find("testsuite")
            assert suite is not None
            assert suite.get("tests") == "2"
            assert suite.get("failures") == "1"

            cases = suite.findall("testcase")
            assert len(cases) == 2

            # Failed test case should have a failure element
            assert cases[1].find("failure") is not None
            assert cases[0].find("failure") is None
        finally:
            os.unlink(out)

    def test_junit_xml_valid_xml(self):
        r = TestResult(test_path="a.do", success=True, rc=0, duration_seconds=0.5)
        summary = TestSuiteSummary(
            path="tests/", total_tests=1, passed=1, failed=0,
            results=[r], summary_text="Ok.",
        )

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            out = f.name

        try:
            write_junit_xml(summary, out)
            # Parse cleanly
            tree = ET.parse(out)
            assert tree.getroot().tag == "testsuites"
        finally:
            os.unlink(out)

    def test_failure_with_assertion_details(self):
        from stata_agent.statest.models import AssertionFailure
        f = AssertionFailure(
            test="b.do", assertion_index=1, command="st_assert_scalar",
            variable="", expected="5000", actual="6165.257", rc=9,
        )
        r = TestResult(
            test_path="b.do", success=False, rc=9, assertion_index=1,
            failure=f, duration_seconds=2.0,
        )
        summary = TestSuiteSummary(
            path="tests/", total_tests=0, passed=0, failed=1,
            results=[r], summary_text="Failed.",
        )

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            out = f.name

        try:
            write_junit_xml(summary, out)
            tree = ET.parse(out)
            failure = tree.find(".//failure")
            assert failure is not None
            assert failure.get("type") == "AssertionError"
            assert "5000" in (failure.text or "")
        finally:
            os.unlink(out)
