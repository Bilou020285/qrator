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


def _as_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


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

    # Import PyQGIS *après* avoir éventuellement ajusté le prefix
    from qgis.core import QgsApplication, QgsProject, QgsLayoutExporter

    if prefix:
        QgsApplication.setPrefixPath(prefix, True)

    qgs = QgsApplication([], False)
    qgs.initQgis()

    try:
        if not project_path or not os.path.exists(project_path):
            raise FileNotFoundError(f"Project not found: {project_path}")

        proj = QgsProject()

        # Lecture du projet
        ok = proj.read(project_path)
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

                code = exporter.exportToPdf(out_path, ps)

            elif fmt == "png":
                iset = QgsLayoutExporter.ImageExportSettings()
                if hasattr(iset, "dpi"):
                    iset.dpi = dpi
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
