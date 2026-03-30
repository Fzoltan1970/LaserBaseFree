# LaserBase -- Bildverarbeitung auf Werkstattniveau

------------------------------------------------------------------------

## 1. Das physikalische Modell: was tatsächlich passiert

Ein Lasergravursystem ist eine rasterbasierte bewegungsgesteuerte
Maschine. Die Gravur erfolgt zeilenweise: Der Kopf scannt entlang einer
Achse, während die Laserleistung variiert.

Die meisten modernen Diodenlaser-Controller verwenden eine
PWM-Leistungsregelung (Pulse Width Modulation). Das bedeutet, dass die
Laserleistung innerhalb eines Bereichs kontinuierlich eingestellt werden
kann – sie ist nicht nur ein einfaches Ein/Aus-Signal.

Der gravierte Ton entsteht in der Praxis aus der Kombination von drei
Faktoren:

1. Laserleistung (PWM)
2. Belichtungszeit – bestimmt durch die Bewegungsgeschwindigkeit
3. räumliche Punktdichte (Raster / Dithering)

Viele Materialien reagieren nicht linear auf die Laserleistung. Deshalb
ist die Tonwiedergabe oft stabiler, wenn das Bild in ein Punktmuster
(dither) umgewandelt wird und der Ton durch die Punktdichte entsteht.

Wichtig: Dithering existiert nicht, weil der Laser keine verschiedenen
Leistungsstufen erzeugen könnte. Dithering ist eine
Quantisierungsmethode, die auf vielen Materialien ein vorhersehbareres
visuelles Ergebnis liefert.

Das Ziel der Bildverarbeitung besteht daher darin, ein Raster- und
Leistungsprofil zu erzeugen, das unter Berücksichtigung der physikalischen
Parameter der Maschine und des Materialverhaltens die Tonwerte des
Originalbildes möglichst genau auf der Oberfläche des Werkstücks
rekonstruiert.

------------------------------------------------------------------------

## 2. Geometrische Zuordnung

### 2.1 Physische Größe und Pixelraster

Das Eingangsbild ist ein Raster aus W_px × H_px Pixeln. Dieses Raster
hat zunächst keine physische Dimension. Ziel der Gravur ist es, eine
Fläche von W_mm × H_mm zu bearbeiten. Die Zuordnung erfolgt über den
DPI-Wert.

Der tatsächliche Linienabstand:

    d = 25,4 mm / DPI

Beispiel bei 254 DPI:

    d = 0,1 mm

Das bedeutet, dass parallele Scanlinien im Abstand von 0,1 mm die
Gravurfläche abdecken.

Anzahl der Linien:

    N_lines = H_mm / d
            = H_mm × DPI / 25,4

Anzahl der Spalten pro Linie:

    N_cols = W_mm × DPI / 25,4

Diese beiden Werte bestimmen die tatsächliche Rasterauflösung des
verarbeiteten Bildes. Sie unterscheidet sich meist von der Auflösung der
Originaldatei. Das Programm resampelt das Quellbild auf dieses Zielraster.

### 2.2 Warum Maschinenparameter wichtig sind

Die obige Berechnung legt fest, wie viele Zeilen und Spalten erzeugt
werden müssen. Die Maschine kann jedoch nicht sofort anhalten. Aufgrund
der Trägheit der Scanachse (typischerweise der X-Achse) benötigt der
Kopf am Ende jeder Linie einen Bremsweg und eine Umkehrstrecke.

Die minimal erforderliche Overscan-Länge ergibt sich aus der Physik der
Bewegung.

Wenn die Scan-Geschwindigkeit v (mm/s) und die Achsverzögerung
a (mm/s²) beträgt, ergibt sich der Bremsweg:

    d_brake = v² / (2 × a)

Das Programm berechnet den Overscan-Wert aus dieser Beziehung anhand der
Parameter xRate und xAccel.

Ist der Overscan zu klein, graviert die Maschine den Anfang und das Ende
der Linie während sie noch beschleunigt oder abbremst. Ungleichmäßige
Geschwindigkeit bedeutet ungleichmäßige Belichtung, was als Verzerrung
an den Bildrändern sichtbar wird.

Daher sollte der Overscan nicht geschätzt werden. Das Feld **Computed
overscan** zeigt den minimal sicheren Wert an, der aus den
Maschinenparametern berechnet wurde.

------------------------------------------------------------------------

## 3. Mathematische Grundlage des Ditherings

### 3.1 Quantisierungsfehler

Auf der Dither-Ebene wird für jedes Pixel eine binäre Entscheidung
getroffen: soll der Laser an dieser Stelle brennen oder nicht.

Sei der Tonwert eines Pixels:

    f ∈ [0,255]

wobei 0 schwarz und 255 weiß ist.

Binäre Entscheidung:

    q(f) = 0    wenn f < Schwelle    (Laser aktiv)
    q(f) = 255  wenn f ≥ Schwelle    (Laser inaktiv)

Quantisierungsfehler:

    e = f - q(f)

Die Idee des Ditherings besteht darin, diesen Fehler nicht zu verlieren,
sondern auf benachbarte Pixel zu verteilen, sodass der durchschnittliche
Ton dem Original möglichst nahekommt.

------------------------------------------------------------------------

### 3.2 FloydSteinberg
Der am weitesten verbreitete Fehlerdiffusionsalgorithmus. Der Fehler des
aktuellen Pixels wird auf vier Nachbarn verteilt:

    rechter Nachbar:      e × 7/16
    unten-links:          e × 3/16
    unten:                e × 5/16
    unten-rechts:         e × 1/16

Die Verarbeitung erfolgt von links nach rechts und von oben nach unten.

------------------------------------------------------------------------

### 3.3 Atkinson

Klassischer Algorithmus aus der Apple-Lisa- und Macintosh-Welt. Nur 3/4
des Fehlers werden auf sechs Nachbarn verteilt (jeweils 1/8). Das
verbleibende Viertel geht verloren.

Das Ergebnis ist ein stärkerer Kontrast, während kontinuierliche
Tonübergänge weniger präzise werden.

Für Gravuren eignet sich dieser Algorithmus besser für Logos, Text und
Liniengrafiken als für Fotos.

------------------------------------------------------------------------

### 3.4 JJN und Stucki

Diese Algorithmen erweitern das Floyd–Steinberg-Prinzip. Der Fehler wird
nicht nur auf die nächste Zeile verteilt, sondern auch auf Pixel zwei
Zeilen darunter.

JJN-Matrix (normalisiert auf 48):

       *  7  5
 3  5  7  5  3
 1  3  5  3  1

Stucki-Matrix (normalisiert auf 42):

       *  8  4
 2  4  8  4  2
 1  2  4  2  1

------------------------------------------------------------------------

### 3.5 Bayer (geordnetes Dithering)

Ein grundsätzlich anderer Ansatz. Statt Fehler zu verteilen wird eine
vordefinierte Schwellenmatrix verwendet (Bayer-Matrix).

Beispiel (4×4):

      0 136  34 170
    102 238 136 204
     51 187  17 153
    153 119 221  85

Das resultierende Punktmuster bildet ein regelmäßiges Raster.

Vorteile:

- schnell
- deterministisch
- reproduzierbar

------------------------------------------------------------------------

### 3.6 Serpentine scan

Dadurch wird bei Fehlerdiffusionsalgorithmen die
Fehlerverteilungsrichtung in jeder zweiten Zeile umgekehrt, was
Richtungsartefakte reduziert.

------------------------------------------------------------------------

## 4. Tonsteuerung: Wirkung der Slider

Vor dem Dithering führt das Programm eine Tonvorbereitung durch.

### 4.1 Brightness (B)

Lineare Verschiebung:

    f' = clamp(f + b, 0, 255)

------------------------------------------------------------------------

### 4.2 Contrast (C)

Skalierung um den Mittelpunkt:

    f' = clamp((f - 128) × c + 128, 0, 255)

------------------------------------------------------------------------

### 4.3 Gamma (G)

Nichtlineare Transformation:

    f' = 255 × (f / 255) ^ (1/γ)

------------------------------------------------------------------------

### 4.4 Radius (R) und Amount (A)

Unsharp-Mask-Schärfung:

    f' = f + A × (f - blur(f, R))

------------------------------------------------------------------------

## 5. Geometrische Transformationen

### 5.1 Spiegelung

Horizontale oder vertikale Spiegelung des Bildes vor der Verarbeitung.

------------------------------------------------------------------------

### 5.2 Negative

Tonwert-Inversion:

    f' = 255 - f

------------------------------------------------------------------------

### 5.3 1-Pixel-Verarbeitung

Ein lokaler Nachbearbeitungsschritt für binäre Dither-Bilder.

Behandelt isolierte Einzelpixel-Störungen anhand einer lokalen Regel. Im
Negativmodus gilt dieselbe Regel mit umgekehrter Polarität.

------------------------------------------------------------------------

## 6. Reihenfolge der Verarbeitung

    1. Resample
    2. Crop
    3. Spiegelung
    4. Brightness + Contrast + Gamma
    5. Unsharp Mask
    6. Negative
    7. Dithering
    8. 1-Pixel-Bereinigung
    9. Machine grid alignment

------------------------------------------------------------------------

## 7. Beziehung zwischen BASE-Bild und G-Code

Das Ergebnis der Verarbeitung ist das **BASE-Bild**, ein binäres Raster.
Jeder Pixel entspricht einer Laser-Ein/Aus-Entscheidung.

Der G-Code wird zeilenweise aus diesem Raster erzeugt.

Belichtungsbeziehung:

    Exposition ∝ Leistung / Geschwindigkeit

------------------------------------------------------------------------

## 8. Vollbild-Vorschau

Die BASE-Ansicht im Vollbildmodus ist die zuverlässigste Methode, um das
tatsächliche Gravurmuster vor dem Start zu beurteilen.

------------------------------------------------------------------------

## 9. Schnelle Referenz

    Linienabstand (mm) = 25,4 / DPI
    Linienanzahl       = Höhe_mm × DPI / 25,4
    Overscan (mm)      ≈ Speed² / (2 × xAccel)
    Exposition         ∝ Power / Speed
