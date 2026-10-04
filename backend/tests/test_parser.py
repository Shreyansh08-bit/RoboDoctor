import pytest

from app.diagnostics.parser import parse_evidence


def codes(text):
    return {f.code for f in parse_evidence([('Terminal', text)])}


@pytest.mark.parametrize('text, expected', [
    ('$ ros2 topic info /cmd_vel\nPublisher count: 0\nSubscription count: 1', 'cmd_vel'),
    ('$ ros2 topic info /cmd_vel\nPublisher count: 1\nSubscription count: 0', 'cmd_vel'),
    ("Could not find a connection between 'base_link' and 'laser'", 'tf'),
    ('map -> odom transform missing', 'tf'),
    ("PackageNotFoundError: package 'nav2_bringup' not found", 'package'),
    ('No executable found', 'executable'),
    ('$ ros2 topic info /odom\nPublisher count: 0', 'odom'),
    ('$ ros2 topic hz /odom\nNo messages received for 8.4 seconds', 'odom'),
    ('[controller] /odom stale: last update was 8.4 seconds ago', 'odom'),
    ('$ ros2 topic info /scan\nPublisher count: 0', 'lidar'),
    ('offering incompatible QoS. Last incompatible policy: RELIABILITY', 'qos'),
    ('InvalidParameterTypeException: wheel_radius', 'parameter'),
])
def test_failure_patterns(text, expected):
    assert expected in codes(text)


@pytest.mark.parametrize('text', [
    '$ ros2 topic info /cmd_vel\nPublisher count: 1\nSubscription count: 1\n$ ros2 topic hz /odom\naverage rate: 30.0',
    '$ ros2 topic list\n/cmd_vel\n/odom\n/scan\n/tf',
    '$ ros2 topic info /cmd_vel\nPublisher count: 1\n$ ros2 topic info /camera\nPublisher count: 0',
    '$ ros2 topic info /odom\nPublisher count: 1\n$ ros2 node info /test\nPublisher count: 0',
    'Publisher count: 0',
])
def test_healthy_and_ambiguous_output(text):
    assert codes(text) == set()


def test_source_isolation_and_exact_evidence():
    findings = parse_evidence([('one.log', '$ ros2 topic info /odom'), ('two.log', 'Publisher count: 0')])
    assert not findings
    text = "[rviz] Could not find a connection between 'base_link' and 'laser'"
    finding = parse_evidence([('robot.log', text)])[0]
    assert finding.source == 'robot.log'
    assert finding.evidence == [text]


def test_long_failure_lines_do_not_break_response_schema():
    from app.diagnostics.fallback import fallback
    findings = parse_evidence([('Terminal', 'No executable found ' + 'x' * 3000)])
    assert fallback(findings).summary == 'Insufficient evidence.'
