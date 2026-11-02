import os
import numpy as np

# STEP imports
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDocStd import TDocStd_Document
from OCP.collections import Sequence_TDF_Label
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.XCAFDoc import XCAFDoc_ShapeTool
from OCP.TDF import TDF_Label
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.TopLoc import TopLoc_Location
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from image_generation import generate_snapshot
# STL import
from stl import mesh as stl_mesh_lib
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
def load_stl_file(filepath):

    stl_mesh = stl_mesh_lib.Mesh.from_file(filepath)
    vertices = []
    triangles = []

    vertex_index = {}

    for tri in stl_mesh.vectors:

        face = []

        for vertex in tri:

            key = tuple(vertex)

            if key not in vertex_index:
                vertex_index[key] = len(vertices)
                vertices.append(list(vertex))

            face.append(vertex_index[key])

        triangles.append(face)

    return [
        {
            "cad_part_id": "P1",
            "cad_name": os.path.basename(filepath),
            "mesh": {
                "vertices": vertices,
                "triangles": triangles,
                "vertex_count": len(vertices),
                "triangle_count": len(triangles)
            }
        }
    ]
def collect_components(shape_tool, label, result):

    # current label
    result.append(label)

    # if assembly, get children
    if XCAFDoc_ShapeTool.IsAssembly_s(label):

        children = Sequence_TDF_Label()

        XCAFDoc_ShapeTool.GetComponents_s(
            label,
            children,
            False
        )

        for i in range(1, children.Length() + 1):

            child = children.Value(i)

            collect_components(
                shape_tool,
                child,
                result
            )
def load_step_xde(filepath):

    app = XCAFApp_Application.GetApplication_s()

    doc = TDocStd_Document(
        TCollection_ExtendedString("cad_doc")
    )

    reader = STEPCAFControl_Reader()

    reader.SetColorMode(True)
    reader.SetNameMode(True)
    reader.SetLayerMode(True)

    status = reader.ReadFile(filepath)

    if status != 1:
        raise RuntimeError(
            f"Failed to load STEP: {filepath}"
        )

    reader.Transfer(doc)

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(
        doc.Main()
    )

    return doc, shape_tool
from OCP.TopExp import TopExp_Explorer

def count_entities(shape, entity_type):
    count = 0

    exp = TopExp_Explorer(
        shape,
        entity_type
    )

    while exp.More():
        count += 1
        exp.Next()

    return count
from OCP.TDataStd import TDataStd_Name
from OCP.TCollection import TCollection_ExtendedString
from OCP.TopoDS import TopoDS_Iterator

def inspect_shape(shape, level=0):

    indent = "  " * level

    print(
        indent,
        "Type:",
        shape.ShapeType()
    )

    it = TopoDS_Iterator(shape)

    while it.More():

        child = it.Value()

        inspect_shape(
            child,
            level + 1
        )

        it.Next()

def extract_named_parts(shape_tool):

    free_shapes = Sequence_TDF_Label()

    shape_tool.GetFreeShapes(free_shapes)
    print(
        "Free Shapes:",
        free_shapes.Length()
    )

    all_labels = []

    for i in range(1, free_shapes.Length() + 1):

        root = free_shapes.Value(i)

        collect_components(
            shape_tool,
            root,
            all_labels
        )

    print(
        "Total Labels:",
        len(all_labels)
    )

    parts = []

    for idx, label in enumerate(all_labels, start=1):

        try:
            shape = XCAFDoc_ShapeTool.GetShape_s(
                label
            )

            if shape.IsNull():
                continue

        except Exception:
            continue

        name = f"Part_{idx}"

        try:

            attr = TDataStd_Name()

            if label.FindAttribute(
                TDataStd_Name.GetID_s(),
                attr
            ):

                name = (
                    attr.Get()
                    .ToExtString()
                )

        except Exception:
            pass
        print(
            name,
             "ShapeType:",
             shape.ShapeType()
        )
        if shape_tool.IsReference_s(label):
            ref_label = TDF_Label()
            shape_tool.GetReferredShape_s(
                label,
                ref_label
            )
            resolved_shape = XCAFDoc_ShapeTool.GetShape_s(
                ref_label
            )
            children = Sequence_TDF_Label()
            shape_tool.GetComponents_s(
                ref_label,
                children,
                False
            )
            print(
                name,
                "Ref Child Count:",
                children.Length()
            )
            print(
                 name,
                 "IsNull:",
                 resolved_shape.IsNull()
            )
            print(
                name,
                 "Edges:",
                 count_entities(
                     resolved_shape,
                     TopAbs_EDGE
                 )
            ) 
            print(
                name,
                "Ref Is Assembly:",
                shape_tool.IsAssembly_s(ref_label)
            )
            print(
                name,
                 "Ref Is Reference:",
                 shape_tool.IsReference_s(ref_label)
            )
            print(
                name,
                "Ref Is SimpleShape:",
                shape_tool.IsSimpleShape_s(ref_label)
            )
                                        
            if idx == 2:
                print("\n===== SHAPE TREE =====")
                inspect_shape(
                    resolved_shape
                )
                print("=====================\n")
            print(
                 name,
                 "Resolved ShapeType:",
                 resolved_shape.ShapeType()
            )
            print(
                 name,
                 "Resolved Solids:",
                 count_entities(
                     resolved_shape,
                     TopAbs_SOLID
                 )
            )
            if not resolved_shape.IsNull():
                 shape = resolved_shape
            print(
                 name,
                 "Resolved SimpleShape:",
                 shape_tool.IsSimpleShape_s(
                     ref_label
                     ),          
                "Resolved Faces:",
            count_entities(
                resolved_shape,
                 TopAbs_FACE
            )
            )
        face_count = count_entities(
            shape,
            TopAbs_FACE
        )
        print(
            name,"Assembly:",
            XCAFDoc_ShapeTool.IsAssembly_s(label),
            "Reference:",
             shape_tool.IsReference_s(label),
             "SimpleShape:",
             shape_tool.IsSimpleShape_s(label),
             "Faces:",
             face_count
        )
        parts.append(
             {
                 "name": name,
                 "shape": shape
             }
        )
        print(
            f"Label {idx}:",
            label
        )
        print(
            "Has Name:",
            label.FindAttribute(
                TDataStd_Name.GetID_s(),
                attr
            )
        )

    return parts
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.TopLoc import TopLoc_Location
from OCP.BRep import BRep_Tool

import numpy as np


def tessellate_named_parts(parts):

    output = []

    for idx, part in enumerate(parts, start=1):
        shape = part["shape"]
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        count = 0
        while explorer.More():
            count += 1
            explorer.Next()
        print("Sub-solids:", count)
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        mesh = BRepMesh_IncrementalMesh(
            shape,
            0.5,
            False,
            0.5,
            True
        )
        mesh.Perform()

        shape = part["shape"]

        vertices = []
        faces = []

        vertex_offset = 0

        explorer = TopExp_Explorer(
            shape,
            TopAbs_FACE
        )

        while explorer.More():

            face = TopoDS.Face(
                explorer.Current()
            )

            loc = TopLoc_Location()

            tri = BRep_Tool.Triangulation_s(
                face,
                loc
            )

            if tri:

                trsf = loc.Transformation()

                for n in range(
                    1,
                    tri.NbNodes() + 1
                ):

                    p = tri.Node(n)

                    p.Transform(trsf)

                    vertices.append([
                        p.X(),
                        p.Y(),
                        p.Z()
                    ])

                for t in range(
                    1,
                    tri.NbTriangles() + 1
                ):

                    a, b, c = (
                        tri.Triangle(t).Get()
                    )

                    faces.append([
                        a - 1 + vertex_offset,
                        b - 1 + vertex_offset,
                        c - 1 + vertex_offset
                    ])

                vertex_offset += (
                    tri.NbNodes()
                )

            explorer.Next()

        cad_name = part["name"]
        clean_name = (
            cad_name
            .rsplit(".", 1)[0]
        )    

        output.append(
            {
                "cad_part_id":
                    f"P{idx}",

                "cad_name":
                    part["name"],

                "mesh": {
                    "vertices": vertices,
                    "triangles": faces,
                    "vertex_count": len(vertices),
                    "triangle_count": len(faces)
    }
            }
        )

    return output
def load_step_file(filepath):

    doc, shape_tool = load_step_xde(filepath)

    named_parts = extract_named_parts(
        shape_tool
    )

    return tessellate_named_parts(
        named_parts
    )
def load_cad_file(filepath):

    ext = os.path.splitext(
        filepath
    )[1].lower()

    if ext in [".stp", ".step"]:

        return load_step_file(
            filepath
        )

    elif ext == ".stl":

        return load_stl_file(
            filepath
        )

    raise ValueError(
        f"Unsupported format: {ext}"
    )

if __name__ == "__main__":
    CAD_FILE=(r"C:\Users\pgavhane\OneDrive - Expleo France\Documents\PROJECT\ENGINE POC ASSY (2).stp")

    doc, shape_tool = load_step_xde(CAD_FILE)

    named_parts = extract_named_parts(shape_tool)

    
    geometry_parts = tessellate_named_parts(
        named_parts
)

    print("Parts:", len(geometry_parts))

    for p in geometry_parts[:15]:
        print(
            p["cad_part_id"],
            p["cad_name"],
            p["mesh"]["vertex_count"],
            p["mesh"]["triangle_count"]
    )