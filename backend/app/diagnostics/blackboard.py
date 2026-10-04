"""A bounded, in-memory diagnostic context; detectors remain independent of inference."""
import platform
import re
from typing import Literal

from pydantic import Field

from app.diagnostics.development import detect_development
from app.diagnostics.parser import parse_evidence
from app.models.schemas import DiagnoseRequest, Finding, StrictModel


class Blackboard(StrictModel):
    language: Literal['python', 'ros2', 'unknown']
    environment: dict[str, str] = Field(default_factory=dict)
    system: dict[str, str] = Field(default_factory=dict)
    ros2: dict[str, str] = Field(default_factory=dict)
    error_types: list[str] = Field(default_factory=list)
    patterns: list[Finding] = Field(default_factory=list)
    important_evidence: list[str] = Field(default_factory=list)
    relevant_sources: list[dict[str, str]] = Field(default_factory=list)
    execution: dict = Field(default_factory=dict)
    recent_context: list[str] = Field(default_factory=list)
    severity: Literal['warning', 'informational'] = 'informational'


def build_blackboard(request: DiagnoseRequest, execution: dict | None = None,
                     history: list[str] | None = None) -> Blackboard:
    sources = request.sources()
    findings = parse_evidence(sources) + detect_development(sources)
    # Bound the finding set to the response/root-cause schema's capacity.
    findings = findings[:8]
    combined = '\n'.join(content for _, content in sources)
    ros_codes = {'tf', 'package', 'executable', 'qos', 'parameter', 'cmd_vel', 'odom', 'lidar', 'build', 'node_start', 'service'}
    language = 'ros2' if any(f.code in ros_codes for f in findings) or re.search(r'\bros2\b|\bcolcon\b|rclpy|rclcpp|AMENT_PREFIX_PATH', combined) else (
        'python' if re.search(r'\bpython\b|Traceback|\w+Error:|\.py\b', combined) else 'unknown')
    environment = (execution or {}).get('environment', {})
    important = list(dict.fromkeys(line for f in findings for line in f.evidence))[:20]
    relevant_sources = []
    remaining = 14000
    for name, content in sources:
        # Keep adjacent code/config/traceback context; don't dump unlimited terminal history.
        lines = content.splitlines()
        if findings and len(content) > 6000:
            indices = set()
            for i, line in enumerate(lines):
                if line.strip() in important:
                    indices.update(range(max(0, i - 8), min(len(lines), i + 9)))
            excerpt = '\n'.join(lines[i] for i in sorted(indices)) if indices else '\n'.join(lines[-80:])
        else:
            excerpt = content
        excerpt = excerpt[:remaining]
        if excerpt:
            relevant_sources.append({'name': name, 'content': excerpt})
            remaining -= len(excerpt)
        if remaining <= 0:
            break
    return Blackboard(language=language, environment=environment,
                      system={'platform': platform.system(), 'python': platform.python_version()},
                      ros2={key: value for key, value in environment.items() if key in {'ROS_DISTRO', 'ROS_VERSION', 'AMENT_PREFIX_PATH'}},
                      error_types=list(dict.fromkeys(f.code for f in findings)), patterns=findings,
                      important_evidence=important, relevant_sources=relevant_sources,
                      execution={key: (execution or {}).get(key) for key in ['command', 'exit_code', 'cwd', 'state']},
                      recent_context=(history or [])[-3:], severity='warning' if findings else 'informational')
