"""OPTIONAL Command-Bar planner via the Anthropic API – only used when the user opted in (~/.config/toravo/agent.json,
provider "anthropic") with their OWN key file. Runs in its own venv with the official SDK (pip install anthropic).
stdin: {"system", "text", "schema", "model", "key_file", "songs"}  ->  stdout: plan JSON
"""
import json, sys

import anthropic


def main():
    req = json.load(sys.stdin)
    with open(req['key_file']) as f:
        key = f.read().strip()
    client = anthropic.Anthropic(api_key=key)
    response = client.beta.messages.create(
        model=req.get('model') or 'claude-opus-5-5',
        max_tokens=16000,
        betas=['server-side-fallback-2026-07-01'],
        fallbacks='default',
        system=req['system'] + '\nExisting songs: ' + (', '.join(req.get('songs') or []) or 'none'),
        messages=[{'role': 'user', 'content': req['text']}],
        output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': req['schema']}},
    )
    if response.stop_reason == 'refusal':
        sys.exit('Anfrage abgelehnt (refusal) – nutze lokalen Planer.')
    text = next(b.text for b in response.content if b.type == 'text')
    print(json.dumps(json.loads(text), ensure_ascii=False))


if __name__ == '__main__':
    main()
