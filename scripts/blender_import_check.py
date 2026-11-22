"""Blender headless import proof for the Meshwright v1 GLBs (docs/15 section 7, promo-1 US-006).

Like ccore's Godot screenshots, this proves the exported GLBs load in a real 3D tool. Run it inside
Blender so the whole check is repeatable:

    blender -b --factory-startup --python scripts/blender_import_check.py -- \
        --glbs a.glb,b.glb --report release/v1/promo/out/blender/report.json \
        [--render FILE --layout release/v1/promo/scenes/village.json]

For every GLB it records ok/error next to the object, mesh, evaluated-triangle, material and action
(animation) counts; the JSON report has one row per GLB plus totals. Each GLB is imported in its own
Blender subprocess, because a few exported assets make Blender 5.2 abort natively while parsing a node
name whose fractional part has ten or more digits (``std::stoi`` out of range) — the GLB is valid
(three.js loads it), the crash is Blender's name parser. The driver imports a **name-safe temp copy** made
by ``scripts/glb_names.mjs`` (names only, geometry untouched) and each row records ``raw_names_crash_risk``
true when that sanitizer would rename anything in the raw GLB. Isolating each import means a GLB that still
aborts becomes a row with ``ok: false`` and the signal instead of aborting the whole run, so every GLB is
reported; any leftover worker process is killed when the run ends.

With ``--render FILE`` it also imports every item of ``--layout``, places it by the same rules as
``scripts/showcase_scene.mjs`` (lowest point on the plinth top, x/z centre at the item's x/z, uniform
``height_m``/``scale`` and a Y rotation, water items lowered by ``drop_m``), adds a plinth, a sun and a
camera aimed the way the layout camera is (yaw, pitch, fov, zoom), and renders the scene twice at
``--width`` x ``--height``: EEVEE to ``FILE`` and the Workbench "random colours" pass to the parts image
(``--render-parts``, default: ``eevee`` in the name replaced by ``parts``). The render imports its items
from a name-safe temp copy too, so the picture is still produced.
Blender is imported only inside Blender, so this module stays importable for the wrapper test.
"""
import argparse
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile

try:  # only present when running inside Blender
    import bpy
except Exception:  # pragma: no cover - the wrapper test imports this module without Blender
    bpy = None

# The name sanitizer from promo-1 US-008; importing it (never copying its rule) keeps one source of truth.
NAMES_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glb_names.mjs")
# A stuck import must not hold the gate forever; a normal import takes a few seconds.
WORKER_TIMEOUT = 120
# Every worker Blender this run started, so the run can kill any that is somehow still alive.
_worker_procs = []


def build_parser():
    parser = argparse.ArgumentParser(
        prog="blender -b --factory-startup --python scripts/blender_import_check.py --",
        description="Import GLBs into Blender and report what loaded (promo-1 US-006).",
    )
    parser.add_argument("--glbs", help="comma-separated GLB paths to import and check")
    parser.add_argument("--report", help="JSON report output path")
    parser.add_argument("--render", help="EEVEE render output PNG (needs --layout)")
    parser.add_argument("--render-parts", dest="render_parts",
                        help="Workbench parts render output PNG (default: --render with eevee -> parts)")
    parser.add_argument("--layout", help="layout JSON to compose for --render")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--worker", action="store_true",
                        help="import the (name-safe) GLBs in this process (used by the driver; no subprocesses)")
    return parser


def parts_path_for(render_path):
    """The Workbench parts image beside the EEVEE render: ``eevee`` -> ``parts``, else ``_parts``."""
    root, ext = os.path.splitext(render_path)
    if root.endswith("eevee"):
        root = root[: -len("eevee")] + "parts"
    else:
        root = root + "_parts"
    return root + ext


def split_glbs(value):
    return [part.strip() for part in value.split(",") if part.strip()]


# --- Name sanitizing (reuses scripts/glb_names.mjs) ----------------------------------------------

def sanitize_glb_copy(glb_path, workdir, tag):
    """Write a name-safe temp copy with ``scripts/glb_names.mjs`` (names only, geometry untouched).

    Returns ``(path, renamed)``: ``path`` is the copy (or ``glb_path`` unchanged when node could not run
    the sanitizer) and ``renamed`` is how many name strings the sanitizer rewrote, so a caller can flag
    the raw GLB's crash risk.
    """
    out_path = os.path.join(workdir, "safe-%s-%s" % (tag, os.path.basename(glb_path)))
    try:
        proc = subprocess.run(["node", NAMES_SCRIPT, "--in", glb_path, "--out", out_path],
                              capture_output=True, text=True)
    except OSError:
        return glb_path, 0
    if proc.returncode != 0 or not os.path.exists(out_path):
        return glb_path, 0
    try:
        renamed = int(json.loads(proc.stdout.strip().splitlines()[-1])["renamed"])
    except (ValueError, KeyError, IndexError):
        renamed = 0
    return out_path, renamed


# --- Blender-side import and measurement ---------------------------------------------------------

def _reset_scene():
    """An empty scene with no leftover meshes, materials or actions from the previous import."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _count_triangles(depsgraph, objects):
    total = 0
    for obj in objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        try:
            mesh = evaluated.to_mesh()
        except Exception:
            continue
        mesh.calc_loop_triangles()
        total += len(mesh.loop_triangles)
        evaluated.to_mesh_clear()
    return total


def check_glb(path):
    """Reset, import one GLB and return its report row."""
    _reset_scene()
    try:
        bpy.ops.import_scene.gltf(filepath=path)
    except Exception as exc:
        return {"file": path, "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    scene_objects = list(bpy.context.scene.objects)
    mesh_objects = [o for o in scene_objects if o.type == "MESH"]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return {
        "file": path,
        "ok": True,
        "objects": len(scene_objects),
        "meshes": len(mesh_objects),
        "triangles": _count_triangles(depsgraph, mesh_objects),
        "materials": len(bpy.data.materials),
        "actions": len(bpy.data.actions),
    }


# --- Driver: one subprocess per GLB so a native crash is a reported row ---------------------------

def _blender_binary():
    path = getattr(bpy.app, "binary_path", None) if bpy is not None else None
    return path or shutil.which("blender") or "blender"


def _exit_reason(code):
    if code is None:
        return "no exit status"
    if code < 0:
        try:
            return "killed by signal %d (%s)" % (-code, signal.Signals(-code).name)
        except ValueError:
            return "killed by signal %d" % (-code)
    return "exit code %d" % code


def _tail(stream):
    for line in reversed((stream or "").splitlines()):
        line = line.strip()
        if line and not line.startswith(("Info:", "Fra:", "Blender ", "Saved:")):
            return line
    return ""


def _run_worker(cmd):
    """Start one worker Blender, wait for it, and return (returncode, stdout, stderr)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _worker_procs.append(proc)
    try:
        out, err = proc.communicate(timeout=WORKER_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    return proc.returncode, out, err


def _kill_leftovers():
    """Kill any worker Blender that is somehow still alive, so the run leaves no process behind."""
    killed = 0
    for proc in _worker_procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
            killed += 1
    _worker_procs.clear()
    return killed


def _worker_row(glb, label, script_path, workdir, index):
    """Run the import for one (name-safe) GLB in a child Blender; a crash becomes a failure row."""
    report_path = os.path.join(workdir, "row-%d.json" % index)
    code, out, err = _run_worker(
        [_blender_binary(), "-b", "--factory-startup", "--python", script_path, "--",
         "--glbs", glb, "--report", report_path, "--worker"])
    if os.path.exists(report_path):  # a caught error (exit 1) still leaves a specific row behind
        try:
            with open(report_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if data.get("glbs"):
                row = data["glbs"][0]
                row["file"] = label  # report the original path, not the temp copy
                return row
        except (OSError, ValueError):
            pass
    reason = _exit_reason(code)
    detail = _tail(err) or _tail(out)
    error = "Blender aborted while importing this GLB: %s" % reason
    if detail:
        error += ": %s" % detail
    return {"file": label, "ok": False, "error": error}


def check_all(paths, script_path, workdir):
    """Sanitize each GLB, import the copy in its own worker, and return one row per GLB."""
    rows = []
    try:
        for index, path in enumerate(paths):
            safe, renamed = sanitize_glb_copy(path, workdir, str(index))
            row = _worker_row(safe, path, script_path, workdir, index)
            row["raw_names_crash_risk"] = renamed > 0
            rows.append(row)
    finally:
        _kill_leftovers()
    return rows


def _write_report(path, rows):
    ok = [row for row in rows if row["ok"]]
    report = {
        "blender": bpy.app.version_string,
        "glbs": rows,
        "totals": {
            "count": len(rows),
            "ok": len(ok),
            "failed": len(rows) - len(ok),
            "triangles": sum(row.get("triangles", 0) for row in ok),
        },
    }
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    return report


def _print_report(report):
    for row in report["glbs"]:
        flag = " (name-fixed)" if row.get("raw_names_crash_risk") else ""
        if row["ok"]:
            print("ok %s objects=%d meshes=%d triangles=%d materials=%d actions=%d%s"
                  % (row["file"], row["objects"], row["meshes"], row["triangles"],
                     row["materials"], row["actions"], flag))
        else:
            print("FAIL %s %s%s" % (row["file"], row["error"], flag))
    totals = report["totals"]
    print("checked %d GLB(s): %d ok, %d failed; %d triangles"
          % (totals["count"], totals["ok"], totals["failed"], totals["triangles"]))


# --- Layout composition and render ---------------------------------------------------------------

def _vec(corner):
    from mathutils import Vector
    return Vector(corner)


def _world_bbox(objects):
    mins = [math.inf, math.inf, math.inf]
    maxs = [-math.inf, -math.inf, -math.inf]
    for obj in objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ _vec(corner)
            for i in range(3):
                mins[i] = min(mins[i], world[i])
                maxs[i] = max(maxs[i], world[i])
    return mins[0], mins[1], mins[2], maxs[0], maxs[1], maxs[2]


def _import_objects(path):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    return [o for o in bpy.context.scene.objects if o not in before]


def _import_item(glb_path, workdir, tag):
    """Import an item's GLB from a name-safe copy, so a crashing node name cannot stop the render."""
    safe, renamed = sanitize_glb_copy(glb_path, workdir, tag)
    return _import_objects(safe), renamed > 0


def _resolve(path, base_dir):
    if os.path.isabs(path) and os.path.exists(path):
        return path
    if os.path.exists(path):
        return os.path.abspath(path)
    return os.path.join(base_dir, path)


def _new_empty(name):
    empty = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(empty)
    return empty


def _material(name, rgb):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
        bsdf.inputs["Roughness"].default_value = 0.9
    return material


def _hex_rgb(text, default):
    if text is None:
        return default
    try:
        value = int(str(text).replace("#", "").replace("0x", ""), 16)
    except ValueError:
        return default
    channels = [((value >> 16) & 255) / 255.0, ((value >> 8) & 255) / 255.0, (value & 255) / 255.0]
    return tuple(c ** 2.2 for c in channels)  # sRGB -> linear


def _add_plinth(shape, size_m, top_color):
    thickness = size_m * 0.06
    if shape == "round":
        bpy.ops.mesh.primitive_cylinder_add(radius=size_m / 2, depth=thickness,
                                            location=(0, 0, -thickness / 2), vertices=96)
    else:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -thickness / 2))
        bpy.context.active_object.scale = (size_m, size_m, thickness)
    plinth = bpy.context.active_object
    plinth.name = "plinth"
    plinth.data.materials.append(_material("plinth", top_color))
    return plinth


def _add_lights_and_world():
    scene = bpy.context.scene
    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 3.0
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (math.radians(50), 0.0, math.radians(30))
    scene.collection.objects.link(sun)

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.82, 0.85, 0.9, 1.0)
        background.inputs[1].default_value = 0.7
    scene.world = world


def _add_camera(centre, radius, camera):
    yaw = float(camera.get("yaw", 35))
    pitch = float(camera.get("pitch", 22))
    fov = float(camera.get("fov", 30))
    zoom = float(camera.get("zoom", 1)) or 1.0
    # three.js dirFor(yaw, pitch) mapped to Blender by (x, y, z)_gltf = (x, -z, y)_blender.
    yaw_r, pitch_r = math.radians(yaw), math.radians(pitch)
    direction = (math.sin(yaw_r) * math.cos(pitch_r), -math.cos(yaw_r) * math.cos(pitch_r), math.sin(pitch_r))
    distance = radius / math.sin(math.radians(fov) / 2) * 1.08 / zoom
    position = tuple(centre[i] + direction[i] * distance for i in range(3))

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.sensor_fit = "VERTICAL"
    cam_data.angle_y = math.radians(fov)
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = position
    cam.rotation_euler = (_vec(centre) - _vec(position)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam


def compose_layout(layout, width, height, render_path, parts_path):
    """Place the layout's items, add a plinth, sun and matching camera, then render EEVEE + Workbench."""
    _reset_scene()
    base_dir = os.path.dirname(os.path.abspath(layout["_path"]))
    water = layout.get("water") or {}
    drop = float(water.get("drop_m", 0.01)) if water else 0.0
    scene = bpy.context.scene
    scene_objects = []
    renamed = 0
    workdir = tempfile.mkdtemp(prefix="blender-import-check-")

    for index, item in enumerate(layout["items"]):
        glb_path = _resolve(item["glb"], base_dir)
        if not os.path.exists(glb_path):
            raise SystemExit("missing GLB: %s" % glb_path)
        tag = item.get("id") or str(index)
        objects, fixed = _import_item(glb_path, workdir, tag)
        renamed += 1 if fixed else 0
        pivot = _new_empty("pivot:%s" % (item.get("id") or os.path.basename(glb_path)))
        for obj in objects:
            obj.parent = pivot
        bpy.context.view_layer.update()

        box = _world_bbox(objects)
        raw_height = box[5] - box[2]
        if item.get("height_m") is None:
            scale = float(item.get("scale", 1))
        else:
            scale = float(item["height_m"]) / raw_height if raw_height > 0 else 1.0
        pivot.scale = (scale, scale, scale)
        pivot.rotation_euler = (0.0, 0.0, math.radians(float(item.get("rot_y_deg", 0))))
        bpy.context.view_layer.update()

        box = _world_bbox(objects)
        centre_x = (box[0] + box[3]) / 2
        centre_y = (box[1] + box[4]) / 2
        base_z = -drop if item.get("on_water") else 0.0
        pivot.location = (float(item["x"]) - centre_x, -float(item["z"]) - centre_y, base_z - box[2])
        bpy.context.view_layer.update()
        scene_objects.append(pivot)
        scene_objects.extend(objects)

    plinth_spec = layout.get("plinth", {})
    plinth = _add_plinth(plinth_spec.get("shape", "round"), float(plinth_spec.get("size_m", 50)),
                         _hex_rgb(plinth_spec.get("top"), (0.61, 0.81, 0.48)))
    scene_objects.append(plinth)
    bpy.context.view_layer.update()

    _add_lights_and_world()

    box = _world_bbox(scene_objects)
    centre = ((box[0] + box[3]) / 2, (box[1] + box[4]) / 2, (box[2] + box[5]) / 2)
    radius = max(math.dist((box[0], box[1], box[2]), (box[3], box[4], box[5])) / 2, 1e-3)
    _add_camera(centre, radius, layout.get("camera", {}))

    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    _ensure_dir(render_path)
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.filepath = render_path
    bpy.ops.render.render(write_still=True)

    if parts_path:
        _ensure_dir(parts_path)
        scene.render.engine = "BLENDER_WORKBENCH"
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.color_type = "RANDOM"
        scene.render.filepath = parts_path
        bpy.ops.render.render(write_still=True)

    shutil.rmtree(workdir, ignore_errors=True)
    return renamed


def _ensure_dir(path):
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)


def main(argv=None):
    if bpy is None:
        raise SystemExit("run inside Blender: blender -b --factory-startup --python "
                         "scripts/blender_import_check.py -- --glbs ... --report ...")
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = build_parser().parse_args(argv)
    if not args.glbs or not args.report:
        raise SystemExit("--glbs and --report are required\n" + build_parser().format_help())
    if args.render and not args.layout:
        raise SystemExit("--render needs --layout\n" + build_parser().format_help())

    paths = split_glbs(args.glbs)
    for path in paths:
        if not os.path.exists(path):
            raise SystemExit("missing GLB: %s" % path)

    if args.worker:
        rows = [check_glb(path) for path in paths]
    else:
        with tempfile.TemporaryDirectory(prefix="blender-import-rows-") as workdir:
            rows = check_all(paths, os.path.abspath(__file__), workdir)

    report = _write_report(args.report, rows)
    _print_report(report)

    if args.render:
        with open(args.layout, "r", encoding="utf-8") as handle:
            layout = json.load(handle)
        layout["_path"] = args.layout
        parts_path = args.render_parts or parts_path_for(args.render)
        renamed = compose_layout(layout, args.width, args.height, args.render, parts_path)
        if renamed:
            print("note: %d layout GLB(s) imported from a name-safe copy so Blender's importer does not abort"
                  % renamed)
        print("rendered %s and %s at %dx%d" % (args.render, parts_path, args.width, args.height))

    return 0 if report["totals"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
