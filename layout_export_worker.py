"""QRator - worker d'export de mises en page (PDF / PNG)

Ce script est lancé dans un *sous-processus* par le plugin.
But : exporter des mises en page d'un projet externe (.qgs/.qgz)
sans risquer de faire planter QGIS (le process principal) quand le projet est énorme.

Entrée : un fichier JSON de configuration passé en argument.
Sortie : un JSON (1 ligne) sur stdout.

NB : le rendu PDF/PNG nécessite de charger le projet et ses couches →
on ne peut pas appliquer la même stratégie "XML-only" que pour un .qpt.
"""

import json
import os
import sys
import traceback
import glob


def _as_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def _prepare_qgis_env(prefix: str):
    """Configure un environnement QGIS minimal *avant* import PyQGIS.

    Objectif : rendre le sous-process aussi proche que possible de l'environnement
    de l'instance QGIS principale (PROJ/GDAL inclus), afin d'éviter :
    - CRS 'not found' (PROJ DB non trouvée)
    - erreurs GDAL (GDAL_DATA non trouvé)
    """
    if not prefix:
        return

    os.environ.setdefault("QGIS_PREFIX_PATH", prefix)

    # prefix est souvent .../apps/qgis -> root = ...
    root = os.path.abspath(os.path.join(prefix, os.pardir, os.pardir))
    bin_dir = os.path.join(root, "bin")
    share_dir = os.path.join(root, "share")

    # PATH / DLLs
    if os.path.isdir(bin_dir):
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(bin_dir)
            except Exception:
                pass

    # PROJ / GDAL data (important pour les CRS EPSG et la lecture raster)
    proj_dir = os.path.join(share_dir, "proj")
    gdal_dir = os.path.join(share_dir, "gdal")

    if os.path.isdir(proj_dir):
        # PROJ 9+ préfère PROJ_DATA, mais on pose aussi PROJ_LIB pour compat.
        os.environ.setdefault("PROJ_DATA", proj_dir)
        os.environ.setdefault("PROJ_LIB", proj_dir)

    if os.path.isdir(gdal_dir):
        os.environ.setdefault("GDAL_DATA", gdal_dir)

    # Chemin Python de QGIS : <prefix>/python
    py_path = os.path.join(prefix, "python")
    if os.path.isdir(py_path) and py_path not in sys.path:
        sys.path.insert(0, py_path)


def _safe_unlink(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _prepare_output_path(out_path: str, fmt: str):
    """Évite les erreurs GDAL 'update access' en supprimant les sorties existantes.

    QGIS peut parfois (selon les options d'export / drivers) tenter une ouverture en
    mode update si un fichier cible existe déjà.
    """
    if not out_path:
        return

    # Suppression du fichier cible
    _safe_unlink(out_path)

    # En PNG multipages, QGIS génère automatiquement *_1.png, *_2.png, etc.
    if fmt == "png":
        base, ext = os.path.splitext(out_path)
        if ext.lower() != ".png":
            return
        for p in glob.glob(base + "_*.png"):
            _safe_unlink(p)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "Missing config path"}, ensure_ascii=False))
        return 2

    cfg_path = sys.argv[1]
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"Cannot read config: {e}"}, ensure_ascii=False))
        return 2

    prefix = (cfg.get("prefix") or "").strip()
    project_path = (cfg.get("project_path") or "").strip()
    fmt = (cfg.get("format") or "").lower().strip()
    dpi = _as_int(cfg.get("dpi"), 300)
    items = cfg.get("items") or []

    # Prépare l'environnement AVANT d'importer PyQGIS.
    _prepare_qgis_env(prefix)

    # Import PyQGIS
    from qgis.core import QgsApplication, QgsProject, QgsLayoutExporter, Qgis

    if prefix:
        QgsApplication.setPrefixPath(prefix, True)

    qgs = QgsApplication([], False)
    qgs.initQgis()

    try:
        if not project_path or not os.path.exists(project_path):
            raise FileNotFoundError(f"Project not found: {project_path}")

        proj = QgsProject()

        # Flags de lecture pour accélérer un peu (sans casser le rendu des layouts)
        # - TrustLayerMetadata / DontStoreOriginalStyles / DontLoadProjectStyles / DontLoad3DViews
        flags = (
            Qgis.ProjectReadFlag.TrustLayerMetadata
            | Qgis.ProjectReadFlag.DontStoreOriginalStyles
            | Qgis.ProjectReadFlag.DontLoadProjectStyles
            | Qgis.ProjectReadFlag.DontLoad3DViews
        )

        ok = proj.read(project_path, flags)
        if not ok:
            raise RuntimeError("QgsProject.read() failed")

        lm = proj.layoutManager()
        results = []

        for it in items:
            name = (it.get("layout_name") or "").strip()
            out_path = (it.get("out_path") or "").strip()
            if not name:
                results.append({"layout_name": name, "out_path": out_path, "ok": False, "code": None, "error": "Empty layout name"})
                continue
            if not out_path:
                results.append({"layout_name": name, "out_path": out_path, "ok": False, "code": None, "error": "Empty output path"})
                continue

            layout = lm.layoutByName(name)
            if not layout:
                results.append({"layout_name": name, "out_path": out_path, "ok": False, "code": None, "error": "Layout not found"})
                continue

            exporter = QgsLayoutExporter(layout)

            # Si le fichier existe déjà, on le supprime (évite certains cas où GDAL tente un update)
            _prepare_output_path(out_path, fmt)

            if fmt == "pdf":
                ps = QgsLayoutExporter.PdfExportSettings()
                # Pour les projets lourds, la sortie vectorielle peut être coûteuse.
                # On laisse QGIS choisir (souvent mieux), et on rasterise si l'option existe.
                if hasattr(ps, "forceVectorOutput"):
                    ps.forceVectorOutput = False
                if hasattr(ps, "rasterizeWholeImage"):
                    ps.rasterizeWholeImage = True
                if hasattr(ps, "dpi"):
                    ps.dpi = dpi

                # Désactive la géoréférence (et les métadonnées) :
                # - évite des erreurs PROJ/GDAL quand un CRS est exotique/incorrect
                # - généralement souhaité pour des figures (PDF de publication)
                if hasattr(ps, "appendGeoreference"):
                    ps.appendGeoreference = False
                if hasattr(ps, "exportMetadata"):
                    ps.exportMetadata = False
                if hasattr(ps, "writeGeoPdf"):
                    ps.writeGeoPdf = False

                code = exporter.exportToPdf(out_path, ps)

            elif fmt == "png":
                iset = QgsLayoutExporter.ImageExportSettings()
                if hasattr(iset, "dpi"):
                    iset.dpi = dpi

                # Export PNG : figure simple → pas de worldfile ni de métadonnées.
                if hasattr(iset, "generateWorldFile"):
                    iset.generateWorldFile = False
                if hasattr(iset, "exportMetadata"):
                    iset.exportMetadata = False

                # Si plusieurs pages, QGIS nommera automatiquement fichier_1.png, fichier_2.png, etc.
                code = exporter.exportToImage(out_path, iset)

            else:
                results.append({"layout_name": name, "out_path": out_path, "ok": False, "code": None, "error": f"Unsupported format: {fmt}"})
                continue

            ok = (code == QgsLayoutExporter.Success or code == 0)
            results.append({
                "layout_name": name,
                "out_path": out_path,
                "ok": bool(ok),
                "code": _as_int(code, -1),
                "error": "" if ok else f"Export failed (code={code})",
            })

        print(json.dumps({"ok": True, "format": fmt, "results": results}, ensure_ascii=False))
        return 0

    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "trace": traceback.format_exc(),
        }, ensure_ascii=False))
        return 1
    finally:
        try:
            qgs.exitQgis()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
