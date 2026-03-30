"""
Interactive SU2 configuration wizard.
Run via:
    python main.py [--output my_sim.cfg] [--help-option OPTION_NAME]
"""

import sys
import textwrap
from pathlib import Path

import questionary
from questionary import Style
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import print as rprint

from su2wizard.db import OptionsDB
from su2wizard.writer import write_cfg

console = Console()

WIZARD_STYLE = Style([
    ("qmark",    "fg:#5f87ff bold"),
    ("question", "fg:#ffffff bold"),
    ("answer",   "fg:#5fff87 bold"),
    ("pointer",  "fg:#5f87ff bold"),
    ("highlighted", "fg:#5f87ff bold"),
    ("selected", "fg:#5fff87"),
    ("separator","fg:#444444"),
    ("instruction", "fg:#888888"),
    ("text",     "fg:#cccccc"),
])

HELP_HINT = "[dim]Enter[/dim] [bold cyan]?[/bold cyan] [dim]at any prompt to get help for that option, or[/dim] [bold cyan]/ keyword[/bold cyan] [dim]to search.[/dim]"
SKIP_HINT = "[dim]Press Enter to accept the default, or type a new value.[/dim]"


# Solver family helpers
COMPRESSIBLE = {"EULER", "NAVIER_STOKES", "RANS",
                "FEM_EULER", "FEM_NAVIER_STOKES", "FEM_RANS", "FEM_LES",
                "NEMO_EULER", "NEMO_NAVIER_STOKES"}
INCOMPRESSIBLE = {"INC_EULER", "INC_NAVIER_STOKES", "INC_RANS"}
VISCOUS = {"NAVIER_STOKES", "RANS", "INC_NAVIER_STOKES", "INC_RANS",
           "FEM_NAVIER_STOKES", "FEM_RANS", "FEM_LES", "NEMO_NAVIER_STOKES"}
RANS   = {"RANS", "INC_RANS", "FEM_RANS"}
FEM    = {"FEM_EULER", "FEM_NAVIER_STOKES", "FEM_RANS", "FEM_LES"}
NEMO   = {"NEMO_EULER", "NEMO_NAVIER_STOKES"}

def is_compressible(s): return s in COMPRESSIBLE
def is_incompressible(s): return s in INCOMPRESSIBLE
def is_viscous(s): return s in VISCOUS
def is_rans(s):   return s in RANS
def is_fem(s):    return s in FEM
def is_nemo(s):   return s in NEMO

# Prompt helpers
def _banner():
    console.print(Panel.fit(
        Text.assemble(
            ("SU2 Configuration Wizard\n", "bold cyan"),
            ("v8.4.0 Harrier  |  su2-wizard", "dim"),
        ),
        border_style="cyan",
    ))
    rprint(HELP_HINT)
    console.print()

def _stage_header(label: str, idx: int, total: int):
    console.print(f"\n[bold yellow]Stage {idx}/{total}: {label}[/bold yellow]")
    console.print("[dim]" + "─" * 60 + "[/dim]")

def _show_help(db: OptionsDB, name: str):
    console.print()
    console.print(Panel(
        db.help_text(name),
        title=f"[bold cyan]Help: {name}[/bold cyan]",
        border_style="cyan",
        expand=False,
    ))
    console.print()

def _show_search(db: OptionsDB, keyword: str):
    results = db.search(keyword)
    if not results:
        console.print(f"[yellow]No options found matching '{keyword}'.[/yellow]")
        return
    console.print(f"\n[bold]Found {len(results)} option(s) matching [cyan]'{keyword}'[/cyan]:[/bold]")
    for name in results[:20]:
        desc = db.description(name)
        short_desc = textwrap.shorten(desc, width=60, placeholder="...")
        console.print(f"  [cyan]{name:<40}[/cyan] {short_desc}")
    if len(results) > 20:
        console.print(f"  [dim]... and {len(results)-20} more.[/dim]")
    console.print()

def _ask_enum(db: OptionsDB, name: str, default: str | None = None) -> str:
    """Present a list-select prompt. Supports ? for help."""
    choices_raw = db.choices(name)
    default_val = default or db.default(name)

    # Build choices with default marked
    choices = []
    for c in choices_raw:
        label = f"{c}  [default]" if c == default_val else c
        choices.append(questionary.Choice(title=label, value=c))

    while True:
        answer = questionary.select(
            message=name,
            choices=choices,
            default=next((c for c in choices if c.value == default_val), None),
            instruction="(↑↓ to navigate, Enter to select, ? for help)",
            style=WIZARD_STYLE,
        ).ask()

        if answer is None:
            return default_val  # Ctrl+C → keep default

        # questionary already handles selection; ? is treated as a literal choice
        # We intercept via a wrapper below instead
        return answer


def _ask_text(db: OptionsDB, name: str, default: str | None = None,
              validator=None) -> str:
    """Present a text input prompt. Supports ?, /keyword."""
    default_val = default if default is not None else db.default(name)
    desc_short = textwrap.shorten(db.description(name), width=55, placeholder="...")

    while True:
        console.print(f"[bold]{name}[/bold]  [dim]{desc_short}[/dim]")
        console.print(SKIP_HINT)
        raw = questionary.text(
            message=f"{name} [default: {default_val}]",
            default=default_val,
            style=WIZARD_STYLE,
        ).ask()

        if raw is None:
            return default_val

        raw = raw.strip()

        if raw == "?":
            _show_help(db, name)
            continue

        if raw.startswith("/"):
            _show_search(db, raw[1:].strip())
            continue

        if raw == "":
            return default_val

        return raw


def _ask_bool(db: OptionsDB, name: str, default: str | None = None) -> str:
    default_val = (default or db.default(name)).upper()
    is_yes = default_val == "YES"

    desc_short = textwrap.shorten(db.description(name), width=55, placeholder="...")
    console.print(f"[bold]{name}[/bold]  [dim]{desc_short}[/dim]")

    while True:
        answer = questionary.confirm(
            message=name,
            default=is_yes,
            style=WIZARD_STYLE,
        ).ask()

        if answer is None:
            return default_val
        return "YES" if answer else "NO"


def _prompt(db: OptionsDB, name: str, config: dict,
            forced_default: str | None = None) -> str | None:
    """
    High-level prompt dispatcher. Returns the chosen value, or None to skip.
    Intercepts ? and / before delegating to questionary.
    """
    if name not in db.options:
        return None

    opt_type = db.opt_type(name)
    choices  = db.choices(name)
    default  = forced_default or db.default(name)
    desc_short = textwrap.shorten(db.description(name), width=60, placeholder="...")

    # For enum types with a small number of choices → list select
    if choices and opt_type == "enum":
        # Show description above the prompt
        console.print(f"\n  [bold]{name}[/bold]")
        console.print(f"  [dim]{desc_short}[/dim]")

        # Build choice list
        qchoices = [questionary.Choice(
            title=c + ("  ✓" if c == default else ""),
            value=c
        ) for c in choices]
        qchoices.append(questionary.Choice(title="? Show help", value="__HELP__"))

        while True:
            answer = questionary.select(
                message="",
                choices=qchoices,
                default=next((q for q in qchoices if q.value == default), None),
                style=WIZARD_STYLE,
            ).ask()
            if answer is None:
                return default
            if answer == "__HELP__":
                _show_help(db, name)
                continue
            return answer

    # Bool
    if opt_type == "bool" or default.upper() in ("YES", "NO"):
        console.print(f"\n  [bold]{name}[/bold]  [dim]{desc_short}[/dim]")
        return _ask_bool(db, name, default)

    # Text / numeric
    console.print(f"\n  [bold]{name}[/bold]  [dim]{desc_short}[/dim]")
    return _ask_text(db, name, default)



# Stage logic: skip conditions based on accumulated config
def _should_skip_option(name: str, config: dict) -> bool:
    """Return True if this option should be skipped given current config state."""
    solver = config.get("SOLVER", "EULER")

    rules = {
        # Turbulence options only for RANS/INC_RANS/FEM_RANS
        "KIND_TURB_MODEL": not is_rans(solver),
        "SST_OPTIONS": not is_rans(solver) or config.get("KIND_TURB_MODEL", "NONE") != "SST",
        "SA_OPTIONS":  not is_rans(solver) or config.get("KIND_TURB_MODEL", "NONE") not in ("SA",),
        "KIND_TRANS_MODEL": not is_rans(solver),
        "LM_OPTIONS":  not is_rans(solver) or config.get("KIND_TRANS_MODEL", "NONE") == "NONE",
        "HROUGHNESS":  not is_rans(solver) or config.get("KIND_TRANS_MODEL", "NONE") == "NONE",
        "KIND_SGS_MODEL": not is_fem(solver),
        "HYBRID_RANSLES": not is_rans(solver),
        "DES_CONST":   not is_rans(solver),

        # Compressible-only
        "MACH_NUMBER":    not is_compressible(solver),
        "AOA":            not is_compressible(solver),
        "SIDESLIP_ANGLE": not is_compressible(solver),
        "INIT_OPTION":    not is_compressible(solver),
        "FREESTREAM_OPTION": not is_compressible(solver),
        "FREESTREAM_PRESSURE": not is_compressible(solver),
        "FREESTREAM_TEMPERATURE": not is_compressible(solver),
        "REYNOLDS_NUMBER": not is_compressible(solver),
        "REYNOLDS_LENGTH": not is_compressible(solver),
        "FREESTREAM_TURBULENCEINTENSITY": not is_rans(solver),
        "FREESTREAM_TURB2LAMVISCRATIO":   not is_rans(solver),
        "REF_DIMENSIONALIZATION": not is_compressible(solver),

        # Incompressible-only
        "INC_DENSITY_MODEL":    not is_incompressible(solver),
        "INC_ENERGY_EQUATION":  not is_incompressible(solver),
        "INC_DENSITY_INIT":     not is_incompressible(solver),
        "INC_VELOCITY_INIT":    not is_incompressible(solver),
        "INC_TEMPERATURE_INIT": not is_incompressible(solver),
        "INC_NONDIM":           not is_incompressible(solver),

        # Viscosity / conductivity for viscous solvers only
        "VISCOSITY_MODEL":    not is_viscous(solver),
        "MU_CONSTANT":        not is_viscous(solver),
        "MU_REF":             not is_viscous(solver) or config.get("VISCOSITY_MODEL") != "SUTHERLAND",
        "MU_T_REF":           not is_viscous(solver) or config.get("VISCOSITY_MODEL") != "SUTHERLAND",
        "SUTHERLAND_CONSTANT": not is_viscous(solver) or config.get("VISCOSITY_MODEL") != "SUTHERLAND",
        "CONDUCTIVITY_MODEL": not is_viscous(solver),
        "PRANDTL_LAM":        not is_viscous(solver),
        "PRANDTL_TURB":       not is_rans(solver),
        "SPECIFIC_HEAT_CP":   config.get("FLUID_MODEL", "STANDARD_AIR") not in
                              ("CONSTANT_DENSITY", "INC_IDEAL_GAS", "INC_IDEAL_GAS_POLY", "FLUID_FLAMELET"),

        # Marker visibility
        "MARKER_EULER":      is_viscous(solver),   # Use MARKER_ISOTHERMAL for viscous
        "MARKER_ISOTHERMAL": not is_viscous(solver),
        "MARKER_HEATFLUX":   not is_viscous(solver),
        "INC_INLET_TYPE":    not is_incompressible(solver),
        "INC_OUTLET_TYPE":   not is_incompressible(solver),

        # FEM-only
        "NUM_METHOD_FEM_FLOW": not is_fem(solver),

        # Time domain
        "TIME_STEP":    config.get("TIME_DOMAIN", "NO") == "NO",
        "MAX_TIME":     config.get("TIME_DOMAIN", "NO") == "NO",
        "TIME_ITER":    config.get("TIME_DOMAIN", "NO") == "NO",
        "UNST_CFL_NUMBER": config.get("TIME_DOMAIN", "NO") == "NO",
        "TIME_MARCHING": config.get("TIME_DOMAIN", "NO") == "NO",

        # GAMMA / GAS_CONSTANT only for ideal gas
        "GAMMA_VALUE":  config.get("FLUID_MODEL", "STANDARD_AIR") not in
                        ("IDEAL_GAS", "VW_GAS", "PR_GAS"),
        "GAS_CONSTANT": config.get("FLUID_MODEL", "STANDARD_AIR") not in
                        ("IDEAL_GAS", "VW_GAS", "PR_GAS"),

        # CFL adapt params only if CFL_ADAPT=YES
        "MGLEVEL":      is_fem(solver),
    }
    return rules.get(name, False)



# Main wizard entry-point
def run_wizard(db: OptionsDB, output_path: str = "simulation.cfg") -> None:
    _banner()

    config: dict[str, str] = {}

    # Gather metadata
    console.print("[bold]Let's start with some basic metadata.[/bold]")
    case_name = questionary.text("Case description", style=WIZARD_STYLE).ask() or ""
    author    = questionary.text("Author name", style=WIZARD_STYLE).ask() or ""
    console.print()

    stages = db.wizard_stages
    total_stages = len(stages)

    for stage_idx, (stage_label, option_keys) in enumerate(stages, start=1):

        # Determine which options in this stage are relevant
        relevant = [
            k for k in option_keys
            if not _should_skip_option(k, config)
        ]
        if not relevant:
            continue

        _stage_header(stage_label, stage_idx, total_stages)

        for key in relevant:
            val = _prompt(db, key, config)
            if val is not None:
                config[key] = val

    # Final confirmation
    console.print()
    console.print(f"[bold green]✓ All stages complete.[/bold green]")
    console.print(f"  [bold]{len(config)}[/bold] options collected.")
    console.print()

    # Show summary
    _show_summary(config, db)

    # Write
    confirmed = questionary.confirm(
        f"Write configuration to '{output_path}'?",
        default=True,
        style=WIZARD_STYLE,
    ).ask()

    if confirmed:
        write_cfg(config, db, output_path, case_name=case_name, author=author)
        console.print(f"\n[bold green]✓ Written:[/bold green] [cyan]{output_path}[/cyan]")
    else:
        console.print("[yellow]Aborted. No file written.[/yellow]")


def _show_summary(config: dict, db: OptionsDB) -> None:
    console.print("[bold]Configuration summary:[/bold]")
    # Group by section
    by_section: dict[str, list] = {}
    for k, v in config.items():
        sec = db.section(k)
        by_section.setdefault(sec, []).append((k, v))

    for sec, pairs in by_section.items():
        console.print(f"\n  [yellow]{sec}[/yellow]")
        for k, v in pairs:
            console.print(f"    [cyan]{k:<40}[/cyan] {v}")
    console.print()



# Help-only mode (--help-option OPTION_NAME)


def show_option_help(db: OptionsDB, name: str) -> None:
    opt = db.get(name.upper())
    if opt is None:
        # Try fuzzy search
        results = db.search(name)
        if results:
            console.print(f"[yellow]Option '{name}' not found. Did you mean:[/yellow]")
            for r in results[:10]:
                console.print(f"  [cyan]{r}[/cyan]")
        else:
            console.print(f"[red]Option '{name}' not found in database.[/red]")
        return
    console.print(Panel(
        db.help_text(name.upper()),
        title=f"[bold cyan]{name.upper()}[/bold cyan]",
        border_style="cyan",
        expand=False,
    ))


def search_options(db: OptionsDB, keyword: str) -> None:
    results = db.search(keyword)
    if not results:
        console.print(f"[yellow]No options found matching '{keyword}'.[/yellow]")
        return
    console.print(f"\n[bold]{len(results)} option(s) matching [cyan]'{keyword}'[/cyan]:[/bold]")
    for name in results:
        opt = db.get(name)
        desc = textwrap.shorten(opt.get("description", ""), width=60, placeholder="...")
        default = opt.get("default", "")
        console.print(f"  [cyan]{name:<40}[/cyan] [dim]default={default}[/dim]")
        console.print(f"  {'':40} {desc}")
