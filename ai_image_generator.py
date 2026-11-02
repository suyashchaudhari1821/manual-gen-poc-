from typing import List, Dict
import json

from image_generation import llm
# =====================================================
# LLM CONFIGURATION
# =====================================================



# =====================================================
# VISUAL CONTEXT
# =====================================================

def build_visual_context(
    generated_content: str,
    extracted_parts: list[str]
):

    return {
        "procedure": generated_content.strip(),
        "components": extracted_parts,
        "component_count": len(extracted_parts),
        "has_components": bool(extracted_parts)
    }


# =====================================================
# PROMPT GENERATION
# =====================================================

def build_image_prompt(
    visual_context: dict
) -> str:

    if visual_context["has_components"]:

        prompt = f"""
Create an image prompt for a technical illustration.

Components:
{json.dumps(visual_context["components"], indent=2)}

Procedure:
{visual_context["procedure"]}

Return only the final image-generation prompt.
"""

    else:

        prompt = f"""
Create an image-generation prompt from this procedure.

Procedure:

{visual_context["procedure"]}

Requirements:
- Engineering manual style
- White background
- Isometric view
- Realistic components
- No text labels
- No arrows

Return only the image-generation prompt.
"""

    response = llm.invoke(prompt)

    generated_prompt = response.content.strip()

    if (
        not generated_prompt
        or len(generated_prompt) < 50
    ):
        generated_prompt = None
    if not generated_prompt:
        components = visual_context["components"]
        if components:
            generated_prompt = f"""

        
    Technical engineering illustration showing:
    {", ".join(visual_context["components"])}

    Engineering manual style.
    White background.
    Product assembly visualization.
    High detail.
    Isometric view.
    No text.
"""

    # Final fallback
    if not generated_prompt:

        generated_prompt = f"""
Technical engineering illustration showing:

{visual_context['procedure']}

White background,
engineering manual style,
product assembly visualization,
high detail,
isometric view,
no text.
"""

    print("\nIMAGE PROMPT GENERATED:\n")
    print(generated_prompt)

    return generated_prompt

# =====================================================
# IMAGE GENERATION
# =====================================================

import requests
from urllib.parse import quote


def generate_ai_image(
    image_prompt: str,
    output_file: str = "generated_image.png"
):

    url = (
        "https://image.pollinations.ai/prompt/"
        + quote(image_prompt)
    )

    response = requests.get(url)

    response.raise_for_status()

    with open(output_file, "wb") as f:
        f.write(response.content)

    return output_file


# =====================================================
# COMPLETE PIPELINE
# =====================================================

def generate_procedure_image(
    generated_content: str,
    extracted_parts: List[str],
    output_file: str = "generated_image.png"
):
    """
    Full image generation pipeline.
    """

    visual_context = build_visual_context(
        generated_content,
        extracted_parts
    )

    image_prompt = build_image_prompt(
        visual_context
    )

    print("\n============== IMAGE PROMPT ==============\n")
    print(image_prompt)

    image_path = generate_ai_image(
        image_prompt=image_prompt,
        output_file=output_file
    )

    return image_path


# =====================================================
# TESTING
# =====================================================

if __name__ == "__main__":

    generated_content = """
    Connect the belt to the drive pulley.
    Install the casing over the assembly.
    Secure the flange and wheel disc hub.
    """

    extracted_parts = [
        "belt",
        "drive pulley",
        "casing",
        "flange",
        "wheel disc hub"
    ]

    image_path = generate_procedure_image(
        generated_content=generated_content,
        extracted_parts=extracted_parts,
        output_file="test_image.png"

)
    print(
        f"\nImage generated successfully: {image_path}"
    )