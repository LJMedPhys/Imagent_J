# micro_sam — verified API (micro_sam 1.8.2, env `napari-mcp`)

All signatures below were introspected from the installed package. Import from
`micro_sam.automatic_segmentation` (batch) and `micro_sam.sam_annotator` (interactive napari widgets).

## Batch / headless — `micro_sam.automatic_segmentation`

```python
get_predictor_and_segmenter(
    model_type: str,                         # e.g. "vit_b_lm" (see MODELS)
    checkpoint: str | os.PathLike | None = None,   # custom finetuned weights
    device: str = None,                      # "cuda" | "cpu"; None auto-selects
    segmentation_mode: Literal["amg","ais","apg"] | None = None,   # None → AIS if a decoder exists
    is_tiled: bool = False,                   # tile very large images (pair with tile_shape/halo)
    predictor=None, state=None, **kwargs,
) -> (SamPredictor, AMGBase | InstanceSegmentationWithDecoder)

automatic_instance_segmentation(
    predictor,                                # from get_predictor_and_segmenter
    segmenter,                                # from get_predictor_and_segmenter
    input_path: os.PathLike | str | np.ndarray,   # array OR image path
    output_path: str | os.PathLike | None = None, # if given, writes the label image
    embedding_path: str | os.PathLike | None = None,  # cache SAM embeddings (speeds re-runs)
    mask_path=None, key=None, mask_key=None,
    ndim: int | None = None,                  # REQUIRED for array input: 2 (plane) or 3 (z-stack)
    tile_shape: tuple[int,int] | None = None,
    halo: tuple[int,int] | None = None,
    verbose: bool = True,
    return_embeddings: bool = False,
    annotate: bool = False,
    batch_size: int = 1,
    **generate_kwargs,                        # forwarded to the mask generator
) -> np.ndarray                               # integer label image (0 = background)
```

## Interactive napari widgets — `micro_sam.sam_annotator`

Call these inside napari (via `mcp__napari_mcp__execute_code`), passing the running `viewer`. Signatures
below are `inspect.signature()` on the installed 1.8.2 package, not the abbreviated public docstring —
every parameter is real and callable.

> The `model_type="vit_b_lm"` default below is **micro_sam's own upstream default**, not the right
> choice on this CPU build — pass `vit_t_lm` explicitly there. These calls also run on napari's Qt
> thread, so warm the model cache from a script first (see `SKILL.md` → Backend B) or the viewer will
> freeze.

```python
annotator_2d(image: np.ndarray, embedding_path=None, segmentation_result=None,
             model_type="vit_b_lm", tile_shape=None, halo=None, return_viewer=False,
             viewer=None, precompute_amg_state=False, checkpoint_path=None,
             decoder_path=None, device=None, prefer_decoder=True)
annotator_3d(image, embedding_path=None, segmentation_result=None, model_type="vit_b_lm",
             tile_shape=None, halo=None, return_viewer=False, viewer=None,
             precompute_amg_state=False, checkpoint_path=None, decoder_path=None,
             device=None, prefer_decoder=True)                                    # z-stack; identical signature to annotator_2d
annotator_tracking(image, embedding_path=None, model_type="vit_b_lm", tile_shape=None,
                    halo=None, return_viewer=False, viewer=None, precompute_amg_state=False,
                    checkpoint_path=None, decoder_path=None, device=None)          # 2d + time; NO segmentation_result, NO prefer_decoder — the only two annotators that drop them
image_series_annotator(images: list, output_folder: str, model_type="vit_b_lm",
                        embedding_path=None, initial_segmentations=None, tile_shape=None,
                        halo=None, viewer=None, return_viewer=False, precompute_amg_state=False,
                        checkpoint_path=None, is_volumetric=False, device=None,
                        prefer_decoder=True, skip_segmented=True)                  # folder, one image at a time; NO decoder_path (the one annotator missing it)
```

`precompute_amg_state=True` also caches the AMG/AIS **decoder** state alongside the embeddings (so a
later "Automatic Segmentation" click in that session is faster) — it does **not** touch the ~60 s
model-weight loading inside `initialize_predictor` (see `SKILL.md` pitfall on the 90 s MCP timeout).
Precomputed embeddings are still the fix for that; this flag is a separate, smaller optimisation.

The napari plugin manifest is registered as **`micro-sam`** → GUI menu **Plugins → Segment Anything for
Microscopy** (opens the same annotator widgets).

## Embedding / state precompute — `micro_sam.precompute_state`

```python
precompute_state(
    input_path: os.PathLike | str,            # single file, container (hdf5/zarr), or a folder
    output_path: os.PathLike | str,            # embedding cache destination (e.g. a .zarr path)
    pattern: str | None = None,                 # glob to select files when input_path is a folder
    model_type: str = "vit_b_lm",
    checkpoint_path: os.PathLike | str | None = None,
    key: str | None = None,                     # required for container files / multi-image stacks
    ndim: int | None = None,                    # inferred if omitted
    tile_shape: tuple[int, int] | None = None,
    halo: tuple[int, int] | None = None,
    precompute_amg_state: bool = False,          # also cache AMG/AIS decoder state, not just embeddings
) -> None
```

Used to warm `embedding_path` before opening an interactive annotator (see `SKILL.md` Pattern 2) —
the call itself does the heavy embedding compute, so it belongs in `python_data_analyst`, never inside
`mcp__napari_mcp__execute_code`.

## Fast environment check — `micro_sam.info` (CLI)

A zero-code, ~2 s sanity check installed as a console script in the `napari-mcp` env. Run it from a
`python_data_analyst` script with the **full path** — the env's `bin/` is not on PATH just from the
`# imagentj-env: napari-mcp` header, even though that header does pick the right Python interpreter:

```python
subprocess.run(["/opt/conda/envs/napari-mcp/bin/micro_sam.info"], capture_output=True, text=True)
```

Before a heavy task, this confirms the installed version, cache directory, the full supported-model
list (with each model's checkpoint version tag, e.g. `vit_t_lm (v3)`), and whether a GPU is actually
visible to this process — cheaper than guessing and finding out 60 s into a launch. The package also
installs `micro_sam.annotator_2d` / `_3d` /
`_tracking` / `image_series_annotator` / `automatic_segmentation` / `train` / `evaluate` as CLI entry
points, but these open their own native/blocking window or run standalone — prefer the Python API
routes above (Backend A/B in `SKILL.md`), which stay inside this app's viewer, timeout and stop-button
machinery.

## Custom / fine-tuned checkpoints

Pass a local checkpoint instead of (or alongside) a built-in `model_type` name:

- **Batch (`get_predictor_and_segmenter`)**: `checkpoint=` — one path, for the encoder. There is no
  separate decoder override here; `segmentation_mode="ais"` with a custom `checkpoint` still needs the
  model to carry (or you to separately load) a matching decoder.
- **Interactive (all four annotators)**: `checkpoint_path=` (encoder) **and** `decoder_path=` (AIS
  decoder) are separate parameters — except `image_series_annotator`, which has `checkpoint_path` but
  **no** `decoder_path`.
- **`precompute_state`**: `checkpoint_path=` only (same asymmetry as the batch path).

If a lab has its own fine-tuned SAM weights (via `micro_sam.training`, not covered by this skill — that
is a separate, GPU-hours-scale workflow requiring labeled training data, out of scope for routine
segmentation tasks), this is how you point micro_sam at them instead of a stock `*_lm`/`*_em` model.

## Models — `micro_sam.util.get_model_names()`

Default = **`vit_b_lm`**. Backbone size: `vit_t` (tiny, fastest; needs `mobile_sam`) < `vit_b` (base)
< `vit_l` (large) < `vit_h` (huge; base SAM only). Domain finetunes:

```
Light microscopy (LM):     vit_t_lm  vit_b_lm  vit_l_lm         (+ *_lm_decoder for AIS)
Electron microscopy (EM):  vit_t_em_organelles  vit_b_em_organelles  vit_l_em_organelles  (+ *_decoder)
Histopathology (H&E):      vit_b_histopathology  vit_l_histopathology  vit_h_histopathology (+ *_decoder)
Medical imaging:           vit_b_medical_imaging                                            (+ _decoder)
Natural-image SAM:         vit_t  vit_b  vit_l  vit_h
```

The `*_decoder` names are the instance-segmentation decoders used by `segmentation_mode="ais"`; you
pass the plain name (e.g. `vit_b_lm`) and micro_sam loads the matching decoder automatically.

## Modes

- **`ais`** — Automatic Instance Segmentation via the finetuned decoder. Fast, recommended for LM/EM
  where a `*_lm` / `*_em` model exists.
- **`amg`** — Automatic Mask Generation (original SAM grid-of-points). Works with any backbone but is
  slower and less microscopy-aware.
- **`apg`** — Automatic Prompt Generation.
