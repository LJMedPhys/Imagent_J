# Bundled micro_sam checkpoints

The Dockerfile copies everything in `models/` into the image's micro_sam cache
(`/home/imagentj/.cache/micro_sam/models`) before its pre-fetch step. Files that are
present here are verified by hash and not downloaded; missing ones are fetched from the
micro_sam model server (uk1s3.embassy.ebi.ac.uk), which was unreachable from 2026-11-20.

Expected files (names without extension, exactly as micro_sam 1.8.2 caches them):

| File | Size |
|---|---|
| `vit_t_lm` | 40,677,198 B |
| `vit_t_lm_decoder` | 44,143,988 B |
| `vit_t_em_organelles` | 40,677,198 B |
| `vit_t_em_organelles_decoder` | 44,143,988 B |

Any other micro_sam checkpoint placed here (e.g. `vit_b_lm` + `vit_b_lm_decoder`) is
baked in the same way.
