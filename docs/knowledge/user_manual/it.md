# LaserBase -- Manuale utente

Questo manuale spiega passo dopo passo come utilizzare il programma LaserBase. Il testo è scritto per un utente hobbista con conoscenze tecniche: non presuppone competenze da sviluppatore, ma non cerca nemmeno di semplificare eccessivamente i concetti.

L'obiettivo è capire:
- come viene realizzata un'incisione
- come funziona il programma
- come ottenere risultati di buona qualità

I capitoli seguono il flusso di lavoro reale.

------------------------------------------------------------------------

# 1. Cos'è LaserBase

LaserBase è un programma progettato per macchine di incisione laser. Il suo scopo è gestire l'intero processo di incisione all'interno di un unico ambiente.

Il programma ha quattro parti principali:

• **Finestra principale** — memorizzazione dei parametri di incisione e delle impostazioni dei materiali  
• **Image Workspace** — preparazione delle immagini per l'incisione  
• **Sender** — invio del G-code alla macchina laser  
• **Sketch** — una semplice superficie di disegno

LaserBase non è un programma di disegno. Il suo scopo principale è creare un programma di incisione a partire da un'immagine o da un grafico.

------------------------------------------------------------------------

# 2. Fondamenti dell'incisione laser

Una macchina di incisione laser è un meccanismo mobile che funziona con un raggio laser focalizzato.

L'energia del laser riscalda la superficie del materiale. Di conseguenza il materiale:

- cambia colore
- si carbonizza
- fonde
- oppure evapora

La maggior parte dei laser a diodo funziona in **modalità raster**. Ciò significa che la testa scansiona la superficie linea per linea.

La potenza del laser è generalmente controllata dal controller tramite **regolazione PWM**. Non si tratta semplicemente di un interruttore acceso/spento: la potenza del laser può variare continuamente all'interno di un intervallo. Il parametro `S` nel G-code controlla questa scala.

Il tono inciso è determinato da tre fattori:

1. potenza del laser (PWM)
2. tempo di esposizione (velocità)
3. densità dei punti (raster dithering)

Insieme determinano il risultato. Esiste una relazione diretta tra velocità e potenza:

    Esposizione ∝ Potenza / Velocità

Se si raddoppia la velocità, per ottenere lo stesso effetto sarà necessario quasi raddoppiare anche la potenza.

------------------------------------------------------------------------

# 3. PWM e dithering — due metodi diversi

Il controllo PWM del laser è già in grado di produrre livelli di grigio. Su un determinato materiale, ad esempio, a 0% di potenza non si verifica alcuna bruciatura, al 45% appare un grigio medio e al 100% si raggiunge il massimo scurimento.

Le impostazioni **Min power** e **Max power** definiscono questo intervallo. Il programma mappa i valori di grigio dell'immagine su questa banda.

Tuttavia il controllo basato su PWM non è sempre sufficiente. A velocità elevate i cicli PWM avvengono così rapidamente che il modulo non riesce ad accendersi e spegnersi completamente: il risultato diventa sfocato. Inoltre molti materiali reagiscono in modo non lineare: piccole differenze di potenza producono cambiamenti appena visibili, poi oltre una certa soglia la bruciatura diventa improvvisamente molto più profonda.

In questi casi il **dithering** è una soluzione più stabile. Il dithering non sostituisce il PWM, ma lo integra: l'immagine viene convertita in un pattern binario di punti e la densità dei punti crea l'illusione del tono — lo stesso principio utilizzato nelle fotografie dei giornali.

Le due tecniche possono essere combinate: il dithering decide se il laser deve incidere in una determinata posizione, ma la potenza effettiva dello stato "attivo" proviene comunque dall'intervallo Min/Max.

------------------------------------------------------------------------

# 4. Flusso di lavoro completo di un'incisione

In pratica un'incisione viene realizzata così:

1. caricare l'immagine
2. impostare la dimensione
3. impostare il DPI
4. selezionare il profilo macchina
5. elaborare l'immagine
6. controllare l'anteprima
7. generare il G-code
8. inviare il programma alla macchina

LaserBase segue esattamente questo processo.

------------------------------------------------------------------------

# 5. Image Workspace

L'Image Workspace è la parte più importante del programma. Qui avviene l'elaborazione dell'immagine.

Lo spazio di lavoro ha due parti principali:

sinistra — immagine originale  
destra — anteprima elaborata

L'immagine a destra mostra come apparirà l'incisione.

------------------------------------------------------------------------

# 6. Caricamento di un'immagine

Per caricare un'immagine usare il pulsante **Load image**.

Formati supportati:

- PNG
- JPG / JPEG
- BMP

Dopo il caricamento l'immagine appare immediatamente nel pannello sinistro. A questo punto il programma esegue un'analisi RAW: esamina la risoluzione, la distribuzione dei toni e il contenuto.

------------------------------------------------------------------------

# 6b. Immagine RAW e BASE

Il programma utilizza due stati dell'immagine.

**Immagine RAW**

È l'immagine originale non elaborata caricata dal file.

**Immagine BASE**

È il raster elaborato per l'incisione. È già stato ridimensionato alla risoluzione DPI target e processato con l'algoritmo di dithering.

L'immagine BASE è binaria: per ogni pixel indica solo se il laser deve incidere oppure no.

Il G-code viene sempre generato dall'immagine BASE.

------------------------------------------------------------------------

# 7. Impostazione della dimensione

La dimensione dell'immagine è indicata in millimetri.

Il programma calcola la scala dell'incisione dai pixel e dalla dimensione fisica.

Esempio:

Se un'immagine di 1000 pixel è larga 100 mm, allora 10 pixel corrispondono a 1 mm.

------------------------------------------------------------------------

# 8. DPI

DPI (dots per inch) determina quanto densamente scorrono le linee una accanto all'altra.

    distanza linee (mm) = 25.4 / DPI

Esempi:

    254 DPI → circa 0.1 mm
    127 DPI → circa 0.2 mm

Un DPI più alto produce più dettaglio ma rende l'incisione più lenta.

------------------------------------------------------------------------

# 9. Profilo macchina

Il profilo macchina contiene i parametri fisici della macchina:

- Rate — velocità massima
- Accel — accelerazione
- Max — dimensione area di lavoro
- Scan axis — asse di scansione

Questi valori servono anche per calcolare l'**overscan**.

    Overscan (mm) ≈ Speed² / (2 × Acceleration)

Il campo **Computed overscan** mostra questo valore.

------------------------------------------------------------------------

# 10. Crop

La funzione Crop permette di ritagliare una parte dell'immagine.

Forme possibili:

- rettangolo
- cerchio

------------------------------------------------------------------------

# 11. Elaborazione immagine — dithering

Durante il dithering i toni continui vengono convertiti in un pattern binario.

Per ogni pixel:

    q(f) = 0   se f < soglia
    q(f) = 255 se f ≥ soglia

Errore:

    e = f - q(f)

------------------------------------------------------------------------

# 12. Algoritmi di dithering

**Floyd–Steinberg**

    destra: e × 7/16
    basso-sinistra: e × 3/16
    basso: e × 5/16
    basso-destra: e × 1/16

**Atkinson**

Distribuisce solo 3/4 dell'errore.

**JJN / Stucki**

Estensione del Floyd–Steinberg.

**Bayer**

Matrice di soglia fissa.

**Serpentine scan**

Elaborazione a zig-zag.

------------------------------------------------------------------------

# 13. Impostazioni immagine

**Brightness**

Spostamento lineare della luminosità.

**Contrast**

Amplifica le differenze.

**Gamma**

Trasformazione non lineare.

    γ > 1 → mezzitoni più chiari
    γ < 1 → mezzitoni più scuri

**Radius / Amount**

Sharpening (unsharp mask).

------------------------------------------------------------------------

# 14. Altre opzioni

**Negative**

Inverte i toni.

**Mirror**

Specchio orizzontale o verticale.

------------------------------------------------------------------------

# 15. Ordine della pipeline

    1. Resize
    2. Crop
    3. Mirror
    4. Brightness + Contrast + Gamma
    5. Sharpen
    6. Negative
    7. Dither
    8. Grid alignment

------------------------------------------------------------------------

# 16. Anteprima

Il pannello destro mostra l'immagine finale.

Controllare:

- transizioni tonali
- bande orizzontali
- halo sui bordi
- zone saturate

------------------------------------------------------------------------

# 17. Generazione G-code

Il programma genera un file G-code.

Esempio:

    G1 X10 Y10
    M3 S800

------------------------------------------------------------------------

# 18. Sender

Sender invia il G-code alla macchina.

Processo:

1. selezionare porta
2. Connect
3. caricare G-code
4. controllare stato
5. Start Send

------------------------------------------------------------------------

# 19. Sketch

image-based processing tool per:

- schizzi rapidi
- test
- grafica semplice

------------------------------------------------------------------------

# 20. Errori comuni

- immagine non caricata
- profilo macchina mancante
- crop non valido
- errore G-code

------------------------------------------------------------------------

# 21. Suggerimenti

- fare sempre un test su nuovo materiale
- salvare parametri funzionanti
- controllare anteprima fullscreen

------------------------------------------------------------------------

# 22. Riferimento rapido

    distanza linee = 25.4 / DPI
    Overscan ≈ Speed² / (2 × Acceleration)
    Esposizione ∝ Potenza / Velocità