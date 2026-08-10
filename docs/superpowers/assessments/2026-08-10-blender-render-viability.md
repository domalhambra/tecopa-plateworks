# Blender as a render path: viability assessment (2026-08-10)

Question asked: is rendering Tecopa posters through Blender viable and useful, and is
there a free way to do it? Researched against primary sources (PyPI/bpy metadata,
Blender manual and developer handbook, the Huffman tutorials, license texts) on
2026-08-10; all load-bearing claims cited at the end.

## Verdict

**Free: yes, unconditionally — but don't make it the engine.** Blender is gratis for
commercial use and its outputs are the artist's sole property [12], and the AGPL app
could legally `import bpy` or bundle the binary [12][13]. It is still the wrong
engine for this product, for three hard reasons and one strategic one:

1. **No `bpy` for our Python.** The current PyPI wheel (bpy 5.2.0, Jul 2026) pins
   `requires_python ==3.13.*` — there is no 3.14 wheel, each release supports exactly
   one CPython minor, and PyPI wheels outside the LTS window get deleted [6]. In-process
   Blender is a version-lockstep treadmill; the workable integration is a subprocess
   against a user-installed binary (~330 MB per platform, permanently archived) [7].
2. **Determinism (invariant 3) cannot be promised over Cycles.** Blender documents no
   bit-exactness contract anywhere; its own render tests compare against reference
   images with per-platform thresholds, and its handbook says results "may sometimes
   be different between CPU and GPU, or between different GPUs" [9]. The OIDN denoiser
   documents cross-device numerical differences even in highest-quality mode [10].
   Same spec + seed + build → identical image would rest on an undocumented emergent
   property of a third-party binary.
3. **The film target dies.** Huffman-era guidance put practical CPU relief renders at
   3–4 MP without tiling heroics [2]; a 24×36 @ 300 dpi sheet is ~78 MP, and a film is
   hundreds of frames of it. Cycles tiles huge stills to disk fine [8], but CPU-only
   hosts are looking at hours per poster and unusable film times; only a GPU (Metal on
   Apple Silicon is well supported [8]) makes it tolerable — and the app can't assume
   one.

Strategic: **the engine already performs the Blender look's load-bearing physics,
deterministically.** The `shadow` knob is not an approximation of hillshading — it is
the Patterson/Huffman "Blender relief" recipe implemented natively in `app/relief.py`:
ray-marched cast shadows along the sun direction with a metres-based penumbra
(`PENUMBRA_M`), multi-scale sky occlusion (`AO_RADII_M` at 200/800/3200 m), cool
Imhof skylight fill in the shadows, and a luminance floor so they never go black —
seeded, resolution-independent, cheap enough for films. Huffman's own 2022 critique
of "the Blender Look" (over-dark, over-detailed) argues the *taste* matters more than
the path tracer [4]; the differentiating physics is soft cast shadows plus occlusion
fill [1][2], and both already ship.

## What Blender would still add — and the native answer

| Blender effect | Worth it? | Native path (seeded numpy, extends `relief.py`'s pass registry) |
|---|---|---|
| True bounced light (GI) between slopes | Marginal on a poster | Widen the existing AO term's fill; a bounce approximation from the already-computed cast/ao masks |
| Multi-directional illumination softness | Yes, cheap | MDOW blend (Mark 1992, the `gdaldem -multidirectional` formula) as one more pass [11] |
| Atmospheric depth (elevation-graded haze) | Yes, cheap | Height-keyed tint ramp at composite time — pure Pillow/numpy |
| True perspective obliques (camera off nadir) | Someday | Out of scope; plan-oblique (`oblique` knob) already covers the poster idiom |
| Photoreal displacement micro-detail | No — Huffman's cliché warning [4] | Decline deliberately |

Also weighed and declined: **rvt-py** (the reference SVF/openness implementation) is
`requires_python <3.12` with a GDAL dependency — port its algorithms if ever needed
(Apache-2.0 permits it), never depend on the package [5]; **BlenderGIS** is an
interactive GUI add-on, not a headless library [3].

## If a Blender tier ever ships ("hero plate")

A concierge-press option, not an app feature: a subprocess export script
(`blender --background --python`) against a pinned minimum Blender version the
operator installs (the `.venv-prep` "shows the setup command" pattern), stills only,
sold as its own edition with `engine_version` provenance doing exactly the job the
forever-contract retirement designed it for — recording which build painted it,
promising nothing across builds. GPL/AGPL compatibility is clean in both directions
(GPLv3 §13 permits the combination; outputs are unencumbered) [12][13]. Nothing about
this needs deciding now.

## Sources

1. Huffman, *Creating Shaded Relief in Blender* — somethingaboutmaps.wordpress.com/2017/11/16/creating-shaded-relief-in-blender/
2. Huffman, *Shaded Relief in Blender*, ICA Mountain Cartography — mountaincartography.icaci.org/activities/workshops/banff_canada/papers/huffman.pdf
3. BlenderGIS — github.com/domlysz/BlenderGIS
4. Huffman, *Towards Less Blender-y Relief* — somethingaboutmaps.wordpress.com/2022/01/13/towards-less-blender-y-relief/
5. rvt-py 2.2.3 metadata (`requires_python >=3.6,<3.12`) — pypi.org/project/rvt-py/ · algorithms at github.com/EarthObservation/RVT_py (Apache-2.0)
6. bpy 5.2.0 metadata (`requires_python ==3.13.*`; wheel sizes 210–401 MB; LTS-window deletion) — pypi.org/project/bpy/ · archived wheels at download.blender.org/pypi/
7. Blender release archive (blender-5.2.0-macos-arm64.dmg = 346,163,615 B, verified) — download.blender.org/release/
8. Cycles performance (tiled high-res stills, Persistent Data) and GPU rendering (Metal on Apple Silicon, macOS 13+ full features) — docs.blender.org/manual/en/latest/render/cycles/render_settings/performance.html · …/gpu_rendering.html
9. Blender render-test handbook (reference images + per-platform thresholds; CPU/GPU result differences) — developer.blender.org/docs/handbook/testing/render/
10. Open Image Denoise docs (cross-device numerical differences) — openimagedenoise.org/documentation.html
11. `gdaldem -multidirectional` (Mark 1992, USGS OFR 92-422) — gdal.org/en/stable/programs/gdaldem.html · pubs.usgs.gov/of/1992/of92-422/of92-422.pdf
12. Blender license & FAQ (GPL binaries; outputs "your sole property"; free to sell your work) — blender.org/about/license/
13. GPLv3 §13 (AGPL combination permission) — opensource.org/license/gpl-3-0
