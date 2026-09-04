# Concept candidates awaiting expert review

Machine-drafted candidates. A domain expert skims each block and either **approves** it
(move the block into `library.md`, flipping `status:pending` → `status:approved`) or
**deletes** it. Nothing here is reachable by `recall_concepts` — the retriever reads
`library.md` only.

Drafted 2026-09-03. Topic: **how to treat objects touching the image border after
segmentation** — a gap found in review. The library currently mentions border objects
only as a sub-clause of `sc-analyze-particles-order` (an Analyze-Particles/ImageJ
counting entry), so the guidance does not surface for a query phrased as "how should
cells on the edge of the image be treated after segmentation" — it returns Cellpose
diameter tuning instead.

## ⚠ Reviewer decisions needed before promotion

1. **New source not yet on the approved list.** Entries 1–2 cite Haase et al.,
   *BioImageAnalysisNotebooks* (proposed `src:haase`, ID prefix `hab-`). It is already
   in the local corpus at `data/knowledge_database/BioImageAnalysisNotebooks-main/`,
   and both claims below were read directly out of those notebooks — but `README.md`'s
   "Current approved sources" list does not admit it yet. **Approving entries 1–2 means
   adding `haase` to that list**, e.g.:
   `**haase** — Haase et al., *BioImageAnalysisNotebooks*, https://haesleinhuepf.github.io/BioImageAnalysisNotebooks/`
   If you would rather not open a new source, entry 1 can instead be re-cited to
   image.sc `t/81131` ("Exclude on Edges"), which `sc-analyze-particles-order` already
   draws on — but entry 2's counting correction has no image.sc citation I could verify.

3. **Keywords are tuned against a hard budget — do not add "cells"/"cell"/"measure"
   aliases when editing these entries.** The retriever lets an entry through on a single
   shared token only if that token is rare: present in ≤10% of entries
   (`SOLO_MAX_DF_FRAC`). Several common tokens sit right at that cliff in the current
   library, so adding entries that mention them silently gates out *existing* entries
   that match on that token alone. Measured headroom, and what these three spend:

   | token | df now | limit at 104 entries | spent by these entries |
   |---|---|---|---|
   | `cells` | 9 | 10.4 | 1 (entry 1 only) |
   | `cell` | 10 | 10.4 | 0 — none may use it |
   | `measure` | 10 | 10.4 | 0 — use "measuring" instead |
   | `measuring` | 9 | 10.4 | 1 (entry 1 only) |
   | `segment` | 5 | 10.4 | 1 (entry 1 only) |
   | `nuclei` | 5 | 10.4 | 3 |

   That is why entry 2 says "objects per field" rather than "cells per field", and why
   entry 3 is worded around "object"/"nucleus"/"cytoplasm" and never "cell". The wording
   is load-bearing, not stylistic. Aliases also deliberately avoid rare bigrams such as
   "segment cells": matching one triples an entry's score, and since the relevance floor
   is 0.34 x the top score, that one entry then cuts everything weaker out of the result.

4. **Measured retrieval, keyword-tuning only (no code changed).** Entry 1 carries the
   generic reach for all three, using tokens that had df headroom: `segment objects`,
   `measuring objects`, `cellpose`, `stardist`, `nuclei segmentation`, `dataset of
   nuclei`. Across a 16-query battery of generic cell-segmentation phrasings the border
   guidance now surfaces **15/16**, usually in the top 3.

   The single remaining miss is *"measure mean intensity per cell"*, and it is
   structurally unreachable: it contains only `measure` and `cell`, both of which have
   **zero** headroom in the table above. Buying it would gate out existing entries.

   Cost, over a 27-query battery: 13 queries lose 17 entries between them, but 16 of
   those were ranked 5th or 6th of 6 — the marginal tail pushed off by `CONCEPT_K = 6`.
   Exactly one displacement is deeper than rank 4. The notable casualty is
   `bib-distance-watershed-split` (declumping) dropping off "segment the cells in these
   images" and "measure the area of the cells after segmentation", where it already sat
   last of six; it still returns normally for its own phrasings ("touching cells clumped
   nuclei"). Raising `CONCEPT_K` would recover the tail, but that is a code change and
   was deliberately not made.

2. **Entry 3 has NO admitted source.** It generalises a pattern from this repo's own
   recipes, not from an authoritative text. Per the provenance rule it must be either
   adopted by a named human (change to `src:lukas`, ID `lj-border-paired-compartments`)
   or deleted. Do not promote it as-is.

---

<!--c:hab-border-object-exclusion status:pending src:haase chap:20h_segmentation_post_processing/remove_labels_on_image_edges modality:general task:measurement kw:border,edge,truncated,clipped,cells on the edge,cells at the image border,objects touching the border,border objects,edge objects,partially imaged cells,cut off cells,truncated objects,remove border objects,exclude edge cells,segment objects,measuring objects,nuclei at the image border,cellpose,stardist,nuclei segmentation,dataset of nuclei-->
- **WHEN** measuring per-object properties (area, shape, intensity) from a label image, and some objects touch the image border
  **DO**   decide the rule before measuring, and drop the objects that touch the border; if the removal leaves gaps in the label numbering, re-number the objects while preserving each surviving object's identity, so any join back to earlier per-object results still holds
  **WHY**  an object clipped by the field of view is only partly imaged, so its area, shape and integrated intensity are wrong by an unknown amount and bias every per-object summary downward
  **AVOID** measuring a label image without ever checking for border contact — and avoid re-numbering by a method that reassigns identities, which silently breaks the link to earlier per-object measurements
  SRC: haase · BioImageAnalysisNotebooks › "Remove labels on image edges" ("In case the size of the objects is relevant, one should exclude the object which were not fully imaged and thus, touch the image border")

<!--c:hab-border-count-correction status:pending src:haase chap:32_tiled_image_processing/tiled_nuclei_counting modality:general task:measurement kw:count,density,objects per area,counting bias,border correction,tile,tiling,tiled processing,double counting,edge correction,how many objects,nuclei count,count objects,density per mm2,counting nuclei,nuclei per field-->
- **WHEN** the output is a **count or a density** (objects per field / per mm² / per tile), not per-object morphometry
  **DO**   correct rather than simply exclude: count the objects, then count again after removing all border-touching objects, and report the average of the two — equivalently, credit half of each removed border object
  **WHY**  dropping every border object systematically undercounts, while keeping them all double-counts across adjacent tiles or fields; each border object is on average shared between two fields, so half-crediting is the unbiased estimate
  **AVOID** reusing the "exclude border objects" rule from morphometry when the answer is a count — the two goals need opposite handling. The correction also assumes objects are small relative to the field, so do not apply it to small tiles or large objects
  SRC: haase · BioImageAnalysisNotebooks › "Counting nuclei in tiles" ("we add the two counts, before and after edge-removal, and compute the average of these two measurements… It is not recommended to apply such")

<!--c:hab-border-paired-compartments status:pending src:NEEDS-HUMAN-AUTHOR modality:fluorescence task:segmentation kw:paired,compartments,nucleus,cytoplasm,matched,border,edge,linked objects,nucleus to cytoplasm ratio,per object measurements,drop matched nuclei,compartment pairing,nucleus cytoplasm pair-->
- **WHEN** two segmentations are paired per object (a nucleus inside its cytoplasm, or an object and its organelles) and border objects are being removed
  **DO**   remove the border-touching object **and its matched partner in the other channel**, keyed on the shared object ID; flag rather than silently drop, and report how many pairs were lost
  **WHY**  removing only the compartment that happens to touch the edge leaves orphaned partners and corrupts every ratio built from the pair (e.g. nucleus-to-cytoplasm area ratio); a large lost fraction means the field of view is too small for the objects
  **AVOID** applying the border filter independently per channel
  SRC: ⚠ UNSOURCED — generalised from this repo's own recipes (`recipes/code/batch_hela_nuclei_cytoplasm_segmentation_with_matc.py`, which drops border cytoplasms and their matched nuclei; `recipes/Python.md` `border_touching_cells_detect_flag_diagnostic`, which flags rather than drops). Adopt as `src:lukas` or delete.
