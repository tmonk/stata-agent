/**
 * stata-agent installer service. Deployed to https://stata-agent-install.tdmonk.com/
 *
 * Routes:
 *   GET  /install.sh              bash installer (from GitHub, edge-cached)
 *   GET  /install.ps1             PowerShell installer (from GitHub, edge-cached)
 *   GET  /v/:version/install.sh   pinned-version bash installer
 *   GET  /v/:version/install.ps1  pinned-version PowerShell installer
 *   GET  /latest.json             version metadata (denylist, emergency_disable)
 *   POST /telemetry               install/upgrade/uninstall events
 *   GET  /                        info page
 *   GET  /health                  liveness probe
 *
 * Configuration (wrangler.toml [vars]):
 *   GITHUB_REPO         'owner/name'. Default 'tmonk/stata-agent'.
 *   INSTALL_REF         git ref to serve. Default 'main'.
 *   INSTALL_SUBPATH     path within the repo. Default 'stata-agent'.
 *
 * Bindings:
 *   STATA_AGENT          Analytics Engine dataset (optional).
 */

const DEFAULTS = {
  GITHUB_REPO: 'tmonk/stata-agent',
  INSTALL_REF: 'main',
  INSTALL_SUBPATH: 'stata-agent',
};

const SCRIPT_CACHE_TTL = 300; // 5 minutes
const LATEST_JSON_CACHE_TTL = 60; // 60 seconds

const TELEMETRY_MAX_BYTES = 32 * 1024; // 32 KB

const ALLOWED_EVENTS = new Set([
  'install_start', 'install_success', 'install_failure',
  'upgrade_start', 'upgrade_success', 'upgrade_failure',
  'uninstall_start', 'uninstall_success', 'uninstall_failure',
]);

const SECURITY_HEADERS = {
  'strict-transport-security': 'max-age=63072000; includeSubDomains',
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'no-referrer',
};

// Rate limit state (per-request ephemeral, resets on cold start — acceptable for this use case)
const rateLimitCache = new Map();

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const pathname = url.pathname;

    try {
      // ── Pinned version routes ──────────────────────────────────────────
      const pinnedMatch = pathname.match(/^\/v\/([^/]+)\/(install\.(?:sh|ps1))$/);
      if (pinnedMatch) {
        return serveScript(request, env, ctx, pinnedMatch[2], pinnedMatch[1]);
      }

      // ── Named routes ───────────────────────────────────────────────────
      switch (pathname) {
        case '/install.sh':
          return serveScript(request, env, ctx, 'install.sh');
        case '/install.ps1':
          return serveScript(request, env, ctx, 'install.ps1');
        case '/latest.json':
          return serveLatestJsonHandler(request, env, ctx);
        case '/telemetry':
          return handleTelemetry(request, env, ctx);
        case '/':
          return serveIndex(request, env);
        case '/health':
          return new Response('ok\n', {
            headers: { 'content-type': 'text/plain' },
          });
        default:
          return new Response('Not found\n', {
            status: 404,
            headers: { 'content-type': 'text/plain' },
          });
      }
    } catch (err) {
      console.error('worker error', err.stack || String(err));
      return new Response('Internal error\n', {
        status: 500,
        headers: { 'content-type': 'text/plain' },
      });
    }
  },
};

// ── Script delivery ──────────────────────────────────────────────────────────

async function serveScript(request, env, ctx, file, version) {
  const repo = env.GITHUB_REPO || DEFAULTS.GITHUB_REPO;
  const ref = env.INSTALL_REF || DEFAULTS.INSTALL_REF;
  const subpath = env.INSTALL_SUBPATH || DEFAULTS.INSTALL_SUBPATH;

  // Pinned-version: use the tag as ref
  const effectiveRef = version || ref;
  // Scripts live at repo root within the subpath
  const upstreamUrl = `https://raw.githubusercontent.com/${repo}/${effectiveRef}/${subpath}/${file}`;

  const cacheTtl = version ? 86400 : SCRIPT_CACHE_TTL; // immutable for pinned, 5 min for latest

  const upstream = await fetch(upstreamUrl, {
    cf: {
      cacheTtl,
      cacheEverything: true,
    },
  });

  if (!upstream.ok) {
    console.error(`upstream ${upstream.status} for ${upstreamUrl}`);
    ctx.waitUntil(
      recordEvent(env, request, {
        event: 'install_failure',
        stage: 'serve_script',
        error_code: `upstream_${upstream.status}`,
        file,
      }),
    );
    return new Response(
      `Could not fetch ${file} (HTTP ${upstream.status}).\n` +
        `Fall back: git clone https://github.com/${repo}\n`,
      {
        status: 502,
        headers: { 'content-type': 'text/plain' },
      },
    );
  }

  const body = await upstream.text();

  ctx.waitUntil(
    recordEvent(env, request, {
      event: 'install_start',
      stage: 'fetch_script',
      file,
    }),
  );

  return new Response(body, {
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      'cache-control': `public, max-age=${cacheTtl}`,
      'x-stata-agent-ref': effectiveRef,
      ...SECURITY_HEADERS,
    },
  });
}

// ── Latest version endpoint ───────────────────────────────────────────────────

export function serveLatestJson(requestOrEnv, env, ctx) {
  // Handle both direct calls (from tests) and worker invocations
  let effectiveEnv = env;
  if (requestOrEnv && typeof requestOrEnv === 'object' && !env) {
    // Called as serveLatestJson(env) from tests
    effectiveEnv = requestOrEnv;
  }

  const version = effectiveEnv?.LATEST_VERSION || '0.1.0';
  const minSupported = effectiveEnv?.MIN_SUPPORTED || '0.1.0';
  const denylistRaw = effectiveEnv?.DENYLIST || '[]';
  const emergencyDisable = effectiveEnv?.EMERGENCY_DISABLE === 'true';

  let denylist;
  try {
    denylist = JSON.parse(denylistRaw);
    if (!Array.isArray(denylist)) denylist = [];
  } catch {
    denylist = [];
  }

  const body = JSON.stringify({
    version,
    min_supported: minSupported,
    denylist,
    emergency_disable: emergencyDisable,
    published_at: new Date().toISOString(),
  }, null, 2);

  return {
    body,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': `public, max-age=${LATEST_JSON_CACHE_TTL}`,
      ...SECURITY_HEADERS,
    },
  };
}

async function serveLatestJsonHandler(request, env, ctx) {
  const result = serveLatestJson(request, env);

  let body = result.body;
  if (typeof body !== 'string') {
    body = JSON.stringify(body);
  }

  return new Response(body, {
    headers: result.headers,
  });
}

// ── Telemetry ────────────────────────────────────────────────────────────────

async function handleTelemetry(request, env, ctx) {
  // CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: corsHeaders(),
    });
  }

  if (request.method !== 'POST') {
    return new Response('Method not allowed\n', {
      status: 405,
      headers: { allow: 'POST', 'content-type': 'text/plain' },
    });
  }

  // Rate limiting: 10 req/min per IP for telemetry
  const ip = request.headers.get('cf-connecting-ip') || 'unknown';
  const rateResult = handleRateLimit(ip, 'telemetry', env);
  if (rateResult) return rateResult;

  const length = parseInt(request.headers.get('content-length') || '0', 10);
  if (length > TELEMETRY_MAX_BYTES) {
    return new Response('Payload too large\n', { status: 413 });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return new Response('Invalid JSON\n', { status: 400 });
  }

  const event = sanitizeEvent(body);
  if (!event) {
    return new Response('Invalid payload\n', { status: 400 });
  }

  const result = await recordEvent(env, request, event);

  return new Response(JSON.stringify({ ok: true, ...result }), {
    headers: {
      'content-type': 'application/json',
      ...corsHeaders(),
    },
  });
}

export function sanitizeTelemetryPayload(body, _rawJson) {
  return sanitizeEvent(body);
}

function sanitizeEvent(body) {
  if (!body || typeof body !== 'object') return null;
  if (!body.event || !ALLOWED_EVENTS.has(body.event)) return null;

  // Strip control characters; cap lengths so a misbehaving client can't blow
  // up our row size.
  const cap = (s, n) =>
    typeof s === 'string' ? s.slice(0, n).replace(/[\x00-\x1f]/g, '') : '';
  const num = (n) => (typeof n === 'number' && Number.isFinite(n) ? n : 0);

  // Allow newlines/tabs in log_tail; strip other control chars.
  const capLog = (s, n) =>
    typeof s === 'string'
      ? s.slice(0, n).replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '')
      : '';

  const schemaVersion = cap(body.schema_version || '1', 8);

  return {
    event:           cap(body.event, 32),
    action:          cap(body.action, 16),
    stage:           cap(body.stage, 64),
    file:            cap(body.file, 32),
    install_source:  cap(body.install_source, 32),
    scope:           cap(body.scope, 16),
    os:              cap(body.os, 32),
    distro:          cap(body.distro, 64),
    arch:            cap(body.arch, 16),
    error_code:      cap(body.error_code, 128),
    duration_ms:     num(body.duration_ms),
    install_id:      cap(body.install_id, 64),
    user_id:         cap(body.user_id, 32),
    username:        cap(body.username, 64),
    machine_id:      cap(body.machine_id, 64),
    script_version:  cap(body.script_version, 32),
    schema_version:  schemaVersion,
    log_tail:        capLog(body.log_tail || '', 4000),
  };
}

export function buildAnalyticsDataPoint(env, request, event) {
  const country = request.cf?.country || 'XX';
  const asn = request.cf?.asn ? String(request.cf.asn) : '';
  const asOrg = request.cf?.asOrganization || request.cf?.as_organization || '';
  const tool = detectClientTool(request.headers?.get?.('user-agent') || '');
  const repo = (env && env.GITHUB_REPO) || DEFAULTS.GITHUB_REPO;
  const ref = (env && env.INSTALL_REF) || DEFAULTS.INSTALL_REF;
  const installId = event.install_id || '';

  const botScore = request.cf?.botManagement?.score || 0;
  const logBytes = event.log_tail ? event.log_tail.length : 0;

  let action = event.action || '';
  if (!action) {
    if (event.event.startsWith('uninstall_')) action = 'uninstall';
    else if (event.event.startsWith('upgrade_')) action = 'upgrade';
    else action = 'install';
  }

  const schemaVersion = event.schema_version || '1';

  return {
    // 20 blobs
    blobs: [
      event.event,                                // 0: event
      action,                                     // 1: action
      event.stage || '',                          // 2: stage
      event.install_source || '',                 // 3: install_source
      event.file || '',                           // 4: file (install.sh | install.ps1)
      event.os || '',                             // 5: os
      event.distro || '',                         // 6: distro
      event.arch || '',                           // 7: arch
      event.error_code || '',                     // 8: error_code
      tool,                                       // 9: tool
      country,                                    // 10: country
      event.script_version || '',                 // 11: script_version
      event.user_id || '',                        // 12: user_id
      event.username || '',                       // 13: username
      event.machine_id || '',                     // 14: machine_id
      event.log_tail || '',                       // 15: log_tail
      `${asn} ${asOrg}`.trim().slice(0, 256),      // 16: network
      `${repo}@${ref}`.slice(0, 256),             // 17: repo@ref
      schemaVersion,                              // 18: schema_version
      '',                                         // 19: reserved
    ],
    // 4 doubles
    doubles: [
      1,                                           // 0: row count
      event.duration_ms || 0,                      // 1: duration_ms
      logBytes || 0,                               // 2: log_tail bytes
      botScore || 0,                               // 3: bot score
    ],
    indexes: [installId || event.event],
  };
}

async function recordEvent(env, request, event) {
  const dataPoint = buildAnalyticsDataPoint(env, request, event);

  if (!env || !env.STATA_AGENT) {
    console.log('event', { ...event, index1: dataPoint.indexes?.[0] || '' });
    return { stored: false, sink: 'console', index1: dataPoint.indexes?.[0] || '' };
  }

  try {
    env.STATA_AGENT.writeDataPoint(dataPoint);
    return { stored: true, sink: 'analytics_engine', index1: dataPoint.indexes?.[0] || '' };
  } catch (err) {
    console.error('metrics write failed', err.stack || String(err));
    return { stored: false, sink: 'analytics_engine', index1: dataPoint.indexes?.[0] || '', error: 'write_failed' };
  }
}

// ── Rate limiting ────────────────────────────────────────────────────────────

export function handleRateLimit(ip, endpoint, env) {
  const now = Date.now();
  const key = `rate:${endpoint}:${ip}`;

  let entry = rateLimitCache.get(key);
  if (!entry || now - entry.windowStart > 60_000) {
    // New 60-second window
    entry = { windowStart: now, count: 0 };
    rateLimitCache.set(key, entry);
  }

  entry.count++;

  const limits = {
    telemetry: 10,
    latest_json: 60,
  };

  const limit = limits[endpoint];
  if (limit && entry.count > limit) {
    return new Response('Rate limited\n', {
      status: 429,
      headers: {
        'content-type': 'text/plain',
        'retry-after': '60',
      },
    });
  }

  return null; // under limit
}

// ── Tool detection ───────────────────────────────────────────────────────────

function detectClientTool(ua) {
  const lower = (ua || '').toLowerCase();
  if (lower.startsWith('curl/')) return 'curl';
  if (lower.startsWith('wget/')) return 'wget';
  if (lower.includes('powershell')) return 'powershell';
  if (lower.includes('mozilla')) return 'browser';
  return 'other';
}

// ── CORS ─────────────────────────────────────────────────────────────────────

function corsHeaders() {
  return {
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'POST, GET, OPTIONS',
    'access-control-allow-headers': 'content-type',
    'access-control-max-age': '86400',
  };
}

// ── Index page ───────────────────────────────────────────────────────────────

function serveIndex(request, env) {
  const ref = env.INSTALL_REF || DEFAULTS.INSTALL_REF;
  const repo = env.GITHUB_REPO || DEFAULTS.GITHUB_REPO;
  const host = new URL(request.url).host;

  const body = `stata-agent installer service

Serving: ${repo}@${ref}

  Linux / macOS:
    curl -fsSL https://${host}/install.sh | bash

  Windows:
    irm https://${host}/install.ps1 | iex

Pinned version (e.g., v1.2.3):
  curl -fsSL https://${host}/v/1.2.3/install.sh | bash

  Version metadata:
    curl -fsSL https://${host}/latest.json

Source: https://github.com/${repo}
`;

  return new Response(body, {
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      ...SECURITY_HEADERS,
    },
  });
}
