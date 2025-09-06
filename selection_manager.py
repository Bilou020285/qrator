# qrator/selection_manager.py
from qgis.PyQt.QtCore import Qt

class SelectionManager:
    """
    Gestionnaire des sélections multi-onglets.

    Idée clé : pas de cache trompeur ; on relit l'état réel des widgets lors de get_selected_elements().
    + Auto-pré-sélection des RELATIONS : si parent_lid et child_lid sont présents
      parmi les couches cochées (via Couches OU via Thèmes), on coche la relation.
    """

    def __init__(self):
        self.connected_widgets = set()

    # ------------------------------------------------------------------
    # Enregistrement des items (appelé quand on peuple l’UI)
    # ------------------------------------------------------------------
    def register_item(self, item_type, identifier, item):
        """
        Associe l'item à un (item_type, identifier) et connecte le tree_widget s'il ne l'est pas déjà.

        item_type: "layers", "layer_groups", "themes", "layouts", "relations",
                   "styles", "theme_layers", "theme_styles", "relation_fields"
        identifier: str unique (ex: layer_id, theme|layer_id, theme|layer_id|style, ...)
        """
        if not isinstance(item_type, str):
            raise ValueError("item_type doit être une chaîne")
        if not isinstance(identifier, str):
            identifier = str(identifier)

        # Stocke le couple (type, id) dans l'item
        item.setData(0, Qt.ItemDataRole.UserRole, (item_type, identifier))

        # Connecte le widget une seule fois
        tree = item.treeWidget()
        if tree and tree not in self.connected_widgets:
            tree.itemChanged.connect(self._on_item_changed)
            self.connected_widgets.add(tree)

    # ------------------------------------------------------------------
    # Lecture / reconstruction "on demand"
    # ------------------------------------------------------------------
    def get_selected_elements(self):
        """
        Retourne un dict de sets avec UNIQUEMENT les items cochés actuellement dans les arbres.
        """
        out = {
            "layers": set(),
            "layer_groups": set(),
            "themes": set(),
            "layouts": set(),
            "relations": set(),
            "styles": set(),
            "theme_layers": set(),
            "theme_styles": set(),
            "relation_fields": set(),
        }

        for tree in list(self.connected_widgets):
            root = tree.invisibleRootItem()
            for item in self._iter_items(root):
                if item.checkState(0) != Qt.CheckState.Checked:
                    continue
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if not data or not isinstance(data, tuple) or len(data) != 2:
                    continue
                item_type, identifier = data
                if item_type in out and identifier:
                    out[item_type].add(identifier)

        return out

    # ------------------------------------------------------------------
    # Auto-pré-sélection des relations
    # ------------------------------------------------------------------
    def _on_item_changed(self, item, column):
        """
        Dès qu'un item change, on essaie de pré-cocher les relations dont parent+enfant sont présents.
        """
        try:
            self._auto_check_relations_based_on_layers()
        except Exception as e:
            print("[SelectionManager] auto-check relations error:", e)

    def _auto_check_relations_based_on_layers(self):
        """
        Si (parent_lid AND child_lid) sont dans l'ensemble des couches effectivement cochées
        (couches OU couches issues des thèmes), on coche la relation correspondante.
        On ne force PAS la décoché (on laisse l'utilisateur libre de décocher).
        """
        selected = self.get_selected_elements()
        eff_layers = self._effective_selected_layer_ids(selected)

        # Pour chaque item "relations", on récupère sa métadonnée (parent_lid, child_lid)
        for tree in list(self.connected_widgets):
            root = tree.invisibleRootItem()
            for it in self._iter_items(root):
                data = it.data(0, Qt.ItemDataRole.UserRole)
                if not data or data[0] != "relations":
                    continue
                meta = it.data(0, Qt.ItemDataRole.UserRole + 1)
                if not meta or not isinstance(meta, tuple) or len(meta) < 3 or meta[0] != "rel_layers":
                    continue
                _tag, parent_lid, child_lid = meta
                if parent_lid and child_lid and parent_lid in eff_layers and child_lid in eff_layers:
                    if it.checkState(0) != Qt.Checked:
                        it.setCheckState(0, Qt.Checked)  # pré-sélection
                        # NB: ceci déclenchera _on_item_changed à nouveau, mais c'est ok.

    def _effective_selected_layer_ids(self, selected_dict):
        """
        Union des IDs de couches cochées directement et celles cochées via Thèmes.
        - 'layers' → {layer_id}
        - 'theme_layers' → tokens 'theme|layer_id'
        - 'theme_styles' → tokens 'theme|layer_id|style'
        """
        eff = set()

        # Couches directes
        for lid in selected_dict.get("layers", set()):
            eff.add(lid)

        # Couches via Thèmes (niveau couche)
        for token in selected_dict.get("theme_layers", set()):
            if "|" in token:
                try:
                    _theme, lid = token.split("|", 1)
                    if lid:
                        eff.add(lid)
                except ValueError:
                    pass

        # Couches via Thèmes (niveau style)
        for token in selected_dict.get("theme_styles", set()):
            if "|" in token:
                parts = token.split("|")
                if len(parts) >= 2 and parts[1]:
                    eff.add(parts[1])

        return eff

    # ------------------------------------------------------------------
    # Divers utilitaires
    # ------------------------------------------------------------------
    def clear_selection(self):
        """Décocher visuellement tout (optionnel)."""
        for tree in list(self.connected_widgets):
            root = tree.invisibleRootItem()
            for item in self._iter_items(root):
                item.setCheckState(0, Qt.Unchecked)

    def reset(self):
        """Oublie les widgets connectés (utile quand on reconstruit l’UI)."""
        self.connected_widgets.clear()

    def _iter_items(self, root_item):
        """Itérateur DFS sur tous les items d'un QTreeWidget."""
        stack = [root_item]
        while stack:
            node = stack.pop()
            for i in range(node.childCount()):
                child = node.child(i)
                yield child
                stack.append(child)