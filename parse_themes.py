from qgis.PyQt.QtWidgets import QTreeWidgetItem
from qgis.PyQt.QtCore import Qt

def _all(elem, xp):
    return elem.xpath(xp)

def _first(elem, xp):
    r = elem.xpath(xp)
    return r[0] if r else None

def _collect_layer_names(xml_root):
    """id -> layername (fallback: id)"""
    mapping = {}
    for ml in _all(xml_root, ".//*[local-name()='maplayer']"):
        lid = ml.findtext("id", "")
        if not lid:
            continue
        lname = ml.findtext("layername", lid)
        mapping[lid] = lname or lid
    return mapping

def _collect_theme_structure(xml_root):
    """
    theme_name -> { layer_id -> set([style_name_or_empty, ...]) }
    S'il manque l'attribut 'style' dans le preset, on met '' (défaut du thème).
    """
    themes = {}
    presets = _first(xml_root, ".//*[local-name()='visibility-presets']")
    if presets is None:
        return themes

    for preset in _all(presets, ".//*[local-name()='visibility-preset']"):
        tname = preset.get("name", "")
        if not tname:
            continue
        layers_map = {}
        for lyr in _all(preset, ".//*[local-name()='layer']"):
            lid = lyr.get("id", "")
            if not lid:
                continue
            s = lyr.get("style", "")  # '' => style par défaut du preset
            layers_map.setdefault(lid, set()).add(s)
        themes[tname] = layers_map
    return themes

def parse_themes(xml_root, tree_widget, selection_manager):
    """
    Onglet THEMES :
      - thème (type 'themes', id = theme_name)
      - couche (type 'theme_layers', id = 'theme|layer_id', *affiche layer_name*)
      - style (type 'theme_styles', id = 'theme|layer_id|style', affiche nom ou '(défaut)')
    """
    tree_widget.clear()
    id_to_name = _collect_layer_names(xml_root)
    themes = _collect_theme_structure(xml_root)

    for theme_name, layers_map in themes.items():
        it_theme = QTreeWidgetItem(tree_widget, [theme_name])
        it_theme.setFlags(it_theme.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsTristate)
        it_theme.setCheckState(0, Qt.Unchecked)
        selection_manager.register_item("themes", theme_name, it_theme)

        for layer_id, style_set in layers_map.items():
            visible_name = id_to_name.get(layer_id, layer_id)
            it_layer = QTreeWidgetItem(it_theme, [visible_name])
            it_layer.setFlags(it_layer.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsTristate)
            it_layer.setCheckState(0, Qt.Unchecked)
            selection_manager.register_item("theme_layers", f"{theme_name}|{layer_id}", it_layer)

            if not style_set:
                style_set = {""}

            for style_name in style_set:
                label = style_name if style_name else "(défaut)"
                it_style = QTreeWidgetItem(it_layer, [label])
                it_style.setFlags(it_style.flags() | Qt.ItemIsUserCheckable)
                it_style.setCheckState(0, Qt.Unchecked)
                selection_manager.register_item("theme_styles", f"{theme_name}|{layer_id}|{style_name}", it_style)