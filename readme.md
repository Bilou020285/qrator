# QRator -- Guide Utilisateur

## Présentation

**QRator** est un plugin QGIS conçu pour :
- **Analyser** un projet QGIS existant (`.qgs` ou `.qgz`),
- **Explorer** les couches, thèmes, mises en page et relations,
- **Sélectionner** une partie du projet (couches, styles, thèmes,
layouts, relations),
- **Exporter** soit :
- un **rapport HTML interactif** du projet,
- un **nouveau projet QGIS filtré** (avec seulement les éléments
choisis).

📦 Développé par **Collectif Ramen, Inrap, Copilot, Mistral AI et ChatGPT5**.

------------------------------------------------------------------------

## Installation & lancement

1.  Installer le plugin dans le dossier QGIS habituel.
2.  Relancer QGIS.
3.  Le plugin est accessible depuis :
    -   Le menu **Extensions → QRator → Lancer QRator**,
    -   La **barre d'outils** (icône du plugin).

------------------------------------------------------------------------

## Interface générale

La fenêtre principale comporte plusieurs sections :

-   **Barre de boutons** (haut de la fenêtre)
    -   📂 *Open Project* : ouvrir un projet `.qgs` ou `.qgz`
    -   💾 *Save Filtered Project* : enregistrer un nouveau projet
        filtré. Si le projet existe déjà, il est possible d'écraser le projet ou de fusionner les réglages de QRator avec le projet existant
    -   🔄 *Refresh* : relancer l'analyse
    -   📑 *Export HTML Report* : générer un rapport HTML interactif
    -   📂 *Browse Output* : définir le chemin de sauvegarde du projet
        filtré
    -   ❌ *Close* : fermer le plugin
-   **Onglets principaux** :
    1.  **Couches (Layers)**
    2.  **Thèmes (Themes)**
    3.  **Mises en page (Layouts)**
    4.  **Relations (Relations)**
-   **Zone de résultats / résumé** : affiche un diagnostic rapide du
    projet (chemin, nombre de couches, CRS, extent, etc.).

------------------------------------------------------------------------

## Onglet **Couches**

-   Affiche l'arborescence des **couches et groupes** du projet.
-   Chaque couche peut contenir un ou plusieurs **styles**.
-   ✅ Cases à cocher pour sélectionner :
    -   les groupes,
    -   les couches,
    -   les styles.

🔧 **Menus contextuels** (clic droit sur une couche ou style) :
- Exporter un style en **.QML**,
- Copier un style dans le presse-papiers,
- Appliquer un style à la couche active du projet QGIS.

------------------------------------------------------------------------

## Onglet **Thèmes**

-   Affiche les **thèmes de visibilité** définis dans le projet.
-   Arborescence :
    -   Thème → Couches → Styles
-   ✅ Cases à cocher pour inclure certains thèmes et leurs variantes de
    styles.

💡 Les couches cochées ici sont automatiquement prises en compte dans
les sélections globales.

------------------------------------------------------------------------

## Onglet **Mises en page**

-   Liste toutes les **mises en page** (layouts) du projet (cartes,
    rapports, compositions imprimées).
-   ✅ Cases à cocher pour inclure certaines mises en page dans
    l'export.

🔧 **Menus contextuels** (clic droit) :
- Exporter une mise en page sélectionnée en **PDF** ou **PNG (300
dpi)**,
- Exporter plusieurs mises en page cochées en lot.

------------------------------------------------------------------------

## Onglet **Relations**

-   Affiche les **relations entre tables** (références parent/enfant).
-   Arborescence :
    -   Relation → (parent) couche → champ
        → (child) couche → champ
-   ✅ Cases à cocher pour sélectionner des relations.
-   ⚡ Auto-sélection : si les deux couches liées sont cochées, la
    relation est automatiquement activée.

------------------------------------------------------------------------

## Onglet **Dépendances**

-   Pour chaque mise en page : remonte tout ce qu'elle utilise — thèmes
    référencés par ses cartes (et les couches/styles de ces thèmes),
    couche de couverture de l'atlas, tableaux attributaires placés dans
    la mise en page — en suivant récursivement les jointures QGIS.
-   Pour les couches SpatiaLite/GeoPackage dont la source est une requête
    SQL ou une vue de la base, QRator tente de retrouver les tables
    référencées (SQL déjà présent dans le projet, ou lecture du fichier
    `.sqlite`/`.gpkg` en lecture seule s'il est accessible au chemin
    enregistré — sinon, la couche est simplement signalée comme "non
    résolue" plutôt que de bloquer l'analyse).
-   Arbre **informatif** (non cochable) ; le bouton **"Sélectionner ces
    dépendances"** coche, dans les onglets Couches/Thèmes/Mises en page,
    tout ce que la mise en page sélectionnée utilise — prêt à exporter.
-   ⚠️ Limité au SpatiaLite/GeoPackage local (pas de PostgreSQL/PostGIS) ;
    extraction des tables référencées par expression régulière, pas un
    vrai parseur SQL.

------------------------------------------------------------------------

## Exports disponibles

### 1. Rapport HTML

-   Contient :
    -   Résumé (nombre de couches, thèmes, layouts, relations),
    -   Carte interactive (Leaflet) avec l'emprise du projet,
    -   Arborescences interactives (couches, thèmes, relations,
        dépendances par mise en page),
    -   Informations détaillées (chemin des couches, CRS, etc.).

🎨 Interface moderne et interactive (expand/collapse, icônes de
sélection).

### 2. Nouveau projet filtré (.qgz)

-   Enregistre un projet QGIS allégé :
    -   seules les couches, styles, thèmes, mises en page et relations
        cochées sont conservées,
    -   les autres sont supprimées du XML.
-   Idéal pour partager un **sous-projet** à un collègue ou pour alléger
    un projet complexe.
-   Si le fichier du projet existe déjà, QRator peut fusionner les paramètres du projet existant avec ceux sélectionnés dans le plugin

### 3. Déconnection aux données locales

La case à cocher **Déconnecter les sources de données locales** permet de générer un nouveau projet avec des sources différentes du projet d'origine.
À l'ouverture du projet créé par QRator, QGIS signalera les sources de données manquantes qu'il suffira alors de réadresser.

------------------------------------------------------------------------

## Bonnes pratiques

-   Toujours ouvrir un projet **.qgz** ou **.qgs** sauvegardé
    récemment.
-   Sélectionner au moins **une couche** avant l'export.
-   Vérifier les styles : certains projets peuvent avoir des styles
    "default" et "défaut".
-   Pour partager un sous-projet avec un collègue → préférer l'export
    **projet filtré**.
-   Pour archiver ou documenter → préférer le **rapport HTML**.

------------------------------------------------------------------------

## Contacts & support

-   **Auteur** : Collectif Ramen
-   📧 Email : collectif.ramen@inrap.fr

------------------------------------------------------------------------

# QRator -- User Guide

## Overview

**QRator** is a QGIS plugin designed to:
- **Analyze** an existing QGIS project (`.qgs` or `.qgz`),
- **Explore** layers, themes, layouts and relations,
- **Select** only part of the project (layers, styles, themes, layouts,
relations),
- **Export** either:
- an **interactive HTML report** of the project,
- or a **filtered QGIS project** (with only the selected items).

📦 Developed by **Collectif Ramen, Inrap, Copilot, Mistral AI, ChatGPT5**.

------------------------------------------------------------------------

## Installation & Launch

1.  Install the plugin in the usual QGIS plugin folder.
2.  Restart QGIS.
3.  Access the plugin from:
    -   The menu **Plugins → QRator → Launch QRator**,
    -   Or the **toolbar icon** (QRator logo).

------------------------------------------------------------------------

## General Interface

The main window contains several parts:

-   **Toolbar buttons** (top of the window)
    -   📂 *Open Project* : open a `.qgs` or `.qgz` project
    -   💾 *Save Filtered Project* : save a new filtered project or merge an existing project with selected settings in QRator
    -   🔄 *Refresh* : reload the project analysis
    -   📑 *Export HTML Report* : generate an interactive HTML report
    -   📂 *Browse Output* : choose where to save the filtered project
    -   ❌ *Close* : close the plugin
-   **Main tabs**:
    1.  **Layers**
    2.  **Themes**
    3.  **Layouts**
    4.  **Relations**
-   **Summary / Results area** : displays a quick analysis of the
    project (path, layer count, CRS, extent, etc.).

------------------------------------------------------------------------

## **Layers** tab

-   Displays the tree structure of **layers and groups** in the
    project.
-   Each layer may have one or more **styles**.
-   ✅ Checkboxes let you select:
    -   groups,
    -   layers,
    -   styles.

🔧 **Context menu** (right-click on a layer or style):
- Export a style as **.QML**,
- Copy a style to the clipboard,
- Apply a style to the active layer in QGIS.

------------------------------------------------------------------------

## **Themes** tab

-   Displays **visibility presets (themes)** defined in the project.
-   Tree structure:
    -   Theme → Layers → Styles
-   ✅ Checkboxes to include certain themes and their styles.

💡 Layers checked here are also considered in the global selections.

------------------------------------------------------------------------

## **Layouts** tab

-   Lists all project **layouts** (maps, reports, print compositions).
-   ✅ Checkboxes to include specific layouts in the export.

🔧 **Context menu** (right-click):
- Export a selected layout as **PDF** or **PNG (300 dpi)**,
- Export multiple checked layouts in batch.

------------------------------------------------------------------------

## **Relations** tab

-   Displays **relations between tables** (parent/child links).
-   Tree structure:
    -   Relation → (parent) layer → field
        → (child) layer → field
-   ✅ Checkboxes to include relations.
-   ⚡ Auto-selection: if both related layers are checked, the relation
    is automatically activated.

------------------------------------------------------------------------

## **Dependencies** tab

-   For each layout: traces everything it uses — themes referenced by
    its maps (and the layers/styles of those themes), the atlas coverage
    layer, attribute tables placed on the layout — following QGIS joins
    recursively.
-   For SpatiaLite/GeoPackage layers backed by a SQL query or a database
    view, QRator tries to resolve the tables involved (SQL already
    present in the project, or a read-only read of the `.sqlite`/`.gpkg`
    file if reachable at its recorded path — otherwise the layer is
    simply flagged "unresolved" rather than blocking the analysis).
-   **Informational** tree (not checkable); the **"Select these
    dependencies"** button checks, in the Layers/Themes/Layouts tabs,
    everything the selected layout uses — ready to export.
-   ⚠️ Limited to local SpatiaLite/GeoPackage (no PostgreSQL/PostGIS);
    referenced tables are extracted with a regular expression, not a
    real SQL parser.

------------------------------------------------------------------------

## Export Options

### 1. HTML Report

-   Contains:
    -   Summary (number of layers, themes, layouts, relations),
    -   Interactive map (Leaflet) showing the project extent,
    -   Interactive trees (layers, themes, relations, per-layout
        dependencies),
    -   Detailed info (layer path, CRS, etc.).

🎨 Modern interactive interface (expand/collapse, selection icons).

### 2. Filtered Project (.qgz)

-   Saves a lighter QGIS project containing only:
    -   the selected layers, styles, themes, layouts and relations,
    -   all other elements are removed from the XML.
-   Perfect for sharing a **subproject** with colleagues or lightening
    complex projects.
-   If the project file already exists, QRator can merge the existing project settings with those selected in the plugin

### 3. Disconnecting local data

The **Disconnect local data sources** checkbox allows you to generate a new project with different sources from the original project.
When you open the project created by QRator, QGIS will flag any missing data sources, which you can then simply re-address.

------------------------------------------------------------------------

## Best Practices

-   Always open a **recently saved** `.qgz` or `.qgs` project.
-   Select at least **one layer** before exporting.
-   Double-check style names: some projects may contain both "default"
    and "défaut".
-   For sharing with colleagues → use **Filtered Project Export**.
-   For archiving or documentation → use the **HTML Report**.

------------------------------------------------------------------------

## Contacts & Support

-   **Authors**: Collectif Ramen, Inrap
-   📧 Email: collectif.ramen@inrap.fr
