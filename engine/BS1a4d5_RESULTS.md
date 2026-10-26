# BS1a4d5 Results

Session start: Sun Oct 25 01:14:38 MST 2026 (HARD CAP 2 h => end by ~03:14 MST)

## Cause (written before any code change)

Instrumented probe of 6f116f9 on the L scene (the `test_bs1a4d_credit_real_bore`
scene, spies on `band.channel_regions`, `band._simulate`, `rough._helix_moves`):

- 41 band caps planned, 29 credited, ALL 29 carry a stored bore; 9 of them
  actually emitted a helix entry. For 8 of those 9 the emitted helix bore
  (= stored bore = predictor at the PIECE start pc[0], stored-vs-emitted
  offset 0.0) has NO planning sim with that bore: the planning sim
  (`shrink_ladder`) pre-cleared the predictor's bore at the FULL-PATH start
  `path[0]`, which for split pieces is a different circle entirely.
  Measured planning-vs-emitted bore-centre offsets (mm, nearest planned bore
  at that Z):

| cap (piece start)        | emitted bore centre / r      | offset mm |
|--------------------------|------------------------------|-----------|
| (-4.7826,-1.5955)@Z0.381 | (-5.2326,-1.5955) r 0.5000   | 9.2763    |
| (-4.8248,-1.9977)@Z0.381 | (-5.2405,-1.8255) r 0.5000   | 9.4803    |
| (-6.2719, 3.5231)@Z0.381 | (-6.0997, 3.1074) r 0.5000   | 6.4243    |
| (-4.9015,-2.6208)@Z0.381 | (-4.9589,-2.4822) r 0.2000   | 9.9321    |
| (-6.7548, 3.1654)@Z0.381 | (-6.0457, 1.4535) r 1.9029   | 7.3803    |
| (-6.3542, 3.3827)@Z0.381 | (-6.3542, 2.9327) r 0.5000   | 6.7325    |
| (-2.6508, 9.3795)@Z0.381 | (-0.7979, 9.3795) r 1.9029   | 2.9370    |
| (-2.7176, 3.0018)@Z0.381 | (-2.8898, 3.4175) r 0.5000   | 3.7910    |

  (cap (-4.8248,-1.9977) is the brief's example: helix centred
  (-5.2405,-1.8255) r 0.5, no planning sim with that bore.)

- So the credited split piece's gate was judged against a sim that
  pre-cleared the WRONG circle: the entry actually clears the stored-bore
  disk, the sim cleared a disk elsewhere - the credit is not backed by the
  bore that is actually emitted.
- Pieces with NO bore at pc[0] already route through plan0_split (credit-0
  emit re-check); the bore-differing split pieces do not.

## Change
TBD

## Tests
TBD

## Mutation
TBD
