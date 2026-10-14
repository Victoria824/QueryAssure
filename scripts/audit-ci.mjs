import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const policy = JSON.parse(readFileSync("security/audit-exceptions.json", "utf8"));
const audit = spawnSync("npm", ["audit", "--json"], { encoding: "utf8" });
if (!audit.stdout) throw new Error(audit.stderr || "npm audit produced no JSON");

const report = JSON.parse(audit.stdout);
const advisories = new Map();
for (const vulnerability of Object.values(report.vulnerabilities ?? {})) {
  for (const item of vulnerability.via ?? []) {
    if (typeof item === "object" && ["high", "critical"].includes(item.severity)) {
      advisories.set(String(item.source), item);
    }
  }
}

const exceptions = new Map(policy.exceptions.map((item) => [String(item.source), item]));
const today = new Date().toISOString().slice(0, 10);
const unknown = [...advisories.keys()].filter((source) => !exceptions.has(source));
const expired = [...advisories.keys()].filter((source) => exceptions.get(source)?.expires < today);

for (const [source, advisory] of advisories) {
  const exception = exceptions.get(source);
  if (exception && exception.expires >= today) {
    console.log(`ACCEPTED UNTIL ${exception.expires}: ${advisory.name} ${advisory.url}`);
  }
}
if (unknown.length || expired.length) {
  console.error(`Unapproved advisories: ${unknown.join(", ") || "none"}`);
  console.error(`Expired exceptions: ${expired.join(", ") || "none"}`);
  process.exit(1);
}
console.log("AUDIT POLICY PASSED: known exceptions are documented; new high/critical advisories still fail CI");
