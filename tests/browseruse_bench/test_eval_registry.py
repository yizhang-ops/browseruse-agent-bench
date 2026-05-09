"""Tests for evaluator registry."""
from __future__ import annotations

import pytest

from browseruse_bench.eval.base import BaseEvaluator
from browseruse_bench.eval.registry import (
    get_evaluator_class,
    list_evaluators,
    register_evaluator,
)


class _Stub(BaseEvaluator):
    name = "Stub-Bench"
    default_mode = "stub_mode"

    def load_tasks(self):
        return {}

    def evaluate_one(self, *args, **kwargs):
        raise NotImplementedError


def test_register_and_get():
    @register_evaluator("Stub-Bench")
    def _factory():
        return _Stub

    cls = get_evaluator_class("Stub-Bench")
    assert cls is _Stub
    assert "Stub-Bench" in list_evaluators()


def test_unknown_raises():
    with pytest.raises(KeyError):
        get_evaluator_class("Definitely-Not-Registered")


def test_builtin_names_registered():
    """Default factories should be bound (calling them may ImportError until subpackages exist)."""
    names = list_evaluators()
    for n in ("Online-Mind2Web", "BrowseComp", "LexBench-Browser"):
        assert n in names
