# Agents

This repo's guide for any coding agent is `CLAUDE.md`. Read it first. It
routes every change to the one document that governs it. The index of
everything under `docs/` is `docs/README.md`.

Dev server: `.venv/bin/uvicorn app.main:app --reload`. Tests:
`.venv/bin/python -m pytest -n auto -m "not slow" -q` is the fast tier and
`.venv/bin/python -m pytest -n auto -q` the full suite. There is no build for
the engine. The macOS launcher is `scripts/macos/build_app.sh --install`, and
the landing page deploys by hand only, per `marketing/DEPLOY.md`.

Two rules an agent breaks most easily: never size anything visual in pixels
(physical units always, because a pixel-sized element looks bold in the proof
and vanishes in the final), and never install the region-prep stack into
`.venv` (it belongs in `.venv-prep`, and it pulls numpy, scipy, and rasterio
past their pins).
