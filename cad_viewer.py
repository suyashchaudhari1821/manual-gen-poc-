"""
cad_viewer.py
=============
Professional 3D CAD Viewer component styled to CATIA engineering visualization standards:
  • OrbitControls (360° pan, rotate, zoom with damping)
  • Balanced CATIA studio lighting with directional key, soft fill, and rim accent
  • Authentic satin mechanical PBR finish (never reflective/shiny chrome or neon blowout)
  • Harmonized engineering material color calibration (cast-iron terracotta, brass yellow, steel)
  • Sleek dark engineering viewport (#0e1117) with tone-mapped contrast
  • Top toolbar with Parts Tree, Reset, Wireframe, Grid, Model Tag, and Explode slider
  • Zero emojis throughout the interface — clean vector SVG icons and engineering badges
  • Collapsible Parts Drawer (hidden by default) with real-time search
"""

import json
import streamlit.components.v1 as components


def generate_viewer_html(
    glb_b64: str,
    model_name: str,
    parts_list: list,
    unique_parts_list: list,
    structured_parts: list = None,
    height: int = 640
) -> str:
    """Generate the full HTML/JS string for the CATIA-standard 3D CAD Viewer."""
    
    parts_meta = {}
    if structured_parts:
        for p in structured_parts:
            u_name = p.get("unique_name") or p.get("name")
            parts_meta[u_name] = p

    parts_data = []
    for i, (orig, uniq) in enumerate(zip(parts_list, unique_parts_list)):
        meta = parts_meta.get(uniq, {})
        part_num = meta.get("part_number") or f"P-{i+1:03d}"
        parts_data.append({
            "index": i + 1,
            "original_name": orig,
            "unique_name": uniq,
            "part_number": part_num,
            "is_duplicate": orig != uniq or parts_list.count(orig) > 1,
            "occurrence": parts_list[:i+1].count(orig),
            "total_occurrences": parts_list.count(orig)
        })
    
    parts_json = json.dumps(parts_data)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{model_name} - 3D CAD Viewer</title>

<!-- Three.js + OrbitControls + GLTFLoader -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js"></script>

<style>
  :root {{
    --bg-dark: #0e1117;
    --panel-bg: rgba(14, 18, 28, 0.82);
    --panel-border: rgba(56, 189, 248, 0.22);
    --accent: #0284c7;
    --accent-hover: #0369a1;
    --accent-cyan: #38bdf8;
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
    --badge-bg: rgba(56, 189, 248, 0.12);
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: var(--bg-dark);
    color: var(--text-main);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    overflow: hidden;
    height: 100vh;
    width: 100vw;
  }}

  #viewport-container {{
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    width: 100%; height: 100%;
  }}
  canvas {{ display: block; width: 100% !important; height: 100% !important; outline: none; }}

  /* Top Toolbar */
  #toolbar {{
    position: absolute;
    top: 12px; left: 16px; right: 16px;
    height: 46px;
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 10px;
    backdrop-filter: blur(14px);
    display: flex;
    align-items: center;
    padding: 0 14px;
    gap: 8px;
    z-index: 100;
    box-shadow: 0 4px 20px rgba(0,0,0,0.45);
  }}

  .tool-btn {{
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: var(--text-main);
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 11px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: all 0.2s ease;
  }}
  .tool-btn svg {{
    display: block;
    flex-shrink: 0;
  }}
  .tool-btn:hover {{
    background: var(--accent);
    border-color: var(--accent-cyan);
    box-shadow: 0 0 10px rgba(56, 189, 248, 0.3);
  }}
  .tool-btn.active {{
    background: #2563eb;
    border-color: var(--accent-cyan);
    color: #fff;
    box-shadow: 0 0 10px rgba(37, 99, 235, 0.35);
  }}

  .model-tag {{
    font-size: 12px;
    font-weight: 600;
    color: var(--text-main);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 260px;
    display: flex;
    align-items: center;
    gap: 6px;
    margin-left: 4px;
  }}
  .cad-pill {{
    background: rgba(56, 189, 248, 0.18);
    color: var(--accent-cyan);
    border: 1px solid rgba(56, 189, 248, 0.35);
    border-radius: 3px;
    padding: 1px 5px;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }}

  /* Parts Tree Drawer */
  #parts-drawer {{
    position: absolute;
    top: 66px; left: 16px; bottom: 16px;
    width: 300px;
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 10px;
    backdrop-filter: blur(14px);
    z-index: 90;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 8px 30px rgba(0,0,0,0.5);
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }}
  #parts-drawer.collapsed {{
    transform: translateX(-340px);
  }}

  .drawer-header {{
    padding: 12px 14px;
    border-bottom: 1px solid var(--panel-border);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .drawer-title {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--accent-cyan);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .search-input {{
    background: rgba(0, 0, 0, 0.45);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 5px;
    color: var(--text-main);
    padding: 6px 10px;
    font-size: 11px;
    width: 100%;
    outline: none;
    transition: border-color 0.2s;
  }}
  .search-input:focus {{
    border-color: var(--accent-cyan);
  }}

  .parts-list {{
    flex: 1;
    overflow-y: auto;
    padding: 8px;
  }}
  .part-item {{
    padding: 7px 10px;
    border-radius: 5px;
    font-size: 11px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-bottom: 4px;
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid transparent;
    transition: all 0.15s ease;
  }}
  .part-item:hover {{
    background: rgba(56, 189, 248, 0.12);
    border-color: var(--accent-cyan);
  }}
  .part-item.selected {{
    background: rgba(56, 189, 248, 0.20);
    border-color: var(--accent-cyan);
    box-shadow: 0 0 10px rgba(56, 189, 248, 0.25);
  }}
  .part-item-name {{
    font-weight: 600;
    color: var(--text-main);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .part-item-sub {{
    font-size: 10px;
    color: var(--text-muted);
  }}
  .dup-pill {{
    background: rgba(245, 158, 11, 0.18);
    color: #fbbf24;
    border: 1px solid rgba(245, 158, 11, 0.35);
    border-radius: 3px;
    padding: 1px 4px;
    font-size: 9px;
    font-weight: 700;
  }}
  .num-pill {{
    background: rgba(56, 189, 248, 0.12);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.25);
    border-radius: 3px;
    padding: 1px 4px;
    font-size: 9px;
    font-weight: 600;
  }}

  /* Floating Info Tag */
  #selected-badge {{
    position: absolute;
    bottom: 22px; left: 50%;
    transform: translateX(-50%);
    background: var(--panel-bg);
    border: 1px solid var(--accent-cyan);
    border-radius: 7px;
    padding: 7px 16px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-main);
    display: none;
    align-items: center;
    gap: 8px;
    z-index: 100;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    backdrop-filter: blur(14px);
    animation: fadeIn 0.2s ease-out;
  }}

  /* Loading Overlay */
  #loader {{
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: var(--bg-dark);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 500;
    transition: opacity 0.3s ease;
  }}
  #loader.done {{ opacity: 0; pointer-events: none; }}
  .spinner {{
    width: 38px; height: 38px;
    border: 3px solid rgba(56, 189, 248, 0.22);
    border-top-color: var(--accent-cyan);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  @keyframes fadeIn {{ from {{ opacity: 0; transform: translate(-50%, 8px); }} to {{ opacity: 1; transform: translate(-50%, 0); }} }}

  /* Scrollbars */
  ::-webkit-scrollbar {{ width: 4px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.15); border-radius: 2px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--accent); }}
</style>
</head>
<body>

<div id="viewport-container"></div>

<!-- Top Toolbar (Zero Emojis, Clean Vector SVG Icons) -->
<div id="toolbar">
  <button class="tool-btn" id="btn-tree" onclick="toggleDrawer()">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
    Parts Tree
  </button>
  <button class="tool-btn" onclick="resetCamera()">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
    Reset
  </button>
  <button class="tool-btn" id="btn-wireframe" onclick="toggleWireframe()">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
    Wireframe
  </button>
  <button class="tool-btn active" id="btn-grid" onclick="toggleGrid()">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
    Grid
  </button>

  <span class="model-tag" title="{model_name}"><span class="cad-pill">CAD</span> {model_name}</span>
</div>

<!-- Parts Drawer (starts hidden / collapsed) -->
<div id="parts-drawer" class="collapsed">
  <div class="drawer-header">
    <div class="drawer-title">
      <span>COMPONENTS</span>
      <div style="display:flex; align-items:center; gap:8px;">
        <span style="color:var(--text-muted); font-size:10px;">{len(unique_parts_list)} PARTS</span>
        <button style="background:transparent; border:none; color:var(--text-muted); cursor:pointer; font-size:16px; line-height:1; padding:0 3px;" onclick="toggleDrawer()" title="Close drawer">&times;</button>
      </div>
    </div>
    <input type="text" class="search-input" placeholder="Search part name or number..." oninput="filterParts(this.value)"/>
  </div>
  <div class="parts-list" id="parts-list"></div>
</div>

<!-- Floating Selected Part Badge -->
<div id="selected-badge">
  <div style="width:7px; height:7px; border-radius:50%; background:var(--accent-cyan); box-shadow:0 0 6px var(--accent-cyan);"></div>
  <span id="badge-text">Selected Part</span>
  <button style="background:transparent; border:none; color:var(--text-muted); cursor:pointer; font-size:16px; line-height:1; margin-left:6px;" onclick="clearSelection()">&times;</button>
</div>

<!-- Loader -->
<div id="loader">
  <div class="spinner"></div>
  <p style="margin-top:12px;font-size:12px;color:var(--text-muted);" id="loader-msg">Loading 3D CAD Assembly...</p>
</div>

<script>
  const MODEL_B64 = "{glb_b64}";
  const MODEL_NAME = "{model_name}";
  const PARTS_DATA = {parts_json};

  let scene, camera, renderer, controls;
  let modelGroup = null;
  let gridHelper;
  let raycaster, mouse;
  let isWireframe = false;
  let selectedMesh = null;
  let originalMaterials = new Map();
  let partOriginalPositions = new Map();
  let modelCenter = new THREE.Vector3();
  let modelRadius = 1;

  // CAD Selection Highlight Material (clean emerald green)
  const highlightMaterial = new THREE.MeshStandardMaterial({{
    color: 0x00E676,
    emissive: 0x00A850,
    emissiveIntensity: 0.35,
    metalness: 0.25,
    roughness: 0.50,
    wireframe: false
  }});

  function init() {{
    const container = document.getElementById('viewport-container');
    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || window.innerHeight;

    // Sleek dark engineering viewport
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0e1117);

    // Camera with vast depth range
    camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 10000000);
    camera.position.set(100, 100, 150);

    // Renderer with ACESFilmic tone mapping to eliminate highlight blowout
    renderer = new THREE.WebGLRenderer({{
      antialias: true,
      alpha: true,
      logarithmicDepthBuffer: true
    }});
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.95;
    container.appendChild(renderer.domElement);

    // Smooth OrbitControls
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.rotateSpeed = 0.85;
    controls.zoomSpeed = 1.2;
    controls.panSpeed = 0.8;
    controls.minDistance = 0.001;
    controls.maxDistance = 10000000;

    // CATIA Engineering Studio Lighting Setup (balanced, volumetric contrast)
    // 1. Soft neutral ambient light — preserves deep contours without flat wash-out
    const ambientLight = new THREE.AmbientLight(0x353a47, 0.45);
    scene.add(ambientLight);

    // 2. Primary Key Light (Top-Right-Front): sculpts curvature, fillets, and chamfers
    const keyLight = new THREE.DirectionalLight(0xfff7ee, 0.95);
    keyLight.position.set(120, 180, 140);
    keyLight.castShadow = true;
    scene.add(keyLight);

    // 3. Soft Fill Light (Left-Back): provides gentle illumination on shadowed sides
    const fillLight = new THREE.DirectionalLight(0x6b7d96, 0.35);
    fillLight.position.set(-140, 60, -100);
    scene.add(fillLight);

    // 4. Subtle Rim Accent (Back-Bottom): sharpens silhouettes
    const rimLight = new THREE.DirectionalLight(0x8da0b5, 0.22);
    rimLight.position.set(0, -100, 80);
    scene.add(rimLight);

    // Floor Grid
    gridHelper = new THREE.GridHelper(300, 30, 0x1f2533, 0x141822);
    gridHelper.position.y = -0.5;
    scene.add(gridHelper);

    // Raycaster for Picking
    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();

    // Event Listeners
    window.addEventListener('resize', onResize);

    // Differentiate drag vs click so rotating the model NEVER accidentally picks
    let isDragging = false;
    let downX = 0, downY = 0;

    renderer.domElement.addEventListener('pointerdown', (e) => {{
      downX = e.clientX;
      downY = e.clientY;
      isDragging = false;
    }});

    renderer.domElement.addEventListener('pointermove', (e) => {{
      if (Math.hypot(e.clientX - downX, e.clientY - downY) > 5) {{
        isDragging = true;
      }}
    }});

    renderer.domElement.addEventListener('pointerup', (e) => {{
      if (!isDragging) {{
        onClick(e);
      }}
    }});

    // Populate Parts List
    buildPartsListUI();

    // Load Model
    loadModel();

    // Render loop
    animate();
  }}

  function loadModel() {{
    if (!MODEL_B64) {{
      document.getElementById('loader').classList.add('done');
      return;
    }}

    document.getElementById('loader-msg').textContent = 'Loading 3D CAD Assembly...';

    const byteCharacters = atob(MODEL_B64);
    const byteArray = new Uint8Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {{
      byteArray[i] = byteCharacters.charCodeAt(i);
    }}
    const blob = new Blob([byteArray], {{ type: 'model/gltf-binary' }});
    const url = URL.createObjectURL(blob);

    const loader = new THREE.GLTFLoader();
    loader.load(
      url,
      function (gltf) {{
        modelGroup = gltf.scene;

        // Calibrate materials to authentic CATIA mechanical engineering finish
        modelGroup.traverse((child) => {{
          if (child.isMesh) {{
            if (child.material) {{
              child.material.side = THREE.DoubleSide;
              // Satin mechanical finish — eliminates plastic gloss and mirror chrome
              child.material.metalness = 0.28;
              child.material.roughness = 0.58;

              // Color calibration matching CATIA reference palette
              if (child.material.color) {{
                const col = child.material.color;
                // Harmonize neon yellow (CASING / PULLEYS) to engineering dichromate brass/gold
                if (col.r > 0.82 && col.g > 0.82 && col.b < 0.25) {{
                  col.setRGB(0.70, 0.68, 0.16);
                }}
                // Harmonize neon coral (ENGINE HOUSING) to authentic CATIA cast machinery terracotta / maroon
                else if (col.r > 0.80 && col.g < 0.50 && col.b < 0.40) {{
                  col.setRGB(0.56, 0.30, 0.28);
                }}
                // Harmonize pure neon green
                else if (col.g > 0.82 && col.r < 0.30 && col.b < 0.30) {{
                  col.setRGB(0.18, 0.58, 0.26);
                }}
                // Harmonize stark pure white
                else if (col.r > 0.90 && col.g > 0.90 && col.b > 0.90) {{
                  col.setRGB(0.76, 0.78, 0.82);
                }}
              }}

              originalMaterials.set(child, child.material.clone());
            }}
            partOriginalPositions.set(child, child.position.clone());
            child.castShadow = true;
            child.receiveShadow = true;
          }}
        }});

        // Center and frame model
        const box = new THREE.Box3().setFromObject(modelGroup);
        box.getCenter(modelCenter);
        const size = new THREE.Vector3();
        box.getSize(size);
        modelRadius = Math.max(size.x, size.y, size.z) / 2 || 1;

        // Reposition model to origin
        modelGroup.position.sub(modelCenter);
        scene.add(modelGroup);

        // Adjust camera & grid to model dimensions
        gridHelper.position.y = -size.y / 2 - 2;
        gridHelper.scale.set(size.x / 50 + 1, 1, size.z / 50 + 1);

        const dist = modelRadius * 2.3;
        camera.position.set(dist * 0.85, dist * 0.65, dist * 1.15);
        camera.lookAt(0, 0, 0);
        controls.target.set(0, 0, 0);
        controls.update();

        // Finished loading
        document.getElementById('loader').classList.add('done');
      }},
      undefined,
      function (err) {{
        console.error('Error loading GLTF model:', err);
        document.getElementById('loader-msg').textContent = 'Failed to load 3D CAD file.';
      }}
    );
  }}

  function buildPartsListUI() {{
    const listEl = document.getElementById('parts-list');
    listEl.innerHTML = '';

    PARTS_DATA.forEach((part) => {{
      const item = document.createElement('div');
      item.className = 'part-item';
      item.id = `part-item-${{part.unique_name}}`;
      item.onclick = () => selectPartByName(part.unique_name);

      const titleRow = document.createElement('div');
      titleRow.className = 'part-item-name';
      titleRow.innerHTML = `<span>${{part.original_name}}</span>`;

      const badgeGroup = document.createElement('div');
      badgeGroup.style.display = 'flex';
      badgeGroup.style.gap = '4px';

      if (part.part_number) {{
        const numBadge = document.createElement('span');
        numBadge.className = 'num-pill';
        numBadge.textContent = part.part_number;
        badgeGroup.appendChild(numBadge);
      }}

      if (part.is_duplicate) {{
        const dupBadge = document.createElement('span');
        dupBadge.className = 'dup-pill';
        dupBadge.textContent = `#${{part.occurrence}} of ${{part.total_occurrences}}`;
        badgeGroup.appendChild(dupBadge);
      }}

      titleRow.appendChild(badgeGroup);

      const subRow = document.createElement('div');
      subRow.className = 'part-item-sub';
      subRow.textContent = `Part No: ${{part.part_number || 'N/A'}} | ID: ${{part.unique_name}}`;

      item.appendChild(titleRow);
      item.appendChild(subRow);
      listEl.appendChild(item);
    }});
  }}

  function filterParts(query) {{
    const q = query.toLowerCase().trim();
    PARTS_DATA.forEach((part) => {{
      const el = document.getElementById(`part-item-${{part.unique_name}}`);
      if (el) {{
        const matches = part.original_name.toLowerCase().includes(q) ||
                        part.unique_name.toLowerCase().includes(q) ||
                        (part.part_number && part.part_number.toLowerCase().includes(q));
        el.style.display = matches ? 'flex' : 'none';
      }}
    }});
  }}

  function selectPartByName(uniqueName) {{
    if (!modelGroup) return;

    let targetMesh = null;
    modelGroup.traverse((child) => {{
      if (child.isMesh && child.name === uniqueName) {{
        targetMesh = child;
      }}
    }});

    // Fallback: match by prefix
    if (!targetMesh) {{
      modelGroup.traverse((child) => {{
        if (child.isMesh && (child.name.startsWith(uniqueName) || uniqueName.startsWith(child.name))) {{
          targetMesh = child;
        }}
      }});
    }}

    highlightMesh(targetMesh, uniqueName);
  }}

  function highlightMesh(mesh, displayName) {{
    if (selectedMesh && originalMaterials.has(selectedMesh)) {{
      selectedMesh.material = originalMaterials.get(selectedMesh).clone();
    }}

    document.querySelectorAll('.part-item').forEach(el => el.classList.remove('selected'));

    if (mesh) {{
      selectedMesh = mesh;
      mesh.material = highlightMaterial;

      const lookupName = displayName || mesh.name;
      const partInfo = PARTS_DATA.find(p => p.unique_name === lookupName || p.original_name === lookupName) || {{
        original_name: lookupName,
        unique_name: lookupName,
        part_number: 'N/A',
        is_duplicate: false,
        occurrence: 1,
        total_occurrences: 1
      }};

      const badge = document.getElementById('selected-badge');
      const badgeText = document.getElementById('badge-text');

      let dupTag = partInfo.is_duplicate ? ` <span class="dup-pill">#${{partInfo.occurrence}} of ${{partInfo.total_occurrences}}</span>` : '';
      badgeText.innerHTML = `Part: <strong>${{partInfo.original_name}}</strong> ${{dupTag}} &bull; <code>${{partInfo.unique_name}}</code>`;
      badge.style.display = 'flex';

      const listEl = document.getElementById(`part-item-${{partInfo.unique_name}}`) || document.getElementById(`part-item-${{lookupName}}`);
      if (listEl) {{
        listEl.classList.add('selected');
        listEl.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
      }}
    }} else {{
      selectedMesh = null;
      document.getElementById('selected-badge').style.display = 'none';
    }}
  }}

  function clearSelection() {{
    highlightMesh(null, null);
  }}

  function onClick(event) {{
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    if (!modelGroup) return;

    const intersects = raycaster.intersectObjects(modelGroup.children, true);
    if (intersects.length > 0) {{
      const hit = intersects[0].object;
      highlightMesh(hit, hit.name);
    }} else {{
      clearSelection();
    }}
  }}

  function onExplodeChange(val) {{
    if (!modelGroup) return;
    const factor = (parseFloat(val) / 100.0) * (modelRadius * 1.5);

    modelGroup.traverse((child) => {{
      if (child.isMesh && partOriginalPositions.has(child)) {{
        const origPos = partOriginalPositions.get(child);
        const dir = origPos.clone().normalize();
        if (dir.lengthSq() < 0.0001) {{
          dir.set(0, 1, 0);
        }}
        child.position.copy(origPos).addScaledVector(dir, factor);
      }}
    }});
  }}

  function toggleDrawer() {{
    const drawer = document.getElementById('parts-drawer');
    const btn = document.getElementById('btn-tree');
    drawer.classList.toggle('collapsed');
    btn.classList.toggle('active', !drawer.classList.contains('collapsed'));
  }}

  function toggleWireframe() {{
    isWireframe = !isWireframe;
    const btn = document.getElementById('btn-wireframe');
    btn.classList.toggle('active', isWireframe);

    if (modelGroup) {{
      modelGroup.traverse((child) => {{
        if (child.isMesh && child.material) {{
          child.material.wireframe = isWireframe;
        }}
      }});
    }}
  }}

  function toggleGrid() {{
    if (gridHelper) {{
      gridHelper.visible = !gridHelper.visible;
      document.getElementById('btn-grid').classList.toggle('active', gridHelper.visible);
    }}
  }}

  function resetCamera() {{
    if (!modelGroup) return;
    const dist = modelRadius * 2.3;
    camera.position.set(dist * 0.85, dist * 0.65, dist * 1.15);
    camera.lookAt(0, 0, 0);
    controls.target.set(0, 0, 0);
    controls.update();

    // Reset explode slider
    const explodeSlider = document.getElementById('explode-slider');
    if (explodeSlider) {{
      explodeSlider.value = 0;
      onExplodeChange(0);
    }}
  }}

  function onResize() {{
    const container = document.getElementById('viewport-container');
    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || window.innerHeight;

    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }}

  function animate() {{
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }}

  window.onload = init;
</script>
</body>
</html>
"""
    return html


def display_cad_viewer(
    glb_b64: str,
    model_name: str,
    parts_list: list,
    unique_parts_list: list,
    structured_parts: list = None,
    height: int = 640
):
    """Embed the CATIA-standard Three.js 3D CAD Viewer in Streamlit."""
    html_code = generate_viewer_html(
        glb_b64=glb_b64,
        model_name=model_name,
        parts_list=parts_list,
        unique_parts_list=unique_parts_list,
        structured_parts=structured_parts,
        height=height
    )
    components.html(html_code, height=height, scrolling=False)
