# bUnwarpJ - UI Guide

bUnwarpJ is available in Fiji under:

`Plugins > Registration > bUnwarpJ`

This menu path is declared in the installed plugin configuration and matches the
official plugin page.

## Before Launching

- Open two related images before launching the plugin.
- Supported image types are 8-bit, 16-bit, 32-bit grayscale, and RGB color.
- bUnwarpJ is a 2D plugin. It does not register 3D volumes.
- If an input is a stack, bUnwarpJ interprets slice 1 as the image and slice 2 as
  its mask rather than as a volume stack.

## Main Dialog

The main dialog lets you define the registration direction and the deformation model.

### Source image

The moving image. This image is elastically deformed to match the target image.

### Target image

The fixed reference image. The direct registered result is returned in target space.

### Registration mode

| Mode | Behavior |
| --- | --- |
| `Fast` | Bidirectional registration with a faster stopping policy |
| `Accurate` | Bidirectional registration with a stricter stopping policy |
| `Mono` | Unidirectional registration from source to target only |

Use `Mono` when only the source-to-target transform matters.
Use `Fast` or `Accurate` when you also need inverse outputs or inverse transform files.

### Image subsample factor

Integer from `0` to `7`.

- `0` keeps full resolution.
- Higher values downsample the images by powers of two during optimization.
- The final transformation is still applied to the original-resolution images.

Use larger values on large images to reduce runtime.

### Initial and final deformation

These settings control the coarsest and finest B-spline deformation scale.

| Label | Internal level |
| --- | --- |
| `Very Coarse` | `0` |
| `Coarse` | `1` |
| `Fine` | `2` |
| `Very Fine` | `3` |
| `Super Fine` | `4` |

Practical guidance:

- Start with `Coarse` to `Very Fine` for moderate misalignment.
- Use `Very Coarse` only when the two images start far apart.
- Use `Super Fine` only when the extra detail is needed and the longer runtime is acceptable.

### Weight controls

| Control | Meaning |
| --- | --- |
| `Divergence weight` | Penalizes rough local expansion and contraction |
| `Curl weight` | Penalizes rough local rotational behavior |
| `Landmark weight` | Enforces manually placed or imported landmarks |
| `Image weight` | Controls pixel-similarity matching |
| `Consistency weight` | Enforces inverse consistency between both directions |
| `Stop threshold` | Stops optimization when the relative change becomes small enough |

Notes:

- All weights are non-negative.
- `Consistency weight` matters only for `Fast` and `Accurate`.
- If you are not using landmarks, leave `landmark weight` at `0`.

## Result Windows

### `Fast` and `Accurate`

Bidirectional modes produce two result stacks:

- source registered into target space
- target registered into source space

Each result stack contains:

1. the warped image
2. the fixed image
3. the warped mask

The final values are also written to the `Results` window.

### `Mono`

`Mono` mode produces only the source-to-target result.

### RGB behavior

RGB images are converted to grayscale for the optimization step, but the resulting
transformations are applied to the original color data.

## Toolbar Features Before Registration

After launching the plugin and before pressing `OK`, the toolbar switches to the
bUnwarpJ tools.

### Landmarks

- Add landmarks with the add-cross tool.
- Move landmarks with the move-cross tool.
- Remove landmarks with the remove-cross tool.
- Matching point selections placed in both images before launch are converted into landmarks.

### Masks

bUnwarpJ supports masks in two ways:

- provide a two-slice stack where slice 1 is the image and slice 2 is the mask
- draw polygonal inner or outer masks with the toolbar tools

### Input/Output menu

The toolbar I/O menu exposes actions such as:

- load landmarks
- save landmarks
- show landmarks
- load elastic transformation
- load raw transformation
- compare transformations
- convert elastic to raw and raw to elastic
- compose transformations
- invert raw transformations
- evaluate image similarity
- adapt coefficients
- load source mask
- load source initial affine matrix

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Dialog does not open | Fewer than two images are open | Open both source and target first |
| Registration is too slow | Images are large or deformation range is too fine | Increase image subsampling or lower the final deformation scale |
| Result is unstable or too elastic | Regularization is too weak | Raise divergence or curl weight slightly |
| Result ignores landmarks | Landmark weight is zero | Raise landmark weight when landmarks should drive the fit |
| Inverse outputs are missing | `Mono` mode was used | Switch to `Fast` or `Accurate` |
| Stack behaves unexpectedly | Input was treated as image-plus-mask | Split the stack or use single-plane images unless a mask stack is intended |
