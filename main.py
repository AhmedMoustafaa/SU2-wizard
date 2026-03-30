#!/usr/bin/env python3
"""
su2-wizard  —  Interactive SU2 configuration file generator

Usage:
  # Interactive wizard (generates a .cfg from scratch)
  python main.py

  # Specify output file
  python main.py --output my_case.cfg

  # Look up a specific option
  python main.py --help-option KIND_TURB_MODEL

  # Search options by keyword
  python main.py --search mach

  # Regenerate the options database from source files
  python main.py --rebuild-db --cfg config_template.cfg --hpp option_structure.hpp

Options database is stored in data/options_db.yaml.
"""

import argparse
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "options_db.yaml"


def main():
    parser = argparse.ArgumentParser(
        prog="su2-wizard",
        description="Interactive SU2 configuration wizard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output", "-o", default="simulation.cfg",
        help="Output .cfg file path (default: simulation.cfg)",
    )
    parser.add_argument(
        "--help-option", metavar="OPTION",
        help="Show detailed help for a specific SU2 option and exit",
    )
    parser.add_argument(
        "--search", metavar="KEYWORD",
        help="Search options by keyword and exit",
    )
    parser.add_argument(
        "--rebuild-db", action="store_true",
        help="Regenerate options_db.yaml from source files (needs --cfg and --hpp)",
    )
    parser.add_argument(
        "--cfg", metavar="PATH",
        default="config_template.cfg",
        help="Path to SU2 config_template.cfg (for --rebuild-db)",
    )
    parser.add_argument(
        "--hpp", metavar="PATH",
        default="option_structure.hpp",
        help="Path to option_structure.hpp (for --rebuild-db)",
    )

    args = parser.parse_args()

    # Rebuild DB
    if args.rebuild_db:
        from su2wizard.parser import build_options_db
        build_options_db(args.cfg, args.hpp, str(DB_PATH))
        print(f"Database written to {DB_PATH}")
        return

    # Ensure DB exists
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found at {DB_PATH}.")
        print("Run with --rebuild-db to generate it from SU2 source files:")
        print("  python main.py --rebuild-db --cfg config_template.cfg --hpp option_structure.hpp")
        sys.exit(1)

    from su2wizard.db import OptionsDB
    db = OptionsDB(str(DB_PATH))

    # Help-option mode
    if args.help_option:
        from su2wizard.wizard import show_option_help
        show_option_help(db, args.help_option)
        return

    # Search mode
    if args.search:
        from su2wizard.wizard import search_options
        search_options(db, args.search)
        return

    # Interactive wizard
    from su2wizard.wizard import run_wizard
    try:
        run_wizard(db, output_path=args.output)
    except (KeyboardInterrupt, EOFError):
        print("\n\nWizard interrupted. No file written.")
        sys.exit(0)


if __name__ == "__main__":
    main()
