import re
import time

from app.ai.local import LocalAIError, diagnose
from app.diagnostics.blackboard import build_blackboard
from app.diagnostics.fallback import fallback
from app.models.schemas import DiagnoseRequest, DiagnoseResponse, Diagnosis, Finding
from app.settings import settings


def healthy_diagnosis(execution: dict) -> Diagnosis:
    return Diagnosis(summary='✓ Everything looks good.', severity='informational', confidence='high',
                     confidence_reason='The latest command exited successfully and no supported error pattern was detected. This is a check of that run, not the whole project.',
                     evidence=[f"Exit code: {execution['exit_code']}"], root_causes=[], recommended_fix=[], commands=[],
                     explanation='The latest captured execution completed successfully. RoboDoctor stays quiet until there is meaningful evidence of a problem.',
                     additional_information_needed=[])


async def analyze_evidence(request: DiagnoseRequest, execution: dict | None = None, history=None) -> tuple:
    started = time.perf_counter()
    board = build_blackboard(request, execution, history)
    findings = board.patterns
    if execution and execution.get('state') == 'cancelled':
        result = Diagnosis(summary='Execution stopped.', severity='informational', confidence='high',
                           confidence_reason='The managed shell was stopped; this does not establish a code failure.',
                           evidence=[f"Exit code: {execution['exit_code']}"], root_causes=[], recommended_fix=[], commands=[],
                           explanation='Inspect the captured output if needed. Stopping a long-running command resets its shell session.',
                           additional_information_needed=[])
        return DiagnoseResponse(diagnosis=result, findings=findings, engine='observed', elapsed_ms=0,
                                status='insufficient'), board
    generic_error = re.search(r'Traceback \(most recent|\[ERROR\]|\berror:|\bfatal:|segmentation fault', request.text, re.I)
    # Explicit managed exit status is stronger than guessing success from pleasant log text.
    if execution and execution.get('exit_code') == 0 and execution.get('state') == 'finished' and not findings and not generic_error:
        return DiagnoseResponse(diagnosis=healthy_diagnosis(execution), findings=[], engine='observed',
                                elapsed_ms=0, status='healthy'), board
    failed = execution and execution.get('exit_code') not in {None, 0}
    if (failed or generic_error) and not findings:
        evidence = [line.strip() for line in request.text.splitlines()
                    if line.strip() and len(line.strip()) <= 2000][-4:]
        findings.append(Finding(code='execution', title='Execution reports an error', source='Terminal', evidence=evidence))
        board.patterns = findings
        board.error_types = ['execution']
        board.important_evidence = evidence
        board.severity = 'warning'
    result = fallback(findings)
    engine, model, notice = 'rules', None, 'Rules-only guidance. Gemma was not used.'
    if request.mode == 'auto':
        try:
            result = await diagnose(request, findings, board)
            engine, model, notice = 'local-ai', settings.model_name, None
        except LocalAIError as exc:
            notice = str(exc) + ' Showing rules-only guidance; no AI diagnosis was produced.'
    status = 'insufficient' if result.summary == 'Insufficient evidence.' else 'problem'
    return DiagnoseResponse(diagnosis=result, findings=findings, engine=engine, model=model,
                            notice=notice, elapsed_ms=int((time.perf_counter() - started) * 1000), status=status), board
