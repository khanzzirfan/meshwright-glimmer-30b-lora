// Shared studio look for the showcase renderers (docs/15, promo-1 US-002).
//
// This is a browser-side module: each renderer serves it to its page by URL, so the file itself must not import
// anything — it receives the three.js namespace as an argument instead. scripts/showcase_render.mjs (single hero
// shots) and scripts/showcase_scene.mjs (dioramas) both import it, so the renderer settings, the lights, the
// contact shadow and the plinth are defined once instead of copied into each renderer.

// The renderer every showcase render uses: sRGB output, ACES tone mapping and soft PCF shadows on a transparent
// background. The caller sets the drawing-buffer size after it knows the output dimensions.
export function createStudioRenderer(T, canvas) {
  const renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  renderer.setClearColor(0x000000, 0);
  return renderer;
}

// The studio lights, sized to a subject radius r: a soft hemisphere fill, a warm key that casts the shadow, and a
// cool rim from behind.
export function addStudioLights(T, scene, r) {
  scene.add(new T.HemisphereLight(0xffffff, 0x8a8f99, 1.3));
  const key = new T.DirectionalLight(0xfff4e6, 2.6);
  key.position.set(r * 1.6, r * 3.2, r * 2.2); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048); key.shadow.radius = 6; key.shadow.bias = -0.0005;
  const sc = key.shadow.camera; sc.left = sc.bottom = -r * 1.5; sc.right = sc.top = r * 1.5; sc.near = 0.01; sc.far = r * 10;
  scene.add(key);
  const rim = new T.DirectionalLight(0xdfe8ff, 1.2); rim.position.set(-r * 2, r * 1.5, -r * 2); scene.add(rim);
  return key;
}

// A contact-shadow catcher on an invisible ground plane at y = groundY, sized to the subject radius r.
export function addContactShadow(T, scene, r, groundY = 0) {
  const ground = new T.Mesh(new T.PlaneGeometry(r * 6, r * 6), new T.ShadowMaterial({ opacity: 0.22 }));
  ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; ground.position.y = groundY; scene.add(ground);
  return ground;
}

// A slab whose top face sits at y = 0 and which extends down by its height; the extrusion runs along y.
export function slab(T, shape, height, bevel) {
  const depth = Math.max(height - 2 * bevel, height * 0.5);
  const geo = new T.ExtrudeGeometry(shape, { depth, bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 2, steps: 1, curveSegments: 64 });
  geo.rotateX(-Math.PI / 2);
  geo.translate(0, -(depth + bevel), 0);
  return geo;
}

// The plinth outline centred on the origin: a circle of diameter size, or a square of side size.
export function plinthShape(T, kind, size) {
  const shape = new T.Shape();
  if (kind === 'round') { shape.absarc(0, 0, size / 2, 0, Math.PI * 2, false); return shape; }
  const h = size / 2;
  shape.moveTo(-h, -h); shape.lineTo(h, -h); shape.lineTo(h, h); shape.lineTo(-h, h); shape.closePath();
  return shape;
}

// One named half of a square plinth outline centred on the origin (front = +z, back = -z, left = -x,
// right = +x) in the plinth's shape space, whose +y maps to world -z once slab() rotates it. Used for a
// harbour's land shelf, which covers the half that is not water.
export function halfSquareShape(T, size, side) {
  const h = size / 2;
  const shape = new T.Shape();
  if (side === 'front') { shape.moveTo(-h, -h); shape.lineTo(h, -h); shape.lineTo(h, 0); shape.lineTo(-h, 0); }
  else if (side === 'back') { shape.moveTo(-h, 0); shape.lineTo(h, 0); shape.lineTo(h, h); shape.lineTo(-h, h); }
  else if (side === 'right') { shape.moveTo(0, -h); shape.lineTo(h, -h); shape.lineTo(h, h); shape.lineTo(0, h); }
  else { shape.moveTo(-h, -h); shape.lineTo(0, -h); shape.lineTo(0, h); shape.lineTo(-h, h); }
  shape.closePath();
  return shape;
}

// A thin flat shelf covering one half of a square plinth footprint with its top surface at y = 0, in the land
// colour. A harbour lays this over the half that is not water so the water (the plinth top, lowered) reads
// drop_m below the land. Returns a mesh; add it to the scene.
export function makeLandShelf(T, size, side, height, color) {
  const mesh = new T.Mesh(slab(T, halfSquareShape(T, size, side), height, 0), new T.MeshStandardMaterial({ color, roughness: 0.92, metalness: 0 }));
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

// A bevelled diorama slab whose top surface is at y = 0: a thin top layer in topColor over a body in sideColor.
// Returns {group, thickness, topH, bodyH}; add the group to the scene. Its bottom sits at y = -thickness.
export function makePlinth(T, kind, size, thickness, topColor, sideColor) {
  const topH = thickness * 0.28;
  const bodyH = thickness - topH;
  const bevel = Math.min(size * 0.012, bodyH * 0.35);
  const shape = plinthShape(T, kind, size);
  const topper = new T.Mesh(slab(T, shape, topH, 0), new T.MeshStandardMaterial({ color: topColor, roughness: 0.92, metalness: 0 }));
  const body = new T.Mesh(slab(T, shape, bodyH, bevel), new T.MeshStandardMaterial({ color: sideColor, roughness: 0.92, metalness: 0 }));
  body.position.y = -topH;                      // the base sits under the thin top layer
  const group = new T.Group();
  for (const part of [topper, body]) { part.castShadow = true; part.receiveShadow = true; group.add(part); }
  return { group, thickness, topH, bodyH };
}
