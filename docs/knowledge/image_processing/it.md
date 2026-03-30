# LaserBase -- Elaborazione delle immagini (livello officina)

------------------------------------------------------------------------

## 1. Il modello fisico: cosa succede realmente

Un sistema di incisione laser è una macchina a controllo di movimento
basata su scansione raster. L’incisione avviene riga per riga: la testa
si muove lungo un asse mentre la potenza del laser varia.

La maggior parte dei controller per laser a diodo moderni utilizza il
controllo di potenza PWM (Pulse Width Modulation). Questo significa che
la potenza del laser può essere regolata in modo continuo all’interno di
un intervallo, non esiste soltanto lo stato acceso/spento.

Nella pratica, il tono inciso deriva dalla combinazione di tre fattori:

1. la potenza del laser (PWM)
2. il tempo di esposizione — determinato dalla velocità di movimento
3. la densità spaziale dei punti (raster / dithering)

Molti materiali non reagiscono in modo lineare alla potenza del laser.
Per questo motivo la riproduzione dei toni è spesso più stabile quando
l’immagine viene convertita in un pattern di punti (dither) e il tono
viene prodotto dalla densità dei punti.

Importante: il dithering non esiste perché il laser non sarebbe capace
di funzionare a diversi livelli di potenza. Il dithering è un metodo di
quantizzazione che spesso produce risultati visivi più prevedibili su
molti materiali.

Lo scopo dell’elaborazione delle immagini è quindi generare un raster e
un profilo di potenza che ricostruiscano il più fedelmente possibile i
toni dell’immagine originale sulla superficie del materiale, tenendo
conto dei parametri fisici della macchina e del comportamento del
materiale.

------------------------------------------------------------------------

## 2. Mappatura geometrica

### 2.1 Dimensione fisica e griglia di pixel

L’immagine di ingresso è una griglia di W_px × H_px pixel. Di per sé
questa griglia non ha dimensione fisica. L’obiettivo dell’incisione è
coprire un’area fisica di W_mm × H_mm. Il collegamento tra le due è
definito dal valore DPI.

Spaziatura reale delle linee:

    d = 25.4 mm / DPI

Per esempio, a 254 DPI:

    d = 0.1 mm

Questo significa che linee parallele coprono la superficie di incisione
ogni 0.1 mm.

Numero di linee:

    N_lines = H_mm / d
            = H_mm × DPI / 25.4

Numero di colonne per linea:

    N_cols = W_mm × DPI / 25.4

Questi valori definiscono la reale risoluzione raster dell’immagine
processata, che spesso differisce dalla risoluzione del file originale.
Il programma ricampiona l’immagine sorgente su questa griglia.

### 2.2 Perché i parametri della macchina sono importanti

I calcoli precedenti determinano quante righe e colonne devono essere
generate. Tuttavia la macchina non può fermarsi istantaneamente. A causa
dell’inerzia dell’asse di scansione (tipicamente l’asse X), la testa ha
bisogno di una distanza di frenata e di inversione alla fine di ogni
riga.

La lunghezza minima di overscan deriva dalla fisica del movimento.

Se la velocità di scansione è v (mm/s) e la decelerazione dell’asse è
a (mm/s²), la distanza di frenata è:

    d_brake = v² / (2 × a)

Il programma calcola il valore di overscan utilizzando questa relazione
e i parametri xRate e xAccel.

Se l’overscan è troppo piccolo, la macchina incide l’inizio e la fine
della riga mentre sta ancora accelerando o rallentando. Una velocità
irregolare produce un’esposizione irregolare, visibile come distorsione
ai bordi dell’immagine.

Per questo motivo non è consigliabile stimare manualmente l’overscan.
Il campo **Computed overscan** mostra il valore minimo sicuro calcolato
dai parametri della macchina.

------------------------------------------------------------------------

## 3. Fondamenti matematici del dithering

### 3.1 Errore di quantizzazione

A livello di dithering, per ogni pixel viene presa una decisione
binaria: il laser deve incidere in quel punto oppure no.

Sia il valore tonale di un pixel:

    f ∈ [0,255]

dove 0 è nero e 255 è bianco.

Decisione binaria:

    q(f) = 0    se f < soglia     (laser attivo)
    q(f) = 255  se f ≥ soglia     (laser inattivo)

Errore di quantizzazione:

    e = f - q(f)

L’idea del dithering è non perdere questo errore, ma distribuirlo ai
pixel vicini in modo che il tono medio approssimi quello originale.

------------------------------------------------------------------------

### 3.2 FloydSteinberg
Il più diffuso algoritmo di diffusione dell’errore.

    vicino destro:         e × 7/16
    vicino basso-sinistra: e × 3/16
    vicino basso:          e × 5/16
    vicino basso-destra:   e × 1/16

------------------------------------------------------------------------

### 3.3 Atkinson

Algoritmo classico dei sistemi Apple Lisa / Macintosh. Solo 3/4
dell’errore viene distribuito a sei vicini (1/8 ciascuno). Il restante
1/4 viene perso.

Questo produce un contrasto più forte, ma le transizioni tonali
continue risultano meno precise.

------------------------------------------------------------------------

### 3.4 JJN e Stucki

Entrambi estendono il principio di Floyd–Steinberg distribuendo
l’errore anche due righe più in basso.

------------------------------------------------------------------------

### 3.5 Bayer (dithering ordinato)

Approccio completamente diverso: invece della diffusione dell’errore
viene utilizzata una matrice di soglia predefinita (matrice di Bayer).

Il pattern risultante forma una griglia regolare di punti.

Vantaggi:

- veloce
- deterministico
- riproducibile

------------------------------------------------------------------------

### 3.6 Serpentine scan

Questo riduce gli artefatti direzionali nei metodi di diffusione
dell’errore.

------------------------------------------------------------------------

## 4. Controllo dei toni: funzionamento degli slider

Prima del dithering il programma applica una fase di preparazione dei
toni.

### 4.1 Brightness (B)

Traslazione lineare:

    f' = clamp(f + b, 0, 255)

------------------------------------------------------------------------

### 4.2 Contrast (C)

Scala intorno al punto medio:

    f' = clamp((f - 128) × c + 128, 0, 255)

------------------------------------------------------------------------

### 4.3 Gamma (G)

Trasformazione non lineare:

    f' = 255 × (f / 255) ^ (1/γ)

------------------------------------------------------------------------

### 4.4 Radius (R) e Amount (A)

Sharpening con metodo unsharp mask:

    f' = f + A × (f - blur(f, R))

------------------------------------------------------------------------

## 5. Trasformazioni geometriche

### 5.1 Mirror

Specchiatura orizzontale o verticale dell’immagine prima della
elaborazione.

------------------------------------------------------------------------

### 5.2 Negative

Inversione dei toni:

    f' = 255 - f

------------------------------------------------------------------------

### 5.3 Trattamento 1 pixel

Passaggio locale di post-elaborazione su un'immagine dither binaria.

Gestisce i punti di rumore isolati di un solo pixel secondo una regola
locale. In modalità negativa la stessa regola viene applicata con
polarità invertita.

------------------------------------------------------------------------

## 6. Ordine della pipeline di elaborazione

    1. Resample
    2. Crop
    3. Mirror
    4. Brightness + Contrast + Gamma
    5. Unsharp mask
    6. Negative
    7. Dithering
    8. Pulizia 1 pixel
    9. Allineamento griglia macchina

------------------------------------------------------------------------

## 7. Relazione tra immagine BASE e G-code

Il risultato finale è l’immagine **BASE**, un raster binario. Ogni pixel
corrisponde a una decisione laser ON/OFF.

Relazione di esposizione:

    Esposizione ∝ Potenza / Velocità

------------------------------------------------------------------------

## 8. Anteprima fullscreen

La vista BASE in modalità fullscreen è il modo più affidabile per
valutare il pattern reale prima dell’incisione.

------------------------------------------------------------------------

## 9. Riferimento rapido

    Spaziatura linee (mm) = 25.4 / DPI
    Numero linee          = Altezza_mm × DPI / 25.4
    Overscan (mm)         ≈ Speed² / (2 × xAccel)
    Esposizione           ∝ Power / Speed
