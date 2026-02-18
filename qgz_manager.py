# qrator/qgz_manager.py
import os
import tempfile
import zipfile
import copy
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
# Sauvegarde
# =========================

def save_new_project(output_path: str, xml_root: etree._Element, selected: Dict) -> bool:
    """
    Écrit un .qgz filtré selon selected.
    Écrit aussi un fichier *_DEBUG.qgs pour inspection manuelle.
    """
    try:
        filtered = filter_project_xml(xml_root, selected)

        # DEBUG : écrire le XML filtré à côté
        try:
            dbg = os.path.splitext(output_path)[0] + "_DEBUG.qgs"
            with open(dbg, "wb") as f:
                f.write(etree.tostring(filtered, pretty_print=True, encoding="utf-8"))
            print(f"[QRator] DEBUG written: {dbg}")
        except Exception:
            pass

        # Emballer dans un .qgz
        with tempfile.NamedTemporaryFile(suffix=".qgs", delete=False) as tmp:
            tmp.write(etree.tostring(filtered, pretty_print=True, encoding="utf-8"))
            tmp_qgs = tmp.name

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(tmp_qgs, arcname="project.qgs")

        os.unlink(tmp_qgs)
        print(f"[QRator] Saved filtered project to {output_path}")
        return True
    except Exception as e:
        print(f"[QRator] save error: {e}")
        return False