from qgis.PyQt.QtWidgets import QTreeWidgetItem
from qgis.PyQt.QtCore import Qt

# --- helpers XML namespace-agnostiques ---
def _all(elem, xp):
    return elem.xpath(xp)

def _first(elem, xp):
    r = elem.xpath(xp)
    return r[0] if r else None

def _collect_layers(xml_root):
    """
    Retourne:
      layer_id -> {
        'name': layer_name,
        'styles': [style_name, ...]
      }

    Robustesse accrue:
    - supporte map-layer-style-manager ET style-manager
    - lit map-layer-style ET style (selon versions)
    - ajoute aussi le style 'current' s'il n'apparaît pas en enfant
    """
    out = {}
    for ml in _all(xml_root, ".//*[local-name()='maplayer']"):
        lid = ml.findtext("id", "")
        if not lid:
            continue
        lname = ml.findtext("layername", lid)

        styles = []
        seen = set()

        # 1) trouver tous les managers possibles (directs ou en profondeur)
        managers = []
        # direct
        for tag in ("map-layer-style-manager", "style-manager"):
            node = ml.find(tag)
            if node is not None:
                managers.append(node)
        # fallback profond
        if not managers:
            managers = _all(ml, ".//*[local-name()='map-layer-style-manager' or local-name()='style-manager']")

        # 2) extraire les styles depuis les managers
        for sm in managers:
            # a) Enfants explicites: <map-layer-style name="..."> et/ou <style name="...">
            for st in _all(sm, ".//*[local-name()='map-layer-style' or local-name()='style']"):
                sname = (st.get("name", "") or "").strip()
                if not sname:
                    sname = "default"
                if sname not in seen:
                    seen.add(sname)
                    styles.append(sname)

            # b) Attribut 'current' du manager (souvent utilisé)
            current = (sm.get("current", "") or "").strip()
            if current and current not in seen:
                seen.add(current)
                styles.append(current)

        # 3) S'il n'existe vraiment aucune info → offrir au moins 'default'
        if not styles:
            styles = ["default"]

        out[lid] = {"name": lname, "styles": styles}

        # DEBUG
        try:
            print(f"[QRator][parse_layers] layer '{lname}' ({lid}) -> styles: {styles}")
        except Exception:
            pass

    return out

def parse_layers(xml_root, tree_widget, selection_manager):
    """
    Onglet COUCHES :
      - item couche (type 'layers', id = layer_id)
      - sous-items styles (type 'styles', id = 'layer_id|style_name')
    """
    tree_widget.clear()

    layers = _collect_layers(xml_root)

    for layer_id, info in layers.items():
        layer_name = info["name"]
        styles = info["styles"]

        it_layer = QTreeWidgetItem(tree_widget, [layer_name])
        it_layer.setFlags(it_layer.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsTristate)
        it_layer.setCheckState(0, Qt.Unchecked)
        selection_manager.register_item("layers", layer_id, it_layer)

        for style_name in styles:
            # Affichage convivial, identifiant inchangé
            label = "(défaut)" if style_name.lower() in ("default", "défaut") else style_name
            it_style = QTreeWidgetItem(it_layer, [label])
            it_style.setFlags(it_style.flags() | Qt.ItemIsUserCheckable)
            it_style.setCheckState(0, Qt.Unchecked)
            selection_manager.register_item("styles", f"{layer_id}|{style_name}", it_style)