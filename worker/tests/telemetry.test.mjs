import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildAnalyticsDataPoint,
  sanitizeTelemetryPayload,
  serveLatestJson,
  handleRateLimit,
} from '../src/index.js';

// Helper to construct a minimal Request-like object
function makeRequest({
  method = 'GET',
  headers = {},
  cf = {},
  url = 'https://stata-agent-install.tdmonk.com/',
  body = null,
} = {}) {
  return {
    method,
    url,
    headers: {
      get(name) {
        const key = String(name || '').toLowerCase();
        for (const [k, v] of Object.entries(headers)) {
          if (k.toLowerCase() === key) return v;
        }
        return null;
      },
    },
    cf,
    async json() {
      if (body) return typeof body === 'string' ? JSON.parse(body) : body;
      throw new Error('no body');
    },
    text() {
      return Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body));
    },
  };
}

// Helper to build a minimal env
function makeEnv(overrides = {}) {
  return {
    GITHUB_REPO: 'tmonk/mcp-stata',
    INSTALL_REF: 'main',
    INSTALL_SUBPATH: 'stata-agent',
    ...overrides,
  };
}

// Helper to build a minimal ctx for tests
function makeCtx() {
  return { waitUntil: () => {} };
}

// ══════════════════════════════════════════════════════════════════
// 1. sanitizeTelemetryPayload
// ══════════════════════════════════════════════════════════════════

test('sanitizeTelemetryPayload rejects unknown event types', () => {
  const raw = { event: 'something_else' };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized, null);
});

test('sanitizeTelemetryPayload rejects null/undefined input', () => {
  assert.equal(sanitizeTelemetryPayload(null, 'null'), null);
  assert.equal(sanitizeTelemetryPayload(undefined, 'undefined'), null);
});

test('sanitizeTelemetryPayload rejects non-object input', () => {
  assert.equal(sanitizeTelemetryPayload('string', '"string"'), null);
  assert.equal(sanitizeTelemetryPayload(42, '42'), null);
});

test('sanitizeTelemetryPayload returns null for missing event field', () => {
  const raw = { action: 'install' };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized, null);
});

test('sanitizeTelemetryPayload accepts all defined event types', () => {
  const events = [
    'install_start', 'install_success', 'install_failure',
    'upgrade_start', 'upgrade_success', 'upgrade_failure',
    'uninstall_start', 'uninstall_success', 'uninstall_failure',
  ];
  for (const evt of events) {
    const raw = { event: evt, install_id: 'test-' + evt };
    const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
    assert.ok(sanitized, `should accept ${evt}`);
    assert.equal(sanitized.event, evt);
  }
});

test('sanitizeTelemetryPayload accepts upgrade_* events', () => {
  const raw = { event: 'upgrade_start', install_id: 'up1', install_source: 'direct' };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.ok(sanitized);
  assert.equal(sanitized.event, 'upgrade_start');
  assert.equal(sanitized.install_source, 'direct');
});

test('sanitizeTelemetryPayload includes schema_version in sanitized output', () => {
  const raw = { event: 'install_start', install_id: 'abc', schema_version: '1' };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized.schema_version, '1');
});

test('sanitizeTelemetryPayload defaults schema_version to "1" when missing', () => {
  const raw = { event: 'install_start', install_id: 'abc' };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized.schema_version, '1');
});

test('sanitizeTelemetryPayload caps string fields to defined lengths', () => {
  // Use over-length values for fields; cap() limits to max, doesn't pad shorter strings.
  // event must be a real allowed value.
  const raw = {
    event: 'install_start',
    action: 'y'.repeat(32),
    stage: 'z'.repeat(128),
    file: 'a'.repeat(64),
    install_source: 'b'.repeat(64),
    install_id: 'c'.repeat(128),
    schema_version: '9'.repeat(16),
  };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.ok(sanitized, 'should not return null');
  assert.ok(sanitized.event.length <= 32, `event length ${sanitized.event.length} <= 32`);
  assert.equal(sanitized.action.length, 16);
  assert.ok(sanitized.stage.length <= 64, `stage length ${sanitized.stage.length} <= 64`);
  assert.equal(sanitized.file.length, 32);
  assert.equal(sanitized.install_source.length, 32);
  assert.equal(sanitized.install_id.length, 64);
  assert.equal(sanitized.schema_version.length, 8);
});

test('sanitizeTelemetryPayload strips control characters from log_tail', () => {
  const raw = {
    event: 'install_failure',
    log_tail: 'line 1\x07\x00line 2',
    install_id: 'id1',
  };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized.log_tail, 'line 1line 2');
});

test('sanitizeTelemetryPayload caps log_tail at 4000 chars', () => {
  const big = 'x'.repeat(10_000);
  const sanitized = sanitizeTelemetryPayload({
    event: 'install_failure',
    log_tail: big,
    install_id: 'id1',
  }, '');
  assert.equal(sanitized.log_tail.length, 4000);
});

test('sanitizeTelemetryPayload preserves newlines and tabs in log_tail', () => {
  const raw = {
    event: 'install_failure',
    log_tail: 'banner\n  step 1\twith tab\n  step 2\nfailure here',
    install_id: 'id1',
  };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized.log_tail, raw.log_tail);
});

test('sanitizeTelemetryPayload strips control chars but keeps newlines in log_tail', () => {
  const raw = {
    event: 'install_failure',
    log_tail: 'ok\x07\nbad\x00\x0b\r\nclean',
    install_id: 'id1',
  };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized.log_tail, 'ok\nbad\r\nclean');
});

test('sanitizeTelemetryPayload maps install_source field', () => {
  const raw = { event: 'install_start', install_id: 'abc', install_source: 'workbench' };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized.install_source, 'workbench');
});

test('sanitizeTelemetryPayload maps file field', () => {
  const raw = { event: 'install_start', install_id: 'abc', file: 'install.ps1' };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized.file, 'install.ps1');
});

// ══════════════════════════════════════════════════════════════════
// 2. buildAnalyticsDataPoint
// ══════════════════════════════════════════════════════════════════

test('buildAnalyticsDataPoint uses install_id as index', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'idx-456' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.indexes[0], 'idx-456');
});

test('buildAnalyticsDataPoint falls back to event name as index when install_id missing', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_success' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.indexes[0], 'install_success');
});

test('buildAnalyticsDataPoint maps install_source to blob[3]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', install_source: 'workbench' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[3], 'workbench');
});

test('buildAnalyticsDataPoint maps file to blob[4]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', file: 'install.ps1' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[4], 'install.ps1');
});

test('buildAnalyticsDataPoint maps event to blob[0]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'upgrade_success', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[0], 'upgrade_success');
});

test('buildAnalyticsDataPoint maps action to blob[1]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'upgrade_start', install_id: 'abc', action: 'upgrade' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[1], 'upgrade');
});

test('buildAnalyticsDataPoint infers action from event prefix', () => {
  const env = makeEnv();
  const request = makeRequest();
  // uninstall_* → 'uninstall'
  let dp = buildAnalyticsDataPoint(env, request, { event: 'uninstall_success', install_id: 'a' });
  assert.equal(dp.blobs[1], 'uninstall');
  // install_* → 'install'
  dp = buildAnalyticsDataPoint(env, request, { event: 'install_start', install_id: 'b' });
  assert.equal(dp.blobs[1], 'install');
  // upgrade_* → 'upgrade'
  dp = buildAnalyticsDataPoint(env, request, { event: 'upgrade_failure', install_id: 'c' });
  assert.equal(dp.blobs[1], 'upgrade');
});

test('buildAnalyticsDataPoint maps stage to blob[2]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', stage: 'bootstrap_uv', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[2], 'bootstrap_uv');
});

test('buildAnalyticsDataPoint maps os to blob[5]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', os: 'darwin' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[5], 'darwin');
});

test('buildAnalyticsDataPoint maps distro to blob[6]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', distro: 'macos-14' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[6], 'macos-14');
});

test('buildAnalyticsDataPoint maps arch to blob[7]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', arch: 'arm64' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[7], 'arm64');
});

test('buildAnalyticsDataPoint maps error_code to blob[8]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_failure', install_id: 'abc', error_code: 'ENOENT' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[8], 'ENOENT');
});

test('buildAnalyticsDataPoint maps tool to blob[9]', () => {
  const env = makeEnv();
  const request = makeRequest({
    headers: { 'user-agent': 'curl/8.0.0' },
  });
  const event = { event: 'install_start', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[9], 'curl');
});

test('buildAnalyticsDataPoint detects powershell tool', () => {
  const env = makeEnv();
  const request = makeRequest({
    headers: { 'user-agent': 'PowerShell/7.4.0' },
  });
  const dp = buildAnalyticsDataPoint(env, request, { event: 'install_start', install_id: 'abc' });
  assert.equal(dp.blobs[9], 'powershell');
});

test('buildAnalyticsDataPoint detects wget tool', () => {
  const env = makeEnv();
  const request = makeRequest({
    headers: { 'user-agent': 'Wget/1.21.3' },
  });
  const dp = buildAnalyticsDataPoint(env, request, { event: 'install_start', install_id: 'abc' });
  assert.equal(dp.blobs[9], 'wget');
});

test('buildAnalyticsDataPoint detects browser tool', () => {
  const env = makeEnv();
  const request = makeRequest({
    headers: { 'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' },
  });
  const dp = buildAnalyticsDataPoint(env, request, { event: 'install_start', install_id: 'abc' });
  assert.equal(dp.blobs[9], 'browser');
});

test('buildAnalyticsDataPoint defaults to "other" for unknown tool', () => {
  const env = makeEnv();
  const request = makeRequest({
    headers: { 'user-agent': 'some-unknown-client/1.0' },
  });
  const dp = buildAnalyticsDataPoint(env, request, { event: 'install_start', install_id: 'abc' });
  assert.equal(dp.blobs[9], 'other');
});

test('buildAnalyticsDataPoint maps country from cf.country to blob[10]', () => {
  const env = makeEnv();
  const request = makeRequest({ cf: { country: 'GB' } });
  const event = { event: 'install_start', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[10], 'GB');
});

test('buildAnalyticsDataPoint defaults country to "XX"', () => {
  const env = makeEnv();
  const request = makeRequest();
  const dp = buildAnalyticsDataPoint(env, request, { event: 'install_start', install_id: 'abc' });
  assert.equal(dp.blobs[10], 'XX');
});

test('buildAnalyticsDataPoint maps script_version to blob[11]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', script_version: '2.3.1' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[11], '2.3.1');
});

test('buildAnalyticsDataPoint maps user_id to blob[12]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', user_id: 'u-42' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[12], 'u-42');
});

test('buildAnalyticsDataPoint maps username to blob[13]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', username: 'tom' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[13], 'tom');
});

test('buildAnalyticsDataPoint maps machine_id to blob[14]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', machine_id: 'm-99' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[14], 'm-99');
});

test('buildAnalyticsDataPoint maps log_tail to blob[15]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_failure', install_id: 'abc', log_tail: 'Error at line 42\nStack trace' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[15], 'Error at line 42\nStack trace');
});

test('buildAnalyticsDataPoint maps network to blob[16]', () => {
  const env = makeEnv();
  const request = makeRequest({ cf: { asn: 12345, asOrganization: 'Cloudflare' } });
  const event = { event: 'install_start', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[16], '12345 Cloudflare');
});

test('buildAnalyticsDataPoint maps repo@ref to blob[17]', () => {
  const env = makeEnv({ GITHUB_REPO: 'tmonk/mcp-stata', INSTALL_REF: 'v2.0.0' });
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[17], 'tmonk/mcp-stata@v2.0.0');
});

test('buildAnalyticsDataPoint maps schema_version to blob[18]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', schema_version: '1' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[18], '1');
});

test('buildAnalyticsDataPoint defaults schema_version to "1" in blob[18]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[18], '1');
});

test('buildAnalyticsDataPoint has 20 blobs total', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs.length, 20);
  // blob[19] is reserved
  assert.equal(dp.blobs[19], '');
});

test('buildAnalyticsDataPoint has 4 doubles', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.doubles.length, 4);
  assert.equal(dp.doubles[0], 1); // row count
});

test('buildAnalyticsDataPoint maps duration_ms to doubles[1]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc', duration_ms: 3500 };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.doubles[1], 3500);
});

test('buildAnalyticsDataPoint maps log_tail bytes to doubles[2]', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_failure', install_id: 'abc', log_tail: 'hello world' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.doubles[2], 'hello world'.length);
});

test('buildAnalyticsDataPoint maps bot score to doubles[3]', () => {
  const env = makeEnv();
  const request = makeRequest({ cf: { botManagement: { score: 87 } } });
  const event = { event: 'install_start', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.doubles[3], 87);
});

test('buildAnalyticsDataPoint defaults bot score to 0', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start', install_id: 'abc' };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.doubles[3], 0);
});

test('buildAnalyticsDataPoint defaults empty fields gracefully', () => {
  const env = makeEnv();
  const request = makeRequest();
  const event = { event: 'install_start' }; // minimal
  const dp = buildAnalyticsDataPoint(env, request, event);
  // Should not throw; all blobs should be strings or empty
  for (let i = 0; i < 20; i++) {
    assert.ok(typeof dp.blobs[i] === 'string', `blob[${i}] should be string, got ${typeof dp.blobs[i]}: "${dp.blobs[i]}"`);
  }
  for (let i = 0; i < 4; i++) {
    assert.ok(typeof dp.doubles[i] === 'number', `doubles[${i}] should be number`);
  }
});

test('buildAnalyticsDataPoint real-world install_failure payload', () => {
  const env = makeEnv();
  const request = makeRequest({
    cf: { country: 'US', botManagement: { score: 0 } },
  });
  const event = {
    event: 'install_failure',
    action: 'install',
    stage: 'ensure_uv',
    error_code: 'Could not install uv via astral.sh',
    install_id: 'i-1',
    schema_version: '1',
    log_tail:
      '======\n' +
      'BOOTSTRAP RUNTIME\n' +
      '======\n' +
      'Installing uv\n' +
      '    • Bootstrap via https://astral.sh/uv/install.sh\n' +
      'curl: (28) Operation timed out after 30001 ms\n' +
      'sh: error: failed to download uv\n',
  };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[0], 'install_failure');
  assert.equal(dp.blobs[8], 'Could not install uv via astral.sh');
  assert.ok(dp.blobs[15].includes('curl: (28) Operation timed out'));
  assert.ok(dp.blobs[15].includes('BOOTSTRAP RUNTIME'));
  assert.equal(dp.doubles[2], event.log_tail.length);
  assert.equal(dp.blobs[18], '1');
});

// ══════════════════════════════════════════════════════════════════
// 3. serveLatestJson
// ══════════════════════════════════════════════════════════════════

test('serveLatestJson returns version, min_supported, denylist, emergency_disable', () => {
  const env = makeEnv();
  // For unit tests, serveLatestJson reads from env vars (mockable)
  const result = serveLatestJson(env);
  const body = JSON.parse(result.body);
  assert.ok(typeof body.version === 'string');
  assert.ok(typeof body.min_supported === 'string');
  assert.ok(Array.isArray(body.denylist));
  assert.equal(typeof body.emergency_disable, 'boolean');
  assert.ok(typeof body.published_at === 'string');
});

test('serveLatestJson includes published_at ISO8601 timestamp', () => {
  const env = makeEnv();
  const result = serveLatestJson(env);
  const body = JSON.parse(result.body);
  // Should be a valid ISO8601 date string
  const date = new Date(body.published_at);
  assert.ok(!isNaN(date.getTime()));
});

test('serveLatestJson returns correct content-type', () => {
  const env = makeEnv();
  const result = serveLatestJson(env);
  assert.ok(result.headers['content-type'].includes('application/json'));
});

test('serveLatestJson has cache-control header with 60s TTL', () => {
  const env = makeEnv();
  const result = serveLatestJson(env);
  assert.ok(result.headers['cache-control'].includes('max-age=60') || result.headers['cache-control'].includes('s-maxage=60'));
});

test('serveLatestJson denylist is an array', () => {
  const env = makeEnv();
  const result = serveLatestJson(env);
  const body = JSON.parse(result.body);
  assert.ok(Array.isArray(body.denylist));
});

test('serveLatestJson emergency_disable is boolean', () => {
  const env = makeEnv();
  const result = serveLatestJson(env);
  const body = JSON.parse(result.body);
  assert.equal(typeof body.emergency_disable, 'boolean');
});

// ══════════════════════════════════════════════════════════════════
// 4. Rate limiting
// ══════════════════════════════════════════════════════════════════

test('handleRateLimit returns null when under rate limit', () => {
  const env = makeEnv();
  // First request from an IP
  const result = handleRateLimit('192.168.1.1', 'telemetry', env);
  assert.equal(result, null);
});

test('handleRateLimit returns 429 when rate limit exceeded', () => {
  const env = makeEnv();
  const ip = '10.0.0.99';
  // Fire 11 requests (telemetry limit is 10/min)
  for (let i = 0; i < 11; i++) {
    handleRateLimit(ip, 'telemetry', env);
  }
  const result = handleRateLimit(ip, 'telemetry', env);
  assert.notEqual(result, null);
  assert.ok(result.status >= 429);
});

// ══════════════════════════════════════════════════════════════════
// 5. serveLatestJson (exported for testing)
// ══════════════════════════════════════════════════════════════════

// Additional export-level tests are covered in section 3 above.
