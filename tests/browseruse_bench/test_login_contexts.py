"""Tests for per-profile login-context storage and legacy-shape migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from browseruse_bench.browsers import login_contexts as lc


@pytest.fixture
def tmp_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect INDEX_PATH at the module level to a temp file."""
    path = tmp_path / "index.json"
    monkeypatch.setattr(lc, "INDEX_PATH", path)
    return path


def test_upsert_profile_round_trip(tmp_index: Path) -> None:
    """Two profile entries on one site read back independently."""
    lc.upsert_profile("xiaohongshu", "zh", {"context_id": "ctx_zh", "website": "https://x.com/zh"})
    lc.upsert_profile("xiaohongshu", "en", {"context_id": "ctx_en", "website": "https://x.com/en"})

    assert lc.get_by_site_profile("xiaohongshu", "zh") == {
        "context_id": "ctx_zh", "website": "https://x.com/zh",
    }
    assert lc.get_by_site_profile("xiaohongshu", "en") == {
        "context_id": "ctx_en", "website": "https://x.com/en",
    }
    assert sorted(lc.get_profiles_for_site("xiaohongshu")) == ["en", "zh"]


def test_legacy_index_normalized_on_read(tmp_index: Path) -> None:
    """An old-shape entry surfaces under the default-fallback path only."""
    legacy = {"xiaohongshu": {"context_id": "ctx_legacy", "website": "https://x.com"}}
    tmp_index.write_text(json.dumps(legacy), encoding="utf-8")

    # Explicit profile_key with no matching profile → None (no _default
    # fallback, so the runner soft-fails to running without login state instead
    # of silently injecting cookies captured against a different endpoint).
    assert lc.get_by_site_profile("xiaohongshu", "zh") is None
    # Implicit profile_key (None) → legacy entry surfaces under default fallback.
    assert lc.get_by_site_profile("xiaohongshu", None) == {
        "context_id": "ctx_legacy", "website": "https://x.com",
    }
    # Backward-compat caller still works.
    assert lc.get_by_site("xiaohongshu") == {
        "context_id": "ctx_legacy", "website": "https://x.com",
    }


def test_get_by_site_profile_returns_none_when_missing(tmp_index: Path) -> None:
    """Unknown site or profile yields None — caller handles soft-fail."""
    lc.upsert_profile("xiaohongshu", "zh", {"context_id": "ctx_zh"})
    assert lc.get_by_site_profile("xiaohongshu", "fr") is None
    assert lc.get_by_site_profile("unknown_site", "zh") is None


def test_get_by_site_profile_no_default_fallback_when_explicit_profile(
    tmp_index: Path,
) -> None:
    """An explicit profile_key never silently picks up a _default entry."""
    lc.upsert_profile("xiaohongshu", lc.DEFAULT_PROFILE_KEY, {"context_id": "ctx_default"})
    # Explicit profile that was not registered → soft-fail (None), not default.
    assert lc.get_by_site_profile("xiaohongshu", "zh") is None
    # Implicit profile → default entry surfaces.
    assert lc.get_by_site_profile("xiaohongshu", None) == {"context_id": "ctx_default"}


def test_remove_profile_drops_site_when_empty(tmp_index: Path) -> None:
    """Removing the last profile drops the site key entirely."""
    lc.upsert_profile("xiaohongshu", "zh", {"context_id": "ctx_zh"})

    assert lc.remove_profile("xiaohongshu", "zh") is True
    assert lc.get_profiles_for_site("xiaohongshu") == {}
    assert "xiaohongshu" not in lc.load_index()


def test_remove_profile_keeps_other_profiles(tmp_index: Path) -> None:
    lc.upsert_profile("xiaohongshu", "zh", {"context_id": "ctx_zh"})
    lc.upsert_profile("xiaohongshu", "en", {"context_id": "ctx_en"})

    assert lc.remove_profile("xiaohongshu", "zh") is True
    assert lc.get_by_site_profile("xiaohongshu", "zh") is None
    assert lc.get_by_site_profile("xiaohongshu", "en") == {"context_id": "ctx_en"}


def test_legacy_entry_migrates_on_write(tmp_index: Path) -> None:
    """Writing a profile to a site that holds a legacy entry preserves both."""
    legacy = {"xiaohongshu": {"context_id": "ctx_legacy", "website": "https://x.com"}}
    tmp_index.write_text(json.dumps(legacy), encoding="utf-8")

    lc.upsert_profile("xiaohongshu", "zh", {"context_id": "ctx_zh"})

    profiles = lc.get_profiles_for_site("xiaohongshu")
    assert sorted(profiles) == [lc.DEFAULT_PROFILE_KEY, "zh"]
    assert profiles[lc.DEFAULT_PROFILE_KEY]["context_id"] == "ctx_legacy"
    assert profiles["zh"]["context_id"] == "ctx_zh"
