"""The showcase plates' stories: marketing/stories.toml, one table per plate.

A plate with no table has no story, and its demo trips compose as they always did.
Spec: docs/superpowers/specs/2026-11-01-showcase-plates-and-pick-a-plate-landing-design.md,
sections 7 and 8."""
from __future__ import annotations

import os
import tomllib

STORIES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "marketing", "stories.toml")


def load_stories(path: str = STORIES) -> dict[str, dict]:
    """Every plate's table, keyed by region id, without the file's own `status`."""
    with open(path, "rb") as f:
        return {k: v for k, v in tomllib.load(f).items() if isinstance(v, dict)}


def story_for(region_id: str) -> dict | None:
    """One plate's story, or None for a plate that has none."""
    return load_stories().get(region_id)
