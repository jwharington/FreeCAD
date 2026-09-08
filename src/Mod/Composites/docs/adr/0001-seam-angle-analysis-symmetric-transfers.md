# Symmetric transfer solves for seam angle analysis

The seam region is analysed as an independent surface contacted from
both sides: the master's fibre direction at the seam comes from a
solved transfer rosette (master → seam), and the attachment's from a
second solved transfer rosette (attachment → seam). The master→seam
rosette seeds the seam shell's drape and rendered weave; the
attachment→seam rosette is analysis-only — it translates the
attachment's lamina directions into the seam's frame evaluated at the
attachment's edge, feeding the effective offset angle
(`attachment_angle_at_seam − master_angle_at_seam`) and the per-ply
seam angle report.

## Why symmetric (considered alternatives)

We considered using the attachment's own drape "natively" over the seam
region for the attachment side — the seam region is a piece of the
attachment surface, so the attachment's drape covers it. Rejected:
either seam edge may be remote from its part's rosette, and the drape
distortion accumulated between a rosette and the seam edge means the
fibre direction at the seam must be solved across the shared edge, not
read from a distant rosette angle (the pre-existing behaviour — copying
the master's rosette angle — could be wrong by many degrees). Treating
the seam symmetrically keeps one rule for both sides.

Consequence: a seam carries **two** transfer rosettes. Do not delete
the attachment→seam rosette as redundant — the attachment's drape
covering the region is an artefact of the attachment shell keeping its
full support after extraction, not a licence to skip the solve. If the
attachment shell is ever re-trimmed at the seam, the symmetric solve
becomes the only correct source for the attachment side.

## Related boundary decision

The seam shell's laminate is the `SeamCompositeLaminate` (combined
master ⊕ attachment stack). The **remainder** shell carries the
attachment's own laminate — not the combined stack. Physically the
master's plies lie on the attachment only within the overlap (the seam
region); beyond it, only the attachment's plies exist. The earlier
virtual-laminate implementation assigned the combined stack to the
remainder too; that was a bug, not a convention.
