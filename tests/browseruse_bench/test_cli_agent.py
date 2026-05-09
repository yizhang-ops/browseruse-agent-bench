"""Tests for CLIAgent._run_subprocess and _map_exit_status."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from browseruse_bench.agents.cli_agent import CLIAgent


# ---------------------------------------------------------------------------
# Concrete minimal subclass (CLIAgent is abstract via BaseAgent)
# ---------------------------------------------------------------------------

class _DummyCLIAgent(CLIAgent):
    name = "dummy-cli"

    def run_task(self, task_info, agent_config, task_workspace):  # type: ignore[override]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# _map_exit_status
# ---------------------------------------------------------------------------

class TestMapExitStatus:
    def test_success(self) -> None:
        assert _DummyCLIAgent._map_exit_status(0, None) == ("success", "done")

    def test_timeout(self) -> None:
        assert _DummyCLIAgent._map_exit_status(-1, "Timeout after 300 seconds") == ("success", "timeout")

    def test_timeout_keyword_match(self) -> None:
        # Any string containing "Timeout" triggers the timeout branch
        assert _DummyCLIAgent._map_exit_status(-1, "Timeout after 60 seconds")[1] == "timeout"

    def test_execution_error(self) -> None:
        assert _DummyCLIAgent._map_exit_status(-1, "connection refused") == ("failed", "error")

    def test_nonzero_returncode_no_result(self) -> None:
        # Non-zero exit + no usable result → error
        assert _DummyCLIAgent._map_exit_status(1, None, has_result=False) == ("failed", "error")

    def test_nonzero_returncode_with_result(self) -> None:
        # Non-zero exit but result was produced → treat as success
        assert _DummyCLIAgent._map_exit_status(1, None, has_result=True) == ("success", "done")

    def test_none_returncode_treated_as_success(self) -> None:
        assert _DummyCLIAgent._map_exit_status(None, None) == ("success", "done")


# ---------------------------------------------------------------------------
# _run_subprocess
# ---------------------------------------------------------------------------

class TestRunSubprocess:
    def _agent(self) -> _DummyCLIAgent:
        return _DummyCLIAgent()

    def test_success_returns_zero_returncode(self, tmp_path: Path) -> None:
        agent = self._agent()
        rc, lines, err = agent._run_subprocess(
            [sys.executable, "-c", "print('hello')"],
            timeout=10,
            task_workspace=tmp_path,
        )
        assert rc == 0
        assert err is None

    def test_stdout_collected(self, tmp_path: Path) -> None:
        agent = self._agent()
        _, lines, _ = agent._run_subprocess(
            [sys.executable, "-c", "print('line1'); print('line2')"],
            timeout=10,
            task_workspace=tmp_path,
        )
        collected = "".join(lines)
        assert "line1" in collected
        assert "line2" in collected

    def test_stdout_not_collected_when_disabled(self, tmp_path: Path) -> None:
        agent = self._agent()
        _, lines, _ = agent._run_subprocess(
            [sys.executable, "-c", "print('something')"],
            timeout=10,
            task_workspace=tmp_path,
            collect_stdout=False,
        )
        assert lines == []

    def test_stdout_written_to_file(self, tmp_path: Path) -> None:
        agent = self._agent()
        agent._run_subprocess(
            [sys.executable, "-c", "print('written')"],
            timeout=10,
            task_workspace=tmp_path,
        )
        content = (tmp_path / "stdout.txt").read_text()
        assert "written" in content

    def test_stderr_written_to_file(self, tmp_path: Path) -> None:
        agent = self._agent()
        agent._run_subprocess(
            [sys.executable, "-c", "import sys; sys.stderr.write('err-line\\n')"],
            timeout=10,
            task_workspace=tmp_path,
        )
        content = (tmp_path / "stderr.txt").read_text()
        assert "err-line" in content

    def test_stdout_line_hook_called(self, tmp_path: Path) -> None:
        seen: list[str] = []
        agent = self._agent()
        agent._run_subprocess(
            [sys.executable, "-c", "print('hook-line')"],
            timeout=10,
            task_workspace=tmp_path,
            stdout_line_hook=seen.append,
        )
        assert any("hook-line" in s for s in seen)

    def test_stderr_line_hook_called(self, tmp_path: Path) -> None:
        seen: list[str] = []
        agent = self._agent()
        agent._run_subprocess(
            [sys.executable, "-c", "import sys; sys.stderr.write('hook-err\\n')"],
            timeout=10,
            task_workspace=tmp_path,
            stderr_line_hook=seen.append,
        )
        assert any("hook-err" in s for s in seen)

    def test_timeout_sets_execution_error(self, tmp_path: Path) -> None:
        agent = self._agent()
        _, _, err = agent._run_subprocess(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout=1,
            task_workspace=tmp_path,
        )
        assert err is not None
        assert "Timeout" in err

    def test_file_not_found_propagates(self, tmp_path: Path) -> None:
        agent = self._agent()
        with pytest.raises(FileNotFoundError):
            agent._run_subprocess(
                ["__nonexistent_binary_xyz__"],
                timeout=5,
                task_workspace=tmp_path,
            )

    def test_env_passed_to_process(self, tmp_path: Path) -> None:
        import os
        env = {**os.environ, "MY_TEST_VAR": "hello_from_env"}
        agent = self._agent()
        _, lines, _ = agent._run_subprocess(
            [sys.executable, "-c", "import os; print(os.environ.get('MY_TEST_VAR',''))"],
            timeout=10,
            task_workspace=tmp_path,
            env=env,
        )
        assert any("hello_from_env" in l for l in lines)

    def test_nonzero_exit_code_returned(self, tmp_path: Path) -> None:
        agent = self._agent()
        rc, _, _ = agent._run_subprocess(
            [sys.executable, "-c", "raise SystemExit(42)"],
            timeout=10,
            task_workspace=tmp_path,
        )
        assert rc == 42

    def test_cwd_applied_to_process(self, tmp_path: Path) -> None:
        agent = self._agent()
        cwd_dir = tmp_path / "subdir"
        cwd_dir.mkdir()
        _, lines, _ = agent._run_subprocess(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            timeout=10,
            task_workspace=tmp_path,
            cwd=cwd_dir,
        )
        assert any(str(cwd_dir) in l for l in lines)
