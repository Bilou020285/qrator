# qrator/parse_layouts_relations.py
from qgis.PyQt.QtWidgets import QTreeWidgetItem
from qgis.PyQt.QtCore import Qt

# --- helpers XML namespace-agnostiques ---
def _all(elem, xp):
    return elem.xpath(xp)

def _first(elem, xp):
    r = elem.xpath(xp)
    return r[0] if r else None

# ------------ Layouts ------------

def _localname(tag: str) -> str:
    return tag.rsplit('}', 1)[-1].lower() if tag else ""

def parse_layouts(xml_root, tree_widget, selection_manager):
    """
    Détecte les mises en page quelle que soit la structure, la casse et les namespaces :
      - <Layouts><Layout name="..."/></Layouts> / <layouts><layout .../>
      - <Layout name="..."/> directement sous <qgis>
      - namespaces éventuels
    """
    tree_widget.clear()
    if xml_root is None or tree_widget is None or selection_manager is None:
        return

    layout_names = []
    for elem in xml_root.iter():
        if _localname(elem.tag) == "layout":
            name = (elem.get("name") or "").strip()
            if name:
                layout_names.append(name)

    # Déduplique en préservant l’ordre d’apparition
    seen = set()
    for name in layout_names:
        if name in seen:
            continue
        seen.add(name)
        it = QTreeWidgetItem(tree_widget, [name])
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(0, Qt.Unchecked)
        selection_manager.register_item("layouts", name, it)

# ------------ Relations (3 niveaux, seuls les niveaux 0 cochables) ------------

def _layer_names(xml_root):
    m = {}
    for ml in _all(xml_root, ".//*[local-name()='maplayer']"):
        lid = ml.findtext("id", "")
        if lid:
            m[lid] = ml.findtext("layername", lid) or lid
    return m

def parse_relations(xml_root, tree_widget, selection_manager):
    """
    Arborescence :
      relation (checkable, type 'relations')
        ├── (parent) <layer_name>   (info, non checkable)
        │     └── <field>           (info, non checkable)
        └── (child)  <layer_name>   (info, non checkable)
              └── <field>           (info, non checkable)
    """
    tree_widget.clear()
    R = _first(xml_root, ".//*[local-name()='relations']")
    if R is None:
        return

    id2name = _layer_names(xml_root)

    for rel in _all(R, ".//*[local-name()='relation']"):
        rname = rel.get("name", "")
        if not rname:
            continue

        # LIDs parent/enfant
        parent_lid = rel.get("referencedLayer", "")     # parent
        child_lid  = rel.get("referencingLayer", "")    # enfant

        parent_name = id2name.get(parent_lid, parent_lid) if parent_lid else "(parent ?)"
        child_name  = id2name.get(child_lid, child_lid)  if child_lid  else "(child ?)"

        # Niveau 0 : relation (cochable)
        it_rel = QTreeWidgetItem(tree_widget, [rname])
        it_rel.setFlags(it_rel.flags() | Qt.ItemIsUserCheckable)  # pas de Tristate
        it_rel.setCheckState(0, Qt.Unchecked)
        # Enregistre l'item comme relation (clé contractuelle)
        selection_manager.register_item("relations", rname, it_rel)
        # >>> Métadonnée pour l’auto-sélection : (parent_lid, child_lid)
        it_rel.setData(0, Qt.ItemDataRole.UserRole + 1, ("rel_layers", parent_lid, child_lid))

        # Niveau -1 : Parent / Child (non cochables)
        it_parent = QTreeWidgetItem(it_rel, [f"(parent) {parent_name}"])
        it_parent.setFlags(it_parent.flags() & ~Qt.ItemIsUserCheckable)

        it_child = QTreeWidgetItem(it_rel, [f"(child) {child_name}"])
        it_child.setFlags(it_child.flags() & ~Qt.ItemIsUserCheckable)

        # Niveau -2 : champs (non cochables)
        for fr in rel.findall("fieldRef"):
            pfield = fr.get("referencedField", "")
            cfield = fr.get("referencingField", "")

            if pfield:
                it_p = QTreeWidgetItem(it_parent, [pfield])
                it_p.setFlags(it_p.flags() & ~Qt.ItemIsUserCheckable)

            if cfield:
                it_c = QTreeWidgetItem(it_child, [cfield])
                it_c.setFlags(it_c.flags() & ~Qt.ItemIsUserCheckable)

# ------------ Wrapper rétro-compatible ------------

def parse_layouts_relations(xml_root, layouts_tree_widget=None, relations_tree_widget=None, selection_manager=None):
    try:
        if layouts_tree_widget is not None:
            parse_layouts(xml_root, layouts_tree_widget, selection_manager)
        if relations_tree_widget is not None:
            parse_relations(xml_root, relations_tree_widget, selection_manager)
    except Exception as e:
        print("[QRator] parse_layouts_relations error:", e)