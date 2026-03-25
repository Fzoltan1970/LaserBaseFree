# LaserBase -- Felhasználói kézikönyv

Ez a kézikönyv a LaserBase program használatát mutatja be lépésről
lépésre. A szöveg egy műszaki hobbi felhasználónak szól: nem feltételez
fejlesztői ismereteket, de nem is próbál mindent túlzottan
leegyszerűsíteni.

A cél az, hogy megértsük: - hogyan készül egy gravírozás - hogyan
működik a program - hogyan lehet jó minőségű eredményt elérni

A fejezetek a valódi munkafolyamatot követik.

------------------------------------------------------------------------

# 1. Mi a LaserBase

A LaserBase egy lézergravírozó gépekhez készült program. Feladata, hogy
a gravírozás teljes folyamatát egyetlen környezetben kezelje.

A program négy fő részből áll:

• **Főablak** -- gravírozási paraméterek és anyagbeállítások tárolása\
• **Image Workspace** -- képek előkészítése gravírozáshoz\
• **Sender** -- a G-code elküldése a lézergépnek\
• **Sketch** -- egyszerű image-based processing tool

A LaserBase nem rajzprogram. A célja elsősorban az, hogy egy képből vagy
grafikából gravírozható program készüljön.

------------------------------------------------------------------------

# 2. A lézergravírozás alapjai

A lézergravírozó gép egy mozgó mechanika, amely egy fókuszált
lézersugárral dolgozik.

A lézer energiája az anyag felületét melegíti. Az anyag ennek hatására:

-   elszíneződik
-   elszenesedik
-   megolvad
-   vagy elpárolog

A legtöbb dióda lézer **raszter módban** dolgozik. Ez azt jelenti, hogy
a fej soronként pásztáz a felületen.

A lézer teljesítményét a vezérlő általában **PWM szabályzással**
állítja. Ez nem egyszerű be/ki kapcsolást jelent: a lézer teljesítménye
egy tartományon belül folyamatosan változtatható. A G-code S paramétere
ezt a skálát vezérli.

A gravírozott tónus három tényezőből áll össze:

1.  lézerteljesítmény (PWM)
2.  expozíciós idő (sebesség)
3.  pontsűrűség (dither raszter)

Ezek együtt határozzák meg az eredményt. A sebesség és a teljesítmény
között közvetlen összefüggés van:

    Expozíció ∝ Teljesítmény / Sebesség

Ha a sebességet megduplázod, azonos hatáshoz a teljesítményt is közel
meg kell duplázni.

------------------------------------------------------------------------

# 3. PWM és dithering -- két különböző módszer

A lézer PWM szabályzása önmagában képes szürkeárnyalatot előállítani.
Egy adott anyagon például 0% teljesítménynél nincs égés, 45%-nál
közép-szürke tónus keletkezik, 100%-nál a maximális sötétség. Ez valódi,
folytonos tónusszabályozás.

A **Min power** és **Max power** beállítások ezt a tartományt
definiálják. A program a képen lévő szürkeárnyalatokat erre a sávra
vetíti rá.

A PWM alapú szabályozás azonban nem mindig elég. Nagy sebességnél a PWM
ciklusok olyan gyorsan zajlanak le, hogy a modul nem tud teljesen
felkapcsolni és lekapcsolni -- az eredmény elmosódik. Emellett sok anyag
nemlineárisan reagál: kis teljesítménykülönbségek alig látható eltérést
okoznak, majd egy küszöb felett hirtelen mélyül az égés.

Ilyenkor a **dithering** stabilabb megoldás. A dithering nem a PWM
helyettesítője, hanem kiegészítője: a kép bináris pontmintává alakul, és
a pontsűrűség hozza létre a tónus illúzióját -- ugyanazon az elven,
ahogy az újságfotók is működnek.

A kettő kombinálható: a dither eldönti, hogy egy pixelpozíción ég-e a
lézer, de a „be" állapothoz rendelt tényleges teljesítmény még mindig a
Min/Max tartományból jön.

------------------------------------------------------------------------

# 4. Egy gravírozás teljes folyamata

A gyakorlatban egy gravírozás így készül:

1.  kép betöltése
2.  méret megadása
3.  DPI beállítása
4.  gépprofil kiválasztása
5.  képfeldolgozás
6.  előnézet ellenőrzése
7.  G-code generálása
8.  program elküldése a gépre

A LaserBase pontosan ezt a folyamatot követi.

------------------------------------------------------------------------

# 5. Image Workspace

Az Image Workspace a program legfontosabb része. Itt történik a kép
feldolgozása.

A munkaterület két fő részből áll:

bal oldal -- eredeti kép\
jobb oldal -- feldolgozott előnézet

A jobb oldali kép mutatja meg, hogyan fog kinézni a gravírozás.

------------------------------------------------------------------------

# 6. Kép betöltése

Kép betöltéséhez használjuk a **Load image** gombot.

Támogatott formátumok:

-   PNG
-   JPG / JPEG
-   BMP

A kép betöltése után azonnal megjelenik a bal oldali panelen. A program
ilyenkor elvégzi a kép RAW elemzését: megvizsgálja a felbontást, a
tónuseloszlást és a tartalmat. Ez az az alapállapot, amiből a
feldolgozás indul.

------------------------------------------------------------------------

# 6b. RAW és BASE kép

A program két különböző képállapotot használ.

**RAW kép**

A RAW kép az eredeti, feldolgozatlan kép. Ez az a kép, amelyet a fájlból
betöltöttünk. A feldolgozás minden lépése ebből indul ki.

**BASE kép**

A BASE kép a feldolgozott gravírozási raszter. Ez már a cél DPI
felbontására átméretezett, szűrt és dithering algoritmussal feldolgozott
kép.

A BASE kép bináris: minden pixelnél csak az dönt el, hogy a lézer
exponál-e vagy sem.

A G-code generálás mindig a BASE képből történik. A **Save image**
funkció ezt a BASE képet menti el.

------------------------------------------------------------------------

# 7. Méret beállítása

A kép méretét milliméterben adjuk meg.

A program a pixelméretből és a megadott fizikai méretből számolja ki a
gravírozás léptékét.

Példa:

Ha egy 1000 pixeles kép 100 mm széles, akkor a gravírozás során 10 pixel
jut 1 mm-re.

Ez az egyszerű arány az alap, de a pontos feldolgozási rács a DPI
értékkel együtt dől el.

------------------------------------------------------------------------

# 8. DPI

A DPI (dots per inch) határozza meg, milyen sűrűn haladnak egymás
mellett a sorok.

A vonalköz kiszámítható:

    vonalköz (mm) = 25,4 / DPI

Példák:

    254 DPI → kb. 0,1 mm vonalköz
    127 DPI → kb. 0,2 mm vonalköz

Nagyobb DPI több részletet ad, de lassabb gravírozást jelent. Túl nagy
DPI-nél a sorok átfedhetnek, ami túlégést okoz.

A program a forrásképet mindig átméretezi a célrács felbontására. Ez azt
jelenti, hogy a feldolgozott kép felbontása általában eltér az eredeti
képfájl felbontásától.

------------------------------------------------------------------------

# 9. Machine profile -- gépprofil

A Machine profile a gép fizikai paramétereit tartalmazza.

Tipikus adatok:

-   Rate -- maximális sebesség
-   Accel -- gyorsulás
-   Max -- munkaterület mérete
-   Scan axis -- pásztázás tengelye

Ezek az adatok nemcsak a G-code generáláshoz szükségesek, hanem az
**overscan** kiszámításához is.

Az overscan az a távolság, amennyit a fej a sor végén túlfut, hogy meg
tudjon állni és visszafordulni. Ha ez az érték túl kicsi, a gép a sor
elejét és végét még lassulás közben gravírozza -- az egyenetlen sebesség
egyenetlen expozíciót és torzult képet eredményez.

A program ezt az értéket automatikusan kiszámítja:

    Overscan (mm) ≈ Sebesség² / (2 × Gyorsulás)

A **Computed overscan** mező ezt az értéket mutatja. Nem érdemes kézzel
megbecsülni -- hagyd a programnak kiszámolni.

Ha van elmentett profilod, töltsd be a **Config betöltés** gombbal. Ha
még nincs, add meg a paramétereket és mentsd el.

------------------------------------------------------------------------

# 10. Crop

A Crop segítségével kivághatjuk a kép egy részét.

Ez hasznos például akkor, ha a képnek csak egy kis részét szeretnénk
gravírozni.

A kivágás lehet:

-   téglalap / négyzet
-   kör

Kör alakú kivágásnál a szélesség és a magasság értékeknek egyenlőnek
kell lenniük. Ha a crop terület érvénytelen, a Process gomb
automatikusan inaktívvá válik.

------------------------------------------------------------------------

# 11. Képfeldolgozás -- dithering

A dithering során a kép folytonos tónusai bináris pontmintává alakulnak.

Minden pixelnél a programnak egy egyszerű döntést kell hoznia:
égjen-e ott a lézer, vagy maradjon üres a pont.

A háttérben ez egy kvantálási probléma: egy folytonos
tónusértéket két állapot egyikére kell leképezni.

Ennek matematikai formája a következő. Ha egy pixel tónusértéke f,
a bináris döntés:

    q(f) = 0   ha f < küszöb    (lézer aktív)
    q(f) = 255 ha f ≥ küszöb   (lézer inaktív)

A keletkező hiba:

    e = f - q(f)

A különböző dither algoritmusok abban térnek el egymástól, hogy ezt a
hibát hogyan osztják szét a szomszédos pixelekre.

------------------------------------------------------------------------

# 12. Dither algoritmusok

**Floyd--Steinberg**\
A legelterjedtebb hibakeresztező algoritmus. A hibát négy szomszédra
osztja szét:

    jobb szomszéd:        e × 7/16
    bal alsó szomszéd:    e × 3/16
    alsó szomszéd:        e × 5/16
    jobb alsó szomszéd:   e × 1/16

Fotóknál, folyamatos tónusoknál általában ez a legjobb választás.

**Atkinson**\
A hiba csak 3/4-ét osztja szét hat szomszédra (egyenként 1/8 arányban),
a maradék 1/4 elvész. Élesebb kontrasztot ad, de a finom tónusátmenetek
pontossága csökken. Logókhoz, szöveghez, vonalas grafikákhoz jobb, mint
fotóhoz.

**JJN (Jarvis--Judice--Ninke) és Stucki**\
Mindkettő a Floyd--Steinberg elvét terjeszti ki két sorral mélyebbre.
Simább átmenetet adnak, de számításigényesebbek. Érdemes mindkettőt
tesztelni -- a különbség anyag- és sebességfüggő.

**Bayer**\
Alapvetően különböző megközelítés: nem terjeszti a hibát, hanem egy
előre definiált küszöbmátrixot alkalmaz. A pontminta szabályos rácsos
mintázatot alkot. Gyors, determinisztikus, reprodukálható. Olyan
anyagokon hasznos, ahol a hibakeresztező algoritmusok szétfolynak (pl.
puha fa, textil).

**Serpentine scan**\
Ez nem önálló dither mód, hanem kiegészítő kapcsoló. Ha aktív, minden
második sorban a feldolgozás jobbról balra halad. Hibakeresztező
algoritmusoknál (Floyd--Steinberg, JJN, Stucki) ez csökkenti a
vízszintes csíkosságot (streaking). Bayer-nél nincs hatása.

------------------------------------------------------------------------

# 13. Képi beállítások -- a sliderek

A sliderek a dithering előtt futnak le. Ez fontos: a bináris pontminta
elkészülte után a tónusokon már nem lehet változtatni.

**Brightness (B) -- fényerő**\
Lineáris eltolás a tónusskálán. Pozitív irányban világosít, negatívban
sötétít. Ha a gravírozás egészében túl mély, a brightness emelése segít.

**Contrast (C) -- kontraszt**\
A középérték körüli skálázás. Növelésével a sötét részek sötétebbek, a
világos részek világosabbak lesznek -- a szélső értékek telítődnek és
részleteket veszítenek. Ez szándékos viselkedés.

**Gamma (G) -- középtónus korrekció**\
Nemlineáris transzformáció: a középtónusokat állítja anélkül, hogy a
legsötétebb és legvilágosabb részeket érzékelhetően érintené.

    γ > 1 → világosabb középtónusok
    γ < 1 → sötétebb középtónusok

Különösen fontos fánál és más organikus anyagoknál, amelyek
nemlineárisan reagálnak a lézerre. Amit 40% teljesítménynek gondolunk,
az a felszínen sokszor 70%-os mélységnek felel meg. A gamma
csökkentésével ezt előre kompenzálhatjuk.

**Radius (R) és Amount (A) -- élesítés**\
A program unsharp mask jellegű élesítést alkalmaz. Az elv:

    f' = f + A × (f - blur(f, R))

A Radius meghatározza, mekkora területen keresi az éleket. Az Amount
megadja, mennyire hangsúlyozza azokat. A kettő együtt dolgozik:
önmagában egyik sem ad értelmes eredményt.

Kis Radius (1-2): apró részleteket, textúrát erősít.\
Nagy Radius (5-10): határozott kontúrokat emel ki.

Fontos: túl erős élesítésnél a dither a mesterséges éleket valós
határokként kezeli, és ott sűrűbb pontmintát generál. Fotóknál ez
kellemetlen lehet, szövegeknél és éles ábráknál előnyös.

------------------------------------------------------------------------

# 14. Egyéb képi opciók

**Negative**\
Megfordítja a kép tónusait: ami fekete volt, fehér lesz. Anodizált
alumíniumon a lézer eltávolítja az eloxált réteget -- negatív módban a
gravírozás eredménye az eredeti kép pozitív képét adja vissza a
felszínen.

**↔ vízszintes tükrözés és ↕ függőleges tükrözés**\
A képet geometriailag tükrözi feldolgozás előtt. Akkor szükséges, ha a
gép valamelyik tengelye fordítottan van bekötve, vagy ha átlátszó
anyagra (pl. akril) a hátsó oldalról gravírozunk.

------------------------------------------------------------------------

# 15. A feldolgozási pipeline sorrendje

A program a transzformációkat mindig ebben a sorrendben alkalmazza:

    1. Átméretezés (forrás → célrács felbontás)
    2. Crop (ha aktív)
    3. Tükrözés (ha aktív)
    4. Brightness + Contrast + Gamma
    5. Élesítés (Radius + Amount)
    6. Negative (ha aktív)
    7. Dithering algoritmus
    8. Machine grid igazítás

Ez a sorrend nem változtatható. A gamma és a kontraszt a dithering
bemenetét befolyásolja -- ha ezek utána futnának, a bináris képen már
nincs mit tónusozni. Az élesítés szintén a dithering előtt fut, mert
utána a kép már csak fekete és fehér pontokból áll.

------------------------------------------------------------------------

# 16. Előnézet

A feldolgozott kép a jobb oldali panelen látható.

A fullscreen mód sokkal jobban megmutatja a részleteket, mint a normál
nézet. Kicsiben sok minden jónak tűnik, ami közelről nem az.

Mit érdemes ellenőrizni fullscreen módban:

-   **Tónusátmenetek**: fokozatosak-e, vagy vannak éles, lépcsős
    határok?
-   **Streaking**: vannak-e vízszintes csíkok? Ez általában a serpentine
    scan kikapcsolt állapotára utal hibakeresztező algoritmusnál.
-   **Él-halo**: az éles kontúroknál megjelenik-e extra fehér vagy
    fekete szegély? Ez túl erős élesítésre utal.
-   **Túlkvantálás**: a legsötétebb területek teljesen egybefolynak-e?
    Ha igen, csökkentsd a Brightness-t vagy a Gamma-t.

Visszalépés fullscreenből: Esc.

------------------------------------------------------------------------

# 17. G-code generálás

A gravírozáshoz a program G-code fájlt készít.

A G-code egy parancslista, amely a gép mozgását és a lézer
teljesítményét vezérli sor-ról sorra, pixel-ről pixelre.

Példa:

    G1 X10 Y10
    M3 S800

A Save image gomb a feldolgozott BASE képet menti el -- azt a bináris
rasztert, amelyből a G-code épül. A G-code gomb maga a vezérlőfájlt
állítja elő, amit a Sender kap meg.

Ha a **Keret** opciót bekapcsolod, a program egy keretfájlt is generál.
Ez körberajzolja a gravírozás területét, így még a tényleges munka előtt
ellenőrizhető, hogy a minta pontosan hova kerül az anyagon.

------------------------------------------------------------------------

# 18. Sender

A Sender modul küldi el a G-code-ot a gépre. Külön ablakban fut, a
főablakból a Laser button nyitható meg.

A folyamat:

1.  port kiválasztása a listából
2.  Connect
3.  G-code betöltése
4.  állapot ellenőrzése (Idle/Ready)
5.  Start Send

A küldés közben:

-   **Pause / Resume** -- szüneteltetés és folytatás
-   **STOP** -- normál leállítás
-   **E-STOP** -- azonnali vészleállítás

Ha a gép Alarm állapotba kerül, a **\$X Unlock** gombbal oldható fel,
majd a küldés újraindítható.

Az alsó panelről elérhető a kézi tengelymozgatás (jog), a marker lézer
be/ki kapcsolása és terminálparancsok kézi küldése.

**Tipikus hibák:**

-   Nincs port a listában -- kattints Refresh-re, ellenőrizd a kábelt és
    a drivert.
-   Nem indul a küldés -- ellenőrizd, hogy be van-e töltve a fájl és
    él-e a kapcsolat.
-   Alarm állapot -- \$X Unlock, majd újra próbálkozás.

------------------------------------------------------------------------

# 18b. Keret (Frame)

A Keret funkció egy segédfájlt generál, amely körberajzolja a gravírozás
határát. Ezzel még a tényleges gravírozás előtt ellenőrizhető, hogy a
minta pontosan hova fog kerülni az anyagon.

Használata:

1.  generálj keretet
2.  küldd el a Senderrel
3.  figyeld meg a lézer mozgását

Ha a keret jó helyen fut, indítható a valódi gravírozás.

------------------------------------------------------------------------

# 18c. Kézi mozgatás (Jog)

A Sender alsó paneljén kézi tengelymozgatás is elérhető. Ezzel a
lézerfej pozíciója finoman állítható a gravírozás indítása előtt.

A lépések általában több méretben állíthatók (például 0,1 mm, 1 mm,
10 mm).

------------------------------------------------------------------------

# 18d. Marker lézer

A marker lézer egy alacsony teljesítményű segédfény. Bekapcsolásával
láthatóvá válik a fej pozíciója anélkül, hogy az anyag sérülne. Ez
különösen hasznos pozicionáláskor.

------------------------------------------------------------------------

# 19. Sketch

A Sketch egy egyszerű image-based processing tool.

Használható:

-   gyors vázlatok készítésére
-   gravírozási ötletek kipróbálására
-   egyszerű grafikák rajzolására

Külön ablakban fut, párhuzamosan használható a főablakkal.

------------------------------------------------------------------------

# 20. Gyakori hibák

Tipikus problémák és megoldásaik:

-   Nincs betöltött kép -- Load image gomb
-   Nincs gépprofil -- add meg vagy töltsd be a Config betöltés gombbal
-   Hibás crop terület -- rajzold újra, vagy kapcsold ki
-   Kör cropnál eltérő szélesség/magasság -- állítsd egyenlőre
-   G-code export hiba -- ellenőrizd a sebesség és teljesítmény mezőket

A legtöbb hiba az előnézet ellenőrzésével megelőzhető.

------------------------------------------------------------------------

# 21. Hasznos tanácsok

-   Új anyagon mindig készíts tesztgravírozást.
-   Ellenőrizd a pontmintát fullscreen módban G-code generálás előtt.
-   Az overscan értékét hagyd a programnak kiszámolni.
-   A Keret opcióval pozícionálj a tényleges munka előtt.
-   Fánál és organikus anyagoknál kísérletezz a gamma értékével.

A lézergravírozás mindig anyagfüggő folyamat. A tapasztalat legalább
olyan fontos, mint a beállítások.

------------------------------------------------------------------------

# 22. Gyors referencia

    Vonalköz (mm)  = 25,4 / DPI
    Sorok száma    = Magasság_mm × DPI / 25,4
    Overscan (mm)  ≈ Sebesség² / (2 × Gyorsulás)
    Expozíció      ∝ Teljesítmény / Sebesség

    Gamma:  γ > 1 → világosabb középtónusok
            γ < 1 → sötétebb középtónusok

    Ha a gravírozás túl mély:
        1. Csökkentsd a gamma értékét.
        2. Emeld a brightness értékét.
        3. Ellenőrizd, hogy a DPI-nél a sorok nem fedik-e át egymást.

    Ha a gravírozás halvány és részletszegény:
        1. Emeld a kontrasztot.
        2. Próbálj Atkinson algoritmust Floyd--Steinberg helyett.
        3. Ellenőrizd, hogy a Radius/Amount nem túl erős-e.
