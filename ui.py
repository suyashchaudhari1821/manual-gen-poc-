import streamlit as st
import tempfile
import json
import os
import textwrap
import fitz
import pandas as pd
from cad_service import process_cad_file
import importlib
import cad_viewer
importlib.reload(cad_viewer)
from cad_viewer import display_cad_viewer
from cad_parser import parse_step_file
from bom_parser import parse_bom_file_from_path
from manual_parser import parse_manual
from engineering_context import build_engineering_knowledge
# Import your Self-RAG runner
from self_rag import run_self_rag
from rag_pipeline import build_rag_indexes
from document_state import DocumentState
import uuid
from word_toc_updater import update_toc
from page_number_updater import (
    update_page_numbers
)
from toc_renderer import (
    get_toc_section,
    extract_original_toc
)
from pdf_blueprint_builder import (
build_pdf_blueprint
)
from section_builder import (
    build_document_structure,
    build_toc,
    print_structure,
)
from document_update_pipeline_1 import (
    find_insertion_page,
    create_generated_section_pdf,
    insert_generated_pdf
)
from document_state import (
    DocumentState,
    GeneratedSection
)
from placement_model import determine_placement
from docx import Document
from copy import deepcopy
from user_query_intent import (
    extract_query_intent
)
from rapidfuzz import fuzz
def update_docx_manual(
    docx_path,
    placement,
    generated_content,
    output_docx
):

    doc = Document(docx_path)

    target = (
        placement.target_section.strip().lower()
        if placement.target_section
        else None
    )

    insert_index = None
    print("\nTARGET SECTION")
    print(target)

    for idx, para in enumerate(doc.paragraphs):
        current_text = para.text.strip().lower()
        print(
            f"[{idx}] "
            f"{current_text}"
        )
        if current_text == target:
            print(
                f"MATCH FOUND AT {idx}"
            )
            insert_index = idx
            break
        score = fuzz.ratio(
            current_text,
             target
        )
        if score > 80:
            if score > 80:
                print(
                    f"MATCH FOUND "
                     f"{current_text}"
                     f" SCORE={score}"
                )
                insert_index = idx
                break      

        if (
            para.text.strip().lower()
            == target
        ):
            insert_index = idx
            break

    # fallback
    if insert_index is None:

        doc.add_page_break()

        heading_para = doc.add_paragraph()
        heading_run = heading_para.add_run(
            placement.generated_title
            )
        heading_run.bold = True
        doc.add_paragraph(
            generated_content
        )
        doc.save(output_docx)
        

        return output_docx
    
    # insert title
    heading_para = doc.paragraphs[
        insert_index
    ].insert_paragraph_before(
        placement.generated_title
    )

    try:
        heading_para.style = "Heading 1"
    except KeyError:
        pass

    # insert content
    for line in generated_content.split("\n"):

        line = line.strip()

        if not line:
            continue

        p = doc.paragraphs[
            insert_index + 1
        ].insert_paragraph_before(
            line
        )

        p.style = "Normal"

    doc.save(output_docx)

    return output_docx
def save_uploaded_file(uploaded_file):

    suffix = "." + uploaded_file.name.split(".")[-1]

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=suffix
    ) as tmp:

        tmp.write(
            uploaded_file.getbuffer()
        )

        return tmp.name



def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except Exception:
        return ""

st.set_page_config(
    page_title="Expleo | Engineering Documentation Generator",
    page_icon="static/favicon.png",
    layout="wide",
)

def inject_expleo_theme():
    bg_b64 = get_base64_image("static/expleo_bg_hd.png")
    bg_css = f"url('data:image/png;base64,{bg_b64}')" if bg_b64 else "none"

    st.markdown(textwrap.dedent(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

    /* Expleo Brand Atmosphere with Crisp HD Background */
    .stApp {{
        background-color: #5631c7 !important;
        background-image: 
            linear-gradient(180deg, rgba(16, 11, 34, 0.50) 0%, rgba(22, 14, 46, 0.68) 100%),
            {bg_css} !important;
        background-size: cover, cover !important;
        background-position: center, center !important;
        background-repeat: no-repeat, no-repeat !important;
        background-attachment: fixed, fixed !important;
        font-family: 'Inter', -apple-system, sans-serif !important;
        color: #F8FAFC !important;
    }}

    /* Hide default Streamlit chrome */
    [data-testid="stHeader"], #MainMenu, footer {{
        display: none !important;
    }}

    .main .block-container {{
        max-width: 1440px !important;
        padding-top: 1.2rem !important;
        padding-bottom: 3rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        margin: auto !important;
    }}

    /* Top Navigation Bar - Clean Corporate */
    .expleo-topbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 20px;
        margin-bottom: 22px;
        background: rgba(16, 20, 36, 0.70) !important;
        backdrop-filter: blur(16px) !important;
        -webkit-backdrop-filter: blur(16px) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25) !important;
    }}

    .expleo-nav-brand {{
        display: flex;
        align-items: center;
        gap: 16px;
    }}

    .nav-logo {{
        height: 36px;
        object-fit: contain;
    }}

    .nav-divider {{
        width: 1px;
        height: 28px;
        background: rgba(148, 163, 184, 0.35);
    }}

    .nav-title {{
        font-size: 1.25rem;
        font-weight: 700;
        color: #FFFFFF;
        letter-spacing: -0.01em;
    }}

    /* Section Architecture Headers */
    .section-header {{
        display: flex;
        align-items: center;
        gap: 12px;
        margin-top: 24px;
        margin-bottom: 14px;
    }}

    .step-badge {{
        background: rgba(2, 132, 199, 0.16);
        border: 1px solid rgba(56, 189, 248, 0.40);
        color: #38BDF8;
        font-size: 0.72rem;
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 6px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}

    .section-title {{
        font-size: 1.15rem;
        font-weight: 700;
        color: #F8FAFC;
        letter-spacing: -0.01em;
    }}

    /* File Uploader Dropzones */
    [data-testid="stFileUploaderDropzone"],
    section[data-testid="stFileUploadDropzone"] {{
        background: rgba(16, 20, 36, 0.72) !important;
        backdrop-filter: blur(14px) !important;
        -webkit-backdrop-filter: blur(14px) !important;
        border: 1px dashed rgba(56, 189, 248, 0.35) !important;
        border-radius: 12px !important;
        padding: 16px 20px !important;
        color: #F8FAFC !important;
        transition: all 0.2s ease !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.20) !important;
    }}

    [data-testid="stFileUploadDropzone"]:hover {{
        border-color: #38BDF8 !important;
        background: rgba(22, 28, 48, 0.85) !important;
        box-shadow: 0 0 20px rgba(2, 132, 199, 0.25) !important;
    }}

    /* Engineering KPI & Metric Cards */
    div[data-testid="stMetric"] {{
        background: rgba(16, 20, 36, 0.76) !important;
        backdrop-filter: blur(16px) !important;
        -webkit-backdrop-filter: blur(16px) !important;
        border: 1px solid rgba(56, 189, 248, 0.22) !important;
        border-radius: 12px !important;
        padding: 16px 20px !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25) !important;
        transition: all 0.2s ease !important;
    }}
    div[data-testid="stMetric"]:hover {{
        border-color: rgba(56, 189, 248, 0.50) !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 24px rgba(2, 132, 199, 0.30) !important;
    }}
    div[data-testid="stMetric"] label {{
        color: #94A3B8 !important;
        font-weight: 600 !important;
        font-size: 0.76rem !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
    }}
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {{
        color: #FFFFFF !important;
        font-weight: 700 !important;
        font-size: 1.75rem !important;
    }}

    /* Expleo Cobalt Action Buttons */
    div[data-testid="stButton"] button {{
        background: linear-gradient(135deg, #0284C7 0%, #0066FF 100%) !important;
        color: #FFFFFF !important;
        font-weight: 600 !important;
        font-size: 0.92rem !important;
        border-radius: 8px !important;
        border: 1px solid rgba(56, 189, 248, 0.40) !important;
        padding: 10px 24px !important;
        box-shadow: 0 4px 16px rgba(2, 132, 199, 0.35) !important;
        transition: all 0.2s ease !important;
    }}
    div[data-testid="stButton"] button:hover {{
        background: linear-gradient(135deg, #0369A1 0%, #0052CC 100%) !important;
        box-shadow: 0 6px 24px rgba(2, 132, 199, 0.50) !important;
        transform: translateY(-1px) !important;
    }}

    /* Inputs */
    textarea, input[type="text"] {{
        background: rgba(16, 20, 36, 0.78) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border: 1px solid rgba(56, 189, 248, 0.25) !important;
        border-radius: 10px !important;
        color: #F8FAFC !important;
    }}
    textarea:focus, input[type="text"]:focus {{
        border-color: #0284C7 !important;
        box-shadow: 0 0 14px rgba(2, 132, 199, 0.30) !important;
    }}

    /* Expanders & Data Tables */
    details[data-testid="stExpander"] {{
        background: rgba(16, 20, 36, 0.72) !important;
        backdrop-filter: blur(14px) !important;
        -webkit-backdrop-filter: blur(14px) !important;
        border: 1px solid rgba(56, 189, 248, 0.22) !important;
        border-radius: 12px !important;
    }}
    button[data-baseweb="tab"] {{
        color: #94A3B8 !important;
        font-weight: 600 !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: #38BDF8 !important;
        border-bottom-color: #0284C7 !important;
    }}
    </style>
    """).strip(), unsafe_allow_html=True)

inject_expleo_theme()

def render_expleo_topbar():
    logo_b64 = get_base64_image("static/expleo_logo.png")
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" class="nav-logo" alt="Expleo" />' if logo_b64 else '<span style="font-size:1.35rem;font-weight:800;color:#fff;letter-spacing:0.5px;">[ expleo ]</span>'

    st.markdown(textwrap.dedent(f"""
    <div class="expleo-topbar">
      <div class="expleo-nav-brand">
        {logo_html}
        <div class="nav-divider"></div>
        <div class="nav-title">Engineering Documentation Generator</div>
      </div>
    </div>
    """).strip(), unsafe_allow_html=True)

render_expleo_topbar()


# --------------------------------------------------------
# Session State
# --------------------------------------------------------

if "knowledge" not in st.session_state:
    st.session_state.knowledge = None

if "structured_document" not in st.session_state:
    st.session_state.structured_document = None

if "toc" not in st.session_state:
    st.session_state.toc = None

if "cad_path" not in st.session_state:
    st.session_state.cad_path = None

if "bom_path" not in st.session_state:
    st.session_state.bom_path = None

if "manual_path" not in st.session_state:
    st.session_state.manual_path = None

if "document_state" not in st.session_state:
    st.session_state.document_state = None

if "blueprint" not in st.session_state:
    st.session_state.blueprint = None

if "manual_type" not in st.session_state:
    st.session_state.manual_type = None

if "uploaded_filename" not in st.session_state:
    st.session_state.uploaded_filename = None

if "cad_data" not in st.session_state:
    st.session_state.cad_data = None

if "cad_doc" not in st.session_state:
    st.session_state.cad_doc = None

if "bom_doc" not in st.session_state:
    st.session_state.bom_doc = None

if "uploaded_cad_filename" not in st.session_state:
    st.session_state.uploaded_cad_filename = None

if "uploaded_bom_filename" not in st.session_state:
    st.session_state.uploaded_bom_filename = None

if st.session_state.document_state:
    st.sidebar.write(
         "Document:",
          st.session_state.document_state.document_name
    )
    st.sidebar.write(
        "Version:",
        st.session_state.document_state.version
    )
    st.sidebar.write(
         "Thread:",
         st.session_state.document_state.document_thread_id
    )

# --------------------------------------------------------
# File Uploads
# --------------------------------------------------------

st.markdown('<div style="font-size: 1.18rem; font-weight: 700; color: #FFFFFF; margin-top: 16px; margin-bottom: 12px; letter-spacing: -0.01em;">Upload Engineering Assets</div>', unsafe_allow_html=True)

col_u1, col_u2, col_u3 = st.columns(3)

with col_u1:
    cad_file = st.file_uploader(
        "Upload CAD File (.stp, .step, .stl)",
        type=["stp", "step", "stl", "obj"],
    )

with col_u2:
    bom_file = st.file_uploader(
        "Upload BOM File",
        type=["pdf", "xlsx", "xls", "csv"],
    )

with col_u3:
    manual_file = st.file_uploader(
        "Upload User Manual",
        type=["pdf", "docx"],
    )

# Handle Manual File
if (
    manual_file
    and
    manual_file.name
    != st.session_state.uploaded_filename
):
    st.session_state.uploaded_filename = manual_file.name
    st.session_state.manual_path = save_uploaded_file(manual_file)
    st.session_state.manual_type = manual_file.name.split(".")[-1].lower()
    st.session_state.document_state = DocumentState(
        document_thread_id=str(uuid.uuid4()),
        document_name=manual_file.name,
        current_file=st.session_state.manual_path,
        version=0
    )

# Handle BOM File
if bom_file and st.session_state.uploaded_bom_filename != bom_file.name:
    st.session_state.bom_path = save_uploaded_file(bom_file)
    st.session_state.uploaded_bom_filename = bom_file.name
    try:
        with st.spinner(f"Reading BOM: {bom_file.name}..."):
            st.session_state.bom_doc = parse_bom_file_from_path(st.session_state.bom_path)
            # Re-correlate CAD if CAD was already uploaded
            if st.session_state.get("cad_path"):
                cad_res = process_cad_file(st.session_state.cad_path, bom_doc=st.session_state.bom_doc)
                st.session_state.cad_data = cad_res
                st.session_state.cad_doc = cad_res["cad_doc"]
    except Exception as e:
        st.warning(f"BOM parsing notice: {e}")

# Handle CAD File & 3D Conversion
if cad_file:
    force_reload = st.session_state.get("force_cad_reload", False)
    if st.session_state.get("uploaded_cad_filename") != cad_file.name or force_reload or not st.session_state.get("cad_data"):
        st.session_state.force_cad_reload = False
        st.session_state.cad_path = save_uploaded_file(cad_file)
        with st.spinner(f"Converting {cad_file.name} to 3D WebGL & parsing parts with PartsManager..."):
            try:
                cad_res = process_cad_file(
                    file_path=st.session_state.cad_path,
                    bom_doc=st.session_state.get("bom_doc")
                )
                st.session_state.cad_data = cad_res
                st.session_state.cad_doc = cad_res["cad_doc"]
                st.session_state.uploaded_cad_filename = cad_file.name
            except Exception as e:
                st.error(f"CAD Conversion error: {e}")

# --------------------------------------------------------
# 3D CAD Interactive Viewer & Parts Details
# --------------------------------------------------------
if st.session_state.get("cad_data"):
    cad_info = st.session_state.cad_data
    dup_report = cad_info["duplicate_report"]
    
    cv_head_col1, cv_head_col2 = st.columns([0.82, 0.18])
    with cv_head_col1:
        st.markdown('<div style="font-size: 1.25rem; font-weight: 700; color: #FFFFFF; margin-top: 24px; margin-bottom: 14px; letter-spacing: -0.01em;">3D CAD Viewer</div>', unsafe_allow_html=True)
    with cv_head_col2:
        st.markdown('<div style="margin-top: 20px;"></div>', unsafe_allow_html=True)
        if st.button("Reload 3D Model", key="btn_reload_cad_model"):
            st.session_state.force_cad_reload = True
            st.session_state.cad_data = None
            st.rerun()
    
    # Metrics
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Parts", len(cad_info["parts_list"]))
    with m2:
        st.metric("Unique Types", dup_report["unique_count"])
    with m3:
        st.metric("Duplicate Parts Found", dup_report["duplicates_found"])
    with m4:
        st.metric("3D Model Size", f"{cad_info['stats']['file_size_mb']} MB")
        
    # Render the Three.js 3D Viewport
    display_cad_viewer(
        glb_b64=cad_info["glb_b64"],
        model_name=st.session_state.get("uploaded_cad_filename", "CAD Model"),
        parts_list=cad_info["parts_list"],
        unique_parts_list=cad_info["unique_parts_list"],
        structured_parts=cad_info.get("structured_parts"),
        height=640
    )
    
    # Expandable Parts Details Table
    with st.expander("Assembly Components & BOM Identification", expanded=False):
        df_parts = pd.DataFrame([
            {
                "Item #": p["part_id"],
                "Original CAD Name": p["name"],
                "Unique Part ID": p["unique_name"],
                "Part Number": p["part_number"],
                "Occurrence": f"#{p['occurrence']} of {p['total_occurrences']}" if p["is_duplicate"] else "1 of 1",
                "Status": "Multi-Instance" if p["is_duplicate"] else "Single Instance"
            }
            for p in cad_info["structured_parts"]
        ])
        st.dataframe(df_parts, use_container_width=True)



# --------------------------------------------------------
# Requirement
# --------------------------------------------------------

st.markdown('<div style="font-size: 1.18rem; font-weight: 700; color: #FFFFFF; margin-top: 24px; margin-bottom: 8px; letter-spacing: -0.01em;">Engineering Requirement</div>', unsafe_allow_html=True)

requirement = st.text_area(
    "Enter Requirement",
    height=120,
    placeholder="""
Examples:

Insert a troubleshooting section.

Generate maintenance instructions.

Generate a complete installation manual.

What is the exhaust hose installation procedure?
""",
)


# --------------------------------------------------------
# BUTTON 1
# --------------------------------------------------------

if st.button("Generate Engineering Knowledge"):

    if (
        not st.session_state.cad_path
        or not st.session_state.bom_path
        or not st.session_state.document_state.current_file
    ):
        st.error("Please upload CAD, BOM and Manual.")

    else:
        with st.spinner("Building Engineering Knowledge..."):

            if st.session_state.get("cad_doc") is not None:
                cad_doc = st.session_state.cad_doc
            else:
                cad_res = process_cad_file(st.session_state.cad_path, bom_doc=st.session_state.get("bom_doc"))
                cad_doc = cad_res["cad_doc"]
                st.session_state.cad_doc = cad_doc

            if st.session_state.get("bom_doc") is not None:
                bom_doc = st.session_state.bom_doc
            else:
                bom_doc = parse_bom_file_from_path(st.session_state.bom_path)
                st.session_state.bom_doc = bom_doc

            manual_doc = parse_manual(
                st.session_state.document_state.current_file
            )
            (
                chunks,
                text_index,
                image_index,
                image_metadata
            ) = build_rag_indexes(
                manual_doc=manual_doc,
                cad_doc=cad_doc
            )
            st.session_state.chunks = chunks
            st.session_state.text_index = text_index
            st.session_state.image_index = image_index
            st.session_state.image_metadata = image_metadata

            blueprint = build_pdf_blueprint(
                st.session_state.document_state.current_file
)

            if st.session_state.manual_type == "pdf":

                blueprint = build_pdf_blueprint(
                    st.session_state.document_state.current_file
    )

                st.session_state.blueprint = blueprint

                print(
                    json.dumps(
                        blueprint["styles"],
                        indent=2
        )
    )       
            print(
                "MANUAL TYPE:",
                st.session_state.manual_type
            )
            print(
                "MANUAL PATH:",
               st.session_state.document_state.current_file
            )
            print(
                "MANUAL DOC:",
                manual_doc
            )
            structured_document = build_document_structure(
                manual_doc
            )

            print_structure(
                structured_document
            )
            print(
                "TOTAL SECTIONS:",
                len(structured_document.sections)
            )
            for section in structured_document.sections:
                print(section.title)

            #toc_section = get_toc_section(
                #structured_document
            #)
            #original_toc = extract_original_toc(
               # st.session_state.document_state.current_file,
                 #toc_section
            #)
            #st.session_state.original_toc = deepcopy(
                #original_toc
            #)
            #st.session_state.toc = deepcopy(
                #original_toc
            #)

            st.session_state.structured_document = (
                structured_document
            )

            knowledge = build_engineering_knowledge(
                cad_doc=cad_doc,
                bom_doc=bom_doc,
                manual_doc=manual_doc,
            )

            st.session_state.knowledge = knowledge

        st.success("Engineering Knowledge Created")

        st.subheader("Document Structure")

        st.write(
            f"Sections Found: "
            f"{len(structured_document.sections)}"
        )

        #with st.expander("Table Of Contents"):
            #st.json(original_toc)

        st.subheader("Engineering Knowledge Summary")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("### CAD")

            st.write(
                f"Filename: {knowledge.cad.filename}"
            )

            st.write(
                f"Total Parts: {knowledge.cad.total_parts}"
            )

        with col2:
            st.markdown("### BOM")

            st.write(
                f"Filename: {knowledge.bom.filename}"
            )

            st.write(
                f"Rows: {knowledge.bom.row_count}"
            )

        with col3:
            st.markdown("### Manual")

            st.write(
                f"Text Blocks: "
                f"{len(knowledge.manual.text_blocks)}"
            )

            st.write(
                f"Image Blocks: "
                f"{len(knowledge.manual.image_blocks)}"
            )

            st.write(
                f"Table Blocks: "
                f"{len(knowledge.manual.table_blocks)}"
            )

        with st.expander("View Full Engineering Knowledge"):
            st.json(
                knowledge.model_dump()
            )


# --------------------------------------------------------
# BUTTON 2
# --------------------------------------------------------

if st.button("Run Self-RAG Pipeline"):

    if st.session_state.knowledge is None:

        st.error(
            "Generate Engineering Knowledge first."
        )

    else:
        # -----------------------------------
        # Extract User Intent
        # -----------------------------------

        intent = extract_query_intent(
            requirement
            )
        print("\nUSER INTENT")
        print(intent)

        with st.spinner("Running Self-RAG..."):

            rag_result = run_self_rag(
                question=intent.retrieval_query,
                chunks=st.session_state.chunks,
                text_index=st.session_state.text_index,
                image_index=st.session_state.image_index,
                image_metadata=st.session_state.image_metadata
)
            
            rag_result["image_path"] = None
            
            print("\nAVAILABLE SECTIONS")
            for section in (
                st.session_state.structured_document.sections
                ):

                print(section.title)

            placement = determine_placement(
                intent=intent,
                structured_document=
                st.session_state.structured_document
            )

            print(
                "PLACEMENT:",
                placement
            )
            print(placement)

            print(
                "TITLE:",
                placement.generated_title
            )

            # --------------------------------------
            # PDF FLOW
            # --------------------------------------

            if (
                st.session_state.manual_type
                == "pdf"
            ):

                if (
                    st.session_state.blueprint
                    is None
                ):

                    st.error(
                        "Blueprint not found. Generate Engineering Knowledge first."
                    )

                    st.stop()

                insert_page = find_insertion_page(
                    st.session_state.structured_document,
                    placement.target_section
                )

                print(
                    "INSERT AFTER PAGE:",
                    insert_page
                )

                if insert_page is None:
                     print(
                         f"Target section not found: "
                         f"{placement.target_section}"
                     )
                     print(
                         "FALLBACK: APPENDING TO END"
                     )
                     placement.action = "append"
                     placement.target_section = None
                else:
                    placement.action = "insert_after"


                generated_section = GeneratedSection(
                    title=placement.generated_title,
                    content=rag_result["answer"],
                    placement_action=placement.action,
                    target_section=placement.target_section,
)

                generated_pdf = (
                    create_generated_section_pdf(
                        title=
                        placement.generated_title,

                        content=generated_section.content,

                        blueprint=
                        st.session_state.blueprint,

                        output_pdf=
                        "generated_section.pdf"
                    )
                )
                version = (
                    st.session_state.document_state.version + 1
                )
                base_name = (
                    os.path.splitext(
                        st.session_state.document_state.document_name
                        )[0]
                )
                output_pdf = (
                    f"{base_name}_v{version}.pdf"
                )

                updated_pdf = (
                    insert_generated_pdf(
                        original_pdf=
                        st.session_state.document_state.current_file,

                        generated_pdf=
                        generated_pdf,

                        insert_after_page=
                        insert_page,

                        output_pdf=
                        output_pdf
                    )
                )
                updated_pdf = update_page_numbers(
                    pdf_path=updated_pdf,
                    output_pdf=f"{base_name}_v{version}_pages.pdf"
                )
                generated_doc = fitz.open(
                    generated_pdf
                )
                pages_added = len(
                    generated_doc
                )
                generated_doc.close()
                updated_manual = parse_manual(
                    updated_pdf
                )
                updated_structure = (
                    build_document_structure(
                        updated_manual
                    )
                )
                st.session_state.structured_document = (
                    updated_structure
                )
                
                final_pdf=updated_pdf
                
                st.session_state.document_state.generated_sections.append(
                    generated_section
                )
                st.session_state.document_state.current_file = (
                    final_pdf
                )
                st.session_state.document_state.version += 1

                print("\nDOCUMENT STATE")
                print(
                    st.session_state.document_state.model_dump()
                )

                if os.path.exists(
                    final_pdf
                ):

                    with open(
                        final_pdf,
                        "rb"
                    ) as f:

                        st.download_button(
                            label=
                            "Download Updated PDF",

                            data=
                            f.read(),

                            file_name=
                            os.path.basename(final_pdf),

                            mime=
                            "application/pdf"
                        )
                

            # --------------------------------------
            # DOCX FLOW
            # --------------------------------------

            elif (
                st.session_state.manual_type
                == "docx"
            ):
                print(
                    "CURRENT DOCX:",
                    st.session_state.document_state.current_file
                    )
                version = (
                    st.session_state.document_state.version + 1
                )
                base_name = (
                    os.path.splitext(
                        st.session_state.document_state.document_name
                        )[0]
                )

                output_docx = (
                    f"{base_name}_v{version}.docx"
                )

                    
                generated_section = GeneratedSection(
                    title=placement.generated_title,
                    content=rag_result["answer"],
                    placement_action=placement.action,
                    target_section=placement.target_section
)
                updated_docx = (
                    update_docx_manual(
                        docx_path=
                        st.session_state.document_state.current_file,
                        placement=
                        placement,
                        generated_content=generated_section.content,
                        output_docx=
                        output_docx
                    )
                )
                try:
                    update_toc(updated_docx)
                    print(
                        "TOC updated successfully"
                    )
                except Exception as e:
                    print(
                        f"TOC update failed: {e}"
                    )
                updated_manual = parse_manual(
                    updated_docx
                )
                updated_structure = (
                    build_document_structure(
                        updated_manual
                    )
                )
                #updated_toc = build_toc(
                   # updated_structure
                #)
                st.session_state.structured_document = (
                    updated_structure
                )
                #st.session_state.toc = (
                    #updated_toc
                #)
                st.session_state.document_state.generated_sections.append(
                    generated_section
                )
                st.session_state.document_state.current_file = (
                    updated_docx
                )
                st.session_state.document_state.version += 1
                print("\nDOCUMENT STATE")
                print(
                    st.session_state.document_state.model_dump()
)

                if os.path.exists(
                    updated_docx
                ):

                    with open(
                        updated_docx,
                        "rb"
                    ) as f:

                        st.download_button(
                            label=
                            "Download Updated DOCX",

                            data=
                            f.read(),

                            file_name=
                            os.path.basename(updated_docx),

                            mime=
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        )

        st.success(
            "Self-RAG Completed"
        )

        tabs = st.tabs(
            [
                "Document Structure",
                "Retrieved Docs",
                "Relevant Docs",
                "Context",
                "Answer",
                "Verification",
            ]
        )

        # --------------------------------
        # Document Structure
        # --------------------------------

        with tabs[0]:

            st.subheader(
                "Document Structure"
            )

            if (
                st.session_state.structured_document
                is not None
            ):

                for section in (
                    st.session_state
                    .structured_document
                    .sections
                ):

                    with st.expander(
                        section.title
                    ):

                        st.write(
                            f"Start Page: "
                            f"{section.start_page}"
                        )

                        st.write(
                            f"End Page: "
                            f"{section.end_page}"
                        )

                        st.write(
                            f"Level: "
                            f"{section.level}"
                        )

                        st.write(
                            f"Text Blocks: "
                            f"{len(section.text_blocks)}"
                        )

                        st.write(
                            f"Images: "
                            f"{len(section.image_blocks)}"
                        )

                        st.write(
                            f"Tables: "
                            f"{len(section.table_blocks)}"
                        )

        # --------------------------------
        # Retrieved Docs
        # --------------------------------

        with tabs[1]:

            st.subheader(
                "Retrieved Documents"
            )

            for doc in rag_result.get(
                "retrieved_docs",
                [],
            ):

                st.markdown(
                    f"### {doc.title}"
                )

                st.write(
                    doc.content[:1000]
                )

        # --------------------------------
        # Relevant Docs
        # --------------------------------

        with tabs[2]:

            st.subheader(
                "Relevant Documents"
            )

            for doc in rag_result.get(
                "relevant_docs",
                [],
            ):

                st.markdown(
                    f"### {doc.title}"
                )

                st.write(
                    doc.content[:1000]
                )

        # --------------------------------
        # Context
        # --------------------------------

        with tabs[3]:

            st.subheader(
                "Context Sent To LLM"
            )

            st.text_area(
                "LLM Context",
                value=rag_result["context"],
                height=500,
            )

        # --------------------------------
        # Answer
        # --------------------------------

        with tabs[4]:
            st.subheader("Generated Answer")
            st.markdown(
                    rag_result["answer"]
                )

        # --------------------------------
        # Verification
        # --------------------------------

        with tabs[5]:

            st.subheader(
                "IsSUP"
            )

            st.json(
                {
                    "issup": rag_result["issup"],
                    "evidence": rag_result["evidence"],
                }
            )

            st.subheader(
                "IsUSE"
            )

            st.json(
                {
                    "isuse": rag_result["isuse"],
                    "reason": rag_result["use_reason"],
                }
            )