"""The showcase plates' stories: marketing/stories.toml, one table per plate.

A plate with no table has no story, and its demo trips compose as they always did.
Spec: docs/superpowers/specs/2026-11-01-showcase-plates-and-pick-a-plate-landing-design.md,
sections 7 and 8.

    ./.venv/bin/python -m scripts.story_config --ship-check   # exit 1 while a plate pins the gradient
"""
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


class StoryError(ValueError):
    """A story's config cannot be rendered: a section with no crop window, a half-given
    sun, a window that does not fit the sheet. The message names the plate or heading."""


def demo_photo_plates(path: str = STORIES) -> list[str]:
    """The plate ids that pin a photo (`photo_at`) and have no real one (`photo_file`):
    the plates whose pinned photo is still the farm's painted gradient. The ship check."""
    return [rid for rid, story in load_stories(path).items()
            if story.get("photo_at") and not story.get("photo_file")]


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Check the showcase plates' stories.")
    ap.add_argument("--ship-check", action="store_true",
                    help="list the plates still pinning the demo gradient as their photo; "
                         "exit 1 while any remain")
    ap.add_argument("--config", default=STORIES, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if not args.ship_check:
        ap.error("nothing to do: pass --ship-check")
    plates = demo_photo_plates(args.config)
    if plates:
        print("these plates still pin the demo gradient as their photo (set photo_file "
              "in marketing/stories.toml):")
        for rid in plates:
            print(f"  {rid}")
        return 1
    print("ok: no plate ships the demo photo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
