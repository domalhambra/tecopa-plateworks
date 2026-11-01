# Pick-a-plate landing, Phase A: layout and content, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write every sentence of the new Tecopa landing page, record the story config as a plan, and build the page on an unmerged plateworks-site branch with empty image slots.

**Architecture:** The copy document is the source of each sentence. `marketing/stories.toml` holds the same headings for the farm, and a test binds the two. In plateworks-site, one new module (`plates.js`) opens one story at a time over plain HTML that stacks all five without the script. `sections.js` learns to leave the stories alone, and the relief viewer learns to release its WebGL context.

**Tech Stack:** Python 3.14 with `tomllib` and pytest (tecopa-plateworks). Astro, vanilla ES modules, Vitest with jsdom, nested CSS (plateworks-site).

**Spec:** `docs/superpowers/specs/2026-11-01-showcase-plates-and-pick-a-plate-landing-design.md`, sections 3, 4, 5, 8 (story config only), 9, 10, 12 (Phase A). Phase B (steps 5 to 12 of section 12) is out of this plan and starts when Dom says the overhauls landed.

## Global Constraints

- Nothing in this plan renders an image, builds a plate, or fetches a network.
- No change to `app/`, `scripts/`, `regions/` or `tests/test_marketing_page.py` in tecopa-plateworks. Another session is overhauling the generator.
- The plateworks-site branch is `tecopa-pick-a-plate`. It is pushed for backup. It gets no pull request and no merge in this phase, because a merge there is a deploy.
- Empty slots are neutral blocks in the page's grounds. Never show a render of another plate under a new plate's name.
- Today's six coins and today's tail stay in the page unchanged. The doubled Susanville poster stays until Phase B.
- Plate ids: `canyonlands_ut`, `tahoe_ca`, `eastern_sierra_ca`, `ruby_mountains_nv`, `zion_ut`. Anchors, in page order: `canyonlands`, `tahoe`, `sierra`, `rubies`, `zion`. Default story: `tahoe`.
- Copy: no em dashes, contractions where speech has them, sentence case, the full name Tecopa Plateworks, no sentence of the shape "I X by Y", one or two sentences under each heading, numbers only where a customer would count them, the place named first in every caption. The word "buy" never appears within three sentences of "plate".
- The heading over the stories is exactly: "Every one is real country and real trails, lit so the mountains stand up off the paper."
- Phone: 44 px coins in one row, shrinking to 34 px when stuck. At most eight live relief viewers. `prefers-reduced-motion: reduce` stops all motion.
- Use a git worktree in each repo (superpowers:using-git-worktrees), because other sessions work in these checkouts. In tecopa-plateworks run the main checkout's `.venv/bin/python` from the worktree. In plateworks-site run `npm ci` and `npm --prefix theme ci` in the worktree.

## Review Focus

- A link to `#prices` or `#how-it-works` must leave the open story open. Pinned in Task 4 (`storyFromHash`).
- A nested `<article>` in the page ends the slice `article()` in the live honesty tests at the first `</article>`, so every later claim would look absent. Pinned in Task 7 (the page test).
- The script failing part way must leave all five stories readable, never one or none. Pinned in Task 4 (`initPlates` with a bad stage) and by the pre-ready CSS rule in Task 8.
- The sticky row must not cover a story's title after a coin tap. Checked in Task 9 (the browser check measures the title's top against the row's bottom).
- A second open of the story already open, or a fast run of opens, must not create a second viewer or dispose one twice. Pinned in Task 4.

---

### Task 1: Commit the approved spec and this plan

**Files:**
- Modify: `docs/superpowers/specs/2026-11-01-showcase-plates-and-pick-a-plate-landing-design.md:4`
- Create: `docs/superpowers/plans/2026-11-01-pick-a-plate-phase-a.md` (this file)

- [ ] **Step 1: Set the spec's status line** to `**Status:** Approved by Dom, 2026-11-01. Brainstormed with Dom in a Claude Code session on 2026-11-01. Mockups in ...`, keeping the rest of the line.
- [ ] **Step 2: Create the branch and commit.** Branch `pick-a-plate-phase-a` in tecopa-plateworks. Commit message: `Plan the Pick-a-plate landing page: spec and Phase A plan`.
- [ ] **Step 3: Run the impact check.** Run `python3 scripts/docs_check.py --impact origin/main`. Expected: exit 0.

### Task 2: The copy document

**Files:**
- Create: `docs/superpowers/specs/2026-11-01-pick-a-plate-landing-copy.md`
- Test: `tests/test_stories_config.py` (the copy half)

**Interfaces:**
- Produces: the document's structure, which Tasks 3 and 7 read. One `## <Plate name>` per story, in page order. Under it: `Anchor:`, `Eyebrow:`, `Title:`, `Poster alt:`, `Poster caption:`, then `### Section <n>: <heading>` with `Feature eyebrow:`, `Body:` and `Image alt:` lines.

- [ ] **Step 1: Read the governing documents.** Read `docs/superpowers/specs/2026-08-16-target-customer-profile-design.md`, `00-09 System/00 Resources/voice-principles.md`, and spec sections 4, 5 and 10.

- [ ] **Step 2: Write the failing test.**

```python
SPEC_DIR = REPO / "docs/superpowers/specs"
COPY = SPEC_DIR / "2026-11-01-pick-a-plate-landing-copy.md"

def test_copy_has_five_stories_of_three_sections():
    text = COPY.read_text()
    assert re.findall(r"^Anchor: (\w+)$", text, re.M) == ["canyonlands", "tahoe", "sierra", "rubies", "zion"]
    assert len(re.findall(r"^### Section [123]: ", text, re.M)) == 15

def test_copy_says_real_trails_and_stays_in_register():
    text = COPY.read_text()
    assert "Every one is real country and real trails, lit so the mountains stand up off the paper." in text
    assert "—" not in text
    assert not re.search(r"\bI [a-z]+[^.]*\bby\b", text)
    for phrase in banned_phrases():   # RETIRED, RETIRED_2026_09, RETIRED_2026_10_12, BUILDER_REGISTER
        assert phrase not in text
```

`banned_phrases()` loads those four lists from `tests/test_marketing_page.py` with `importlib.util.spec_from_file_location`. It does not copy them. Importing that file runs no live request.

- [ ] **Step 3: Run the test.** Run `.venv/bin/python -m pytest tests/test_stories_config.py -q`. Expected: FAIL, the file is missing.

- [ ] **Step 4: Write the document.** It holds, in page order: the chooser's accessible label, the heading over the stories, the five stories, the heading "More country" and its one line, and the tail quoted from `src/content/pages/tecopa.html` unchanged. Use the section headings from the spec's table in section 4 as they stand, shaped as full plain statements where the table has shorthand. Write the Tahoe section 3 and Zion section 2 copy for a real photograph. Mark any sentence that depends on a count or a place in a render with `(check against the crop)`. Zion section 1 needs two sentences that never blur: a caption saying what the light in this render is, and the product claim about the sun of the day you were there. The Ruby Mountains section 2 does not promise the dry lake's name.

- [ ] **Step 5: Run the test.** Same command. Expected: PASS.

- [ ] **Step 6: Commit.** Message: `Write every sentence of the Pick-a-plate page for Dom's read`.

### Task 3: The story config as a plan

**Files:**
- Create: `marketing/stories.toml`
- Modify: `tests/test_stories_config.py`
- Modify: `marketing/README.md` (a short section: what the file is, and that nothing reads it until Phase B)

**Interfaces:**
- Consumes: the copy document's headings (Task 2).
- Produces: for Phase B, one table per plate id with keys `anchor`, `name`, `eyebrow`, `destinations` (list of names), `trips` (list of tables with `shape`, and `road` for a `drive`), `look` (empty table until Phase B), and `[[<id>.sections]]` with `heading`, `feature`, `variant`, `crop_place`. Top-level `status = "plan"`. `crop_center_m` and `crop_in` are added in Phase B.

- [ ] **Step 1: Write the failing tests.**

```python
def test_config_lists_the_five_plates_in_page_order():
    cfg = tomllib.loads(STORIES.read_text())
    assert cfg["status"] == "plan"
    plates = [k for k in cfg if k != "status"]
    assert plates == ["canyonlands_ut", "tahoe_ca", "eastern_sierra_ca", "ruby_mountains_nv", "zion_ut"]
    assert [cfg[p]["anchor"] for p in plates] == ["canyonlands", "tahoe", "sierra", "rubies", "zion"]

def test_every_section_heading_is_in_the_copy_document():
    cfg, text = tomllib.loads(STORIES.read_text()), COPY.read_text()
    for plate in PLATES:
        assert len(cfg[plate]["sections"]) == 3
        for section in cfg[plate]["sections"]:
            assert section["heading"] in text
            assert section["crop_place"]

def test_drive_trips_name_their_road():
    cfg = tomllib.loads(STORIES.read_text())
    assert {"shape": "drive", "road": "White Rim Road"} in cfg["canyonlands_ut"]["trips"]
    assert {"shape": "drive", "road": "Lamoille Canyon Road"} in cfg["ruby_mountains_nv"]["trips"]
```

- [ ] **Step 2: Run the tests.** Run `.venv/bin/python -m pytest tests/test_stories_config.py -q`. Expected: FAIL, the file is missing.

- [ ] **Step 3: Write `marketing/stories.toml`.** Take destinations from the spec's section 6 "Must hold" column and section 7: Ruby Mountains pins Lamoille Lake, Island Lake and Liberty Pass; Zion pins Angels Landing and Observation Point; Tahoe pins Freel Peak, Mount Tallac, Mount Rose and Pyramid Peak. Describe each crop in words, for example "the Confluence, looking into the inner gorge". Variants: `poster` everywhere, except Zion section 1 (`poster_journey`), Zion section 3 (`editions`) and Sierra section 3 (`film`). A comment says a name is checked against `labels.json` and `hydro.json` in Phase B, and that a name that does not resolve fails that run.

- [ ] **Step 4: Run the tests and the docs check.** Run the pytest command, then `python3 scripts/docs_check.py --impact origin/main`. Expected: PASS, exit 0.

- [ ] **Step 5: Commit and open the pull request.** Message: `Record the five stories as a plan the farm reads in Phase B`. The description ends with `Docs: marketing/README.md, docs/superpowers/specs/2026-11-01-*`. Dom merges it. It changes no code path.

### Task 4: `plates.js`, the chooser's behaviour

**Files:**
- Create: `theme/assets/js/tecopa/plates.js`
- Test: `theme/assets/js/tecopa/__tests__/plates.test.js`

All plateworks-site tasks work on branch `tecopa-pick-a-plate`.

**Interfaces:**
- Consumes: `placeHeroRelief(content, stage)` from `sections.js`.
- Produces:
  - `storyFromHash(hash: string, ids: string[]) -> string | null`
  - `hiddenStories(openId: string, ids: string[]) -> string[]`
  - `isStuck(sentinelTop: number, headerBottom: number) -> boolean`, true when `sentinelTop < headerBottom`
  - `initPlates(content: Element, stage: Element) -> { open(id): void, current(): string, ids: string[], attachViewers(factory): void, figure: Element | null }`, or `null` when the page holds no `.tecopa-plates`

- [ ] **Step 1: Write the failing tests** (`@vitest-environment jsdom`). Build a fixture of three `.tecopa-story` sections, one with `data-plate-default`, each with a `.tecopa-hero-relief` figure, one with a `[data-relief-surface][data-relief-height]` element, and a chooser link per story. `scrollIntoView` is stubbed.

```js
expect(storyFromHash('#tahoe', ids)).toBe('tahoe');
expect(storyFromHash('#prices', ids)).toBeNull();
expect(storyFromHash('', ids)).toBeNull();
expect(hiddenStories('tahoe', ['a', 'tahoe', 'b'])).toEqual(['a', 'b']);
expect(isStuck(10, 60)).toBe(true);
expect(isStuck(60, 60)).toBe(false);
```

Named tests, each asserting what its name says:
  - `opens the data-plate-default story with no hash, and hides the others with the hidden attribute`
  - `opens the hash's story on load and scrolls to it`
  - `does not scroll on load with no hash`
  - `a hashchange to a story opens it and scrolls; a hashchange to #prices changes nothing`
  - `moves the open story's figure into the stage and returns the last one to its own story, in its first position`
  - `sets aria-current="true" on the open coin only`
  - `writes the open plate's data-plate-name and data-plate-eyebrow under the row`
  - `attachViewers creates one viewer per relief element of the open story and its staged figure, and disposes them when the story closes`
  - `opening the open story again creates no viewer and disposes none`
  - `a story with no relief elements opens with no viewer`
  - `if the stage is missing, returns null and leaves every story visible`

- [ ] **Step 2: Run the tests.** Run `npm --prefix theme run test:unit -- tecopa/__tests__/plates`. Expected: FAIL, no module.

- [ ] **Step 3: Implement `plates.js`.** Stories come from `root.querySelectorAll('.tecopa-story')`. Links stay real anchors with no `preventDefault`, so Back works, and a `hashchange` listener does the opening. The story swaps with no animation at any motion setting, and the scroll is `scrollIntoView({ block: 'start', behavior: 'instant' })`. The sticky watch uses an `IntersectionObserver` on `.tecopa-chooser__sentinel` and sets `is-stuck` on `.tecopa-chooser`. The sentinel sits above the row, so the row's shrink cannot flip the state. The module sets `--tecopa-chooser-top` from the bottom of `.navbar` when that element's computed position is `sticky` or `fixed`, else `0px`, and re-reads it on resize.

- [ ] **Step 4: Run the tests.** Same command. Expected: PASS.

- [ ] **Step 5: Commit.** Message: `Open one Tecopa story at a time, from the coins and the hash`.

### Task 5: Wire the stories into the page's structure

**Files:**
- Modify: `theme/assets/js/tecopa/sections.js` (`classifySection`)
- Modify: `theme/assets/js/tecopa/relief.js` (`ReliefViewer.dispose`, `initReliefs`)
- Modify: `theme/assets/js/tecopa/index.js`
- Test: `theme/assets/js/tecopa/__tests__/sections.test.js`, `theme/assets/js/tecopa/__tests__/relief-lifecycle.test.js` (new)

**Interfaces:**
- Consumes: `initPlates` and its return value (Task 4).
- Produces: `ReliefViewer.dispose() -> void`. `initReliefs(root)` skips any element inside `.tecopa-story` or `.tecopa-hero__stage`, since `plates.js` owns those.

- [ ] **Step 1: Write the failing tests.**
  - `sections.test.js`: `a section holding .tecopa-plates is classed stories only`. Its fixture puts a video card, a three-image gallery, a two-image gallery and a disc relief inside a story, and asserts `dataset.kinds === 'stories'` and no `.tecopa-section__text` wrapper.
  - `relief-lifecycle.test.js`: `initReliefs leaves story and stage reliefs to plates.js`, and `dispose restores the fallback image, removes the canvas and is safe to call twice`. Both go in a new file with `@vitest-environment jsdom`, because `relief.test.js` runs without a DOM. Stub `IntersectionObserver`, and stub `getContext` to return null, which sends the viewer down its fallback path.

- [ ] **Step 2: Run the tests.** Run `npm --prefix theme run test:unit -- tecopa/__tests__`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement.** `classifySection` returns `['stories']` first when the section holds `.tecopa-plates`. `dispose()` cancels the frame, runs `this.cleanups`, calls `WEBGL_lose_context.loseContext()` when the extension exists, removes the canvas, clears `el.tecopaRelief` and the `tecopa-relief` class, and shows the fallback image. In `index.js`, replace the `placeHeroRelief` call with `state.plates = attempt('plates', () => initPlates(content, stage))`, taking the title phrase from `state.plates?.figure`. At the end of `boot`, after `initReliefs`, call `state.plates?.attachViewers((el) => new ReliefViewer(el))`.

- [ ] **Step 4: Run all the tests.** Run `npm test`. Expected: PASS, with the same failure set as `main` (none).

- [ ] **Step 5: Commit.** Message: `Let the stories hold films and galleries without reclassifying the page; release a viewer's context`.

### Task 6: The before-and-after comparison

**Files:**
- Create: `theme/assets/js/tecopa/compare.js`
- Modify: `theme/assets/js/tecopa/index.js`
- Test: `theme/assets/js/tecopa/__tests__/compare.test.js`

**Interfaces:**
- Produces: `splitPercent(value: string | number) -> number`, clamped to 0 to 100, and `initCompare(root: Element) -> Element[]`. Markup it reads: `.tecopa-compare` holding two `.tecopa-compare__side` figures, each with a `figcaption` of "Before" or "After".

- [ ] **Step 1: Write the failing tests.** Assert: `splitPercent` clamps `-5`, `120` and `'40'`; `initCompare` adds `is-live`, sets `--split: 50%`, and appends one `input[type=range]` with an `aria-label`; an `input` event updates `--split`; a page with no `.tecopa-compare` returns `[]`.

- [ ] **Step 2: Run the tests.** Run `npm --prefix theme run test:unit -- tecopa/__tests__/compare`. Expected: FAIL.

- [ ] **Step 3: Implement.** A transparent range input over the pair is the divider. It gives keyboard use and finger tracking with no pointer code. Set `touch-action: pan-y` in Task 8, so a vertical swipe still scrolls the page. Call `initCompare(root)` from `index.js` inside `attempt`.

- [ ] **Step 4: Run the tests.** Same command. Expected: PASS.

- [ ] **Step 5: Commit.** Message: `Add the before-and-after divider for Zion's Journey Light pair`.

### Task 7: The page's markup

**Files:**
- Modify: `src/content/pages/tecopa.html`
- Create: `test/tecopa-page.test.js`

**Interfaces:**
- Consumes: the copy document (Task 2), the classes from Tasks 4 to 6.
- Produces, for Phase B: each empty slot is `<div class="tecopa-slot" data-slot="<id>-<asset>" aria-hidden="true"></div>`, with assets `coin`, `poster`, `story-1` to `story-3`, plus `journey-before`, `journey-after`, `edition-1` to `edition-3` for Zion and `film` for the Sierra. Phase B replaces each one with its image, and the slot's name matches the file name in spec section 9.

- [ ] **Step 1: Write the failing test.** Parse the file with `linkedom`, after the front matter.

```js
expect(doc.querySelectorAll('.tecopa-story').length).toBe(5);
expect([...doc.querySelectorAll('.tecopa-story')].map((s) => s.id))
  .toEqual(['canyonlands', 'tahoe', 'sierra', 'rubies', 'zion']);
expect(doc.querySelectorAll('[data-plate-default]').length).toBe(1);
expect(doc.querySelector('[data-plate-default]').id).toBe('tahoe');
expect(html).not.toMatch(/<article/);
expect(html).not.toContain('—');
expect(html).toContain('real trails');
expect(html).not.toContain('real trips');
expect(doc.querySelectorAll('.tecopa-chooser a[data-evt="Plate Pick"]').length).toBe(5);
expect(doc.querySelectorAll('.tecopa-coins [data-relief-shape="disc"]').length).toBe(6);
expect(doc.querySelectorAll('.tecopa-story img:not([loading="lazy"])').length).toBe(0);
expect(doc.querySelector('.tecopa-compare')).not.toBeNull();
expect(doc.querySelectorAll('.tecopa-story .tecopa-story__part').length).toBe(15);
```

Each `tecopa-story` must also hold `.tecopa-hero-relief` as its first figure, and each coin link's `href` must match a story id.

- [ ] **Step 2: Run the test.** Run `npx vitest run test/tecopa-page.test.js`. Expected: FAIL.

- [ ] **Step 3: Rewrite the body, keeping the front matter.** In this order:
  1. `<h2 id="posters-ive-made">` with the new heading. The id stays, since links may hold it.
  2. `<div class="tecopa-plates">`: `.tecopa-chooser__sentinel`, then `<nav class="tecopa-chooser">` with five `<a class="tecopa-chooser__coin" href="#<anchor>" data-evt="Plate Pick" data-evt-where="<anchor>">`, each holding a coin slot and a `.tecopa-chooser__label` with the plate's name, then `<p class="tecopa-chooser__name">`, then the five `<section class="tecopa-story" id="<anchor>" aria-labelledby="<anchor>-title" data-plate-name data-plate-eyebrow>`.
  3. In a story: the `.tecopa-hero-relief` figure (`data-title-em="everywhere you've been"` on every story's figure, a poster slot, a `figcaption`), the eyebrow, `<h3 id="<anchor>-title">`, then three `<div class="tecopa-story__part">`, each a slot, a `.tecopa-eyebrow`, an `<h4>` and the body. Never use `<article>`. Canyonlands' first part also holds a coin slot, the relief coin to turn. Zion's first part holds `.tecopa-compare`, and its third holds three edition slots. The Sierra's third is a film slot.
  4. `<h2 id="more-country">More country</h2>` with its one line, then today's `.tecopa-coins` block byte for byte, then today's `#how-it-works`, the Start button, `#add-next-years-trips`, `#prices` and `#questions` byte for byte. Remove today's wall gallery, `#up-close`, `#see-the-relief` and `#watch-a-poster-come-together`. `npm run check` proves no address depends on them.

- [ ] **Step 4: Check the copy against the page.** From the tecopa-plateworks worktree, run a one-off that loads `marketing/stories.toml` and asserts each `heading` is in the page file. Expected: no assertion fails.

- [ ] **Step 5: Run the test.** Same command as Step 2. Expected: PASS.

- [ ] **Step 6: Commit.** Message: `Rebuild the Tecopa page around five stories, with empty image slots`.

### Task 8: The layout

**Files:**
- Modify: `theme/assets/css/templates/custom-tecopa.css`
- Modify: `README.md` (one paragraph on the chooser, the stories and the phone layout)

- [ ] **Step 1: Add the rules, under the existing `.template-tecopa` nesting.**
  - `.tecopa-story[hidden] { display: none; }`.
  - Before the script is ready, one story shows, with no flash of all five: `:root.tecopa-js:not(.tecopa-ready) .tecopa-story:not([data-plate-default], :target) { display: none; }`. The 4 s failsafe in `Tecopa.astro` removes `tecopa-js`, so all five stack if the script never arrives.
  - `.tecopa-chooser`: `position: sticky`, `top: var(--tecopa-chooser-top, 0px)`, in the page's ground, above the story content. It is a child of `.tecopa-plates`, so it stops sticking where More country starts.
  - Coins: 44 px in one row with `justify-content: space-between`. `is-stuck` makes them 34 px. The content below must not visibly jump when the row shrinks.
  - `.tecopa-chooser__label`: visually hidden when scripts run, shown as a stacked list of links under `:root:not(.tecopa-js)`.
  - `.tecopa-story { scroll-margin-top: calc(var(--tecopa-chooser-top, 0px) + <stuck row height>); }`.
  - `.tecopa-story__part`: stacks at phone width, one per screen, as the page's cards do today. Above `--breakpoint-md`, reuse the `feature` layout's grid.
  - `.tecopa-slot`: a neutral block in the page's ground colors, with the aspect its image will have (coin round, poster about 0.81, story 4:3, compare 4:3, edition about 0.8). No color outside `vars.css`.
  - `.tecopa-compare`: two sides side by side with captions. With `is-live` they stack in one frame, the top side clipped by `--split`, with the range input on top and `touch-action: pan-y`.
  - Under `prefers-reduced-motion: reduce`: no transition on the coins or the row.

- [ ] **Step 2: Check colors.** Run `git diff main -- theme/assets/css | grep -E '^\+.*#[0-9a-fA-F]{3,8}\b'`. Expected: no output, so every new color comes from `vars.css`.

- [ ] **Step 3: Commit.** Message: `Lay out the chooser and the stories at phone and desk width`.

### Task 9: Verify on a local build

**Files:** none, unless a check fails.

- [ ] **Step 1: Run the suite.** Run `npm test && npm run build && npm run check`. Expected: every step exits 0.

- [ ] **Step 2: Drive the page in the browser pane at 375 px and at desk width.** Serve the build with `npm run preview` through a `.claude/launch.json` entry. Check each of these, and fix what fails:
  - Five coins fit in one row at 375 px and at 320 px, with no horizontal page scroll (`document.documentElement.scrollWidth <= innerWidth`).
  - Each coin opens its story, and the hero stage shows that story's figure.
  - After a coin tap, the story title's top is at or below the row's bottom.
  - The row shrinks and sticks while reading, and it no longer sticks at More country. This also proves no ancestor breaks `position: sticky`.
  - `/tecopa/#zion` opens Zion on load. Back returns to the last story. `#prices` leaves the story open.
  - The six More country coins draw. Run `el.tecopaRelief.dispose()` on one: the fallback image shows, and the console has no error.
  - The divider moves by keyboard. A vertical drag on it at phone width scrolls the page.
  - With JavaScript off (a build check on the HTML is not enough, so block the script in the pane): all five stories stack, and the coins are a list of links.

- [ ] **Step 3: Push the branch.** Run `git push -u origin tecopa-pick-a-plate`. Open no pull request. Record proof screenshots at both widths for Dom.

- [ ] **Step 4: Record the open work.** Add one STATE.md row in the session log repo. Owner Dom. Item: start Phase B when the generator overhauls land; the branch `tecopa-pick-a-plate` waits. Check that closes it: the live tests pass against the shipped page. Add the session entry in the same commit, per CONVENTION.md.

Viewer behaviour on real story posters is not exercised in this phase, because the slots are empty. Phase B checks it at step 9 of the spec's section 12, including the eight-viewer limit.
