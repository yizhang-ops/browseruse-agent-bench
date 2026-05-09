"""Local index of Lexmount login contexts keyed by site.

A login context is a Lexmount persistent context that has been pre-logged-in by
a human once (via ``bubench login add``). Evaluations with
``login_required: true`` consume it by fork() — the base context is never
written to by evals, so a single login serves many concurrent runs.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from browseruse_bench.utils.repo_root import REPO_ROOT

logger = logging.getLogger(__name__)

INDEX_PATH = REPO_ROOT / "browser_data" / "login_contexts" / "index.json"

# Built-in site registry lives in a sibling YAML file — edit that, not this module.
# The runtime flattens {group: {site: url}} into {site: url}.
_REGISTRY_YAML_PATH = Path(__file__).with_name("login_sites.yaml")


def _load_site_registry() -> dict[str, str]:
    """Load ``login_sites.yaml`` and return a flat {site_key: url} dict."""
    if not _REGISTRY_YAML_PATH.exists():
        logger.warning("Login site registry not found at %s", _REGISTRY_YAML_PATH)
        return {}
    try:
        raw = yaml.safe_load(_REGISTRY_YAML_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.error("Failed to load login site registry %s: %s", _REGISTRY_YAML_PATH, exc)
        return {}
    if not isinstance(raw, dict):
        logger.warning("Login site registry has unexpected shape; ignoring")
        return {}
    flat: dict[str, str] = {}
    for group_name, entries in raw.items():
        if not isinstance(entries, dict):
            logger.warning("Skipping non-dict group %r in %s", group_name, _REGISTRY_YAML_PATH)
            continue
        for site_key, url in entries.items():
            # YAML parses bare numeric keys like `12306` and `58` as ints;
            # coerce defensively so the file doesn't have to quote everything.
            if isinstance(site_key, (int, float)):
                site_key = str(site_key)
            if not isinstance(site_key, str) or not isinstance(url, str):
                logger.warning(
                    "Skipping invalid entry %r=%r in group %r", site_key, url, group_name,
                )
                continue
            key = site_key.strip().lower()
            if key in flat:
                logger.warning(
                    "Duplicate site key %r in registry; %r overrides previous entry",
                    key, group_name,
                )
            flat[key] = url.strip()
    return flat


SITE_REGISTRY: dict[str, str] = _load_site_registry()

# Reverse map: registry canonical URL hostname → site key.
# Checked first in resolve_site_for_url so that subdomain-distinguished sites
# (tieba.baidu.com → "tieba", pan.baidu.com → "baidu_pan") are resolved correctly
# before the generic heuristic runs.
_REGISTRY_HOST_TO_KEY: dict[str, str] = {
    urlparse(url).hostname or "": key
    for key, url in SITE_REGISTRY.items()
    if urlparse(url).hostname
}

# Subdomains stripped when deriving a site key (order matters: longer first).
_STRIPPED_SUBDOMAIN_PREFIXES = ("mobile.", "www.", "m.", "h5.", "wap.", "pc.")

# Generic TLD-ish suffixes to drop when picking the registrable label.
# We don't need perfect public-suffix accuracy — the site key is only a bucket
# name used to look up an entry the user chose when registering it.
_SECOND_LEVEL_SUFFIXES = {"com", "net", "org", "co", "gov", "edu", "ac", "cn"}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except OSError:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def load_index() -> dict[str, dict[str, Any]]:
    if not INDEX_PATH.exists():
        return {}
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read login contexts index %s: %s", INDEX_PATH, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("login contexts index has unexpected shape; resetting to empty")
        return {}
    return data


def save_index(index: dict[str, dict[str, Any]]) -> None:
    _atomic_write(INDEX_PATH, json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True))


DEFAULT_PROFILE_KEY = "_default"


def _normalize(site_entry: Any) -> dict[str, dict[str, Any]]:
    """Coerce a raw index value to ``{profile_key: entry, ...}``.

    Legacy single-entry shape (``{context_id, ...}``) is migrated on read to
    ``{"_default": <old>}`` so old indexes still resolve. The on-disk file is
    only rewritten on the next upsert.
    """
    if not isinstance(site_entry, dict):
        return {}
    if "context_id" in site_entry:
        return {DEFAULT_PROFILE_KEY: dict(site_entry)}
    return {k: v for k, v in site_entry.items() if isinstance(v, dict)}


def upsert(site: str, entry: dict[str, Any]) -> None:
    upsert_profile(site, DEFAULT_PROFILE_KEY, entry)


def upsert_profile(site: str, profile_key: str, entry: dict[str, Any]) -> None:
    index = load_index()
    profiles = _normalize(index.get(site))
    profiles[profile_key] = entry
    index[site] = profiles
    save_index(index)


def remove(site: str) -> bool:
    index = load_index()
    if site not in index:
        return False
    del index[site]
    save_index(index)
    return True


def remove_profile(site: str, profile_key: str) -> bool:
    index = load_index()
    if site not in index:
        return False
    profiles = _normalize(index.get(site))
    if profile_key not in profiles:
        return False
    del profiles[profile_key]
    if profiles:
        index[site] = profiles
    else:
        del index[site]
    save_index(index)
    return True


def get_by_site(site: str) -> dict[str, Any] | None:
    profiles = _normalize(load_index().get(site))
    if not profiles:
        return None
    if DEFAULT_PROFILE_KEY in profiles:
        return profiles[DEFAULT_PROFILE_KEY]
    return next(iter(profiles.values()))


def get_by_site_profile(site: str, profile_key: str | None) -> dict[str, Any] | None:
    """Look up the saved login entry for one (site, profile_key) pair.

    When ``profile_key`` is explicitly specified, only that profile's entry is
    returned — no fallback to a legacy ``_default`` entry. Preserves the
    soft-fail contract: a task whose region requires a profile the user has
    not registered runs without login state, rather than silently injecting
    cookies that were captured against a different endpoint.

    When ``profile_key`` is None (no ``lexmount_profiles`` configured, or the
    task's region key is not in the profile map), the ``_default`` entry is
    returned as the legacy single-profile fallback.
    """
    profiles = _normalize(load_index().get(site))
    if not profiles:
        return None
    if profile_key:
        return profiles.get(profile_key)
    return profiles.get(DEFAULT_PROFILE_KEY)


def get_profiles_for_site(site: str) -> dict[str, dict[str, Any]]:
    return _normalize(load_index().get(site))


def _extract_host(url_or_host: str) -> str:
    s = (url_or_host or "").strip().lower()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    host = urlparse(s).hostname or ""
    return host


def resolve_site_for_url(url_or_host: str | None) -> str | None:
    """Normalize ``url_or_host`` to a short site key used as index bucket.

    Examples::

        www.xiaohongshu.com        -> xiaohongshu
        https://m.jd.com/item/1    -> jd
        mp.weixin.qq.com           -> qq       (one key per registrable domain)
        www.xiaohongshu.com或其他   -> xiaohongshu  (best-effort: tolerates junk)
    """
    if not url_or_host:
        return None
    # Some task rows put noisy values like "www.xiaohongshu.com或其他" —
    # keep just the hostname-looking prefix.
    match = re.match(r"[A-Za-z0-9._\-:/]+", url_or_host.strip())
    if not match:
        return None
    candidate = match.group(0)
    host = _extract_host(candidate)
    if not host:
        return None

    # Registry reverse-lookup takes priority over the heuristic so that
    # subdomain-distinguished sites resolve correctly:
    #   tieba.baidu.com  → "tieba"  (not "baidu")
    #   pan.baidu.com    → "baidu_pan"
    #   mail.qq.com      → "qq_mail"
    if host in _REGISTRY_HOST_TO_KEY:
        return _REGISTRY_HOST_TO_KEY[host]

    for prefix in _STRIPPED_SUBDOMAIN_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
            break

    labels = [lab for lab in host.split(".") if lab]
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0] or None

    # Drop generic TLD-ish suffixes from the right, then take the label
    # immediately left of the TLD. Treats qq.com as the registrable domain
    # for *.qq.com subdomains — one site key per registrable domain.
    while len(labels) > 1 and labels[-1] in _SECOND_LEVEL_SUFFIXES:
        labels.pop()
    return labels[-1] or None
