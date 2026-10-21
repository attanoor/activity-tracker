import { execFileSync } from "node:child_process";
import path from "node:path";

export default function globalSetup() {
  const root = path.resolve(__dirname, "..", "..", "..");
  execFileSync(path.join(root, ".venv", "Scripts", "python.exe"), ["-m", "app.cli", "e2e-setup"],
    { cwd: path.join(root, "apps", "api"), stdio: "inherit" });
}
