# TrackMate ilastik detector (TrackMate-Ilastik 2.0.0)

Applies an ilastik **Pixel Classification** project to each frame, thresholds the probability map of
one class and turns the connected objects into TrackMate spots. 2D (+t) only. Verified 2026-11-16
with ilastik4ij 2.1.0 + ilastik 1.4.2 (the jar is built against ilastik4ij 2.0.3; every class and
field it uses exists in 2.1.0).

```groovy
import fiji.plugin.trackmate.*
import fiji.plugin.trackmate.ilastik.IlastikDetectorFactory
import fiji.plugin.trackmate.tracking.jaqaman.SparseLAPTrackerFactory

def s = new Settings(imp)                       // imp: 2D time series (T > 1, Z = 1)
s.detectorFactory = new IlastikDetectorFactory()
s.detectorSettings = s.detectorFactory.getDefaultSettings()
s.detectorSettings['CLASSIFIER_FILEPATH'] = '/path/pixel_classifier.ilp'
s.detectorSettings['CLASS_INDEX']         = (Integer) 0      // 0-based: 0 = first label class in ilastik
s.detectorSettings['PROBA_THRESHOLD']     = 0.5d
s.detectorSettings['TARGET_CHANNEL']      = (Integer) 1      // 1-based ImageJ channel
s.initialSpotFilterValue = 0.0d
s.trackerFactory  = new SparseLAPTrackerFactory()
s.trackerSettings = s.trackerFactory.getDefaultSettings()
// set LINKING_MAX_DISTANCE etc. in calibrated units, then new TrackMate(new Model(), s).process()
```

| Key | Meaning |
|---|---|
| `CLASSIFIER_FILEPATH` | trained Pixel Classification `.ilp` |
| `CLASS_INDEX` | which label class becomes objects, **0-based** (ilastik "Label 1" = 0) |
| `PROBA_THRESHOLD` | probability cut-off for that class (default 0.5) |
| `TARGET_CHANNEL` | channel fed to ilastik when the model has one channel; multi-channel models get all channels |

Spot QUALITY = maximum class probability inside the object (0–1), so a quality filter is a
confidence filter.

Verified example: `pixel_class_2d_cells_apoptotic.ilp` on a 3-frame movie of `2d_cells_apoptotic.tif`
→ CLASS_INDEX 0: ~120 spots/frame, median radius 24 px, quality 0.53–1.0; CLASS_INDEX 1 (background
class): 5–6 spots/frame. Pick the class index whose objects match what you see.

## Requirements and failure modes

- Executable comes from the ilastik4ij preference (`IlastikOptions.executableFile`). Agentic-J presets
  it at container start; if it is empty TrackMate fails with
  `NullPointerException ... "opts.executableFile" is null` — run any GROOVY_WORKFLOW_* of this skill
  once, or set it in `Plugins > ilastik > Configure ilastik executable location`.
- The `.ilp` must contain `Input Data/infos/lane0000/Raw Data/shape` (saved by ilastik ≥ 1.3.3).
  Projects from ilastik ≤ 1.2 that store axistags without shape fail with
  `HDF5SymbolTableException: object 'shape' doesn't exist` (in `IlastikRunner.getModelNChannel`) —
  open and re-save the project in the bundled ilastik 1.4.2.
- Only Pixel Classification projects; 3D (Z > 1) is rejected ("Image must be 2D over time").
- The detector runs ilastik once on the whole movie (TrackMate `processGlobal`), via a temporary
  HDF5 copy — expect ilastik start-up (~10 s) plus prediction time; validate on 2–3 frames first.
