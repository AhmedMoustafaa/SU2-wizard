"""
Loads options_db.yaml and provides query helpers used by the wizard.
"""

import yaml
from pathlib import Path

class OptionsDB:
    def __init__(self, yaml_path: str):
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.version = data.get("version", "unknown")
        self.options: dict = data.get("options", {})
        self.wizard_stages: list = [
            (s[0], s[1]) for s in data.get("wizard_stages", [])
        ]

    def get(self, name: str) -> dict | None:
        return self.options.get(name)

    def choices(self, name: str) -> list[str]:
        opt = self.options.get(name, {})
        return opt.get("choices", [])

    def default(self, name: str) -> str:
        opt = self.options.get(name, {})
        return str(opt.get("default", ""))

    def description(self, name: str) -> str:
        opt = self.options.get(name, {})
        return opt.get("description", "(no description available)")

    def opt_type(self, name: str) -> str:
        opt = self.options.get(name, {})
        return opt.get("type", "string")

    def section(self, name: str) -> str:
        opt = self.options.get(name, {})
        return opt.get("section", "")

    def is_relevant(self, name: str, solver: str) -> bool:
        """
        Return True if this option should be shown for the given solver value.
        Options with no solver constraint are always relevant.
        """
        opt = self.options.get(name, {})
        required = opt.get("requires_solver")
        if not required:
            return True
        return solver in required

    def help_text(self, name: str) -> str:
        """Format a rich help block for a single option."""
        opt = self.options.get(name)
        if opt is None:
            return f"Option '{name}' not found in database."
        lines = [
            f"  Option  : {name}",
            f"  Section : {opt.get('section', '-')}",
            f"  Type    : {opt.get('type', '-')}",
            f"  Default : {opt.get('default', '-')}",
        ]
        choices = opt.get("choices")
        if choices:
            lines.append(f"  Choices : {', '.join(choices)}")
        req = opt.get("requires_solver")
        if req:
            lines.append(f"  Solver  : {', '.join(req)}")
        desc = opt.get("description", "")
        if desc:
            # Word-wrap to ~72 chars
            import textwrap
            wrapped = textwrap.fill(desc, width=72, initial_indent="    ",
                                    subsequent_indent="    ")
            lines.append(f"  Description:\n{wrapped}")
        return "\n".join(lines)

    def search(self, keyword: str) -> list[str]:
        """Return option names whose name or description contain keyword (case-insensitive)."""
        kw = keyword.lower()
        return [
            name for name, opt in self.options.items()
            if kw in name.lower() or kw in opt.get("description", "").lower()
        ]
