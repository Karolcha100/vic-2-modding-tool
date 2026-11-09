// Drive a headless Firefox (WebDriver BiDi, no extra packages) to check the GUI:
// open a URL, run optional steps, collect console errors, save a screenshot.
//
//   node scripts/snapshot.mjs <url> <out.png> [steps.json]
//
// steps.json: [{"eval": "<js expression, may return a promise>"}, {"wait": 1500}, ...]
// Firefox must be running: firefox --headless --remote-debugging-port 9222 --profile <dir>
import { readFileSync, writeFileSync } from "node:fs";

const [url, out, stepsFile] = process.argv.slice(2);
const steps = stepsFile ? JSON.parse(readFileSync(stepsFile, "utf8")) : [];
const ws = new WebSocket("ws://127.0.0.1:9222/session");
let id = 0;
const pending = new Map();
const logs = [];

ws.onmessage = (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.type === "error" ? reject(new Error(`${msg.error}: ${msg.message}`)) : resolve(msg.result);
  } else if (msg.method === "log.entryAdded") {
    const e = msg.params;
    logs.push(`[${e.level}] ${e.text ?? ""}${e.stackTrace ? "" : ""}`);
  }
};
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const n = ++id;
    pending.set(n, { resolve, reject });
    ws.send(JSON.stringify({ id: n, method, params }));
  });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

ws.onopen = async () => {
  try {
    await send("session.new", { capabilities: {} });
    await send("session.subscribe", { events: ["log.entryAdded"] });
    const tree = await send("browsingContext.getTree", {});
    const context = tree.contexts[0].context;
    await send("browsingContext.setViewport", { context, viewport: { width: 1500, height: 900 } });
    await send("browsingContext.navigate", { context, url, wait: "complete" });
    await sleep(1500);
    for (const step of steps) {
      if (step.wait) await sleep(step.wait);
      if (step.eval) {
        const r = await send("script.evaluate", {
          expression: step.eval, target: { context }, awaitPromise: true,
        });
        if (r.type === "exception") logs.push(`[step exception] ${JSON.stringify(r.exceptionDetails?.text)}`);
        else if (r.result?.value !== undefined) logs.push(`[step] ${JSON.stringify(r.result.value).slice(0, 400)}`);
      }
    }
    const shot = await send("browsingContext.captureScreenshot", { context });
    writeFileSync(out, Buffer.from(shot.data, "base64"));
    console.log(logs.join("\n") || "(no console messages)");
    await send("session.end", {});
  } catch (e) {
    console.error("snapshot failed:", e.message);
    process.exitCode = 1;
  } finally {
    ws.close();
  }
};
