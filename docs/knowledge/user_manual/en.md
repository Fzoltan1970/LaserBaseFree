# LaserBase -- User Manual

This manual explains how to use the LaserBase program step by step. The text is written for a technical hobby user: it does not assume developer knowledge, but it also does not try to oversimplify everything.

The goal is to understand:
- how an engraving is made
- how the program works
- how to achieve good-quality results

The chapters follow the real workflow.

------------------------------------------------------------------------

# 1. What LaserBase Is

LaserBase is a program designed for laser engraving machines. Its purpose is to manage the entire engraving process within a single environment.

The program has four main parts:

• **Main window** -- storing engraving parameters and material settings  
• **Image Workspace** -- preparing images for engraving  
• **Sender** -- sending the G-code to the laser machine  
• **Sketch** -- a image-based processing tool

LaserBase is not a drawing program. Its main purpose is to create an engravable program from an image or graphic.

------------------------------------------------------------------------

# 2. Basics of Laser Engraving

A laser engraving machine is a moving mechanism that works with a focused laser beam.

The laser energy heats the surface of the material. As a result, the material:

- changes color
- chars
- melts
- or evaporates

Most diode lasers work in **raster mode**. This means the head scans the surface line by line.

The laser power is usually controlled by the controller using **PWM regulation**. This does not mean a simple on/off switch: the laser power can be varied continuously within a range. The `S` parameter in G-code controls this scale.

The engraved tone is determined by three factors:

1. laser power (PWM)
2. exposure time (speed)
3. dot density (dither raster)

Together these determine the result. There is a direct relationship between speed and power:

    Exposure ∝ Power / Speed

If you double the speed, then to achieve the same effect you will need to nearly double the power as well.

------------------------------------------------------------------------

# 3. PWM and Dithering -- Two Different Methods

The laser's PWM control alone is capable of producing grayscale. On a given material, for example, at 0% power there is no burn, at 45% a mid-gray tone appears, and at 100% the maximum darkness is reached. This is true, continuous tone control.

The **Min power** and **Max power** settings define this range. The program maps the grayscale values in the image onto this band.

However, PWM-based control is not always enough. At high speed, the PWM cycles happen so fast that the module cannot fully switch on and off -- the result becomes blurred. In addition, many materials react nonlinearly: small power differences cause barely visible changes, then above a threshold the burn suddenly becomes much deeper.

In such cases, **dithering** is a more stable solution. Dithering is not a replacement for PWM, but a complement to it: the image is converted into a binary dot pattern, and the density of the dots creates the illusion of tone -- the same principle used in newspaper photographs.

The two can be combined: the dither determines whether the laser burns at a given pixel position, but the actual power assigned to the “on” state still comes from the Min/Max range.

------------------------------------------------------------------------

# 4. The Full Workflow of an Engraving

In practice, an engraving is made like this:

1. load image
2. set size
3. set DPI
4. select machine profile
5. process image
6. check preview
7. generate G-code
8. send program to the machine

LaserBase follows exactly this process.

------------------------------------------------------------------------

# 5. Image Workspace

The Image Workspace is the most important part of the program. This is where image processing takes place.

The workspace has two main parts:

left side -- original image  
right side -- processed preview

The image on the right shows what the engraving will look like.

------------------------------------------------------------------------

# 6. Loading an Image

To load an image, use the **Load image** button.

Supported formats:

- PNG
- JPG / JPEG
- BMP

After loading, the image immediately appears in the left panel. At that point, the program performs RAW image analysis: it examines the resolution, tone distribution, and content. This is the base state from which processing starts.

------------------------------------------------------------------------

# 6b. RAW and BASE Image

The program uses two different image states.

**RAW image**

The RAW image is the original, unprocessed image. This is the image loaded from the file. Every step of processing starts from this.

**BASE image**

The BASE image is the processed engraving raster. It has already been resized to the target DPI resolution, filtered, and processed with a dithering algorithm.

The BASE image is binary: for each pixel it only determines whether the laser will expose or not.

G-code is always generated from the BASE image. The **Save image** function saves this BASE image.

------------------------------------------------------------------------

# 7. Setting the Size

The image size is given in millimeters.

The program calculates the engraving scale from the pixel dimensions and the specified physical size.

Example:

If a 1000-pixel image is 100 mm wide, then during engraving 10 pixels correspond to 1 mm.

This simple ratio is the basis, but the exact processing grid is determined together with the DPI value.

------------------------------------------------------------------------

# 8. DPI

DPI (dots per inch) determines how densely the lines run next to each other.

The line spacing can be calculated as:

    line spacing (mm) = 25.4 / DPI

Examples:

    254 DPI → approx. 0.1 mm line spacing
    127 DPI → approx. 0.2 mm line spacing

Higher DPI gives more detail, but also means slower engraving. At too high a DPI, the lines may overlap, causing overburn.

The program always resizes the source image to the target grid resolution. This means that the processed image resolution usually differs from the resolution of the original image file.

------------------------------------------------------------------------

# 9. Machine Profile

The machine profile contains the physical parameters of the machine.

Typical data:

- Rate -- maximum speed
- Accel -- acceleration
- Max -- work area size
- Scan axis -- scan axis

These values are needed not only for G-code generation, but also for calculating **overscan**.

Overscan is the distance the head runs beyond the end of a line so that it can stop and reverse. If this value is too small, the machine engraves the beginning and end of the line while still decelerating -- uneven speed results in uneven exposure and a distorted image.

The program calculates this automatically:

    Overscan (mm) ≈ Speed² / (2 × Acceleration)

The **Computed overscan** field shows this value. It is not worth estimating it manually -- let the program calculate it.

If you have a saved profile, load it with the **Load config** button. If not, enter the parameters and save them.

------------------------------------------------------------------------

# 10. Crop

With Crop, you can cut out a part of the image.

This is useful, for example, if you want to engrave only a small part of the image.

The crop can be:

- rectangle / square
- circle

With a circular crop, the width and height values must be equal. If the crop area is invalid, the Process button automatically becomes inactive.

------------------------------------------------------------------------

# 11. Image Processing -- Dithering

During dithering, the continuous tones of the image are converted into a binary dot pattern.

For each pixel, the program has to make a simple decision:
should the laser burn there, or should the point remain empty.

In the background, this is a quantization problem: a continuous tone value must be mapped to one of two states.

Its mathematical form is the following. If the tone value of a pixel is `f`, the binary decision is:

    q(f) = 0   if f < threshold    (laser active)
    q(f) = 255 if f ≥ threshold    (laser inactive)

The resulting error is:

    e = f - q(f)

Different dither algorithms differ in how they distribute this error to neighboring pixels.

------------------------------------------------------------------------

# 12. Dither Algorithms

**Floyd--Steinberg**  
The most common error-diffusion algorithm. It distributes the error to four neighbors:

    right neighbor:         e × 7/16
    bottom-left neighbor:   e × 3/16
    bottom neighbor:        e × 5/16
    bottom-right neighbor:  e × 1/16

For photos and continuous tones, this is usually the best choice.

**Atkinson**  
Only 3/4 of the error is distributed to six neighbors (each with a 1/8 ratio), while the remaining 1/4 is lost. It gives sharper contrast, but the accuracy of fine tone transitions is reduced. Better for logos, text, and line graphics than for photos.

**JJN (Jarvis--Judice--Ninke) and Stucki**  
Both extend the Floyd--Steinberg principle two lines deeper. They produce smoother transitions, but require more computation. It is worth testing both -- the difference depends on the material and speed.

**Bayer**  
A fundamentally different approach: it does not diffuse the error, but applies a predefined threshold matrix. The dot pattern forms a regular grid-like structure. Fast, deterministic, reproducible. Useful on materials where error-diffusion algorithms tend to spread out (e.g. soft wood, textile).

**Serpentine scan**  
This is not a standalone dither mode, but an additional switch. When active, processing runs from right to left on every second row. With error-diffusion algorithms (Floyd--Steinberg, JJN, Stucki), this reduces horizontal streaking. It has no effect with Bayer.

------------------------------------------------------------------------

# 13. Image Settings -- The Sliders

The sliders run before dithering. This is important: once the binary dot pattern is created, the tones can no longer be changed.

**Brightness (B)**  
A linear shift on the tone scale. Positive direction brightens, negative darkens. If the engraving is too deep overall, increasing brightness helps.

**Contrast (C)**  
Scaling around the midpoint. Increasing it makes the dark parts darker and the light parts lighter -- extreme values saturate and lose detail. This is intentional behavior.

**Gamma (G) -- midtone correction**  
A nonlinear transformation: it adjusts the midtones without noticeably affecting the darkest and brightest areas.

    γ > 1 → lighter midtones
    γ < 1 → darker midtones

This is especially important on wood and other organic materials, which react nonlinearly to the laser. What we think of as 40% power often corresponds on the surface to something like 70% depth. By lowering gamma, we can compensate for this in advance.

**Radius (R) and Amount (A) -- sharpening**  
The program uses unsharp-mask-type sharpening. The principle is:

    f' = f + A × (f - blur(f, R))

Radius determines over what area edges are searched for. Amount determines how strongly they are emphasized. The two work together: neither gives a meaningful result on its own.

Small Radius (1-2): enhances fine details and texture.  
Large Radius (5-10): emphasizes strong contours.

Important: with too much sharpening, the dither treats artificial edges as real boundaries and generates a denser dot pattern there. This can be unpleasant in photos, but beneficial for text and sharp diagrams.

------------------------------------------------------------------------

# 14. Other Image Options

**Negative**  
Inverts the tones of the image: what was black becomes white. On anodized aluminum, the laser removes the anodized layer -- in negative mode, the engraving result reproduces the original image as a positive image on the surface.

**↔ horizontal mirror and ↕ vertical mirror**  
Mirrors the image geometrically before processing. This is needed if one axis of the machine is wired in reverse, or if we engrave from the back side on transparent material (for example acrylic).

------------------------------------------------------------------------

# 15. Order of the Processing Pipeline

The program always applies the transformations in this order:

    1. Resizing (source → target grid resolution)
    2. Crop (if active)
    3. Mirroring (if active)
    4. Brightness + Contrast + Gamma
    5. Sharpening (Radius + Amount)
    6. Negative (if active)
    7. Dithering algorithm
    8. Machine grid alignment

This order cannot be changed. Gamma and contrast affect the input of the dithering -- if they ran afterward, there would be nothing left to tone-adjust in the binary image. Sharpening also runs before dithering, because afterward the image consists only of black and white dots.

------------------------------------------------------------------------

# 16. Preview

The processed image is visible in the right-hand panel.

Fullscreen mode shows details much better than normal view. In small view, many things look good that do not look good up close.

What to check in fullscreen mode:

- **Tone transitions**: are they gradual, or are there sharp, stepped boundaries?
- **Streaking**: are there horizontal bands? This usually indicates that serpentine scan is turned off with an error-diffusion algorithm.
- **Edge halo**: do extra white or black borders appear along sharp contours? This indicates too much sharpening.
- **Over-quantization**: do the darkest areas merge completely? If so, reduce Brightness or Gamma.

Exit fullscreen: Esc.

------------------------------------------------------------------------

# 17. G-code Generation

For engraving, the program creates a G-code file.

G-code is a list of commands that controls the machine movement and the laser power line by line, pixel by pixel.

Example:

    G1 X10 Y10
    M3 S800

The Save image button saves the processed BASE image -- the binary raster from which the G-code is built. The G-code button itself produces the control file that is passed to the Sender.

If you enable the **Frame** option, the program also generates a frame file. This draws a border around the engraving area, so before the actual job you can verify exactly where the pattern will be placed on the material.

------------------------------------------------------------------------

# 18. Sender

The Sender module sends the G-code to the machine. It runs in a separate window and can be opened from the main window via the Laser button.

The process:

1. select port from the list
2. Connect
3. load G-code
4. check status (Idle/Ready)
5. Start Send

During sending:

- **Pause / Resume** -- pause and continue
- **STOP** -- normal stop
- **E-STOP** -- immediate emergency stop

If the machine enters Alarm state, it can be unlocked with the **$X Unlock** button, then sending can be started again.

From the bottom panel, manual axis movement (jog), marker laser on/off, and manual sending of terminal commands are available.

**Typical errors:**

- No port in the list -- click Refresh, check the cable and the driver.
- Sending does not start -- check that a file is loaded and the connection is active.
- Alarm state -- `$X Unlock`, then try again.

------------------------------------------------------------------------

# 18b. Frame

The Frame function generates a helper file that outlines the engraving boundary. This allows you to verify exactly where the pattern will go on the material before the actual engraving starts.

Usage:

1. generate frame
2. send it with Sender
3. observe the laser movement

If the frame runs in the correct place, the real engraving can be started.

------------------------------------------------------------------------

# 18c. Jog

Manual axis movement is also available on the bottom panel of Sender. This allows fine adjustment of the laser head position before starting the engraving.

The step sizes can usually be set in several increments (for example 0.1 mm, 1 mm, 10 mm).

------------------------------------------------------------------------

# 18d. Marker Laser

The marker laser is a low-power guiding light. When switched on, the head position becomes visible without damaging the material. This is especially useful during positioning.

------------------------------------------------------------------------

# 19. Sketch

Sketch is a image-based processing tool.

It can be used for:

- making quick sketches
- testing engraving ideas
- drawing simple graphics

It runs in a separate window and can be used in parallel with the main window.

------------------------------------------------------------------------

# 20. Common Errors

Typical problems and solutions:

- No image loaded -- Load image button
- No machine profile -- enter it or load it with the Load config button
- Invalid crop area -- draw it again or turn it off
- Different width/height in circular crop -- make them equal
- G-code export error -- check the speed and power fields

Most errors can be prevented by checking the preview.

------------------------------------------------------------------------

# 21. Useful Tips

- Always make a test engraving on a new material.
- Check the dot pattern in fullscreen mode before generating G-code.
- Let the program calculate the overscan value.
- Use the Frame option for positioning before the real job.
- On wood and organic materials, experiment with the gamma value.

Laser engraving is always a material-dependent process. Experience is at least as important as the settings.

------------------------------------------------------------------------

# 22. Quick Reference

    line spacing (mm) = 25.4 / DPI
    number of lines   = Height_mm × DPI / 25.4
    Overscan (mm)     ≈ Speed² / (2 × Acceleration)
    Exposure          ∝ Power / Speed

    Gamma:  γ > 1 → lighter midtones
            γ < 1 → darker midtones

    If the engraving is too deep:
        1. Reduce the gamma value.
        2. Increase the brightness value.
        3. Check whether the lines overlap at the selected DPI.

    If the engraving is faint and lacks detail:
        1. Increase the contrast.
        2. Try the Atkinson algorithm instead of Floyd--Steinberg.
        3. Check whether Radius/Amount is too strong.
