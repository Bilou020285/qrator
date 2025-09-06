# -*- coding: utf-8 -*-
"""
QRator – HTML report generator (English UI, clean Map section)

- Header + logo (embedded if icons/icon_full.png exists)
- Table of contents
- Project summary (counters)
- CRS + extent + file path
- Leaflet map in its own section (no empty block below)
- Layers: plugin-like tree (groups/layers/styles) with check icons
  + Expand/Collapse all
  + Layer details show ID, Path, and CRS
  + Checks reflect selections made via Layers tab AND Themes tab
- Themes: theme → layers → styles with check icons
  + Expand/Collapse all
- Layouts: names only with check icons
- Relations: nested like plugin with check icons
  + Expand/Collapse all
"""

import os
import base64
import json

def _read_logo_data_uri():
    """Return a data URI for icons/icon_full.png if available, else None."""
    try:
        here = os.path.dirname(__file__)
        logo_path = os.path.join(here, "icons", "icon_full.png")
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return f"data:image/png;base64,{b64}"
    except Exception:
        pass
    return None

def _text(el, default="Unknown"):
    return el.text if el is not None and el.text is not None else default

def _strip_ns(tag):
    return tag.split('}')[-1] if tag else tag

class HTMLReportGenerator:
    def __init__(self, project_path, selected_elements, xml_root):
        self.project_path = project_path
        self.selected = selected_elements or {}
        self.xml_root = xml_root
        self.layer_index = self._build_layer_index()  # by id

    # ------------------------------------------------------------------ PUBLIC
    def generate_report(self, output_path):
        if not output_path.endswith('.html'):
            output_path += '.html'
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        html = self._generate_html_content()
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    # ----------------------------------------------------------------- EXTRACT
    def _build_layer_index(self):
        """
        Build {layer_id: {name, path, crs, styles[]}} from <maplayer>.
        Be robust to CRS schema differences across QGIS versions.
        """
        idx = {}
        for ml in self.xml_root.findall(".//maplayer"):
            lid = _text(ml.find("id"), "")
            name = _text(ml.find("layername"), "(unnamed)")
            datasource = _text(ml.find("datasource"), "N/A")
            provider = ml.get("provider", "N/A")
            path = f"{provider}:{datasource}" if provider != "N/A" else datasource

            # Try multiple CRS paths
            crs_auth = "N/A"
            for xp in [
                "spatialrefsys/authid",
                "crs/authid",
                ".//spatialrefsys/authid",
                ".//crs/authid",
            ]:
                node = ml.find(xp)
                if node is not None and node.text:
                    crs_auth = node.text.strip()
                    break
            # Fallback to raw EPSG code if present
            if crs_auth == "N/A":
                epsg = None
                for xp in ["spatialrefsys/epsg", ".//spatialrefsys/epsg", "crs/epsg", ".//crs/epsg"]:
                    node = ml.find(xp)
                    if node is not None and node.text:
                        epsg = node.text.strip()
                        break
                if epsg:
                    crs_auth = f"EPSG:{epsg}"

            styles = []
            mgr = ml.find(".//map-layer-style-manager")
            if mgr is not None:
                for st in mgr.findall(".//map-layer-style"):
                    styles.append(st.get("name", "default"))
            if not styles:
                styles = ["default"]

            idx[lid] = {
                "name": name,
                "path": path,
                "crs": crs_auth,
                "styles": styles,
            }
        return idx

    def _extract_project_info(self):
        def find_text(xps, default="Unknown"):
            for xp in xps:
                el = self.xml_root.find(xp)
                if el is not None and el.text:
                    return el.text
            return default

        return {
            "name": os.path.basename(self.project_path) if self.project_path else "Unnamed",
            "user": self.xml_root.attrib.get("saveUserFull", "Unknown"),
            "date": self.xml_root.attrib.get("saveDateTime", "Unknown"),
            "version": self.xml_root.attrib.get("version", "Unknown"),
            "crs": {
                "authid": find_text([
                    ".//projectCrs/spatialrefsys/authid",
                    ".//projectCrs/crs/authid",
                ], "Unknown"),
                "description": find_text([
                    ".//projectCrs/spatialrefsys/description",
                    ".//projectCrs/crs/description",
                ], "Unknown"),
            },
            "extent": {
                "xmin": find_text([".//mapcanvas/extent/xmin"], "Unknown"),
                "ymin": find_text([".//mapcanvas/extent/ymin"], "Unknown"),
                "xmax": find_text([".//mapcanvas/extent/xmax"], "Unknown"),
                "ymax": find_text([".//mapcanvas/extent/ymax"], "Unknown"),
            },
        }

    # ---------- robust matching for selections from SelectionManager -----------
    def _guess_layer_id_in_string(self, s):
        """Find a known layer id inside an arbitrary selection string; return lid or None."""
        s = str(s)
        for lid in self.layer_index.keys():
            if lid and lid in s:
                return lid
        return None

    def _split_theme_layer_identifier(self, s):
        """
        Accept various formats: "<theme>_<lid>", "<theme>::<lid>", "<theme>|<lid>", etc.
        Returns (theme, lid) where theme may be None.
        """
        s = str(s)
        # try common separators
        for sep in ("::", "|", "__", "||", "--", "§", "¤", "→", "=>", "==", "_"):
            if sep in s:
                left, right = s.split(sep, 1)
                if right in self.layer_index:
                    return (left, right)
        # fallback: search any known layer id
        lid = self._guess_layer_id_in_string(s)
        if lid:
            theme = s.split(lid)[0].rstrip("_:| ")
            return (theme or None, lid)
        return (None, None)

    def _split_theme_style_identifier(self, s):
        """
        Accept formats like "<theme>_<lid>_<style>", or with :: / |.
        If not obvious, locate a known layer id inside and take the suffix as style.
        Returns (theme, lid, style) with theme possibly None.
        """
        s = str(s)
        # try two separators cases
        for sep in ("::", "|", "__", "--", "==", "_"):
            parts = s.split(sep)
            if len(parts) >= 3:
                theme = sep.join(parts[:-2])
                lid = parts[-2]
                style = parts[-1]
                if lid in self.layer_index:
                    return (theme or None, lid, style)
        # fallback: find lid anywhere
        lid = self._guess_layer_id_in_string(s)
        if lid:
            tail = s.split(lid, 1)[1].lstrip("_:| -")
            style = tail if tail else "default"
            head = s.split(lid, 1)[0].rstrip("_:| -")
            return (head or None, lid, style)
        return (None, None, None)

    # ---------------------------- LAYERS (tree with checks/icons)
    def _extract_layers_tree(self):
        root = self.xml_root.find(".//layer-tree-group")
        if root is None:
            return []

        # selections from the UI (Layers tab)
        sel_groups = set(self.selected.get("layer_groups", [])) or set()
        sel_layers = set(self.selected.get("layers", [])) or set()
        sel_styles = set(self.selected.get("styles", [])) or set()

        # also consider selections coming from the Themes tab (robust parsing)
        eff_layers = set(sel_layers)
        eff_styles = set(sel_styles)

        for tl in self.selected.get("theme_layers", set()) or set():
            _, lid = self._split_theme_layer_identifier(tl)
            if lid:
                eff_layers.add(lid)

        for ts in self.selected.get("theme_styles", set()) or set():
            _, lid, sname = self._split_theme_style_identifier(ts)
            if lid and sname:
                eff_styles.add(f"{lid}_{sname}")

        def parse_group(g):
            gname = g.get("name", "Group")
            node = {
                "type": "group",
                "name": gname,
                "checked": (gname in sel_groups),
                "children": []
            }
            for child in g:
                tag = _strip_ns(child.tag)
                if tag == "layer-tree-group":
                    node["children"].append(parse_group(child))
                elif tag == "layer-tree-layer":
                    lid = child.get("id", "")
                    info = self.layer_index.get(lid, {"name": "(unknown)", "path": "N/A", "crs": "N/A", "styles": ["default"]})
                    styles = []
                    for sname in info["styles"]:
                        sid = f"{lid}_{sname}"
                        styles.append({
                            "name": sname,
                            "checked": (sid in eff_styles)
                        })
                    node["children"].append({
                        "type": "layer",
                        "id": lid,
                        "name": info["name"],
                        "checked": (lid in eff_layers),
                        "path": info["path"],
                        "crs": info["crs"],
                        "styles": styles
                    })
            return node

        return [parse_group(root)]

    # ----------------------------------------------- THEMES (tree with checks)
    def _extract_themes(self):
        out = []
        vps = self.xml_root.find("visibility-presets")
        if vps is None:
            return out

        sel_themes = set(self.selected.get("themes", [])) or set()
        sel_theme_layers_raw = set(self.selected.get("theme_layers", [])) or set()
        sel_theme_styles_raw = set(self.selected.get("theme_styles", [])) or set()

        # normalize selections keyed by (theme, lid) and (theme, lid, style)
        sel_theme_layers = set()
        for tl in sel_theme_layers_raw:
            theme, lid = self._split_theme_layer_identifier(tl)
            if lid:
                sel_theme_layers.add((theme, lid))

        sel_theme_styles = set()
        for ts in sel_theme_styles_raw:
            theme, lid, sname = self._split_theme_style_identifier(ts)
            if lid and sname:
                sel_theme_styles.add((theme, lid, sname))

        for vp in vps.findall("visibility-preset"):
            tname = vp.get("name", "(unnamed theme)")
            tnode = {
                "type": "theme",
                "name": tname,
                "checked": (tname in sel_themes),
                "children": []
            }
            for layer in vp.findall("layer"):
                lid = layer.get("id", "")
                sname = layer.get("style", "") or "default"
                lname = self.layer_index.get(lid, {}).get("name", f"(id {lid})")

                l_checked = ((tname, lid) in sel_theme_layers)
                s_checked = ((tname, lid, sname) in sel_theme_styles)

                lnode = {
                    "type": "theme_layer",
                    "name": lname,
                    "id": lid,
                    "checked": l_checked,
                    "children": [{
                        "type": "theme_style",
                        "name": sname,
                        "checked": s_checked
                    }]
                }
                tnode["children"].append(lnode)
            out.append(tnode)
        return out

    # ------------------------------------------------------- LAYOUTS (names only)
    def _extract_layouts(self):
        out = []
        layouts = self.xml_root.find(".//Layouts")
        sel_layouts = set(self.selected.get("layouts", [])) or set()
        if layouts is None:
            return out
        for layout in layouts.findall("Layout"):
            name = layout.get("name", "(unnamed)")
            out.append({
                "type": "layout",
                "name": name,
                "checked": (name in sel_layouts)
            })
        return out

    # --------------------------------------------------- RELATIONS (nested tree)
    def _extract_relations(self):
        out = []
        rels = self.xml_root.find(".//relations")
        if rels is None:
            return out

        sel_rel = set(self.selected.get("relations", [])) or set()
        sel_fields = set(self.selected.get("relation_fields", [])) or set()

        def lname(lid):
            return self.layer_index.get(lid, {}).get("name", f"(id {lid})")

        for rel in rels.findall("relation"):
            rname = rel.get("name", "(unnamed relation)")
            refd = rel.get("referencedLayer", "")
            refg = rel.get("referencingLayer", "")

            # Fields
            child_field = ""
            parent_field = ""
            fr = rel.find("fieldRef")
            if fr is not None:
                child_field = fr.get("referencingField", "") or ""
                parent_field = fr.get("referencedField", "") or ""

            rnode = {
                "type": "relation",
                "name": rname,
                "checked": (rname in sel_rel),
                "children": []
            }
            parent_node = {
                "type": "relation_parent",
                "name": f"Parent layer: {lname(refd)}",
                "children": []
            }
            if parent_field:
                pid = f"{rname}_parent_field_{parent_field}"
                parent_node["children"].append({
                    "type": "relation_parent_field",
                    "name": f"Parent field: {parent_field}",
                    "checked": (pid in sel_fields)
                })
            child_node = {
                "type": "relation_child",
                "name": f"Child layer: {lname(refg)}",
                "children": []
            }
            if child_field:
                cid = f"{rname}_child_field_{child_field}"
                child_node["children"].append({
                    "type": "relation_child_field",
                    "name": f"Child field: {child_field}",
                    "checked": (cid in sel_fields)
                })
            rnode["children"].append(parent_node)
            rnode["children"].append(child_node)
            out.append(rnode)

        return out

    # -------------------------------------------------------------- PRESENTATION
    def _generate_html_content(self):
        pinfo = self._extract_project_info()
        layers_tree = self._extract_layers_tree()
        themes_tree = self._extract_themes()
        layouts = self._extract_layouts()
        relations_tree = self._extract_relations()

        # Counters
        def count_layers(nodes):
            c = 0
            for n in nodes:
                if n.get("type") == "group":
                    c += count_layers(n.get("children", []))
                elif n.get("type") == "layer":
                    c += 1
            return c

        layer_count = count_layers(layers_tree)
        theme_count = len(themes_tree)
        layout_count = len(layouts)
        relation_count = len(relations_tree)

        # Map center / bounds (project CRS -> EPSG:4326), fallback Paris
        try:
            from pyproj import Transformer, CRS
            auth = pinfo["crs"]["authid"]
            src = CRS.from_user_input(auth) if auth and auth != "Unknown" else CRS.from_epsg(2154)
            tr = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
            xmin = float(pinfo["extent"]["xmin"])
            ymin = float(pinfo["extent"]["ymin"])
            xmax = float(pinfo["extent"]["xmax"])
            ymax = float(pinfo["extent"]["ymax"])
            lon_min, lat_min = tr.transform(xmin, ymin)
            lon_max, lat_max = tr.transform(xmax, ymax)
            center_lat = (lat_min + lat_max) / 2.0
            center_lon = (lon_min + lon_max) / 2.0
            bounds = [[lat_min, lon_min], [lat_max, lon_max]]
        except Exception:
            center_lat, center_lon = 48.8566, 2.3522
            bounds = [[48.85, 2.34], [48.87, 2.36]]

        logo_data_uri = _read_logo_data_uri()

        # ------------------------------ CSS
        css = """
        <style>
          :root{
            --c1:#2c3e50; --c2:#2962ff; --bg:#f8fafc; --border:#e5e7eb; --muted:#6b7280;
          }
          *{ box-sizing:border-box; }
          html, body{ margin:0; padding:0; }
          body{
            font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
            color:#111827; background:var(--bg);
          }
          .container{ max-width:1100px; margin:24px auto; padding:0 16px; }
          header{
            display:flex; align-items:center; gap:14px;
            background:#fff; border:1px solid var(--border); border-radius:12px;
            padding:12px 14px; box-shadow:0 1px 2px rgba(0,0,0,.04); margin-bottom:18px;
          }
          header img{ height:44px; width:auto; }
          .title{ font-size:20px; font-weight:800; color:var(--c1); }
          .meta{ color:var(--muted); font-size:12px; }
          .card{
            background:#fff; border:1px solid var(--border); border-radius:12px; padding:14px;
            box-shadow:0 1px 2px rgba(0,0,0,.04); margin:16px 0;
          }
          /* Hide any truly empty card (belt & suspenders) */
          .card:empty { display:none; }
          .section-head{ display:flex; align-items:center; gap:8px; justify-content:space-between; }
          .section-actions{ display:flex; gap:8px; }
          .btn{
            border:1px solid var(--border); background:#f3f4f6; padding:6px 10px; border-radius:8px;
            font-size:12px; cursor:pointer;
          }
          .btn:hover{ background:#e5e7eb; }
          .toc a{ color:var(--c2); text-decoration:none; margin-right:8px; }
          .grid{ display:grid; gap:12px; }
          .cols-4{ grid-template-columns:repeat(4,minmax(0,1fr)); }
          .cols-2{ grid-template-columns:repeat(2,minmax(0,1fr)); }
          .counter{ background:#eef2ff; border:1px solid #e0e7ff; padding:10px; border-radius:10px; }
          .counter .label{ font-size:12px; color:#1f2937; }
          .counter .value{ font-size:22px; font-weight:800; color:#1d4ed8; }
          #map{ height:380px; border-radius:12px; border:1px solid var(--border); }
          h2{ color:#1d4ed8; margin:4px 0 10px; }
          .muted{ color:var(--muted); }
          .mono{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
          /* Tree */
          .tree ul{ list-style:none; margin:0; padding:0 0 0 14px; border-left:1px dashed #d1d5db; }
          .tree li{ margin:6px 0; }
          .node{ display:flex; align-items:center; gap:8px; cursor:pointer; }
          .node .caret{ width:12px; display:inline-block; user-select:none; }
          .node .name{ font-weight:600; }
          .node .badge{ font-size:11px; padding:2px 6px; border-radius:999px; border:1px solid var(--border); color:#374151; background:#f9fafb; }
          .node-details{ margin:6px 0 0 22px; padding:8px; background:#f9fafb; border:1px solid var(--border); border-radius:8px; }
          .nowrap{ white-space:nowrap; }
          @media (max-width: 900px){
            .cols-4{ grid-template-columns:repeat(2,minmax(0,1fr)); }
            .cols-2{ grid-template-columns:repeat(1,minmax(0,1fr)); }
          }
        </style>
        """

        # ------------------------------ JS renderers
        js = """
        <script>
          function checkIcon(on){ return on ? '<i class="fa-solid fa-square-check"></i>' : '<i class="fa-regular fa-square"></i>'; }
          function caret(open){ return open ? '▾' : '▸'; }
          function toggleNode(el){
            const kids = el.nextElementSibling;
            if(!kids) return;
            const c = el.querySelector('.caret');
            const open = kids.style.display === 'block';
            kids.style.display = open ? 'none' : 'block';
            if(c) c.textContent = caret(!open);
          }
          // Expand/collapse helpers for a section
          function setAll(sectionId, open){
            const container = document.getElementById(sectionId);
            if(!container) return;
            const caretEls = container.querySelectorAll('.node .caret');
            const kids = container.querySelectorAll('.node + div'); // siblings that hold children/details
            kids.forEach(k => { k.style.display = open ? 'block' : 'none'; });
            caretEls.forEach(c => { c.textContent = caret(open); });
          }
          function expandAll(sectionId){ setAll(sectionId, true); }
          function collapseAll(sectionId){ setAll(sectionId, false); }

          // -------- Layers
          function renderLayers(nodes){
            if(!nodes || !nodes.length) return "<div class='muted'>No layers.</div>";
            function renderNode(n){
              if(n.type === 'group'){
                return `
                  <li>
                    <div class="node" onclick="toggleNode(this)">
                      <span class="caret">▸</span>
                      ${checkIcon(!!n.checked)}
                      <span class="name">${n.name}</span>
                    </div>
                    <div style="display:none">
                      <div class="tree"><ul>
                        ${(n.children||[]).map(renderNode).join('')}
                      </ul></div>
                    </div>
                  </li>`;
              }
              if(n.type === 'layer'){
                const styles = (n.styles||[]).map(s => `
                  <li>
                    <div class="node">
                      ${checkIcon(!!s.checked)}
                      <span class="name">${s.name}</span>
                    </div>
                  </li>`).join('');
                return `
                  <li>
                    <div class="node" onclick="toggleNode(this)">
                      <span class="caret">▸</span>
                      ${checkIcon(!!n.checked)}
                      <span class="name">${n.name}</span>
                      <span class="badge">ID: <span class="mono">${n.id}</span></span>
                    </div>
                    <div style="display:none">
                      <div class="node-details">
                        <div><strong>Path:</strong> <span class="mono">${n.path||'N/A'}</span></div>
                        <div><strong>CRS:</strong> <span class="mono">${n.crs||'N/A'}</span></div>
                        ${(styles ? '<div style="margin-top:6px;"><strong>Styles</strong><div class="tree"><ul>'+styles+'</ul></div></div>' : '')}
                      </div>
                    </div>
                  </li>`;
              }
              return '';
            }
            return `<div class="tree"><ul>${nodes.map(renderNode).join('')}</ul></div>`;
          }

          // -------- Themes
          function renderThemes(nodes){
            if(!nodes || !nodes.length) return "<div class='muted'>No themes.</div>";
            function renderNode(n){
              if(n.type === 'theme'){
                return `
                  <li>
                    <div class="node" onclick="toggleNode(this)">
                      <span class="caret">▸</span>
                      ${checkIcon(!!n.checked)}
                      <span class="name">${n.name}</span>
                    </div>
                    <div style="display:none">
                      <div class="tree"><ul>
                        ${(n.children||[]).map(renderNode).join('')}
                      </ul></div>
                    </div>
                  </li>`;
              }
              if(n.type === 'theme_layer'){
                return `
                  <li>
                    <div class="node" onclick="toggleNode(this)">
                      <span class="caret">▸</span>
                      ${checkIcon(!!n.checked)}
                      <span class="name">${n.name}</span>
                      <span class="badge">ID: <span class="mono">${n.id}</span></span>
                    </div>
                    <div style="display:none">
                      <div class="tree"><ul>
                        ${(n.children||[]).map(renderNode).join('')}
                      </ul></div>
                    </div>
                  </li>`;
              }
              if(n.type === 'theme_style'){
                return `
                  <li>
                    <div class="node">
                      ${checkIcon(!!n.checked)}
                      <span class="name">${n.name}</span>
                    </div>
                  </li>`;
              }
              return '';
            }
            return `<div class="tree"><ul>${nodes.map(renderNode).join('')}</ul></div>`;
          }

          // -------- Layouts (names only)
          function renderLayouts(list){
            if(!list || !list.length) return "<div class='muted'>No layouts.</div>";
            const rows = list.map(L => `
              <li>
                <div class="node">
                  ${checkIcon(!!L.checked)}
                  <span class="name">${L.name}</span>
                </div>
              </li>`).join('');
            return `<div class="tree"><ul>${rows}</ul></div>`;
          }

          // -------- Relations (nested like plugin)
          function renderRelations(nodes){
            if(!nodes || !nodes.length) return "<div class='muted'>No relations.</div>";
            function renderNode(n){
              if(n.type === 'relation'){
                return `
                  <li>
                    <div class="node" onclick="toggleNode(this)">
                      <span class="caret">▸</span>
                      ${checkIcon(!!n.checked)}
                      <span class="name">${n.name}</span>
                    </div>
                    <div style="display:none">
                      <div class="tree"><ul>
                        ${(n.children||[]).map(renderNode).join('')}
                      </ul></div>
                    </div>
                  </li>`;
              }
              if(n.type === 'relation_parent' || n.type === 'relation_child'){
                return `
                  <li>
                    <div class="node">
                      <i class="fa-solid fa-info-circle"></i>
                      <span class="name">${n.name}</span>
                    </div>
                    ${(n.children && n.children.length) ? '<div class="tree"><ul>'+n.children.map(renderNode).join('')+'</ul></div>' : ''}
                  </li>`;
              }
              if(n.type === 'relation_parent_field' || n.type === 'relation_child_field'){
                return `
                  <li>
                    <div class="node">
                      ${checkIcon(!!n.checked)}
                      <span class="name">${n.name}</span>
                    </div>
                  </li>`;
              }
              return '';
            }
            return `<div class="tree"><ul>${nodes.map(renderNode).join('')}</ul></div>`;
          }
        </script>
        """

        # ------------------------------ HTML
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>QRator – Report: {pinfo['name']}</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  {css}
  {js}
</head>
<body>
  <div class="container">
    <header>
      {f'<img src="{logo_data_uri}" alt="logo" />' if (logo_data_uri := _read_logo_data_uri()) else ''}
      <div>
        <div class="title">QRator – Project Report</div>
        <div class="meta">Project: <strong>{pinfo['name']}</strong> · Saved by {pinfo['user']} · {pinfo['date']} · QGIS {pinfo['version']}</div>
      </div>
    </header>

    <div class="card toc">
      <strong>Contents</strong> —
      <a href="#summary">Summary</a> ·
      <a href="#map-section">Map</a> ·
      <a href="#layers">Layers</a> ·
      <a href="#themes">Themes</a> ·
      <a href="#layouts">Layouts</a> ·
      <a href="#relations">Relations</a>
    </div>

    <!-- SUMMARY (no map inside) -->
    <div id="summary" class="card">
      <h2>Project summary</h2>
      <div class="grid cols-4">
        <div class="counter"><div class="label"><i class="fa-solid fa-layer-group"></i> Layers</div><div class="value">{layer_count}</div></div>
        <div class="counter"><div class="label"><i class="fa-solid fa-palette"></i> Themes</div><div class="value">{theme_count}</div></div>
        <div class="counter"><div class="label"><i class="fa-solid fa-diagram-project"></i> Relations</div><div class="value">{relation_count}</div></div>
        <div class="counter"><div class="label"><i class="fa-solid fa-file-lines"></i> Layouts</div><div class="value">{layout_count}</div></div>
      </div>
      <div class="grid cols-2" style="margin-top:12px;">
        <div class="card" style="margin:0;">
          <strong>Project CRS:</strong> {pinfo['crs']['authid']} <span class="muted">({pinfo['crs']['description']})</span><br/>
          <strong>Extent:</strong> {pinfo['extent']['xmin']}, {pinfo['extent']['ymin']} → {pinfo['extent']['xmax']}, {pinfo['extent']['ymax']}
        </div>
        <div class="card" style="margin:0;">
          <strong>File:</strong> <span class="mono">{os.path.basename(self.project_path) if self.project_path else '-'}</span><br/>
          <span class="muted">Full path: <span class="mono">{self.project_path}</span></span>
        </div>
      </div>
    </div>

    <!-- MAP in its own card (no sibling empty block thereafter) -->
    <div class="card" id="map-section">
      <h2><i class="fa-solid fa-map-location-dot"></i> Map</h2>
      <div id="map"></div>
    </div>

    <div id="layers" class="card">
      <div class="section-head">
        <h2><i class="fa-solid fa-layer-group"></i> Layers</h2>
        <div class="section-actions">
          <button class="btn" onclick="expandAll('layers-tree')"><i class="fa-solid fa-plus-square"></i> Expand all</button>
          <button class="btn" onclick="collapseAll('layers-tree')"><i class="fa-regular fa-square-minus"></i> Collapse all</button>
        </div>
      </div>
      <div id="layers-tree"></div>
    </div>

    <div id="themes" class="card">
      <div class="section-head">
        <h2><i class="fa-solid fa-palette"></i> Themes</h2>
        <div class="section-actions">
          <button class="btn" onclick="expandAll('themes-tree')"><i class="fa-solid fa-plus-square"></i> Expand all</button>
          <button class="btn" onclick="collapseAll('themes-tree')"><i class="fa-regular fa-square-minus"></i> Collapse all</button>
        </div>
      </div>
      <div id="themes-tree"></div>
    </div>

    <div id="layouts" class="card">
      <h2><i class="fa-solid fa-file-lines"></i> Layouts</h2>
      <div id="layouts-list"></div>
    </div>

    <div id="relations" class="card">
      <div class="section-head">
        <h2><i class="fa-solid fa-diagram-project"></i> Relations</h2>
        <div class="section-actions">
          <button class="btn" onclick="expandAll('relations-tree')"><i class="fa-solid fa-plus-square"></i> Expand all</button>
          <button class="btn" onclick="collapseAll('relations-tree')"><i class="fa-regular fa-square-minus"></i> Collapse all</button>
        </div>
      </div>
      <div id="relations-tree"></div>
    </div>
  </div>

  <script>
    // Leaflet
    var map = L.map('map').setView([{center_lat}, {center_lon}], 12);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: '© OpenStreetMap'
    }}).addTo(map);
    var b = {json.dumps(bounds)};
    L.rectangle(b, {{weight:2, fillOpacity:0.08}}).addTo(map);
    map.fitBounds(b);

    // Data
    const LAYERS = {json.dumps(layers_tree, ensure_ascii=False)};
    const THEMES = {json.dumps(themes_tree, ensure_ascii=False)};
    const LAYOUTS = {json.dumps(layouts, ensure_ascii=False)};
    const RELATIONS = {json.dumps(relations_tree, ensure_ascii=False)};

    // Render
    document.getElementById('layers-tree').innerHTML = renderLayers(LAYERS);
    document.getElementById('themes-tree').innerHTML = renderThemes(THEMES);
    document.getElementById('layouts-list').innerHTML = renderLayouts(LAYOUTS);
    document.getElementById('relations-tree').innerHTML = renderRelations(RELATIONS);
  </script>
</body>
</html>
"""
        return html