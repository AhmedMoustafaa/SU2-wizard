"""
Reads the C++ source text of SetConfig_Options() and SetPostprocessing()
and enriches the options database with:
  - Corrected types  (addBoolOption, addDoubleOption, addEnumOption, etc.)
  - C++ defaults (overriding template-file guesses)
  - Incompatibility rules (from SU2_MPI::Error calls in SetPostprocessing)

Usage:
    python enricher.py \
        --db   data/options_db.yaml \
        --opts SetConfig_Options.cpp \
        --post SetPostprocessing.cpp \
        --out  data/options_db.yaml
"""
import re
import yaml
import argparse
from pathlib import Path


# Type mapping  C++ add*Option → wizard type string

ADD_FUNC_TO_TYPE = {
    "addBoolOption":          "bool",
    "addDoubleOption":        "float",
    "addDoubleListOption":    "list_float",
    "addDoubleArrayOption":   "array_float",
    "addUShortListOption":    "list_int",
    "addULongListOption":     "list_int",
    "addShortListOption":     "list_int",
    "addUnsignedShortOption": "int",
    "addUnsignedLongOption":  "int",
    "addLongOption":          "int",
    "addStringOption":        "string",
    "addStringListOption":    "list_string",
    "addEnumOption":          "enum",
    "addEnumListOption":      "list_enum",
    "addConvectOption":       "enum",        # convective scheme
    "addConvectFEMOption":    "enum",
    "addMathProblemOption":   "enum",
    "addPythonOption":        "python_only", # ignored by wizard
}

BOOL_DEFAULT_MAP = {
    "NO": "NO", "YES": "YES",
    "false": "NO", "true": "YES",
}


# Parser for SetConfig_Options()
# Pattern: addXxxOption("KEY", var, ..., DEFAULT, ...)
# Capture the function name, the quoted key, and the full argument list.
_ADD_PAT = re.compile(
    r'\badd(\w+Option)\s*\(\s*"([A-Z_0-9]+)"\s*,([^;]+)\);',
    re.DOTALL,
)

def _extract_default_from_args(func_name: str, args: str) -> str | None:
    """
    Try to extract the default value literal from the argument list.
    For most add*Option calls the default is the LAST scalar argument.
    """
    # Strip trailing whitespace / comments
    args = re.sub(r"//[^\n]*", "", args).strip().rstrip(",")

    # Split on top-level commas (not inside angle brackets or parens)
    parts = _split_top_level(args)
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return None

    if func_name in ("addBoolOption",):
        # Format: ("KEY", var, DEFAULT)
        # DEFAULT is last token
        raw = parts[-1]
        return BOOL_DEFAULT_MAP.get(raw, raw)

    if func_name in ("addDoubleOption", "addUnsignedShortOption",
                     "addUnsignedLongOption", "addLongOption"):
        raw = parts[-1]
        # Remove type casts like SU2_TYPE::Int(...)
        raw = re.sub(r'\w+::\w+\s*\(([^)]+)\)', r'\1', raw)
        return raw.strip()

    if func_name == "addStringOption":
        # addStringOption("KEY", var, string("default"))
        m = re.search(r'string\s*\(\s*"([^"]*)"\s*\)', args)
        if m:
            return m.group(1)

    if func_name == "addEnumOption":
        # Last token is the C++ enum default like TURB_MODEL::NONE or NONE
        raw = parts[-1]
        # Strip namespace prefix e.g. TURB_MODEL::NONE → NONE
        raw = re.sub(r'^.*::', '', raw).strip()
        return raw

    if func_name in ("addConvectOption", "addConvectFEMOption"):
        # Non-standard signature: ("KEY", KindConvScheme, KindCentered, KindUpwind)
        # No scalar default — keep the existing default from config_template
        return None

    return None


def _split_top_level(s: str) -> list[str]:
    """Split string on commas that are not inside <>, (), {}."""
    depth = 0
    current = []
    parts = []
    for ch in s:
        if ch in "(<{":
            depth += 1
        elif ch in ")>}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def parse_set_config_options(text: str) -> dict[str, dict]:
    """
    Returns dict: option_name → {type, default}
    """
    results = {}
    for m in _ADD_PAT.finditer(text):
        func_name = "add" + m.group(1)
        opt_name  = m.group(2)
        args      = m.group(3)

        opt_type = ADD_FUNC_TO_TYPE.get(func_name, "string")
        default  = _extract_default_from_args(func_name, args)

        results[opt_name] = {
            "type":    opt_type,
            "default": default,
        }
    return results


# ---------------------------------------------------------------------------
# Parser for SetPostprocessing() → incompatibility rules
# ---------------------------------------------------------------------------

# We extract structured rules from the SU2_MPI::Error calls.
# Each rule has:
#   - condition (human-readable)
#   - options involved
#   - error message (truncated)

# The raw rules are hand-extracted from the key Error() branches:
INCOMPATIBILITY_RULES = [
    {
        "id": "R01",
        "description": "NAVIER_STOKES requires KIND_TURB_MODEL= NONE",
        "when": {"SOLVER": ["NAVIER_STOKES"]},
        "conflicts_with": {"KIND_TURB_MODEL": ["SA", "SST"]},
        "message": "KIND_TURB_MODEL must be NONE if SOLVER= NAVIER_STOKES",
    },
    {
        "id": "R02",
        "description": "INC_NAVIER_STOKES requires KIND_TURB_MODEL= NONE",
        "when": {"SOLVER": ["INC_NAVIER_STOKES"]},
        "conflicts_with": {"KIND_TURB_MODEL": ["SA", "SST"]},
        "message": "KIND_TURB_MODEL must be NONE if SOLVER= INC_NAVIER_STOKES",
    },
    {
        "id": "R03",
        "description": "RANS requires a turbulence model",
        "when": {"SOLVER": ["RANS"]},
        "requires": {"KIND_TURB_MODEL": ["SA", "SST"]},
        "message": "A turbulence model must be specified with KIND_TURB_MODEL if SOLVER= RANS",
    },
    {
        "id": "R04",
        "description": "INC_RANS requires a turbulence model",
        "when": {"SOLVER": ["INC_RANS"]},
        "requires": {"KIND_TURB_MODEL": ["SA", "SST"]},
        "message": "A turbulence model must be specified with KIND_TURB_MODEL if SOLVER= INC_RANS",
    },
    {
        "id": "R05",
        "description": "Transition model requires a turbulence model",
        "when": {"KIND_TRANS_MODEL": ["LM"]},
        "requires": {"KIND_TURB_MODEL": ["SA", "SST"]},
        "message": "KIND_TURB_MODEL cannot be NONE to use a transition model",
    },
    {
        "id": "R06",
        "description": "Euler solvers only support slip walls (MARKER_EULER), not heat or CHT markers",
        "when": {"SOLVER": ["EULER", "INC_EULER", "FEM_EULER", "NEMO_EULER"]},
        "conflicts_with": {"MARKER_ISOTHERMAL": None, "MARKER_HEATFLUX": None,
                           "MARKER_HEATTRANSFER": None},
        "message": "Euler solvers are only compatible with slip walls (MARKER_EULER)",
    },
    {
        "id": "R07",
        "description": "SST COMPRESSIBILITY-SARKAR only for compressible RANS",
        "when": {"SOLVER": ["INC_RANS"]},
        "conflicts_with": {"SST_OPTIONS": ["COMPRESSIBILITY-SARKAR"]},
        "message": "COMPRESSIBILITY-SARKAR only supported for SOLVER= RANS",
    },
    {
        "id": "R08",
        "description": "SST COMPRESSIBILITY-WILCOX only for compressible RANS",
        "when": {"SOLVER": ["INC_RANS"]},
        "conflicts_with": {"SST_OPTIONS": ["COMPRESSIBILITY-WILCOX"]},
        "message": "COMPRESSIBILITY-WILCOX only supported for SOLVER= RANS",
    },
    {
        "id": "R09",
        "description": "CoolProp only with DIMENSIONAL non-dimensionalization",
        "when": {"FLUID_MODEL": ["COOLPROP"]},
        "requires": {"REF_DIMENSIONALIZATION": ["DIMENSIONAL"]},
        "message": "CoolProp can not be used with non-dimensionalization",
    },
    {
        "id": "R10",
        "description": "Harmonic Balance only for compressible EULER/NS/RANS",
        "when": {"TIME_MARCHING": ["HARMONIC_BALANCE"]},
        "conflicts_with": {"SOLVER": ["INC_EULER", "INC_NAVIER_STOKES", "INC_RANS"]},
        "message": "Harmonic Balance not yet implemented for the incompressible solver",
    },
    {
        "id": "R11",
        "description": "TIME_DOMAIN must be YES for unsteady TIME_MARCHING",
        "when": {"TIME_MARCHING": ["TIME_STEPPING", "DUAL_TIME_STEPPING-1ST_ORDER",
                                   "DUAL_TIME_STEPPING-2ND_ORDER"]},
        "requires": {"TIME_DOMAIN": ["YES"]},
        "message": "TIME_DOMAIN must be set to YES if TIME_MARCHING is TIME_STEPPING or DUAL_TIME_STEPPING",
    },
    {
        "id": "R12",
        "description": "INC_EULER must use CONSTANT density and no energy equation",
        "when": {"SOLVER": ["INC_EULER"]},
        "requires": {"INC_DENSITY_MODEL": ["CONSTANT"]},
        "message": "Inviscid incompressible problems must be constant density (no energy eqn.)",
    },
    {
        "id": "R13",
        "description": "Incompressible solvers must use SI units",
        "when": {"SOLVER": ["INC_EULER", "INC_NAVIER_STOKES", "INC_RANS"]},
        "conflicts_with": {"SYSTEM_MEASUREMENTS": ["US"]},
        "message": "Must use SI units for incompressible solver",
    },
    {
        "id": "R14",
        "description": "CONSTANT_DENSITY/INC_IDEAL_GAS/INC_IDEAL_GAS_POLY only for incompressible",
        "when": {"FLUID_MODEL": ["CONSTANT_DENSITY", "INC_IDEAL_GAS", "INC_IDEAL_GAS_POLY"]},
        "requires": {"SOLVER": ["INC_EULER", "INC_NAVIER_STOKES", "INC_RANS"]},
        "message": "Fluid model not compatible with compressible flows",
    },
    {
        "id": "R15",
        "description": "VARIABLE density model only with INC_IDEAL_GAS or INC_IDEAL_GAS_POLY",
        "when": {"INC_DENSITY_MODEL": ["VARIABLE"]},
        "requires": {"FLUID_MODEL": ["INC_IDEAL_GAS", "INC_IDEAL_GAS_POLY",
                                     "FLUID_MIXTURE", "FLUID_FLAMELET"]},
        "message": "Variable density incompressible solver limited to ideal gases",
    },
    {
        "id": "R16",
        "description": "FLUID_MIXTURE requires VARIABLE density model",
        "when": {"FLUID_MODEL": ["FLUID_MIXTURE"]},
        "requires": {"INC_DENSITY_MODEL": ["VARIABLE"]},
        "message": "The use of FLUID_MIXTURE requires the INC_DENSITY_MODEL option to be VARIABLE",
    },
    {
        "id": "R17",
        "description": "FLUID_MIXTURE requires SPECIES_TRANSPORT scalar model",
        "when": {"FLUID_MODEL": ["FLUID_MIXTURE"]},
        "requires": {"KIND_SCALAR_MODEL": ["SPECIES_TRANSPORT"]},
        "message": "The use of FLUID_MIXTURE requires the KIND_SCALAR_MODEL option to be SPECIES_TRANSPORT",
    },
    {
        "id": "R18",
        "description": "FLAMELET scalar model requires FLUID_FLAMELET fluid model",
        "when": {"KIND_SCALAR_MODEL": ["FLAMELET"]},
        "requires": {"FLUID_MODEL": ["FLUID_FLAMELET"]},
        "message": "The use of SCALAR_MODEL= FLAMELET requires the FLUID_MODEL option to be FLUID_FLAMELET",
    },
    {
        "id": "R19",
        "description": "FLUID_FLAMELET requires VARIABLE or FLAMELET density model",
        "when": {"FLUID_MODEL": ["FLUID_FLAMELET"]},
        "requires": {"INC_DENSITY_MODEL": ["VARIABLE", "FLAMELET"]},
        "message": "The use of FLUID_FLAMELET requires the INC_DENSITY_MODEL option to be VARIABLE or FLAMELET",
    },
    {
        "id": "R20",
        "description": "FLUID_FLAMELET requires FLAMELET conductivity model",
        "when": {"FLUID_MODEL": ["FLUID_FLAMELET"]},
        "requires": {"CONDUCTIVITY_MODEL": ["FLAMELET"]},
        "message": "The use of FLUID_FLAMELET requires the CONDUCTIVITY_MODEL option to be FLAMELET",
    },
    {
        "id": "R21",
        "description": "FLUID_FLAMELET requires FLAMELET viscosity model",
        "when": {"FLUID_MODEL": ["FLUID_FLAMELET"]},
        "requires": {"VISCOSITY_MODEL": ["FLAMELET"]},
        "message": "The use of FLUID_FLAMELET requires the VISCOSITY_MODEL option to be FLAMELET",
    },
    {
        "id": "R22",
        "description": "FLUID_FLAMELET requires FLAMELET diffusivity model",
        "when": {"FLUID_MODEL": ["FLUID_FLAMELET"]},
        "requires": {"DIFFUSIVITY_MODEL": ["FLAMELET"]},
        "message": "The use of FLUID_FLAMELET requires the DIFFUSIVITY_MODEL option to be FLAMELET",
    },
    {
        "id": "R23",
        "description": "Non-ideal gas: only ROE, HLLC (upwind) or JST (centered) allowed",
        "when": {"FLUID_MODEL": ["VW_GAS", "PR_GAS", "COOLPROP", "DATADRIVEN_FLUID"]},
        "allowed_conv": ["ROE", "HLLC", "JST"],
        "message": "Only ROE Upwind, HLLC Upwind, and JST can be used for Non-Ideal Compressible Fluids",
    },
    {
        "id": "R24",
        "description": "DATADRIVEN_FLUID only for compressible flows",
        "when": {"FLUID_MODEL": ["DATADRIVEN_FLUID"]},
        "conflicts_with": {"SOLVER": ["INC_EULER", "INC_NAVIER_STOKES", "INC_RANS"]},
        "message": "Data-driven fluid model can only be used for compressible flows",
    },
    {
        "id": "R25",
        "description": "POLYNOMIAL viscosity/conductivity only for incompressible",
        "when": {"VISCOSITY_MODEL": ["POLYNOMIAL_VISCOSITY"]},
        "requires": {"SOLVER": ["INC_EULER", "INC_NAVIER_STOKES", "INC_RANS"]},
        "message": "POLYNOMIAL_VISCOSITY and POLYNOMIAL_CONDUCTIVITY are for incompressible only currently",
    },
    {
        "id": "R26",
        "description": "CFL_ADAPT not available for TIME_STEPPING",
        "when": {"CFL_ADAPT": ["YES"]},
        "conflicts_with": {"TIME_MARCHING": ["TIME_STEPPING"]},
        "message": "CFL adaption not available for TIME_STEPPING integration",
    },
    {
        "id": "R27",
        "description": "CFL_ADAPT factor down must be < 1.0",
        "when": {"CFL_ADAPT": ["YES"]},
        "note": "CFL_ADAPT_PARAM[0] (factor down) must be < 1.0; CFL_ADAPT_PARAM[1] (factor up) must be > 1.0",
    },
    {
        "id": "R28",
        "description": "STREAMWISE_PERIODIC only for incompressible flow",
        "when": {"KIND_STREAMWISE_PERIODIC": ["PRESSURE_DROP", "MASSFLOW"]},
        "requires": {"SOLVER": ["INC_EULER", "INC_NAVIER_STOKES", "INC_RANS"]},
        "message": "Streamwise Periodic Flow currently only implemented for incompressible flow",
    },
    {
        "id": "R29",
        "description": "STREAMWISE_PERIODIC requires INC_NONDIM= DIMENSIONAL",
        "when": {"KIND_STREAMWISE_PERIODIC": ["PRESSURE_DROP", "MASSFLOW"]},
        "requires": {"INC_NONDIM": ["DIMENSIONAL"]},
        "message": "Streamwise Periodicity only works with INC_NONDIM= DIMENSIONAL",
    },
    {
        "id": "R30",
        "description": "MUSCL_ADJTURB= YES not supported",
        "when": {"MUSCL_ADJTURB": ["YES"]},
        "message": "MUSCL_ADJTURB= YES not currently supported. Please select MUSCL_ADJTURB= NO",
    },
    {
        "id": "R31",
        "description": "Centered schemes do not use MUSCL reconstruction",
        "when": {"CONV_NUM_METHOD_FLOW": ["JST", "JST_KE", "JST_MAT", "LAX-FRIEDRICH"]},
        "conflicts_with": {"MUSCL_FLOW": ["YES"]},
        "message": "Centered schemes do not use MUSCL reconstruction (use MUSCL_FLOW= NO)",
    },
    {
        "id": "R32",
        "description": "LEAST_SQUARES not allowed for viscous/source gradient method",
        "when": {"NUM_METHOD_GRAD": ["LEAST_SQUARES"]},
        "message": "LEAST_SQUARES gradient method not allowed for viscous / source terms. Use WEIGHTED_LEAST_SQUARES or GREEN_GAUSS",
    },
    {
        "id": "R33",
        "description": "Species transport only for viscous (compressible or incompressible NS/RANS)",
        "when": {"KIND_SCALAR_MODEL": ["SPECIES_TRANSPORT", "FLAMELET"]},
        "requires": {"SOLVER": ["INC_NAVIER_STOKES", "INC_RANS", "NAVIER_STOKES", "RANS",
                                 "DISC_ADJ_INC_NAVIER_STOKES", "DISC_ADJ_INC_RANS",
                                 "DISC_ADJ_NAVIER_STOKES", "DISC_ADJ_RANS"]},
        "message": "Species transport currently only available for viscous flow solvers",
    },
    {
        "id": "R34",
        "description": "Reynolds number required for NS/RANS when INIT_OPTION= REYNOLDS",
        "when": {"INIT_OPTION": ["REYNOLDS"], "SOLVER": ["NAVIER_STOKES", "RANS"]},
        "note": "REYNOLDS_NUMBER must be > 0",
    },
    {
        "id": "R35",
        "description": "Giles BCs only with turbomachinery markers",
        "note": "MARKER_GILES requires MARKER_TURBOMACHINERY to be set",
    },
    {
        "id": "R36",
        "description": "VORTICITY_CONFINEMENT not supported for incompressible or NEMO or axisymmetric",
        "when": {"VORTICITY_CONFINEMENT": ["YES"]},
        "conflicts_with": {"SOLVER": ["INC_EULER", "INC_NAVIER_STOKES", "INC_RANS",
                                       "NEMO_EULER", "NEMO_NAVIER_STOKES"]},
        "message": "Vorticity confinement feature currently not supported for incompressible or non-equilibrium model",
    },
    {
        "id": "R37",
        "description": "Only STANDARD_AIR fluid model with US measurement system",
        "when": {"SYSTEM_MEASUREMENTS": ["US"]},
        "requires": {"FLUID_MODEL": ["STANDARD_AIR"]},
        "message": "Only STANDARD_AIR fluid model can be used with US Measurement System",
    },
    {
        "id": "R38",
        "description": "INC_NAVIER_STOKES/INC_RANS with Sutherland viscosity requires INC_IDEAL_GAS",
        "when": {"SOLVER": ["INC_NAVIER_STOKES", "INC_RANS"],
                 "VISCOSITY_MODEL": ["SUTHERLAND"]},
        "requires": {"FLUID_MODEL": ["INC_IDEAL_GAS", "INC_IDEAL_GAS_POLY", "FLUID_MIXTURE"]},
        "message": "Sutherland's law only valid for ideal gases in incompressible flows",
    },
    {
        "id": "R39",
        "description": "SURFACE_MOVEMENT count must match MARKER_MOVING count",
        "note": "Number of SURFACE_MOVEMENT entries must equal number of MARKER_MOVING entries",
    },
    {
        "id": "R40",
        "description": "REF_ORIGIN_MOMENT_X/Y/Z must all have same length",
        "note": "REF_ORIGIN_MOMENT_X, REF_ORIGIN_MOMENT_Y, and REF_ORIGIN_MOMENT_Z must have equal lengths",
    },
]


# ---------------------------------------------------------------------------
# Enrich the YAML database
# ---------------------------------------------------------------------------

def enrich_db(yaml_path: str, cfg_ops_text: str, post_text: str, out_path: str) -> None:
    print(f"[enricher] Loading {yaml_path} ...")
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    options: dict = data["options"]

    # ── Step 1: Parse SetConfig_Options() ───────────────────────────────────
    print("[enricher] Parsing SetConfig_Options() ...")
    cpp_meta = parse_set_config_options(cfg_ops_text)
    print(f"           Found {len(cpp_meta)} option registrations")

    updated_type = 0
    updated_default = 0
    skipped_python = 0

    for name, meta in cpp_meta.items():
        if meta["type"] == "python_only":
            skipped_python += 1
            continue

        if name not in options:
            # New option not in template — add it
            options[name] = {
                "section": "ADDITIONAL",
                "description": "(registered in CConfig but not in config_template.cfg)",
                "default": meta["default"] or "",
                "type": meta["type"],
            }
            continue

        # Update type if the C++ source gives a more specific answer
        existing_type = options[name].get("type", "string")
        new_type = meta["type"]

        # Only override if the new type is more specific
        if existing_type in ("string", "float") and new_type != "string":
            options[name]["type"] = new_type
            updated_type += 1
        elif existing_type == "string" and new_type == "string":
            pass  # no change
        elif new_type != existing_type and new_type != "string":
            options[name]["type"] = new_type
            updated_type += 1

        # Update default if C++ has a concrete value
        if meta["default"] is not None and meta["default"] != "":
            old_default = options[name].get("default", "")
            new_default = meta["default"]
            # Normalize bool defaults
            if new_default in ("NO", "YES", "false", "true"):
                new_default = BOOL_DEFAULT_MAP.get(new_default, new_default)
            options[name]["default"] = new_default
            if str(old_default) != str(new_default):
                updated_default += 1

    print(f"           Updated {updated_type} types, {updated_default} defaults, "
          f"skipped {skipped_python} python-only options")

    # ── Step 2: Inject incompatibility rules ────────────────────────────────
    print("[enricher] Injecting incompatibility rules ...")
    data["incompatibility_rules"] = INCOMPATIBILITY_RULES

    # Also annotate individual options with rule IDs that reference them
    for rule in INCOMPATIBILITY_RULES:
        involved_options = set()
        for key in ("when", "requires", "conflicts_with", "allowed_conv"):
            if key in rule and isinstance(rule[key], dict):
                involved_options.update(rule[key].keys())
        for opt_name in involved_options:
            if opt_name in options:
                rules_list = options[opt_name].setdefault("incompatibility_rules", [])
                if rule["id"] not in rules_list:
                    rules_list.append(rule["id"])

    # ── Step 3: Write out ────────────────────────────────────────────────────
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    n_rules = len(INCOMPATIBILITY_RULES)
    print(f"[enricher] Written → {out_path}  "
          f"({len(options)} options, {n_rules} incompatibility rules)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Enrich options_db.yaml with Phase 2 data")
    ap.add_argument("--db",   required=True, help="Input options_db.yaml path")
    ap.add_argument("--opts", required=True, help="File containing SetConfig_Options() text")
    ap.add_argument("--post", required=True, help="File containing SetPostprocessing() text")
    ap.add_argument("--out",  required=True, help="Output options_db.yaml path")
    args = ap.parse_args()

    cfg_text  = Path(args.opts).read_text(encoding="utf-8")
    post_text = Path(args.post).read_text(encoding="utf-8")

    enrich_db(args.db, cfg_text, post_text, args.out)
