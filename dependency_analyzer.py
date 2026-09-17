# qrator/dependency_analyzer.py
"""
Analyse des dépendances d'une mise en page QGIS : thèmes utilisés (et leurs couches/styles),
couche de couverture de l'atlas, tableaux attributaires de la mise en page, et jointures
(QGIS natives via <vectorjoins>, ainsi que les tables référencées par les requêtes SQL
intégrées ou par les vues SpatiaLite/GeoPackage sous-jacentes).

Aucune dépendance Qt : ce module est utilisé à la fois par l'onglet "Dépendances" (parse_dependencies.py)
et par le générateur de rapport HTML (html_report_generator.py).

Limitations connues :
- L'extraction des noms de table référencés dans un SQL (sous-requête intégrée ou vue de la base)
  se fait par expression régulière (repère les motifs FROM/JOIN <nom>), pas par un vrai parseur SQL.
  Suffisant pour les motifs usuels vus en pratique, mais peut rater des cas exotiques (sous-requêtes
  imbriquées directement dans un FROM, noms de table calculés, etc.).
- Seul le provider "spatialite" (et par extension gpkg/sqlite pour "ogr") est introspecté au niveau
  base de données ; les autres providers (postgres, wfs, ...) s'arrêtent aux jointures QGIS natives.
- L'ouverture de la base se fait toujours en lecture seule et échoue silencieusement (nœud marqué
  "unresolved") si le fichier n'est pas trouvé au chemin résolu.
"""
import os
import re
import sqlite3
from typing import Dict, List, Optional, Set

from lxml import etree

# =========================
# Helpers XML (namespace-agnostiques, dupliqués par cohérence avec le reste du projet)
# =========================

def _localname(tag: str) -> str:
    return tag.rsplit('}', 1)[-1].lower() if tag else ""

def _all(elem, xp):
    return elem.xpath(xp)

def _first(elem, xp):
    r = elem.xpath(xp)
    return r[0] if r else None

MAP_ITEM_TYPE = "65639"
MULTIFRAME_ATTRIBUTE_TABLE_TYPE = "65649"
MULTIFRAME_HTML_TYPE = "65648"

_MULTIFRAME_KIND_NAMES = {
    MULTIFRAME_ATTRIBUTE_TABLE_TYPE: "attribute_table",
    MULTIFRAME_HTML_TYPE: "html",
}

# =========================
# Extraction de noms de table depuis un texte SQL (regex, best-effort)
# =========================

_FROM_JOIN_RE = re.compile(r'(?:FROM|JOIN)\s+"?([A-Za-z_][A-Za-z0-9_]*)"?', re.IGNORECASE)
_CTE_RE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(', re.IGNORECASE)

def _extract_table_names_from_sql(sql_text: str) -> Set[str]:
    """Retourne les noms de table référencés par FROM/JOIN dans sql_text, en excluant
    les noms de CTE (WITH <nom> AS (...)) qui ne sont pas de vraies tables."""
    if not sql_text:
        return set()
    names = {m.group(1) for m in _FROM_JOIN_RE.finditer(sql_text)}
    cte_names = {m.group(1) for m in _CTE_RE.finditer(sql_text)}
    return names - cte_names

# =========================
# Parsing du datasource spatialite
# =========================

_DBNAME_RE = re.compile(r"dbname='([^']*)'")
_TABLE_ATTR_RE = re.compile(r'table="(.*)"', re.DOTALL)

def _parse_spatialite_datasource(datasource: str) -> Dict:
    """Extrait {dbname, table, is_embedded_sql} d'un datasource spatialite QGIS."""
    m_db = _DBNAME_RE.search(datasource or "")
    m_table = _TABLE_ATTR_RE.search(datasource or "")
    dbname = m_db.group(1) if m_db else None
    table_val = m_table.group(1) if m_table else None
    is_embedded_sql = bool(table_val) and table_val.strip().startswith("(") and bool(
        re.search(r"\bSELECT\b", table_val, re.IGNORECASE)
    )
    return {"dbname": dbname, "table": table_val, "is_embedded_sql": is_embedded_sql}

def _resolve_db_path(dbname: str, project_dir: Optional[str]) -> Optional[str]:
    """Résout dbname (chemin absolu ou relatif au projet) vers un fichier existant, ou None."""
    if not dbname:
        return None
    candidate = dbname if os.path.isabs(dbname) else os.path.normpath(
        os.path.join(project_dir or "", dbname)
    )
    return candidate if os.path.exists(candidate) else None

def _lookup_sqlite_object(db_path: str, name: str) -> Optional[Dict]:
    """Lit sqlite_master en lecture seule pour retrouver le type et le SQL d'une table/vue."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT type, sql FROM sqlite_master WHERE name=? AND type IN ('table','view')",
                (name,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        obj_type, sql = row
        return {"type": obj_type, "sql": sql}
    except Exception as e:
        print(f"[QRator][dependency_analyzer] Could not inspect '{name}' in {db_path}: {e}")
        return None

# =========================
# Résolution récursive d'une couche
# =========================

# Cache mono-entrée (clé = identité de l'objet xml_root, pas son id() pour éviter tout risque de
# collision après garbage-collection) : évite de re-scanner tout le document à chaque couche/mise
# en page résolue. Un seul projet est analysé à la fois en pratique (onglet Dépendances ou rapport
# HTML), donc une seule entrée suffit.
_index_cache_key = None
_index_cache_value = None

def _get_project_index(xml_root) -> Dict:
    """{'by_id': {layer_id: maplayer}, 'by_name': {layername: layer_id}, 'layouts': {name: Layout}},
    construit en un seul passage et mémoïsé tant que xml_root ne change pas."""
    global _index_cache_key, _index_cache_value
    if _index_cache_key is xml_root and _index_cache_value is not None:
        return _index_cache_value

    by_id, by_name = {}, {}
    for ml in _all(xml_root, ".//*[local-name()='maplayer']"):
        lid = ml.findtext("id")
        if not lid:
            continue
        by_id[lid] = ml
        name = ml.findtext("layername")
        if name and name not in by_name:
            by_name[name] = lid

    layouts = {}
    presets = {}
    relations = {}
    for elem in xml_root.iter():
        tag = _localname(elem.tag)
        if tag == "layout":
            name = (elem.get("name") or "").strip()
            if name and name not in layouts:
                layouts[name] = elem
        elif tag == "visibility-preset":
            name = (elem.get("name") or "").strip()
            if name and name not in presets:
                presets[name] = elem
        elif tag == "relation":
            rid = elem.get("id")
            if rid and rid not in relations:
                relations[rid] = elem

    index = {
        "by_id": by_id, "by_name": by_name,
        "layouts": layouts, "presets": presets, "relations": relations,
    }
    _index_cache_key, _index_cache_value = xml_root, index
    return index

def _find_layer(xml_root, layer_id: str):
    if not layer_id:
        return None
    return _get_project_index(xml_root)["by_id"].get(layer_id)

def _build_layername_index(xml_root) -> Dict[str, str]:
    """{layername: layer_id} pour le croisement best-effort des tables référencées en SQL."""
    return _get_project_index(xml_root)["by_name"]

def resolve_layer_node(xml_root, layer_id: str, project_dir: Optional[str] = None,
                        style: Optional[str] = None, seen: frozenset = frozenset(),
                        depth: int = 0, max_depth: int = 6, cache: Optional[Dict] = None,
                        layername_index: Optional[Dict[str, str]] = None) -> Dict:
    """Construit récursivement le nœud de dépendance d'une couche (jointures + résolution SQL)."""
    if cache is None:
        cache = {}
    if layername_index is None:
        layername_index = _build_layername_index(xml_root)

    ml = _find_layer(xml_root, layer_id)
    if ml is None:
        return {"layer_id": layer_id, "style": style, "error": "layer_not_found_in_project"}

    node = {
        "layer_id": layer_id,
        "layer_name": ml.findtext("layername") or layer_id,
        "provider": ml.findtext("provider") or "",
        "style": style,
        "joins": [],
    }

    if layer_id in seen or depth >= max_depth:
        node["truncated"] = True
        return node

    if layer_id in cache:
        # Réutilise le sous-arbre déjà résolu pour cette couche (partagée par plusieurs branches),
        # en conservant le style propre à CE contexte d'appel.
        cached = dict(cache[layer_id])
        cached["style"] = style
        return cached

    next_seen = seen | {layer_id}

    for j in _all(ml, ".//*[local-name()='vectorjoins']/*[local-name()='join']"):
        target_id = j.get("joinLayerId")
        if not target_id:
            continue
        node["joins"].append({
            "field": j.get("joinFieldName"),
            "target": resolve_layer_node(
                xml_root, target_id, project_dir,
                seen=next_seen, depth=depth + 1, max_depth=max_depth,
                cache=cache, layername_index=layername_index,
            ),
        })

    provider = (node["provider"] or "").lower()
    datasource = ml.findtext("datasource") or ""

    if provider == "spatialite":
        parsed = _parse_spatialite_datasource(datasource)
        if parsed["is_embedded_sql"]:
            table_names = _extract_table_names_from_sql(parsed["table"])
            node["source_kind"] = "embedded_sql"
            node["referenced_tables"] = sorted(table_names)
            node["referenced_project_layers"] = sorted(
                {layername_index[n] for n in table_names if n in layername_index}
            )
        elif parsed["table"]:
            node["source_kind"] = "table"
            node["table_name"] = parsed["table"]
            db_path = _resolve_db_path(parsed["dbname"], project_dir)
            if not db_path:
                node["db_lookup"] = "db_file_not_found"
            else:
                info = _lookup_sqlite_object(db_path, parsed["table"])
                if info is None:
                    node["db_lookup"] = "object_not_found_in_db"
                elif info["type"] == "view":
                    view_tables = _extract_table_names_from_sql(info["sql"])
                    node["db_lookup"] = "view_resolved"
                    node["referenced_tables"] = sorted(view_tables)
                    node["referenced_project_layers"] = sorted(
                        {layername_index[n] for n in view_tables if n in layername_index}
                    )
                else:
                    node["db_lookup"] = "table_confirmed"
        else:
            node["source_kind"] = "unresolved"
    else:
        node["source_kind"] = "other_provider"

    cache[layer_id] = node
    return node

# =========================
# Analyse d'une mise en page
# =========================

def _preset_layers(xml_root, theme_name: str) -> List[tuple]:
    p = _get_project_index(xml_root)["presets"].get(theme_name)
    if p is None:
        return []
    return [(ly.get("id"), ly.get("style")) for ly in _all(p, ".//*[local-name()='layer']")]

def _relation_info(xml_root, relation_id: str) -> Optional[Dict]:
    rel = _get_project_index(xml_root)["relations"].get(relation_id)
    if rel is None:
        return None
    return {
        "relation_id": relation_id,
        "name": rel.get("name") or relation_id,
        "parent_layer_id": rel.get("referencedLayer") or "",
        "child_layer_id": rel.get("referencingLayer") or "",
    }

def analyze_layout_dependencies(xml_root, layout_name: str, project_path: Optional[str] = None) -> Dict:
    """Construit l'arbre complet des dépendances d'une mise en page (thèmes, atlas, tableaux)."""
    result = {
        "layout": layout_name,
        "atlas": None,
        "themes": [],
        "tables": [],
        "warnings": [],
    }

    lay = _get_project_index(xml_root)["layouts"].get(layout_name)
    if lay is None:
        result["warnings"].append("layout_not_found")
        return result

    project_dir = os.path.dirname(project_path) if project_path else None
    cache: Dict = {}
    layername_index = _build_layername_index(xml_root)

    atlas = _first(lay, ".//*[local-name()='Atlas']")
    if atlas is not None and atlas.get("enabled") == "1":
        coverage_id = atlas.get("coverageLayer")
        if coverage_id:
            result["atlas"] = {
                "coverage_layer_name": atlas.get("coverageLayerName"),
                "layer": resolve_layer_node(
                    xml_root, coverage_id, project_dir, cache=cache, layername_index=layername_index
                ),
            }

    themes_used: Set[str] = set()
    for m in _all(lay, ".//*[local-name()='LayoutItem'][@type='%s']" % MAP_ITEM_TYPE):
        if m.get("followPreset") == "true" and m.get("followPresetName"):
            themes_used.add(m.get("followPresetName"))
        else:
            result["warnings"].append(
                f"map_item_without_theme:{m.get('uuid') or m.get('id') or '?'}"
            )

    for theme_name in sorted(themes_used):
        layers = [
            resolve_layer_node(
                xml_root, lid, project_dir, style=style, cache=cache, layername_index=layername_index
            )
            for lid, style in _preset_layers(xml_root, theme_name)
            if lid
        ]
        result["themes"].append({"theme": theme_name, "layers": layers})

    for mf in _all(lay, ".//*[local-name()='LayoutMultiFrame']"):
        vl = mf.get("vectorLayer")
        if not vl:
            continue
        entry = {
            "kind": _MULTIFRAME_KIND_NAMES.get(mf.get("type"), mf.get("type")),
            "layer": resolve_layer_node(
                xml_root, vl, project_dir, cache=cache, layername_index=layername_index
            ),
        }
        rel_id = mf.get("relationId")
        if rel_id:
            entry["relation"] = _relation_info(xml_root, rel_id)
        result["tables"].append(entry)

    return result

# =========================
# Présentation (partagée par l'onglet Qt et le rapport HTML)
# =========================

def source_kind_label(node: Dict) -> str:
    """Description humaine de la provenance des données d'un nœud résolu par resolve_layer_node."""
    kind = node.get("source_kind")
    if kind == "embedded_sql":
        tables = node.get("referenced_tables") or []
        return f"Requête SQL intégrée → tables référencées : {', '.join(tables) or '(aucune détectée)'}"
    if kind == "table":
        lookup = node.get("db_lookup")
        table_name = node.get("table_name", "")
        if lookup == "view_resolved":
            tables = node.get("referenced_tables") or []
            return f"Vue « {table_name} » (résolue dans la base) → tables : {', '.join(tables) or '(aucune détectée)'}"
        if lookup == "table_confirmed":
            return f"Table « {table_name} » confirmée dans la base"
        if lookup == "object_not_found_in_db":
            return f"« {table_name} » introuvable dans la base (nom obsolète ?)"
        if lookup == "db_file_not_found":
            return f"« {table_name} » — fichier base de données introuvable au chemin résolu"
        return f"Table/vue « {table_name} » (non résolue)"
    if kind == "other_provider":
        return f"Provider « {node.get('provider')} » non introspecté (hors SpatiaLite/GeoPackage)"
    return ""
