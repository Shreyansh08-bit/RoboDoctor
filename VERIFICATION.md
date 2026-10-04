# Verification — UI refinement

Verified on Windows on **4 October 2026**, with Python 3.10.10, Node.js 24.19.0, Ollama, and the installed `gemma3:4b` model. This update refines presentation and UX. SHA-256 comparisons confirm all **14 backend application source files are unchanged**. The diagnostic engine, APIs, blackboard, and Ollama client were preserved.

## Build and regression checks

- **62 pytest tests pass.** The original 59 tests still pass; three additional resilience tests cover malformed terminal control sequences, bounded/normalized output, empty and unstructured evidence, and rules/healthy operation without inference.
- Strict TypeScript compilation and production Vite build pass: 56 modules, approximately 218.94 KB JavaScript / 68.05 KB gzip; CSS 18.79 KB / 4.80 KB gzip.
- Repeated clean Windows startup/shutdown: ports 8000 and 5173 were verified closed before restarting. The frontend, backend, and floating launcher started again, and the captured Python/ROS2-style/healthy integration checks passed after the final restart.
- The configured `.env` remained `gemma3:4b` and loopback Ollama. Temporary failure-test configuration was supplied only to isolated backend processes; the user's actual Ollama service and installed weights were left intact.

## Real execution and local inference

| Check | Result |
| --- | --- |
| Python missing import | A real managed PowerShell execution failed with `ModuleNotFoundError`. Gemma returned a validated local diagnosis (about 44 seconds). |
| ROS2-style package error | A failing command emitted a ROS2-style `PackageNotFoundError` fixture. The backend detected the package pattern and Gemma returned a local response (about 37 seconds). This minimal fixture was ambiguous to Gemma, which interpreted it as a Python dependency. |
| Rich ROS2 parameter fixture | The managed shell emitted the existing parameter-crash fixture, including ROS2 context and selected environment metadata. A repeated run returned a validated Gemma diagnosis identifying the string/double mismatch (about 44 seconds). |
| Real ROS2 CLI invocation | `ros2 --help` failed because ROS2 is not installed here. RoboDoctor correctly diagnosed an unavailable command/environment. |
| Successful command | A real Python command printed successful robot initialization/controller/mission messages and exited 0. The backend returned exactly **✓ Everything looks good.**, engine `observed`, with no commands. |
| Local inference without internet access | A process-level guard blocked external TCP connections and external DNS while allowing loopback. Installed Gemma returned a validated syntax-error diagnosis. The network adapter and OS settings were not changed. |

The managed shell/client implementation and real loopback backend were used for execution tests. Suggested commands were never executed. A test harness initially hit a Windows console encoding error while printing the checkmark after its healthy assertions had passed; UTF-8 output was corrected. This was a harness logging issue, not an application failure.

## Failure checks

- **Ollama unreachable:** an isolated backend used an unused loopback Ollama port. Health distinguished installed runtime from unreachable API, the setup dialog showed the right state, diagnosis returned an explicitly labeled rules fallback, and the healthy example still worked.
- **Gemma missing:** an isolated backend requested a deliberately nonexistent local model. The actual Ollama API remained reachable. Health showed runtime found / API reachable / model unavailable; diagnosis handled HTTP 404 with rules guidance. No model download occurred.
- **Unverified model evidence:** one rich ROS2 attempt returned a quote that did not exactly match supplied lines. The existing evidence validator rejected it and correctly produced a disclosed rules-only report. A later attempt produced validated evidence. Model recommendations remain hypotheses; successful formatting/quote validation does not guarantee technical correctness.
- **Malformed output:** ANSI sequences, NULs, and long output were normalized and bounded; the meaningful exception survived. Unstructured pasted text, including a literal script-like string, returned insufficient evidence rather than a healthy guess.
- **Empty terminal:** `/api/terminal/diagnose` returned 409 with no execution; the web Inspect button was disabled. Running and cancelled execution behavior remains covered by existing tests.
- **Backend restart/reconnection:** stale reports clear when a fresh backend has no history. Examples now retry after the backend becomes available instead of leaving a startup error behind.

## Visual and interaction checks

- Checked **1920×1080, 1440×900, 1280×800, 1024×768, and 390×844**. Document and viewport widths matched at each size; no horizontal overflow. Content width stays bounded on large desktops. Temporary viewport overrides are reset after verification.
- Latest diagnosis is the visual focus. Evidence, cause, commands, confidence explanation, and supporting context expand on demand; the fix is initially visible. Healthy mode is deliberately sparse.
- Sidebar navigation retains Diagnose, Terminal, Examples, History, and Settings. All eleven examples remain accessible.
- History selection restores a prior report. Evidence and command disclosures open correctly. Copy changes to **Copied**.
- A synthetic UTF-8 `.log` file uploaded through the browser file chooser and produced the expected syntax diagnosis. Paste, file validation, upload limits, and example behavior remain covered by backend tests.
- The footer displays **RoboDoctor / Made by Shreyansh Chauhan / v1.0**. It remains visible on narrow screens.
- Launcher, sidebar mark, and favicon use the same quiet robot identity and restrained green/amber palette. The web signal responds only to actual state, and CSS respects reduced-motion preferences. No artificial thinking stages, giant demo panel, gradients, or decorative metrics were added.
- The Windows launcher renders correctly with quiet sleeping/checking states. It starts clear of the notification corner and retains its existing drag, double-click, and menu bindings.

## Verification limits

- **Native input automation is blocked on the current Windows session:** the helper can capture the borderless launcher but returns `failed to activate captured window` for input. This prevents automated confirmation of double-click/drag on the refined build. A manual double-click check was requested. The previous build's double-click/browser/menu behavior was verified on 3 October; the same launcher handlers remain in this update.
- **No live ROS2 node or robot was available.** The actual missing-CLI case and captured ROS2 fixtures were tested; live robot correctness is not claimed.
- **Ubuntu desktop runtime remains unverified.** Linux/Bash branches were preserved; this Windows environment cannot verify a Linux compositor. Mac remains unsupported.
- The suite has one existing Starlette/AnyIO deprecation warning; all tests pass.

Screenshots: [healthy workspace](docs/healthy.jpg), [diagnosis workspace](docs/workspace.jpg), [launcher](docs/launcher.jpg), [Ollama offline](docs/ollama-offline.jpg), [Gemma missing](docs/gemma-missing.jpg).

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm run build
cd ..
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Run the README examples in the managed terminal and inspect them through the workspace or launcher. Ollama and Gemma setup remain explicit user actions; no packages, weights, or project fixes are installed/applied automatically.
