#!/usr/bin/env python3
import re
import json

def parse_markdown_tables(filepath):
    destinations = []
    current_section = ""
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Keep track of section headers (e.g., Highest-value picks...)
        if line.startswith("## "):
            current_section = line.replace("## ", "").strip()
            continue
            
        if line.startswith("|") and not line.startswith("|-"):
            # Split cells
            cells = [c.strip() for c in line.split("|")[1:-1]]
            
            # Skip header row or separator row
            if not cells or "Place" in cells[0] or "---" in cells[0]:
                continue
                
            # Parse destination row
            if len(cells) >= 7:
                # Strip markdown bolding from Place
                place_raw = cells[0]
                place_clean = re.sub(r'\*\*+', '', place_raw).strip()
                
                # Split place and region if applicable (e.g. "Ranganathittu, Karnataka" -> "Ranganathittu", "Karnataka")
                place_parts = [p.strip() for p in place_clean.split(",")]
                name = place_parts[0]
                state = place_parts[1] if len(place_parts) > 1 else ""
                
                best_time = cells[1]
                ease_raw = cells[2]
                transit = cells[3]
                expect = cells[4]
                birding = cells[5]
                wildlife = cells[6]
                
                ease_parts = [p.strip() for p in ease_raw.split("/")]
                ease_get = ease_parts[0] if len(ease_parts) > 0 else ""
                ease_stay = ease_parts[1] if len(ease_parts) > 1 else ""
                
                destinations.append({
                    "name": name,
                    "state": state,
                    "best_time": best_time,
                    "ease_get": ease_get,
                    "ease_stay": ease_stay,
                    "transit": transit,
                    "expect": expect,
                    "birding": birding,
                    "wildlife": wildlife,
                    "section": current_section
                })
                
    return destinations

if __name__ == "__main__":
    import sys
    filepath = "destinations.md"
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    parsed_data = parse_markdown_tables(filepath)
    print(json.dumps(parsed_data, indent=2))
