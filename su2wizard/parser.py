"""
Parses config_template.cfg and option_structure.hpp to produce options_db.yaml.

Usage:
    from su2wizard.parser import build_options_db
    build_options_db("config_template.cfg", "option_structure.hpp", "data/options_db.yaml")
"""

import re
import yaml
from pathlib import Path

def _clean_desc(lines: list[str]) -> str:
    """Join and clean a list of raw comment lines into a readable description."""
    parts = []
    for line in lines:
        # strip leading '%' and whitespace
        stripped = re.sub(r"^%+\s*", "", line).strip()
        if stripped:
            parts.append(stripped)
    return " ".join(parts)


def _infer_type(default_value: str, desc: str, choices: list[str]) -> str:
    """Guess the option type from its default value and context."""
    if choices:
        return "enum"
    v = default_value.strip().upper()
    if v in ("YES", "NO"):
        return "bool"
    if v.startswith("("):
        return "list"
    try:
        int(v)
        return "int"
    except ValueError:
        pass
    try:
        float(v.replace("E", "e"))
        return "float"
    except ValueError:
        pass
    return "string"


# Step 1: Parse config_template.cfg

SECTION_RE = re.compile(r"^%\s*-{5,}(.+?)-{5,}%?\s*$")
OPTION_RE  = re.compile(r"^([A-Z][A-Z0-9_]+)\s*=\s*(.*)$")

def parse_config_template(path: str) -> dict:
    """
    Returns a dict keyed by option name:
        {
            "SOLVER": {
                "default": "EULER",
                "section": "DIRECT, ADJOINT, AND LINEARIZED PROBLEM DEFINITION",
                "description": "...",
                "inline_choices": ["EULER", "NAVIER_STOKES", ...]
            },
            ...
        }
    """
    options = {}
    current_section = "GENERAL"
    pending_comments = []

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        raw = lines[i].rstrip("\n")
        stripped = raw.strip()

        # Section header
        m = SECTION_RE.match(stripped)
        if m:
            current_section = m.group(1).strip(" -%")
            pending_comments = []
            i += 1
            continue

        # Comment line → accumulate for the next option
        if stripped.startswith("%"):
            pending_comments.append(stripped)
            i += 1
            continue

        # Blank line → reset accumulated comments
        if stripped == "":
            pending_comments = []
            i += 1
            continue

        # Option definition
        m = OPTION_RE.match(stripped)
        if m:
            name = m.group(1)
            default = m.group(2).strip()

            # Build description from accumulated comments
            desc = _clean_desc(pending_comments)

            # Extract inline choices like "(EULER, NAVIER_STOKES, ...)"
            inline_choices = _extract_inline_choices(desc)

            options[name] = {
                "default": default,
                "section": current_section,
                "description": desc,
                "inline_choices": inline_choices,
            }
            pending_comments = []
            i += 1
            continue

        pending_comments = []
        i += 1

    return options


def _extract_inline_choices(desc: str) -> list[str]:
    """
    Pull enum values from parenthesised lists in descriptions.
    E.g. "(EULER, NAVIER_STOKES, RANS, ...)" → ["EULER", "NAVIER_STOKES", "RANS"]
    Only keeps tokens that look like SU2 keywords (ALL_CAPS with optional _).
    """
    choices = []
    # Find all parenthesised groups
    for m in re.finditer(r"\(([^)]+)\)", desc):
        tokens = [t.strip().rstrip(",") for t in m.group(1).split(",")]
        for t in tokens:
            # Keep only ALL_CAPS tokens (SU2 enum values)
            if re.match(r"^[A-Z][A-Z0-9_\-]+$", t) and len(t) > 1:
                choices.append(t)
    return list(dict.fromkeys(choices))  # deduplicate while preserving order

# Step 2: Parse option_structure.hpp  (MapType definitions)
def parse_option_structure(path: str) -> dict:
    """
    Returns a dict mapping option-string values to their enum name, grouped
    by map variable name:
        {
            "Solver_Map": ["NONE", "EULER", "NAVIER_STOKES", ...],
            "Turb_Model_Map": ["NONE", "SA", "SST"],
            ...
        }
    """
    maps = {}
    current_map = None

    with open(path, encoding="utf-8") as f:
        content = f.read()

    # Match each MapType definition block
    # Pattern: static const MapType<...> SomeName_Map = { MakePair("VALUE", ...) ... };
    map_block_re = re.compile(
        r'static\s+const\s+MapType\s*<[^>]+>\s*(\w+)\s*=\s*\{([^}]+)\}',
        re.DOTALL
    )
    make_pair_re = re.compile(r'MakePair\(\s*"([^"]+)"')

    for block in map_block_re.finditer(content):
        map_name = block.group(1)
        body = block.group(2)
        values = make_pair_re.findall(body)
        if values:
            maps[map_name] = values

    return maps


# Step 3: Build the mapping from option name → enum map

# Hand-curated: which option uses which Map from option_structure.hpp
OPTION_TO_MAP = {
    "SOLVER":                        "Solver_Map",
    "KIND_TURB_MODEL":               "Turb_Model_Map",
    "KIND_TRANS_MODEL":              "TransModel_Map",
    "KIND_SGS_MODEL":                "SGSModel_Map",
    "FLUID_MODEL":                   "FluidModel_Map",
    "GAS_MODEL":                     "GasModel_Map",
    "VISCOSITY_MODEL":               "ViscosityModel_Map",
    "CONDUCTIVITY_MODEL":            "ConductivityModel_Map",
    "TURBULENT_CONDUCTIVITY_MODEL":  "TurbConductivityModel_Map",
    "DIFFUSIVITY_MODEL":             "Diffusivity_Model_Map",
    "MIXING_VISCOSITY_MODEL":        "MixingViscosityModel_Map",
    "INC_DENSITY_MODEL":             "DensityModel_Map",
    "INIT_OPTION":                   "InitOption_Map",
    "FREESTREAM_OPTION":             "FreeStreamOption_Map",
    "REF_DIMENSIONALIZATION":        "NonDim_Map",
    "GRID_MOVEMENT":                 "GridMovement_Map",
    "SURFACE_MOVEMENT":              "SurfaceMovement_Map",
    "GUST_TYPE":                     "Gust_Type_Map",
    "GUST_DIR":                      "Gust_Dir_Map",
    "CONV_NUM_METHOD_FLOW":          "Upwind_Map",    # merged with Centered_Map below
    "CONV_NUM_METHOD_TURB":          "Upwind_Map",
    "CONV_NUM_METHOD_SPECIES":       "Upwind_Map",
    "SLOPE_LIMITER_FLOW":            "Limiter_Map",
    "SLOPE_LIMITER_TURB":            "Limiter_Map",
    "SLOPE_LIMITER_ADJFLOW":         "Limiter_Map",
    "SLOPE_LIMITER_ADJTURB":         "Limiter_Map",
    "SLOPE_LIMITER_SPECIES":         "Limiter_Map",
    "LINEAR_SOLVER":                 "Linear_Solver_Map",
    "LINEAR_SOLVER_PREC":            "Linear_Solver_Prec_Map",
    "DISCADJ_LIN_SOLVER":            "Linear_Solver_Map",
    "DISCADJ_LIN_PREC":              "Linear_Solver_Prec_Map",
    "MATH_PROBLEM":                  "MathProblem_Map",
    "TIME_MARCHING":                 "TimeMarching_Map",
    "SYSTEM_MEASUREMENTS":           "Measurements_Map",
    "MULTIZONE_SOLVER":              "Multizone_Map",
    "TURBOMACHINERY_KIND":           "TurboMachineType_Map",
    "MIXINGPLANE_INTERFACE_KIND":    "MixingPlaneInterface_Map",
    "AVERAGE_PROCESS_KIND":          "MixedOut_Map",
    "PERFORMANCE_AVERAGE_PROCESS_KIND": "MixedOut_Map",
    "RADIATION_MODEL":               "Radiation_Map",
    "KIND_SCALAR_MODEL":             "ScalarTransportModel_Map",
    "INTERPOLATION_METHOD":          "DataDrivenMethod_Map",
    "HYBRID_RANSLES":                "HybridRansLes_Map",
    "NUM_METHOD_GRAD":               "Gradient_Map",
    "NUM_METHOD_GRAD_RECON":         "Gradient_Map",
    "TIME_DISCRE_FLOW":              "TimeInt_Map",
    "TIME_DISCRE_SPECIES":           "TimeInt_Map",
    "OBJECTIVE_FUNCTION":            "Obj_Map",
    "KIND_INTERPOLATION":            "Interpolator_Map",
    "KIND_RADIAL_BASIS_FUNCTION":    "RadialBasisFunction_Map",
    "INLET_TYPE":                    "Inlet_Map",
    "ACTDISK_TYPE":                  "ActDisk_Map",
    "ACTDISK_JUMP":                  "Jump_Map",
    "WINDOW_FUNCTION":               "Window_Map",
    "INC_INLET_TYPE":                "IncInlet_Map",
    "INC_OUTLET_TYPE":               "IncOutlet_Map",
    "MARKER_ANALYZE_AVERAGE":        "Average_Map",
    "MGCYCLE":                       "MG_Cycle_Map",
    "ROE_LOW_DISSIPATION":           "RoeLowDiss_Map",
    "STRUCT_DEFORMATION":            "Struct_Map",
    "MATERIAL_MODEL":                "Material_Map",
    "MATERIAL_COMPRESSIBILITY":      "MatComp_Map",
    "KIND_STREAMWISE_PERIODIC":      "StreamwisePeriodic_Map",
    "BASIS_GENERATION":              "POD_Map",
    "NUM_METHOD_FEM_FLOW":           "FEM_Map",
    "RIEMANN_SOLVER_FEM":            "Upwind_Map",
    "ADER_PREDICTOR":                "Ader_Predictor_Map",
    "KIND_FEM_DG_SHOCK":             "ShockCapturingDG_Map",
    "KIND_MATRIX_COLORING":          "MatrixColoring_Map",
    "KIND_MUSCL_RAMP":               "MUSCLRamp_Map",
    "P1_INITIALIZATION":             "Radiation_P1_Init_Map",
}


# Step 4: Solver-context dependency map (for wizard branching)

COMPRESSIBLE_SOLVERS = [
    "EULER", "NAVIER_STOKES", "RANS",
    "FEM_EULER", "FEM_NAVIER_STOKES", "FEM_RANS", "FEM_LES",
    "NEMO_EULER", "NEMO_NAVIER_STOKES",
    "DISC_ADJ_EULER", "DISC_ADJ_NAVIER_STOKES", "DISC_ADJ_RANS",
]
INCOMPRESSIBLE_SOLVERS = [
    "INC_EULER", "INC_NAVIER_STOKES", "INC_RANS",
    "DISC_ADJ_INC_EULER", "DISC_ADJ_INC_NAVIER_STOKES", "DISC_ADJ_INC_RANS",
]
VISCOUS_SOLVERS = [
    "NAVIER_STOKES", "RANS",
    "INC_NAVIER_STOKES", "INC_RANS",
    "FEM_NAVIER_STOKES", "FEM_RANS", "FEM_LES",
    "NEMO_NAVIER_STOKES",
    "DISC_ADJ_NAVIER_STOKES", "DISC_ADJ_RANS",
    "DISC_ADJ_INC_NAVIER_STOKES", "DISC_ADJ_INC_RANS",
]
RANS_SOLVERS = ["RANS", "INC_RANS", "FEM_RANS", "DISC_ADJ_RANS", "DISC_ADJ_INC_RANS"]
FEM_SOLVERS  = ["FEM_EULER", "FEM_NAVIER_STOKES", "FEM_RANS", "FEM_LES"]
NEMO_SOLVERS = ["NEMO_EULER", "NEMO_NAVIER_STOKES"]

# Map: option_name → list of solver families that make it relevant
OPTION_REQUIRES_SOLVER_FAMILY = {
    # Turbulence
    "KIND_TURB_MODEL":      RANS_SOLVERS,
    "SST_OPTIONS":          RANS_SOLVERS,
    "SA_OPTIONS":           RANS_SOLVERS,
    "KIND_TRANS_MODEL":     RANS_SOLVERS,
    "LM_OPTIONS":           RANS_SOLVERS,
    "HROUGHNESS":           RANS_SOLVERS,
    "KIND_SGS_MODEL":       FEM_SOLVERS,
    "HYBRID_RANSLES":       RANS_SOLVERS,
    "DES_CONST":            RANS_SOLVERS,
    # Compressible free-stream
    "MACH_NUMBER":          COMPRESSIBLE_SOLVERS,
    "AOA":                  COMPRESSIBLE_SOLVERS,
    "SIDESLIP_ANGLE":       COMPRESSIBLE_SOLVERS,
    "REYNOLDS_NUMBER":      COMPRESSIBLE_SOLVERS,
    "REYNOLDS_LENGTH":      COMPRESSIBLE_SOLVERS,
    "FREESTREAM_PRESSURE":  COMPRESSIBLE_SOLVERS,
    "FREESTREAM_TEMPERATURE": COMPRESSIBLE_SOLVERS,
    "FREESTREAM_DENSITY":   COMPRESSIBLE_SOLVERS,
    "FREESTREAM_VISCOSITY": VISCOUS_SOLVERS,
    "FREESTREAM_TURBULENCEINTENSITY": RANS_SOLVERS,
    "FREESTREAM_TURB2LAMVISCRATIO":   RANS_SOLVERS,
    "REF_DIMENSIONALIZATION": COMPRESSIBLE_SOLVERS,
    # Incompressible free-stream
    "INC_DENSITY_MODEL":    INCOMPRESSIBLE_SOLVERS,
    "INC_ENERGY_EQUATION":  INCOMPRESSIBLE_SOLVERS,
    "INC_DENSITY_INIT":     INCOMPRESSIBLE_SOLVERS,
    "INC_VELOCITY_INIT":    INCOMPRESSIBLE_SOLVERS,
    "INC_TEMPERATURE_INIT": INCOMPRESSIBLE_SOLVERS,
    "INC_NONDIM":           INCOMPRESSIBLE_SOLVERS,
    "INC_DENSITY_REF":      INCOMPRESSIBLE_SOLVERS,
    "INC_VELOCITY_REF":     INCOMPRESSIBLE_SOLVERS,
    "INC_TEMPERATURE_REF":  INCOMPRESSIBLE_SOLVERS,
    "INC_INLET_TYPE":       INCOMPRESSIBLE_SOLVERS,
    "INC_OUTLET_TYPE":      INCOMPRESSIBLE_SOLVERS,
    "INC_INLET_DAMPING":    INCOMPRESSIBLE_SOLVERS,
    "INC_OUTLET_DAMPING":   INCOMPRESSIBLE_SOLVERS,
    "BULK_MODULUS":         INCOMPRESSIBLE_SOLVERS,
    "BETA_FACTOR":          INCOMPRESSIBLE_SOLVERS,
    # Viscosity / Conductivity
    "VISCOSITY_MODEL":      VISCOUS_SOLVERS,
    "MU_CONSTANT":          VISCOUS_SOLVERS,
    "MU_REF":               VISCOUS_SOLVERS,
    "MU_T_REF":             VISCOUS_SOLVERS,
    "SUTHERLAND_CONSTANT":  VISCOUS_SOLVERS,
    "MU_POLYCOEFFS":        VISCOUS_SOLVERS,
    "CONDUCTIVITY_MODEL":   VISCOUS_SOLVERS,
    "PRANDTL_LAM":          VISCOUS_SOLVERS,
    "PRANDTL_TURB":         RANS_SOLVERS,
    "TURBULENT_CONDUCTIVITY_MODEL": RANS_SOLVERS,
    # NEMO
    "GAS_MODEL":            NEMO_SOLVERS,
    "GAS_COMPOSITION":      NEMO_SOLVERS,
    "FROZEN_MIXTURE":       NEMO_SOLVERS,
    "IONIZATION":           NEMO_SOLVERS,
    "VT_RESIDUAL_LIMITING": NEMO_SOLVERS,
    "INLET_TEMPERATURE_VE": NEMO_SOLVERS,
    "INLET_GAS_COMPOSITION":NEMO_SOLVERS,
    "FREESTREAM_TEMPERATURE_VE": NEMO_SOLVERS,
    # FEM-specific
    "NUM_METHOD_FEM_FLOW":  FEM_SOLVERS,
    "RIEMANN_SOLVER_FEM":   FEM_SOLVERS,
    "TIME_DISCRE_FEM_FLOW": FEM_SOLVERS,
    "QUADRATURE_FACTOR_STRAIGHT_FEM": FEM_SOLVERS,
    "QUADRATURE_FACTOR_CURVED_FEM":   FEM_SOLVERS,
    "THETA_INTERIOR_PENALTY_DG_FEM":  FEM_SOLVERS,
    "USE_LUMPED_MASSMATRIX_DGFEM":    FEM_SOLVERS,
    "JACOBIAN_SPATIAL_DISCRETIZATION_ONLY": FEM_SOLVERS,
    "ALIGNED_BYTES_MATMUL": FEM_SOLVERS,
    "TIME_DOFS_ADER_DG":    FEM_SOLVERS,
    "ADER_PREDICTOR":       FEM_SOLVERS,
    "LEVELS_TIME_ACCURATE_LTS": FEM_SOLVERS,
    "KIND_MATRIX_COLORING": FEM_SOLVERS,
    "KIND_FEM_DG_SHOCK":    FEM_SOLVERS,
}

# Wizard sections: ordered list of (section_label, [option_keys_in_order])
WIZARD_STAGES = [
    ("Problem Definition", [
        "SOLVER", "MATH_PROBLEM", "SYSTEM_MEASUREMENTS",
        "AXISYMMETRIC", "RESTART_SOL",
    ]),
    ("Turbulence & Physics Models", [
        "KIND_TURB_MODEL", "SST_OPTIONS", "SA_OPTIONS",
        "KIND_TRANS_MODEL", "LM_OPTIONS", "KIND_SGS_MODEL",
        "HYBRID_RANSLES",
    ]),
    ("Compressible Flow Conditions", [
        "MACH_NUMBER", "AOA", "SIDESLIP_ANGLE",
        "INIT_OPTION", "FREESTREAM_OPTION",
        "FREESTREAM_PRESSURE", "FREESTREAM_TEMPERATURE",
        "REYNOLDS_NUMBER", "REYNOLDS_LENGTH",
        "FREESTREAM_TURBULENCEINTENSITY", "FREESTREAM_TURB2LAMVISCRATIO",
        "REF_DIMENSIONALIZATION",
    ]),
    ("Incompressible Flow Conditions", [
        "INC_DENSITY_MODEL", "INC_ENERGY_EQUATION",
        "INC_DENSITY_INIT", "INC_VELOCITY_INIT", "INC_TEMPERATURE_INIT",
        "INC_NONDIM",
    ]),
    ("Fluid Model", [
        "FLUID_MODEL", "GAMMA_VALUE", "GAS_CONSTANT",
        "VISCOSITY_MODEL", "MU_CONSTANT", "MU_REF",
        "MU_T_REF", "SUTHERLAND_CONSTANT",
        "CONDUCTIVITY_MODEL", "PRANDTL_LAM", "PRANDTL_TURB",
        "SPECIFIC_HEAT_CP",
    ]),
    ("Reference Values", [
        "REF_ORIGIN_MOMENT_X", "REF_ORIGIN_MOMENT_Y", "REF_ORIGIN_MOMENT_Z",
        "REF_LENGTH", "REF_AREA",
    ]),
    ("Mesh & I/O", [
        "MESH_FILENAME", "MESH_FORMAT",
    ]),
    ("Boundary Conditions", [
        "MARKER_EULER", "MARKER_FAR", "MARKER_SYM",
        "MARKER_ISOTHERMAL", "MARKER_HEATFLUX",
        "MARKER_INLET", "MARKER_OUTLET",
        "INLET_TYPE",
        "INC_INLET_TYPE", "INC_OUTLET_TYPE",
        "MARKER_MONITORING", "MARKER_PLOTTING",
    ]),
    ("Numerical Methods", [
        "NUM_METHOD_GRAD", "NUM_METHOD_GRAD_RECON",
        "CFL_NUMBER", "CFL_ADAPT",
        "CONV_NUM_METHOD_FLOW", "MUSCL_FLOW", "SLOPE_LIMITER_FLOW",
        "CONV_NUM_METHOD_TURB", "MUSCL_TURB", "SLOPE_LIMITER_TURB",
        "TIME_DISCRE_FLOW",
        "LINEAR_SOLVER", "LINEAR_SOLVER_PREC",
        "LINEAR_SOLVER_ERROR", "LINEAR_SOLVER_ITER",
        "MGLEVEL",
    ]),
    ("Convergence Control", [
        "ITER", "CONV_FIELD",
        "CONV_RESIDUAL_MINVAL", "CONV_STARTITER",
        "CONV_CAUCHY_ELEMS", "CONV_CAUCHY_EPS",
        "OBJECTIVE_FUNCTION",
    ]),
    ("Time-Dependent Settings", [
        "TIME_DOMAIN", "TIME_MARCHING",
        "TIME_STEP", "MAX_TIME", "TIME_ITER",
        "UNST_CFL_NUMBER",
    ]),
    ("Output", [
        "OUTPUT_FILES", "CONV_FILENAME",
        "RESTART_FILENAME", "VOLUME_FILENAME", "SURFACE_FILENAME",
        "SCREEN_OUTPUT", "HISTORY_OUTPUT",
        "OUTPUT_WRT_FREQ",
    ]),
]


# Step 5: Combine everything into options_db.yaml

def build_options_db(cfg_path: str, hpp_path: str, out_yaml: str) -> None:
    """Parse source files and write the options database to out_yaml."""
    print(f"[parser] Reading {cfg_path} ...")
    cfg_opts = parse_config_template(cfg_path)

    print(f"[parser] Reading {hpp_path} ...")
    enum_maps = parse_option_structure(hpp_path)

    # Merge centered + upwind maps for CONV_NUM_METHOD_FLOW
    combined_flow_methods = list(dict.fromkeys(
        enum_maps.get("Centered_Map", []) + enum_maps.get("Upwind_Map", [])
    ))
    enum_maps["FlowMethod_Map"] = combined_flow_methods
    OPTION_TO_MAP["CONV_NUM_METHOD_FLOW"] = "FlowMethod_Map"

    print(f"[parser] Building database ({len(cfg_opts)} options) ...")

    db = {}
    for name, meta in cfg_opts.items():
        # Determine choices: prefer hpp enum map, fall back to inline hints
        map_key = OPTION_TO_MAP.get(name)
        choices = []
        if map_key and map_key in enum_maps:
            choices = enum_maps[map_key]
        elif meta["inline_choices"]:
            choices = meta["inline_choices"]

        # Filter out obviously non-enum tokens from inline choices
        # (e.g. numbers, single letters)
        choices = [c for c in choices if re.match(r"^[A-Z][A-Z0-9_\-]+$", c) and len(c) > 1]

        opt_type = _infer_type(meta["default"], meta["description"], choices)

        entry = {
            "section": meta["section"],
            "description": meta["description"],
            "default": meta["default"],
            "type": opt_type,
        }
        if choices:
            entry["choices"] = choices
        if name in OPTION_REQUIRES_SOLVER_FAMILY:
            entry["requires_solver"] = OPTION_REQUIRES_SOLVER_FAMILY[name]

        db[name] = entry

    # Embed wizard stage metadata — convert tuples → lists for yaml.safe_load
    stages_serializable = [[label, list(keys)] for label, keys in WIZARD_STAGES]
    output = {
        "version": "8.4.0",
        "wizard_stages": stages_serializable,
        "options": db,
    }

    Path(out_yaml).parent.mkdir(parents=True, exist_ok=True)
    with open(out_yaml, "w") as f:
        yaml.dump(output, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"[parser] Written → {out_yaml}  ({len(db)} options)")
