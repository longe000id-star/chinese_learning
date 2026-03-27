# utils/search.py
import re
import streamlit as st

def search_in_dict(node, path_list, source, level_num, keyword):
    matches = []
    keyword_lower = keyword.lower()
    
    if not isinstance(node, dict):
        return matches
    
    if path_list:
        last_key = str(path_list[-1])
        if keyword_lower in last_key.lower():
            content_preview = last_key[:150]
            matches.append({
                "source": source,
                "level": level_num,
                "path": path_list.copy(),
                "type": "Category",
                "content": content_preview
            })

    if "name" in node and node["name"] and keyword_lower in str(node["name"]).lower():
        matches.append({
            "source": source,
            "level": level_num,
            "path": path_list.copy(),
            "type": "Section",
            "content": str(node["name"])[:150]
        })
    
    if "notes" in node and node["notes"] and keyword_lower in str(node["notes"]).lower():
        content = str(node["notes"])[:200] + "..." if len(str(node["notes"])) > 200 else str(node["notes"])
        matches.append({
            "source": source,
            "level": level_num,
            "path": path_list.copy(),
            "type": "Note",
            "content": content
        })
    
    if "examples" in node and node["examples"]:
        if isinstance(node["examples"], list):
            for idx, ex in enumerate(node["examples"]):
                if ex and keyword_lower in str(ex).lower():
                    matches.append({
                        "source": source,
                        "level": level_num,
                        "path": path_list.copy(),
                        "type": "Example",
                        "content": str(ex)[:150],
                        "index": idx
                    })
        elif isinstance(node["examples"], str) and keyword_lower in node["examples"].lower():
            matches.append({
                "source": source,
                "level": level_num,
                "path": path_list.copy(),
                "type": "Example",
                "content": node["examples"][:150]
            })
    
    if "vocabulary" in node and node["vocabulary"]:
        if isinstance(node["vocabulary"], list):
            for idx, item in enumerate(node["vocabulary"]):
                if item and keyword_lower in str(item).lower():
                    matches.append({
                        "source": source,
                        "level": level_num,
                        "path": path_list.copy(),
                        "type": "Vocabulary",
                        "content": str(item)[:150],
                        "index": idx
                    })
        elif isinstance(node["vocabulary"], str) and keyword_lower in node["vocabulary"].lower():
            matches.append({
                "source": source,
                "level": level_num,
                "path": path_list.copy(),
                "type": "Vocabulary",
                "content": node["vocabulary"][:150]
            })
    
    if "words" in node and node["words"] and keyword_lower in str(node["words"]).lower():
        content = str(node["words"])[:200] + "..." if len(str(node["words"])) > 200 else str(node["words"])
        matches.append({
            "source": source,
            "level": level_num,
            "path": path_list.copy(),
            "type": "Words",
            "content": content
        })
    
    for key, value in node.items():
        if key in ("name", "notes", "examples", "vocabulary", "words"):
            continue
        if isinstance(value, dict):
            matches.extend(search_in_dict(value, path_list + [key], source, level_num, keyword))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    matches.extend(search_in_dict(item, path_list + [f"{key}[{idx}]"], source, level_num, keyword))
    
    return matches


def deduplicate_results(results):
    seen = set()
    deduped = []
    for r in results:
        key = (r.get("source"), r.get("level"), tuple(r.get("path", [])), r.get("type"), r.get("content", "")[:50])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


def global_search(keyword, levels_data, nemt_cet_data):
    if not keyword.strip():
        return []
    
    results = []
    
    for level_num in range(1, 4):
        level_key = f"Level {level_num}"
        if level_key in levels_data:
            root_node = levels_data[level_key]
            for root_key, root_value in root_node.items():
                if isinstance(root_value, dict):
                    results.extend(search_in_dict(root_value, [root_key], "textbook", level_num, keyword))
    
    for exam_name, exam_data in nemt_cet_data.items():
        if not exam_data:
            continue
        
        data_to_search = exam_data
        if len(exam_data) == 1 and exam_name in exam_data:
            data_to_search = exam_data[exam_name]
        
        for key, value in data_to_search.items():
            if isinstance(value, dict):
                if keyword.lower() in str(key).lower():
                    results.append({
                        "source": "nemt_cet",
                        "exam": exam_name,
                        "level": None,
                        "path": [key],
                        "type": "Category",
                        "content": str(key)[:150]
                    })
                results.extend(search_in_dict(value, [key], "nemt_cet", exam_name, keyword))
    
    return deduplicate_results(results)


def local_search_textbook(keyword, level, levels_data):
    if not keyword.strip():
        return []
    if not level:
        return []
    
    results = []
    level_key = f"Level {level}"
    if level_key in levels_data:
        root_node = levels_data[level_key]
        for root_key, root_value in root_node.items():
            if isinstance(root_value, dict):
                results.extend(search_in_dict(root_value, [root_key], "textbook", level, keyword))
    return deduplicate_results(results)


def local_search_nemt_cet(keyword, selected_nemt_cet, nemt_cet_data):
    if not keyword.strip():
        return []
    if not selected_nemt_cet:
        st.warning("Please select an exam (TEM-8 / NEMT / CET-46) before using Local Search.")
        return []
    
    results = []
    exam_name = selected_nemt_cet
    exam_data = nemt_cet_data.get(exam_name, {})
    
    if not exam_data:
        return results
    
    data_to_search = exam_data
    if len(exam_data) == 1 and exam_name in exam_data:
        data_to_search = exam_data[exam_name]
    
    for key, value in data_to_search.items():
        if isinstance(value, dict):
            if keyword.lower() in str(key).lower():
                results.append({
                    "source": "nemt_cet",
                    "exam": exam_name,
                    "level": None,
                    "path": [key],
                    "type": "Category",
                    "content": str(key)[:150]
                })
            results.extend(search_in_dict(value, [key], "nemt_cet", exam_name, keyword))
    
    return deduplicate_results(results)


def local_search(keyword, current_mode, level, selected_nemt_cet, levels_data, nemt_cet_data):
    if current_mode == "textbook":
        return local_search_textbook(keyword, level, levels_data)
    elif current_mode == "nemt_cet":
        return local_search_nemt_cet(keyword, selected_nemt_cet, nemt_cet_data)
    return []