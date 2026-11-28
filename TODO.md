# TODO

## Halftone - effect

- **Paper and ink over the image, or cut out.** Today the effect repaints every pixel
  of the image it is given: between the dots, the paper color replaces the image. A
  transparent paper (`#00000000`) cuts the layer out, so what the effects before it made
  (a film grain, say) is lost and the page shows through. Blend the paper and the ink
  over the image instead, by their alpha, keeping the layer's own transparency: an opaque
  paper looks as now, a transparent one leaves the image between the dots, a half
  transparent one tints it. Keep today's look with a new choice, "Between the dots":
  **Paper** (the new default) or **Cut out**. Test a transparent paper over a non-uniform
  image, both choices. Minor version bump; `compatible_from` unchanged (saved settings
  load as before, only a paper or ink that isn't opaque looks different).
- **Better default dot spacing and dot size.** The defaults (spacing 8 px, dot size
  100 %) look ugly: pick ones that look good on a typical image and shape, in the same
  release.

## Checkers - generator

- **Number of dots instead of squar size** or add x,y offsets to control pattern position

## Cloud - generator

- Add a refresh/seed button to force regeneration

## Dot grid - generator

- Why does adjusting the spacing changes the size of the dots !!! dot size is supposed to be a % of the surface
  maybe it make sense but then an explanation is needed

## Noise - generator

- Add refresh/seed button

## Bands - generator

- Add an offset (that depends on the orientation)
- Add a rotation point (currently center of the surface)
