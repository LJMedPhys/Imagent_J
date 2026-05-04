# BioVoxxel Toolbox — UI Guide

## Menu Surface

The installed plugin menu entries are provided under `Plugins > BioVoxxel`, with one utility command under `Plugins > BioVoxxel > Utilities`.

| Menu entry | Primary input | Main purpose | Automation note in this skill |
|---|---|---|---|
| `Adaptive Filter` | 8-bit or 16-bit single image | Shape-aware median or mean filtering | GUI-focused |
| `Binary Feature Extractor` | Two same-size binary images | Keep objects that overlap a selector mask | GUI-focused |
| `Convoluted Background Subtraction` | 8-bit or 16-bit image | Subtract a blurred or ranked background estimate | Source-grounded only |
| `Particle Distribution (2D)` | Binary image | Measure spacing / neighborhood relationships | GUI-focused |
| `EDM Binary Operations` | 8-bit binary image | Erode, dilate, open, or close with EDM morphology | Batch-safe in this skill |
| `Enhance True Color Contrast` | RGB image | Contrast enhancement while preserving color tone | GUI-focused |
| `Extended Particle Analyzer` | Binary image, optional redirect image | Restrict particle analysis by multiple descriptor ranges | GUI-focused |
| `Filter Check` | Image or ROI | Compare filter radii across a stack of trial outputs | GUI-focused |
| `Gaussian Weighted Median` | Single image | Edge-preserving median filtering | GUI-focused |
| `Limited Mean` | Image for thresholding | MoLiM / DiLiM thresholding variants | GUI-focused |
| `Pseudo flat field correction` | 8-bit, 16-bit, or RGB image | Correct uneven illumination | Source-grounded only |
| `Recursive Filters` | Single 8-bit, 16-bit, or RGB image | Repeated median / mean / Gaussian filtering | Source-grounded only |
| `Speckle Inspector` | Two binary images plus optional redirect image | Count or measure secondary objects per primary object | GUI-focused |
| `Watershed Irregular Features` | 8-bit binary image | Split touching irregular objects | Batch-safe in this skill |
| `SSIDC Cluster Indicator` | Binary image | Spatial clustering / comparison workflow | GUI-focused |
| `Leica ROI Reader` | Leica ROI file | Import Leica ROIs into ROI Manager | Utility |

## Core Binary-Analysis Dialogs

### EDM Binary Operations

Menu path: `Plugins > BioVoxxel > EDM Binary Operations`

Controls (GUI label → macro key):

| GUI label | Macro key | Meaning |
|---|---|---|
| `iterations` | `iterations` | Number of erosion / dilation cycles |
| `operation` | `operation` | `erode`, `dilate`, `open`, or `close` |

Use this before watershed when a binary mask contains narrow bridges, small burrs, or tiny holes.

### Watershed Irregular Features

Menu path: `Plugins > BioVoxxel > Watershed Irregular Features`

Controls (GUI label → macro key):

| GUI label | Macro key | Meaning |
|---|---|---|
| `erosion cycle number` | `erosion` | How strongly to erode before candidate separators are evaluated |
| `convexity threshold` | `convexity_threshold` | Convexity-aware stopping criterion; `0` uses erosion-only behavior |
| `separator size` | `separator_size` | Size range of separator fragments to keep, written as `min-max` |
| `exclude` | `exclude` | Treat the separator range as a rejected range rather than an accepted range |

This tool only accepts 8-bit binary images.

### Extended Particle Analyzer

Menu path: `Plugins > BioVoxxel > Extended Particle Analyzer`

Highlights:

- extends standard `Analyze Particles...`
- accepts hyphenated min-max ranges such as `0.20-1.00`
- supports descriptor filters including `Extent`, `Compactness`, `Feret_AR`, and `Coefficient of variation`
- `Redirect to` enables intensity-based measurements on a grayscale image
- `Keep borders (correction)` compensates edge-touching particles instead of simply excluding them

### Binary Feature Extractor

Menu path: `Plugins > BioVoxxel > Binary Feature Extractor`

Controls:

| Control | Meaning |
|---|---|
| `Objects image` | Primary binary mask to keep or reject |
| `Selector image` | Secondary binary mask used as overlap criterion |
| `Object_overlap in % (0=off)` | Required overlap percentage; `0` means any overlap |
| `Combine objects and selectors` | Merge extracted objects with overlapping selectors |
| `Count output` | Emit the `BFE_Results` summary table |
| `Analysis tables` | Emit per-class measurement tables |

The two input images must be binary and have the same width and height.

### Speckle Inspector

Menu path: `Plugins > BioVoxxel > Speckle Inspector`

Controls:

| Control | Meaning |
|---|---|
| `Primary objects (binary)` | Main objects to inspect |
| `Secondary objects (binary)` | Speckles or internal sub-objects to count |
| `Redirect measurements to` | Optional grayscale source for intensity measurements |
| `min_primary_size`, `max_primary_size` | Primary-object size gates |
| `lower_secondary_count`, `upper_secondary_count` | Required secondary-object count per primary object |
| `min_secondary_size`, `max_secondary_size` | Secondary-object size gates |
| `show ROI Manager` | Display ROIs for `primary`, `secondary`, or none |

## Preprocessing and Exploration Dialogs

### Pseudo flat field correction

Menu path: `Plugins > BioVoxxel > Pseudo flat field correction`

Controls:

| Control | Meaning |
|---|---|
| `Blurring radius` | Gaussian background scale used to estimate illumination |
| `hide background` | Hides or keeps the preview background image |

The source code rejects composite images. The plugin supports grayscale and RGB images.

### Recursive Filters

Menu path: `Plugins > BioVoxxel > Recursive Filters`

Controls:

| Control | Meaning |
|---|---|
| `filter` | `Median`, `Mean`, or `Gaussian` |
| `radius` | Must stay `<= 3` |
| `max_iterations` | Hard limit `<= 500` |

The filter stops early when two consecutive filtered images no longer differ.

### Convoluted Background Subtraction

Menu path: `Plugins > BioVoxxel > Convoluted Background Subtraction`

Controls:

| Control | Meaning |
|---|---|
| `convolution filter` | `Gaussian`, `Median`, or `Mean` |
| `radius` | Background scale for subtraction |

The plugin subtracts the filtered copy from the original image and writes the result back into the active image.

## Note on Macro Keys for GUI-Only Tools

The control tables above use the labels shown in each dialog. For `Extended Particle Analyzer`, `Binary Feature Extractor`, `Speckle Inspector`, `Pseudo flat field correction`, `Recursive Filters`, and `Convoluted Background Subtraction`, this skill does **not** claim validated macro parameter keys — these tools are documented for GUI use. If you need to script them, record a fresh macro string via `Plugins > Macros > Record...` inside Fiji and treat the recorded string as authoritative. Only `EDM Binary Operations` and `Watershed Irregular Features` have their macro keys validated here.

## Practical Selection Guide

| If you need to... | Start with... |
|---|---|
| remove thin bridges or tiny mask artifacts | `EDM Binary Operations` with `operation=open` |
| split touching but irregular objects | `Watershed Irregular Features` |
| keep only particles matching descriptor ranges | `Extended Particle Analyzer` |
| keep only objects that overlap a second mask | `Binary Feature Extractor` |
| count puncta or sub-objects inside larger objects | `Speckle Inspector` |
| correct uneven shading before segmentation | `Pseudo flat field correction` |
| compare filter radii quickly | `Filter Check` |
