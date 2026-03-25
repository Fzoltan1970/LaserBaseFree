# LaserBase -- Image Processing (Workshop Level)

------------------------------------------------------------------------

## 1. The physical model: what actually happens

A laser engraving system is a raster-based motion-controlled machine.
Engraving occurs line by line: the head scans along one axis while the
laser power varies.

Most modern diode laser controllers use PWM (Pulse Width Modulation)
power control. This means the laser power can be continuously adjusted
within a range — it is not limited to simple on/off states.

In practice the engraved tone results from a combination of three
factors:

1. laser power (PWM)
2. exposure time — determined by travel speed
3. spatial density of the dots (raster / dithering)

Many materials do not respond linearly to laser power. Because of this,
tone reproduction is often more stable when the image is converted into
a dot pattern (dither) and the tone is produced by dot density.

Important: dithering does not exist because the laser cannot operate at
different power levels. Dithering is a quantization method that often
produces more predictable visual results on many materials.

The purpose of image processing is therefore to generate a raster and
power profile that reproduces the tones of the original image on the
material surface as accurately as possible, taking into account the
machine’s physical parameters and the material’s behavior.

------------------------------------------------------------------------

## 2. Geometric mapping

### 2.1 Physical size and pixel grid

The input image is a grid of W_px × H_px pixels. By itself this grid has
no physical dimension. The goal of engraving is to cover a physical area
W_mm × H_mm. The connection between the two is defined by the DPI value.

Actual line spacing:

    d = 25.4 mm / DPI

For example, at 254 DPI:

    d = 0.1 mm

That means parallel scan lines cover the surface every 0.1 mm.

Number of lines:

    N_lines = H_mm / d
            = H_mm × DPI / 25.4

Number of columns per line:

    N_cols = W_mm × DPI / 25.4

These values define the actual raster resolution of the processed image,
which usually differs from the resolution of the original image file.
The program resamples the source image onto this target grid.

### 2.2 Why machine parameters matter

The calculations above determine how many rows and columns must be
generated. However, the machine cannot stop instantly. Because of the
inertia of the scan axis (usually the X axis), the head needs a braking
distance and a reversal distance at the end of each line.

The minimum required overscan length follows from the physics of motion.

If the scan speed is v (mm/s) and the axis deceleration is a (mm/s²),
the braking distance is:

    d_brake = v² / (2 × a)

The program calculates the overscan value using this formula based on
the xRate and xAccel parameters.

If the overscan is too small, the machine engraves the beginning and end
of the line while still accelerating or decelerating. Uneven speed
results in uneven exposure, which appears as distortion near the edges
of the image.

Therefore overscan should not be estimated manually. The **Computed
overscan** field displays the minimum safe value calculated from the
machine parameters.

------------------------------------------------------------------------

## 3. Mathematical foundation of dithering

### 3.1 Quantization error

At the dithering level, every pixel produces a binary decision: should
the laser fire at that location or not.

Let the tone value of a pixel be:

    f ∈ [0,255]

where 0 is black and 255 is white.

Binary decision:

    q(f) = 0    if f < threshold    (laser active)
    q(f) = 255  if f ≥ threshold    (laser inactive)

Quantization error:

    e = f - q(f)

The idea of dithering is not to discard this error but to distribute it
to neighboring pixels so that the average tone approximates the
original.

------------------------------------------------------------------------

### 3.2 FloydSteinberg
The most widely used error diffusion algorithm. The error of the current
pixel is distributed to four neighbors:

    right neighbor:       e × 7/16
    bottom-left neighbor: e × 3/16
    bottom neighbor:      e × 5/16
    bottom-right neighbor:e × 1/16

Processing proceeds from left to right and top to bottom. The error is
spread in a visually natural direction rather than accumulating in one
place.

------------------------------------------------------------------------

### 3.3 Atkinson

Classic algorithm from the Apple Lisa / Macintosh systems. Only 3/4 of
the error is distributed to six neighbors (each receiving 1/8). The
remaining 1/4 is discarded.

This results in stronger contrast. Continuous tone transitions become
less precise, but dark and light regions remain cleaner.

For engraving this works better for logos, text and line graphics than
for photographs.

------------------------------------------------------------------------

### 3.4 JJN and Stucki

Both algorithms extend the Floyd–Steinberg principle. Error is
distributed not only to the next row but also to pixels two rows below.

JJN weight matrix (normalized to 48):

       *  7  5
 3  5  7  5  3
 1  3  5  3  1

Stucki weight matrix (normalized to 42):

       *  8  4
 2  4  8  4  2
 1  2  4  2  1

The visual difference between the two depends mainly on the material and
engraving speed.

------------------------------------------------------------------------

### 3.5 Bayer (ordered dithering)

This approach is fundamentally different. Instead of propagating error,
it uses a predefined threshold matrix (Bayer matrix).

Example 4×4 matrix:

      0 136  34 170
    102 238 136 204
     51 187  17 153
    153 119 221  85

The resulting dot pattern forms a regular grid. From a distance it
appears as gray, but the grid structure is visible up close.

Advantages:

- fast
- deterministic
- reproducible

Useful on materials where random diffusion dithers tend to blur
(e.g. soft wood or textiles).

------------------------------------------------------------------------

### 3.6 Serpentine scan

For error diffusion algorithms this reverses the direction of error
propagation on alternating lines. The result reduces directional streak
patterns that may appear with single-direction scanning.

For Bayer dithering this has no effect because no error diffusion occurs.

------------------------------------------------------------------------

## 4. Tone control: how the sliders work

Before dithering, the program performs a tone preparation stage on the
image. The sliders control this stage.

### 4.1 Brightness (B)

Linear shift of the tone scale:

    f' = clamp(f + b, 0, 255)

Positive values brighten the image.

------------------------------------------------------------------------

### 4.2 Contrast (C)

Scaling around the midpoint:

    f' = clamp((f - 128) × c + 128, 0, 255)

c > 1 increases contrast  
c < 1 decreases contrast

Extreme values cause clipping of highlights and shadows.

------------------------------------------------------------------------

### 4.3 Gamma (G)

Nonlinear transformation:

    f' = 255 × (f / 255) ^ (1/γ)

γ > 1 → brighter midtones  
γ < 1 → darker midtones

Most materials respond nonlinearly to laser exposure. Gamma adjustment
compensates for this behavior.

------------------------------------------------------------------------

### 4.4 Radius (R) and Amount (A) — sharpening

The program uses an **unsharp mask** method.

1. A blurred copy of the image is generated (Gaussian blur with radius
   R).

2. The difference between original and blurred image is scaled by the
   Amount value and added back:

    f' = f + A × (f - blur(f, R))

Small radius emphasizes fine detail. Large radius emphasizes stronger
edges.

Sharpening is applied before dithering.

------------------------------------------------------------------------

## 5. Geometric transformations

### 5.1 Mirroring

Horizontal and vertical mirroring operate on the raster image before
processing.

Used when:

- machine axis wiring is reversed
- engraving on the back side of transparent materials

------------------------------------------------------------------------

### 5.2 Negative

Tone inversion:

    f' = 255 - f

Used for materials such as anodized aluminum where the laser removes the
surface layer.

------------------------------------------------------------------------

## 6. Processing pipeline order

The program applies transformations in the following order:

    1. Resample (source → target grid resolution)
    2. Crop
    3. Mirroring
    4. Brightness + Contrast + Gamma
    5. Unsharp mask
    6. Negative
    7. Dithering
    8. Machine grid alignment

------------------------------------------------------------------------

## 7. Relationship between BASE image and G-code

The final result of processing is the **BASE image**, a binary raster.
Each pixel corresponds to one laser on/off decision.

The G-code generator reads the BASE image line by line.

Black pixel (0) → laser on  
White pixel (255) → laser off

Exposure relationship:

    Exposure ∝ Power / Speed

------------------------------------------------------------------------

## 8. Fullscreen preview — what to check

The BASE view in fullscreen is the most reliable way to evaluate the
actual engraving pattern before sending it to the machine.

Look for:

- tone transition consistency
- horizontal streaking
- halo artifacts near edges
- excessive quantization in dark areas

------------------------------------------------------------------------

## 9. Practical quick reference

    Line spacing (mm) = 25.4 / DPI
    Number of lines   = Height_mm × DPI / 25.4
    Overscan (mm)     ≈ Speed² / (2 × xAccel)
    Exposure          ∝ Power / Speed

Gamma correction:

    γ < 1 → darker midtones
    γ > 1 → lighter midtones