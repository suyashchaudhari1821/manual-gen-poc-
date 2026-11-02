"""
CAD/STEP File Parser - Fixed for pythonocc-core compatibility
Supports pythonocc-core 7.4.x, 7.5.x, 7.6.x, 7.7.x, and 7.8.x

Fix for error:
  Tessellation failed: Wrong number or type of arguments for overloaded function
  'new_BRepMesh_IncrementalMesh'
"""
import logging
logger = logging.getLogger(__name__)
from cad_models import CADAssembly
import time
import os
import sys
import math
import struct
import re
try:
    from cad_tracing import traceable
except Exception:
    def traceable(*args, **kwargs):
        def wrapper(fn):
            return fn
        return wrapper

# Try to detect if OCC is available
try:
    from OCP.TopoDS import TopoDS
    from OCP.STEPControl import STEPControl_Reader
    OCC_AVAILABLE = True
except ImportError:
    TopoDS = None
    OCC_AVAILABLE = False

def _parse_binary_stl(filepath, num_facets):
    vertices = []
    triangles = []
    vertex_map = {}
    
    total_surface_area = 0.0
    total_volume = 0.0
    cx, cy, cz = 0.0, 0.0, 0.0
    
    xmin, xmax = float('inf'), float('-inf')
    ymin, ymax = float('inf'), float('-inf')
    zmin, zmax = float('inf'), float('-inf')
    
    with open(filepath, 'rb') as f:
        f.seek(84) # Skip header (80 bytes) and count (4 bytes)
        
        for _ in range(num_facets):
            data = f.read(50)
            if len(data) < 50:
                break
                
            # Unpack 12 floats (normal + 3 vertices)
            floats = struct.unpack('<12f', data[:48])
            v1 = floats[3:6]
            v2 = floats[6:9]
            v3 = floats[9:12]
            
            # Bounding box updates
            for v in (v1, v2, v3):
                if v[0] < xmin: xmin = v[0]
                if v[0] > xmax: xmax = v[0]
                if v[1] < ymin: ymin = v[1]
                if v[1] > ymax: ymax = v[1]
                if v[2] < zmin: zmin = v[2]
                if v[2] > zmax: zmax = v[2]
                
            # Add to vertices list with deduplication
            t_idx = []
            for v in (v1, v2, v3):
                v_key = (round(v[0], 5), round(v[1], 5), round(v[2], 5))
                if v_key not in vertex_map:
                    vertex_map[v_key] = len(vertices)
                    vertices.append(v)
                t_idx.append(vertex_map[v_key])
            triangles.append(tuple(t_idx))
            
            # Area calculation
            ab = (v2[0]-v1[0], v2[1]-v1[1], v2[2]-v1[2])
            ac = (v3[0]-v1[0], v3[1]-v1[1], v3[2]-v1[2])
            cp = (
                ab[1]*ac[2] - ab[2]*ac[1],
                ab[2]*ac[0] - ab[0]*ac[2],
                ab[0]*ac[1] - ab[1]*ac[0]
            )
            area = 0.5 * math.sqrt(cp[0]**2 + cp[1]**2 + cp[2]**2)
            total_surface_area += area
            
            # Volume calculation (signed volume of tetrahedron)
            v_tet = (1.0 / 6.0) * (
                -v3[2]*v2[1]*v1[0] + v2[2]*v3[1]*v1[0] +
                v3[2]*v1[1]*v2[0] - v1[2]*v3[1]*v2[0] -
                v2[2]*v1[1]*v3[0] + v1[2]*v2[1]*v3[0]
            )
            total_volume += v_tet
            
            cx += ((v1[0] + v2[0] + v3[0]) / 4.0) * v_tet
            cy += ((v1[1] + v2[1] + v3[1]) / 4.0) * v_tet
            cz += ((v1[2] + v2[2] + v3[2]) / 4.0) * v_tet
            
    if abs(total_volume) > 1e-9:
        cx /= total_volume
        cy /= total_volume
        cz /= total_volume
    else:
        cx, cy, cz = 0.0, 0.0, 0.0
        
    total_volume = abs(total_volume)
    
    if xmin == float('inf'):
        xmin, xmax, ymin, ymax, zmin, zmax = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        
    filename = os.path.basename(filepath)
    part_name = os.path.splitext(filename)[0]
    
    part_data = {
        "part_id": "P1",
        "name": part_name,
        "description": "STL mesh part",
        "face_count": len(triangles),
        "edge_count": len(triangles) * 3 // 2,
        "vertex_count": len(vertices),
        "bounding_box": {
            "width": round(xmax - xmin, 4),
            "height": round(ymax - ymin, 4),
            "depth": round(zmax - zmin, 4)
        },
        "volume": round(total_volume, 4),
        "surface_area": round(total_surface_area, 4),
        "face_types": {"Triangle": len(triangles)},
        "faces": [{"surface_type": "Triangle"} for _ in range(min(len(triangles), 100))],
        "center_of_mass": {"x": round(cx, 4), "y": round(cy, 4), "z": round(cz, 4)},
        "mesh": {
            "vertices": vertices,
            "triangles": triangles,
            "face_count": len(triangles),
            "vertex_count": len(vertices),
            "triangle_count": len(triangles),
        },
    }
    
    return {
        "file": filename,
        "pythonocc_version": "Unavailable (STL Parser)",
        "parts": [part_data],
        "bounding_box": {
            "xmin": round(xmin, 4), "xmax": round(xmax, 4),
            "ymin": round(ymin, 4), "ymax": round(ymax, 4),
            "zmin": round(zmin, 4), "zmax": round(zmax, 4)
        },
        "face_type_summary": {"Triangle": len(triangles)},
        "total_parts": 1,
        "total_faces": len(triangles),
        "total_edges": len(triangles) * 3 // 2,
        "total_surface_area": round(total_surface_area, 4),
        "total_volume": round(total_volume, 4)
    }

def _parse_ascii_stl(filepath):
    vertices = []
    triangles = []
    vertex_map = {}
    
    total_surface_area = 0.0
    total_volume = 0.0
    cx, cy, cz = 0.0, 0.0, 0.0
    
    xmin, xmax = float('inf'), float('-inf')
    ymin, ymax = float('inf'), float('-inf')
    zmin, zmax = float('inf'), float('-inf')
    
    current_facet = []
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip().lower()
            if line.startswith('vertex'):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        v = (float(parts[1]), float(parts[2]), float(parts[3]))
                        current_facet.append(v)
                    except ValueError:
                        pass
            elif line.startswith('endloop'):
                if len(current_facet) == 3:
                    v1, v2, v3 = current_facet
                    
                    for v in (v1, v2, v3):
                        if v[0] < xmin: xmin = v[0]
                        if v[0] > xmax: xmax = v[0]
                        if v[1] < ymin: ymin = v[1]
                        if v[1] > ymax: ymax = v[1]
                        if v[2] < zmin: zmin = v[2]
                        if v[2] > zmax: zmax = v[2]
                        
                    t_idx = []
                    for v in (v1, v2, v3):
                        v_key = (round(v[0], 5), round(v[1], 5), round(v[2], 5))
                        if v_key not in vertex_map:
                            vertex_map[v_key] = len(vertices)
                            vertices.append(v)
                        t_idx.append(vertex_map[v_key])
                    triangles.append(tuple(t_idx))
                    
                    ab = (v2[0]-v1[0], v2[1]-v1[1], v2[2]-v1[2])
                    ac = (v3[0]-v1[0], v3[1]-v1[1], v3[2]-v1[2])
                    cp = (
                        ab[1]*ac[2] - ab[2]*ac[1],
                        ab[2]*ac[0] - ab[0]*ac[2],
                        ab[0]*ac[1] - ab[1]*ac[0]
                    )
                    area = 0.5 * math.sqrt(cp[0]**2 + cp[1]**2 + cp[2]**2)
                    total_surface_area += area
                    
                    v_tet = (1.0 / 6.0) * (
                        -v3[2]*v2[1]*v1[0] + v2[2]*v3[1]*v1[0] +
                        v3[2]*v1[1]*v2[0] - v1[2]*v3[1]*v2[0] -
                        v2[2]*v1[1]*v3[0] + v1[2]*v2[1]*v3[0]
                    )
                    total_volume += v_tet
                    
                    cx += ((v1[0] + v2[0] + v3[0]) / 4.0) * v_tet
                    cy += ((v1[1] + v2[1] + v3[1]) / 4.0) * v_tet
                    cz += ((v1[2] + v2[2] + v3[2]) / 4.0) * v_tet
                    
                current_facet = []
                
    if abs(total_volume) > 1e-9:
        cx /= total_volume
        cy /= total_volume
        cz /= total_volume
    else:
        cx, cy, cz = 0.0, 0.0, 0.0
        
    total_volume = abs(total_volume)
    
    if xmin == float('inf'):
        xmin, xmax, ymin, ymax, zmin, zmax = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        
    filename = os.path.basename(filepath)
    part_name = os.path.splitext(filename)[0]
    
    part_data = {
        "part_id": "P1",
        "name": part_name,
        "description": "STL mesh part (ASCII)",
        "face_count": len(triangles),
        "edge_count": len(triangles) * 3 // 2,
        "vertex_count": len(vertices),
        "bounding_box": {
            "width": round(xmax - xmin, 4),
            "height": round(ymax - ymin, 4),
            "depth": round(zmax - zmin, 4)
        },
        "volume": round(total_volume, 4),
        "surface_area": round(total_surface_area, 4),
        "face_types": {"Triangle": len(triangles)},
        "faces": [{"surface_type": "Triangle"} for _ in range(min(len(triangles), 100))],
        "center_of_mass": {"x": round(cx, 4), "y": round(cy, 4), "z": round(cz, 4)},
        "mesh": {
            "vertices": vertices,
            "triangles": triangles,
            "face_count": len(triangles),
            "vertex_count": len(vertices),
            "triangle_count": len(triangles),
        },
    }
    
    return {
        "file": filename,
        "pythonocc_version": "Unavailable (STL Parser)",
        "parts": [part_data],
        "bounding_box": {
            "xmin": round(xmin, 4), "xmax": round(xmax, 4),
            "ymin": round(ymin, 4), "ymax": round(ymax, 4),
            "zmin": round(zmin, 4), "zmax": round(zmax, 4)
        },
        "face_type_summary": {"Triangle": len(triangles)},
        "total_parts": 1,
        "total_faces": len(triangles),
        "total_edges": len(triangles) * 3 // 2,
        "total_surface_area": round(total_surface_area, 4),
        "total_volume": round(total_volume, 4)
    }
def parse_stl_file(filepath):
    """
    Parse an STL file (.stl) and return a cad-style dictionary.
    Supports both ASCII and Binary STL formats.
    """

    start_time = time.perf_counter()

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"STL file not found: {filepath}")

    with open(filepath, "rb") as f:

        header = f.read(80)

        if len(header) < 80:

            result = _parse_ascii_stl(filepath)

        else:

            num_facets_bytes = f.read(4)

            if len(num_facets_bytes) < 4:

                result = _parse_ascii_stl(filepath)

            else:

                num_facets = struct.unpack(
                    "<I",
                    num_facets_bytes
                )[0]

                file_size = os.path.getsize(filepath)

                expected_size = (
                    80 + 4 + num_facets * 50
                )

                is_binary = True

                if (
                    header.startswith(b"solid")
                    and not (
                        expected_size - 100
                        <= file_size
                        <= expected_size + 100
                    )
                ):
                    is_binary = False

                if is_binary:
                    try:
                        result = _parse_binary_stl(
                            filepath,
                            num_facets
                        )
                    except Exception:
                        logger.exception(
                            "Binary STL parse failed. Falling back to ASCII parser."
                        )
                        result = _parse_ascii_stl(filepath)
                else:
                    result = _parse_ascii_stl(filepath)

    duration = time.perf_counter() - start_time

    result["parsing_mode"] = "stl"
    result["parsing_confidence"] = 1.0
    result["parse_duration"] = round(duration, 3)

    return result

def parse_step_file_fallback(filepath):
    """
    Fallback STEP file parser when pythonocc-core (OCC) is not available.
    Uses regex to extract assembly parts and names.

    Bug-fix note
    ------------
    This used to hand-roll its own PRODUCT() regex with two bugs:
      1. Field-mapping was backwards. A STEP entity like
             #57=PRODUCT('NAS577B6A','STD','',(#2))
         has (identifier, category, description) in that order. The old
         code used the identifier ('NAS577B6A' — the value that actually
         matches BOM part numbers) as `part_id`, and the CATEGORY string
         ('STD', 'ADAP-ASSY', 'CADNODE'...) as the part's display `name` —
         so every part showed up named "ADAP-ASSY" / "CADNODE" instead of
         its real identifier.
      2. It never filtered out assembly/reference nodes (ADAP-ASSY,
         CADNODE, etc.), so non-physical wrapper entries were listed
         alongside real leaf parts.
    _extract_step_leaf_product_names() already gets both of these right
    (it's what the real OCC path uses to recover BOM-matching part names),
    so this now delegates to it instead of duplicating the same regex with
    different bugs.
    """
    start_time = time.perf_counter()
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"STEP file not found: {filepath}")

    leaf_products = _extract_step_leaf_product_names(filepath)

    parts_list = []
    for i, prod in enumerate(leaf_products):
        parts_list.append({
            "part_id": f"P{i+1}",
            "name": prod["name"],
            "description": prod.get("description", ""),
            "face_count": 0,
            "edge_count": 0,
            "vertex_count": 0,
            "bounding_box": {"width": 0.0, "height": 0.0, "depth": 0.0},
            "volume": 0.0,
            "surface_area": 0.0,
            "face_types": {},
            "faces": [],
            "center_of_mass": {"x": 0.0, "y": 0.0, "z": 0.0}
        })

    filename = os.path.basename(filepath)

    duration = time.perf_counter() - start_time

    summary = {
    "total_parts": len(parts_list),
    "total_faces": 0,
    "total_edges": 0,
    "total_surface_area": 0.0,
    "total_volume": 0.0,
    "bounding_box": {
        "width": 0.0,
        "height": 0.0,
        "depth": 0.0,
    },
    "face_type_summary": {},
}
    return CADAssembly(
    filename=filename,
    parts=parts_list,
    parsing_mode="fallback",
    parsing_confidence=0.4,
    parse_duration=round(duration, 3),

    total_parts=summary["total_parts"],
    total_faces=summary["total_faces"],
    total_edges=summary["total_edges"],
    total_surface_area=summary["total_surface_area"],
    total_volume=summary["total_volume"],

    bounding_box=summary["bounding_box"],
    face_type_summary=summary["face_type_summary"],
)

def get_pythonocc_version():
    """Get the installed pythonocc-core version."""
    try:
        import importlib.metadata
        return importlib.metadata.version("pythonocc-core")
    except Exception:
        return None


def tessellate_shape(shape, linear_deflection=0.1, angular_deflection=0.5, relative=False, parallel=True):
    """
    Tessellate a TopoDS_Shape with compatibility across all pythonocc-core versions.

    Args:
        shape: TopoDS_Shape to tessellate
        linear_deflection (float): Linear deflection for tessellation quality (smaller = finer mesh)
        angular_deflection (float): Angular deflection in radians
        relative (bool): If True, deflection is relative to shape size
        parallel (bool): Enable parallel computation (ignored on older versions)

    Returns:
        BRepMesh_IncrementalMesh instance (already performed)
    """
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    mesh = None

    # Strategy 1: Try modern API with keyword arguments (pythonocc-core >= 7.5)
    # Signature: BRepMesh_IncrementalMesh(theShape, theLinDeflection, isRelative, theAngDeflection, isInParallel)
    try:
        mesh = BRepMesh_IncrementalMesh(
            shape,
            linear_deflection,
            relative,
            angular_deflection,
            parallel
        )
        if mesh.IsDone():
            return mesh
    except TypeError:
        pass

    # Strategy 2: Try with IMeshTools_Parameters (pythonocc-core >= 7.6 alternative)
    try:
        from OCP.IMeshTools import IMeshTools_Parameters
        params = IMeshTools_Parameters()
        params.Deflection = linear_deflection
        params.Angle = angular_deflection
        params.Relative = relative
        params.InParallel = parallel

        from OCP.Message import Message_ProgressRange
        mesh = BRepMesh_IncrementalMesh(shape, params, Message_ProgressRange())
        if mesh.IsDone():
            return mesh
    except (ImportError, TypeError, AttributeError):
        pass

    # Strategy 3: Try IMeshTools_Parameters without ProgressRange
    try:
        from OCP.IMeshTools import IMeshTools_Parameters
        params = IMeshTools_Parameters()
        params.Deflection = linear_deflection
        params.Angle = angular_deflection
        params.Relative = relative

        mesh = BRepMesh_IncrementalMesh(shape, params)
        if mesh.IsDone():
            return mesh
    except (ImportError, TypeError, AttributeError):
        pass

    # Strategy 4: Minimal 2-arg call (very old pythonocc-core < 7.4)
    try:
        mesh = BRepMesh_IncrementalMesh(shape, linear_deflection)
        if mesh.IsDone():
            return mesh
    except TypeError:
        pass

    # Strategy 5: Default constructor then Perform (some versions)
    try:
        mesh = BRepMesh_IncrementalMesh()
        mesh.SetShape(shape)
        mesh.SetDeflection(linear_deflection)
        mesh.Perform()
        if mesh.IsDone():
            return mesh
    except (TypeError, AttributeError):
        pass

    raise RuntimeError(
        f"Tessellation failed: Could not find a compatible BRepMesh_IncrementalMesh "
        f"constructor. Your pythonocc-core version: {get_pythonocc_version()}. "
        f"Please upgrade: pip install pythonocc-core --upgrade"
    )


def load_step_file(filepath):
    """
    Load a STEP (.stp / .step) file and return the shape.
    Handles converted STEP files, multi-root assemblies, and tolerant status returns.

    Args:
        filepath (str): Path to the STEP file

    Returns:
        TopoDS_Shape
    """
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_COMPOUND, TopAbs_SHELL, TopAbs_COMPSOLID, TopAbs_FACE

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"STEP file not found: {filepath}")

    Interface_Static.SetIVal_s('read.step.shape.repr', 1)
    Interface_Static.SetIVal_s('read.step.assembly.level', 1)
    Interface_Static.SetIVal_s('read.step.shape.aspect', 1)

    reader = STEPControl_Reader()
    status = reader.ReadFile(str(filepath))

    num_roots = 0
    try:
        num_roots = reader.NbRootsForTransfer()
    except Exception:
        pass

    if status != IFSelect_RetDone and num_roots == 0:
        logger.warning(f"STEP reader status {status} and 0 roots for {filepath}")

    try:
        reader.TransferRoots()
    except Exception as e:
        logger.warning(f"STEP TransferRoots notice: {e}")

    shape = reader.OneShape()

    if shape.IsNull() or shape.ShapeType() not in (TopAbs_SOLID, TopAbs_COMPOUND, TopAbs_SHELL, TopAbs_COMPSOLID, TopAbs_FACE):
        nb_s = reader.NbShapes()
        if nb_s > 0:
            from OCP.BRep import BRep_Builder
            from OCP.TopoDS import TopoDS_Compound
            builder = BRep_Builder()
            compound = TopoDS_Compound()
            builder.MakeCompound(compound)
            added = 0
            for i in range(1, nb_s + 1):
                s = reader.Shape(i)
                if not s.IsNull():
                    builder.Add(compound, s)
                    added += 1
            if added > 0:
                shape = compound

    if shape.IsNull():
        raise ValueError(f"STEP file loaded but shape is null: {filepath}")

    return shape

@traceable(name="extract_mesh_data")
def extract_mesh_data(shape, linear_deflection=0.1, angular_deflection=0.5):
    """
    Extract triangulated mesh data from a STEP shape.

    Args:
        shape: TopoDS_Shape
        linear_deflection (float): Mesh quality (smaller = finer)
        angular_deflection (float): Angular tolerance in radians

    Returns:
        dict with keys:
            - 'vertices': list of (x, y, z) tuples
            - 'triangles': list of (i1, i2, i3) index tuples
            - 'face_count': number of faces
    """
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    # Tessellate
    tessellate_shape(shape, linear_deflection, angular_deflection)

    vertices = []
    triangles = []
    vertex_offset = 0
    face_count = 0

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        current = explorer.Current()
        print(type(current))
        face = TopoDS.Face(current)
        face = TopoDS.Face(current)
        location = face.Location()

        # Get triangulation from BRep_Tool
        triangulation = BRep_Tool.Triangulation_s(face, location)

        if triangulation is not None:
            face_count += 1
            nb_nodes = triangulation.NbNodes()
            nb_triangles = triangulation.NbTriangles()

            # Extract vertices
            for i in range(1, nb_nodes + 1):
                node = triangulation.Node(i)
                vertices.append((node.X(), node.Y(), node.Z()))

            # Extract triangles (1-indexed in OCC)
            for i in range(1, nb_triangles + 1):
                tri = triangulation.Triangle(i)
                n1, n2, n3 = tri.Get()
                triangles.append((
                    n1 - 1 + vertex_offset,
                    n2 - 1 + vertex_offset,
                    n3 - 1 + vertex_offset
                ))

            vertex_offset += nb_nodes

        explorer.Next()

    return {
        "vertices": vertices,
        "triangles": triangles,
        "face_count": face_count,
        "vertex_count": len(vertices),
        "triangle_count": len(triangles),
    }


def get_shape_properties(shape):
    """
    Extract basic geometric properties from a shape.

    Args:
        shape: TopoDS_Shape

    Returns:
        dict with bounding box and other properties
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    bbox = Bnd_Box()
    try:
        BRepBndLib.Add_s(shape, bbox)
        print("Shape Null:", shape.IsNull())
        print("BBox Void :", bbox.IsVoid())
    except AttributeError:
        BRepBndLib.Add(shape, bbox)
    xmin = bbox.CornerMin().X()
    ymin = bbox.CornerMin().Y()
    zmin = bbox.CornerMin().Z()
    xmax = bbox.CornerMax().X()
    ymax = bbox.CornerMax().Y()
    zmax = bbox.CornerMax().Z()

    return {
        "bounding_box": {
            "xmin": xmin, "xmax": xmax,
            "ymin": ymin, "ymax": ymax,
            "zmin": zmin, "zmax": zmax,
        },
        "dimensions": {
            "length_x": round(xmax - xmin, 4),
            "length_y": round(ymax - ymin, 4),
            "length_z": round(zmax - zmin, 4),
        }
    }


@traceable(name="parse_cad_file")
def parse_cad_file(
    filepath,
    linear_deflection=0.1,
    angular_deflection=0.5,
):
    """
    Main entry point: parse a STEP/STP or STL file and return all useful data.

    Args:
        filepath (str): Path to file
        linear_deflection (float): Mesh quality (0.01=fine, 0.1=normal, 1.0=coarse)
        angular_deflection (float): Angular tolerance in radians (0.5 is typical)

    Returns:
        dict with shape properties, mesh data, and metadata
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".stl":
        res = parse_stl_file(filepath)
        part = res["parts"][0]
        return {
            "file": res["file"],
            "pythonocc_version": res["pythonocc_version"],
            "properties": {
                "bounding_box": {
                    "xmin": res["bounding_box"]["xmin"], "xmax": res["bounding_box"]["xmax"],
                    "ymin": res["bounding_box"]["ymin"], "ymax": res["bounding_box"]["ymax"],
                    "zmin": res["bounding_box"]["zmin"], "zmax": res["bounding_box"]["zmax"],
                },
                "dimensions": {
                    "length_x": part["bounding_box"]["width"],
                    "length_y": part["bounding_box"]["height"],
                    "length_z": part["bounding_box"]["depth"],
                }
            },
            "mesh": {
                "vertices": [],
                "triangles": [],
                "face_count": part["face_count"],
                "vertex_count": part["vertex_count"],
                "triangle_count": part["face_count"],
            }
        }
        
    if not OCC_AVAILABLE:
        res = parse_step_file_fallback(filepath)
        print(type(res))
        print(res)
        return {
            "file":res.filename,
            "pythonocc_version": "unavailable",
            "properties": {
                "bounding_box": {
                    "xmin": 0.0, "xmax": 0.0, "ymin": 0.0, "ymax": 0.0, "zmin": 0.0, "zmax": 0.0
                },
                "dimensions": {
                    "length_x": 0.0, "length_y": 0.0, "length_z": 0.0
                }
            },
            "mesh": {
                "vertices": [],
                "triangles": [],
                "face_count": 0,
                "vertex_count": 0,
                "triangle_count": 0,
            }
        }

    logger.info("Loading CAD file: %s", filepath)
    shape = load_step_file(filepath)
    logger.info("Shape loaded. Extracting properties.")

    props = get_shape_properties(shape)
    logger.info(
    "Tessellating mesh. deflection=%s",
    linear_deflection
)
    mesh = extract_mesh_data(shape, linear_deflection, angular_deflection)
    logger.info(
    "Mesh extraction complete. faces=%s vertices=%s triangles=%s",
    mesh["face_count"],
    mesh["vertex_count"],
    mesh["triangle_count"],
)

    return {
        "file": os.path.basename(filepath),
        "pythonocc_version": get_pythonocc_version(),
        "properties": props,
        "mesh": mesh,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Per-part decomposition — used by spec_resolver.build_spec_card() / app.py
# ──────────────────────────────────────────────────────────────────────────────
# parse_cad_file() above returns whole-shape mesh + bounding box only. The
# rest of the pipeline (spec_resolver.py, the CAD sidebar handler in app.py)
# needs a *per-part* breakdown — one entry per solid, each with its own
# bounding box, volume, surface area, and face-type histogram (Cylinder vs.
# Plane counts drive the fastener/bracket inference in spec_resolver). That
# function didn't exist under any name, which is why `from cad_parser import
# parse_step_file` failed. parse_step_file() below is that entry point.

def _classify_face(face):
    """Return (surface_type_name, radius_or_None) for a single TopoDS_Face."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
                                   GeomAbs_Sphere, GeomAbs_Torus)
    surf = BRepAdaptor_Surface(face, True)
    kind_map = {
        GeomAbs_Plane:    "Plane",
        GeomAbs_Cylinder: "Cylinder",
        GeomAbs_Cone:     "Cone",
        GeomAbs_Sphere:   "Sphere",
        GeomAbs_Torus:    "Torus",
    }
    kind = kind_map.get(surf.GetType(), "Other")
    radius = None
    if kind == "Cylinder":
        try:
            radius = surf.Cylinder().Radius()
        except Exception:
            radius = None
    return kind, radius


def _volume_and_surface_area(shape):
    """Compute (volume, surface_area) for a shape, tolerant of pythonocc
    binding differences across 7.4–7.8 (static `_s` methods vs. module-level
    functions)."""
    from OCP.GProp import GProp_GProps
    try:
        from OCP.BRepGProp import brepgprop
        vol_props, surf_props = GProp_GProps(), GProp_GProps()
        brepgprop.VolumeProperties_s(shape, vol_props)
        brepgprop.SurfaceProperties_s(shape, surf_props)
        return vol_props.Mass(), surf_props.Mass()
    except (ImportError, AttributeError):
        from OCP.BRepGProp import brepgprop_VolumeProperties, brepgprop_SurfaceProperties
        vol_props, surf_props = GProp_GProps(), GProp_GProps()
        brepgprop_VolumeProperties(shape, vol_props)
        brepgprop_SurfaceProperties(shape, surf_props)
        return vol_props.Mass(), surf_props.Mass()


def _analyze_part(shape, name, linear_deflection=0.3, angular_deflection=0.5,
                   include_mesh=True, part_id="P1"):
    """Build the per-part dict expected by spec_resolver.build_spec_card()
    AND ai_assistant.py's _build_system_prompt() — the latter accesses
    p['part_id'], p['face_count'], p['edge_count'], p['vertex_count'], and
    p['center_of_mass'] directly (no .get()), so all five MUST be present
    or query_cad_assistant() raises a KeyError on every real STEP part.

    include_mesh: when True (default) also tessellates this individual solid
    and attaches its real vertices/triangles under "mesh", so a real 3D
    rendering (see cad_renderer.py) can be produced for THIS part rather than
    the whole assembly. Deflection defaults are coarser than the whole-shape
    export in extract_mesh_data() since per-part renders don't need CAD-grade
    precision — just an accurate silhouette.
    """
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX

    dims = get_shape_properties(shape)["dimensions"]

    try:
        volume, surface_area = _volume_and_surface_area(shape)
    except Exception as e:
        logger.exception(
        "Volume/surface-area calculation failed for part '%s'",
        name,
        )
        volume, surface_area = 0.0, 0.0
    try:
     center_of_mass = _center_of_mass(shape)
    except Exception:
     logger.exception(
        "Center-of-mass calculation failed for '%s'",
        name,
       )

     center_of_mass = {
          "x": 0.0,
          "y": 0.0,
          "z": 0.0,
    }
    face_types, faces = {}, []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        kind, radius = _classify_face(explorer.Current())
        face_types[kind] = face_types.get(kind, 0) + 1
        entry = {"surface_type": kind}
        if radius is not None:
            entry["radius"] = radius
        faces.append(entry)
        explorer.Next()

    def _count(topabs_type):
        n = 0
        exp = TopExp_Explorer(shape, topabs_type)
        while exp.More():
            n += 1
            exp.Next()
        return n

    try:
        edge_count = _count(TopAbs_EDGE)
        vertex_count = _count(TopAbs_VERTEX)
    except Exception :
       logger.exception(
        "Edge/vertex count calculation failed for '%s'",
        name,
       )
       edge_count, vertex_count = 0, 0
        

    part = {
        "name": name,
        "part_id": part_id,
        "face_count": len(faces),
        "edge_count": edge_count,
        "vertex_count": vertex_count,
        "center_of_mass": center_of_mass,
        "bounding_box": {
            "width":  dims["length_x"],
            "height": dims["length_y"],
            "depth":  dims["length_z"],
        },
        "volume": volume,
        "surface_area": surface_area,
        "face_types": face_types,
        "faces": faces,
    }

    if include_mesh:
        try:
            part["mesh"] = extract_mesh_data(shape, linear_deflection, angular_deflection)
        except Exception as e:
            logger.exception(
    "Mesh export failed for part '%s'",
    name,
)
            part["mesh"] = {"vertices": [], "triangles": [], "face_count": 0,
                             "vertex_count": 0, "triangle_count": 0}

    return part


def _center_of_mass(shape) -> dict:
    """Compute the center of mass of a shape as {'x':.., 'y':.., 'z':..},
    tolerant of the same pythonocc binding differences handled in
    _volume_and_surface_area (static `_s` methods vs. module-level functions)."""
    from OCP.GProp import GProp_GProps
    try:
        from OCP.BRepGProp import brepgprop
        props = GProp_GProps()
        brepgprop.VolumeProperties_s(shape, props)
    except (ImportError, AttributeError):
        from OCP.BRepGProp import brepgprop_VolumeProperties
        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)
    com = props.CentreOfMass()
    return {"x": round(com.X(), 4), "y": round(com.Y(), 4), "z": round(com.Z(), 4)}


def _extract_step_leaf_product_names(filepath: str) -> list[dict]:
    """
    Regex-extract PRODUCT() entities directly from the raw STEP text, in
    file-declaration order, and return only the LEAF (physical, buildable)
    parts — filtering out assembly/reference nodes.

    Why this matters: STEP PRODUCT identifiers are very often the exact
    same string as the part number in the BOM (e.g. this parser was
    verified against a real Airbus rail-assembly STEP file where the
    PRODUCT ids 'NAS577B6A', 'NAS578-6A', 'D53111416200' are EXACTLY the
    BOM's PART NUMBER column values). Previously parse_step_file() ignored
    these entirely and labelled every solid "Part 1", "Part 2", ... which
    made BOM cross-referencing and meaningful image captions impossible.

    A STEP PRODUCT entity looks like:
        #57=PRODUCT('NAS577B6A','STD','',(#2)) ;
        #5 =PRODUCT('E5312070200000','ADAP-ASSY','RAIL EQUIPE',(#2)) ;
    Fields: (entity_id, name, category/type, description, ...)

    Entries whose category matches a known ASSEMBLY/reference-node pattern
    (assembly, cadnode, config, node...) are excluded — only concrete
    part-level entries are returned. This is a heuristic based on common
    CATIA/AP242 export conventions, not the STEP standard itself, so
    callers must verify the returned count matches the actual solid count
    before trusting the ordering (see parse_step_file()).

    Returns
    -------
    list of {"name": <PRODUCT id>, "description": <PRODUCT description>}
    in file-declaration order.
    """
    _ASSEMBLY_TYPE_PATTERN = re.compile(
        r'^(ADAP-ASSY|ASSY|ASSEMBLY|CADNODE|CONFIG|NODE)$', re.I
    )
    leaf_products = []
    try:
        with open(filepath, "r", errors="ignore") as f:
            text = f.read()
    except Exception as e:
       logger.exception(
    "Could not read STEP text for PRODUCT extraction"
)
       return []

    for m in re.finditer(
    r"PRODUCT\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'",
    text
):
        prod_id, prod_type, prod_desc = (
        m.group(1),
        m.group(2),
        m.group(3),
    )

        if _ASSEMBLY_TYPE_PATTERN.match(prod_type.strip()):
           continue

        leaf_products.append({
           "name": prod_id,
        "description": prod_desc,
    }) 

    return leaf_products


def _aggregate_cad_summary(parts: list[dict]) -> dict:
    """
    Roll per-part stats up into the assembly-level summary fields that
    ai_assistant.py's system prompt displays (total_parts, total_faces,
    total_edges, total_surface_area, total_volume, bounding_box,
    face_type_summary). Previously parse_step_file()'s return dict didn't
    include any of these, so the LLM was always shown "Total parts: 0 |
    Faces: 0 | Edges: 0" and "Face geometry distribution: none" regardless
    of how many real parts were actually parsed — the per-part breakdown
    further down the prompt was correct, but the top-level summary was
    silently wrong the whole time (accessed via .get() with defaults, so
    this never raised an error — it just quietly fed the LLM bad numbers).
    """
    if not parts:
        return {
            "total_parts": 0, "total_faces": 0, "total_edges": 0,
            "total_surface_area": 0.0, "total_volume": 0.0,
            "bounding_box": {"width": 0.0, "height": 0.0, "depth": 0.0},
            "face_type_summary": {},
        }

    total_faces = sum(p.get("face_count", 0) for p in parts)
    total_edges = sum(p.get("edge_count", 0) for p in parts)
    total_surface_area = sum(p.get("surface_area", 0.0) or 0.0 for p in parts)
    total_volume = sum(p.get("volume", 0.0) or 0.0 for p in parts)

    face_type_summary: dict = {}
    for p in parts:
        for kind, cnt in (p.get("face_types") or {}).items():
            face_type_summary[kind] = face_type_summary.get(kind, 0) + cnt

    # Overall bounding box = max extent across all parts (approximation —
    # parts aren't repositioned to their real assembly placement here, but
    # this is still far more useful to the LLM than a hardcoded zero).
    widths  = [p.get("bounding_box", {}).get("width", 0)  or 0 for p in parts]
    heights = [p.get("bounding_box", {}).get("height", 0) or 0 for p in parts]
    depths  = [p.get("bounding_box", {}).get("depth", 0)  or 0 for p in parts]

    return {
        "total_parts": len(parts),
        "total_faces": total_faces,
        "total_edges": total_edges,
        "total_surface_area": total_surface_area,
        "total_volume": total_volume,
        "bounding_box": {
            "width":  max(widths)  if widths  else 0.0,
            "height": max(heights) if heights else 0.0,
            "depth":  max(depths)  if depths  else 0.0,
        },
        "face_type_summary": face_type_summary,
    }


@traceable(name="parse_step_file")
def parse_step_file(filepath):
    """
    Entry point used by CAD upload handler.
    Uses cad_service and PartsManager to parse unique parts with duplicate renaming.
    """
    try:
        from cad_service import process_cad_file
        res = process_cad_file(filepath)
        return res["cad_doc"]
    except Exception as e:
        logger.warning(f"cad_service.process_cad_file fallback notice: {e}")

    start_time = time.perf_counter()
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".stl":
        return parse_stl_file(filepath)

    if not OCC_AVAILABLE:
        return parse_step_file_fallback(filepath)

    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID

    shape = load_step_file(filepath)

    print("IS NULL:", shape.IsNull())
    from OCP.TopAbs import (
        TopAbs_SOLID,
        TopAbs_COMPOUND,
        TopAbs_SHELL,
        TopAbs_FACE
    )
    from OCP.TopExp import TopExp_Explorer
    for shape_type, name in [
        (TopAbs_SOLID, "SOLID"),
        (TopAbs_SHELL, "SHELL"),
        (TopAbs_FACE, "FACE"),
        (TopAbs_COMPOUND, "COMPOUND")
        ]:
        count = 0
        exp = TopExp_Explorer(
            shape,
            shape_type
        )
        while exp.More():
            count += 1
            exp.Next()
        print(name, count)


    # Try to recover REAL part identifiers (often literally BOM part
    # numbers) from the raw STEP text — see _extract_step_leaf_product_names.
    # Only used if the count matches the solid count exactly; a mismatch
    # means the file's assembly/reference-node structure doesn't fit our
    # heuristic and we fall back to safe generic naming rather than risk
    # mislabeling a part (e.g. calling a bolt a "rail").
    leaf_products = _extract_step_leaf_product_names(filepath)

    solid_count = 0
    _counter = TopExp_Explorer(shape, TopAbs_SOLID)
    while _counter.More():
        solid_count += 1
        _counter.Next()

    use_real_names = len(leaf_products) == solid_count and solid_count > 0
    if leaf_products and not use_real_names:
        logger.warning(
    f"STEP PRODUCT count ({len(leaf_products)}) != solid count "
    f"({solid_count}). Falling back to generic Part-N names."
)
    parts = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    idx = 0
    while explorer.More():
        
        idx += 1
        try:
            if use_real_names:
                prod = leaf_products[idx - 1]
                part = _analyze_part(explorer.Current(), name=prod["name"], part_id=f"P{idx}")
                if prod.get("description"):
                    part["description"] = prod["description"]
            else:
                part = _analyze_part(explorer.Current(), name=f"Part {idx}", part_id=f"P{idx}")
            parts.append(part)
        except Exception as e:
            logger.exception(
    "Failed to process solid %s",
    idx,
)
        explorer.Next()

    if not parts:
        fallback_name = os.path.splitext(os.path.basename(filepath))[0]
        try:
            parts.append(_analyze_part(shape, name=fallback_name))
        except Exception as e:
            logger.exception(
    "Whole-shape fallback failed"
)

    logger.info(
    "STEP parsing completed. parts=%s file=%s",
    len(parts),
    os.path.basename(filepath),
)
    duration = time.perf_counter() - start_time
    summary = _aggregate_cad_summary(parts)

    return CADAssembly(
    filename=os.path.basename(filepath),

    parts=parts,

    parsing_mode="pythonocc",

    parsing_confidence=1.0,

    parse_duration=round(duration, 3),

    total_parts=summary["total_parts"],

    total_faces=summary["total_faces"],

    total_edges=summary["total_edges"],

    total_surface_area=summary["total_surface_area"],

    total_volume=summary["total_volume"],

    bounding_box=summary["bounding_box"],

    face_type_summary=summary["face_type_summary"],
)


# ──────────────────────────────────────────────────────────────────────────────
# CLI / quick test
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    step_file = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "E5312070100000 1.stp"
    )

    deflection = (
        float(sys.argv[2])
        if len(sys.argv) > 2
        else 0.1
    )

    try:
        result = parse_cad_file(
            step_file,
            linear_deflection=deflection,
        )

        summary = {
            "file": result["file"],
            "pythonocc_version": result["pythonocc_version"],
            "properties": result["properties"],
            "mesh_summary": {
                "face_count": result["mesh"]["face_count"],
                "vertex_count": result["mesh"]["vertex_count"],
                "triangle_count": result["mesh"]["triangle_count"],
            },
        }

        print(json.dumps(summary, indent=2))

    except Exception:
        logger.exception(
            "CAD parsing failed during CLI execution"
        )
        sys.exit(1)