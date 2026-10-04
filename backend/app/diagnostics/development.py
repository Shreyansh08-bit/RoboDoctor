"""Small independent detector plug-in for Python, shell and ROS2 workspace failures."""
import re

from app.models.schemas import Finding

RULES = [
    ('python_module', 'Python dependency is not importable', r'ModuleNotFoundError:|ImportError:'),
    ('python_syntax', 'Python syntax or indentation error', r'(?:SyntaxError|IndentationError|TabError):'),
    ('python_runtime', 'Python runtime exception', r'(?:NameError|TypeError|ValueError|AttributeError|IndexError|KeyError|ZeroDivisionError|FileNotFoundError|PermissionError|RuntimeError|AssertionError|UnboundLocalError):'),
    ('environment', 'Executable or shell environment problem', r'command not found|is not recognized as|CommandNotFoundException|No module named pip|externally-managed-environment'),
    ('build', 'ROS2 workspace build or dependency failure', r'Failed\s+<<<|Aborted\s+<<<|CMake Error|Could not find.*(?:package|configuration file)|rosdep.*(?:ERROR|failed)|Cannot locate rosdep definition'),
    ('node_start', 'ROS2 node startup failure', r'process has died|failed to load node|failed to start.*node'),
    ('service', 'ROS2 topic or service is unavailable', r'service.*(?:not available|not found)|(?:Unknown topic|Invalid topic name)|topic.*does not appear to be published'),
]


def detect_development(sources: list[tuple[str, str]]) -> list[Finding]:
    findings = []
    for source, text in sources:
        for code, title, pattern in RULES:
            lines = [line.strip() for line in text.splitlines()
                     if 0 < len(line.strip()) <= 2000 and re.search(pattern, line, re.I)]
            if lines:
                findings.append(Finding(code=code, title=title, source=source, evidence=list(dict.fromkeys(lines))[:6]))
    return findings
