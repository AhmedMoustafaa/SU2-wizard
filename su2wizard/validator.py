"""
Checks a completed configuration dict against the 40 incompatibility rules
extracted from SetPostprocessing(). Returns a list of warning/error messages.
"""

import yaml
from pathlib import Path


class Violation:
    def __init__(self, rule_id: str, description: str, message: str, severity: str = "error"):
        self.rule_id    = rule_id
        self.description = description
        self.message     = message
        self.severity    = severity  # "error" | "warning"

    def __str__(self):
        icon = "✗" if self.severity == "error" else "⚠"
        return f"  [{self.rule_id}] {icon} {self.message}"


def validate(config: dict, rules: list[dict]) -> list[Violation]:
    """
    Evaluate each incompatibility rule against the config dict.
    Returns a list of Violation objects (may be empty).
    """
    violations = []
    solver = config.get("SOLVER", "")

    for rule in rules:
        rid = rule.get("id", "?")
        desc = rule.get("description", "")
        msg  = rule.get("message", desc)

        # Evaluate "when" conditions — all must match for the rule to apply
        when = rule.get("when", {})
        if not _conditions_match(when, config):
            continue

        # "requires" — at least one of the allowed values must be present
        requires = rule.get("requires", {})
        for opt, allowed_vals in requires.items():
            actual = config.get(opt, "")
            if actual and actual not in allowed_vals:
                violations.append(Violation(
                    rid, desc,
                    f"{msg}  (got {opt}= {actual}, expected one of: {', '.join(allowed_vals)})"
                ))

        # "conflicts_with" — none of the listed values should be present
        conflicts = rule.get("conflicts_with", {})
        for opt, bad_vals in conflicts.items():
            actual = config.get(opt, "")
            if bad_vals is None:
                # Any non-NONE value is a conflict
                if actual and actual.upper() not in ("NONE", "( NONE )", ""):
                    violations.append(Violation(
                        rid, desc,
                        f"{msg}  ({opt} should not be set when {_when_str(when)})"
                    ))
            elif actual in bad_vals:
                violations.append(Violation(
                    rid, desc,
                    f"{msg}  ({opt}= {actual} is incompatible when {_when_str(when)})"
                ))

    return violations


def _conditions_match(when: dict, config: dict) -> bool:
    """Return True if ALL conditions in the 'when' dict are satisfied."""
    for opt, required_vals in when.items():
        actual = config.get(opt, "")
        if actual not in required_vals:
            return False
    return True


def _when_str(when: dict) -> str:
    parts = [f"{k}= {'/'.join(v)}" for k, v in when.items()]
    return ", ".join(parts)


def load_rules(yaml_path: str) -> list[dict]:
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("incompatibility_rules", [])
