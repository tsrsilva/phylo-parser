# SPDX-FileCopyrightText: 2026 Thiago S. R. Silva, Diego S. Porto
# SPDX-License-Identifier: MIT

########################
##### PHYLO PARSER #####
########################

# ======================================================
# IMPORTS
# ======================================================

import pandas as pd 
from rdflib import Graph, RDFS
import json
import yaml
import re
import csv
from pathlib import Path

import yaml
from pathlib import Path

# ======================================================
# HELPERS
# ======================================================

def none_if_empty(val):
    return None if val == "" else val

# ======================================================
# MAIN
# ======================================================

def main() -> None:
    """
    Main entry point for the phylo_parser pipeline.
    Processes all TXT files in the input directory and generates CSV/JSON outputs.
    """
    print("Starting phylo_parser pipeline...")
    
    # ---- Load configuration ---- #

    CONFIG_PATH = Path("configs/config.yaml")

    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    # Input
    DIR_DATA = Path(config["input"]["data_dir"])

    # Resources
    DIR_DICTS = Path(config["resources"]["dicts_dir"])

    # Output
    DIR_OUTPUT_CSV  = Path(config["output"]["csv_dir"])
    DIR_OUTPUT_JSON = Path(config["output"]["json_dir"])
    DIR_MISSING     = Path(config["output"]["missing_dir"])

    # Create output dirs if missing
    for d in [DIR_OUTPUT_CSV, DIR_OUTPUT_JSON, DIR_MISSING]:
        d.mkdir(parents=True, exist_ok=True)

    # ---- Load ontologies ---- #

    # Set base URL.
    obo_url = "http://purl.obolibrary.org/obo/"

    # Initialize RDF graphs.
    aism_g = Graph()
    hao_g = Graph()
    bspo_g = Graph()
    pato_g = Graph()

    # Parse base ontologies.
    aism_g.parse(obo_url + "aism.owl", format = "owl")
    hao_g.parse(obo_url + "hao.owl", format = "owl")
    bspo_g.parse(obo_url + "bspo.owl", format = "owl")
    pato_g.parse(obo_url + "pato.owl", format = "owl")

    def build_label_dict(graph):
        return {str(o): str(s) for s, _, o in graph.triples((None, RDFS.label, None))}

    aism_dict = build_label_dict(aism_g)
    hao_dict  = build_label_dict(hao_g)
    bspo_dict = build_label_dict(bspo_g)
    pato_dict = build_label_dict(pato_g)

    ent_dict = aism_dict | hao_dict | bspo_dict | pato_dict

    for name, dct in {
        "aism_dict": aism_dict,
        "hao_dict": hao_dict,
        "bspo_dict": bspo_dict,
        "pato_dict": pato_dict,
        "ent_dict": ent_dict
    }.items():
        with open(DIR_DICTS / f"{name}.json", "w") as f:
            json.dump(dct, f, indent=2)

    # ---- Load synonyms ---- #

    # Define a query to get all synonyms (:hasRelatedSynonym).
    syn_query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX oboI: <http://www.geneontology.org/formats/oboInOwl#>
    SELECT ?label ?term ?syn
    WHERE {
        ?term rdfs:label ?label .
        ?term oboI:hasRelatedSynonym ?syn .
    }
    """

    # Perform the SPARQL query.
    hao_syn = hao_g.query(syn_query)
    bspo_syn = bspo_g.query(syn_query)
    pato_syn = pato_g.query(syn_query)

    # Convert query results to a dictionary (for latter use).
    hao_syn_dict = {str(r.syn): str(r.term) for r in hao_syn}
    bspo_syn_dict = {str(r.syn): str(r.term) for r in bspo_syn}
    pato_syn_dict = {str(r.syn): str(r.term) for r in pato_syn}

    # Build composite dictionary for synonyms.
    syn_dict = bspo_syn_dict | hao_syn_dict

    # Write synonym dictionaries
    for name, dct in {
        "syn_dict": syn_dict,
        "hao_syn_dict": hao_syn_dict,
        "bspo_syn_dict": bspo_syn_dict,
        "pato_syn_dict": pato_syn_dict
    }.items():
        with open(DIR_DICTS / f"{name}.json", "w") as f:
            json.dump(dct, f, indent=2)

    # ======================================================
    # PER-FILE PROCESSOR
    # ======================================================

    def process_character_file(txt_path: Path):
        prefix = txt_path.stem
        print(f"Processing {prefix}")

        char_ls_dict = {}

        with open(txt_path, "r") as file:
            for line in file:
                char_id, char_rest = line.strip().split(".", 1)
                char_text, state_text = char_rest.strip().split(":", 1)

                char_text_s = [w.strip().lower() for w in char_text.split(",") if w.strip()]
                if not char_text_s:
                    continue

                char_text_d = {
                    "_organism": None,
                    "_locators": [],
                    "_variable": None
                }

                # 1️⃣ First term = organism
                organism_term = char_text_s[0]
                organism_id = ent_dict.get(organism_term) or syn_dict.get(organism_term, "")
                char_text_d["_organism"] = (organism_term, organism_id)

                # 2️⃣ Parse states first to detect neomorphic
                state_matches = re.findall(r'\s*([^\(\):;"]+?)\s*\((\d+)\)', state_text)
                state_dict = {}
                state_labels = []
                for state, token in state_matches:
                    pato_id = pato_dict.get(state) or pato_syn_dict.get(state, "")
                    state_dict[token] = {state: pato_id}
                    state_labels.append(state.lower())

                if {"absent", "present"} & set(state_labels):
                    # Neomorphic: all terms after organism → Locators; no Variable
                    for locator_term in char_text_s[1:]:
                        locator_id = ent_dict.get(locator_term) or syn_dict.get(locator_term, "")
                        char_text_d["_locators"].append((locator_term, locator_id))
                    tag = "neomorphic"
                else:
                    # Transformational: last term before colon → Variable
                    variable_term = char_text_s[-1]
                    match = re.match(r"^(.+?)\s*\[\s*(.+?)\s*\]$", variable_term)
                    if match:
                        # Transformational complex (Variable + comment)
                        label, comment = match.groups()
                        var_uri = ent_dict.get(label.strip())
                        char_text_d["_variable"] = [label.strip(), var_uri, comment.strip()]
                    else:
                        # Transformational simple (Variable without comment)
                        var_uri = ent_dict.get(variable_term) or syn_dict.get(variable_term, None)
                        char_text_d["_variable"] = [variable_term, var_uri, None]

                    # Terms between first and last → Locators
                    for locator_term in char_text_s[1:-1]:
                        locator_id = ent_dict.get(locator_term) or syn_dict.get(locator_term, "")
                        char_text_d["_locators"].append((locator_term, locator_id))

                    # Tag assignment
                    var = char_text_d["_variable"]
                    tag = "transformational_complex" if isinstance(var, list) and var[2] else "transformational_simple"

                char_ls_dict[char_id] = {
                    "char_part": char_text_d,
                    "state_part": state_dict,
                    "tag": tag
                }

        # ------------------ CHARACTER PART DF ------------------ #
        max_locators = max(len(data["char_part"]["_locators"]) for data in char_ls_dict.values())
        base_columns = ["Organism_label", "Organism_ID"]
        locator_columns = [f"Locator_{i}_{x}" for i in range(1, max_locators+1) for x in ("label", "ID")]
        variable_columns = ["Variable_label", "Variable_ID", "Variable_comment"]
        ALL_COLUMNS = base_columns + locator_columns + variable_columns

        char_dict_org = {}
        for char, data in char_ls_dict.items():
            row = {col: "" for col in ALL_COLUMNS}
            # Organism
            if data["char_part"]["_organism"]:
                row["Organism_label"], row["Organism_ID"] = data["char_part"]["_organism"]
            # Locators
            for i, (label, uri) in enumerate(data["char_part"]["_locators"], start=1):
                row[f"Locator_{i}_label"] = label
                row[f"Locator_{i}_ID"] = uri
            # Variable
            var = data["char_part"]["_variable"]
            if isinstance(var, list):
                row["Variable_label"] = var[0]
                row["Variable_ID"] = var[1]
                row["Variable_comment"] = var[2]
            char_dict_org[char] = row

        char_df = pd.DataFrame.from_dict(char_dict_org, orient="index").reindex(columns=ALL_COLUMNS).fillna("")
        char_df.to_csv(DIR_OUTPUT_CSV / f"{prefix}_char_part.csv", index=True, index_label="CH_ID")

        # ------------------ STATE PART DF ------------------ #
        state_dict_org = {}
        for char, data in char_ls_dict.items():
            lst = []
            for token, state in data["state_part"].items():
                lst += [*state.keys(), *state.values(), token]
            keys = [f"{x}_{i}" for i in range(1, len(lst)//3+1) for x in ("state_label", "state_ID", "token")]
            state_dict_org[char] = dict(zip(keys, lst))

        state_df = pd.DataFrame.from_dict(state_dict_org, orient="index").fillna("")
        state_df.to_csv(DIR_OUTPUT_CSV / f"{prefix}_state_part.csv", index=False)

        # ------------------ FULL DF ------------------ #
        final_df = pd.concat([char_df, state_df], axis=1)
        final_df["tag"] = [v["tag"] for v in char_ls_dict.values()]
        final_df.to_csv(DIR_OUTPUT_CSV / f"{prefix}_full.csv", index=True, index_label="Char_ID")

        # ------------------ JSON EXPORTS ------------------ #
        final_json = []
        for char_id, char_data in char_ls_dict.items():
            tag = char_data["tag"]
            row = final_df.loc[char_id]

            entry = {
                "Char_ID": char_id,
                "Organism": {
                    "Label": none_if_empty(row["Organism_label"]),
                    "URI": none_if_empty(row["Organism_ID"])
                },
                "Locators": []
            }
            # Locators
            for i, (label, uri) in enumerate(char_data["char_part"]["_locators"], start=1):
                entry["Locators"].append({
                    f"Locator {i} label": label,
                    f"Locator {i} URI": uri if uri else None
                })
            # Variable
            if tag != "neomorphic" and char_data["char_part"]["_variable"]:
                var_label, var_uri, var_comment = char_data["char_part"]["_variable"]
                entry["Variable"] = {
                    "Variable label": var_label,
                    "Variable URI": var_uri if var_uri else None,
                    **({"Variable comment": var_comment} if tag == "transformational_complex" else {})
                }
            # States
            entry["States"] = []
            for i, (token, state_dict) in enumerate(char_data["state_part"].items()):
                state_label, state_uri = list(state_dict.items())[0]
                entry["States"].append({
                    f"State {i} label": state_label if state_label else "",
                    f"State {i} URI": state_uri if state_uri else None,
                    f"State {i} token": token
                })
            # Tag
            entry["Tag"] = tag
            final_json.append(entry)

        with open(DIR_OUTPUT_JSON / f"{prefix}_full.json", "w") as f:
            json.dump(final_json, f, indent=2)

        # ------------------ MISSING TERMS ------------------ #
        missing = set()
        for _, row in final_df.iterrows():
            for col in final_df.columns:
                if "_ID" in col and row[col] == "":
                    label_col = col.replace("_ID", "_label")
                    if label_col in final_df.columns:
                        missing.add(row[label_col])

        with open(DIR_MISSING / f"{prefix}_missing_terms.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Missing term"])
            for term in sorted(missing):
                writer.writerow([term])
    
    # ---- Process all TXT files ---- #

    for txt_file in sorted(DIR_DATA.glob("*.txt")):
        process_character_file(txt_file)

# ======================================================
# RUN MAIN IF MODULE EXECUTED
# ======================================================

if __name__ == "__main__":
    main()

# ======================================================