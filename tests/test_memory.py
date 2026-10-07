"""Tests for app.memory — MemoryStore using temp SQLite."""
from __future__ import annotations

import pytest
from app.memory.models import MemoryCategory, MemoryEntry
from app.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_initialize(memory_store):
    assert memory_store is not None


@pytest.mark.asyncio
async def test_remember_creates_entry(memory_store):
    entry = await memory_store.remember(MemoryCategory.PREFERENCES, "theme", "dark")
    assert entry.key == "theme"
    assert entry.value == "dark"
    assert entry.category == MemoryCategory.PREFERENCES


@pytest.mark.asyncio
async def test_remember_updates_existing(memory_store):
    await memory_store.remember(MemoryCategory.PREFERENCES, "theme", "dark")
    entry = await memory_store.remember(MemoryCategory.PREFERENCES, "theme", "light")
    assert entry.value == "light"


@pytest.mark.asyncio
async def test_recall_by_category(memory_store):
    await memory_store.remember(MemoryCategory.PREFERENCES, "k1", "v1")
    await memory_store.remember(MemoryCategory.USER_PROFILE, "k2", "v2")
    results = await memory_store.recall(category=MemoryCategory.PREFERENCES)
    assert len(results) == 1
    assert results[0].key == "k1"


@pytest.mark.asyncio
async def test_recall_by_key(memory_store):
    await memory_store.remember(MemoryCategory.PREFERENCES, "color", "blue")
    results = await memory_store.recall(category=MemoryCategory.PREFERENCES, key="color")
    assert len(results) == 1
    assert results[0].value == "blue"


@pytest.mark.asyncio
async def test_recall_with_query(memory_store):
    await memory_store.remember(MemoryCategory.PREFERENCES, "food", "apple pie")
    results = await memory_store.recall(query="apple")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_forget_by_entry_id(memory_store):
    entry = await memory_store.remember(MemoryCategory.PREFERENCES, "tmp", "val")
    deleted = await memory_store.forget(entry_id=entry.id)
    assert deleted >= 1
    results = await memory_store.recall(category=MemoryCategory.PREFERENCES, key="tmp")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_forget_by_category(memory_store):
    await memory_store.remember(MemoryCategory.TASK_HISTORY, "t1", "v1")
    await memory_store.remember(MemoryCategory.TASK_HISTORY, "t2", "v2")
    deleted = await memory_store.forget(category=MemoryCategory.TASK_HISTORY)
    assert deleted == 2


@pytest.mark.asyncio
async def test_list_memories(memory_store):
    await memory_store.remember(MemoryCategory.PREFERENCES, "a", "1")
    await memory_store.remember(MemoryCategory.PREFERENCES, "b", "2")
    memories = await memory_store.list_memories(category=MemoryCategory.PREFERENCES)
    assert len(memories) == 2


@pytest.mark.asyncio
async def test_clear_all(memory_store):
    await memory_store.remember(MemoryCategory.PREFERENCES, "x", "y")
    count = await memory_store.clear_all()
    assert count >= 1
    memories = await memory_store.list_memories()
    assert len(memories) == 0


@pytest.mark.asyncio
async def test_get_stats(memory_store):
    await memory_store.remember(MemoryCategory.PREFERENCES, "s", "v")
    stats = await memory_store.get_stats()
    assert stats["total_memories"] >= 1
    assert "by_category" in stats
