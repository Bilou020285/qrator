# report_context.py
from qgis.core import QgsProject

class FakeTreeWidget:
    """Simule un QTreeWidget pour les parsers."""
    def __init__(self):
        self.items = []
        self.selected_items = set()

    def clear(self):
        """Méthode factice pour vider le widget."""
        self.items = []
        self.selected_items.clear()

    def addTopLevelItem(self, item):
        """Simule l'ajout d'un item."""
        self.items.append(item)

    def findItems(self, text, flags=0):
        """Simule la recherche d'items."""
        return [item for item in self.items if hasattr(item, 'text') and item.text(0) == text]

class FakeSelectionManager:
    """Simule le gestionnaire de sélection de QRator."""
    def __init__(self):
        self.selected_items = set()

    def clear(self):
        """Efface la sélection."""
        self.selected_items.clear()

    def is_selected(self, item_id):
        """Vérifie si un item est sélectionné."""
        return str(item_id) in self.selected_items

    def select(self, item_id, selected=True):
        """Sélectionne/désélectionne un item."""
        if selected:
            self.selected_items.add(str(item_id))
        else:
            self.selected_items.discard(str(item_id))

class ReportContext:
    """Contexte minimal pour les parsers QRator."""
    def __init__(self, xml_root):
        self.xml_root = xml_root
        self.tree_widget = FakeTreeWidget()
        self.selection_manager = FakeSelectionManager()
        self.project = QgsProject.instance()