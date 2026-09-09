# Metal as a render path: viability assessment (2026-09-02)

Question asked: should Tecopa Plateworks move relief or graphics generation onto Metal,
Apple's GPU framework — and if so, for which operations, by which Python route, and at
what cost to determinism, CI parity, and maintenance? Researched against primary sources
(the Metal Shading Language specification, Apple developer documentation, library docs
and source, PyPI metadata, the tools' own sites) on 2026-09-02, and measured on this
Mac. Every load-bearing claim is cited at the end. Anything no primary source settles is
marked UNVERIFIED. The Blender assessment [B] is the precedent for this document. It
settled the path-tracer question and is not re-derived here.

Host measured: Apple M5 (10 cores, 32 GB, Metal 4), macOS 27.0 (26A5406e), the repo
`.venv` at Python 3.14.2 with numpy 2.4.6 on Accelerate, scipy 1.17.1, Pillow 12.3.0.
CI is `ubuntu-latest` with no GPU, and it installs the Python named in
`.python-version`, which is **3.11**, not 3.14 (`.github/workflows/ci.yml`,
`.python-version`). That mismatch predates this question and is recorded here, not
fixed.

## Verdict

**Not now.** Metal does not earn a place in the engine today, for three hard reasons and
one strategic one. When a GPU path ever ships, it ships as a second *performance* of the
score — confined to previews and share twins — and never as the engine that paints the
archival file.

1. **Determinism (invariant 3) cannot be promised on Metal in the form the engine
   relies on.** Apple's shading-language compiler defaults to fast math [1]. The
   specification bounds each operation's *accuracy* in ULPs and grants permissions —
   rounding mode, flush-to-zero, contraction — but promises stability nowhere [1]. Even
   `safe` math mode "sets the FP contract to on", so fused multiply-add still varies by
   compiler [1][2]. Apple's own guidance: "CPUs are IEEE accurate, whereas GPUs are
   implementation specific" [9]. MLX compiles its kernels with `-fno-fast-math` and
   defaults custom kernels to `safe`, and still carries an open report of the same key
   producing different bytes on different Apple GPU families [14]. The only honest GPU
   contract is "same host + same build", proven empirically per machine. The engine's
   contract is "same spec + seed + build" (`CLAUDE.md` § Invariants, [R1]), and CI proves
   it on a machine with no GPU at all.
2. **The gain is bounded, and Amdahl bounds it low.** Measured on the real `lassen_ca`
   plate: an 18×24 final at 300 dpi takes 17.2 s. `shaded_relief` is 8.7 s of it (50%).
   The GPU-shaped kernels inside — blurs, rotate, zoom, distance transform, trig — sum
   to ~10 s of thread time but only ~6 s of wall, because the relief fan-out already
   overlaps them [R2]. Pillow ink, rasterio reads, label placement, and PNG encode stay
   on the CPU whatever happens: ~8 s of the 17. A complete MLX port of the relief chain
   therefore lands near 9 s, not near 2 s. The 96-dpi draft goes from 2.15 s to perhaps
   1.2 s, and the base cache already makes most knob drags 0.9 s [R3].
3. **CI parity.** Any Metal path is a second implementation of the ~800-line relief chain
   that CI cannot execute. The repo already pays for one cross-host rendering difference
   — seven tests red on this Mac because Georgia is installed here and DejaVu on CI
   (`CLAUDE.md` § Known local failures). A GPU relief is that problem on every pixel of
   every sheet, and its thresholds would be tuned against a machine CI never sees.

Strategic: **the cheap speed is on the CPU, inside code that already exists.**
`_biome_layers` is 26% of the final, and half of that is a fifteen-iteration boolean-mask
loop (`app/render.py:312-315`) that a 256-entry lookup table replaces. Its four edge
blurs run at full resolution while the relief blurs already decimate through the rev-2
pyramid (`app/relief.py:340-376`). The cast-shadow ray-march already runs on a 96-spi
ground grid whatever the render dpi (`app/render.py:248-257`), so at 300 dpi the pass a
GPU would help most is already ten times cheaper than the sheet. Spend that headroom
first. It costs no second implementation and moves no archival pixel. When macOS-only
acceleration is ever worth a second implementation, vImage's separable convolution is
the candidate with no GPU in it (see § The Apple-native image pipeline): probed at
0.020 s for a 9+9 pass over the full 16096×11027 DEM, bit-identical across runs [32].
It pays the CI-parity cost, not the Metal-determinism one.

## What the engine computes — measured

One 18×24 sheet of `lassen_ca` (real 3DEP terrain, 6200×7719 at 10 m), six journeys,
biome tint, labels, `soft_light` 0.35, `shadow_strength` 0.5, four relief workers.
Wall seconds from `cProfile` around `render.rasterize`, then a separate PNG encode.

| tier | pixels | render | `shaded_relief` | `_biome_layers` | route ink | `_read_window` | labels + overlays | PNG encode |
|---|---|---|---|---|---|---|---|---|
| draft, 96 dpi | 1728×2304 | 2.15 | 1.26 | 0.33 | 0.16 | 0.19 | 0.18 | 0.15 |
| refine, 200 dpi | 3600×4800 | 7.73 | 3.90 | 1.80 | 0.80 | 0.83 | 0.33 | 0.80 |
| refine, 200 dpi, High relief 0.4 | 3600×4800 | 8.82 | 3.44 | 2.03 | 1.32 | 0.66 | 0.37 + warp 0.90 | 0.80 |
| final, 300 dpi | 5400×7200 | 17.2 | 8.67 | 4.50 | 2.19 | 0.92 | 0.63 | 1.81 |

Inside `shaded_relief` at 300 dpi, cumulative seconds with worker threads included:
the fan-out is 2.32 wall, and its critical path is `_shadow_terms` at 2.31 (two
`rotate` calls 0.74, `sky_occlusion` 0.25, the penumbra blur). Then `base_colour` 1.64
(three `np.interp`), `_soft_light` 1.56, `_fill_nan` 1.27 (the distance transform on
this plate's nodata corners), seven `shade_from` calls 1.23 (sin/cos), `_tonal_finish`
0.75, `grain` 0.32. Across every caller, the C kernels total: `correlate1d` 3.53 (14
`gaussian_filter` calls), `euclidean_feature_transform` 1.05, `zoom_shift` 1.01,
`geometric_transform` 0.74.

What in this is GPU-shaped: separable blurs (a convolution), affine rotate and zoom (a
gather), elementwise trig and composites, and the running-max column sweep in
`cast_shadow_mask` (a scan, `app/relief.py:439-441`). What is not: Pillow's line
rasteriser in `_coverage` (`app/render.py:792-806`), text in `_draw_labels`, rasterio
window reads, PNG deflate, `np.percentile` in `valley_pass`, and the paper grain. The
grain draws from `np.random.default_rng(seed)` (`app/relief.py:614-623`). A GPU
generator seeded the same way produces different noise, so grain stays on the CPU under
any port or the seed contract changes.

Memory is the other axis. The 300-dpi window is ~8064×6048 float32, 195 MB per plane and
~585 MB for RGB. A 24×36 sheet at 300 dpi is 7200×10800 — padded, ~97 MP, 390 MB per
plane, ~1.2 GB for RGB. Apple silicon shares memory between CPU and GPU, but a numpy
array is not an MLX array. The numpy↔MLX conversion cost at these sizes was not measured
(UNVERIFIED). On the raw Metal path it was: a 7200×10800 float32 plane uploads through
`replaceRegion` in 0.035 s and reads back through `getBytes` in 0.115 s, and
`MTLBuffer.contents().as_buffer()` gives a zero-copy numpy view [32]. Metal's 2-D
texture limit is 16,384 px before the Apple10 family and 32,768 on it, and 32-bit float
*filtering* is guaranteed only from Apple9 — check `supports32BitFloatFiltering` [1b].
On this M5 it is true, and both a 7200×10800 and a 16096×11027 `r32Float` texture
allocate [32]. The M5's `MTLDevice.maxBufferLength` was not queried (UNVERIFIED) [1b].

## Routes from Python 3.14 to Metal

PyPI metadata was read through the JSON API on 2026-09-02 [15]. "Wheel" means a
`macosx` arm64 or universal2 wheel for CPython 3.14.

| Route | Latest (date) | Py 3.14 wheel | License | Maintained | What maps to the relief passes |
|---|---|---|---|---|---|
| **MLX** (`mlx` + `mlx-metal`) [14] | 0.32.2 (2026-08-25) | yes, cp314 and cp314t, macOS ≥ 14 | MIT | yes, commit 2026-09-02 | `conv2d`, `fft2`/`rfft2`, `sum`/`max`/`cumsum`, `where`/`clip`/`pad`/`arctan2`, `nn.Upsample` (nearest, linear, cubic). **No** gaussian primitive, `rotate`, `zoom`, `gradient`, `hypot`, `percentile`, or distance transform. Custom MSL via `mx.fast.metal_kernel` (Metal-only). `float64` is CPU-only. Linux CPU build via `mlx[cpu]`. |
| **PyObjC** (`Metal`, `MetalPerformanceShaders`, `MetalPerformanceShadersGraph`, `Quartz`) [16] | 12.2.2 (2026-08-11) | yes, cp314 and cp314t universal2 | MIT | yes, commit 2026-08-15 | Everything Apple ships, hand-marshalled: MPS blur, convolution, EDT, Lanczos/bilinear scale, Sobel. Raw MSL compute via `MTL*`. Core Image and Core Graphics through `Quartz`. macOS only by nature. |
| **PyTorch MPS** [19] | 2.14.0 (2026-09-02) | yes, cp314 and cp314t, macOS ≥ 14 | BSD-style | yes | `conv2d`, `F.interpolate`, `grid_sample`, `torch.fft`, `cumsum`, `torch.mps.compile_shader`. No distance transform. No `float64` on MPS. MPS absent from the deterministic-ops list. Same tensor code on `device="cpu"` in CI. |
| **wgpu-py** [17] | 0.32.0 (2026-07-19) | yes, ABI-agnostic `py3` wheel, CI tests 3.14 | BSD-2 (wgpu-native Apache-2.0) | yes, commit 2026-08-26 | Nothing built in. WGSL compute over buffer-protocol arrays. Metal selected automatically, `WGPU_BACKEND_TYPE` overrides. Linux CI would need a software Vulkan device (UNVERIFIED whether wgpu-py's CI uses one). |
| **metalcompute** [15] | 0.2.9 (2025-01-21) | **no** (cp39–cp313 only, sdist untested on 3.14) | MIT | dormant, "preview" | Nothing built in. Raw MSL kernels on buffer-protocol arrays. |
| **Taichi** [18] | 1.7.4 (2025-07-31) | **no** (cp310–cp313) | Apache-2.0 | slowed, last commit 2025-07-30 | Nothing built in. Python-syntax kernels on `ti.metal` or `ti.cpu`. No `f64` on Metal. Docs still list Python 3.7–3.10. |
| **jax-metal** [20] | 0.1.1 (2024-10-08) | `py3` wheel, but fails to load against current JAX | proprietary Apple, closed source | **no** — JAX maintainers: no plan for further releases | Moot. Not AGPL-compatible for redistribution. |
| **MoltenVK** + `vulkan` [21] | MoltenVK 1.4.2 (2026-07-24), `vulkan` 1.3.275.1 (2024-02-27) | `vulkan` is pure Python, 3.14 UNVERIFIED | Apache-2.0 | MoltenVK yes, `vulkan` dormant | Raw Vulkan API only. SPIR-V toolchain external. On macOS, wgpu-py's native Metal backend makes this unnecessary. |
| **numpy / scipy** (the baseline) [22] | 2.4.6 / 1.17.1 pinned | yes, Accelerate wheels for macOS ≥ 14 | BSD-3 | yes | The reference. Accelerate serves BLAS/LAPACK only. `scipy.ndimage` kernels (`gaussian_filter`, `distance_transform_edt`, `rotate`, `zoom`) are scipy's own C and do not touch it. |

Three findings cut across the table. **No candidate publishes a bit-determinism
guarantee for GPU execution.** **Only MLX array ops and PyTorch tensor ops run the same
source on Metal here and on a CPU in CI** — and MLX's `metal_kernel`, the route to a
ray-march, has no CPU counterpart [14]. **Everything usable is MIT, BSD, or Apache-2.0**,
and Apple's frameworks fall under the GPL system-library carve-out [25]. `jax-metal` is
the one proprietary binary, and it is dead.

## The Apple-native image pipeline

Everything below is reachable from Python through PyObjC's `Quartz`,
`MetalPerformanceShaders`, `MetalPerformanceShadersGraph`, and `CoreText` packages [16].
What Apple documents, and what it means for this engine:

- **MPS image filters** [3][4][6]. `MPSImageGaussianBlur` is, in Apple's words, "an
  approximate Gaussian" intended for "~10 bits of precision or less". Apple's own advice
  for an analytically clean blur is `MPSImageConvolution` — whose kernel "can be either
  3, 5, 7 or 9" wide. The engine's blurs reach hundreds of pixels (`app/relief.py:340-
  345`), so neither MPS blur can reproduce `scipy.ndimage.gaussian_filter`.
  `MPSImageEuclideanDistanceTransform`, `MPSImageLanczosScale`, `MPSImageBilinearScale`,
  and `MPSImageSobel` exist. `MPSKernelOptions.allowReducedPrecision` is off by default,
  and when on "the precision of the result may vary by hardware and OS" [5].
- **MPSGraph** [7]. `convolution2D` (macOS 11+) and `fastFourierTransform` (macOS 14+)
  exist, so a wide blur is expressible as an FFT convolution. No accuracy statement.
- **Core Image** [8]. The Core Image Kernel Language path (`CIKernel(source:)`) is
  deprecated since macOS 10.14. Kernels are Metal now: `kernels(withMetalString:)` on
  macOS 12+, or a precompiled metallib. The working format defaults to `RGBAh` (16-bit
  float). `RGBAf` (32-bit float) is "only available on macOS". `useSoftwareRenderer`
  "has no effect if the platform does not support OpenCL", so there is no documented
  CPU fallback on current macOS. `inputImageMaximumSize()` and
  `outputImageMaximumSize()` report hardware limits per context; the M5 GPU context
  reports 32,768×32,768 for both [32]. Tiling is documented on
  `CIKernel.apply(extent:roiCallback:arguments:)`: "Core Image automatically splits
  large images into smaller tiles for rendering, so your callback may be called
  multiple times" [33]. `CIImage(bitmapData:…colorSpace:)` accepts `nil` for images
  "that don't contain color data (such as elevation maps)", so float terrain enters
  without a colour match [33].
- **Core Graphics** [10]. PDF contexts (`CGContext(consumer:mediaBox:_:)`), ICC colour
  spaces from data (`CGColorSpace(iccData:)`), `genericCMYK`, and 16-bit-per-channel
  bitmap contexts. `CGBitmapInfo.floatComponents` is deprecated as of OS 27.0.
- **ImageIO** [11]. `CGImageDestination` writes PNG and TIFF with `kCGImagePropertyDepth`,
  `kCGImagePropertyProfileName`, and DPI keys. Pillow already writes the sRGB profile
  and the manifest chunk (`app/main.py:128-148`, `app/provenance.py:232`), so ImageIO
  adds nothing the archive needs.
- **ColorSync** [12] is the engine under Core Graphics and Core Image. Direct use is
  for "a professional photo, print, or video app that builds custom transforms". The
  engine's print path embeds sRGB and hands soft-proofing to the lab.
- **vImage** (Accelerate) [13]. `vImageConvolve_PlanarF`, `vImageSepConvolve_PlanarF`
  (macOS 11+, separate 1-D kernels), `vImageScale_PlanarF` (Lanczos-3, or Lanczos-5
  with `kvImageHighQualityResampling`), and `vImageRotate_PlanarF` are CPU, vectorised,
  multithreaded, and float32-planar — the shape of the relief passes exactly. PyObjC
  will not wrap Accelerate by policy [16], but `ctypes.util.find_library("Accelerate")`
  resolves the framework and the calls work [32]. Probed on this Mac: a 9+9 separable
  pass over the full 16096×11027 `elko_bonneville` DEM in 0.020 s, within 1.2e-4 of a
  float64 reference, bit-identical across runs; the 2-D 9×9 took 0.137 s [32]. Cost
  scales with kernel length, and the documentation states no width limit for the
  separable variant (UNVERIFIED that the engine's widest sigmas fit without the
  pyramid). The box and tent fast paths are 8-bit only; float uses the separable call
  [13]. It is still a second implementation CI cannot run — but with no GPU in it, the
  reproducibility question is numpy's, not Metal's.

## Determinism on the GPU — what the primary sources say

- **MSL specification 4.1** [1]. `-fmetal-math-mode`: "The default is fast."
  `-fmetal-math-fp32-functions`: "The default is fast." Fast mode drops NaN, INF, and
  signed-zero handling and allows reciprocal, reassociation, and fast contraction. `safe`
  "sets the FP contract to on", so only `-ffp-contract=off` removes FMA variance. §8:
  "Metal is compliant to a subset of the IEEE 754 standard." §8.2: either
  round-to-nearest-even or round-toward-zero "may be supported". Denormals "may be
  flushed to zero". Table 8.2 (fast math, the default) bounds `sin`/`cos` only by absolute
  error on [−π, π], `exp` at 3 + ⌊2|x|⌋ ULP, division at 2.5 ULP. The document contains
  no statement about identical results across GPU families or OS versions.
- **`MTLCompileOptions`** [2]. `mathMode` replaces the deprecated `fastMathEnabled`,
  whose default is `true`. `.safe` prevents "any transformations that could affect the
  results" — read with the spec's contraction note above.
- **MPS** [3][5]: the blur is approximate by design. Reduced precision "may vary by
  hardware and OS". No reproducibility statement on the framework page.
- **MLX** [14]. Random uses a splittable Threefry counter-based PRNG. Custom kernels
  default to `math_mode="safe"`. The built-in metallib compiles with `-fno-fast-math`.
  Indexed writes: "updates to the same location are nondeterministic". A maintainer
  closed CPU-versus-GPU float divergence as expected behaviour (#1341). Float32 matmul
  runs in TF32 on M5-class hardware unless `MLX_ENABLE_TF32=0` (#3702). Issue #3568,
  open: the same key yields different bytes on M1 Max versus M3/M5 — reporter data,
  no maintainer reply (UNVERIFIED as evidence, but exactly the divergence the spec
  permits).
- **PyTorch** [19]: "Completely reproducible results are not guaranteed across PyTorch
  releases, individual commits, or different platforms", and results "may not be
  reproducible between CPU and GPU executions, even when using identical seeds". The
  deterministic-algorithms page lists CUDA and CPU cases and mentions MPS nowhere.
- **WGSL** [23] (what wgpu-py compiles to Metal): "An implementation may reassociate
  operations", may fuse them, may flush to zero, and gives the same accuracy table shape
  as Metal's fast-math table.
- **IEEE 754-2019** [24], clause 11: reproducible results "require cooperation from
  language standards, language processors, and users". None of the GPU stacks above
  claims that cooperation.
- **The CPU baseline is not a fixed point either** [22]. numpy selects SIMD kernels per
  CPU at import, its policy is loops "identical to within a small number (1-3?) ULPs",
  and 2.0.0 changed unstable-sort results through SIMD. `np.sum` uses pairwise
  summation only along the fast axis. This is why the repo's promise is per build, and
  why the fan-out test pins call order rather than trusting the hardware
  (`tests/test_relief.py:210-225`).
- **Core Image** [9]: the retired QA1416 is the only Apple text found that names the
  difference: "Get reproducible accuracy. CPUs are IEEE accurate, whereas GPUs are
  implementation specific." The current Programming Guide says only that Core Image
  "determines whether the calculations are performed using the GPU or the CPU" [8b].
- **Observed, not promised** [32]. On this M5, `MPSImageGaussianBlur` (σ=3),
  `MPSImageConvolution` 9×9, `MPSImageLanczosScale`, and a Core Image GPU render were
  each bit-identical across repeated runs, and a `useSoftwareRenderer=true` context
  returned the same bytes as the GPU context — consistent with the OpenCL note above,
  not evidence of a CPU path. The blur's error against a float64 reference was 0.1% of
  range, which is the "~10 bits" the documentation claims [3]. This supports (a) below
  and says nothing about (b).

What can be promised, then. **(a) Same host, same build, run to run:** plausible for
kernels with a fixed reduction order, no atomics, `mathMode = .safe`,
`mathFloatingPointFunctions = .precise`, and `-ffp-contract=off` — but proven per
machine, and re-proven per OS update. **(b) CPU-versus-GPU identity:** contradicted by
Apple, PyTorch, and the spec's permissions. A Metal path is a second build in
`engine_version`'s sense, and its golden images belong to one machine.

## What the field does

- **Eduard** [26] — Jenny et al.'s macOS relief app — is the one print-oriented relief
  tool found that shades on the GPU. It does so through **Core ML**, not a named Metal
  path: the 2021 paper "used the hardware-accelerated Apple Core ML framework" on a
  Radeon Pro 5300M, rendering a 5,000×5,000 grid in six seconds from 256-pixel input
  tiles cut to 156-pixel output tiles with 20 pixels of alpha blending at the seams. The
  2024 ambient-occlusion paper reports the AO pass at "less than one second" for the same
  grid on an M1, with the API unnamed. The app exports "one shaded pixel for each
  elevation value" as GeoTIFF, JPEG, or PNG, and Eduard Cloud caps at 10,000×10,000.
  Neither paper nor the user guide says anything about CPU-versus-GPU output or
  reproducibility. Which compute units the shipping app selects: UNVERIFIED.
- **Affinity Photo 2** [27]. "Affinity Photo 2 can use Apple's Metal technology … to
  talk directly to your system's graphics hardware." The accelerated work is
  "raster-based tasks", while "vector operations and specific features like blend
  ranges are performed on the CPU." The toggle, "Enable Metal compute acceleration", is on by
  default, and the help says to disable it "if you experience poorer performance than
  expected." Documents go to 16- and 32-bit RGB, ICC profiles, and PDF/X CMYK. No
  statement on CPU-versus-GPU output.
- **Pixelmator Pro** [28]. "Both apps fully leverage your Mac's graphics processor using
  Metal and Core Image technologies", and Core ML is listed beside them. Colour depth
  is 8 or 16 bits per channel, with 16 recommended "for print workflows". No statement
  on output differences, and no documented maximum image size (UNVERIFIED).
- **Blender** [29]. Metal for Cycles and EEVEE on Apple silicon, macOS 13+, and since
  4.0 the only macOS backend. Render tests pass against reference images with
  per-platform thresholds, "Result may sometimes be different between CPU and GPU, or
  between different GPUs", and "Tests that are non-deterministic should be added to the
  blocklist" — the finding the Blender assessment recorded [B].
- **MapLibre Native and Mapbox** [30]. Metal shipped in iOS v6.0.0 (January 2024)
  because Apple deprecated OpenGL ES, for "GPU accelerated real-time rendering" of
  tiles. Its `hillshade` layer is "client-side hillshading … based on DEM data",
  computed per fragment in a Metal shader (`standard_hillshade`,
  `multidirectional_hillshade`) — a display effect at screen resolution, not a print
  path. Its render tests keep per-platform expectation images. Mapbox's v10 SDK claims
  "1:1 accurate rendering results" between its OpenGL and Metal compilers — a vendor
  claim about its own two backends, not about CPU parity.
- **QGIS, GDAL, and ArcGIS Pro** [31]. QGIS 2D rendering is CPU, with an opt-in
  **OpenCL** path for the hillshade renderer and the slope/aspect/hillshade algorithms
  that falls back to the CPU and disables itself on a kernel error. Its tracker carries
  OpenCL-versus-CPU correctness bugs — "Hillshade Layer Style wrong if OpenCL
  acceleration is enabled", and a raster-calculator aspect-ratio fault. `gdaldem
  hillshade` (Horn, Zevenbergen–Thorne, `-multidirectional`, `-igor`) mentions no GPU.
  ArcGIS Pro lists Aspect and Slope among its CUDA-accelerated tools and Hillshade is
  absent from that list. rvt-py, WhiteboxTools, rayshader, and Natural Scene Designer
  are CPU by their own docs.

The pattern is the finding. **No primary source shows an offline, print-resolution
relief tool computing its relief with Metal compute.** The GPU relief that exists runs
through Core ML (Eduard, tiled at 256 px with blended seams), through OpenCL as an
opt-in with a CPU fallback and a bug history (QGIS), or as a real-time fragment shader
(MapLibre, Mapbox). Every tool that documents a GPU path either tolerates platform
differences in its tests (Blender, MapLibre) or ships a switch to turn the GPU off
(Affinity, QGIS). None documents byte-identical CPU and GPU output.

## Where Metal would pay off — Amdahl, honestly

- **The draft (96 dpi, synchronous).** 2.15 s, of which relief is 1.26 s. A perfect GPU
  relief leaves ~0.9 s of Pillow, rasterio, and labels. Best case ~1.2 s. The base cache
  already turns a non-terrain knob drag into 0.9 s [R3]. Gain: a few hundred
  milliseconds on the terrain knobs only.
- **The refine (200 dpi, queued).** 7.7 s, relief 3.9 s, biome 1.8 s. Best case ~3.5 s.
  The LUT fix to `_biome_layers` alone gets ~1 s of that on the CPU.
- **The final (300 dpi).** 17.2 s plus 1.8 s PNG encode. Best case ~9 s plus the same
  encode. The final is the archival file. This is the one place a GPU path must never
  paint — see the verdict — so the largest absolute saving is the one the contract
  forbids.
- **The archival film.** The base paints once and each frame re-inks the route
  (`app/timelapse.py:10-13`), so the film is one relief plus N cheap Pillow passes. No
  relief per frame, no GPU gain.
- **The Journey Light film.** The sun moves, so the base repaints every frame
  (`app/timelapse.py:246-250`) — at the film's default 96 dpi (`app/main.py:106`),
  about 40 × 1.8 s ≈ 72 s. This is the one product path where relief dominates and
  where the output is a lossy share twin that carries no manifest by construction
  (`app/timelapse.py:20-23`). Best case ~30 s. It is also the only path where GPU
  drift touches nothing archival.
- **The asset farm and light sweep** (`scripts/render_asset_farm.py`,
  `scripts/render_lightsweep.py`) are operator batch jobs. They benefit, but they also
  feed `marketing/build_deploy.py`'s terrain guard, which compares hashes, not
  thresholds.

## If a Metal tier ever ships

Not an engine change. A second performance, with these properties fixed in advance:

- **Route: MLX array ops**, for `conv2d`-based blurs, `nn.Upsample` resampling, and the
  elementwise chain. It is the only route that is MIT, maintained, on Python 3.14, and
  able to run the same code on a Linux CPU. `mx.fast.metal_kernel` is out — it has no
  CPU counterpart, so the ray-march stays numpy. `distance_transform_edt`, `percentile`,
  and the grain stay numpy. `float64` never enters (MLX GPU is float32 only), which the
  engine already honours (`app/relief.py:327-333`).
- **Scope: previews and share twins only** — the draft, the refine, the Journey Light
  WebP/MP4. The archival final, `/api/reprint`, `/api/continue`, and the APNG film keep
  the numpy path. No GPU pixel ever enters a manifest, so `engine_version` needs no
  suffix.
- **Opt-in, default off**: `TECOPA_RELIEF_BACKEND=metal`, refused on any host without
  MLX. CI never sets it. The numpy path stays the reference and the only one tests
  compare bytes against.
- **Tests: tolerance, not identity.** The proof-versus-final MAD tests already accept
  sub-LSB drift across dpi. A GPU draft is held to the same thresholds against the numpy
  refine, on this Mac, with the failure set recorded the way the seven font tests are.
- **Cost, stated plainly.** Determinism: bit-identity per host and build only, proven by
  golden images that belong to one machine. CI parity: a second relief implementation
  that CI can run only on MLX's CPU backend, which is a third numerical path, not the
  reference. Maintenance: two copies of every relief change, and MLX's release cadence
  (four releases since April) against a lock that pins numpy to the byte.

**Revisit when** a product needs per-frame relief at refine dpi or above — a Journey
Light film at 200 dpi, a plate-scale batch — and the CPU headroom (the biome LUT, a
pyramid for the biome edge blur, `_fill_nan` on plates with interior nodata) is spent.
Or when Apple publishes a reproducibility contract for Metal compute, which today it
does not.

## Sources

Repo references (`file:line` against `main` at `a3d4ba9`):

- [R1] `CLAUDE.md` § Invariants, invariant 3, and § Versioned drift.
- [R2] `app/relief.py:17-30` (`RELIEF_WORKERS`, `_fan_out`), `:340-376` (the blur
  pyramid), `:423-448` (`cast_shadow_mask`), `:450-460` (`sky_occlusion`), `:614-623`
  (`grain`), `:713-714` (the fan-out call).
- [R3] `app/basecache.py:5-9` (terrain ≈ 90% of a render, 6.4 s → 0.9 s measured),
  `app/render.py:248-257` (`SHADOW_GRID_SPI`, `_shadow_res_m`), `:290-323`
  (`_biome_layers`), `:619-678` (`_oblique_warp`), `:771-809` (`_coverage`),
  `:942-999` (`_ink_layer`), `:2598-2705` (`_paint_terrain`), `:3051-3103`
  (`_base_layer`).
- `app/main.py:34-53` (proof and refine dpi), `:106` (film dpi), `:128-148` (final
  encode). `app/timelapse.py:10-23`, `:246-250`, `:443-445`. `app/provenance.py:47-65`
  (`ENGINE_VERSION`). `tests/test_relief.py:210-225`. `tests/test_provenance.py:311`.
  `.github/workflows/ci.yml`, `.python-version`, `requirements-lock.txt`.
- [B] `docs/superpowers/assessments/2026-08-10-blender-render-viability.md`.
- Measurement script and raw profile: this session's scratchpad, not committed. Rerun
  is one `cProfile` around `render.rasterize` on the spec described above.

Primary sources:

1. Metal Shading Language Specification, Version 4.1 (2026-06-04), §1.6.3 Math
   Intrinsics Compiler Options, §8 Numerical Compliance, Tables 8.1–8.2 —
   developer.apple.com/metal/Metal-Shading-Language-Specification.pdf
   · [1b] Metal Feature Set Tables (PDF, 2026-05-21: texture limits by family, 32-bit
   float filtering by family, `maxBufferLength`) —
   developer.apple.com/metal/Metal-Feature-Set-Tables.pdf ·
   `MTLDevice.supports32BitFloatFiltering` —
   developer.apple.com/documentation/metal/mtldevice/supports32bitfloatfiltering
2. `MTLCompileOptions.mathMode`, `.fastMathEnabled` (default `true`, deprecated
   macOS 15), `MTLMathMode` — developer.apple.com/documentation/metal/mtlcompileoptions/mathmode
   · …/mtlcompileoptions/fastmathenabled · …/mtlmathmode
3. `MPSImageGaussianBlur` ("an approximate Gaussian", "~10 bits of precision or less")
   — developer.apple.com/documentation/metalperformanceshaders/mpsimagegaussianblur
4. `MPSImageConvolution` (width and height "3, 5, 7 or 9") —
   developer.apple.com/documentation/metalperformanceshaders/mpsimageconvolution
5. `MPSKernelOptions.allowReducedPrecision` ("may vary by hardware and OS") —
   developer.apple.com/documentation/metalperformanceshaders/mpskerneloptions/allowreducedprecision
6. MPS image filters catalogue, `MPSImageEuclideanDistanceTransform`,
   `MPSImageLanczosScale`, `MPSImageBilinearScale`, `MPSImageSobel` —
   developer.apple.com/documentation/metalperformanceshaders/image-filters
7. `MPSGraph.convolution2D(_:weights:descriptor:name:)` (macOS 11+),
   `fastFourierTransform(_:axesTensor:descriptor:name:)` (macOS 14+) —
   developer.apple.com/documentation/metalperformanceshadersgraph/mpsgraph
8. Core Image: `CIContext`, `CIContextOption.workingFormat` (default `RGBAh`, `RGBAf`
   macOS only), `.useSoftwareRenderer` ("no effect if the platform does not support
   OpenCL"), `CIKernel.init(source:)` (deprecated macOS 10.14),
   `CIKernel.kernels(withMetalString:)` (macOS 12+), `CIRenderDestination`,
   `inputImageMaximumSize()` — developer.apple.com/documentation/coreimage/…
   · [8b] Core Image Programming Guide, "What You Need to Know Before Writing a Custom
   Filter" — developer.apple.com/library/archive/documentation/GraphicsImaging/Conceptual/CoreImaging/ci_advanced_concepts/ci.advanced_concepts.html
9. Apple Technical Q&A QA1416 ("CPUs are IEEE accurate, whereas GPUs are implementation
   specific", marked retired) — developer.apple.com/library/archive/qa/qa1416/_index.html
10. Core Graphics: `CGContext.init(consumer:mediaBox:_:)`, `CGColorSpace.init(iccData:)`,
    `CGColorSpace.genericCMYK`, `CGBitmapInfo.floatComponents` (deprecated 27.0) —
    developer.apple.com/documentation/coregraphics/…
11. ImageIO: `CGImageDestination`, `kCGImagePropertyDepth`, `kCGImagePropertyProfileName`,
    `kCGImagePropertyDPIWidth` — developer.apple.com/documentation/imageio/…
12. ColorSync framework overview — developer.apple.com/documentation/colorsync
13. vImage: `vImageConvolve_PlanarF`, `vImageSepConvolve_PlanarF`, `vImageScale_PlanarF`,
    `kvImageHighQualityResampling`, `vImageRotate_PlanarF`, and the Convolution topic
    (box and tent listed for `Planar8`/`ARGB8888` only) —
    developer.apple.com/documentation/accelerate/vimage ·
    …/accelerate/vimagesepconvolve_planarf(_:_:_:_:_:_:_:_:_:_:_:_:) ·
    …/accelerate/convolution · …/accelerate/kvimagehighqualityresampling
14. MLX: install (macOS ≥ 14, Python ≥ 3.10, `mlx[cpu]` on Linux glibc ≥ 2.35) —
    ml-explore.github.io/mlx/build/html/install.html · ops — …/python/ops.html · fft —
    …/python/fft.html · random (Threefry) — …/python/random.html · `metal_kernel`
    (`math_mode` default `safe`) — …/python/_autosummary/mlx.core.fast.metal_kernel.html
    · data types (`float64` CPU-only) — …/python/data_types.html · indexing
    ("nondeterministic") — github.com/ml-explore/mlx/blob/main/docs/src/usage/indexing.rst
    · `-fno-fast-math` — github.com/ml-explore/mlx/blob/main/mlx/backend/metal/kernels/CMakeLists.txt
    · issues #1341, #3568, #3702 — github.com/ml-explore/mlx/issues/{1341,3568,3702}
    · license MIT, commit 2026-09-02 — github.com/ml-explore/mlx
15. PyPI JSON API, read 2026-09-02 — pypi.org/pypi/{mlx,pyobjc-core,pyobjc-framework-Metal,pyobjc-framework-MetalPerformanceShaders,pyobjc-framework-MetalPerformanceShadersGraph,pyobjc-framework-Quartz,metalcompute,wgpu,taichi,torch,jax-metal,vulkan,numpy,scipy}/json
16. PyObjC changelog (Python 3.14 fixes from 11.x, macOS 26.5 SDK in 12.2), API notes
    for Metal, MetalPerformanceShaders, Quartz, license —
    pyobjc.readthedocs.io/en/latest/changelog.html · …/apinotes/Metal.html ·
    …/apinotes/MetalPerformanceShaders.html · …/apinotes/Quartz.html ·
    github.com/ronaldoussoren/pyobjc/blob/main/pyobjc-core/License.txt · "Accelerate —
    Will not be wrapped" — pyobjc.readthedocs.io/en/latest/notes/framework-wrappers.html
17. wgpu-py: Python ≥ 3.11, bundled wgpu-native, `WGPU_BACKEND_TYPE` —
    wgpu-py.readthedocs.io/en/stable/start.html · `compute_with_buffers` —
    …/utils.html · CI matrix incl. 3.14 — github.com/pygfx/wgpu-py/blob/main/.github/workflows/ci.yml
    · Vulkan on macOS needs MoltenVK — github.com/gfx-rs/wgpu/blob/trunk/README.md
18. Taichi: README (backends, Apache-2.0) — github.com/taichi-dev/taichi · maintainers on
    pace (2024) — github.com/taichi-dev/taichi/discussions/8506 · Metal type limits —
    docs.taichi-lang.org/docs/type
19. PyTorch: reproducibility notes — docs.pytorch.org/docs/stable/notes/randomness.html
    · `torch.use_deterministic_algorithms` —
    docs.pytorch.org/docs/stable/generated/torch.use_deterministic_algorithms.html · MPS
    notes — docs.pytorch.org/docs/stable/notes/mps.html · fallback —
    github.com/pytorch/pytorch/blob/main/aten/src/ATen/mps/MPSFallback.mm · no float64 —
    github.com/pytorch/pytorch/blob/main/aten/src/ATen/native/mps/OperationUtils.mm ·
    op coverage issue — github.com/pytorch/pytorch/issues/77764
20. jax-metal: Apple's page ("experimental") — developer.apple.com/metal/jax/ · JAX
    maintainer on status — github.com/jax-ml/jax/issues/34109 · JAX install page —
    docs.jax.dev/en/latest/installation.html
21. MoltenVK (Vulkan 1.4 on Metal, Apache-2.0) — github.com/KhronosGroup/MoltenVK ·
    `vulkan` binding — github.com/realitix/vulkan
22. numpy 2.0.0 notes (Accelerate wheels on macOS ≥ 14, SIMD sort differences) —
    numpy.org/doc/stable/release/2.0.0-notes.html · 1.17.0 notes (runtime AVX dispatch,
    exp 2.52 ulp) — numpy.org/doc/stable/release/1.17.0-notes.html · NEP 38 (1–3 ULP
    policy) — numpy.org/neps/nep-0038-SIMD-optimizations.html · `numpy.sum` (pairwise) —
    numpy.org/doc/stable/reference/generated/numpy.sum.html · scipy 1.14.0 (Accelerate)
    — github.com/scipy/scipy/releases/tag/v1.14.0 · `gaussian_filter` —
    docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.gaussian_filter.html
23. WGSL specification §15.7 Floating Point Evaluation — w3.org/TR/WGSL/
24. IEEE 754-2019, clause 11 Reproducible floating-point results —
    standards.ieee.org/ieee/754/6210/ (clause text verified against a university mirror,
    not an IEEE-served PDF) · committee background —
    grouper.ieee.org/groups/msc/ANSI_IEEE-Std-754-2019/background/ieee-computer.pdf
25. GNU GPL FAQ, system-library exception — gnu.org/licenses/gpl-faq.html#SystemLibraryException
26. Eduard — eduard.earth · export ("one shaded pixel for each elevation value") —
    eduard.earth/user_guide/en-US.lproj/Page5.html · formats —
    eduard.earth/user_guide/en-US.lproj/Page29.html · Cloud cap — eduard.earth/cloud/help/
    · Mac App Store — apps.apple.com/us/app/eduard-relief-shading/id6443577400 · Jenny,
    Heitzler, Singh, Farmakis-Serebryakova, Liu, Hurni, "Cartographic Relief Shading with
    Neural Networks", IEEE TVCG 2021 (Core ML on a Radeon Pro 5300M, 5,000×5,000 in six
    seconds) — arxiv.org/abs/2010.01256 · doi.org/10.1109/TVCG.2020.3030456 · the 2024
    ambient-occlusion paper (AO "less than one second" on an M1) —
    doi.org/10.14714/CP103.1901
27. Affinity Photo 2 help, "Hardware acceleration" ("Enable Metal compute acceleration",
    raster on GPU, vector on CPU) —
    affinity.help/photo2/en-US.lproj/pages/Extras/hardwareAcceleration.html · key features
    (16- and 32-bit, ICC, PDF/X) — affinity.help/photo2/en-US.lproj/pages/Introduction/keyFeatures.html
    · product page — affinity.studio/photo-editing-software
28. Pixelmator Pro FAQ ("Metal and Core Image technologies", Core ML) —
    support.pixelmator.com/faq-photomator/general/general-questions.md · colour depth —
    support.apple.com/guide/pixelmator-pro/change-the-color-depth-of-an-image-pixa0ae0513d/mac
    · product page — apple.com/pixelmator-pro/
29. Blender GPU rendering (Metal, Apple silicon, macOS 13+) —
    docs.blender.org/manual/en/latest/render/cycles/gpu_rendering.html · render-test
    handbook (per-platform thresholds, CPU/GPU differences, non-deterministic blocklist)
    — developer.blender.org/docs/handbook/testing/render/ · compatibility notes (Metal the
    only macOS backend since 4.0) — developer.blender.org/docs/release_notes/compatibility/
30. MapLibre Native Metal release (iOS v6.0.0) —
    maplibre.org/news/2024-01-19-metal-support-for-maplibre-native-ios-is-here/ ·
    `hillshade` layer — maplibre.org/maplibre-style-spec/layers/ · Metal hillshade shader —
    github.com/maplibre/maplibre-native/blob/main/include/mln/shaders/mtl/hillshade.hpp ·
    render tests (per-platform expectations) —
    github.com/maplibre/maplibre-native/blob/main/docs/mdbook/src/render-tests.md · BSD-2 —
    github.com/maplibre/maplibre-native · Mapbox v10 ("1:1 accurate rendering results") —
    mapbox.com/blog/mapbox-mobile-sdk-v10-beta
31. `gdaldem hillshade` — gdal.org/en/stable/programs/gdaldem.html · QGIS hillshade
    renderer — docs.qgis.org/latest/en/docs/user_manual/working_with_raster/raster_properties.html
    · QGIS OpenCL acceleration option —
    docs.qgis.org/3.44/en/docs/user_manual/introduction/qgis_configuration.html · OpenCL
    hillshade PR — github.com/qgis/QGIS/pull/7451 · renderer source (CPU fallback,
    self-disable on kernel error) —
    github.com/qgis/QGIS/blob/master/src/core/raster/qgshillshaderenderer.cpp · OpenCL
    correctness issues — github.com/qgis/QGIS/issues/28939 · github.com/qgis/QGIS/issues/60077
    · ArcGIS Pro GPU tool list (Hillshade absent) —
    doc.esri.com/en/arcgis-pro/latest/tool-reference/spatial-analyst/gpu-processing-with-spatial-analyst.html
    · rvt-py — rvt-py.readthedocs.io/en/latest/rvt.vis.html · WhiteboxTools —
    github.com/jblindsay/whitebox-tools · rayrender (CPU path tracer) — rayrender.net
32. Local probes, this session, on the host named above (PyObjC 12.2.2 in a scratch
    venv, Python 3.14.2): `probe.py` and `probe2.py` in the session scratchpad, not
    committed. Observations on one machine, not primary sources, and cited only as such.
33. `CIKernel.apply(extent:roiCallback:arguments:)` ("automatically splits large images
    into smaller tiles") —
    developer.apple.com/documentation/coreimage/cikernel/apply(extent:roicallback:arguments:)
    · `CIImage.init(bitmapData:bytesPerRow:size:format:colorSpace:)` (`nil` colour space
    for elevation maps) —
    developer.apple.com/documentation/coreimage/ciimage/init(bitmapdata:bytesperrow:size:format:colorspace:)
    · `CIContext.inputImageMaximumSize()` —
    developer.apple.com/documentation/coreimage/cicontext/inputimagemaximumsize()
