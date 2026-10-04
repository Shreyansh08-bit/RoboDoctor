# Verification — supplied robot, light UI and multi-session workflow

Verified on Windows on **4 October 2026**. The existing application was extended in place; the detector/fallback/structured Gemma diagnosis pipeline remains. Backend session and API orchestration were intentionally extended for the new interaction brief.

## Results

- **114 backend tests pass** (62 existing tests and 52 new test cases). There is one existing Starlette/AnyIO deprecation warning.
- Strict TypeScript compilation and production Vite build pass: 56 modules; JS 222.94 KB / 69.09 KB gzip; CSS 27.46 KB / 6.67 KB gzip. No frontend unit-test runner existed; browser interaction checks supplement the build.
- Multiple clean Windows stops/starts completed. Ports 8000/5173 were confirmed closed before the final startup. Frontend, backend, local Gemma connection and supplied-image launcher came back up.
- The supplied PNG is copied unchanged into `assets/robot.png` and `frontend/public/robot.png`; desktop, sidebar and favicon use it. Native facial overlays preserve the body, colors and proportions.

## Live checks

| Check | Observed result |
| --- | --- |
| Three native managed terminals | Created Terminal 01, 02 and 03 through the real robot menu. They appeared as independent sessions in the workspace. |
| Three real shell clients | Independent persistent PowerShell sessions captured two successful commands and one actual `import nonexistent_package` failure, with separate stdout/stderr. Only the failed session created an issue; inference remained idle. |
| No-error double-click | Real desktop double-click opened the RoboDoctor workspace in the default Brave browser. |
| Single issue double-click | The actual worried robot displayed one issue. Double-click selected its session and began investigation automatically. |
| First live Gemma investigation | Gemma requested `python3 --version`; the read-only diagnostic session returned Python 3.10.10. A validated local-AI report identified `nonexistent_package`. Final report inference took approximately 53 seconds, excluding probe planning. |
| Multiple issues double-click | A second real shell failed independently. The robot displayed 2 issues. Double-click left inference idle; the first issue was diagnosed and the second remained unopened. |
| Selected second investigation | Selecting only the second issue in the browser started its investigation. Gemma requested `python --version`, then returned a validated ValueError diagnosis (approximately 59 seconds for final inference). Reports retained the correct session ID and execution sequence. |
| Successful identical rerun | A controlled environment flag changed the behavior of the same command. The actual rerun exited 0; only that command's issue resolved. The robot returned to happy when no issues remained. |
| Native terminal focus | Selecting Terminal 01 requested the matching GUI window and the companion acknowledged the attempt. The correct named window was observed. OS focus is best-effort; the product never claims confirmed focus and retains an Open Terminal fallback. |
| Native controls | Final startup created a terminal with visible rounded Run/Stop/Inspect controls, correct robot window icon, and readable light output area. The text area's initial height was reduced so controls no longer fell below the window. |

Native terminal commands were tested through the existing runner/client in shell harnesses, not by typing into Windows terminal UI. Desktop menu/double-click and browser selection were exercised with the Computer Use tool. Browser-created examples remain explicitly labeled as examples.

## Regression coverage

New cases verify unique session IDs, independent sequences and output, multiple simultaneous issues, deterministic error detection without inference, selecting only one issue, automatic issue-open diagnosis, cached repeat opens, correct focus association, successful rerun isolation, healthy/idle/concerned/unresolved states, and low-confidence handling. A background session's streaming updates and successful completion cannot steal another selected issue.

Tests also cover stale Gemma responses, a slow fake_robot example after a newer real execution, silent whitespace-only output, separate real stdout/stderr streams, missing Ollama fallback without probes, 18 approved command forms, 15 prohibited command forms, actual read-only collection, planner rejection and a hard maximum of three investigation rounds. Existing Python/ROS2 parser, model availability, input-validation, origin and terminal cancellation tests continue to pass.

A live silent environment-setting command exposed a whitespace normalization error during verification. It was fixed, covered by a regression test, and the real identical-command rerun then passed. A Windows encoding issue in the temporary edit scripts was also corrected; final app labels and terminal titles are valid UTF-8.

## Visual and interaction checks

- Light blue/teal surfaces, curved corners, restrained shadows and smooth button/disclosure motion replace the dark angular presentation. The footer remains **RoboDoctor / Made by Shreyansh Chauhan / v1.0**.
- Checked 1920×1080, 1440×900, 1280×800, 1024×768 and 390×844. No horizontal overflow after fixing narrow-screen navigation padding. Temporary viewport overrides were reset.
- All eleven examples remain accessible. The ROS2 parameter example rendered correctly as a labeled rules report. Command disclosure and Copy → Copied worked.
- The supplied robot was observed resting, worried with one issue, worried with two issues and happy after resolution. The live backend/browser showed investigating and diagnosis-ready states; low-confidence/unresolved transitions are covered by tests. The image stays recognizable with restrained eye/face overlays.
- UI screenshots: [clean-start workspace](docs/light-ready.jpg), [healthy rerun](docs/light-healthy.jpg), [live Gemma report](docs/light-workspace.jpg), [ROS2 example](docs/light-example.jpg), [robot](docs/light-launcher.jpg), [native terminal](docs/light-terminal.jpg).

## Architecture and files changed

| File | Change |
| --- | --- |
| `backend/app/state.py` | Session isolation, token ownership, issue lifecycle, deterministic detection, selected-view protection, sequence guards |
| `backend/app/main.py` | Session selection/focus, issue-open routing, bounded investigation, cached diagnosis and stale result handling |
| `backend/app/models/schemas.py` | Session/sequence/issue identifiers on reports |
| `backend/app/diagnostics/blackboard.py` | Session IDs, sequence, streams, timestamp and ROS_DOMAIN_ID context |
| `backend/app/diagnostics/investigation.py` | Local probe planner, strict argv allowlist, three-round bound, time/output caps and separate diagnostic log |
| `companion/client.py` | Per-client session identity and name |
| `companion/session.py` | Separate bounded stdout/stderr capture while preserving persistent PowerShell/Bash behavior |
| `companion/desktop.py` | Supplied robot, expression overlays, multiple windows, issue-aware double-click, focus handling, light rounded controls |
| `frontend/src/App.tsx` | Terminal roster, issue chooser, automatic selected issue investigation, diagnostic transcript and stale UI response guards |
| `frontend/src/style.css` / `frontend/index.html` | Light curved presentation, responsive layout and PNG favicon |
| `assets/robot.png` / `frontend/public/robot.png` | Unchanged supplied image |
| `backend/tests/test_multi_session.py` / `test_companion_routing.py` | 52 additional regression cases |
| `start.ps1` / `README.md` / `VERIFICATION.md` / `docs/` | Startup wording, architecture, workflow instructions and verification artifacts |

## Start and create terminals

Windows, from the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
# Optional project directory:
powershell -ExecutionPolicy Bypass -File .\start.ps1 -ProjectPath C:\path\to\robot_ws
```

Ubuntu:

```bash
bash start.sh
bash start.sh --cwd ~/robot_ws
```

Right-click the robot → **New managed terminal** repeatedly. Run commands in each window. Failed sessions appear automatically; double-click the robot, then select an issue if several exist. Fix suggestions remain user-controlled.

## Known limits

- ROS2 is not installed on this Windows machine. The exact three-turtlesim demo could not be executed; ROS2 detection was checked with existing captured fixtures and regression cases. No live robot/node correctness is claimed.
- Ubuntu desktop/compositor behavior is unverified here. Bash branches remain; Windows transparency is implemented, while the current Linux Tk launcher may retain an opaque background. Mac is unsupported.
- Managed sessions are persistent pipes, not a full interactive TTY. Password prompts, fullscreen terminal tools and arbitrary external terminals are outside scope.
- Diagnostic environment is a separate process context, not a complete clone of every shell variable. PATH comes from backend startup; captured ROS metadata and a virtual-environment interpreter are used where available. Tool absence in this context is reported as such.
- Sessions/issues/history remain process-local and clear on backend restart. Maximum 32 sessions per backend lifetime; reports retain twelve history entries. A closed terminal's stored output can be inspected, but it has no live window to focus.
- Diagnosis caching avoids duplicate inference for the same execution. A newer execution supersedes stale results. An unrelated successful command does not resolve an older failed command; rerun the relevant command successfully.
- Model recommendations are hypotheses. Exact quote/schema validation does not prove technical correctness. Unavailable/invalid Gemma output is disclosed as rules fallback. No cloud model, automatic fix or package installation was introduced.
## Ubuntu onboarding documentation

The README now includes the configured GitHub clone URL, Ubuntu system dependencies, Node 22 through `.nvmrc` / nvm, isolated Python installation, Ollama service and model setup, desktop and headless launch paths, health checks, a same-command error/recovery demo, optional ROS2 environment sourcing, troubleshooting, and contributor commands. `.gitattributes` preserves LF line endings for Bash scripts. Install instructions were checked against the official nvm and Ollama documentation. Git Bash `bash -n` checks the launcher and README Bash command blocks; this is syntax/documentation validation, not a completed Ubuntu desktop test. Real Ubuntu compositor, terminal, and Gemma behavior remains unverified.
