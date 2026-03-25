# LaserBase -- Manuel d’utilisation

Ce manuel explique étape par étape l’utilisation du programme LaserBase. Le texte est écrit pour un utilisateur technique amateur : il ne suppose pas de connaissances de développeur, mais il ne cherche pas non plus à simplifier excessivement les choses.

L’objectif est de comprendre :
- comment une gravure est réalisée
- comment fonctionne le programme
- comment obtenir un résultat de bonne qualité

Les chapitres suivent le flux de travail réel.

------------------------------------------------------------------------

# 1. Qu’est-ce que LaserBase

LaserBase est un programme conçu pour les machines de gravure laser. Son objectif est de gérer l’ensemble du processus de gravure dans un seul environnement.

Le programme comporte quatre parties principales :

• **Fenêtre principale** — stockage des paramètres de gravure et des réglages de matériaux  
• **Image Workspace** — préparation des images pour la gravure  
• **Sender** — envoi du G-code à la machine laser  
• **Sketch** — une surface de dessin simple

LaserBase n’est pas un programme de dessin. Son objectif principal est de créer un programme de gravure à partir d’une image ou d’un graphique.

------------------------------------------------------------------------

# 2. Bases de la gravure laser

Une machine de gravure laser est un mécanisme mobile qui fonctionne avec un faisceau laser focalisé.

L’énergie du laser chauffe la surface du matériau. En conséquence, le matériau :

- change de couleur
- se carbonise
- fond
- ou s’évapore

La plupart des lasers à diode fonctionnent en **mode raster**. Cela signifie que la tête balaie la surface ligne par ligne.

La puissance du laser est généralement contrôlée par le contrôleur à l’aide d’une **régulation PWM**. Cela ne signifie pas un simple interrupteur marche/arrêt : la puissance du laser peut être variée continuellement dans une plage donnée. Le paramètre `S` du G-code contrôle cette échelle.

Le ton gravé est déterminé par trois facteurs :

1. la puissance du laser (PWM)
2. le temps d’exposition (vitesse)
3. la densité des points (raster de dithering)

Ensemble, ils déterminent le résultat. Il existe une relation directe entre la vitesse et la puissance :

    Exposition ∝ Puissance / Vitesse

Si vous doublez la vitesse, vous devrez presque doubler la puissance pour obtenir le même effet.

------------------------------------------------------------------------

# 3. PWM et dithering — deux méthodes différentes

Le contrôle PWM du laser est déjà capable de produire des niveaux de gris. Sur un matériau donné, par exemple, à 0 % de puissance il n’y a pas de brûlure, à 45 % un gris moyen apparaît, et à 100 % on obtient l’obscurité maximale.

Les paramètres **Min power** et **Max power** définissent cette plage. Le programme associe les valeurs de gris de l’image à cet intervalle.

Cependant, le contrôle basé sur PWM n’est pas toujours suffisant. À grande vitesse, les cycles PWM sont si rapides que le module ne peut pas s’allumer et s’éteindre complètement — le résultat devient flou. De plus, de nombreux matériaux réagissent de manière non linéaire : de petites différences de puissance produisent peu d’effet visible, puis au-delà d’un certain seuil la brûlure devient soudainement beaucoup plus forte.

Dans ces cas, le **dithering** est une solution plus stable. Le dithering ne remplace pas le PWM, mais le complète : l’image est convertie en un motif de points binaires, et la densité des points crée l’illusion de tonalité — le même principe que dans les photos de journaux.

Les deux méthodes peuvent être combinées : le dithering détermine si le laser doit brûler à un pixel donné, mais la puissance réelle de l’état « actif » provient toujours de la plage Min/Max.

------------------------------------------------------------------------

# 4. Flux de travail complet d’une gravure

En pratique, une gravure se fait ainsi :

1. charger l’image
2. définir la taille
3. définir le DPI
4. sélectionner le profil de machine
5. traiter l’image
6. vérifier l’aperçu
7. générer le G-code
8. envoyer le programme à la machine

LaserBase suit exactement ce processus.

------------------------------------------------------------------------

# 5. Image Workspace

L’Image Workspace est la partie la plus importante du programme. C’est là que se déroule le traitement de l’image.

L’espace de travail comporte deux parties principales :

gauche — image originale  
droite — aperçu traité

L’image de droite montre à quoi ressemblera la gravure.

------------------------------------------------------------------------

# 6. Chargement d’une image

Pour charger une image, utilisez le bouton **Load image**.

Formats supportés :

- PNG
- JPG / JPEG
- BMP

Après le chargement, l’image apparaît immédiatement dans le panneau de gauche. À ce moment-là, le programme effectue une analyse RAW : il examine la résolution, la distribution des tons et le contenu.

------------------------------------------------------------------------

# 6b. Image RAW et BASE

Le programme utilise deux états d’image.

**Image RAW**

L’image RAW est l’image originale non traitée. Toutes les étapes de traitement commencent à partir de celle-ci.

**Image BASE**

L’image BASE est le raster de gravure traité. Elle a déjà été redimensionnée à la résolution DPI cible et traitée par l’algorithme de dithering.

L’image BASE est binaire : pour chaque pixel, elle indique seulement si le laser doit exposer ou non.

Le G-code est toujours généré à partir de l’image BASE.

------------------------------------------------------------------------

# 7. Définition de la taille

La taille de l’image est définie en millimètres.

Le programme calcule l’échelle de gravure à partir du nombre de pixels et de la taille physique.

Exemple :

si une image de 1000 pixels fait 100 mm de large, alors 10 pixels correspondent à 1 mm.

------------------------------------------------------------------------

# 8. DPI

DPI (dots per inch) détermine la densité des lignes.

    espacement des lignes (mm) = 25.4 / DPI

Exemples :

    254 DPI → env. 0.1 mm
    127 DPI → env. 0.2 mm

Un DPI plus élevé donne plus de détails, mais ralentit la gravure.

------------------------------------------------------------------------

# 9. Profil de machine

Le profil de machine contient les paramètres physiques :

- Rate — vitesse maximale
- Accel — accélération
- Max — dimensions de la zone de travail
- Scan axis — axe de balayage

Ces valeurs servent aussi à calculer l’**overscan**.

    Overscan (mm) ≈ Speed² / (2 × Acceleration)

Le champ **Computed overscan** affiche cette valeur.

------------------------------------------------------------------------

# 10. Crop

La fonction Crop permet de découper une partie de l’image.

Formes possibles :

- rectangle
- cercle

------------------------------------------------------------------------

# 11. Traitement de l’image — dithering

Lors du dithering, les tons continus sont convertis en un motif de points binaires.

Pour chaque pixel :

    q(f) = 0   si f < seuil
    q(f) = 255 si f ≥ seuil

Erreur :

    e = f - q(f)

------------------------------------------------------------------------

# 12. Algorithmes de dithering

**Floyd–Steinberg**

    droite : e × 7/16
    bas-gauche : e × 3/16
    bas : e × 5/16
    bas-droite : e × 1/16

**Atkinson**

Distribue seulement 3/4 de l’erreur.

**JJN / Stucki**

Version étendue de Floyd-Steinberg.

**Bayer**

Matrice de seuil fixe.

**Serpentine scan**

Traitement en zigzag.

------------------------------------------------------------------------

# 13. Réglages de l’image

**Brightness**

Décalage linéaire.

**Contrast**

Amplifie les différences.

**Gamma**

Transformation non linéaire.

    γ > 1 → tons moyens plus clairs
    γ < 1 → tons moyens plus foncés

**Radius / Amount**

Accentuation (unsharp mask).

------------------------------------------------------------------------

# 14. Autres options

**Negative**

Inverse les tons.

**Mirror**

Miroir horizontal ou vertical.

------------------------------------------------------------------------

# 15. Ordre du pipeline

    1. Resize
    2. Crop
    3. Mirror
    4. Brightness + Contrast + Gamma
    5. Sharpen
    6. Negative
    7. Dither
    8. Grid alignment

------------------------------------------------------------------------

# 16. Aperçu

Le panneau de droite montre l’image finale.

Mode plein écran recommandé pour vérifier :

- transitions de tons
- bandes horizontales
- halo sur les contours
- zones saturées

------------------------------------------------------------------------

# 17. Génération du G-code

Le programme crée un fichier G-code.

Exemple :

    G1 X10 Y10
    M3 S800

------------------------------------------------------------------------

# 18. Sender

Sender envoie le G-code à la machine.

Processus :

1. sélectionner le port
2. Connect
3. charger le G-code
4. vérifier l’état
5. Start Send

------------------------------------------------------------------------

# 19. Sketch

image-based processing tool pour :

- croquis rapides
- tests
- petits graphiques

------------------------------------------------------------------------

# 20. Erreurs courantes

- image non chargée
- profil de machine absent
- crop invalide
- erreur G-code

------------------------------------------------------------------------

# 21. Conseils

- faire un test sur chaque nouveau matériau
- sauvegarder les paramètres
- vérifier l’aperçu en plein écran

------------------------------------------------------------------------

# 22. Rappel rapide

    espacement ligne = 25.4 / DPI
    Overscan ≈ Speed² / (2 × Acceleration)
    Exposition ∝ Puissance / Vitesse