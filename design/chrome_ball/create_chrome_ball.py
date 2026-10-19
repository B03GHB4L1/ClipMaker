"""Build the compact ClipMaker chrome football and its studio preview."""
import math
import argparse
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

parser = argparse.ArgumentParser()
parser.add_argument('--brand', default='CM')
parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=True)
asset_name = 'vizorplay-football' if args.brand == 'VizorPlay' else 'cm-chrome-football'
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)


def metal(name, color, roughness):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1)
    material.use_nodes = True
    shader = material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Metallic'].default_value = 1
    shader.inputs['Roughness'].default_value = roughness
    return material


silver = metal('Satin-polished silver chrome', (0.72, 0.77, 0.79), 0.28)
green = metal('ClipMaker emerald chrome', (0.055, 0.48, 0.006), 0.32)
seam = metal('Recessed graphite silver seams', (0.09, 0.115, 0.12), 0.29)

bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1)
seed = bpy.context.object
points = [v.co.copy() for v in seed.data.vertices]
faces = [list(p.vertices) for p in seed.data.polygons]
bpy.data.objects.remove(seed, do_unlink=True)
neighbors = {i: set() for i in range(len(points))}
panels = []
for a, b, c in faces:
    for i, j in ((a, b), (b, c), (c, a)):
        neighbors[i].add(j)
        neighbors[j].add(i)
    panels.append([(points[i] * 2 + points[j]) / 3
                   for i, j in ((a, b), (b, a), (b, c), (c, b), (c, a), (a, c))])
for i, adjacent in neighbors.items():
    normal = points[i].normalized()
    tangent = normal.cross(Vector((0, 0, 1)))
    if tangent.length < 0.01:
        tangent = normal.cross(Vector((0, 1, 0)))
    tangent.normalize()
    bitangent = normal.cross(tangent)
    ring = [(points[i] * 2 + points[j]) / 3 for j in adjacent]
    ring.sort(key=lambda p: math.atan2(p.dot(bitangent), p.dot(tangent)))
    panels.append(ring)

vertices, triangles = [], []


def subdivide(a, b, c, depth):
    if depth:
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        for triple in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)):
            subdivide(*triple, depth - 1)
    else:
        index = len(vertices)
        vertices.extend([tuple(p.normalized()) for p in (a, b, c)])
        triangles.append((index, index + 1, index + 2))


for ring in panels:
    center = sum(ring, Vector()) / len(ring)
    inset = [center + (p - center) * 0.985 for p in ring]
    for i, p in enumerate(inset):
        subdivide(center, p, inset[(i + 1) % len(inset)], 3)
mesh = bpy.data.meshes.new('Spherical pentagon and hexagon panels')
mesh.from_pydata(vertices, [], triangles)
mesh.update()
football = bpy.data.objects.new('Chrome football panels', mesh)
bpy.context.collection.objects.link(football)
football.data.materials.append(silver)
for polygon in mesh.polygons:
    polygon.use_smooth = True
# Welding preserves a small file while retaining the recessed panel boundaries.
bpy.context.view_layer.objects.active = football
football.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=0.00001)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode='OBJECT')
football.select_set(False)

bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=0.992)
core = bpy.context.object
core.name = 'Recessed seam backing'
core.data.materials.append(seam)
for polygon in core.data.polygons:
    polygon.use_smooth = True
core.select_set(False)

font = bpy.data.fonts.load('C:/Windows/Fonts/bahnschrift.ttf')


def lettering(body, size, x, z):
    curve = bpy.data.curves.new('Embossed ' + body, 'FONT')
    curve.body = body
    curve.font = font
    curve.size = size
    curve.space_character = 1.06
    curve.extrude = 0.006
    curve.offset = 0.004
    curve.bevel_depth = 0.0018
    curve.bevel_resolution = 2
    curve.resolution_u = 6
    obj = bpy.data.objects.new('Emerald chrome ' + body, curve)
    bpy.context.collection.objects.link(obj)
    obj.location = (x, -1, z)
    obj.rotation_euler = (math.pi / 2, 0, 0)
    curve.materials.append(green)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target='MESH')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # Tessellate before wrapping so long letter strokes follow the sphere.
    letter_mesh = bmesh.new()
    letter_mesh.from_mesh(obj.data)
    bmesh.ops.triangulate(letter_mesh, faces=list(letter_mesh.faces))
    long_edges = [edge for edge in letter_mesh.edges if edge.calc_length() > 0.065]
    bmesh.ops.subdivide_edges(letter_mesh, edges=long_edges, cuts=4, use_grid_fill=True)
    letter_mesh.to_mesh(obj.data)
    letter_mesh.free()
    # Wrap the raised lettering around the front of the sphere.
    for vertex in obj.data.vertices:
        px, py, pz = vertex.co
        vertex.co.y = -math.sqrt(max(0.01, 1 - px * px - pz * pz)) + (py + 1) - 0.008
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.select_set(False)
    return obj


if args.brand == 'VizorPlay':
    lettering('VizorPlay', 0.37, -0.78, -0.12)
else:
    lettering('CM', 1.02, -0.73, -0.27)
    lettering('1.3', 0.36, 0.29, 0.20)

asset_objects = [football, core] + [o for o in bpy.context.scene.objects if o.name.startswith('Emerald chrome')]
root = bpy.data.objects.new(args.brand + ' chrome football', None)
bpy.context.collection.objects.link(root)
for obj in asset_objects:
    obj.parent = root


def aim(obj, target=(0, 0, 0)):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def light(name, position, power, size, size_y, color=(1, 1, 1)):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = power
    data.shape = 'RECTANGLE'
    data.size = size
    data.size_y = size_y
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = position
    aim(obj)


light('Large left softbox', (-3, -3, 3), 250, 4, 5)
light('Right strip reflection', (3, -1, 1), 130, 2, 4)
light('Top rim softbox', (0, 1, 3), 220, 4, 3)
light('Front lettering fill', (0, -4, 0.5), 70, 3, 2)
scene = bpy.context.scene
scene.world.use_nodes = True
scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0.3, 0.32, 0.34, 1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value = 0.35
camera_data = bpy.data.cameras.new('Product camera')
camera = bpy.data.objects.new('Product camera', camera_data)
bpy.context.collection.objects.link(camera)
camera.location = (0, -5.2, 0.28)
aim(camera)
camera_data.type = 'ORTHO'
camera_data.ortho_scale = 2.5
scene.camera = camera
scene.render.engine = 'CYCLES'
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.render.resolution_x = 1200
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.view_settings.view_transform = 'AgX'
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.filepath = str(OUT / ('vizorplay-football.png' if args.brand == 'VizorPlay' else 'chrome-football-preview.png'))

for obj in bpy.context.selected_objects:
    obj.select_set(False)
for obj in asset_objects:
    obj.select_set(True)
root.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT / (asset_name + '.glb')),
    use_selection=True, export_format='GLB', export_yup=True)
# Embedded font data keeps the editable studio file portable.
bpy.ops.file.pack_all()
scene.tool_settings.use_keyframe_insert_auto = False
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.region_3d.view_perspective = 'CAMERA'
            area.spaces.active.shading.type = 'MATERIAL'
bpy.context.preferences.filepaths.save_version = 0
if args.brand != 'VizorPlay':
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / (asset_name + '.blend')))
bpy.ops.render.render(write_still=True)
print('CLIPMAKER_ASSET_COMPLETE', OUT)
