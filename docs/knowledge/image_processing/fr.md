# LaserBase -- Traitement d’image (niveau atelier)

------------------------------------------------------------------------

## 1. Le modèle physique : ce qui se passe réellement

Un système de gravure laser est une machine à mouvement contrôlé basée
sur un balayage raster. La gravure se fait ligne par ligne : la tête se
déplace le long d’un axe pendant que la puissance du laser varie.

La plupart des contrôleurs de lasers à diode modernes utilisent une
régulation de puissance PWM (Pulse Width Modulation). Cela signifie que
la puissance du laser peut être ajustée de manière continue dans une
plage donnée — il ne s’agit pas simplement d’un état marche/arrêt.

Dans la pratique, la tonalité gravée résulte de la combinaison de trois
facteurs :

1. la puissance du laser (PWM)
2. le temps d’exposition — déterminé par la vitesse de déplacement
3. la densité spatiale des points (raster / dithering)

De nombreux matériaux ne réagissent pas de manière linéaire à la
puissance du laser. Pour cette raison, la restitution des tons est
souvent plus stable lorsque l’image est convertie en un motif de points
(dither), où la tonalité est produite par la densité des points.

Important : le dithering n’existe pas parce que le laser serait incapable
de fonctionner à différents niveaux de puissance. Le dithering est une
méthode de quantification qui produit souvent un résultat visuel plus
prévisible sur de nombreux matériaux.

L’objectif du traitement d’image est donc de générer un raster et un
profil de puissance qui reproduisent au mieux les tons de l’image
originale sur la surface du matériau, en tenant compte des paramètres
physiques de la machine et du comportement du matériau.

------------------------------------------------------------------------

## 2. Correspondance géométrique

### 2.1 Taille physique et grille de pixels

L’image d’entrée est une grille de W_px × H_px pixels. Par elle-même,
cette grille n’a pas de dimension physique. Le but de la gravure est de
couvrir une surface physique de W_mm × H_mm. La relation entre les deux
est définie par la valeur DPI.

Espacement réel des lignes :

    d = 25.4 mm / DPI

Par exemple, à 254 DPI :

    d = 0.1 mm

Cela signifie que des lignes parallèles couvrent la surface de gravure
tous les 0.1 mm.

Nombre de lignes :

    N_lines = H_mm / d
            = H_mm × DPI / 25.4

Nombre de colonnes par ligne :

    N_cols = W_mm × DPI / 25.4

Ces valeurs définissent la résolution raster réelle de l’image traitée,
qui diffère généralement de la résolution du fichier image d’origine.
Le programme rééchantillonne l’image source sur cette grille cible.

### 2.2 Pourquoi les paramètres machine sont importants

Les calculs précédents déterminent combien de lignes et de colonnes
doivent être générées. Cependant, la machine ne peut pas s’arrêter
instantanément. En raison de l’inertie de l’axe de balayage (généralement
l’axe X), la tête nécessite une distance de freinage et une distance de
retournement à la fin de chaque ligne.

La longueur minimale d’overscan découle de la physique du mouvement.

Si la vitesse de balayage est v (mm/s) et la décélération de l’axe est
a (mm/s²), la distance de freinage est :

    d_brake = v² / (2 × a)

Le programme calcule la valeur d’overscan à partir de cette relation en
utilisant les paramètres xRate et xAccel.

Si l’overscan est trop petit, la machine grave le début et la fin de la
ligne pendant l’accélération ou la décélération. Une vitesse irrégulière
entraîne une exposition irrégulière, visible comme une distorsion sur
les bords de l’image.

C’est pourquoi il ne faut pas estimer l’overscan manuellement. Le champ
**Computed overscan** affiche la valeur minimale sûre calculée à partir
des paramètres de la machine.

------------------------------------------------------------------------

## 3. Base mathématique du dithering

### 3.1 Erreur de quantification

Au niveau du dithering, chaque pixel produit une décision binaire :
le laser doit-il brûler à cet endroit ou non ?

Soit la valeur tonale d’un pixel :

    f ∈ [0,255]

où 0 est noir et 255 est blanc.

Décision binaire :

    q(f) = 0    si f < seuil      (laser actif)
    q(f) = 255  si f ≥ seuil      (laser inactif)

Erreur de quantification :

    e = f - q(f)

L’idée du dithering consiste à ne pas perdre cette erreur, mais à la
redistribuer aux pixels voisins afin que la moyenne des tons se
rapproche du ton original.

------------------------------------------------------------------------

### 3.2 FloydSteinberg
L’algorithme de diffusion d’erreur le plus répandu.

    voisin droit :         e × 7/16
    voisin bas-gauche :    e × 3/16
    voisin bas :           e × 5/16
    voisin bas-droit :     e × 1/16

------------------------------------------------------------------------

### 3.3 Atkinson

Algorithme classique du monde Apple Lisa / Macintosh. Seuls 3/4 de
l’erreur sont redistribués à six voisins (1/8 chacun). Le quart restant
est perdu.

Cela produit un contraste plus marqué, mais les transitions tonales
continues deviennent moins précises.

------------------------------------------------------------------------

### 3.4 JJN et Stucki

Ces algorithmes étendent le principe de Floyd–Steinberg. L’erreur est
distribuée non seulement à la ligne suivante, mais également deux lignes
plus bas.

------------------------------------------------------------------------

### 3.5 Bayer (dithering ordonné)

Approche différente : aucune diffusion d’erreur. Une matrice de seuil
prédéfinie est utilisée (matrice de Bayer).

Le motif de points forme une grille régulière.

Avantages :

- rapide
- déterministe
- reproductible

------------------------------------------------------------------------

### 3.6 Serpentine scan

Cela réduit les motifs directionnels dans certains algorithmes de
diffusion d’erreur.

------------------------------------------------------------------------

## 4. Contrôle des tons : fonctionnement des curseurs

Avant le dithering, le programme applique une étape de préparation des
tons.

### 4.1 Brightness (B)

Décalage linéaire :

    f' = clamp(f + b, 0, 255)

------------------------------------------------------------------------

### 4.2 Contrast (C)

Mise à l’échelle autour du point médian :

    f' = clamp((f - 128) × c + 128, 0, 255)

------------------------------------------------------------------------

### 4.3 Gamma (G)

Transformation non linéaire :

    f' = 255 × (f / 255) ^ (1/γ)

------------------------------------------------------------------------

### 4.4 Radius (R) et Amount (A)

Accentuation de type unsharp mask :

    f' = f + A × (f - blur(f, R))

------------------------------------------------------------------------

## 5. Transformations géométriques

### 5.1 Miroir

Miroir horizontal ou vertical de l’image avant le traitement.

------------------------------------------------------------------------

### 5.2 Negative

Inversion des tons :

    f' = 255 - f

------------------------------------------------------------------------

## 6. Ordre du pipeline de traitement

    1. Resample
    2. Crop
    3. Mirror
    4. Brightness + Contrast + Gamma
    5. Unsharp mask
    6. Negative
    7. Dithering
    8. Alignement de la grille machine

------------------------------------------------------------------------

## 7. Relation entre l’image BASE et le G-code

Le résultat final du traitement est l’image **BASE**, un raster binaire.
Chaque pixel correspond à une décision laser ON/OFF.

Relation exposition :

    Exposition ∝ Puissance / Vitesse

------------------------------------------------------------------------

## 8. Aperçu plein écran

La vue BASE en plein écran est la méthode la plus fiable pour juger du
motif réel avant la gravure.

------------------------------------------------------------------------

## 9. Référence rapide

    Espacement ligne (mm) = 25.4 / DPI
    Nombre de lignes      = Hauteur_mm × DPI / 25.4
    Overscan (mm)         ≈ Speed² / (2 × xAccel)
    Exposition            ∝ Power / Speed
