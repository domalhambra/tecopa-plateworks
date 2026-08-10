# scripts/hero_scene.py
"""Runs INSIDE Blender (blender --background --python scripts/hero_scene.py -- scene.json).

Builds the hero-plate scene from the sidecar JSON written by scripts/hero_plate.py: a
plane covering the render window in real metres, displaced by the exported 16-bit
heightmap, the engine's own hypsometric/biome colour draped over it, one sun with a
real angular size (so shadows get a penumbra), an orthographic top-down camera whose
frame IS the window, and a Cycles render with denoising.

Imports nothing from `app/` -- it runs inside Blender's own Python, which has neither
the venv nor the engine on its path. Every decision it needs was made in the sidecar;
this file only builds what it is told to. In particular the sun's rotation arrives
precomputed (`sun.rotation_euler`), because that is the one piece of geometry worth
testing outside Blender.

Deliberately NOT deterministic -- a hero plate is a performance. The archival record
stays the manifest inside the source PNG, which the CLI re-embeds unchanged."""
import json
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
with open(args[0]) as f:
    side = json.load(f)

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = side["samples"]
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = side["resolution"]
scene.render.resolution_percentage = 100        # never let a % scale break the shape
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.image_settings.color_depth = "16"
scene.render.filepath = side["out"]

for obj in list(bpy.data.objects):        # empty the default scene
    bpy.data.objects.remove(obj, do_unlink=True)

# The ground: one plane, sized in metres, centred on the window's centre. The window's
# own centre is the origin, so the camera below needs no offset.
w_m, h_m = side["plane_size"]
bpy.ops.mesh.primitive_plane_add(size=1.0)
plane = bpy.context.active_object
plane.scale = (w_m, h_m, 1.0)             # primitive_plane_add(size=1) spans -0.5..0.5
bpy.ops.object.transform_apply(scale=True)

mat = bpy.data.materials.new("plate")
mat.use_nodes = True
mat.cycles.displacement_method = "DISPLACEMENT"
nt = mat.node_tree
bsdf = nt.nodes["Principled BSDF"]
bsdf.inputs["Roughness"].default_value = 1.0      # matte paper, not wet rock
color = nt.nodes.new("ShaderNodeTexImage")
color.image = bpy.data.images.load(side["color_png"])
color.interpolation = "Cubic"
nt.links.new(color.outputs["Color"], bsdf.inputs["Base Color"])

height = nt.nodes.new("ShaderNodeTexImage")
height.image = bpy.data.images.load(side["height_png"])
height.image.colorspace_settings.name = "Non-Color"   # elevation is data, not colour
height.interpolation = "Cubic"
disp = nt.nodes.new("ShaderNodeDisplacement")
# the heightmap is 0..1 over the window's own elevation range, so the scale that puts
# it back in metres is exactly that range (times the operator's exaggeration).
disp.inputs["Scale"].default_value = side["elev_range_m"] * side["z_exaggeration"]
disp.inputs["Midlevel"].default_value = 0.0
nt.links.new(height.outputs["Color"], disp.inputs["Height"])
nt.links.new(disp.outputs["Displacement"],
             nt.nodes["Material Output"].inputs["Displacement"])
plane.data.materials.append(mat)

# Adaptive subdivision gives the displacement real geometry (and therefore real cast
# shadows) at whatever density the camera actually resolves.
sub = plane.modifiers.new("subdiv", "SUBSURF")
sub.subdivision_type = "SIMPLE"
plane.cycles.use_adaptive_subdivision = True

sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
bpy.context.collection.objects.link(sun)
sun.data.energy = 4.0
sun.data.angle = __import__("math").radians(side["sun"]["angular_size_deg"])
sun.rotation_euler = tuple(side["sun"]["rotation_euler"])

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
bpy.context.collection.objects.link(cam)
cam.data.type = "ORTHO"
# ortho_scale is the frame size along the LARGER pixel dimension; the CLI already
# picked the matching ground extent, so this is a straight copy.
cam.data.ortho_scale = side["ortho_scale"]
cam.data.clip_start = 1.0
cam.data.clip_end = side["elev_range_m"] * 20.0 + 1000.0
# straight down from well above the highest displaced ground (default rotation looks
# along -Z, which is what a plan-view plate wants)
cam.location = (0.0, 0.0, side["elev_range_m"] * 10.0 + 500.0)
scene.camera = cam

bpy.ops.render.render(write_still=True)
