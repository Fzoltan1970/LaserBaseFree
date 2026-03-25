# LaserBase -- Képfeldolgozás műhely szinten

------------------------------------------------------------------------

## 1. A fizikai modell: mi történik valójában

A lézergravírozó rendszer raszter alapú mozgásvezérelt gép. A gravírozás
soronként történik: a fej egy tengely mentén pásztáz, miközben a lézer
teljesítménye változik.

A modern dióda lézervezérlők többsége PWM (Pulse Width Modulation)
teljesítményszabályzást használ. Ez azt jelenti, hogy a lézer
teljesítménye folyamatosan állítható egy tartományon belül, nem csak be-
és kikapcsolt állapot létezik.

A gravírozott tónus a gyakorlatban három tényező kombinációjából jön
létre:

1.  a lézer teljesítménye (PWM)
2.  az expozíciós idő -- amelyet a haladási sebesség határoz meg
3.  a pontok térbeli sűrűsége (raszter / dithering)

Sok anyag nem lineárisan reagál a lézer teljesítményére. Emiatt a
tónusvisszaadás gyakran stabilabb, ha a kép pontmintává (dither) alakul,
és a tónust a pontsűrűség hozza létre.

Fontos: a dithering nem azért létezik, mert a lézer ne tudna különböző
teljesítményszinteken működni. A dithering egy kvantálási módszer, amely
sok anyagon kiszámíthatóbb vizuális eredményt ad.

A képfeldolgozás célja ezért az, hogy a létrehozott raszter és
teljesítményprofil a gép fizikai paraméterei és az anyag viselkedése
alapján a lehető legjobban rekonstruálja az eredeti kép tónusait a
munkadarab felszínén.

## 2. A geometriai összerendelés

### 2.1 Fizikai méret és pixelrács

A bemeneti kép egy W_px × H_px pixelből álló rács. Ez önmagában
dimenziótlan. A gravírozás célja egy W_mm × H_mm fizikai terület
lefedése. A kettőt a DPI értéken keresztül rendeljük össze.

A tényleges vonalköz (line spacing):

    d = 25,4 mm / DPI

Például 254 DPI esetén d = 0,1 mm, azaz soronként 0,1 mm-enkénti
párhuzamos vonalak fedik le a gravírozási területet.

A sorok száma:

    N_lines = H_mm / d = H_mm × DPI / 25,4

Egy sor hossza pixelben:

    N_cols = W_mm × DPI / 25,4

Ez a két szám adja meg a feldolgozott kép tényleges raszterfelbontását
-- ami általában eltér az eredeti képfájl felbontásától. A program a
forrásképet erre a célrácson resamplezi.

### 2.2 Miért nem mindegy a gépparaméter

Az előző számítás megadja, hány sort és hány oszlopot kell legyártani.
De a gép nem tud azonnal megállni. Az X tengely (tipikusan a scan
tengely) tehetetlensége miatt a sor végén a fejnek van egy féktávolsága,
majd egy visszafordulási távolsága.

Az overscan minimálisan szükséges hossza a következőből adódik:

Ha a scan sebesség v (mm/s), a tengely lassulása a (mm/s²), akkor a
féktávolság:

    d_brake = v² / (2 × a)

Az overscan értékét a program ebből az összefüggésből számolja, a
megadott xRate és xAccel paraméterek alapján. Ha az overscan túl kicsi,
a sor elejét és végét nem konstans sebességen gravírozza a gép -- az
egyenetlen sebesség egyenetlen expozíciót jelent, ami a kép szélein
látható torzulásként jelenik meg.

Ezért nem elegendő „nagyjából megbecsülni" az overscan értéket. A
Computed overscan mező pontosan erre van: a gépadatokból számolt
minimálisan biztonságos értéket mutatja.

------------------------------------------------------------------------

## 3. A dithering matematikai alapja

### 3.1 A kvantálási hiba fogalma

A dithering szintjén minden pixelre egy bináris döntés születik: ég-e
ott a lézer, vagy sem. Ez a döntés a dither logika szintjén bináris --
nem a lézer fizikai korlátja, hanem a kvantálási módszer természete.

Legyen egy pixel tónusértéke f ∈ \[0, 255\], ahol 0 a fekete és 255 a
fehér. A bináris döntés:

    q(f) = 0,   ha f < küszöb    (lézer aktív)
    q(f) = 255, ha f ≥ küszöb   (lézer inaktív)

A kvantálási hiba:

    e = f - q(f)

A dithering lényege: ezt a hibát ne veszítsük el, hanem adjuk tovább a
szomszédos pixeleknek, hogy az összesített tónus átlagban közelítse az
eredetit.

### 3.2 FloydSteinberg
A legelterjedtebb hibakeresztező algoritmus. Az aktuális pixel hibáját
négy szomszédra terjeszti:

    jobb szomszéd:        e × 7/16
    bal alsó szomszéd:    e × 3/16
    alsó szomszéd:        e × 5/16
    jobb alsó szomszéd:   e × 1/16

Ez balról jobbra, fentről le haladva dolgozza fel a képet. Az eredmény
az, hogy a hiba nem halmozódik egy helyen, hanem a vizuálisan
természetes irányban terül szét.

### 3.3 Atkinson

Az Apple Lisa / Macintosh világ klasszikusa. Csak a hiba 3/4-ét osztja
szét hat szomszédra (egyenként 1/8 arányban), a maradék 1/4 elvész. Ez
azt jelenti, hogy a nagyon sötét és nagyon világos területeken kevésbé
„szürke" az eredmény -- élesebb kontraszthatás, de a folyamatos
tónusátmenetek pontossága csökken.

Gravírozásnál: kontrasztos, vonalas mintákhoz, logókhoz, szöveghez
jobban illik, mint fotóhoz.

### 3.4 JJN és Stucki

Mindkét algoritmus a Floyd--Steinberg elvét terjeszti ki: a hibát
nemcsak az egy sorral lejjebb lévő szomszédokra, hanem két sorral
lejjebb lévőkre is osztja szét. A hibaeloszlás mátrixa nagyobb (5×3), az
eredmény simább, de számításigényesebb.

JJN súlymátrix (normálva 48-ra):

           *  7  5
    3  5  7  5  3
    1  3  5  3  1

Stucki súlymátrix (normálva 42-re):

           *  8  4
    2  4  8  4  2
    1  2  4  2  1

A két algoritmus között a különbség inkább anyag- és sebességfüggő --
érdemes mindkettőt tesztelni azonos beállítások mellett.

### 3.5 Bayer (ordered dithering)

Az előző algoritmusoktól alapvetően különböző megközelítés. Nem
terjeszti a hibát, hanem egy előre definiált küszöbmátrixot
(Bayer-mátrix) alkalmaz: minden pixelre az adott pozícióhoz tartozó
küszöbértékkel hasonlítja a tónust.

Például 4×4-es Bayer-mátrix (normálva 0--255 tartományra):

      0 136  34 170
    102 238 136 204
     51 187  17 153
    153 119 221  85

Következmény: a pontminta szabályos rácsmintát alkot -- ez távolabbról
szürkeként látszik, de közelről felismerhető a rács. Gyors,
determinisztikus, reprodukálható. Olyan anyagokon hasznos, ahol a random
hibaeloszlású dither szétfolyik (pl. puha fa, textil).

### 3.6 Serpentine scan

Matematikai hatás: a hibakeresztező algoritmusoknál (Floyd--Steinberg,
JJN, Stucki) a hiba terjedési iránya is megfordul soronként. Ez
csökkenti a bal-jobb irányú mintázatosságot (streaking), amely egyirányú
feldolgozásnál megjelenhet. Bayer-nél nincs hatása, mert az nem
terjeszti a hibát.

------------------------------------------------------------------------

## 4. Tónusvezérlés: a sliderek hatásmechanizmusa

A feldolgozás előtt a program az eredeti képre egy tónuselőkészítési
lépést alkalmaz. A sliderek ezt a lépést vezérlik -- nem a bemeneti
pixelértékeket módosítják közvetlenül, hanem a feldolgozó pipeline
bemenetére ható transzformációkat.

### 4.1 Brightness (B)

Lineáris eltolás a tónusskálán. Minden pixelre:

    f' = clamp(f + b, 0, 255)

ahol b a brightness eltolás értéke (pozitív = világosítás). Egyenletes
hatás az egész tónustartományban. Ha az anyag rendszeresen túl mélyen
gravíroz (az egész kép sötét), a brightness emelése csökkenti a lézer
által érzékelt sötét tartomány arányát.

### 4.2 Contrast (C)

A tónus skálázása a középpont körül:

    f' = clamp((f - 128) × c + 128, 0, 255)

ahol c \> 1 növeli, c \< 1 csökkenti a kontrasztot. c = 1 esetén nincs
változás. A csúcsoknál (nagyon sötét és nagyon világos pixeleknél)
telítés következik be -- ezek elveszítik a részleteiket. Ez szándékos
viselkedés: a kontrasztemelés általában a középső tónusokat húzza szét,
a szélső értékeket feláldozva.

### 4.3 Gamma (G)

Nemlineáris transzformáció:

    f' = 255 × (f / 255) ^ (1/γ)

γ \> 1 esetén a középtónusok világosodnak (a görbe felfelé hajlik). γ \<
1 esetén sötétednek (a görbe lefelé hajlik). A fényes csúcsok és a
fekete árnyalatok alig változnak.

Gravírozásnál: a legtöbb anyag -- különösen a fa -- nemlineárisan reagál
a lézerexpozícióra. Amit 40% teljesítménynek gondolunk, az a felszínen
sokszor 70%-os mélységnek felel meg. A gamma csökkentésével
kompenzálhatjuk ezt a nemlinearitást: a kép előzetesen „előkompenzált"
tónust kap, és az anyag reakciója közelebb kerül a lineárishoz.

### 4.4 Radius (R) és Amount (A) -- élesítés

A program egy unsharp mask jellegű élesítést alkalmaz. Az elv:

1.  Az eredeti képből készül egy elmosott változat (Gauss-simítás, sugár
    = R pixel).

2.  A különbséget (eredeti - elmosott = él) az Amount értékkel súlyozva
    visszaadják az eredeti képhez:

    f' = f + A × (f - blur(f, R))

A Radius meghatározza, milyen méretű struktúrákra hat az élesítés. Kis
Radius (1-2): apró részleteket, szemcsézettséget erősít. Nagy Radius
(5-10): határozott éleket, kontúrokat emel ki.

Ha csak a Radius nagy, de az Amount kicsi: enyhe halo effekt, alig
észrevehető. Ha az Amount nagy, de a Radius kicsi: zajszerű textúra
kiemelés. A két paramétert mindig együtt kell értelmezni.

Fontos: az élesítés a dithering előtt fut. Ha túl erős, a dither
algoritmus a mesterségesen kiemelkedő éleket valós határokként kezeli,
és ott sűrűbb pontmintát generál. Fotóknál ez kellemetlen lehet,
szövegeknél és éles ábráknál előnyös.

------------------------------------------------------------------------

## 5. Geometriai transzformációk

### 5.1 Tükrözés

A vízszintes és függőleges tükrözés a raszter szintjén értelmezett
geometriai transzformáció. Nem a G-code koordinátáit forgatja -- magát a
képet tükrözi feldolgozás előtt.

Mikor szükséges: ha a gép Y tengelye fordítottan van bekötve, vagy a
gravírozást átlátszó anyagra (pl. akril) a hátsó oldalról végzik, és a
mintának az előlapról kell olvashatónak lennie.

### 5.2 Negative

Bitwise inverzió:

    f' = 255 - f

Anodizált alumíniumon a lézer eltávolítja az eloxált réteget -- ahol a
kép fekete lenne, ott lesz a fém ezüst. A negatív módban a program a
sötét és a világos területeket felcseréli, és a gravírozás eredménye az
eredeti kép pozitív képét adja vissza a felszínen.

------------------------------------------------------------------------

## 6. A feldolgozási pipeline sorrendje

A program a következő sorrendben alkalmazza a transzformációkat:

    1. Resample (forrás → célrács felbontás)
    2. Crop (ha aktív)
    3. Tükrözés (ha aktív)
    4. Brightness + Contrast + Gamma
    5. Unsharp mask (Radius + Amount)
    6. Negative (ha aktív)
    7. Dithering algoritmus
    8. Machine grid igazítás

Ez a sorrend nem véletlenszerű. A gamma és a kontraszt a dithering
bemeneti tónusát befolyásolja -- ha ezek a dithering után futnának, a
bináris képen már nincs mit tónusozni. Az élesítés szintén a dithering
előtt fut, mert utána a kép már csak fekete és fehér pontokból áll, és
az élek kiemelése értelmét veszti.

------------------------------------------------------------------------

## 7. A BASE kép és a G-code kapcsolata

A feldolgozás végeredménye a BASE kép: egy bináris raszter, amelynek
minden pixele pontosan egy lézer be/ki döntésnek felel meg. Ez az a kép,
amiből a G-code épül.

A G-code generátor a BASE képet soronként olvassa. Ahol a pixel fekete
(0), ott M3 S{power} parancs kerül a kódba a beállított Max power
értékkel. Ahol fehér (255), ott M5 vagy S0 szerepel. A gép X
koordinátája a pixelszélesség × fizikai lépésközzel (1/DPI hüvelykben)
növekszik soronként.

A sebesség és a teljesítmény egymástól nem független:

    Expozíció ∝ Power / Speed

Ha a sebességet megduplázod, azonos hatáshoz a teljesítményt is közel
meg kell duplázni. Az Auto mód ezt a kapcsolatot automatikusan kezeli az
anyag és a modul adataiból.

A Min power értéke a lézer minimális tüzelési szintje -- ezt akkor
használja a gép, amikor serpentine módban visszafelé megy, vagy a
sorforduló közeledtén lassít. Nullára állítva a lézer teljesen kialszik
ilyenkor, ami bizonyos anyagokon jobb, másokon rosszabb eredményt ad.

------------------------------------------------------------------------

## 8. Fullscreen előnézet -- amit érdemes ellenőrizni

A BASE nézet fullscreen módban az egyetlen megbízható módja annak, hogy
a tényleges gravírozási pontmintát még a gép előtt megítéljük.

Mit keress:

-   **Tónusátmenet konzisztenciája**: az árnyalatok fokozatosan mennek-e
    át egymásba, vagy vannak éles, lépcsős határok ahol nem kellene?

-   **Streaking**: vannak-e vízszintes csíkok vagy sávok? Ez általában a
    serpentine scan kikapcsolt állapotára és hibakeresztező algoritmus
    kombinációjára utal.

-   **Él-halo**: az éles kontúroknál megjelenik-e egy extra fehér vagy
    fekete szegély? Ez túl erős élesítésre utal.

-   **Túlkvantálás a sötét területeken**: a képlegmélyebb területei
    teljesen egybefolynak-e? Ha igen, csökkentsd a Brightness-t vagy a
    Gamma-t.

-   **Overscan terület**: a keret opció bekapcsolásával ellenőrizhető,
    hogy a generált G-code valóban a megadott fizikai területen belül
    marad-e, figyelembe véve az overscan-t.

------------------------------------------------------------------------

## 9. Praktikus összefüggések -- gyors referencia

    Vonalköz (mm) = 25,4 / DPI
    Sorok száma   = Magasság_mm × DPI / 25,4
    Overscan (mm) ≈ Speed² / (2 × xAccel)   [mm/s és mm/s² egységekben]
    Expozíció     ∝ Power / Speed
    Gamma korrekció: γ < 1 → sötétebb középtónusok, γ > 1 → világosabb

Ha egy anyagon a gravírozás következetesen túl mély, de a sebesség és a
teljesítmény látszólag helyes:

    1. Ellenőrizd a gamma értékét -- valószínűleg le kell vinni.
    2. Ellenőrizd a brightness értékét -- kissé emelni lehet.
    3. Ellenőrizd a DPI-t -- ha a vonalak átfednek, csökkenteni kell.

Ha a gravírozás halvány és részletszegény:

    1. Emeld a kontrasztot.
    2. Próbálj Floyd–Steinberg helyett Atkinson algoritmust.
    3. Ellenőrizd, hogy a Radius/Amount élesítés nem homályosítja-e
       el a finom részleteket (paradox módon a túl erős élesítés
       bizonyos dither algoritmusokkal elmosódást okoz).
