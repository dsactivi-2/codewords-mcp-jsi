"""Regenerate repo guide/catalog from the service without importing or starting it.

Run with --check to verify the checked-in artifacts without changing files.
Only pure catalog constructors and named constant assignments are evaluated.
"""
import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def artifacts():
    path = ROOT / 'jobstep_mcp.py'
    tree = ast.parse(path.read_text())
    env = {'Any': object}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {'_p', '_spec'}:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), env)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id in {'SERVICE_VERSION', 'TOOL_SPECS', 'SKILL_TEXT'} for t in targets):
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), env)
    reference = ROOT / '.agents/skills/jobstep-crm/references/service-guide.md'
    # Preserve the explicitly versioned provenance, not a fabricated live-fetch date.
    header = reference.read_text().split('-->\n\n', 1)[0] + '-->\n\n'
    if f'Version {env["SERVICE_VERSION"]}' not in header:
        raise ValueError('Update the provenance version before regenerating the reference')
    catalog = {'version': env['SERVICE_VERSION'], 'service_id': 'jobstep_mcp_4a31136a', 'tools': env['TOOL_SPECS']}
    return {reference: header + env['SKILL_TEXT'],
            ROOT / 'skills/jobstep-crm/SKILL.md': env['SKILL_TEXT'],
            ROOT / 'tools.json': json.dumps(catalog, ensure_ascii=False, indent=2) + '\n'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    different = []
    for path, content in artifacts().items():
        if args.check:
            if path.read_text() != content:
                different.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(content)
    if different:
        parser.exit(1, 'Artifacts differ: ' + ', '.join(different) + '\n')
    print('Service artifacts are consistent.' if args.check else 'Service artifacts regenerated.')
