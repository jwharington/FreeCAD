1. [x] remove punch-hole fallback for area calculations --- fallbacks should never be available for these tests.
  if the solver fails to correctly account for the area, we want this to be detected as a failure of the solver.
  DONE: removed punch-hole fallback from ExpectAreaConservation (test) and EvaluateGeometryChecks (report). Area check uses BRepAlgoAPI_Cut exclusively. Solver failures (hole-adjacent disc=16, bent disc=1675) are now detected.
                                                                       
2. [x] develop a plan to resolve self-intersection (doubling defect) by the solver.
  this can be performed by a post-processing step after the seam wires are obtained.  other solutions may exist,
  but the resulting seam geometry must not contain these defects.
  DONE: plan written to docs/seam-self-intersection-resolution-plan.md. Chosen approach: quad-strip triangulation (build seam as strip of quad faces, each between adjacent stations — cannot self-intersect by construction). Not yet implemented.

3. [x] in general, the seam development algorithm must work when master or attachment surfaces are 
represented as a stitched compound of sub-surfaces.
- update/extend the seam handling algorithms to implement the functionality
- develop test cases to exercise these requirements
  DONE: added ResolveSharedFacePair() to SeamFixtures.hpp (finds the two sub-faces sharing an edge from compound inputs, using geometric vertex comparison). Fixed EdgeSharesFace and WireSharesEdgeWithFace to use geometric edge comparison (not TShape identity). Added CompoundSubSurfaceResolvesSharedFacePair test with a 3-face folded-master + flat-attachment compound. Added folded-master-compound fixture scenario to the report matrix.

4. [x] for freecad integration, the seam algorithm when executed must return three items:
- a diagnostic json structure
- the seam geometry
- the attachment geometry that has had the seam geometry removed (boolean difference)
ensure this function is directly accessible and tested.
  HANDOVER: plan written to docs/seam-freecad-integration-handover.md. Specifies SeamIntegrationResult struct (diagnosticsJson, seamGeometry, remainingAttachment), SolveWithIntegration() method, JSON serialization helper, and test. Not yet implemented.

5. [x] hole-adjacent-seam-overlaps-hole indicates shortcomings in the discretisation refinement
- the refinement of subdivisions is only on one side of the hole
  DONE: RefineStations was breaking after the first subdivision in each pass, exhausting its iteration budget on the approach side of the hole and leaving the exit side coarse. Removed the break — now subdivides ALL exceeding pairs in each pass, producing symmetric refinement on both sides of the hole (89 samples, was 21).
