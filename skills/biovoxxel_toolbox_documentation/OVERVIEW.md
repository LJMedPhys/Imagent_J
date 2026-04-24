# BioVoxxel Toolbox — Overview

## What BioVoxxel Toolbox Does

BioVoxxel Toolbox is a Fiji/ImageJ plugin suite for image filtering, binary-mask cleanup, particle screening, neighborhood analysis, and segmentation support. The public ImageJ plugin page and the upstream GitHub repository describe it as a collection of plugins and macros rather than a single monolithic command surface.

This repo skill treats the toolbox in two layers:

1. A **batch-safe binary-mask workflow** built around `EDM Binary Operations` and `Watershed Irregular Features`.
2. A broader **GUI toolbox surface** for particle screening, selector-based extraction, speckle analysis, and filter exploration.

## Main Workflow Families

| Family | Representative tools | Typical use |
|---|---|---|
| Binary cleanup and splitting | `EDM Binary Operations`, `Watershed Irregular Features` | Clean a binary mask, then separate touching objects before counting |
| Particle screening and extraction | `Extended Particle Analyzer`, `Binary Feature Extractor`, `Speckle Inspector` | Keep only objects matching shape, overlap, or secondary-object criteria |
| Intensity preprocessing | `Pseudo flat field correction`, `Convoluted Background Subtraction` | Correct uneven illumination or remove slowly varying background |
| Filter exploration | `Filter Check`, `Recursive Filters`, `Gaussian Weighted Median`, `Adaptive Filter` | Compare radii and filter types before choosing a production setting |
| Spatial relationships | `Particle Distribution (2D)`, `SSIDC Cluster Indicator` | Explore neighbor spacing or clustering in binary object sets |

## Typical Inputs

| Tool family | Required input |
|---|---|
| EDM / Watershed | 8-bit binary image with foreground at 255 and background at 0 |
| Extended Particle Analyzer | Binary image, optionally plus a grayscale redirect image |
| Binary Feature Extractor | Two same-size binary images: object mask and selector mask |
| Speckle Inspector | Two binary images plus an optional grayscale redirect image |
| Background correction and filtering | 8-bit, 16-bit, or RGB image depending on the specific tool |

## Typical Outputs

| Tool family | Output type |
|---|---|
| EDM / Watershed | Updated binary mask in the active image |
| Extended Particle Analyzer | Results table, outlines or masks, optional ROI Manager entries |
| Binary Feature Extractor | Extracted binary mask and optional count / analysis tables |
| Speckle Inspector | ROI selections, count tables, and optional per-secondary analysis |
| Filter and background tools | Updated image in-place or preview / comparison image stacks |

## Automation Level in This Skill

The checked-in workflow and API notes cover the subset that executed cleanly in this repo's Fiji container:

- `EDM Binary Operations`
- `Watershed Irregular Features`
- the combined script in `GROOVY_WORKFLOW_PREPROCESS_AND_WATERSHED.groovy`

The following BioVoxxel commands are documented for menu-driven use but are **not** claimed as stable headless automation paths here:

- `Extended Particle Analyzer`
- `Binary Feature Extractor`
- `Speckle Inspector`
- `Recursive Filters`
- `Pseudo flat field correction`

The main reason is that some of these tools allocate AWT or ROI-manager windows internally, while others were not adopted as reliable batch commands in this container.

## Installation

### Fiji update site

1. Open `Help > Update...`
2. Choose `Manage Update Sites`
3. Enable the `BioVoxxel` update site
4. Apply changes and restart Fiji

The upstream update site also distributes toolbox dependencies such as `ij_blob`, which are needed by several binary-analysis plugins.

## Known Limitations

- The ImageJ plugin page itself warns that the migrated page content has not been fully re-vetted.
- Batch-safe scripting in this skill is intentionally narrower than the full plugin menu.
- `EDM Binary Operations` and `Watershed Irregular Features` only accept 8-bit binary masks.
- `Pseudo flat field correction` does not support composite images according to the source code.
- `Recursive Filters` limits the radius to `<= 3` and iterations to `<= 500`.
- `Extended Particle Analyzer`, `Binary Feature Extractor`, and `Speckle Inspector` are best treated as GUI-first tools in this repo.

## Citation and Links

- ImageJ plugin page: `https://imagej.net/plugins/biovoxxel-toolbox`
- Source repository: `https://github.com/biovoxxel/BioVoxxel-Toolbox`
- BioVoxxel update site: `https://sites.imagej.net/BioVoxxel/`
