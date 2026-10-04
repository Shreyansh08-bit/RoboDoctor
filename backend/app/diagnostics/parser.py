"""Conservative pattern matching: topic counts belong to the current command block."""
import re

from app.models.schemas import Finding

PATTERNS = [
    ('tf', 'Possible TF broadcaster or frame configuration issue',
     r"could not find a connection|invalid frame id|lookup would require extrapolation|(?:transform|transformation).*(?:does not exist|not available|unavailable)|(?:map.*odom|odom.*map).*(?:missing|not found)"),
    ('package', 'ROS2 package/environment issue', r'PackageNotFoundError|package [\'\"].+?[\'\"] not found'),
    ('executable', 'ROS2 package/executable configuration issue', r'no executable found|executable .* not found'),
    ('qos', 'Possible QoS incompatibility', r'incompatible QoS|incompatible.*(?:reliability|durability)|last incompatible policy'),
    ('parameter', 'Possible node parameter configuration issue', r'InvalidParameterTypeException|ParameterUninitializedException|parameter.*(?:wrong type|invalid type|must be|not set)'),
]


def parse_evidence(sources: list[tuple[str, str]]) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    def add(code: str, title: str, source: str, lines: list[str]):
        if (code, source) not in seen:
            findings.append(Finding(code=code, title=title, source=source,
                                    evidence=list(dict.fromkeys(lines))[:8]))
            seen.add((code, source))

    for source, text in sources:
        lines = text.splitlines()
        for code, title, pattern in PATTERNS:
            matches = [line.strip() for line in lines if len(line.strip()) <= 2000 and re.search(pattern, line, re.I)]
            if matches:
                add(code, title, source, matches)

        # Only interpret counts when their topic is explicitly identified.
        topic = None
        context = []
        for line in lines:
            match = re.search(r'ros2 topic (?:info|echo|hz)\s+(/[^\s]+)', line)
            if match and len(line.strip()) <= 2000:
                topic, context = match.group(1), [line.strip()]
            elif re.match(r'\s*\$\s*', line):
                topic, context = None, []
            if topic and len(line.strip()) <= 2000:
                context.append(line.strip())
                no_publisher = bool(re.search(r'Publisher count:\s*0\b', line, re.I))
                no_subscriber = bool(re.search(r'Subscription count:\s*0\b', line, re.I))
                stalled = bool(re.search(r'no messages received|not publishing|does not appear to be published|unknown topic', line, re.I))
                if topic == '/cmd_vel' and (no_publisher or no_subscriber or stalled):
                    add('cmd_vel', 'Possible velocity topic connection issue', source,
                        [context[0], line.strip()])
                elif topic in {'/odom', '/scan'} and (no_publisher or stalled):
                    code = 'odom' if topic == '/odom' else 'lidar'
                    title = 'Possible odometry/controller issue' if code == 'odom' else 'Possible LiDAR publisher issue'
                    add(code, title, source, [context[0], line.strip()])
        for topic_name, code, title in [('/odom', 'odom', 'Possible odometry/controller issue'),
                                        ('/scan', 'lidar', 'Possible LiDAR publisher issue')]:
            matches = [line.strip() for line in lines if len(line.strip()) <= 2000 and topic_name in line and re.search(
                r'no messages received|not publishing|timed out|stale', line, re.I)]
            if matches:
                add(code, title, source, matches)
    return findings
