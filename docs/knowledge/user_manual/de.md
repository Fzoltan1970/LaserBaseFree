# LaserBase -- Benutzerhandbuch

Dieses Handbuch erklärt Schritt für Schritt die Verwendung des Programms LaserBase. Der Text richtet sich an technisch interessierte Hobbyanwender: Entwicklerkenntnisse werden nicht vorausgesetzt, dennoch wird auf eine übermäßige Vereinfachung verzichtet.

Das Ziel ist zu verstehen:
- wie eine Gravur entsteht
- wie das Programm funktioniert
- wie man qualitativ gute Ergebnisse erzielt

Die Kapitel folgen dem tatsächlichen Arbeitsablauf.

------------------------------------------------------------------------

# 1. Was ist LaserBase

LaserBase ist ein Programm für Lasergravurmaschinen. Sein Zweck besteht darin, den gesamten Gravurprozess in einer einzigen Umgebung zu verwalten.

Das Programm besteht aus vier Hauptteilen:

• **Hauptfenster** — Speicherung von Gravurparametern und Materialeinstellungen  
• **Image Workspace** — Vorbereitung von Bildern für die Gravur  
• **Sender** — Übertragung des G-Codes an die Lasermaschine  
• **Sketch** — eine einfache image-based processing tool

LaserBase ist kein Zeichenprogramm. Der Hauptzweck besteht darin, aus einem Bild oder einer Grafik ein gravierbares Programm zu erzeugen.

------------------------------------------------------------------------

# 2. Grundlagen der Lasergravur

Eine Lasergravurmaschine ist ein beweglicher Mechanismus, der mit einem fokussierten Laserstrahl arbeitet.

Die Energie des Lasers erhitzt die Oberfläche des Materials. Dadurch kann das Material:

- seine Farbe ändern
- verkohlen
- schmelzen
- oder verdampfen

Die meisten Diodenlaser arbeiten im **Rastermodus**. Das bedeutet, dass der Kopf die Oberfläche zeilenweise abtastet.

Die Laserleistung wird normalerweise über eine **PWM-Regelung** gesteuert. Das ist kein einfaches Ein/Aus-Signal: die Leistung kann kontinuierlich innerhalb eines Bereichs verändert werden. Der Parameter `S` im G-Code steuert diese Skala.

Der gravierte Ton wird durch drei Faktoren bestimmt:

1. Laserleistung (PWM)
2. Belichtungszeit (Geschwindigkeit)
3. Punktdichte (Dither-Raster)

Diese bestimmen gemeinsam das Ergebnis. Zwischen Geschwindigkeit und Leistung besteht eine direkte Beziehung:

    Belichtung ∝ Leistung / Geschwindigkeit

Wenn sich die Geschwindigkeit verdoppelt, muss für denselben Effekt die Leistung nahezu verdoppelt werden.

------------------------------------------------------------------------

# 3. PWM und Dithering — zwei unterschiedliche Methoden

Die PWM-Steuerung allein kann bereits Graustufen erzeugen. Auf einem bestimmten Material führt beispielsweise 0 % Leistung zu keiner Verbrennung, etwa 45 % erzeugen ein mittleres Grau und 100 % die maximale Dunkelheit.

Die Einstellungen **Min power** und **Max power** definieren diesen Bereich. Das Programm ordnet die Graustufen des Bildes diesem Bereich zu.

PWM-basierte Steuerung reicht jedoch nicht immer aus. Bei hoher Geschwindigkeit laufen die PWM-Zyklen so schnell ab, dass das Modul nicht vollständig ein- und ausschalten kann — das Ergebnis wird unscharf. Außerdem reagieren viele Materialien nicht linear: kleine Leistungsunterschiede erzeugen kaum sichtbare Veränderungen, oberhalb einer Schwelle wird die Gravur plötzlich deutlich stärker.

In solchen Fällen ist **Dithering** eine stabilere Lösung. Dithering ersetzt PWM nicht, sondern ergänzt es: das Bild wird in ein binäres Punktmuster umgewandelt, und die Punktdichte erzeugt die Illusion von Graustufen — ähnlich wie bei Zeitungsfotos.

Beide Methoden können kombiniert werden: das Dither entscheidet, ob der Laser an einer Pixelposition aktiv ist, während die tatsächliche Leistung weiterhin aus dem Min/Max-Bereich stammt.

------------------------------------------------------------------------

# 4. Der vollständige Gravur-Workflow

In der Praxis läuft eine Gravur folgendermaßen ab:

1. Bild laden
2. Größe festlegen
3. DPI einstellen
4. Maschinenprofil wählen
5. Bild verarbeiten
6. Vorschau prüfen
7. G-Code erzeugen
8. Programm an die Maschine senden

LaserBase folgt genau diesem Ablauf.

------------------------------------------------------------------------

# 5. Image Workspace

Der Image Workspace ist der wichtigste Teil des Programms. Hier findet die Bildverarbeitung statt.

Der Arbeitsbereich hat zwei Hauptteile:

links — Originalbild  
rechts — verarbeitete Vorschau

Das rechte Bild zeigt, wie die Gravur aussehen wird.

------------------------------------------------------------------------

# 6. Bild laden

Zum Laden eines Bildes verwenden Sie die Schaltfläche **Load image**.

Unterstützte Formate:

- PNG
- JPG / JPEG
- BMP

Nach dem Laden erscheint das Bild sofort im linken Panel. Anschließend führt das Programm eine RAW-Analyse durch: Auflösung, Tonverteilung und Inhalt werden untersucht.

------------------------------------------------------------------------

# 6b. RAW- und BASE-Bild

Das Programm verwendet zwei Bildzustände.

**RAW-Bild**

Das RAW-Bild ist das unverarbeitete Originalbild.

**BASE-Bild**

Das BASE-Bild ist das verarbeitete Gravurraster. Es wurde bereits auf die Ziel-DPI-Auflösung skaliert und mit einem Dither-Algorithmus verarbeitet.

Das BASE-Bild ist binär: für jedes Pixel wird nur entschieden, ob der Laser aktiv ist oder nicht.

Der G-Code wird immer aus dem BASE-Bild erzeugt.

------------------------------------------------------------------------

# 7. Größe einstellen

Die Bildgröße wird in Millimetern angegeben.

Das Programm berechnet die Gravurskalierung aus Pixelanzahl und physischer Größe.

Beispiel:

Wenn ein Bild mit 1000 Pixeln 100 mm breit ist, entsprechen 10 Pixel 1 mm.

------------------------------------------------------------------------

# 8. DPI

DPI (dots per inch) bestimmt den Abstand der Linien.

    Linienabstand (mm) = 25.4 / DPI

Beispiele:

    254 DPI → ca. 0,1 mm
    127 DPI → ca. 0,2 mm

Höhere DPI liefern mehr Details, machen die Gravur jedoch langsamer.

------------------------------------------------------------------------

# 9. Maschinenprofil

Das Maschinenprofil enthält die physikalischen Parameter:

- Rate — maximale Geschwindigkeit
- Accel — Beschleunigung
- Max — Arbeitsbereich
- Scan axis — Scanachse

Diese Werte werden auch zur Berechnung des **Overscan** verwendet.

    Overscan (mm) ≈ Speed² / (2 × Acceleration)

Das Feld **Computed overscan** zeigt diesen Wert an.

------------------------------------------------------------------------

# 10. Crop

Mit Crop kann ein Bildbereich ausgeschnitten werden.

Formen:

- Rechteck
- Kreis

------------------------------------------------------------------------

# 11. Bildverarbeitung — Dithering

Beim Dithering werden kontinuierliche Graustufen in ein binäres Punktmuster umgewandelt.

Für jedes Pixel:

    q(f) = 0   wenn f < Schwelle
    q(f) = 255 wenn f ≥ Schwelle

Fehler:

    e = f - q(f)

------------------------------------------------------------------------

# 12. Dither-Algorithmen

**Floyd–Steinberg**

    rechts: e × 7/16
    unten-links: e × 3/16
    unten: e × 5/16
    unten-rechts: e × 1/16

**Atkinson**

Verteilt nur 3/4 des Fehlers.

**JJN / Stucki**

Erweiterung von Floyd–Steinberg.

**Bayer**

Schwellenmatrix.

**Serpentine scan**

Zickzack-Verarbeitung.

------------------------------------------------------------------------

# 13. Bildeinstellungen

**Brightness**

Lineare Helligkeitsverschiebung.

**Contrast**

Verstärkt Unterschiede.

**Gamma**

Nichtlineare Transformation.

    γ > 1 → hellere Mitteltöne
    γ < 1 → dunklere Mitteltöne

**Radius / Amount**

Schärfung (Unsharp Mask).

------------------------------------------------------------------------

# 14. Weitere Optionen

**Negative**

Invertiert die Tonwerte.

**Mirror**

Horizontales oder vertikales Spiegeln.

------------------------------------------------------------------------

# 15. Reihenfolge der Verarbeitung

    1. Resize
    2. Crop
    3. Mirror
    4. Brightness + Contrast + Gamma
    5. Sharpen
    6. Negative
    7. Dither
    8. Grid alignment

------------------------------------------------------------------------

# 16. Vorschau

Das rechte Panel zeigt das Ergebnis.

Im Vollbildmodus prüfen:

- Tonübergänge
- horizontale Streifen
- Halos an Kanten
- gesättigte Bereiche

------------------------------------------------------------------------

# 17. G-Code-Erzeugung

Das Programm erstellt eine G-Code-Datei.

Beispiel:

    G1 X10 Y10
    M3 S800

------------------------------------------------------------------------

# 18. Sender

Sender überträgt den G-Code an die Maschine.

Ablauf:

1. Port auswählen
2. Connect
3. G-Code laden
4. Status prüfen
5. Start Send

------------------------------------------------------------------------

# 19. Sketch

Einfache image-based processing tool für:

- schnelle Skizzen
- Tests
- einfache Grafiken

------------------------------------------------------------------------

# 20. Häufige Fehler

- Bild nicht geladen
- kein Maschinenprofil
- ungültiger Crop
- G-Code-Fehler

------------------------------------------------------------------------

# 21. Nützliche Tipps

- Immer Testgravur durchführen
- Parameter speichern
- Vorschau im Vollbild prüfen

------------------------------------------------------------------------

# 22. Schnellreferenz

    Linienabstand = 25.4 / DPI
    Overscan ≈ Speed² / (2 × Acceleration)
    Belichtung ∝ Leistung / Geschwindigkeit