from qgis.PyQt.QtWidgets import (QDialog, QMessageBox, QTreeWidgetItem, QFileDialog,
                                QLabel, QHeaderView, QProgressDialog, QSizePolicy, QApplication)
from qgis.PyQt.QtCore import Qt, QPoint
from qgis.PyQt.QtGui import QFont
from .ui.QRator_dialog import Ui_QRatorDialog
from .selection_manager import SelectionManager
from .qgz_manager import open_project, save_new_project
from .parse_layers import parse_layers
from .parse_themes import parse_themes
from .parse_layouts_relations import parse_layouts_relations
from .html_report_generator import HTMLReportGenerator  # Nouveau module
import os
import datetime
from qgis.core import QgsApplication, QgsProject, QgsLayoutExporter
from qgis.PyQt.QtGui import QPixmap, QGuiApplication, QIcon  # Ajoutez QPixmap à vos imports existants
from qgis.PyQt.QtWidgets import QMenu, QAction, QCheckBox
import tempfile


class QRatorDialog(QDialog, Ui_QRatorDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # === QRator: Checkbox "Déconnecter les sources locales" ===
        def _init_disconnect_checkbox(self):
            """Crée et insère la case juste au-dessus de la ligne 'Chemin du projet modifié (.qgz)...'."""
            self.chk_disconnect_local = QCheckBox("Déconnecter les sources de données locales", self)
            self.chk_disconnect_local.setToolTip(
                "Si coché : les couches locales (SHP, GPKG/SpatiaLite, CSV, rasters, etc.) "
                "seront volontairement 'cassées' dans le projet généré pour que QGIS propose "
                "de les réadresser à l'ouverture. Les couches distantes (PostGIS, WMS/WFS/WMTS, "
                "XYZ, ArcGIS, vectortiles, etc.) sont conservées."
            )

            # État par défaut : toujours décoché
            self.chk_disconnect_local.setChecked(False)

            # Insertion juste avant outputLayout dans mainLayout
            try:
                main = getattr(self, "mainLayout", None)
                out_lay = getattr(self, "outputLayout", None)
                if main is not None and out_lay is not None:
                    insert_idx = main.count()
                    for i in range(main.count()):
                        item = main.itemAt(i)
                        if item is not None and item.layout() is out_lay:
                            insert_idx = i
                            break
                    main.insertWidget(insert_idx, self.chk_disconnect_local)
                else:
                    self.mainLayout.addWidget(self.chk_disconnect_local)
            except Exception:
                self.mainLayout.addWidget(self.chk_disconnect_local)

        # Appel d'init
        self._init_disconnect_checkbox = _init_disconnect_checkbox.__get__(self, self.__class__)
        self._init_disconnect_checkbox()
        # === /QRator: Checkbox ===

        # Couches (déjà présent chez toi)
        if hasattr(self, 'layerTree') and hasattr(self.layerTree.header(), 'setSectionResizeMode'):
            self.layerTree.header().setSectionResizeMode(0, QHeaderView.Stretch)

        # Thèmes
        if hasattr(self, 'themeTree') and hasattr(self.themeTree.header(), 'setSectionResizeMode'):
            self.themeTree.header().setSectionResizeMode(0, QHeaderView.Stretch)

        # Mises en page
        if hasattr(self, 'layoutTree') and hasattr(self.layoutTree.header(), 'setSectionResizeMode'):
            self.layoutTree.header().setSectionResizeMode(0, QHeaderView.Stretch)

        # Relations
        if hasattr(self, 'relationTree') and hasattr(self.relationTree.header(), 'setSectionResizeMode'):
            self.relationTree.header().setSectionResizeMode(0, QHeaderView.Stretch)

        # Menus contextuels sur les arbres où il y a des styles

        for tree_name in ("layersTree", "layerTree", "themeTree"):
            tw = getattr(self, tree_name, None)
            if tw is not None:
                tw.setContextMenuPolicy(Qt.CustomContextMenu)
                tw.customContextMenuRequested.connect(self._on_tree_context_menu)

        def _stretch_tree_headers(tree):
            if not tree:
                return
            tree.setHeaderHidden(False)  # <- au cas où un header serait masqué
            hdr = tree.header()
            if hdr is not None:
                hdr.setStretchLastSection(True)
                hdr.setSectionResizeMode(0, QHeaderView.Stretch)
            tree.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))

        for t in [getattr(self, "layerTree", None),
                  getattr(self, "themeTree", None),
                  getattr(self, "layoutTree", None),
                  getattr(self, "relationTree", None)]:
            _stretch_tree_headers(t)

        # Menu contextuel sur l'onglet Mises en page
        if hasattr(self, "layoutTree") and self.layoutTree is not None:
            self.layoutTree.setContextMenuPolicy(Qt.CustomContextMenu)
            self.layoutTree.customContextMenuRequested.connect(self._on_layouts_context_menu)
        
        # Configuration de base
        self.setWindowTitle("QRator - QGIS Project Manager")
        self.setMinimumSize(900, 700)

        # Chargement du logo
        self._load_logo()

        # Application des styles
        self.apply_styles()

        # Configuration des tooltips et icônes
        self._setup_tooltips()

        # Configuration de la barre de statut
        self._setup_status_bar()

        # Initialisation
        self.selection_manager = SelectionManager()
        self.current_project_path = None

        # Cache de projet temporaire pour les styles (évite de relire le .qgz à chaque action)
        self._style_tmp_project = None
        self._style_tmp_project_path = ""

        # Connexions des signaux principaux
        if hasattr(self, 'loadProjectButton'):
            self.loadProjectButton.clicked.connect(self.open_project)
        if hasattr(self, 'refreshButton'):
            self.refreshButton.clicked.connect(self.refresh_analysis)
        if hasattr(self, 'exportButton'):
            self.exportButton.clicked.connect(self.export_to_html)
        if hasattr(self, 'saveProjectButton'):
            self.saveProjectButton.clicked.connect(self.export_project)
        if hasattr(self, 'closeButton'):
            self.closeButton.clicked.connect(self.close)
        if hasattr(self, 'browseOutputButton'):
            self.browseOutputButton.clicked.connect(self.browse_output_path)

        # Connexions des boutons de sélection (NOUVEAU)
        self._connect_selection_buttons()   

        #Détruit l'objet à la fermeture
        self.setAttribute(Qt.WA_DeleteOnClose, True)

    def _setup_tooltips(self):
        """Configure les infobulles et les icônes pour une meilleure expérience utilisateur."""
        try:
            # Boutons principaux
            if hasattr(self, 'loadProjectButton'):
                self.loadProjectButton.setToolTip("Open a QGIS project file (.qgs or .qgz)")
                try:
                    self.loadProjectButton.setIcon(QgsApplication.getThemeIcon("/mActionFileOpen.svg"))
                except:
                    pass  # Si l'icône ne peut pas être chargée, on continue sans

            if hasattr(self, 'saveProjectButton'):
                self.saveProjectButton.setToolTip("Save the filtered project as a new .qgz file")
                try:
                    self.saveProjectButton.setIcon(QgsApplication.getThemeIcon("/mActionFileSave.svg"))
                except:
                    pass

            if hasattr(self, 'refreshButton'):
                self.refreshButton.setToolTip("Refresh the project analysis")
                try:
                    self.refreshButton.setIcon(QgsApplication.getThemeIcon("/mActionRefresh.svg"))
                except:
                    pass

            if hasattr(self, 'exportButton'):
                self.exportButton.setToolTip("Generate an HTML report of the project")
                try:
                    self.exportButton.setIcon(QgsApplication.getThemeIcon("/mActionFilePrint.svg"))
                except:
                    pass

            if hasattr(self, 'browseOutputButton'):
                self.browseOutputButton.setToolTip("Browse output location")
                try:
                    self.browseOutputButton.setIcon(QgsApplication.getThemeIcon("/mActionFileOpen.svg"))
                except:
                    pass

            # Boutons de sélection pour les couches
            if hasattr(self, 'selectAllLayersButton'):
                self.selectAllLayersButton.setToolTip("Sélectionner toutes les couches et groupes")
                try:
                    self.selectAllLayersButton.setIcon(QgsApplication.getThemeIcon("/mActionSelectAll.svg"))
                except:
                    pass

            if hasattr(self, 'deselectAllLayersButton'):
                self.deselectAllLayersButton.setToolTip("Désélectionner toutes les couches et groupes")
                try:
                    self.deselectAllLayersButton.setIcon(QgsApplication.getThemeIcon("/mActionDeselectAll.svg"))
                except:
                    pass

            if hasattr(self, 'invertLayerSelectionButton'):
                self.invertLayerSelectionButton.setToolTip("Inverser la sélection des couches et groupes")
                try:
                    self.invertLayerSelectionButton.setIcon(QgsApplication.getThemeIcon("/mActionInvertSelection.svg"))
                except:
                    pass

            # Boutons de sélection pour les thèmes
            if hasattr(self, 'selectAllThemesButton'):
                self.selectAllThemesButton.setToolTip("Sélectionner tous les thèmes")
                try:
                    self.selectAllThemesButton.setIcon(QgsApplication.getThemeIcon("/mActionSelectAll.svg"))
                except:
                    pass

            if hasattr(self, 'deselectAllThemesButton'):
                self.deselectAllThemesButton.setToolTip("Désélectionner tous les thèmes")
                try:
                    self.deselectAllThemesButton.setIcon(QgsApplication.getThemeIcon("/mActionDeselectAll.svg"))
                except:
                    pass

            if hasattr(self, 'invertThemeSelectionButton'):
                self.invertThemeSelectionButton.setToolTip("Inverser la sélection des thèmes")
                try:
                    self.invertThemeSelectionButton.setIcon(QgsApplication.getThemeIcon("/mActionInvertSelection.svg"))
                except:
                    pass

            # Boutons de sélection pour les mises en page
            if hasattr(self, 'selectAllLayoutsButton'):
                self.selectAllLayoutsButton.setToolTip("Sélectionner toutes les mises en page")
                try:
                    self.selectAllLayoutsButton.setIcon(QgsApplication.getThemeIcon("/mActionSelectAll.svg"))
                except:
                    pass

            if hasattr(self, 'deselectAllLayoutsButton'):
                self.deselectAllLayoutsButton.setToolTip("Désélectionner toutes les mises en page")
                try:
                    self.deselectAllLayoutsButton.setIcon(QgsApplication.getThemeIcon("/mActionDeselectAll.svg"))
                except:
                    pass

            if hasattr(self, 'invertLayoutSelectionButton'):
                self.invertLayoutSelectionButton.setToolTip("Inverser la sélection des mises en page")
                try:
                    self.invertLayoutSelectionButton.setIcon(QgsApplication.getThemeIcon("/mActionInvertSelection.svg"))
                except:
                    pass     

            # Boutons de sélection pour les relations
            if hasattr(self, 'selectAllRelationsButton'):
                self.selectAllRelationsButton.setToolTip("Sélectionner toutes les relations")
                try:
                    self.selectAllRelationsButton.setIcon(QgsApplication.getThemeIcon("/mActionSelectAll.svg"))
                except:
                    pass

            if hasattr(self, 'deselectAllRelationsButton'):
                self.deselectAllRelationsButton.setToolTip("Désélectionner toutes les relations")
                try:
                    self.deselectAllRelationsButton.setIcon(QgsApplication.getThemeIcon("/mActionDeselectAll.svg"))
                except:
                    pass

            if hasattr(self, 'invertRelationSelectionButton'):
                self.invertRelationSelectionButton.setToolTip("Inverser la sélection des relations")
                try:
                    self.invertRelationSelectionButton.setIcon(QgsApplication.getThemeIcon("/mActionInvertSelection.svg"))
                except:
                    pass                              

        except Exception as e:
            print(f"Erreur lors de la configuration des tooltips: {str(e)}")

    def _load_logo(self):
        """Charge le logo de manière sécurisée sans dépendre des ressources"""
        try:
            if hasattr(self, 'logoLabel'):
                # Chemin relatif depuis le dossier du plugin
                plugin_dir = os.path.dirname(__file__)
                logo_path = os.path.join(plugin_dir, "icons", "icon.png")

                if os.path.exists(logo_path):
                    pixmap = QPixmap(logo_path)
                    if not pixmap.isNull():
                        # Redimensionner si nécessaire
                        max_height = 60
                        if pixmap.height() > max_height:
                            pixmap = pixmap.scaledToHeight(max_height, Qt.SmoothTransformation)
                        self.logoLabel.setPixmap(pixmap)
                    else:
                        self._set_fallback_logo()
                else:
                    self._set_fallback_logo()
        except Exception as e:
            print(f"Error loading logo: {str(e)}")
            self._set_fallback_logo()

    def _set_fallback_logo(self):
        """Affiche un logo de remplacement si le fichier n'est pas trouvé"""
        if hasattr(self, 'logoLabel'):
            self.logoLabel.setText("QRator")
            self.logoLabel.setStyleSheet("""
                QLabel {
                    font-size: 18px;
                    font-weight: bold;
                    color: #2c3e50;
                    qproperty-alignment: AlignCenter;
                }
            """)
            self.logoLabel.setMinimumHeight(40)        

    def _connect_selection_buttons(self):
        """Connecte les boutons de sélection pour chaque onglet"""
        # Boutons pour les couches
        if hasattr(self, 'selectAllLayersButton'):
            self.selectAllLayersButton.clicked.connect(lambda: self._select_all_items(self.layerTree))
        if hasattr(self, 'deselectAllLayersButton'):
            self.deselectAllLayersButton.clicked.connect(lambda: self._deselect_all_items(self.layerTree))
        if hasattr(self, 'invertLayerSelectionButton'):
            self.invertLayerSelectionButton.clicked.connect(lambda: self._invert_selection(self.layerTree))

        # Boutons pour les thèmes
        if hasattr(self, 'selectAllThemesButton'):
            self.selectAllThemesButton.clicked.connect(lambda: self._select_all_items(self.themeTree))
        if hasattr(self, 'deselectAllThemesButton'):
            self.deselectAllThemesButton.clicked.connect(lambda: self._deselect_all_items(self.themeTree))
        if hasattr(self, 'invertThemeSelectionButton'):
            self.invertThemeSelectionButton.clicked.connect(lambda: self._invert_selection(self.themeTree))

        # Boutons pour les mises en page
        if hasattr(self, 'selectAllLayoutsButton'):
            self.selectAllLayoutsButton.clicked.connect(lambda: self._select_all_items(self.layoutTree))
        if hasattr(self, 'deselectAllLayoutsButton'):
            self.deselectAllLayoutsButton.clicked.connect(lambda: self._deselect_all_items(self.layoutTree))
        if hasattr(self, 'invertLayoutSelectionButton'):
            self.invertLayoutSelectionButton.clicked.connect(lambda: self._invert_selection(self.layoutTree))

        # Boutons pour les relations
        if hasattr(self, 'selectAllRelationsButton'):
            self.selectAllRelationsButton.clicked.connect(lambda: self._select_all_items(self.relationTree))
        if hasattr(self, 'deselectAllRelationsButton'):
            self.deselectAllRelationsButton.clicked.connect(lambda: self._deselect_all_items(self.relationTree))
        if hasattr(self, 'invertRelationSelectionButton'):
            self.invertRelationSelectionButton.clicked.connect(lambda: self._invert_selection(self.relationTree))

    def _select_all_items(self, tree_widget):
        """Sélectionne tous les items d'un QTreeWidget"""
        if not tree_widget:
            return

        self.update_status(f"Selecting all items in {tree_widget.objectName()}...")
        root = tree_widget.invisibleRootItem()
        self._set_check_state_recursive(root, Qt.Checked)
        self.update_status("All items selected")

    def _deselect_all_items(self, tree_widget):
        """Désélectionne tous les items d'un QTreeWidget"""
        if not tree_widget:
            return

        self.update_status(f"Deselecting all items in {tree_widget.objectName()}...")
        root = tree_widget.invisibleRootItem()
        self._set_check_state_recursive(root, Qt.Unchecked)
        self.update_status("All items deselected")

    def _invert_selection(self, tree_widget):
        """Inverse la sélection des items d'un QTreeWidget"""
        if not tree_widget:
            return

        self.update_status(f"Inverting selection in {tree_widget.objectName()}...")
        root = tree_widget.invisibleRootItem()
        self._invert_check_state_recursive(root)
        self.update_status("Selection inverted")

    def _set_check_state_recursive(self, item, state):
        """Définir récursivement l'état de coche pour un item et ses enfants"""
        item.setCheckState(0, state)
        for i in range(item.childCount()):
            self._set_check_state_recursive(item.child(i), state)

    def _invert_check_state_recursive(self, item):
        """Inverser récursivement l'état de coche pour un item et ses enfants"""
        current_state = item.checkState(0)
        new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
        item.setCheckState(0, new_state)
        for i in range(item.childCount()):
            self._invert_check_state_recursive(item.child(i))              

    def _setup_status_bar(self):
        """Configure la barre de statut"""
        self.status_label = QLabel()
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #f8f9fa;
                border-top: 1px solid #ddd;
                padding: 5px;
                font-size: 9pt;
                color: #666;
            }
        """)
        self.status_label.setText("Ready")

        # Ajout au layout principal
        # Note: Vous devrez adapter cette partie selon votre UI réelle
        # Soit via Qt Designer, soit en modifiant le layout programmatiquement
        if hasattr(self, 'verticalLayout'):
            self.verticalLayout.addWidget(self.status_label)

    def update_status(self, message):
        """Met à jour le message de statut"""
        if hasattr(self, 'status_label'):
            self.status_label.setText(message)

    def apply_styles(self):
        """Applique un style moderne à l'interface."""
        self.setStyleSheet("""
            /* Style général */
            QDialog {
                background-color: #727272;
            }

            /* Arbres */
            QTreeWidget {
                alternate-background-color: #f0f0f0;
                background-color: #ffffff;
                font-size: 10pt;
                border: 1px solid #ddd;
                border-radius: 3px;
            }
            QTreeWidget::item {
                padding: 3px;
            }
            QTreeWidget::item:selected {
                background: #e0e0e0;
            }

            /* Boutons */
            QPushButton {
                padding: 6px 12px;
                min-height: 30px;
                min-width: 100px;
                background-color: #727272;
                border: 1px solid #c0c0c0;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #e9ecef;
            }
            QPushButton:pressed {
                background-color: #dee2e6;
            }

            /* Champs de texte */
            QLineEdit, QTextEdit {
                padding: 5px;
                border: 1px solid #c0c0c0;
                border-radius: 3px;
                background: #b2b2b2;
            }

            /* Onglets */
            QTabWidget::pane {
                border: 1px solid #c0c0c0;
                border-radius: 3px;
                background: #b2b2b2;
            }
            QTabBar::tab {
                padding: 8px 12px;
                min-width: 120px;
                background: #b2b2b2;
                border: 1px solid #ddd;
                border-top-left-radius: 3px;
                border-top-right-radius: 3px;
            }
            QTabBar::tab:selected {
                background: #b2b2b2;
                border-bottom-color: white;
                font-weight: bold;
            }

            /* Zone de résultat */
            QTextEdit {
                border: 1px solid #c0c0c0;
                border-radius: 3px;
                background: #b2b2b2;
                font-family: Courier, monospace;
            }
        """)

    def show_progress(self, message, max_value=100):
        """Affiche une barre de progression"""
        self.progress = QProgressDialog(message, "Cancel", 0, max_value, self)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setWindowTitle("Processing")
        self.progress.setValue(0)
        self.progress.show()
        QApplication.processEvents()

    def update_progress(self, value):
        """Met à jour la barre de progression"""
        if hasattr(self, 'progress'):
            self.progress.setValue(value)
            QApplication.processEvents()

    def hide_progress(self):
        """Cache la barre de progression"""
        if hasattr(self, 'progress'):
            self.progress.hide()
            del self.progress

    def browse_output_path(self):
        """Ouvre une boîte de dialogue pour choisir le chemin de sortie."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Modified Project",
            "",
            "QGIS Files (*.qgz)"
        )
        if file_path:
            if not file_path.endswith('.qgz'):
                file_path += '.qgz'
            self.modifiedPathLineEdit.setText(file_path)

    def open_project(self):
        """Ouvre un projet QGIS et remplit les arbres."""
        self.update_status("Opening project...")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open a QGIS Project",
            "",
            "QGIS Files (*.qgs *.qgz)"
        )
        if file_path:
            try:
                self.update_status("Loading project...")
                # Effacer les sélections précédentes
                self.selection_manager.clear_selection()
                xml_root, info = open_project(file_path)
                self.current_project_path = file_path
                self.projectPathLineEdit.setText(file_path)
                # Remplir les arbres avec des éléments décochés par défaut
                self.fill_trees(xml_root, info)
                self.analyze_project(xml_root)
                self.update_status("Project loaded successfully")
            except Exception as e:
                self.update_status("Error loading project")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to open the project: {str(e)}"
                )

    def refresh_analysis(self):
        """Rafraîchit l'analyse du projet."""
        if not hasattr(self, 'current_project_path') or not self.current_project_path:
            QMessageBox.warning(
                self,
                "Warning",
                "No project is currently loaded."
            )
            return
        try:
            self.update_status("Refreshing analysis...")
            xml_root, _ = open_project(self.current_project_path)
            self.analyze_project(xml_root)
            self.update_status("Analysis refreshed")
        except Exception as e:
            self.update_status("Error refreshing analysis")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to refresh analysis: {str(e)}"
            )

    def analyze_project(self, xml_root):
        """Analyse le projet et affiche un résumé détaillé."""
        try:
            self.update_status("Analyzing project...")
            summary = []
            summary.append(f"Project Path: {self.current_project_path}")

            # Get extent
            extent = xml_root.find(".//mapcanvas/extent")
            if extent is not None:
                xmin = extent.findtext("xmin", "N/A")
                ymin = extent.findtext("ymin", "N/A")
                xmax = extent.findtext("xmax", "N/A")
                ymax = extent.findtext("ymax", "N/A")
                summary.append(f"Extent: {xmin}, {ymin} to {xmax}, {ymax}")
            else:
                summary.append("Extent: Not defined in the project")

            # Get CRS
            crs = xml_root.find(".//spatialrefsys")
            if crs is not None:
                authid = crs.findtext("authid", "N/A")
                summary.append(f"CRS: {authid}")

            # Count layers
            layers = xml_root.findall(".//maplayer")
            summary.append(f"Number of Layers: {len(layers)}")

            # Count themes
            themes = xml_root.find("visibility-presets")
            num_themes = len(themes.findall("visibility-preset")) if themes is not None else 0
            summary.append(f"Number of Themes: {num_themes}")

            # Count layouts (robuste : casse, namespace, deux structures possibles)
            def _localname(tag: str) -> str:
                """Retourne le nom local de la balise sans namespace."""
                return tag.rsplit('}', 1)[-1].lower() if tag else ""

            layout_names = set()
            for elem in xml_root.iter():
                if _localname(elem.tag) == "layout":
                    name = (elem.get("name") or "").strip()
                    if name:
                        layout_names.add(name)

            summary.append(f"Number of Layouts: {len(layout_names)}")

            # Afficher le résumé
            self.resultTextEdit.setPlainText("\n".join(summary))
            self.update_status("Project analysis complete.")

        except Exception as e:
            self.update_status(f"Failed to analyze the project: {e}")    

    def fill_trees(self, xml_root, info):
        """Remplit les arbres avec les informations du projet et harmonise les entêtes."""
        from qgis.PyQt.QtWidgets import QHeaderView, QSizePolicy
        # 0) garde-fous
        if xml_root is None or not hasattr(self, "selection_manager") or self.selection_manager is None:
            print("[QRator] fill_trees: xml_root ou selection_manager manquant.")
            return

        # 1) références widgets (adapte les noms si besoin)
        trees = [
            ("layerTree",   "Layers"),
            ("themeTree",   "Themes"),
            ("layoutTree",  "Layouts"),
            ("relationTree","Relations"),
        ]

        # 2) reset visuel minimal
        for name, header in trees:
            tw = getattr(self, name, None)
            if not tw:
                continue
            try:
                tw.blockSignals(True)
                tw.clear()
                tw.setHeaderHidden(False)
                tw.setHeaderLabels([header])
                # stretch propre : colonne 0 qui suit la largeur + policy Expanding
                hdr = tw.header()
                if hdr is not None:
                    hdr.setStretchLastSection(True)
                    if hasattr(hdr, "setSectionResizeMode"):
                        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
                tw.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))
            finally:
                tw.blockSignals(False)

        # 3) remplir les arbres via les parseurs
        try:
            from .parse_layers import parse_layers
            from .parse_themes import parse_themes
            from .parse_layouts_relations import parse_layouts, parse_relations

            if getattr(self, "layerTree", None):
                parse_layers(xml_root, self.layerTree, self.selection_manager)
            if getattr(self, "themeTree", None):
                parse_themes(xml_root, self.themeTree, self.selection_manager)
            if getattr(self, "layoutTree", None):
                parse_layouts(xml_root, self.layoutTree, self.selection_manager)
            if getattr(self, "relationTree", None):
                parse_relations(xml_root, self.relationTree, self.selection_manager)
        except Exception as e:
            print("[QRator] fill_trees parse error:", e)

        # 4) petit message de statut
        try:
            self.update_status("Project tree updated")
        except Exception:
            pass

    def export_to_html(self):
        try:
            output_path, _ = QFileDialog.getSaveFileName(
                self, "Save HTML Report", "", "HTML Files (*.html)"
            )
            if not output_path:
                return
            if not hasattr(self, 'current_project_path') or not self.current_project_path:
                QMessageBox.warning(self, "Warning", "No project is currently loaded.")
                return

            self.update_status("Generating report...")

            xml_root, _ = open_project(self.current_project_path)
            selected_elements = self.selection_manager.get_selected_elements()

            # Utilisation du générateur de rapport
            generator = HTMLReportGenerator(self.current_project_path, selected_elements, xml_root)
            generator.generate_report(output_path)

            self.update_status(f"Report saved to {output_path}")
            QMessageBox.information(
                self, "Success", f"HTML report saved successfully: {output_path}"
            )

        except Exception as e:
            self.update_status("Error generating report")
            QMessageBox.critical(self, "Error", f"Failed to generate HTML report: {str(e)}")

    def _generate_layers_section(self, xml_root, selected_elements):
        """Génère la section des couches sélectionnées."""
        selected_layers = selected_elements.get("layers", set())
        selected_styles = selected_elements.get("styles", set())

        if not selected_layers:
            return "<p>No layers selected.</p>"

        html = "<table><tr><th>Layer ID</th><th>Layer Name</th><th>Styles</th><th>CRS</th></tr>"

        for layer in xml_root.findall(".//maplayer"):
            layer_id = layer.findtext("id", "")
            if layer_id in selected_layers:
                layer_name = layer.findtext("layername", "(unnamed)")
                crs = layer.find("spatialrefsys")
                authid = crs.findtext("authid", "N/A") if crs is not None else "N/A"

                # Trouver les styles sélectionnés pour cette couche
                layer_styles = []
                for style_id in selected_styles:
                    if style_id.startswith(layer_id):
                        style_name = style_id[len(layer_id)+1:]
                        layer_styles.append(style_name)

                html += f"""
                <tr>
                    <td>{layer_id}</td>
                    <td>{layer_name}</td>
                    <td>{', '.join(layer_styles) if layer_styles else 'Default'}</td>
                    <td>{authid}</td>
                </tr>
                """

        html += "</table>"
        return html

    def _generate_selection_details(self, selected_elements):
        """Génère les détails de la sélection."""
        html = "<table>"

        # Thèmes
        themes = selected_elements.get("themes", set())
        html += f"""
        <tr>
            <td><strong>Themes:</strong></td>
            <td>{len(themes)} selected</td>
        </tr>
        """

        # Layouts
        layouts = selected_elements.get("layouts", set())
        html += f"""
        <tr>
            <td><strong>Layouts:</strong></td>
            <td>{len(layouts)} selected</td>
        </tr>
        """

        # Relations
        relations = selected_elements.get("relations", set())
        html += f"""
        <tr>
            <td><strong>Relations:</strong></td>
            <td>{len(relations)} selected</td>
        </tr>
        """

        html += "</table>"
        return html
    
    def _generate_system_info(self, xml_root):
        """Génère les informations système à inclure dans le rapport HTML."""
        import platform
        import datetime

        # Valeurs par défaut
        qgis_version = "(inconnue)"
        project_name = "(sans nom)"
        save_user = "(inconnu)"
        save_datetime = "(non précisé)"

        # Extraire les attributs depuis la balise <qgis>
        if xml_root is not None:
            qgis_tag = xml_root  # La racine est déjà la balise <qgis>
            qgis_version = qgis_tag.attrib.get("version", qgis_version)
            project_name = qgis_tag.attrib.get("projectname", project_name)
            save_user = qgis_tag.attrib.get("saveUserFull", save_user)
            save_datetime = qgis_tag.attrib.get("saveDateTime", save_datetime)

        # Générer le HTML
        html = f"""
        <h2>Informations système</h2>
        <table border="1" cellpadding="4" cellspacing="0">
            <tr><td><strong>Nom du projet :</strong></td><td>{project_name}</td></tr>
            <tr><td><strong>Utilisateur :</strong></td><td>{save_user}</td></tr>
            <tr><td><strong>Date de sauvegarde :</strong></td><td>{save_datetime}</td></tr>
            <tr><td><strong>Version QGIS :</strong></td><td>{qgis_version}</td></tr>
            <tr><td><strong>Version Python :</strong></td><td>{platform.python_version()}</td></tr>
            <tr><td><strong>Système d'exploitation :</strong></td><td>{platform.system()} {platform.release()}</td></tr>
            <tr><td><strong>Date du rapport :</strong></td><td>{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
        </table>
        """
        return html

    def export_project(self):
        """Exporte le projet filtré en fonction des sélections dans tous les onglets."""
        if not hasattr(self, 'modifiedPathLineEdit'):
            QMessageBox.warning(self, "Warning", "UI element missing: modifiedPathLineEdit")
            return

        output_path = self.modifiedPathLineEdit.text()
        if not output_path:
            QMessageBox.warning(self, "Warning", "Please specify a path for the modified project.")
            return

        if not self.current_project_path or not os.path.exists(self.current_project_path):
            QMessageBox.warning(self, "Warning", "Please open a valid QGIS project first.")
            return

        try:
            self.update_status("Exporting project...")
            selected_elements = self.selection_manager.get_selected_elements()
            print("[QRator] Selected elements before export:", selected_elements)

            xml_root, _ = open_project(self.current_project_path)

            # Autoriser export si au moins 1 couche effective (via onglet Couches ou Thèmes)
            layers = set(selected_elements.get("layers", set()))
            theme_layers = set(selected_elements.get("theme_layers", set()))
            theme_styles = set(selected_elements.get("theme_styles", set()))

            effective_layers = set(layers)
            for tl in theme_layers:
                try:
                    _theme, lid = tl.rsplit("_", 1)
                    effective_layers.add(lid)
                except Exception:
                    pass
            for ts in theme_styles:
                try:
                    _theme, lid, _sname = ts.rsplit("_", 2)
                    effective_layers.add(lid)
                except Exception:
                    pass

            if not effective_layers:
                QMessageBox.warning(
                    self, "Warning",
                    "Please select at least one layer (directly in Couches or via Thèmes)."
                )
                return

            import inspect, qrator.qgz_manager as qm
            
            print("[QRator] qgz_manager file:", inspect.getfile(qm))
            print("[QRator] selections:", self.selection_manager.get_selected_elements())
            print("[QRator] will save to:", output_path)

            # Passer l’état de la case à cocher au moteur d’export
            try:
                selected_elements["disconnect_local"] = bool(
                    getattr(self, "chk_disconnect_local", None)
                    and self.chk_disconnect_local.isChecked()
                )
            except Exception:
                selected_elements["disconnect_local"] = False

            success = save_new_project(output_path, xml_root, selected_elements)

            if success:
                self.update_status(f"Project saved to {output_path}")
                QMessageBox.information(self, "Success", f"Project saved successfully: {output_path}")
            else:
                self.update_status("Error saving project")
                QMessageBox.critical(self, "Error", "Failed to save the project.")
        except Exception as e:
            self.update_status("Error exporting project")
            QMessageBox.critical(self, "Error", f"Failed to export the project: {str(e)}")

    def _resolve_layer_by_id(self, layer_id: str):
        """
        Essaie de retrouver une QgsMapLayer par ID :
        1) dans le projet courant (QgsProject.instance())
        2) sinon, via un projet 'cache' chargé depuis self.current_project_path
            (évite de relire le .qgz à chaque fois)
        Retourne un tuple (layer, temp_project) ; temp_project peut être le cache.
        """
        if not layer_id:
            return None, None

        # 1) Projet courant
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is not None:
            return layer, None

        # 2) Projet analysé (cache)
        proj_path = getattr(self, "current_project_path", "") or getattr(self, "project_path", "")
        if not proj_path:
            return None, None

        # Si le cache est déjà prêt et pour le bon chemin → réutilise-le
        if self._style_tmp_project and self._style_tmp_project_path == proj_path:
            layer = self._style_tmp_project.mapLayer(layer_id)
            if layer is not None:
                return layer, self._style_tmp_project

        # Sinon (re)charge le cache
        temp_proj = QgsProject()
        ok = temp_proj.read(proj_path)
        if not ok:
            return None, None

        self._style_tmp_project = temp_proj
        self._style_tmp_project_path = proj_path

        layer = temp_proj.mapLayer(layer_id)
        if layer is None:
            return None, temp_proj  # renvoie tout de même le proj pour que l'appelant sache qu'il existe
        return layer, temp_proj
    
    def _on_tree_context_menu(self, pos: QPoint):
        """Menu contextuel pour exporter/copier/appliquer un style QML (sur layerTree et themeTree)."""
        sender = self.sender()
        if sender is None:
            return

        item = sender.itemAt(pos)
        if item is None:
            return

        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, tuple) or len(data) != 2:
            return

        item_type, identifier = data

        # On n’active le menu que pour un item "style"
        if item_type not in ("styles", "theme_styles"):
            return

        menu = QMenu(sender)

        act_export = QAction("Enregistrer le style en .QML…", menu)
        act_export.triggered.connect(lambda: self._export_style_qml(item_type, identifier))
        menu.addAction(act_export)

        act_copy = QAction("Copier le style (QML) dans le presse-papiers", menu)
        act_copy.triggered.connect(lambda: self._copy_style_qml_to_clipboard(item_type, identifier))
        menu.addAction(act_copy)

        # NOUVEAU : appliquer à la couche active
        act_apply = QAction("Appliquer le style à la couche active", menu)
        act_apply.triggered.connect(lambda: self._apply_style_to_active_layer(item_type, identifier))
        menu.addAction(act_apply)

        menu.exec_(sender.mapToGlobal(pos))

    def _export_style_qml(self, item_type: str, identifier: str):
        """Enregistre le style en .QML (fonctionne depuis Couches et Thèmes, avec cache projet)."""
        try:
            from qgis.PyQt.QtWidgets import QFileDialog
            layer_id, style_name = self._parse_style_identifier(item_type, identifier)
            if not layer_id:
                QMessageBox.warning(self, "QRator", "Impossible d’identifier la couche.")
                return

            layer, temp_proj = self._resolve_layer_by_id(layer_id)
            if layer is None:
                QMessageBox.warning(self, "QRator", f"Couche introuvable dans le projet: {layer_id}")
                return

            sm = layer.styleManager()
            prev = sm.currentStyle()

            target = style_name or "default"
            if target.lower() == "défaut" and "default" in sm.styles():
                target = "default"
            if target not in sm.styles():
                QMessageBox.warning(
                    self, "QRator",
                    f"Le style « {style_name or 'default'} » n’existe pas sur « {layer.name()} ».\n"
                    f"Styles disponibles : {', '.join(sm.styles())}"
                )
                return

            safe_style = style_name or "default"
            default_name = f"{layer.name()}_{safe_style}.qml"
            path, _ = QFileDialog.getSaveFileName(
                self, "Enregistrer le style QML", default_name, "QGIS Layer Style (*.qml)"
            )
            if not path:
                return

            sm.setCurrentStyle(target)
            ok = layer.saveNamedStyle(path)
            sm.setCurrentStyle(prev)

            # NE PAS vider le cache si c'est lui
            if temp_proj and temp_proj is not self._style_tmp_project:
                temp_proj.clear()

            # Évalue le succès (bool|int|tuple)
            if isinstance(ok, tuple):
                res, msg = ok[0], (ok[1] if len(ok) > 1 else "")
            else:
                res, msg = ok, ""
            success = (res is True) or (isinstance(res, int) and res == 0)

            if not success:
                QMessageBox.critical(self, "QRator", f"Échec d’enregistrement du style.\n{msg}")
                return

            QMessageBox.information(self, "QRator", f"Style enregistré :\n{path}")

        except Exception as e:
            QMessageBox.critical(self, "QRator", f"Erreur: {e}")

    def _parse_style_identifier(self, item_type: str, identifier: str):
        """
        Normalise l’identifiant en (layer_id, style_name).
        - "styles"       : "layer_id|style"
        - "theme_styles" : "theme|layer_id|style"
        """
        if item_type == "styles":
            if "|" in identifier:
                lid, style = identifier.split("|", 1)
                return lid.strip(), style.strip()
            return identifier.strip(), ""  # fallback improbable

        if item_type == "theme_styles":
            parts = identifier.split("|")
            if len(parts) >= 3:
                # theme, layer_id, style (style peut contenir des '|', on les recolle)
                lid = parts[1].strip()
                style = "|".join(parts[2:]).strip()
                return lid, style
            elif len(parts) == 2:
                return parts[1].strip(), ""
            elif len(parts) == 1:
                return "", ""
        return "", ""        
    
    def _copy_style_qml_to_clipboard(self, item_type: str, identifier: str):
        """Copie le style QML dans le presse-papiers (fonctionne avec cache projet)."""
        try:
            import tempfile, os
            from qgis.PyQt.QtGui import QGuiApplication

            layer_id, style_name = self._parse_style_identifier(item_type, identifier)
            if not layer_id:
                QMessageBox.warning(self, "QRator", "Impossible d’identifier la couche.")
                return

            layer, temp_proj = self._resolve_layer_by_id(layer_id)
            if layer is None:
                QMessageBox.warning(self, "QRator", f"Couche introuvable dans le projet: {layer_id}")
                return

            sm = layer.styleManager()
            prev = sm.currentStyle()

            target = style_name or "default"
            if target.lower() == "défaut" and "default" in sm.styles():
                target = "default"
            if target not in sm.styles():
                QMessageBox.warning(
                    self, "QRator",
                    f"Le style « {style_name or 'default'} » n’existe pas sur « {layer.name()} ».\n"
                    f"Styles disponibles : {', '.join(sm.styles())}"
                )
                return

            # Export temporaire
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".qml")
            tmp_path = tmp.name
            tmp.close()

            sm.setCurrentStyle(target)
            ok = layer.saveNamedStyle(tmp_path)
            sm.setCurrentStyle(prev)

            # NE PAS vider le cache si c'est lui
            if temp_proj and temp_proj is not self._style_tmp_project:
                temp_proj.clear()

            # Évalue le succès (bool|int|tuple)
            if isinstance(ok, tuple):
                res, msg = ok[0], (ok[1] if len(ok) > 1 else "")
            else:
                res, msg = ok, ""
            success = (res is True) or (isinstance(res, int) and res == 0)
            if not success:
                try: os.remove(tmp_path)
                except: pass
                QMessageBox.critical(self, "QRator", f"Échec de l’export du style.\n{msg}")
                return

            # Lit le QML → presse-papiers
            with open(tmp_path, "r", encoding="utf-8") as f:
                qml_text = f.read()
            try: os.remove(tmp_path)
            except: pass

            QGuiApplication.clipboard().setText(qml_text)
            QMessageBox.information(self, "QRator", "Style copié dans le presse-papiers ✅")

        except Exception as e:
            QMessageBox.critical(self, "QRator", f"Erreur: {e}")

    def _apply_style_to_active_layer(self, item_type: str, identifier: str):
        """Applique le style sélectionné (depuis Couches/Thèmes) à la couche ACTIVE du projet courant.
        1) tentative ultra-rapide en mémoire via QgsMapLayerStyle (pas de fichier)
        2) fallback via export QML temporaire puis loadNamedStyle
        + garde-fous et diagnostics détaillés
        """
        try:
            from qgis.utils import iface
            import tempfile, os
            from qgis.core import QgsMapLayer  # pour enums et QgsMapLayerStyle

            target = iface.activeLayer()
            if target is None:
                QMessageBox.warning(self, "QRator", "Aucune couche active dans le projet courant.")
                return

            # Style source (depuis item)
            layer_id, style_name = self._parse_style_identifier(item_type, identifier)
            if not layer_id:
                QMessageBox.warning(self, "QRator", "Impossible d’identifier la couche source du style.")
                return

            src_layer, _temp_proj = self._resolve_layer_by_id(layer_id)
            if src_layer is None:
                QMessageBox.warning(self, "QRator", f"Couche source introuvable: {layer_id}")
                return

            # Garde-fous : type compatible (vector↔vector, raster↔raster) + géométrie si vecteur
            def _layer_kind(l):
                try:
                    return l.type()  # QgsMapLayer.VectorLayer / RasterLayer / MeshLayer...
                except Exception:
                    return None

            src_kind = _layer_kind(src_layer)
            dst_kind = _layer_kind(target)
            if src_kind != dst_kind:
                QMessageBox.warning(
                    self, "QRator",
                    f"Type de couche incompatible (source: {src_kind}, cible: {dst_kind})."
                )
                return

            # Si ce sont des vecteurs, vérifier la géométrie (Point/Line/Polygon)
            try:
                if src_kind == QgsMapLayer.VectorLayer:
                    if hasattr(src_layer, "geometryType") and hasattr(target, "geometryType"):
                        if src_layer.geometryType() != target.geometryType():
                            QMessageBox.warning(
                                self, "QRator",
                                "Type de géométrie incompatible (ex: ligne → polygone)."
                            )
                            return
            except Exception:
                pass  # si la géométrie n’est pas dispo, on tente quand même

            sm = src_layer.styleManager()
            src_styles = sm.styles()
            # Normalisation du nom du style
            target_style = style_name or "default"
            if target_style.lower() == "défaut" and "default" in src_styles:
                target_style = "default"
            if target_style not in src_styles:
                QMessageBox.warning(
                    self, "QRator",
                    f"Le style « {style_name or 'default'} » n’existe pas sur « {src_layer.name()} ».\n"
                    f"Styles disponibles : {', '.join(src_styles)}"
                )
                return

            # 1) TENTATIVE EN MÉMOIRE (pas de fichier) ------------------------------
            try:
                src_qml_style = sm.style(target_style)  # QgsMapLayerStyle
                if src_qml_style is not None:
                    tsm = target.styleManager()
                    tmp_name = f"__QRator__{target_style}"
                    # s'il existe déjà, on écrase
                    if tmp_name in tsm.styles():
                        tsm.removeStyle(tmp_name)
                    ok_add = tsm.addStyle(tmp_name, src_qml_style)
                    ok_set = tsm.setCurrentStyle(tmp_name)
                    # Vérifie succès
                    if ok_add and ok_set and tsm.currentStyle() == tmp_name:
                        target.triggerRepaint()
                        QMessageBox.information(self, "QRator", f"Style appliqué à « {target.name()} » ✅ (en mémoire)")
                        return
                    # sinon, on tombera en fallback
            except Exception as e_mem:
                print("[QRator] apply in-memory failed, fallback to QML:", e_mem)

            # 2) FALLBACK : EXPORT QML TEMPORAIRE PUIS LOAD -------------------------
            prev = sm.currentStyle()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".qml")
            tmp_path = tmp.name
            tmp.close()

            sm.setCurrentStyle(target_style)
            ok = src_layer.saveNamedStyle(tmp_path)
            sm.setCurrentStyle(prev)

            # Évalue le succès saveNamedStyle (bool|int|tuple) + fallback fichier existant
            if isinstance(ok, tuple):
                res, msg = ok[0], (ok[1] if len(ok) > 1 else "")
            else:
                res, msg = ok, ""
            save_success = (res is True) or (isinstance(res, int) and res == 0)
            try:
                if (not save_success) and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    save_success = True
            except Exception:
                pass

            if not save_success:
                try: os.remove(tmp_path)
                except: pass
                QMessageBox.critical(
                    self, "QRator",
                    f"Échec d’export du style source (fallback QML).\n{msg if msg else ''}"
                )
                return

            loaded = target.loadNamedStyle(tmp_path)
            try: os.remove(tmp_path)
            except: pass

            # Évalue le succès loadNamedStyle (bool|int|tuple ou int=0)
            if isinstance(loaded, tuple):
                res, lmsg = loaded[0], (loaded[1] if len(loaded) > 1 else "")
            else:
                res, lmsg = loaded, ""
            load_success = (res is True) or (isinstance(res, int) and res == 0)

            if not load_success:
                # Diagnostic enrichi pour t’aider :
                diag = []
                try:
                    diag.append(f"source_kind={src_kind}, target_kind={dst_kind}")
                    if src_kind == QgsMapLayer.VectorLayer:
                        diag.append(f"src_geom={getattr(src_layer, 'geometryType', lambda: '?')()}")
                        diag.append(f"dst_geom={getattr(target, 'geometryType', lambda: '?')()}")
                    diag.append(f"style='{target_style}'")
                    diag.append(f"src_styles={', '.join(src_styles)}")
                except Exception:
                    pass
                QMessageBox.critical(
                    self, "QRator",
                    "Échec d’application du style (fallback QML).\n"
                    f"{lmsg if lmsg else ''}\n\n" + "\n".join(diag)
                )
                return

            target.triggerRepaint()
            QMessageBox.information(self, "QRator", f"Style appliqué à « {target.name()} » ✅")

        except Exception as e:
            QMessageBox.critical(self, "QRator", f"Erreur: {e}")

    def _on_layouts_context_menu(self, pos: QPoint):
        """Menu contextuel sur layoutTree : export PDF/PNG (300 dpi), individuel ou en lot (éléments cochés)."""
        sender = self.sender()
        if sender is None:
            return

        item = sender.itemAt(pos)
        clicked_name = None
        clicked_is_layout = False
        if item is not None:
            data = item.data(0, Qt.UserRole)
            if data and isinstance(data, tuple) and len(data) == 2 and data[0] == "layouts":
                clicked_is_layout = True
                clicked_name = data[1]

        # Récupère aussi les mises en page cochées (si tu coches dans l’arbre)
        checked = sorted(list(self._collect_checked_layout_names()))

        menu = QMenu(sender)

        # Actions "sur la mise en page cliquée"
        if clicked_is_layout and clicked_name:
            a1 = QAction(f"Exporter « {clicked_name} » en PDF…", menu)
            a1.triggered.connect(lambda: self._export_single_layout(clicked_name, "pdf"))
            menu.addAction(a1)

            a2 = QAction(f"Exporter « {clicked_name} » en PNG (300 dpi)…", menu)
            a2.triggered.connect(lambda: self._export_single_layout(clicked_name, "png"))
            menu.addAction(a2)

            if checked and (clicked_name not in checked or len(checked) > 1):
                menu.addSeparator()

        # Actions "lot" si au moins 2 cochées (ou 1 si tu veux autoriser)
        if checked:
            b1 = QAction(f"Exporter {len(checked)} mise(s) en page cochée(s) en PDF…", menu)
            b1.triggered.connect(lambda: self._export_multiple_layouts(checked, "pdf"))
            menu.addAction(b1)

            b2 = QAction(f"Exporter {len(checked)} mise(s) en page cochée(s) en PNG (300 dpi)…", menu)
            b2.triggered.connect(lambda: self._export_multiple_layouts(checked, "png"))
            menu.addAction(b2)

        if menu.actions():
            menu.exec_(sender.mapToGlobal(pos))

    def _collect_checked_layout_names(self):
        """Retourne l'ensemble des noms de mises en page cochées dans layoutTree."""
        names = set()
        tree = getattr(self, "layoutTree", None)
        if not tree:
            return names
        root = tree.invisibleRootItem()
        stack = [root]
        while stack:
            node = stack.pop()
            for i in range(node.childCount()):
                child = node.child(i)
                # On s'appuie sur le 'register_item("layouts", name, item)' fait par parse_layouts
                data = child.data(0, Qt.UserRole)
                if data and isinstance(data, tuple) and len(data) == 2 and data[0] == "layouts":
                    if child.checkState(0) == Qt.Checked:
                        names.add(data[1])
                stack.append(child)
        return names

    def _resolve_temp_project_for_layouts(self):
        """Renvoie le projet QGIS à utiliser pour exporter les layouts (réutilise le cache déjà présent)."""
        # Si un projet courant est chargé en mémoire avec ces mises en page, on pourrait l’utiliser,
        # mais dans ton flux on travaille depuis un projet externe → on réutilise le cache déjà géré.
        proj_path = getattr(self, "current_project_path", "") or getattr(self, "project_path", "")
        if not proj_path:
            return None

        # Réutilise le cache existant (mêmes attributs que pour les styles)
        if self._style_tmp_project and self._style_tmp_project_path == proj_path:
            return self._style_tmp_project

        # Sinon, charger et mettre en cache
        p = QgsProject()
        if not p.read(proj_path):
            return None
        self._style_tmp_project = p
        self._style_tmp_project_path = proj_path
        return p

    def _get_layouts_by_names(self, project: QgsProject, names):
        """Retourne dict {name: QgsLayout} pour les noms demandés (ignore ceux introuvables)."""
        res = {}
        if not project:
            return res
        lm = project.layoutManager()
        for n in names:
            lay = lm.layoutByName(n)
            if lay:
                res[n] = lay
        return res
    
    def _export_single_layout(self, layout_name: str, fmt: str):
        """Export d'une mise en page unique en PDF ou PNG(300dpi)."""
        try:
            proj = self._resolve_temp_project_for_layouts()
            if proj is None:
                QMessageBox.warning(self, "QRator", "Projet introuvable pour exporter la mise en page.")
                return

            layouts = self._get_layouts_by_names(proj, [layout_name])
            if layout_name not in layouts:
                QMessageBox.warning(self, "QRator", f"Mise en page introuvable : {layout_name}")
                return

            layout = layouts[layout_name]
            exporter = QgsLayoutExporter(layout)

            if fmt.lower() == "pdf":
                path, _ = QFileDialog.getSaveFileName(self, "Exporter en PDF",
                                                    f"{layout_name}.pdf", "PDF (*.pdf)")
                if not path:
                    return
                ps = QgsLayoutExporter.PdfExportSettings()
                # Optionnel : forcer sortie vectorielle quand possible
                ps.forceVectorOutput = True
                code = exporter.exportToPdf(path, ps)
                ok = (code == QgsLayoutExporter.Success or code == 0)
                if not ok:
                    QMessageBox.critical(self, "QRator", f"Échec d'export PDF ({code}).")
                    return
                QMessageBox.information(self, "QRator", f"PDF exporté :\n{path}")
                return

            # PNG 300 dpi
            if fmt.lower() == "png":
                path, _ = QFileDialog.getSaveFileName(self, "Exporter en PNG (300 dpi)",
                                                    f"{layout_name}.png", "PNG (*.png)")
                if not path:
                    return
                iset = QgsLayoutExporter.ImageExportSettings()
                iset.dpi = 300
                # Si plusieurs pages, QGIS nommera automatiquement fichier_1.png, fichier_2.png, etc.
                code = exporter.exportToImage(path, iset)
                ok = (code == QgsLayoutExporter.Success or code == 0)
                if not ok:
                    QMessageBox.critical(self, "QRator", f"Échec d'export PNG ({code}).")
                    return
                QMessageBox.information(self, "QRator", f"PNG exporté :\n{path}")
                return

            QMessageBox.warning(self, "QRator", f"Format non supporté : {fmt}")

        except Exception as e:
            QMessageBox.critical(self, "QRator", f"Erreur export : {e}")

    def _export_multiple_layouts(self, layout_names, fmt: str):
        """Export de plusieurs mises en page cochées. Demande un dossier, produit 1 fichier par mise en page.
        - PDF : <nom>.pdf
        - PNG 300dpi : <nom>.png (ou <nom>_1.png, <nom>_2.png si plusieurs pages)
        """
        try:
            proj = self._resolve_temp_project_for_layouts()
            if proj is None:
                QMessageBox.warning(self, "QRator", "Projet introuvable pour exporter les mises en page.")
                return

            lay_map = self._get_layouts_by_names(proj, layout_names)
            missing = [n for n in layout_names if n not in lay_map]
            if missing:
                QMessageBox.warning(self, "QRator", "Mises en page introuvables :\n- " + "\n- ".join(missing))
                # on continue quand même pour celles trouvées

            # Choisit un dossier de sortie
            out_dir = QFileDialog.getExistingDirectory(self, "Choisir un dossier de sortie")
            if not out_dir:
                return

            exported = 0
            errors = []

            for name, layout in lay_map.items():
                exporter = QgsLayoutExporter(layout)
                if fmt.lower() == "pdf":
                    out_path = os.path.join(out_dir, f"{name}.pdf")
                    ps = QgsLayoutExporter.PdfExportSettings()
                    ps.forceVectorOutput = True
                    code = exporter.exportToPdf(out_path, ps)
                    ok = (code == QgsLayoutExporter.Success or code == 0)
                    if ok:
                        exported += 1
                    else:
                        errors.append(f"{name} (code={code})")
                elif fmt.lower() == "png":
                    out_path = os.path.join(out_dir, f"{name}.png")
                    iset = QgsLayoutExporter.ImageExportSettings()
                    iset.dpi = 300
                    code = exporter.exportToImage(out_path, iset)
                    ok = (code == QgsLayoutExporter.Success or code == 0)
                    if ok:
                        exported += 1
                    else:
                        errors.append(f"{name} (code={code})")
                else:
                    errors.append(f"{name} (format non supporté)")

            if exported and not errors:
                QMessageBox.information(self, "QRator", f"Export terminé : {exported} fichier(s) écrit(s) dans\n{out_dir}")
            elif exported and errors:
                QMessageBox.warning(self, "QRator",
                                    f"Export partiel : {exported} ok / {len(errors)} erreurs\n"
                                    + "\n".join(errors))
            else:
                QMessageBox.critical(self, "QRator", "Aucun export réalisé.\n" + ("\n".join(errors) if errors else ""))

        except Exception as e:
            QMessageBox.critical(self, "QRator", f"Erreur export lot : {e}")

    def _clear_ui_and_state(self):
        """Remet l'UI et l'état interne à zéro."""
        # 1) Vider les arbres (sans émettre de signaux parasites)
        trees = []
        if hasattr(self, "layerTree"):    trees.append(self.layerTree)
        if hasattr(self, "themeTree"):    trees.append(self.themeTree)
        if hasattr(self, "layoutTree"):   trees.append(self.layoutTree)
        if hasattr(self, "relationTree"): trees.append(self.relationTree)

        for tw in trees:
            try:
                tw.blockSignals(True)
                tw.clear()
            finally:
                tw.blockSignals(False)

        # 2) Réinitialiser le gestionnaire de sélection
        if hasattr(self, "selection_manager") and self.selection_manager:
            try:
                self.selection_manager.reset()
            except Exception:
                pass

        # 3) Effacer l’état “projet chargé”
        # adapte les attributs si tes noms diffèrent
        if hasattr(self, "xml_root"):          self.xml_root = None
        if hasattr(self, "current_project"):    self.current_project = None
        if hasattr(self, "current_project_path"): self.current_project_path = ""
        if hasattr(self, "loaded"):             self.loaded = False

        # 4) Nettoyer les widgets d’info (chemin, labels, boutons, etc.)
        # adapte selon ton UI
        for attr in ("projectPathLineEdit", "projectLineEdit"):
            if hasattr(self, attr):
                try:
                    getattr(self, attr).clear()
                except Exception:
                    pass

        # 5) Vider proprement le cache de projet temporaire (styles)
        if getattr(self, "_style_tmp_project", None):
            try:
                self._style_tmp_project.clear()
            except Exception:
                pass
            self._style_tmp_project = None
            self._style_tmp_project_path = ""

    def closeEvent(self, event):
        """Nettoyage automatique à la fermeture de la boîte de dialogue."""
        try:
            self._clear_ui_and_state()
        finally:
            super().closeEvent(event)

    def showEvent(self, event):
        """À chaque affichage de la fenêtre, on remet la case à décoché."""
        try:
            if hasattr(self, "chk_disconnect_local"):
                self.chk_disconnect_local.setChecked(False)
        finally:
            super().showEvent(event)

    def reject(self):
        """Si on ferme via Échap / bouton Annuler."""
        try:
            self._clear_ui_and_state()
        finally:
            super().reject()