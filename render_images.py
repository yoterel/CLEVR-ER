from __future__ import print_function
import math, sys, random, argparse, json, os
from datetime import datetime as dt
from collections import Counter
from pathlib import Path
"""
Supports Blender 2.9.3 <= version <= 3.0.0 
This file expects to be run from Blender like this:
blender --background --python render_images.py -- [arguments to this script]
"""
INSIDE_BLENDER = True
try:
    import bpy, bpy_extras
    from mathutils import Vector
except ImportError as e:
    INSIDE_BLENDER = False
if INSIDE_BLENDER:
    blender_version = bpy.app.version
    try:
        import utils
        assert utils.version_supported(blender_version)
    except ImportError as e:
        print("\nERROR !")
        print("Running render_images.py from Blender and cannot import utils.py.")
        print("You may need to add a .pth file to the site-packages of Blender's")
        print("bundled python with a command like this:\n")
        print("echo $PWD > $BLENDER/$VERSION/python/lib/python3.5/site-packages/liquid.pth")
        print("\nWhere: \n$PWD is current working directory ({})\n"
              "$BLENDER is the directory where Blender is installed ({})\n"
              "$VERSION is your Blender version ({}).".format(Path().absolute(),
                                                              Path(bpy.app.binary_path).parent,
                                                              blender_version))
        sys.exit(1)
parser = argparse.ArgumentParser()

# Input options
parser.add_argument('--base_scene_blendfile', default='data/base_scene.blend',
                    help="Base blender file on which all scenes are based; includes " +
                         "ground plane, lights, and camera.")
parser.add_argument('--properties_json', default='data/properties.json',
                    help="JSON file defining objects, materials, sizes, and colors. " +
                         "The \"colors\" field maps from CLEVR color names to RGB values; " +
                         "The \"sizes\" field maps from CLEVR size names to scalars used to " +
                         "rescale object models; the \"materials\" and \"shapes\" fields map " +
                         "from CLEVR material and shape names to .blend files in the " +
                         "--object_material_dir and --shape_dir directories respectively.")
parser.add_argument('--shape_dir', default='data/shapes',
                    help="Directory where .blend files for object models are stored")
parser.add_argument('--material_dir', default='data/materials',
                    help="Directory where .blend files for materials are stored")
parser.add_argument('--shape_color_combos_json', default=None,
                    help="Optional path to a JSON file mapping shape names to a list of " +
                         "allowed color names for that shape. This allows rendering images " +
                         "for CLEVR-CoGenT.")

# Settings for objects
parser.add_argument('--liquid_simulation', action='store_true', default=False)
parser.add_argument('--min_objects', default=2, type=int,
                    help="The minimum number of objects to place in each scene")
parser.add_argument('--max_objects', default=2, type=int,
                    help="The maximum number of objects to place in each scene")
parser.add_argument('--min_dist', default=0.25, type=float,
                    help="The minimum allowed distance between object centers")
parser.add_argument('--margin', default=0.4, type=float,
                    help="Along all cardinal directions (left, right, front, back), all " +
                         "objects will be at least this distance apart. This makes resolving " +
                         "spatial relationships slightly less ambiguous.")
parser.add_argument('--min_pixels_per_object', default=200, type=int,
                    help="All objects will have at least this many visible pixels in the " +
                         "final rendered images; this ensures that no objects are fully " +
                         "occluded by other objects.")
parser.add_argument('--max_retries', default=50, type=int,
                    help="The number of times to try placing an object before giving up and " +
                         "re-placing all objects in the scene.")

# Output settings
parser.add_argument('--start_idx', default=0, type=int,
                    help="The index at which to start for numbering rendered images. Setting " +
                         "this to non-zero values allows you to distribute rendering across " +
                         "multiple machines and recombine the results later.")
parser.add_argument('--num_images', default=5, type=int,
                    help="The number of images to render")
parser.add_argument('--filename_prefix', default='CLEVR',
                    help="This prefix will be prepended to the rendered images and JSON scenes")
parser.add_argument('--split', default='new',
                    help="Name of the split for which we are rendering. This will be added to " +
                         "the names of rendered images, and will also be stored in the JSON " +
                         "scene structure for each image.")
parser.add_argument('--output_image_dir', default='../output/images/',
                    help="The directory where output images will be stored. It will be " +
                         "created if it does not exist.")
parser.add_argument('--output_scene_dir', default='../output/scenes/',
                    help="The directory where output JSON scene structures will be stored. " +
                         "It will be created if it does not exist.")
parser.add_argument('--output_cache_dir', default='../output/cache/',
                    help="The directory where output JSON scene structures will be stored. " +
                         "It will be created if it does not exist.")
parser.add_argument('--output_scene_file', default='../output/CLEVR_scenes.json',
                    help="Path to write a single JSON file containing all scene information")
parser.add_argument('--output_blend_dir', default='output/blendfiles',
                    help="The directory where blender scene files will be stored, if the " +
                         "user requested that these files be saved using the " +
                         "--save_blendfiles flag; in this case it will be created if it does " +
                         "not already exist.")
parser.add_argument('--save_blendfiles', type=int, default=0,
                    help="Setting --save_blendfiles 1 will cause the blender scene file for " +
                         "each generated image to be stored in the directory specified by " +
                         "the --output_blend_dir flag. These files are not saved by default " +
                         "because they take up ~5-10MB each.")
parser.add_argument('--version', default='1.0',
                    help="String to store in the \"version\" field of the generated JSON file")
parser.add_argument('--license',
                    default="Creative Commons Attribution (CC-BY 4.0)",
                    help="String to store in the \"license\" field of the generated JSON file")
parser.add_argument('--date', default=dt.today().strftime("%m/%d/%Y"),
                    help="String to store in the \"date\" field of the generated JSON file; " +
                         "defaults to today's date")

# Rendering options
parser.add_argument('--use_gpu', default=0, type=int,
                    help="Setting --use_gpu 1 enables GPU-accelerated rendering using CUDA. " +
                         "You must have an NVIDIA GPU with the CUDA toolkit installed for " +
                         "to work.")
parser.add_argument('--width', default=512, type=int,
                    help="The width (in pixels) for the rendered images")
parser.add_argument('--height', default=512, type=int,
                    help="The height (in pixels) for the rendered images")
parser.add_argument('--key_light_jitter', default=1.0, type=float,
                    help="The magnitude of random jitter to add to the key light position.")
parser.add_argument('--fill_light_jitter', default=1.0, type=float,
                    help="The magnitude of random jitter to add to the fill light position.")
parser.add_argument('--back_light_jitter', default=1.0, type=float,
                    help="The magnitude of random jitter to add to the back light position.")
parser.add_argument('--camera_jitter', default=0.5, type=float,
                    help="The magnitude of random jitter to add to the camera position")
parser.add_argument('--render_num_samples', default=128, type=int,
                    help="The number of samples to use when rendering. Larger values will " +
                         "result in nicer images but will cause rendering to take longer.")
parser.add_argument('--render_min_bounces', default=8, type=int,
                    help="The minimum number of bounces to use for rendering.")
parser.add_argument('--render_max_bounces', default=8, type=int,
                    help="The maximum number of bounces to use for rendering.")
parser.add_argument('--render_tile_size', default=256, type=int,
                    help="The tile size to use for rendering. This should not affect the " +
                         "quality of the rendered image but may affect the speed; CPU-based " +
                         "rendering may achieve better performance using smaller tile sizes " +
                         "while larger tile sizes may be optimal for GPU-based rendering.")


def main(args):
    num_digits = 6
    prefix = '%s_%s_' % (args.filename_prefix, args.split)
    img_template = '%s%%0%dd.png' % (prefix, num_digits)
    scene_template = '%s%%0%dd.json' % (prefix, num_digits)
    blend_template = '%s%%0%dd.blend' % (prefix, num_digits)
    img_template = os.path.join(args.output_image_dir, img_template)
    scene_template = os.path.join(args.output_scene_dir, scene_template)
    blend_template = os.path.join(args.output_blend_dir, blend_template)

    if not os.path.isdir(args.output_image_dir):
        os.makedirs(args.output_image_dir)
    if not os.path.isdir(args.output_scene_dir):
        os.makedirs(args.output_scene_dir)
    if not os.path.isdir(args.output_cache_dir):
        os.makedirs(args.output_cache_dir)
    if args.save_blendfiles == 1 and not os.path.isdir(args.output_blend_dir):
        os.makedirs(args.output_blend_dir)

    all_scene_paths = []
    for i in range(args.num_images):
        img_path = img_template % (i + args.start_idx)
        scene_path = scene_template % (i + args.start_idx)
        all_scene_paths.append(scene_path)
        blend_path = None
        if args.save_blendfiles == 1:
            blend_path = blend_template % (i + args.start_idx)
        num_objects = random.randint(args.min_objects, args.max_objects)
        render_scene(args,
                     num_objects=num_objects,
                     output_index=(i + args.start_idx),
                     output_split=args.split,
                     output_image=img_path,
                     output_scene=scene_path,
                     output_blendfile=blend_path,
                     iter=i
                     )
    # After rendering all images, combine the JSON files for each scene into a
    # single JSON file.
    all_scenes = []
    for scene_path in all_scene_paths:
        with open(scene_path, 'r') as f:
            all_scenes.append(json.load(f))
    output = {
        'info': {
            'date': args.date,
            'version': args.version,
            'split': args.split,
            'license': args.license,
        },
        'scenes': all_scenes
    }
    with open(args.output_scene_file, 'w') as f:
        json.dump(output, f)


def render_scene(args,
                 num_objects=5,
                 output_index=0,
                 output_split='none',
                 output_image='render.png',
                 output_scene='render_json',
                 output_blendfile=None,
                 iter=0
                 ):
    # Load the main blendfile
    bpy.ops.wm.open_mainfile(filepath=args.base_scene_blendfile)

    # Load materials
    utils.load_materials(args.material_dir)

    # Set render arguments so we can get pixel coordinates later.
    # We use functionality specific to the CYCLES renderer so BLENDER_RENDER
    # cannot be used.
    render_args = bpy.context.scene.render
    render_args.engine = "CYCLES"
    render_args.filepath = output_image
    render_args.resolution_x = args.width
    render_args.resolution_y = args.height
    render_args.resolution_percentage = 100
    if blender_version >= (3, 0, 0) and blender_version < (4, 0, 0):
        bpy.context.scene.cycles.tile_size = args.render_tile_size
    else:
        render_args.tile_x = args.render_tile_size
        render_args.tile_y = args.render_tile_size
    if args.use_gpu == 1:
        # Blender changed the API for enabling CUDA at some point
        if bpy.app.version < (2, 78, 0):
            bpy.context.user_preferences.system.compute_device_type = 'CUDA'
            bpy.context.user_preferences.system.compute_device = 'CUDA_0'
        elif bpy.app.version < (3, 0, 0):
            cycles_prefs = bpy.context.user_preferences.addons['cycles'].preferences
            cycles_prefs.compute_device_type = 'CUDA'
    # Some CYCLES-specific stuff
    bpy.data.worlds['World'].cycles.sample_as_light = True
    bpy.context.scene.cycles.blur_glossy = 2.0
    bpy.context.scene.cycles.samples = args.render_num_samples
    bpy.context.scene.cycles.transparent_min_bounces = args.render_min_bounces
    bpy.context.scene.cycles.transparent_max_bounces = args.render_max_bounces
    bpy.context.scene.cycles.use_denoising = True
    bpy.context.scene.cycles.use_adaptive_sampling = True
    if args.use_gpu == 1:
        bpy.context.scene.cycles.device = 'GPU'

    # This will give ground-truth information about the scene and its objects
    scene_struct = {
        'split': output_split,
        'image_index': output_index,
        'image_filename': os.path.basename(output_image),
        'objects': [],
        'directions': {},
    }

    # Put a plane on the ground so we can compute cardinal directions
    bpy.ops.mesh.primitive_plane_add(size=5)
    plane = bpy.context.object

    def rand(L):
        return 2.0 * L * (random.random() - 0.5)

    # Add random jitter to camera position
    if args.camera_jitter > 0:
        for i in range(3):
            bpy.data.objects['Camera'].location[i] += rand(args.camera_jitter)

    # Figure out the left, up, and behind directions along the plane and record
    # them in the scene structure
    camera = bpy.data.objects['Camera']
    plane_normal = plane.data.vertices[0].normal
    cam_behind = camera.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    cam_left = camera.matrix_world.to_quaternion() @ Vector((-1, 0, 0))
    cam_up = camera.matrix_world.to_quaternion() @ Vector((0, 1, 0))
    plane_behind = (cam_behind - cam_behind.project(plane_normal)).normalized()
    plane_left = (cam_left - cam_left.project(plane_normal)).normalized()
    plane_up = cam_up.project(plane_normal).normalized()

    # Delete the plane; we only used it for normals anyway. The base scene file
    # contains the actual ground plane.
    utils.delete_object(plane)

    # Save all six axis-aligned directions in the scene struct
    scene_struct['directions']['behind'] = tuple(plane_behind)
    scene_struct['directions']['front'] = tuple(-plane_behind)
    scene_struct['directions']['left'] = tuple(plane_left)
    scene_struct['directions']['right'] = tuple(-plane_left)
    scene_struct['directions']['above'] = tuple(plane_up)
    scene_struct['directions']['below'] = tuple(-plane_up)

    # Add random jitter to lamp positions
    if args.key_light_jitter > 0:
        for i in range(3):
            bpy.data.objects['Lamp_Key'].location[i] += rand(args.key_light_jitter)
    if args.back_light_jitter > 0:
        for i in range(3):
            bpy.data.objects['Lamp_Back'].location[i] += rand(args.back_light_jitter)
    if args.fill_light_jitter > 0:
        for i in range(3):
            bpy.data.objects['Lamp_Fill'].location[i] += rand(args.fill_light_jitter)

    # Now make some random objects
    if args.liquid_simulation:  # liquid_setup 0=no fluid, 1=water, 2=viscous liquid
        liquid_setup = random.randint(0, 2)
    else:
        liquid_setup = 0
    objects, blender_objects = add_random_objects(scene_struct, num_objects, args, camera, liquid_setup)

    # Render the scene and dump the scene data structure
    scene_struct['objects'] = objects
    scene_struct['relationships'] = compute_all_relationships(scene_struct)

    # Create liquid domain
    if liquid_setup > 0:
        scene_struct['liquid_params'] = add_liquid_domain(args, iter, camera, liquid_setup)
        # bpy.ops.fluid.free_all()
        bpy.context.scene.frame_end = scene_struct['liquid_params']["sim_time"]
        result = bpy.ops.fluid.bake_all()
        assert 'FINISHED' in result
        bpy.ops.screen.frame_jump(end=True)
    while True:
        try:
            bpy.ops.render.render(write_still=True)
            break
        except Exception as e:
            print(e)
    # bpy.ops.fluid.free_all()
    # bpy.ops.fluid.free_data()
    with open(output_scene, 'w') as f:
        json.dump(scene_struct, f, indent=2)

    if output_blendfile is not None:
        bpy.ops.wm.save_as_mainfile(filepath=output_blendfile)


def add_liquid_domain(args, iteration, camera, liquid_setup):
    bpy.ops.mesh.primitive_cube_add(size=6,
                                    enter_editmode=False,
                                    align='WORLD',
                                    location=(0, 0, 3),
                                    scale=(1, 1, 1))
    bpy.context.object.name = "liquid_domain"
    bpy.ops.object.modifier_add(type='FLUID')
    bpy.context.object.modifiers["Fluid"].fluid_type = 'DOMAIN'
    # cache_dir = str(Path(args.output_cache_dir, "{:05d}".format(iteration)))
    cache_dir = str(Path(args.output_cache_dir))
    bpy.context.object.modifiers["Fluid"].domain_settings.cache_directory = cache_dir
    sim_time = 50
    vis = 0
    if liquid_setup == 2:
        vis = 0.05
        sim_time = 100
    bpy.context.object.modifiers["Fluid"].domain_settings.domain_type = 'LIQUID'  # GAS
    if vis > 0:
        bpy.context.object.modifiers["Fluid"].domain_settings.use_viscosity = True
        bpy.context.object.modifiers["Fluid"].domain_settings.viscosity_value = vis
    bpy.context.object.modifiers["Fluid"].domain_settings.use_mesh = True
    bpy.context.object.modifiers["Fluid"].domain_settings.cache_frame_end = sim_time
    bpy.context.object.modifiers["Fluid"].domain_settings.cache_type = 'ALL'
    bpy.context.object.modifiers["Fluid"].domain_settings.use_collision_border_right = False
    bpy.context.object.modifiers["Fluid"].domain_settings.use_collision_border_top = False
    bpy.context.object.modifiers["Fluid"].domain_settings.use_collision_border_back = False
    bpy.context.object.modifiers["Fluid"].domain_settings.use_collision_border_left = False
    bpy.context.object.modifiers["Fluid"].domain_settings.use_collision_border_front = False
    bpy.context.object.modifiers["Fluid"].domain_settings.use_collision_border_bottom = True
    with open(args.properties_json, 'r') as f:
        properties = json.load(f)
        material_mapping = [(v, k) for k, v in properties['liquid_materials'].items()]
        mat_name, mat_name_out = random.choice(material_mapping)
        mat_name_out = "Water"
        # rgb = [42, 75, 215]
        # rgba = [float(c) / 255.0 for c in rgb] + [1.0]
        utils.add_material(mat_name_out)
    return {"viscosity": vis,
            "sim_time": sim_time,
            "rgb": [0, 0, 0]}


def add_random_objects(scene_struct, num_objects, args, camera, liquid_setup):
    """
    Add random objects to the current blender scene
    """

    # Load the property file
    with open(args.properties_json, 'r') as f:
        properties = json.load(f)
        color_name_to_rgba = {}
        for name, rgb in properties['colors'].items():
            rgba = [float(c) / 255.0 for c in rgb] + [1.0]
            color_name_to_rgba[name] = rgba
        material_mapping = [(v, k) for k, v in properties['materials'].items()]
        object_mapping = [(v, k) for k, v in properties['shapes'].items()]
        size_mapping = list(properties['sizes'].items())

    shape_color_combos = None
    if args.shape_color_combos_json is not None:
        with open(args.shape_color_combos_json, 'r') as f:
            shape_color_combos = list(json.load(f).items())

    positions = []
    objects = []
    blender_objects = []
    rand_mat = random.randint(0, 1)
    for i in range(num_objects):
        # Choose a random size
        size_name, r = random.choice(size_mapping)

        # Try to place the object, ensuring that we don't intersect any existing
        # objects and that we are more than the desired margin away from all existing
        # objects along all cardinal directions.
        num_tries = 0
        while True:
            # If we try and fail to place an object too many times, then delete all
            # the objects in the scene and start over.
            num_tries += 1
            if num_tries > args.max_retries:
                for obj in blender_objects:
                    utils.delete_object(obj)
                return add_random_objects(scene_struct, num_objects, args, camera, liquid_setup)
            x = random.uniform(-3, 3)
            y = random.uniform(-3, 3)
            if i == 0:  # this object is always above the second one (as it is possibly a liquid source)
                z = random.uniform(1, 4)
            elif i == 1:
                z = 0  # this effector is on the ground
            else:
                raise NotImplementedError
            # Check to make sure the new object is further than min_dist from all
            # other objects, and further than margin along the four cardinal directions
            dists_good = True
            margins_good = True
            for (xx, yy, zz, rr) in positions:
                dx, dy, dz = x - xx, y - yy, z - zz
                dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                if dist - r - rr < args.min_dist:
                    dists_good = False
                    break
                for direction_name in ['left', 'right', 'front', 'behind']:
                    direction_vec = scene_struct['directions'][direction_name]
                    assert direction_vec[2] == 0
                    margin = dx * direction_vec[0] + dy * direction_vec[1]
                    if 0 < margin < args.margin:
                        print(margin, args.margin, direction_name)
                        print('BROKEN MARGIN!')
                        margins_good = False
                        break
                for direction_name in ['above', 'below']:
                    direction_vec = scene_struct['directions'][direction_name]
                    # assert direction_vec[2] == 0
                    margin = dz * direction_vec[2]
                    if 0 < margin < args.margin:
                        print(margin, args.margin, direction_name)
                        print('BROKEN MARGIN!')
                        margins_good = False
                        break
                if not margins_good:
                    break

            if dists_good and margins_good:
                break

        # Choose random color and shape
        if shape_color_combos is None:
            obj_name, obj_name_out = random.choice(object_mapping)
            color_name, rgba = random.choice(list(color_name_to_rgba.items()))
        else:
            obj_name_out, color_choices = random.choice(shape_color_combos)
            color_name = random.choice(color_choices)
            obj_name = [k for k, v in object_mapping if v == obj_name_out][0]
            rgba = color_name_to_rgba[color_name]

        # For cube, adjust the size a bit
        if obj_name == 'Cube':
            r /= math.sqrt(2)

        # Choose random orientation for the object.
        theta = 360.0 * random.random()

        # Actually add the object to the scene
        utils.add_object(args.shape_dir, obj_name, r, (x, y, z), theta=theta)
        obj = bpy.context.object
        blender_objects.append(obj)
        positions.append((x, y, z, r))

        # Attach a separate material per object
        if i == 0:
            mat_name, mat_name_out = material_mapping[rand_mat]
        elif i == 1:
            mat_name, mat_name_out = material_mapping[1 - rand_mat]
        else:
            raise NotImplementedError
        # mat_name, mat_name_out = random.choice(material_mapping)
        utils.add_material(mat_name, Color=rgba)
        liquid_src = False
        if liquid_setup > 0:
            # Make source if this is first objectS
            if i == 0:
                liquid_src = True
                bpy.ops.object.modifier_add(type='FLUID')
                bpy.context.object.modifiers["Fluid"].fluid_type = 'FLOW'
                bpy.context.object.modifiers["Fluid"].flow_settings.flow_type = 'LIQUID'
                bpy.context.object.modifiers["Fluid"].flow_settings.flow_behavior = 'INFLOW'
                bpy.context.object.modifiers["Fluid"].flow_settings.use_plane_init = True
                #bpy.context.object.hide_render = True
            else:
                bpy.ops.object.modifier_add(type='FLUID')
                bpy.context.object.modifiers["Fluid"].fluid_type = 'EFFECTOR'
                bpy.context.object.modifiers["Fluid"].effector_settings.effector_type = 'COLLISION'

        # Record data about the object in the scene data structure
        pixel_coords = utils.get_camera_coords(camera, obj.location)
        objects.append({
            'shape': obj_name_out,
            'size': size_name,
            'material': mat_name_out,
            '3d_coords': tuple(obj.location),
            'rotation': theta,
            'pixel_coords': pixel_coords,
            'color': color_name,
            'liquid_src': liquid_src
        })

    # Check that all objects are at least partially visible in the rendered image
    # all_visible = check_visibility(blender_objects, args.min_pixels_per_object)
    all_visible = True
    if not all_visible:
        # If any of the objects are fully occluded then start over; delete all
        # objects from the scene and place them all again.
        print('Some objects are occluded; replacing objects')
        for obj in blender_objects:
            utils.delete_object(obj)
        return add_random_objects(scene_struct, num_objects, args, camera, liquid_setup)

    return objects, blender_objects


def compute_all_relationships(scene_struct, eps=0.2):
    """
    Computes relationships between all pairs of objects in the scene.

    Returns a dictionary mapping string relationship names to lists of lists of
    integers, where output[rel][i] gives a list of object indices that have the
    relationship rel with object i. For example if j is in output['left'][i] then
    object j is left of object i.
    """
    all_relationships = {}
    for name, direction_vec in scene_struct['directions'].items():
        if name == 'above' or name == 'below': continue
        all_relationships[name] = []
        for i, obj1 in enumerate(scene_struct['objects']):
            coords1 = obj1['3d_coords']
            related = set()
            for j, obj2 in enumerate(scene_struct['objects']):
                if obj1 == obj2: continue
                coords2 = obj2['3d_coords']
                diff = [coords2[k] - coords1[k] for k in [0, 1, 2]]
                dot = sum(diff[k] * direction_vec[k] for k in [0, 1, 2])
                if dot > eps:
                    related.add(j)
            all_relationships[name].append(sorted(list(related)))
    return all_relationships


def check_visibility(blender_objects, min_pixels_per_object):
    """
    Check whether all objects in the scene have some minimum number of visible
    pixels; to accomplish this we assign random (but distinct) colors to all
    objects, and render using no lighting or shading or antialiasing; this
    ensures that each object is just a solid uniform color. We can then count
    the number of pixels of each color in the output image to check the visibility
    of each object.

    Returns True if all objects are visible and False otherwise.
    """
    from pathlib import Path
    path = str(Path("C:/src/clevr-dataset-gen/output/images/blah.png"))
    object_colors = render_shadeless(blender_objects, path=path)
    img = bpy.data.images.load(path)
    p = list(img.pixels)
    color_count = Counter((p[i], p[i + 1], p[i + 2], p[i + 3])
                          for i in range(0, len(p), 4))
    # os.remove(path)
    if len(color_count) != len(blender_objects) + 1:
        return False
    for _, count in color_count.most_common():
        if count < min_pixels_per_object:
            return False
    return True


def render_shadeless(blender_objects, path='flat.png'):
    """
    Render a version of the scene with shading disabled and unique materials
    assigned to all objects, and return a set of all colors that should be in the
    rendered image. The image itself is written to path. This is used to ensure
    that all objects will be visible in the final rendered scene.
    """
    render_args = bpy.context.scene.render

    # Cache the render args we are about to clobber
    old_filepath = render_args.filepath
    old_engine = render_args.engine
    old_use_antialiasing = bpy.context.scene.cycles.pixel_filter_type

    # Override some render settings to have flat shading
    render_args.filepath = path
    render_args.engine = 'CYCLES'
    bpy.context.scene.cycles.pixel_filter_type = 'BOX'

    # Move the lights and ground to layer 2 so they don't render
    bpy.data.objects['Lamp_Key'].hide_render = True
    bpy.data.objects['Lamp_Fill'].hide_render = True
    bpy.data.objects['Lamp_Back'].hide_render = True
    bpy.data.objects['Ground'].hide_render = True
    # utils.set_layer(bpy.data.objects['Lamp_Key'], 2)
    # utils.set_layer(bpy.data.objects['Lamp_Fill'], 2)
    # utils.set_layer(bpy.data.objects['Lamp_Back'], 2)
    # utils.set_layer(bpy.data.objects['Ground'], 2)

    # Add random shadeless materials to all objects
    object_colors = set()
    old_materials = []
    for i, obj in enumerate(blender_objects):
        old_materials.append(obj.data.materials[0])
        bpy.ops.material.new()
        mat = bpy.data.materials['Material']
        mat.name = 'Material_%d' % i
        while True:
            r, g, b = [random.random() for _ in range(3)]
            if (r, g, b) not in object_colors: break
        object_colors.add((r, g, b))
        mat.diffuse_color = [r, g, b, 1]
        # mat.use_shadeless = True
        obj.data.materials[0] = mat

    # Render the scene
    bpy.ops.render.render(write_still=True)

    # Undo the above; first restore the materials to objects
    for mat, obj in zip(old_materials, blender_objects):
        obj.data.materials[0] = mat

    # Move the lights and ground back to layer 0
    bpy.data.objects['Lamp_Key'].hide_render = False
    bpy.data.objects['Lamp_Fill'].hide_render = False
    bpy.data.objects['Lamp_Back'].hide_render = False
    bpy.data.objects['Ground'].hide_render = False
    # utils.set_layer(bpy.data.objects['Lamp_Key'], 0)
    # utils.set_layer(bpy.data.objects['Lamp_Fill'], 0)
    # utils.set_layer(bpy.data.objects['Lamp_Back'], 0)
    # utils.set_layer(bpy.data.objects['Ground'], 0)

    # Set the render settings back to what they were
    render_args.filepath = old_filepath
    render_args.engine = old_engine
    bpy.context.scene.cycles.pixel_filter_type = old_use_antialiasing

    return object_colors


if __name__ == '__main__':
    if INSIDE_BLENDER:
        # Run normally
        argv = utils.extract_args()
        args = parser.parse_args(argv)
        main(args)
    elif '--help' in sys.argv or '-h' in sys.argv:
        parser.print_help()
    else:
        print('This script is intended to be called from blender like this:')
        print()
        print('blender --background --python render_images.py -- [args]')
        print()
        print('You can also run as a standalone python script to view all')
        print('arguments like this:')
        print()
        print('python render_images.py --help')
