"""Rules-only guidance; never impersonates model output or claims a confirmed cause."""
from app.models.schemas import Command, Diagnosis, Finding, RootCause

# summary, inferred cause, suggested steps, commands, beginner explanation
GUIDANCE = {
    'execution': (
        'The captured execution reports a failure.',
        'The process failed, but the available output does not establish a specific root cause.',
        ['Inspect the captured error and the failing command.',
         'Provide the relevant traceback, source excerpt and environment details before changing configuration.'],
        [],
        'A failed exit status confirms that the command did not finish successfully. It does not, by itself, explain the cause.'),
    'python_module': (
        'Python cannot import a required module.',
        'The selected interpreter may lack the dependency, or a local module may be outside its import path.',
        ['Inspect the missing module name and the interpreter used by the failing command.',
         'Compare the project requirements with the active environment. Choose any installation or import-path change yourself.'],
        [('python -c "import sys; print(sys.executable)"', 'Identify the Python interpreter.'),
         ('python -m pip list', 'Inspect packages in that interpreter environment.')],
        'Python imports from the interpreter’s module search path. A package installed into a different virtual environment is not automatically available here.'),
    'python_syntax': (
        'Python could not parse the source file.',
        'A syntax, indentation or incomplete-expression problem may occur at or immediately before the reported line.',
        ['Read the filename, line number and caret in the traceback.',
         'Inspect the surrounding lines for missing punctuation, unclosed brackets or inconsistent indentation. Edit only after reviewing the cause.'],
        [('python --version', 'Check the interpreter version against the source syntax.')],
        'Python parses a file before running it. The caret can point after the actual mistake, so inspect the preceding lines too.'),
    'python_runtime': (
        'A Python exception interrupted execution.',
        'A runtime value, missing file, permission or assumption may disagree with what the code expects.',
        ['Read the final exception line and the last application frame in the traceback.',
         'Check the affected value or path before choosing a fix; include the relevant code if the cause remains unclear.'],
        [('python -c "import sys; print(sys.executable); print(sys.version)"', 'Check the interpreter and version.')],
        'A traceback shows the path to the failure. The final line names the exception, while application frames show where your code encountered it.'),
    'environment': (
        'The command or development environment is unavailable.',
        'The executable may be missing from PATH, or the wrong environment may be active.',
        ['Check the exact executable name and your current environment.',
         'For ROS2, verify installation and workspace setup sourcing. For Python, verify the selected virtual environment.'],
        [('python --version', 'Check whether Python is visible in the active shell.')],
        'The shell finds executable programs through PATH. Activating a virtual environment or sourcing a ROS2 setup file changes what the shell can discover.'),
    'build': (
        'The ROS2 workspace reports a build or dependency failure.',
        'A declared dependency, package configuration or build step may be missing or invalid.',
        ['Find the first package-specific error before the build summary.',
         'Inspect package.xml, CMakeLists.txt and the reported missing dependency. Review any dependency installation before running it.'],
        [('colcon list', 'Inspect discoverable workspace packages.'),
         ('rosdep check --from-paths src --ignore-src', 'Check declared ROS2 dependencies without installing them.')],
        'A failed package can cause downstream packages to be aborted. The first actual error is usually more useful than the final count of failed packages.'),
    'node_start': (
        'A ROS2 node failed to start or exited unexpectedly.',
        'Startup configuration, dependency or application code may have caused the process to exit.',
        ['Inspect the lines immediately before the process-exit message.',
         'Include the launch configuration and specific exception rather than assuming the exit message is the root cause.'],
        [('ros2 node list', 'Check which nodes remain visible.')],
        'The launch system reports that a process exited, but the preceding application output usually explains why.'),
    'service': (
        'A reported topic or service is unavailable.',
        'Its provider may not be running, or a name, namespace or ROS domain may differ.',
        ['Compare the requested name with discovered topic/service names.',
         'Inspect the provider node, namespace, ROS_DOMAIN_ID and sourced environment.'],
        [('ros2 topic list -t', 'List visible topic names and types.'),
         ('ros2 service list -t', 'List visible services and types.'),
         ('ros2 node list', 'Check provider nodes.')],
        'ROS2 discovery depends on compatible names and environments. A missing provider and a namespace mismatch can both look like an unavailable service.'),
    'cmd_vel': (
        'The velocity topic may have a disconnected publisher or subscriber.',
        'A command publisher may be stopped, remapped, inactive, or using a different topic.',
        ['Inspect both endpoints of /cmd_vel and their remappings.',
         'If publisher count is zero, check whether the navigation controller is active and has a goal.',
         'If subscriber count is zero, inspect the drive controller and its configured velocity topic.'],
        [('ros2 topic info /cmd_vel --verbose', 'Inspect publishers, subscribers, types and QoS.'),
         ('ros2 node list', 'Find navigation and drive controller nodes.'),
         ('ros2 lifecycle get /controller_server', 'If using Nav2, check the controller lifecycle state.')],
        'A topic name alone does not mean data is flowing. Publishers send velocity commands; '
        'the drive controller subscribes to them. One subscriber with zero publishers means '
        'something is listening, but no command source is currently connected.'),
    'odom': (
        'Odometry messages may be missing or stale.',
        'The odometry publisher or drive controller may be inactive, remapped, or waiting for sensor data.',
        ['Check whether /odom has a publisher and a steady message rate.',
         'Inspect controller logs and wheel encoder input before changing navigation settings.'],
        [('ros2 topic info /odom --verbose', 'Identify the publisher and endpoint QoS.'),
         ('ros2 topic hz /odom', 'Measure odometry frequency; use Ctrl+C to stop.'),
         ('ros2 node list', 'Locate the actual odometry or controller node.')],
        'Odometry estimates how the robot moves. Navigation needs fresh estimates to compare '
        'the intended motion with what actually happened. A stalled stream can stop navigation.'),
    'tf': (
        'The TF frame tree may be disconnected or unavailable at the requested time.',
        'A broadcaster, frame name, timestamp, or localization transform may be missing or misconfigured.',
        ['Inspect frame names, timestamps and the broadcaster responsible for the missing edge.',
         'For map to odom, check localization/SLAM and its lifecycle state.',
         'Use static transforms only for known fixed geometry; do not invent a map to odom transform.'],
        [('ros2 topic info /tf --verbose', 'Inspect dynamic transform publishers.'),
         ('ros2 topic info /tf_static --verbose', 'Inspect fixed transform publishers.'),
         ('ros2 run tf2_ros tf2_echo map odom', 'For navigation issues, check the map to odom transform.')],
        'TF links coordinate frames so ROS2 can interpret a measurement relative to the robot or map. '
        'Disconnected frames and timestamps outside the transform buffer prevent that conversion.'),
    'lidar': (
        'The LiDAR scan stream may not be publishing.',
        'The sensor driver may be inactive, disconnected, or configured with a different scan topic.',
        ['Inspect the LiDAR driver logs and its device/network configuration.',
         'Compare the configured scan topic and QoS with the consumer.'],
        [('ros2 topic info /scan --verbose', 'Check scan endpoints and QoS.'),
         ('ros2 topic hz /scan', 'Measure scan frequency; use Ctrl+C to stop.'),
         ('ros2 node list', 'Check whether the sensor driver node is present.')],
        'LaserScan messages carry distance measurements. Without a driver publishing scans, '
        'obstacle detection and mapping lack the sensor data they need.'),
    'package': (
        'ROS2 cannot locate a requested package.',
        'The package may not be installed/built, or the terminal may not have sourced the workspace.',
        ['Check the exact package name and whether the workspace build completed.',
         'Source your ROS2 distribution and workspace setup file in the terminal used to launch.'],
        [('ros2 pkg list', 'Check which packages are visible in this environment.'),
         ('printenv AMENT_PREFIX_PATH', 'Inspect sourced install prefixes on Ubuntu/Linux.')],
        'ROS2 discovers packages through sourced installation prefixes. Code can exist on disk '
        'without being discoverable in the terminal environment.'),
    'executable': (
        'ROS2 cannot find a requested executable.',
        'The executable name, install target, or Python console_scripts entry may be incorrect.',
        ['Inspect setup.py console_scripts for Python, or CMake install targets for C++.',
         'Rebuild the affected package and source the workspace install setup.'],
        [('ros2 pkg executables', 'List visible package/executable pairs.')],
        'ros2 run uses installed executable entries. Having a source file in a package does '
        'not automatically register an executable.'),
    'qos': (
        'A reported QoS mismatch may prevent topic delivery.',
        'Publisher and subscriber reliability or durability policies may be incompatible.',
        ['Compare endpoint policies before changing them.',
         'Configure compatible policies in the subscriber/driver; sensor data often uses best effort.'],
        [('ros2 topic info /scan --verbose', 'For scan issues, compare endpoint QoS policies.'),
         ('ros2 topic echo /scan --qos-reliability best_effort', 'For scan issues, test receiving best-effort data.')],
        'QoS describes delivery guarantees. A reliable subscriber cannot receive from a '
        'best-effort publisher. Match the policy to the topic and the application requirements.'),
    'parameter': (
        'A node reports an invalid or missing parameter.',
        'The supplied parameter type/value or YAML namespace may disagree with the node declaration.',
        ['Compare the error with the parameter declaration in the node source.',
         'Check YAML types, node namespaces and ros__parameters nesting, then relaunch the affected node.'],
        [('ros2 node list', 'Identify surviving nodes; a crashed node cannot answer parameter queries.'),
         ('ros2 param list', 'List parameters on currently running nodes.')],
        'ROS2 parameters have declared types. YAML 10 and 10.0 can be interpreted differently, '
        'and a YAML file under the wrong node name may leave a required parameter unset.'),
}


def fallback(findings: list[Finding]) -> Diagnosis:
    if not findings:
        return Diagnosis(
            summary='Insufficient evidence.', severity='informational', confidence='low',
            confidence_reason='No supported failure pattern was found. This does not confirm a healthy robot.',
            evidence=[], root_causes=[], recommended_fix=['Provide the failing command, its complete output and the symptom.'],
            commands=[Command(command=c, purpose=p) for c, p in [
                ('ros2 node list', 'Identify visible ROS2 nodes.'),
                ('ros2 topic list -t', 'List topics and message types.'),
                ('ros2 topic info /odom --verbose', 'Inspect odometry endpoints.')]],
            explanation='A snapshot is only part of the story. Describe what should happen and what actually happens, '
                        'and include your ROS2 distribution and relevant logs.',
            additional_information_needed=['ROS2 distribution, expected behavior, failing command and complete output.'])
    unique = list(dict.fromkeys(f.code for f in findings))
    guides = [GUIDANCE[code] for code in unique]
    commands = dict(pair for g in guides for pair in g[3])
    summary = guides[0][0]
    if unique[0] == 'cmd_vel':
        cmd_lines = [line for f in findings if f.code == 'cmd_vel' for line in f.evidence]
        if any('Publisher count: 0' in line for line in cmd_lines):
            summary = 'No velocity publisher is visible on /cmd_vel.'
        elif any('Subscription count: 0' in line for line in cmd_lines):
            summary = 'No velocity subscriber is visible on /cmd_vel.'
    return Diagnosis(
        summary=summary if len(guides) == 1 else f'{len(guides)} potential issues found. {summary}',
        severity='warning', confidence='medium',
        confidence_reason='Rules matched explicit supplied lines; root causes remain hypotheses and need verification.',
        evidence=list(dict.fromkeys(line for f in findings for line in f.evidence))[:20],
        root_causes=[RootCause(cause=g[1], reason='Inferred from: ' + next(f.title for f in findings if f.code == code))
                     for code, g in zip(unique, guides)],
        recommended_fix=list(dict.fromkeys(step for g in guides for step in g[2]))[:10],
        commands=[Command(command=c, purpose=p) for c, p in commands.items()][:12],
        explanation='\n\n'.join(g[4] for g in guides)[:3000],
        additional_information_needed=['Run the relevant inspection commands and provide their output to confirm the cause.'])
