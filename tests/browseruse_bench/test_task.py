"""Tests for browseruse_bench.utils.task_utils module."""

import json
from pathlib import Path

import pytest

from browseruse_bench.utils import (
    filter_tasks,
    is_browsecomp_benchmark,
    is_task_completed_by_result_json,
    load_tasks,
)
from browseruse_bench.utils.task import normalize_task_url, resolve_default_task_url


class TestLoadTasks:
    """Tests for load_tasks function."""

    def test_load_tasks_from_list_format(self, tmp_path: Path):
        """Test loading tasks from JSON array format."""
        tasks_data = [
            {"task_id": "1", "task": "Task 1", "website": "https://example.com"},
            {"task_id": "2", "task": "Task 2", "website": "https://test.com"},
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert len(tasks) == 2
        assert tasks[0]["task_id"] == "1"
        assert tasks[0]["task_text"] == "Task 1"
        assert tasks[0]["url"] == "https://example.com"

    def test_load_tasks_from_dict_format(self, tmp_path: Path):
        """Test loading tasks from dict with 'tasks' key."""
        tasks_data = {
            "benchmark": "test",
            "tasks": [
                {"task_id": "1", "task": "Task 1", "website": "https://example.com"},
            ]
        }
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "1"

    def test_load_tasks_with_prompt_format(self, tmp_path: Path):
        """Test loading tasks with prompt template."""
        tasks_data = [
            {"task_id": "1", "task": "Click button", "website": "https://example.com"},
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file), prompt_fmt="Do: {task} on {url}")

        assert "prompt" in tasks[0]
        assert tasks[0]["prompt"] == "Do: Click button on https://example.com"

    def test_load_tasks_adds_https_prefix(self, tmp_path: Path):
        """Test that URL without protocol gets https:// prefix."""
        tasks_data = [
            {"task_id": "1", "task": "Task", "website": "example.com"},
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["url"] == "https://example.com"

    def test_load_tasks_uses_google_when_url_missing(self, tmp_path: Path):
        """Test missing URL falls back to Google."""
        tasks_data = [
            {"task_id": "1", "task": "Task without URL"},
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert len(tasks) == 1
        assert tasks[0]["url"] == "https://www.google.com"

    def test_load_tasks_uses_default_url_for_whitespace_website(self, tmp_path: Path):
        """Test whitespace URL falls back to default URL."""
        tasks_data = [
            {"task_id": "1", "task": "Task with whitespace URL", "website": "   "},
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert len(tasks) == 1
        assert tasks[0]["url"] == "https://www.google.com"

    def test_load_tasks_uses_custom_default_url(self, tmp_path: Path):
        """Test custom default URL is applied when task URL is missing."""
        tasks_data = [
            {"task_id": "1", "task": "Task without URL"},
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file), default_url="example.org")

        assert len(tasks) == 1
        assert tasks[0]["url"] == "https://example.org"

    def test_load_tasks_preserves_existing_scheme_urls(self, tmp_path: Path):
        """Test URLs with explicit schemes are not rewritten."""
        tasks_data = [
            {"task_id": "1", "task": "Chrome task", "website": "chrome://settings"},
            {"task_id": "2", "task": "Data task", "website": "data:text/plain,hello"},
            {"task_id": "3", "task": "FTP task", "website": "ftp://example.com/file"},
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["url"] == "chrome://settings"
        assert tasks[1]["url"] == "data:text/plain,hello"
        assert tasks[2]["url"] == "ftp://example.com/file"

    def test_load_tasks_applies_env_default_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Test env var default URL is used when task URL is missing."""
        tasks_data = [{"task_id": "1", "task": "Task without URL"}]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))
        monkeypatch.setenv("BUBENCH_DEFAULT_TASK_URL", "example.net")

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["url"] == "https://example.net"

    def test_load_tasks_explicit_default_url_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Test explicit default URL takes precedence over env var."""
        tasks_data = [{"task_id": "1", "task": "Task without URL"}]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))
        monkeypatch.setenv("BUBENCH_DEFAULT_TASK_URL", "from-env.example")

        tasks = load_tasks(str(tasks_file), default_url="from-arg.example")

        assert tasks[0]["url"] == "https://from-arg.example"

    def test_load_tasks_file_not_found(self, tmp_path: Path):
        """Test loading from non-existent file returns empty list."""
        tasks = load_tasks(str(tmp_path / "nonexistent.json"))
        assert tasks == []

    def test_load_tasks_alternative_field_names(self, tmp_path: Path):
        """Test loading tasks with alternative field names."""
        tasks_data = [
            {"annotation_id": "abc", "confirmed_task": "Do something", "url": "https://test.com"},
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["task_id"] == "abc"
        assert tasks[0]["task_text"] == "Do something"

    def test_load_tasks_single_site_populates_urls_singleton(self, tmp_path: Path):
        """Single-site target_website produces a urls list with one entry equal to url."""
        tasks_data = [
            {"task_id": "1", "task": "Single site", "target_website": "example.com"},
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["url"] == "https://example.com"
        assert tasks[0]["urls"] == ["https://example.com"]

    def test_load_tasks_multi_site_split_on_padded_plus(self, tmp_path: Path):
        """target_website joined by ' + ' (space-plus-space) is split into multiple urls."""
        tasks_data = [
            {
                "task_id": "1",
                "task": "Multi site",
                "target_website": "movie.douban.com + imdb.com",
            },
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["urls"] == ["https://movie.douban.com", "https://imdb.com"]
        # url is the first entry, used as the starting URL
        assert tasks[0]["url"] == "https://movie.douban.com"

    def test_load_tasks_multi_site_three_targets(self, tmp_path: Path):
        """Three sites separated by ' + ' all become urls entries in order."""
        tasks_data = [
            {
                "task_id": "1",
                "task": "Three sites",
                "target_website": "top.baidu.com + s.weibo.com/top + toutiao.com/hot",
            },
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["urls"] == [
            "https://top.baidu.com",
            "https://s.weibo.com/top",
            "https://toutiao.com/hot",
        ]

    def test_load_tasks_does_not_split_on_unpadded_plus_in_query(self, tmp_path: Path):
        """A '+' inside a query string (no surrounding spaces) must not trigger multi-site split."""
        tasks_data = [
            {
                "task_id": "1",
                "task": "URL with + in query",
                "target_website": "https://example.com/search?q=foo+bar",
            },
        ]
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks_data))

        tasks = load_tasks(str(tasks_file))

        # Single-site: urls has one entry, untouched (no spurious split)
        assert tasks[0]["urls"] == ["https://example.com/search?q=foo+bar"]
        assert tasks[0]["url"] == "https://example.com/search?q=foo+bar"


class TestFilterTasks:
    """Tests for filter_tasks function."""

    @pytest.fixture
    def sample_tasks(self):
        return [
            {"task_id": "1", "task_text": "Task 1"},
            {"task_id": "2", "task_text": "Task 2"},
            {"task_id": "3", "task_text": "Task 3"},
            {"task_id": "4", "task_text": "Task 4"},
            {"task_id": "5", "task_text": "Task 5"},
        ]

    def test_filter_single(self, sample_tasks):
        """Test single mode returns first task."""
        result = filter_tasks(sample_tasks, mode="single", count=1, task_ids=None)
        assert len(result) == 1
        assert result[0]["task_id"] == "1"

    def test_filter_first_n(self, sample_tasks):
        """Test first_n mode returns first N tasks."""
        result = filter_tasks(sample_tasks, mode="first_n", count=3, task_ids=None)
        assert len(result) == 3
        assert [t["task_id"] for t in result] == ["1", "2", "3"]

    def test_filter_sample_n(self, sample_tasks):
        """Test sample_n mode returns N random tasks."""
        result = filter_tasks(sample_tasks, mode="sample_n", count=2, task_ids=None)
        assert len(result) == 2

    def test_filter_specific(self, sample_tasks):
        """Test specific mode returns tasks with given IDs."""
        result = filter_tasks(sample_tasks, mode="specific", count=0, task_ids=["2", "4"])
        assert len(result) == 2
        assert set(t["task_id"] for t in result) == {"2", "4"}

    def test_filter_all(self, sample_tasks):
        """Test all mode returns all tasks."""
        result = filter_tasks(sample_tasks, mode="all", count=0, task_ids=None)
        assert len(result) == 5

    def test_filter_specific_without_ids_raises(self, sample_tasks):
        """Test specific mode without task_ids raises ValueError."""
        with pytest.raises(ValueError, match="task_ids"):
            filter_tasks(sample_tasks, mode="specific", count=0, task_ids=None)

    def test_filter_unknown_mode_raises(self, sample_tasks):
        """Test unknown mode raises ValueError."""
        with pytest.raises(ValueError, match="Unknown mode"):
            filter_tasks(sample_tasks, mode="invalid", count=0, task_ids=None)


class TestIsTaskCompleted:
    """Tests for is_task_completed_by_result_json function."""

    def test_task_completed_with_result_file(self, tmp_path: Path):
        """Test returns True when result.json exists and is non-empty."""
        task_dir = tmp_path / "tasks" / "task_001"
        task_dir.mkdir(parents=True)
        result_file = task_dir / "result.json"
        result_file.write_text('{"status": "done"}')

        assert is_task_completed_by_result_json("task_001", tmp_path) is True

    def test_task_not_completed_without_file(self, tmp_path: Path):
        """Test returns False when result.json doesn't exist."""
        assert is_task_completed_by_result_json("task_001", tmp_path) is False

    def test_task_not_completed_with_empty_file(self, tmp_path: Path):
        """Test returns False when result.json is empty."""
        task_dir = tmp_path / "tasks" / "task_001"
        task_dir.mkdir(parents=True)
        result_file = task_dir / "result.json"
        result_file.write_text("")

        assert is_task_completed_by_result_json("task_001", tmp_path) is False


class TestIsBrowseCompBenchmark:
    """Tests for is_browsecomp_benchmark function."""

    def test_browsecomp_path(self):
        """Test returns True for BrowseComp paths."""
        path = Path("/benchmarks/BrowseComp/data/tasks.json")
        assert is_browsecomp_benchmark(path) is True

    def test_non_browsecomp_path(self):
        """Test returns False for non-BrowseComp paths."""
        path = Path("/benchmarks/LexBench-Browser/data/tasks.json")
        assert is_browsecomp_benchmark(path) is False


class TestUrlNormalization:
    """Tests for URL normalization helpers."""

    def test_normalize_task_url_adds_https_for_scheme_less_url(self):
        assert normalize_task_url("example.com:8080/home") == "https://example.com:8080/home"

    def test_normalize_task_url_keeps_supported_schemes(self):
        assert normalize_task_url("about:blank") == "about:blank"
        assert normalize_task_url("file:///tmp/test.txt") == "file:///tmp/test.txt"
        assert normalize_task_url("chrome://settings") == "chrome://settings"

    def test_resolve_default_task_url_fallback_for_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("BUBENCH_DEFAULT_TASK_URL", raising=False)
        assert resolve_default_task_url() == "https://www.google.com"

    def test_resolve_default_task_url_normalizes_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BUBENCH_DEFAULT_TASK_URL", "example.org")
        assert resolve_default_task_url() == "https://example.org"
