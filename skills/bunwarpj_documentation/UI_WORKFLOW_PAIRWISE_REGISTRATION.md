# bUnwarpJ - UI Workflow: Pairwise Elastic Registration

This workflow registers one 2D source image to one 2D target image from the Fiji GUI.

## Prerequisites

- Fiji with `Plugins > Registration > bUnwarpJ` available
- Two related 2D images open in Fiji
- Optional: point selections or masks prepared before launch

## Step 1 - Open and rename the images

1. Open the moving image and the fixed reference image.
2. Rename them to short, stable titles with `Image > Rename...`.
3. Confirm both are single-plane 2D images unless you intentionally want to use a
   two-slice image-plus-mask stack.

## Step 2 - Optional landmark preparation

Use landmarks when the default image-based optimization is not enough.

1. If you already know matching features, place point selections in both images before launch.
2. Make sure both images contain the same number of points.
3. These point selections are converted into bUnwarpJ landmarks after launch.

If you do not need landmarks, skip this step and leave `landmark weight` at `0`.

## Step 3 - Launch bUnwarpJ

1. Choose `Plugins > Registration > bUnwarpJ`.
2. In the dialog, set:
   - `Source image`: the moving image
   - `Target image`: the fixed reference image

## Step 4 - Choose the registration settings

For a strong default starting point:

- `Registration`: `Accurate`
- `Image subsample factor`: `0`
- `Initial deformation`: `Coarse`
- `Final deformation`: `Very Fine`
- `Divergence weight`: `0`
- `Curl weight`: `0`
- `Landmark weight`: `0` unless landmarks are being used
- `Image weight`: `1`
- `Consistency weight`: `10`
- `Stop threshold`: `0.01`

When to adjust:

- Use `Fast` when you want the same bidirectional workflow with lower runtime.
- Use `Mono` when only the direct source-to-target transform matters.
- Increase `image subsample factor` on very large images.
- Raise `landmark weight` when manual correspondences must dominate the fit.

## Step 5 - Optional mask setup

Use masks only when background regions would mislead the registration.

Options:

- supply an image-plus-mask stack for one or both inputs
- use the inner-mask or outer-mask drawing tools from the bUnwarpJ toolbar

If masks are not needed, leave them unset.

## Step 6 - Optional transform export

If you want reusable transformation files:

1. Enable the dialog option that saves transformations.
2. Provide output paths for the direct and inverse elastic transforms.
3. Remember that inverse output exists only for `Fast` and `Accurate`.

These elastic transform files can be reused later from the toolbar I/O menu or from scripts.

## Step 7 - Run the registration

1. Click `OK`.
2. Watch the progress windows and the `Results` window.
3. If the optimization needs to stop early, use the stop button from the temporary toolbar.

Result behavior:

- `Fast` and `Accurate` return two result stacks, one for each direction.
- `Mono` returns only the source-to-target result.

## Step 8 - Inspect the outputs

For each result stack:

1. View slice 1 for the warped image.
2. View slice 2 for the fixed image.
3. View slice 3 for the warped mask.

Check that the warped source now matches the target geometry.

If the result is poor:

- add a few landmarks near strong features
- narrow the deformation range
- lower the image subsample factor
- increase regularization slightly with divergence or curl weight

## Step 9 - Save the outputs

Save the items you need:

- registered result stack(s) as TIFF
- transformation text files
- landmark files from the toolbar I/O menu
- screenshots or overlays for documentation

## Notes

- `Mono` mode is the simplest choice when you only need one direction.
- `Fast` and `Accurate` are the modes to use when inverse outputs or inverse transform files are required.
- bUnwarpJ is a 2D plugin. For 3D registration, use another tool.
