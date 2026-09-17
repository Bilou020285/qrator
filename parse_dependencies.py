# qrator/parse_dependencies.py
"""
Peuple l'onglet "Dépendances" : un item par mise en page (liste immédiate, bon marché),
chacun chargé paresseusement (à l'expansion) via dependency_analyzer, car un projet peut
contenir des dizaines de mises en page et l'introspection SQLite a un coût.

Tous les items sont informatifs (non cochables) : cet onglet ne participe pas au système
de sélection multi-onglets, voir QRator_dialog.py pour le bouton "Sélectionner ces dépendances"
qui relit dependency_analyzer à la demande et utilise SelectionManager.check_items().
"""
from qgis.PyQt.QtWidgets import QTreeWidgetItem
from qgis.PyQt.QtCore import Qt

from . import dependency_analyzer as da

_LOADED_ROLE = Qt.ItemDataRole.UserRole + 3
_LAYOUT_NAME_ROLE = Qt.ItemDataRole.UserRole + 4


def _localname(tag: str) -> str:
    return tag.rsplit('}', 1)[-1].lower() if tag else ""


def _non_checkable(item: QTreeWidgetItem) -> QTreeWidgetItem:
    item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
    return item


def _build_layer_item(parent: QTreeWidgetItem, node: dict, prefix: str = "") -> QTreeWidgetItem:
    if node.get("error"):
        label = f"{prefix}⚠ {node.get('layer_id')} — couche absente du projet (référence brisée)"
        return _non_checkable(QTreeWidgetItem(parent, [label]))

    style = node.get("style")
    name = node.get("layer_name") or node.get("layer_id")
    label = f"{prefix}{name}"
    if style:
        label += f"  [style: {style}]"
    it = _non_checkable(QTreeWidgetItem(parent, [label]))

    if node.get("truncated"):
        _non_checkable(QTreeWidgetItem(it, ["… (déjà résolue plus haut dans cette branche)"]))
        return it

    src_label = da.source_kind_label(node)
    if src_label:
        _non_checkable(QTreeWidgetItem(it, [src_label]))

    for j in node.get("joins", []):
        join_label = f"Jointure ({j.get('field') or '?'}) → "
        _build_layer_item(it, j["target"], prefix=join_label)

    return it


def _build_layout_dependencies(tree_widget: QTreeWidgetItem, layout_item: QTreeWidgetItem,
                                xml_root, layout_name: str, project_path):
    result = da.analyze_layout_dependencies(xml_root, layout_name, project_path=project_path)

    if result["atlas"]:
        atlas_root = _non_checkable(QTreeWidgetItem(layout_item, ["Atlas (couche de couverture)"]))
        _build_layer_item(atlas_root, result["atlas"]["layer"])

    if result["themes"]:
        themes_root = _non_checkable(QTreeWidgetItem(layout_item, ["Thèmes utilisés"]))
        for th in result["themes"]:
            th_item = _non_checkable(QTreeWidgetItem(themes_root, [f"Thème : {th['theme']}"]))
            for ly in th["layers"]:
                _build_layer_item(th_item, ly)

    if result["tables"]:
        tables_root = _non_checkable(QTreeWidgetItem(layout_item, ["Tableaux de la mise en page"]))
        for tb in result["tables"]:
            kind_label = "Tableau attributaire" if tb["kind"] == "attribute_table" else (tb["kind"] or "Table")
            tb_item = _non_checkable(QTreeWidgetItem(tables_root, [kind_label]))
            rel = tb.get("relation")
            if rel:
                _non_checkable(QTreeWidgetItem(
                    tb_item, [f"Relation : {rel['name']} (parent → enfant)"]
                ))
            _build_layer_item(tb_item, tb["layer"])

    if result["warnings"]:
        warn_root = _non_checkable(QTreeWidgetItem(layout_item, ["Avertissements"]))
        for w in result["warnings"]:
            _non_checkable(QTreeWidgetItem(warn_root, [w]))

    if not (result["atlas"] or result["themes"] or result["tables"]):
        _non_checkable(QTreeWidgetItem(layout_item, ["(aucune dépendance détectée)"]))


def parse_dependencies(xml_root, tree_widget, selection_manager=None, project_path=None):
    """Peuple tree_widget avec un item par mise en page, chargé à l'expansion."""
    tree_widget.clear()
    if xml_root is None or tree_widget is None:
        return

    layout_names = []
    seen = set()
    for elem in xml_root.iter():
        if _localname(elem.tag) == "layout":
            name = (elem.get("name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                layout_names.append(name)

    for name in layout_names:
        it = QTreeWidgetItem(tree_widget, [name])
        _non_checkable(it)
        it.setData(0, _LOADED_ROLE, False)
        it.setData(0, _LAYOUT_NAME_ROLE, name)
        # enfant factice pour afficher la flèche d'expansion sans tout calculer immédiatement
        QTreeWidgetItem(it, ["…"])

    def _on_expanded(item):
        if item.data(0, _LOADED_ROLE):
            return
        layout_name = item.data(0, _LAYOUT_NAME_ROLE)
        if not layout_name:
            return
        item.takeChildren()
        try:
            _build_layout_dependencies(tree_widget, item, xml_root, layout_name, project_path)
        except Exception as e:
            print(f"[QRator] Could not analyze dependencies for layout '{layout_name}': {e}")
            _non_checkable(QTreeWidgetItem(item, [f"⚠ Erreur d'analyse : {e}"]))
        item.setData(0, _LOADED_ROLE, True)

    try:
        tree_widget.itemExpanded.disconnect()
    except Exception:
        pass
    tree_widget.itemExpanded.connect(_on_expanded)
