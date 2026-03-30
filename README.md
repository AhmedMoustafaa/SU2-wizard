# su2-wizard

Interactive CLI wizard for generating SU2 CFD configuration files.

Built against **SU2 v8.4.0 "Harrier"**.

---

## Features

- **Guided wizard** — stage-by-stage prompts organized by physics, numerics, BCs, and output
- **Smart filtering** — options irrelevant to your chosen solver are automatically hidden (e.g. turbulence options hidden for EULER, incompressible options hidden for compressible solvers)
- **Inline help** — press `?` at any prompt or use `--help-option` to get the full description, type, default, and valid choices for any option
- **Search** — use `--search keyword` or type `/keyword` during the wizard to find options by name or description
- **Annotated output** — the generated `.cfg` includes comments with descriptions and valid choices above each option
- **689 options** parsed directly from SU2 source files (`config_template.cfg` + `option_structure.hpp`)

---

## Installation

```bash
git clone https://github.com/AhmedMoustafaa/SU2-wizard
cd SU2-wizard
pip install -r requirements.txt
```

No build step required as the options database (`data/options_db.yaml`) is included.

---

## Usage

### Interactive wizard
```bash
python main.py
python main.py --output my_case.cfg   # for a specified output file
```

### Look up a specific option
```bash
python main.py --help-option KIND_TURB_MODEL
python main.py --help-option CONV_NUM_METHOD_FLOW
python main.py --help-option slope_limiter_flow   # case-insensitive
```

### Search options by keyword
```bash
python main.py --search mach
python main.py --search turbulence
python main.py --search "linear solver"
```

### During the wizard
- Press `Enter` to accept the default value
- Type `?` at any prompt to see full help for that option
- Type `/keyword` to search the database without leaving the wizard
- `Ctrl+C` at any time exits cleanly

---

## Wizard stages

| Stage | What gets asked |
|-------|----------------|
| Problem Definition | Solver, math problem, units, restart |
| Turbulence & Physics Models | Turb model, SGS, transition, hybrid RANS/LES |
| Compressible Flow Conditions | Mach, AoA, Reynolds, freestream T/P |
| Incompressible Flow Conditions | Density model, init velocity/temperature |
| Fluid Model | Fluid model, viscosity, conductivity, Prandtl |
| Reference Values | Moment origin, ref length, ref area |
| Mesh & I/O | Mesh file |
| Boundary Conditions | Markers (walls, farfield, inlet, outlet) |
| Numerical Methods | Gradient, CFL, convective scheme, limiter, linear solver |
| Convergence Control | Iter count, convergence field, residual target |
| Time-Dependent Settings | Time domain, time step, max time |
| Output | Output files, screen/history output, filenames |

---

## Rebuilding the options database

If you update SU2 or have a different version, rebuild the database from source:

```bash
python main.py --rebuild-db \
    --cfg /path/to/SU2/config_template.cfg \
    --hpp /path/to/SU2/Common/include/option_structure.hpp
```

---

## Project structure

```
su2-wizard/
├── main.py              ← CLI entry point
├── requirements.txt
├── data/
│   └── options_db.yaml  ← Generated options database (689 options, SU2 v8.4.0)
└── su2wizard/
    ├── parser.py         ← Parses SU2 source files → options_db.yaml
    ├── db.py             ← Database loader and query API
    ├── wizard.py         ← Interactive wizard stages and prompt logic
    └── writer.py         ← Writes annotated .cfg output
```

---

## Roadmap
- [x] Phase 1: Build the core options_db.yaml i.e. option names, descriptions, section groups, enum choices, and types
- [x] Phase 2: Enrich types/defaults from `CConfig.cpp` → `SetConfig_Options()`
- [x] Phase 3: Incompatibility rules from `SetPostprocessing()` (conflict detection)
- [ ] VS Code extension using the same YAML schema for autocomplete + linting
- [ ] Python config API (`su2config`) for programmatic config building

---

## Contributing

Incompatibility rules (`SetPostprocessing()`) are the most valuable next contribution — if you
know specific SU2 option conflicts that should raise an error, open an issue or PR.

---
## See Also
- [**_paraview-su2-reader_**](https://github.com/AhmedMoustafaa/paraview-su2-reader) for natively viewing `.su2` mesh files in Paraview.
- [**_meshio-su2-fix_**](https://pypi.org/project/meshio-su2-fix/): a fixed fork of [meshio](https://github.com/nschloe/meshio/) for dealing with .su2 meshes.