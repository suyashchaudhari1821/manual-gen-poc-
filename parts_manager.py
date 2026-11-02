"""
Parts Manager — Handle unique part naming for CAD assemblies
============================================================
Detects duplicate part names and renames them with numeric suffixes.
Maintains mappings between original and renamed parts.
"""

from collections import defaultdict
from typing import Dict, List, Tuple


class PartsManager:
    """
    Manages unique part naming for CAD assemblies.
    
    Behavior:
    - Traverses scene graph to collect all mesh parts
    - Detects duplicate names
    - Renames duplicates with numeric suffixes (_1, _2, etc.)
    - Stores mapping of original → renamed
    """
    
    def __init__(self):
        self.original_names: List[str] = []  # Original names from CAD
        self.unique_names: List[str] = []    # Renamed with numeric suffixes
        self.name_map: Dict[str, str] = {}   # original → renamed
        self.reverse_map: Dict[str, str] = {} # renamed → original
        self.occurrences: Dict[str, int] = {} # name → occurrence count
    
    def parse_and_rename_parts(self, parts_list: List[str]) -> List[str]:
        """
        Takes a list of part names and renames duplicates.
        
        Args:
            parts_list: List of original part names from CAD model
            
        Returns:
            List of unique renamed parts
            
        Example:
            Input:  ["BOLT", "BOLT", "BOLT", "WASHER", "DRIVE_PULLEY"]
            Output: ["BOLT_1", "BOLT_2", "BOLT_3", "WASHER_1", "DRIVE_PULLEY_1"]
        """
        self.original_names = parts_list
        self.occurrences = defaultdict(int)
        self.name_map = {}
        self.reverse_map = {}
        
        # Count occurrences of each name
        occurrence_count = defaultdict(int)
        for name in parts_list:
            occurrence_count[name] += 1
        
        # Rename duplicates with numeric suffix
        seen_counts = defaultdict(int)
        unique_names = []
        
        for original_name in parts_list:
            seen_counts[original_name] += 1
            count = seen_counts[original_name]
            total_occurrences = occurrence_count[original_name]
            
            # Always add _N suffix to ensure ALL parts have unique names
            # This is required for proper part selection in viewer and animations
            renamed = f"{original_name}_{count}"
            
            unique_names.append(renamed)
            self.name_map[original_name] = renamed
            self.reverse_map[renamed] = original_name
            self.occurrences[original_name] = total_occurrences
        
        self.unique_names = unique_names
        return unique_names
    
    def get_duplicate_report(self) -> Dict:
        """
        Returns a report of detected duplicate parts.
        
        Returns:
            {
                "duplicates": {
                    "BOLT": 3,
                    "WASHER": 2
                },
                "unique_count": 3,
                "duplicates_found": 2,
                "total_parts": 5
            }
        """
        duplicates = {name: count for name, count in self.occurrences.items() if count > 1}
        return {
            "duplicates": duplicates,
            "unique_count": len(set(self.original_names)),
            "duplicates_found": len(duplicates),
            "total_parts": len(self.original_names)
        }
    
    def get_renamed_mapping(self) -> Dict[str, str]:
        """
        Returns the full mapping of original → renamed parts.
        
        Returns:
            {"BOLT": "BOLT_1", "DRIVE_PULLEY": "DRIVE_PULLEY_1", ...}
        """
        return {
            orig: self.unique_names[i]
            for i, orig in enumerate(self.original_names)
        }
    
    def get_ui_parts_list(self) -> List[Tuple[str, str]]:
        """
        Returns a list of (renamed_name, original_name) for UI display.
        Useful for showing tooltips or original names.
        
        Returns:
            [("BOLT_1", "BOLT"), ("BOLT_2", "BOLT"), ("WASHER_1", "WASHER"), ...]
        """
        return [(renamed, self.reverse_map[renamed]) for renamed in self.unique_names]
    
    def find_by_unique_name(self, unique_name: str) -> str:
        """Find original name by unique renamed name."""
        return self.reverse_map.get(unique_name)
    
    def find_by_original_name(self, original_name: str) -> str:
        """Find first renamed name by original name."""
        for unique in self.unique_names:
            if self.reverse_map[unique] == original_name:
                return unique
        return None


def parse_gltf_scene_graph(scene_graph: Dict) -> List[str]:
    """
    Traverse a glTF scene graph and extract all mesh part names.
    
    This would be called after loading the glTF model to collect all
    mesh names from the scene hierarchy.
    
    Args:
        scene_graph: The glTF scene structure
        
    Returns:
        List of all mesh names in the scene
    """
    parts = []
    
    def traverse(node):
        """Recursively traverse node hierarchy."""
        if node is None:
            return
        
        # If node has a mesh, add its name
        if "name" in node and node.get("mesh") is not None:
            parts.append(node["name"])
        
        # Traverse children
        if "children" in node:
            for child_idx in node["children"]:
                if isinstance(child_idx, int):
                    # Note: In real implementation, need to look up child by index
                    pass
                else:
                    traverse(child_idx)
    
    # Start from root nodes
    if "nodes" in scene_graph:
        for node in scene_graph["nodes"]:
            traverse(node)
    
    return parts


if __name__ == "__main__":
    # Example usage
    manager = PartsManager()
    
    raw_parts = ["BOLT", "BOLT", "BOLT", "WASHER", "DRIVE_PULLEY", "CASING", "WASHER"]
    renamed = manager.parse_and_rename_parts(raw_parts)
    
    print("Original parts:", raw_parts)
    print("Renamed parts:", renamed)
    print("\nDuplicate report:")
    report = manager.get_duplicate_report()
    for key, val in report.items():
        print(f"  {key}: {val}")
    
    print("\nUI list (renamed, original):")
    for renamed_name, original_name in manager.get_ui_parts_list():
        print(f"  {renamed_name:20} ← {original_name}")
