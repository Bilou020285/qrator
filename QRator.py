# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsProject
from .QRator_dialog import QRatorDialog  # Fenêtre principale
from qgis.PyQt.QtGui import QIcon
import os

class QRator:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None  # référence courante de la fenêtre

    def initGui(self):
        plugin_dir = os.path.dirname(__file__)
        icon_path = os.path.join(plugin_dir, "icons", "icon.png")

        self.action = QAction(QIcon(icon_path), "Lancer QRator", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        # Menu « Extensions »
        self.iface.addPluginToMenu("&QRator", self.action)

        # (Optionnel) Ajouter une icône dans la barre d’outils
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        # Nettoyage du menu
        try:
            self.iface.removePluginMenu("&QRator", self.action)
        except Exception:
            pass
        # Si une fenêtre existe, on la ferme et on oublie la ref
        if self.dialog is not None:
            try:
                self.dialog.close()
            except Exception:
                pass
            self.dialog = None

    def run(self):
        # Petit message informatif
        project = QgsProject.instance()
        project_path = project.fileName()
        self.iface.messageBar().pushMessage("QRator", f"Projet chargé : {project_path}", level=0)

        # Fermer toute instance précédente si elle traîne encore
        if self.dialog is not None:
            try:
                self.dialog.close()
            except Exception:
                pass
            self.dialog = None

        # CRÉER TOUJOURS UNE NOUVELLE FENÊTRE
        # (si ton QRatorDialog prend un argument iface, fais QRatorDialog(self.iface))
        self.dialog = QRatorDialog()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()