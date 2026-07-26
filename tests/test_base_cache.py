# tests/test_base_cache.py
"""The base-layer cache: the store, the key, and cached-vs-cold pixel equality.

The cache exists because ~90% of every proof is terrain that the knob being dragged
cannot change (see docs/superpowers/plans/2026-07-26-base-layer-cache.md). That makes
it a correctness risk as much as a speed win: a cache that serves a stale base produces
a proof that no longer predicts the print, which is the one bug class this product
cannot have. These tests are the guard, and the field-enumeration test below is the
one that keeps it honest as the spec grows.
"""
import dataclasses
import json
import os

import numpy as np
import pytest

from app import basecache


def test_put_then_get_returns_the_entry():
    c = basecache.BaseCache(1000)
    c.put("k", "payload", 10)
    assert c.get("k") == "payload"
    assert c.stats()["entries"] == 1
    assert c.stats()["bytes"] == 10


def test_missing_key_returns_none_and_counts_a_miss():
    c = basecache.BaseCache(1000)
    assert c.get("nope") is None
    assert c.stats()["misses"] == 1
    assert c.stats()["hits"] == 0


def test_eviction_is_least_recently_used_and_respects_the_budget():
    c = basecache.BaseCache(100)
    c.put("a", "A", 40)
    c.put("b", "B", 40)
    c.get("a")                       # 'a' is now the most recently used
    c.put("c", "C", 40)              # 120 > 100, so the LRU ('b') goes
    assert c.get("b") is None
    assert c.get("a") == "A"
    assert c.get("c") == "C"
    assert c.stats()["bytes"] <= 100


def test_an_entry_larger_than_the_budget_is_never_admitted():
    # admitting it would evict everything else and then be evicted itself
    c = basecache.BaseCache(100)
    c.put("small", "S", 50)
    c.put("huge", "H", 500)
    assert c.get("huge") is None
    assert c.get("small") == "S"


def test_replacing_a_key_does_not_double_count_its_bytes():
    c = basecache.BaseCache(1000)
    c.put("k", "v1", 100)
    c.put("k", "v2", 100)
    assert c.get("k") == "v2"
    assert c.stats()["bytes"] == 100


def test_a_zero_budget_disables_the_cache_entirely():
    c = basecache.BaseCache(0)
    assert not c.enabled
    c.put("k", "v", 1)
    assert c.get("k") is None
    assert c.stats()["entries"] == 0


def test_clear_empties_the_store():
    c = basecache.BaseCache(1000)
    c.put("k", "v", 10)
    c.clear()
    assert c.get("k") is None
    assert c.stats()["bytes"] == 0
