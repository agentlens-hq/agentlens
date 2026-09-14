import { init, run, recordToolResult, type Run } from 'agentlens-sdk';
init();
const result: Promise<number> = run('typed', async () => 42);
recordToolResult({toolName: 'lookup', toolUseId: 'id', output: null});
const status: Run['status'] = 'cancelled';
// @ts-expect-error the callable result remains number, not string
const invalid: Promise<string> = result;
void status;
void invalid;
