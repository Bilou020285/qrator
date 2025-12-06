# qrator/selection_manager.py
from qgis.PyQt.QtCore import Qt


class SelectionManager:
    """Gestionnaire des sélections multi-onglets.

    Idée clé : on NE garde aucun cache de sélection « parallèle ».
    Quand on a besoin de connaître l'état, on relit les widgets
    via :meth:`get_selected_elements`.

    Fonctionnalités :
    - Enregistrement centralisé de tous les items cochables via :meth:`register_item`
      (couches, thèmes, styles, layouts, relations…).
    - Auto-pré-sélection des relations : si *parent_lid* ET *child_lid* sont
      présents parmi les couches effectivement sélectionnées (directement ou
      via les thèmes), on coche automatiquement la relation.
    - Synchronisation visuelle Thèmes → Couches : lorsqu'on coche / décoche
      des éléments dans l'onglet *Thèmes*, l'onglet *Couches* reflète cette
      sélection (couches + styles), tout en conservant les choix manuels
      faits directement dans *Couches*.
    """

    def __init__(self):
        # QTreeWidget déjà connectés au signal itemChanged
        self.connected_widgets = set()

        # Registre des items : item_type -> {identifier -> QTreeWidgetItem}
        # Exemple :
        #   - "layers"       -> {"layer_id" -> item_layer}
        #   - "styles"       -> {"layer_id|style" -> item_style}
        #   - "theme_layers" -> {"theme|layer_id" -> item_theme_layer}
        self._registry = {}

        # État interne pour la synchro Thèmes -> Couches
        # (sélection issue UNIQUEMENT des thèmes, sans les choix manuels)
        self._theme_layers_effective = set()   # set[str]    (layer_id)
        self._theme_styles_effective = set()   # set[str]    ("layer_id|style")

        # Drapeau pour éviter la récursion lors des mises à jour programmatiques
        self._updating_from_themes = False

    # ------------------------------------------------------------------
    # Enregistrement des items (appelé quand on peuple l’UI)
    # ------------------------------------------------------------------
    def register_item(self, item_type, identifier, item):
        """Associe *item* à un couple (*item_type*, *identifier*).

        Parameters
        ----------
        item_type : str
            "layers", "layer_groups", "themes", "layouts", "relations",
            "styles", "theme_layers", "theme_styles", "relation_fields", …
        identifier : str
            Identifiant contractuel (ex. layer_id, "theme|layer_id",
            "theme|layer_id|style", …)
        item : QTreeWidgetItem
        """
        if not isinstance(item_type, str):
            raise ValueError("item_type doit être une chaîne")

        if not isinstance(identifier, str):
            identifier = str(identifier)

        # 1) Mémoriser dans le registre
        self._registry.setdefault(item_type, {})[identifier] = item

        # 2) Stocker le couple (type, id) directement sur l'item
        item.setData(0, Qt.ItemDataRole.UserRole, (item_type, identifier))

        # 3) Connecter le widget UNE SEULE fois au signal itemChanged
        tree = item.treeWidget()
        if tree and tree not in self.connected_widgets:
            tree.itemChanged.connect(self._on_item_changed)
            self.connected_widgets.add(tree)

    # ------------------------------------------------------------------
    # Lecture / reconstruction "on demand"
    # ------------------------------------------------------------------
    def get_selected_elements(self):
        """Retourne un dict de set contenant UNIQUEMENT
        les items actuellement cochés dans les arbres.

        Clés standard (toujours présentes) :
        - "layers"
        - "layer_groups"
        - "themes"
        - "layouts"
        - "relations"
        - "styles"
        - "theme_layers"
        - "theme_styles"
        - "relation_fields"
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

        # On relit l'état réel des widgets, sans cache
        for tree in list(self.connected_widgets):
            if tree is None:
                continue
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
    # Gestion des changements (synchro Thèmes → Couches + relations)
    # ------------------------------------------------------------------
    def _on_item_changed(self, item, column):
        """Callback global appelé dès qu'un item change de checkState.

        - Si la modification vient de l'onglet *Thèmes* (types "themes",
          "theme_layers" ou "theme_styles"), on resynchronise l'onglet
          *Couches* pour refléter la sélection.
        - Dans les autres cas, on tente la pré-sélection des relations.
        """
        # On ignore les évènements générés par nos propres setCheckState()
        if self._updating_from_themes:
            return

        # Récupérer le type d'item
        data = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = None
        if data and isinstance(data, tuple) and len(data) == 2:
            item_type = data[0]

        try:
            if item_type in {"themes", "theme_layers", "theme_styles"}:
                # Synchro Thèmes -> Couches (met à jour couches/styles)
                self._sync_layers_from_themes()
            else:
                # Changements directs dans Couches / Layouts / Relations…
                self._auto_check_relations_based_on_layers()
        except Exception as e:
            # Simple log dans la console de QGIS (pas d'exception bloquante)
            print("[SelectionManager] item_changed error:", e)

    def _sync_layers_from_themes(self):
        """Met à jour visuellement l'onglet *Couches* à partir de l'état
        courant de l'onglet *Thèmes*.

        Principe :
        - On considère que les couches/styles cochés dans *Couches* proviennent
          (1) soit de l'utilisateur (sélection manuelle),
          (2) soit d'une sélection via les thèmes.
        - On calcule d'abord l'ancienne contribution des thèmes
          (self._theme_*_effective), puis la nouvelle contribution des
          thèmes à partir de l'état actuel des arbres.
        - La sélection manuelle est donc::

              manuel = actuel - ancien_theme

        - La nouvelle sélection à afficher dans *Couches* est alors::

              cible = manuel ∪ nouveau_theme
        """
        # Empêcher les callbacks récursifs pendant qu'on modifie les états
        self._updating_from_themes = True
        try:
            selected_now = self.get_selected_elements()

            # Sélection courante dans l'onglet Couches
            current_layers = set(selected_now.get("layers", set()))
            current_styles = set(selected_now.get("styles", set()))

            # Contribution MANUELLE (ce que l'utilisateur a explicitement coché
            # dans Couches, en dehors des thèmes)
            manual_layers = current_layers - self._theme_layers_effective
            manual_styles = current_styles - self._theme_styles_effective

            # --- Nouvelle contribution issue des thèmes ---

            # Tokens de thèmes actuellement cochés
            theme_layer_tokens = set(selected_now.get("theme_layers", set()))
            theme_style_tokens = set(selected_now.get("theme_styles", set()))

            # 1) Couches issues uniquement des thèmes
            themes_dict = {
                "layers": set(),
                "theme_layers": theme_layer_tokens,
                "theme_styles": theme_style_tokens,
            }
            new_theme_layers_effective = self._effective_selected_layer_ids(themes_dict)

            # 2) Styles issus des thèmes : "theme|layer_id|style" -> "layer_id|style"
            new_theme_styles_effective = set()
            for token in theme_style_tokens:
                if "|" not in token:
                    continue
                parts = token.split("|")
                if len(parts) >= 3:
                    lid, style = parts[1], parts[2]
                    if lid and style is not None:
                        new_theme_styles_effective.add(f"{lid}|{style}")

            # Sélection cible = contribution manuelle ∪ contribution des thèmes
            target_layers = manual_layers.union(new_theme_layers_effective)
            target_styles = manual_styles.union(new_theme_styles_effective)

            # --- Appliquer aux items de l'onglet COUCHES ---

            # Couches
            for lid, it in list(self._registry.get("layers", {}).items()):
                if it is None or it.treeWidget() is None:
                    continue
                desired = Qt.CheckState.Checked if lid in target_layers else Qt.CheckState.Unchecked
                if it.checkState(0) != desired:
                    it.setCheckState(0, desired)

            # Styles
            for token, it in list(self._registry.get("styles", {}).items()):
                if it is None or it.treeWidget() is None:
                    continue
                desired = Qt.CheckState.Checked if token in target_styles else Qt.CheckState.Unchecked
                if it.checkState(0) != desired:
                    it.setCheckState(0, desired)

            # Mettre à jour notre mémoire de la contribution des thèmes
            self._theme_layers_effective = new_theme_layers_effective
            self._theme_styles_effective = new_theme_styles_effective
        finally:
            self._updating_from_themes = False

        # Après la synchro, on recalcule les relations éventuellement à cocher
        try:
            self._auto_check_relations_based_on_layers()
        except Exception as e:
            print("[SelectionManager] auto-check after sync error:", e)

    # ------------------------------------------------------------------
    # Auto-pré-sélection des relations
    # ------------------------------------------------------------------
    def _auto_check_relations_based_on_layers(self):
        """Pré-sélectionne les relations dont les deux couches (parent/enfant)
        sont présentes dans l'ensemble des couches effectivement sélectionnées.

        On ne force pas la décoché : l'utilisateur reste libre de décocher
        une relation même si les deux couches sont sélectionnées.
        """
        selected = self.get_selected_elements()
        eff_layers = self._effective_selected_layer_ids(selected)

        # Parcourt tous les items "relations" connus
        for tree in list(self.connected_widgets):
            if tree is None:
                continue
            root = tree.invisibleRootItem()
            for it in self._iter_items(root):
                data = it.data(0, Qt.ItemDataRole.UserRole)
                if not data or data[0] != "relations":
                    continue
                meta = it.data(0, Qt.ItemDataRole.UserRole + 1)
                if (
                    not meta
                    or not isinstance(meta, tuple)
                    or len(meta) < 3
                    or meta[0] != "rel_layers"
                ):
                    continue
                _tag, parent_lid, child_lid = meta
                if parent_lid and child_lid and parent_lid in eff_layers and child_lid in eff_layers:
                    if it.checkState(0) != Qt.CheckState.Checked:
                        # Pré-sélection (déclenchera _on_item_changed, mais l'appel
                        # suivant n'aura plus d'effet et s'arrêtera rapidement)
                        it.setCheckState(0, Qt.CheckState.Checked)

    def _effective_selected_layer_ids(self, selected_dict):
        """Retourne l'union des IDs de couches cochées directement ET
        via les thèmes.

        - "layers"       → {layer_id}
        - "theme_layers" → tokens "theme|layer_id"
        - "theme_styles" → tokens "theme|layer_id|style"
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
        """Décoche visuellement tout (tous les arbres connectés)."""
        for tree in list(self.connected_widgets):
            if tree is None:
                continue
            root = tree.invisibleRootItem()
            for item in self._iter_items(root):
                item.setCheckState(0, Qt.CheckState.Unchecked)

        # Réinitialise aussi la contribution "thèmes" (tout est décoché)
        self._theme_layers_effective.clear()
        self._theme_styles_effective.clear()

    def reset(self):
        """Oublie les widgets connectés et le registre.

        À appeler lorsqu'on reconstruit complètement l'UI
        (nouveau projet chargé, fermeture de la boîte de dialogue, …).
        """
        self.connected_widgets.clear()
        self._registry.clear()
        self._theme_layers_effective.clear()
        self._theme_styles_effective.clear()
        self._updating_from_themes = False

    def _iter_items(self, root_item):
        """Itérateur DFS sur tous les items d'un QTreeWidget.

        Parameters
        ----------
        root_item : QTreeWidgetItem
            Racine invisible (tree.invisibleRootItem())
        """
        if root_item is None:
            return
        stack = [root_item]
        while stack:
            node = stack.pop()
            for i in range(node.childCount()):
                child = node.child(i)
                if child is not None:
                    yield child
                    stack.append(child)