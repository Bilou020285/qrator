# qrator/qgz_manager.py
import os
import tempfile
import zipfile
import copy
import re
from typing import Dict, Set, DefaultDict, Tuple, Iterable
from collections import defaultdict
from lxml import etree

# =========================
# Helpers XML (namespace-agnostiques)
# =========================

def _localname(tag: str) -> str:
    """Retourne le nom local en minuscules, sans namespace."""
    return tag.rsplit('}', 1)[-1].lower() if tag else ""

def filter_layouts_in_xml(xml_root, selected_layout_names):
    """
    Ne garder que les mises en page dont le nom est dans 'selected_layout_names'.
    Gère :
      - <Layouts> / <layouts> contenant des <Layout> / <layout>
      - <Layout> / <layout> directement sous la racine <qgis>
      - Namespaces éventuels
    Compatible xml.etree.ElementTree (pas besoin de getparent()).
    """
    if xml_root is None:
        return
    selected = set(selected_layout_names or [])

    # 1) Cas: <Layout>/<layout> directement sous la racine <qgis>
    #    → on supprime les enfants non sélectionnés en itérant sur une copie (list(...))
    for child in list(xml_root):
        if _localname(child.tag) == "layout":
            name = (child.get("name") or "").strip()
            if not selected or name not in selected:
                xml_root.remove(child)

    # 2) Cas: conteneurs <Layouts>/<layouts> n'importe où dans l'arbre
    #    → on passe en revue TOUT l'arbre et on nettoie les enfants layout non sélectionnés
    #    Note: avec ElementTree, pas d'XPath avancé, donc on itère et on teste le localname
    for elem in xml_root.iter():
        if _localname(elem.tag) in ("layouts",):
            # Supprime les enfants <Layout>/<layout> non sélectionnés
            for lay in list(elem):
                if _localname(lay.tag) == "layout":
                    name = (lay.get("name") or "").strip()
                    if not selected or name not in selected:
                        elem.remove(lay)
            # On laisse intacts d'éventuels nœuds de préférences (ex: lastLayoutExportDir)

def _first(elem: etree._Element, xp: str) -> etree._Element:
    r = elem.xpath(xp)
    return r[0] if r else None

def _all(elem: etree._Element, xp: str) -> Iterable[etree._Element]:
    return elem.xpath(xp)

# =========================
# Ouverture / lecture projet
# =========================

def open_project(file_path: str):
    """Ouvre un projet QGIS (.qgs ou .qgz) et renvoie (xml_root, meta)."""
    if file_path.endswith(".qgz"):
        with zipfile.ZipFile(file_path, "r") as qgz:
            qgs_name = next((n for n in qgz.namelist() if n.endswith(".qgs")), None)
            if not qgs_name:
                raise FileNotFoundError("No .qgs in .qgz")
            with qgz.open(qgs_name) as qgs:
                xml_bytes = qgs.read()
    else:
        with open(file_path, "rb") as f:
            xml_bytes = f.read()
    root = etree.fromstring(xml_bytes)
    return root, {}

# =========================
# Collecte & parsing d'identifiants
# =========================

def _collect_known_layer_ids(xml_root: etree._Element) -> Set[str]:
    """Récupère tous les IDs de couches réellement présents dans le projet."""
    ids = set()
    for ml in _all(xml_root, ".//*[local-name()='maplayer']"):
        lid = ml.findtext("id", "")
        if lid:
            ids.add(lid)
    pl = _first(xml_root, ".//*[local-name()='projectlayers']")
    if pl is not None:
        for lyr in pl:
            lid = lyr.findtext("id", "")
            if lid:
                ids.add(lid)
    return ids

def _layer_source_key(maplayer: etree._Element) -> str:
    """
    Construit une « clé » stable pour une couche à partir de :
      - provider
      - datasource
      - subsetstring (filtre SQL éventuel)

    Deux couches appartenant à des projets différents mais pointant vers la
    même source auront la même clé, même si leurs IDs internes QGIS diffèrent.
    """
    if maplayer is None:
        return ""

    ds = maplayer.findtext("datasource", "") or ""
    prov = maplayer.findtext("provider", "") or ""
    subset = maplayer.findtext("subsetstring", "") or ""

    key = f"{prov.strip().lower()}||{ds.strip()}||{subset.strip()}"
    # On enlève les séparateurs superflus si tout est vide
    return key.strip("|")

def _parse_token_theme_layer(token: str, known_ids: Set[str]) -> Tuple[str, str]:
    """
    Retourne (theme, layer_id) depuis un token 'theme|layer_id'.
    Tolérance : si pas de '|', tente de retrouver layer_id connu dans la chaîne (format legacy à base de '_').
    """
    if "|" in token:
        theme, layer_id = token.split("|", 1)
        return theme, layer_id
    # Fallback legacy: retrouver le plus long id connu contenu dans le token
    lid = _extract_known_id(token, known_ids)
    th, _ = _split_theme_and_style_from_token(token, lid)
    return th, lid

def _parse_token_theme_style(token: str, known_ids: Set[str]) -> Tuple[str, str, str]:
    """
    Retourne (theme, layer_id, style) depuis 'theme|layer_id|style'.
    Tolérance legacy (underscores) si nécessaire.
    """
    if "|" in token:
        parts = token.split("|")
        if len(parts) >= 3:
            return parts[0], parts[1], "|".join(parts[2:])  # style peut contenir des '|'
    # Fallback legacy
    lid = _extract_known_id(token, known_ids)
    th, style = _split_theme_and_style_from_token(token, lid)
    return th, lid, style

def _parse_token_style(token: str, known_ids: Set[str]) -> Tuple[str, str]:
    """
    Retourne (layer_id, style) depuis 'layer_id|style', avec fallback legacy.
    """
    if "|" in token:
        layer_id, style = token.split("|", 1)
        return layer_id, style
    lid = _extract_known_id(token, known_ids)
    _, style = _split_theme_and_style_from_token(token, lid)
    return lid, style

def _extract_known_id(token: str, known_ids: Set[str]) -> str:
    """Trouve l'ID de couche en cherchant le plus LONG ID connu contenu dans 'token'."""
    hit = ""
    for kid in known_ids:
        pos = token.rfind(kid)
        if pos != -1 and len(kid) > len(hit):
            hit = kid
    return hit

def _split_theme_and_style_from_token(token: str, layer_id: str) -> Tuple[str, str]:
    """
    Déduit (theme_prefix, style_suffix) autour d'un layer_id présent dans token.
    Compatible avec anciens formats 'theme_layerid_style' où theme/style contiennent des underscores.
    """
    if not layer_id:
        return "", ""
    pos = token.find(layer_id)
    if pos == -1:
        return "", ""
    prefix = token[:pos].rstrip("_|")
    suffix = token[pos + len(layer_id):].lstrip("_|")
    return prefix, suffix  # (theme, style)

# =========================
# Filtrage principal
# =========================

def filter_project_xml(xml_root: etree._Element, selected: Dict) -> etree._Element:
    """
    Applique le filtrage du projet selon les sélections issues de TOUS les onglets.
    Attend des tokens avec '|' (contrat), mais reste tolérant aux anciens formats.
    """
    root = copy.deepcopy(xml_root)

    # Sélections issues de l'UI
    sel_layers       = set(selected.get("layers", set()))
    sel_groups       = set(selected.get("layer_groups", set()))
    sel_styles       = set(selected.get("styles", set()))               # "layer_id|style"
    sel_themes       = set(selected.get("themes", set()))               # "theme"
    sel_theme_layers = set(selected.get("theme_layers", set()))         # "theme|layer_id"
    sel_theme_styles = set(selected.get("theme_styles", set()))         # "theme|layer_id|style"
    sel_layouts      = set(selected.get("layouts", set()))              # "layout_name"
    sel_relations    = set(selected.get("relations", set())) or set(selected.get("relations", set()))
    sel_rel_fields   = set(selected.get("relation_fields", set()))      # "rel_parent_field_X", "rel_child_field_X"

    # IDs connus du projet (pour tolérance legacy)
    known_ids = _collect_known_layer_ids(root)

    # Construire les sélections effectives
    eff_layers: Set[str] = set(sel_layers)
    eff_styles: Set[str] = set()  # on normalise en "layer_id|style"
    per_layer_allowed: DefaultDict[str, Set[str]] = defaultdict(set)

    # Styles (onglet Couches)
    for token in sel_styles:
        lid, style = _parse_token_style(token, known_ids)
        if lid:
            eff_layers.add(lid)
            if style:
                eff_styles.add(f"{lid}|{style}")
                per_layer_allowed[lid].add(style)

    # Thèmes → couches
    for token in sel_theme_layers:
        th, lid = _parse_token_theme_layer(token, known_ids)
        if lid:
            eff_layers.add(lid)
            if th:
                sel_themes.add(th)

    # Thèmes → styles
    for token in sel_theme_styles:
        th, lid, style = _parse_token_theme_style(token, known_ids)
        if lid:
            eff_layers.add(lid)
            if style:
                eff_styles.add(f"{lid}|{style}")
                per_layer_allowed[lid].add(style)
            if th:
                sel_themes.add(th)

    # DEBUG console
    print("[QRator] eff_layers:", eff_layers)
    print("[QRator] eff_styles:", eff_styles)
    print("[QRator] sel_themes:", sel_themes)
    print("[QRator] sel_layouts:", sel_layouts)
    print("[QRator] sel_relations:", sel_relations)
    print("[QRator] sel_rel_fields:", sel_rel_fields)

    # Filtrages
    _filter_layers_and_groups(root, eff_layers)  # on épure les maplayers + l'arbre
    _filter_layer_styles(root, eff_layers, eff_styles, per_layer_allowed)
    _filter_themes(root, sel_themes, eff_layers, per_layer_allowed)
    _filter_layouts(root, sel_layouts)
    _filter_relations(root, sel_relations, sel_rel_fields)

    return root

# =========================
# Filtrages concrets
# =========================

def _filter_layers_and_groups(xml_root: etree._Element, eff_layers: Set[str]):
    """
    1) Supprime toutes les définitions <maplayer> dont l'id n'est pas dans eff_layers.
    2) Nettoie <projectlayers> (certains schémas y contiennent des définitions additionnelles).
    3) Émonde l'arbre <layer-tree-group> pour ne garder que les branches contenant des couches retenues.
    """
    # 1) maplayer
    for ml in list(_all(xml_root, ".//*[local-name()='maplayer']")):
        lid = ml.findtext("id", "")
        if lid and lid not in eff_layers:
            parent = ml.getparent()
            if parent is not None:
                parent.remove(ml)

    # 2) projectlayers
    pl = _first(xml_root, ".//*[local-name()='projectlayers']")
    if pl is not None:
        for child in list(pl):
            # Certains projets ont <maplayer> directement ici, d'autres <layer> → on gère les deux
            if etree.QName(child).localname in ("maplayer", "layer"):
                lid = child.findtext("id", "")
                if lid and lid not in eff_layers:
                    pl.remove(child)

    # 3) layer-tree-group
    ltg = _first(xml_root, ".//*[local-name()='layer-tree-group']")
    if ltg is not None:
        _prune_tree_keep_if_contains_layers(ltg, eff_layers)

def _prune_tree_keep_if_contains_layers(group_elem: etree._Element, eff_layers: Set[str]) -> bool:
    """
    Retourne True si le groupe contient encore au moins une couche retenue après élagage.
    Supprime récursivement les sous-groupes/couches non retenus.
    """
    to_remove, keep = [], False
    for child in list(group_elem):
        tag = etree.QName(child).localname
        if tag == "layer-tree-layer":
            lid = child.get("id", "")
            if lid in eff_layers:
                keep = True
            else:
                to_remove.append(child)
        elif tag == "layer-tree-group":
            if _prune_tree_keep_if_contains_layers(child, eff_layers):
                keep = True
            else:
                to_remove.append(child)
    for n in to_remove:
        group_elem.remove(n)
    return keep

def _filter_layer_styles(xml_root: etree._Element,
                         eff_layers: Set[str],
                         eff_styles: Set[str],
                         per_layer_allowed: DefaultDict[str, Set[str]]):
    """
    Dans chaque <maplayer>, si des styles explicites ont été sélectionnés pour cette couche,
    ne garder que ces styles dans <style-manager> (ou <map-layer-style-manager>).
    eff_styles est normalisé en "layer_id|style".
    """
    for ml in _all(xml_root, ".//*[local-name()='maplayer']"):
        lid = ml.findtext("id", "")
        if lid not in eff_layers:
            continue

        sm = (_first(ml, ".//*[local-name()='style-manager']") or
              _first(ml, ".//*[local-name()='map-layer-style-manager']"))
        if sm is None:
            continue

        has_explicit = any(s.startswith(f"{lid}|") for s in eff_styles)
        if not has_explicit:
            continue

        for st in list(_all(sm, ".//*[local-name()='map-layer-style']")):
            sname = st.get("name", "default")
            token = f"{lid}|{sname}"
            if token not in eff_styles:
                p = st.getparent()
                if p is not None:
                    p.remove(st)

def _filter_themes(xml_root: etree._Element,
                   themes: Set[str],
                   eff_layers: Set[str],
                   per_layer_allowed: DefaultDict[str, Set[str]]):
    """
    Filtre <visibility-presets> :
    - Si aucun thème sélectionné → supprime entièrement la section.
    - Sinon, garde uniquement les <visibility-preset name="..."> sélectionnés.
      À l'intérieur, ne garde que les <layer id="..."> correspondant à eff_layers.
      Si des styles explicites existent pour cette couche, on ne garde que les 'style' autorisés.
    """
    presets = _first(xml_root, ".//*[local-name()='visibility-presets']")
    if presets is None:
        return

    if not themes:
        parent = presets.getparent()
        if parent is not None:
            parent.remove(presets)
        return

    for preset in list(_all(presets, ".//*[local-name()='visibility-preset']")):
        name = preset.get("name", "")
        if name not in themes:
            presets.remove(preset)
            continue

        for lyr in list(_all(preset, ".//*[local-name()='layer']")):
            lid = lyr.get("id", "")
            if lid and lid not in eff_layers:
                preset.remove(lyr)
                continue
            if lid in per_layer_allowed:
                s = lyr.get("style", "")
                if s and s not in per_layer_allowed[lid]:
                    preset.remove(lyr)

def _filter_layouts(xml_root: etree._Element, layouts: Set[str]):
    """
    Filtre les mises en page dans tous les schémas rencontrés :
      - Conteneurs <Layouts>/<layouts> avec enfants <Layout>/<layout>
      - <Layout>/<layout> directement sous la racine <qgis>
    Règles :
      - Si 'layouts' est vide → on supprime toutes les mises en page (dans les deux structures).
      - Sinon → on ne garde que les mises en page dont le 'name' est dans 'layouts'.
      - Les éventuelles préférences (ex: <lastLayoutExportDir>) sont laissées telles quelles.
    """
    sel = set(layouts or [])

    # 1) Cas: <Layout>/<layout> directement sous la racine <qgis>
    #    → supprimer / garder selon la sélection
    for child in list(xml_root):
        if _localname(child.tag) == "layout":
            name = (child.get("name") or "").strip()
            if not sel or name not in sel:
                xml_root.remove(child)

    # 2) Cas: conteneurs <Layouts>/<layouts> n'importe où → nettoyer leurs enfants layout
    #    NB: on ne supprime pas le conteneur lui-même s'il reste des préférences (ex: lastLayoutExportDir).
    for elem in xml_root.iter():
        if _localname(elem.tag) == "layouts":
            for lay in list(elem):
                if _localname(lay.tag) == "layout":
                    name = (lay.get("name") or "").strip()
                    if not sel or name not in sel:
                        elem.remove(lay)

    # 3) Optionnel : si aucun layout retenu nulle part et qu'un conteneur <Layouts> est devenu vide
    #    (sans enfants <layout>), on peut le supprimer si tu veux un XML minimal.
    #    -> Décommente si souhaité :
    # for elem in list(xml_root.iter()):
    #     if _localname(elem.tag) == "layouts":
    #         has_layout = any(_localname(c.tag) == "layout" for c in elem)
    #         if not has_layout:
    #             parent = elem.getparent()
    #             if parent is not None:
    #                 parent.remove(elem)

def _filter_relations(xml_root: etree._Element,
                      relations: Set[str],
                      rel_fields: Set[str]):
    """
    Filtre <relations> :
    - Si aucune relation sélectionnée → supprime entièrement la section.
    - Sinon, garde uniquement les <relation name="..."> sélectionnées.
      À l’intérieur, garde les <fieldRef> dont les champs sont cochés si rel_fields est fourni.
    """
    R = _first(xml_root, ".//*[local-name()='relations']")
    if R is None:
        return

    if not relations:
        p = R.getparent()
        if p is not None:
            p.remove(R)
        return

    for rel in list(_all(R, ".//*[local-name()='relation']")):
        name = rel.get("name", "")
        if name not in relations:
            R.remove(rel)
            continue

        if rel_fields:
            for fr in list(rel.findall("fieldRef")):
                child_field = fr.get("referencingField", "")
                parent_field = fr.get("referencedField", "")
                if (f"{name}_child_field_{child_field}" not in rel_fields or
                    f"{name}_parent_field_{parent_field}" not in rel_fields):
                    rel.remove(fr)

# =========================
# Fusion de projets (merge A + B sans doublon de couches)
# =========================

def merge_project_xml(base_root: etree._Element, filtered_root: etree._Element) -> etree._Element:
    """
    Fusionne dans *base_root* le contenu filtré de *filtered_root*.

    Principe général :
      - On reconnaît les couches par leur « clé de source »
        (provider + datasource + subsetstring) et NON par leur ID QGIS.
      - Si une couche de B existe déjà dans A (même clé de source) :
          * on réutilise l'ID de la couche existante dans A ;
          * on fusionne les styles (style-manager) sans dupliquer
            les styles déjà présents.
      - Si une couche n'existe pas dans A :
          * on ajoute un nouveau <maplayer> dans <projectlayers> de A ;
          * on ajoute un <layer-tree-layer> correspondant dans l'arbre des couches.
      - On injecte ensuite dans A les thèmes, mises en page et relations
        de B (déjà filtrés), en réécrivant automatiquement les références
        aux IDs de couches selon un mapping ancien_id → nouvel_id.
    """
    # --- 1) Index des couches existantes dans A par « clé de source » ---
    base_index = {}
    base_ids = _collect_known_layer_ids(base_root)

    for ml in _all(base_root, ".//*[local-name()='maplayer']"):
        lid = ml.findtext("id", "")
        key = _layer_source_key(ml)
        if lid and key and key not in base_index:
            base_index[key] = ml

    # --- 2) Parcourir les couches de B filtré et construire le mapping d'IDs ---
    id_map: Dict[str, str] = {}         # ancien_id (B) -> nouvel_id (dans A)
    src_layers_by_id: Dict[str, etree._Element] = {}
    new_layer_ids = []                  # liste des IDs d'origine (B) pour les couches vraiment nouvelles

    def _merge_style_manager(dst_ml: etree._Element, src_ml: etree._Element):
        """Fusionne les styles du style-manager de src_ml dans dst_ml (sans doublons)."""
        dst_sm = (
            _first(dst_ml, ".//*[local-name()='style-manager']")
            or _first(dst_ml, ".//*[local-name()='map-layer-style-manager']")
        )
        src_sm = (
            _first(src_ml, ".//*[local-name()='style-manager']")
            or _first(src_ml, ".//*[local-name()='map-layer-style-manager']")
        )
        if src_sm is None:
            return
        if dst_sm is None:
            # Pas de style-manager côté A : on recopie celui de B tel quel
            dst_ml.append(copy.deepcopy(src_sm))
            return

        def _collect_styles(sm_elem: etree._Element) -> Dict[str, etree._Element]:
            out = {}
            for ch in sm_elem:
                if _localname(ch.tag) in ("style", "map-layer-style"):
                    name = (ch.get("name") or "").strip()
                    if name:
                        out[name] = ch
            return out

        dst_styles = _collect_styles(dst_sm)
        src_styles = _collect_styles(src_sm)

        for name, st in src_styles.items():
            if name not in dst_styles:
                dst_sm.append(copy.deepcopy(st))

    for ml in _all(filtered_root, ".//*[local-name()='maplayer']"):
        lid_src = ml.findtext("id", "")
        if not lid_src:
            continue

        key = _layer_source_key(ml)
        if not key:
            continue

        src_layers_by_id[lid_src] = ml

        if key in base_index:
            # Couches identiques par leur source : on réutilise la couche de A
            ml_base = base_index[key]
            lid_dst = ml_base.findtext("id", "") or lid_src
            id_map[lid_src] = lid_dst

            # Fusion des styles
            _merge_style_manager(ml_base, ml)
        else:
            # Nouvelle couche : on ajoutera son maplayer et un layer-tree-layer
            new_id = lid_src
            if new_id in base_ids:
                # Collision d'ID très improbable, mais on gère proprement
                i = 1
                while f"{lid_src}_{i}" in base_ids:
                    i += 1
                new_id = f"{lid_src}_{i}"
            id_map[lid_src] = new_id
            base_ids.add(new_id)
            new_layer_ids.append(lid_src)

    # --- 3) Helper pour cloner un sous-arbre en remplaçant les IDs ---
    def _clone_with_id_map(elem: etree._Element) -> etree._Element:
        if elem is None:
            return None
        xml_bytes = etree.tostring(elem, encoding="utf-8")
        xml_str = xml_bytes.decode("utf-8")
        for old, new in id_map.items():
            if old and new and old != new:
                xml_str = xml_str.replace(old, new)
        return etree.fromstring(xml_str.encode("utf-8"))

    # --- 4) Ajout des nouveaux maplayers dans <projectlayers> ---
    base_pl = _first(base_root, ".//*[local-name()='projectlayers']")
    src_pl = _first(filtered_root, ".//*[local-name()='projectlayers']")
    if base_pl is not None and src_pl is not None:
        for child in src_pl:
            if _localname(child.tag) != "maplayer":
                continue
            lid = child.findtext("id", "")
            if lid in new_layer_ids:
                final_id = id_map.get(lid, lid)
                ml_clone = _clone_with_id_map(child)
                # Sécurité : forcer le <id> du clone à l'ID final
                id_node = ml_clone.find("id")
                if id_node is not None:
                    id_node.text = final_id
                base_pl.append(ml_clone)

    # --- 5) S'assurer que ces nouvelles couches apparaissent dans l'arbre de couches ---
    tree_root = _first(base_root, ".//*[local-name()='layer-tree-group']")
    if tree_root is not None:
        for lid in new_layer_ids:
            ml = src_layers_by_id.get(lid)
            if ml is None:
                continue
            final_id = id_map.get(lid, lid)
            name = (ml.findtext("layername") or ml.findtext("name") or "").strip() or final_id
            node = etree.Element("layer-tree-layer")
            node.set("id", final_id)
            node.set("name", name)
            node.set("checked", "Qt::Checked")
            tree_root.append(node)

    # --- 6) Fusion des thèmes (visibility-presets) ---
    base_presets = _first(base_root, ".//*[local-name()='visibility-presets']")
    src_presets = _first(filtered_root, ".//*[local-name()='visibility-presets']")
    if src_presets is not None:
        if base_presets is None:
            clone = _clone_with_id_map(src_presets)
            base_root.append(clone)
        else:
            def _iter_presets(root_elem: etree._Element):
                return [p for p in _all(root_elem, ".//*[local-name()='visibility-preset']")]

            base_by_name = {
                (p.get("name") or "").strip(): p
                for p in _iter_presets(base_presets)
                if (p.get("name") or "").strip()
            }

            for p_src in _iter_presets(src_presets):
                name = (p_src.get("name") or "").strip()
                if not name:
                    continue

                p_clone = _clone_with_id_map(p_src)
                if name not in base_by_name:
                    base_presets.append(p_clone)
                    base_by_name[name] = p_clone
                else:
                    target = base_by_name[name]
                    existing_ids = {
                        ly.get("id", "")
                        for ly in _all(target, ".//*[local-name()='layer']")
                    }
                    for ly in _all(p_clone, ".//*[local-name()='layer']"):
                        lid = ly.get("id", "")
                        if lid and lid not in existing_ids:
                            target.append(copy.deepcopy(ly))

    # --- 7) Fusion des mises en page (layouts) ---
    def _iter_layouts(root_elem: etree._Element):
        return [elem for elem in root_elem.iter() if _localname(elem.tag) == "layout"]

    def _get_layout_container(root_elem: etree._Element):
        cont = _first(root_elem, ".//*[local-name()='layouts']")
        return cont if cont is not None else root_elem

    base_layouts = _iter_layouts(base_root)
    src_layouts = _iter_layouts(filtered_root)
    existing_layout_names = {
        (l.get("name") or "").strip()
        for l in base_layouts
        if (l.get("name") or "").strip()
    }

    if src_layouts:
        cont = _get_layout_container(base_root)
        for lay in src_layouts:
            name = (lay.get("name") or "").strip()
            if not name or name in existing_layout_names:
                continue
            lay_clone = _clone_with_id_map(lay)
            cont.append(lay_clone)

    # --- 8) Fusion des relations ---
    base_rel_root = _first(base_root, ".//*[local-name()='relations']")
    src_rel_root = _first(filtered_root, ".//*[local-name()='relations']")
    if src_rel_root is not None:
        if base_rel_root is None:
            clone_rel = _clone_with_id_map(src_rel_root)
            base_root.append(clone_rel)
        else:
            existing_rel_names = {
                (r.get("name") or "").strip()
                for r in _all(base_rel_root, ".//*[local-name()='relation']")
                if (r.get("name") or "").strip()
            }
            for r_src in _all(src_rel_root, ".//*[local-name()='relation']"):
                name = (r_src.get("name") or "").strip()
                if not name or name in existing_rel_names:
                    continue
                r_clone = _clone_with_id_map(r_src)
                base_rel_root.append(r_clone)

    return base_root

# =========================
# Sauvegarde
# =========================
# === QRator: déconnexion des sources locales dans le XML ===
def _is_remote_provider(provider: str, datasource: str) -> bool:
    p = (provider or "").lower()
    ds = (datasource or "")

    remote_providers = {
        "postgres", "wfs", "wms", "wmts", "xyz",
        "arcgismapserver", "arcgisfeatureserver", "ows",
        "mssql", "oracle", "vectortile", "memory", "virtual"
    }
    if p in remote_providers:
        return True

    # Datasource http(s)/ftp ⇒ distant
    if re.search(r"(?i)^(https?|ftp)://", ds):
        return True
    if re.search(r"(?i)(^|[?&])url=(https?|ftp)://", ds):
        return True

    return False


def _should_disconnect_local_provider(provider: str, datasource: str) -> bool:
    if _is_remote_provider(provider, datasource):
        return False
    # Providers typiquement locaux
    localish = {"ogr", "gdal", "delimitedtext", "spatialite", "gpx", "mdal"}
    return (provider or "").lower() in localish


def _make_invalid_datasource(provider: str) -> str:
    import os as _os
    invalid_path = r"C:\__qrator_missing__\missing.xxx" if _os.name == "nt" else "/__qrator_missing__/missing.xxx"
    p = (provider or "").lower()
    if p == "delimitedtext":
        return f"file://{invalid_path}?encoding=UTF-8"
    return invalid_path


def disconnect_local_layers_in_xml(xml_root: etree._Element):
    """
    Parcourt toutes les <maplayer> et remplace <datasource> par un chemin invalide
    pour forcer le réadressage des couches locales à la réouverture du projet.
    """
    for ml in _all(xml_root, ".//*[local-name()='maplayer']"):
        prov_node = ml.find("provider")
        provider = prov_node.text.strip() if prov_node is not None and prov_node.text else ""

        ds_node = ml.find("datasource")
        datasource = ds_node.text if ds_node is not None and ds_node.text else ""

        if not _should_disconnect_local_provider(provider, datasource):
            continue

        invalid_ds = _make_invalid_datasource(provider)
        if ds_node is None:
            ds_node = etree.SubElement(ml, "datasource")
        ds_node.text = invalid_ds

        try:
            ml.addprevious(etree.Comment("QRator: datasource intentionally broken to force relinking"))
        except Exception:
            pass
# === /QRator: déconnexion ===

# =========================
# Sauvegarde : QGZ = QGS + QGD
# =========================
def _write_project_with_aux(xml_root: etree._Element,
                            output_path: str,
                            aux_source_project_path: str = None) -> bool:
    """Écrit xml_root dans un fichier .qgz (output_path) en y intégrant
    éventuellement les fichiers de stockage auxiliaire (.qgd) trouvés dans
    *aux_source_project_path* (projet source .qgz ou .qgs).
    """
    try:
        # 1) Écrire le XML dans un .qgs temporaire
        with tempfile.NamedTemporaryFile(suffix=".qgs", delete=False) as tmp:
            tmp.write(etree.tostring(xml_root, pretty_print=True, encoding="utf-8"))
            tmp_qgs = tmp.name

        # 2) Collecter les éventuels fichiers de stockage auxiliaire (.qgd)
        aux_files = []  # liste de tuples (arcname, bytes)

        if aux_source_project_path:
            try:
                # Cas 1 : projet source déjà au format .qgz
                if aux_source_project_path.lower().endswith(".qgz") and os.path.exists(aux_source_project_path):
                    with zipfile.ZipFile(aux_source_project_path, "r") as src_zip:
                        for name in src_zip.namelist():
                            if name.lower().endswith(".qgd"):
                                try:
                                    data = src_zip.read(name)
                                    aux_files.append((name, data))
                                    print(f"[QRator] Found auxiliary storage in source qgz: {name}")
                                except Exception as e:
                                    print(f"[QRator] Could not read aux file '{name}' from source qgz: {e}")

                # Cas 2 : projet source .qgs avec un .qgd à côté
                elif aux_source_project_path.lower().endswith(".qgs"):
                    base = os.path.splitext(aux_source_project_path)[0]
                    qgd_path = base + ".qgd"
                    if os.path.exists(qgd_path):
                        try:
                            with open(qgd_path, "rb") as f:
                                data = f.read()
                            # À l'intérieur de l'archive, QGIS utilise généralement 'project.qgd'
                            arcname = "project.qgd"
                            aux_files.append((arcname, data))
                            print(f"[QRator] Found auxiliary storage beside source qgs: {qgd_path}")
                        except Exception as e:
                            print(f"[QRator] Could not read aux file '{qgd_path}': {e}")
            except Exception as e:
                print(f"[QRator] Error while collecting auxiliary storage: {e}")

        # 3) Emballer dans un .qgz : toujours écrire 'project.qgs'
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(tmp_qgs, arcname="project.qgs")

            # Ré-injecter les éventuels fichiers .qgd collectés
            if aux_files:
                existing = set(zipf.namelist())
                for arcname, data in aux_files:
                    if arcname in existing:
                        print(f"[QRator] Aux file '{arcname}' already present in qgz, skipping.")
                        continue
                    try:
                        zipf.writestr(arcname, data)
                        print(f"[QRator] Embedded auxiliary storage file '{arcname}' in qgz.")
                    except Exception as e:
                        print(f"[QRator] Could not write aux file '{arcname}' to qgz: {e}")

        # Nettoyage du temporaire
        os.unlink(tmp_qgs)
        print(f"[QRator] Saved filtered project to {output_path}")
        return True

    except Exception as e:
        print(f"[QRator] save error: {e}")
        return False

def save_new_project(output_path: str,
                     xml_root: etree._Element,
                     selected: Dict,
                     source_project_path: str = None) -> bool:
    """Écrit un nouveau projet filtré sur disque (au format .qgz).

    Paramètres
    ----------
    output_path : str
        Chemin du fichier .qgz de sortie.
    xml_root : etree._Element
        Racine XML du projet d'origine (projet actuellement ouvert).
    selected : dict
        Dictionnaire de sélections retourné par SelectionManager.get_selected_elements().
    source_project_path : str, optionnel
        Chemin du projet source (.qgz ou .qgs). S'il pointe vers un
        projet qui utilise un stockage auxiliaire (.qgd), ce fichier sera
        recopié dans la nouvelle archive .qgz.
    """
    # 1) Appliquer le filtrage sur une copie du XML source
    filtered = filter_project_xml(xml_root, selected)

    # 2) Déconnecter les couches locales si demandé
    if selected.get("disconnect_local"):
        try:
            disconnect_local_layers_in_xml(filtered)
        except Exception as e:
            print(f"[QRator] Error while disconnecting local layers: {e}")

    # 3) Écrire le projet + stockage auxiliaire
    return _write_project_with_aux(
        xml_root=filtered,
        output_path=output_path,
        aux_source_project_path=source_project_path,
    )

def save_merged_project(existing_project_path: str,
                        xml_root_source: etree._Element,
                        selected: Dict,
                        output_path: str) -> bool:
    """
    Fusionne les éléments sélectionnés du projet source (B) dans un projet
    existant (A), puis écrit le résultat dans *output_path*.

    - existing_project_path : chemin du projet A (déjà existant, .qgs ou .qgz).
    - xml_root_source       : XML du projet B (celui actuellement ouvert).
    - selected              : sélections renvoyées par SelectionManager.
    - output_path           : chemin du projet fusionné (souvent le même que A).
    """
    try:
        # 1) Charger le projet de base (A)
        base_root, _ = open_project(existing_project_path)

        # 2) Filtrer le projet source B selon les sélections
        filtered_source = filter_project_xml(xml_root_source, selected)

        # 3) Fusionner B (filtré) dans A
        merged_root = merge_project_xml(base_root, filtered_source)

        # 4) Déconnecter les couches locales si demandé
        if selected.get("disconnect_local"):
            try:
                disconnect_local_layers_in_xml(merged_root)
            except Exception as e:
                print(f"[QRator] Error while disconnecting local layers in merge: {e}")

        # 5) Écrire sur disque en réutilisant le stockage auxiliaire du projet A
        return _write_project_with_aux(
            xml_root=merged_root,
            output_path=output_path,
            aux_source_project_path=existing_project_path,
        )

    except Exception as e:
        print(f"[QRator] save_merged_project error: {e}")
        return False