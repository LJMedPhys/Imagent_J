# DeepImageJ - MODEL DISCOVERY

DeepImageJ is not limited to one bundled segmentation model. The official
DeepImageJ project points users to the BioImage Model Zoo as the main source of
compatible models.

Official references:

- DeepImageJ models page: https://deepimagej.github.io/models.html
- DeepImageJ home page: https://deepimagej.github.io/
- DeepImageJ about page: https://deepimagej.github.io/about.html
- BioImage Model Zoo: https://bioimage.io/
- Official BioImage Model Zoo collection JSON:
  https://uk1s3.embassy.ebi.ac.uk/public-datasets/bioimage.io/collection.json

The DeepImageJ about page explicitly describes `DeepImageJ Install Model` as
installing compatible models from the BioImage Model Zoo, a given URL, or a
local path.

---

## Example Model Categories

The DeepImageJ home page highlights example model categories beyond
segmentation:

- Super-resolution fluorescence
- Virtual staining / in-silico labeling
- Density estimation
- Background removal and sparse imaging workflows

Examples named on the official site include:

- `Widefield DAPI Super-resolution`
- `Widefield FITC Super-resolution`
- `Widefield TxRED Super-resolution`
- `Jones Virtual Staining`
- `MT3 Virtual Staining`
- `DEFCoN density map estimation`

Examples currently present in the official BioImage Model Zoo collection with
the `deepimagej` tag include:

- `Pancreatic Phase Contrast Cell Segmentation (U-Net)`
- `Mitochondria resolution enhancement Wasserstein GAN`
- `CHO cells nuclei virtual staining - brightfield - Pix2Pix`
- `SLNet_STORM_10100_it`
- `Mitochondria TOM20 artificial labelling - pix2pix`

Treat the BioImage Model Zoo as the authoritative live catalog because the
available set changes over time.

---

## Reproducible Local Listing

Use this Python snippet to list current DeepImageJ-compatible model entries from
the official BioImage Model Zoo collection JSON:

```python
import json
import urllib.request

url = "https://uk1s3.embassy.ebi.ac.uk/public-datasets/bioimage.io/collection.json"
with urllib.request.urlopen(url, timeout=30) as r:
    collection = json.load(r)["collection"]

for item in collection:
    if item.get("type") != "model":
        continue
    tags = [t.lower() for t in item.get("tags", [])]
    links = item.get("links", [])
    if "deepimagej" not in tags and "deepimagej/deepimagej" not in links:
        continue
    print(item.get("name"))
    print("  id:      ", item.get("id"))
    print("  nickname:", item.get("nickname"))
    print("  rdf:     ", item.get("rdf_source"))
```

This is the best way to keep the skill aligned with the current collection
without hard-coding a stale model inventory.

---

## How To Pick a Model

When choosing a DeepImageJ model, check:

- modality: fluorescence, brightfield, TEM, SMLM, confocal, light sheet
- task: segmentation, super-resolution, virtual staining, denoising, background removal
- framework: Torchscript, TensorFlow, or ONNX
- input axes and shape from `rdf.yaml`
- whether the model provides sample input and sample output files
- whether preprocessing or postprocessing macros are required

If you are evaluating a new model, start with the packaged sample input before
moving to your own data.
