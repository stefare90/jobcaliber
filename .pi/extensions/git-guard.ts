/**
 * git-guard — constrains the agent's git operations and requires user approval
 * before anything enters history or leaves the machine.
 *
 * Policy:
 *  - read-only (status/diff/log/show/blame/rev-parse/remote/ls-files/...): allowed
 *  - non-destructive writes (add/commit/switch/checkout -b/branch/tag/stash/pull/fetch/...):
 *      ALWAYS ask the user with a Conferma/Rifiuta menu
 *  - destructive (reset, clean, branch -d/-D, checkout -- path, restore, rebase,
 *      merge, push --force, worktree, filter-branch, config <set>): ALWAYS blocked
 *  - push: Conferma/Rifiuta menu with a branch -> remote summary
 *  - git outside the session repo: blocked
 *  - session outside a repo (e.g. workspace root): all writes blocked
 *  - non-interactive session: all writes blocked (no way to ask)
 *  - commit message: conventional commits, non-conforming => blocked
 *  - every rejection asks the user for a reason and hands it to the agent
 *
 * Known limit: this guard inspects bash commands; an agent that evades via
 * `python -c` / `sh -c` is not intercepted (mitigated by the AGENTS.md rules).
 */

import { spawnSync } from "node:child_process";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const COMMIT_SUBJECT_RE =
	/^(feat|fix|refactor|docs|test|chore|perf|style|build|ci)(\([a-z0-9._/-]+\))?!?: \S.{0,71}$/;

type Op = "read" | "write" | "destructive" | "push";

type Pending = {
	op: Op;
	seg: string;
	commit: { message: string; amend: boolean } | null;
};

const READ_ONLY = new Set([
	"status", "diff", "log", "show", "blame", "rev-parse", "describe",
	"ls-files", "grep", "help", "version", "cat-file", "diff-tree",
	"ls-remote", "var", "check-ignore", "count-objects",
]);

const DESTRUCTIVE_SUB = new Set([
	"reset", "clean", "rebase", "restore", "merge", "worktree", "filter-branch",
	"notes", "replace", "bisect",
]);

const WRITE_SUB = new Set([
	"add", "rm", "mv", "commit", "switch", "checkout", "branch", "tag",
	"stash", "pull", "fetch", "apply", "config", "gc", "prune", "init",
]);

const repoRootCache = new Map<string, string | null>();

function runGit(cwd: string, args: string[]): { ok: boolean; out: string } {
	const r = spawnSync("git", args, { cwd, encoding: "utf-8" });
	if (r.error || r.status !== 0) {
		return { ok: false, out: String(r.stderr ?? r.stdout ?? r.error ?? "").trim() };
	}
	return { ok: true, out: String(r.stdout ?? "").trim() };
}

function gitRoot(cwd: string): string | null {
	if (repoRootCache.has(cwd)) return repoRootCache.get(cwd) ?? null;
	const r = runGit(cwd, ["rev-parse", "--show-toplevel"]);
	const root = r.ok ? r.out : null;
	repoRootCache.set(cwd, root);
	return root;
}

function splitSegments(command: string): string[] {
	return command
		.split(/\r?\n|&&|\|\||;|\|/)
		.map((s) => s.trim())
		.filter((s) => s.length > 0);
}

function tokenize(segment: string): string[] {
	return segment.trim().split(/\s+/).filter(Boolean);
}

function gitTokens(segment: string): string[] | null {
	const t = tokenize(segment);
	if (t.length === 0) return null;
	const first = t[0].replace(/^["']|["']$/g, "");
	if (first !== "git") return null;
	return t;
}

function dirOverride(tokens: string[]): string | null {
	for (let i = 0; i < tokens.length; i++) {
		if (tokens[i] === "-C" && tokens[i + 1]) return tokens[i + 1];
	}
	return null;
}

function subcommandIndex(args: string[]): number {
	const takesValue = new Set(["-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"]);
	const takesValueEq = /^(--git-dir|--work-tree|--namespace|--exec-path|--super-prefix)=/;
	const valueless = new Set(["--no-pager", "-p", "--paginate", "--bare", "--literal-pathspecs", "--no-replace-objects"]);
	for (let i = 0; i < args.length; i++) {
		const a = args[i];
		if (takesValue.has(a)) {
			i++;
			continue;
		}
		if (takesValueEq.test(a) || valueless.has(a)) continue;
		if (a.startsWith("-")) continue;
		return i;
	}
	return -1;
}

/** Subcommand of a git command (skipping global flags), or "" when none. */
function subcommandOf(args: string[]): string {
	const idx = subcommandIndex(args);
	if (idx < 0) return "";
	return args[idx].replace(/^["']|["']$/g, "");
}

/** Commit message read from the raw segment text (tokenizer ignores quotes). */
function commitMessageFromSegment(segment: string): string | null {
	const re = /(?:^|\s)(?:-[a-zA-Z]*m|--message)(?:=|\s+)?(?:"([^"]*)"|'([^']*)'|(\S+))/;
	const m = segment.match(re);
	if (!m) return null;
	return m[1] ?? m[2] ?? m[3] ?? null;
}

function isDisplayOnly(rest: string[]): boolean {
	if (rest.length === 0) return true;
	if (rest.some((a) => !a.startsWith("-"))) return false;
	return rest.every((a) =>
		/^(-[arlvni]+|--(list|show-current|all|remotes|verbose|contains|no-contains|merged|no-merged|points-at|sort|format|column|abbrev|ignore-case))/.test(
			a,
		),
	);
}

function classify(args: string[]): Op | "unknown" {
	const idx = subcommandIndex(args);
	if (idx < 0) return "unknown";
	const sub = args[idx].replace(/^["']|["']$/g, "");
	const rest = args.slice(idx + 1);
	if (!sub) return "unknown";

	if (sub === "push") {
		if (rest.some((a) => /^--force(-with-lease)?$/.test(a))) return "destructive";
		return "push";
	}
	if (READ_ONLY.has(sub)) return "read";

	if (sub === "remote") {
		const head = rest[0];
		const display = head === undefined || ["-v", "--verbose", "-n", "show", "get-url"].includes(head);
		return display ? "read" : "write";
	}
	if (sub === "reflog") {
		if (rest.length === 0 || rest[0] === "show") return "read";
		if (rest[0] === "delete" || rest[0] === "expire") return "destructive";
		return "write";
	}
	if (sub === "symbolic-ref") {
		return rest.length <= 1 ? "read" : "write";
	}
	if (sub === "branch") {
		if (rest.some((a) => /^(-[dD]|--delete(-force)?$)/.test(a))) return "destructive";
		return isDisplayOnly(rest) ? "read" : "write";
	}
	if (sub === "tag") {
		if (rest.some((a) => /^(-[dD]|--delete)/.test(a))) return "destructive";
		return isDisplayOnly(rest) ? "read" : "write";
	}
	if (DESTRUCTIVE_SUB.has(sub)) return "destructive";

	if (sub === "checkout") {
		if (rest.length === 0) return "read";
		if (rest.includes("--")) return "destructive";
		if (rest.some((a) => a === "-b" || a === "-B" || a === "-t" || a === "--track")) return "write";
		if (rest.every((a) => !a.startsWith("-"))) return rest.length === 1 ? "write" : "destructive";
		return "destructive";
	}
	if (sub === "stash") {
		if (rest.length === 0 || rest[0] === "list" || rest[0] === "show") return "read";
		if (rest[0] === "drop" || rest[0] === "clear") return "destructive";
		return "write";
	}
	if (WRITE_SUB.has(sub)) return "write";
	return "unknown";
}

function describe(op: Op, raw: string, cwd: string): string {
	if (op !== "push") return raw;
	const b = runGit(cwd, ["rev-parse", "--abbrev-ref", "HEAD"]);
	const r = runGit(cwd, ["remote", "get-url", "origin"]);
	const branch = b.ok ? b.out : "(unknown)";
	const remote = r.ok ? r.out : "(no 'origin' remote)";
	return `push -> branch "${branch}" to ${remote}`;
}

function formatChanges(cwd: string, extra: string[], maxFiles = 12): { files: string[]; stat: string } {
	const ns = runGit(cwd, ["diff", ...extra, "--name-status"]);
	const st = runGit(cwd, ["diff", ...extra, "--stat"]);
	const files: string[] = [];
	if (ns.ok && ns.out) {
		const all = ns.out.split("\n").filter((l) => l.trim().length > 0);
		for (const line of all.slice(0, maxFiles)) files.push("  " + line.replace(/\t/g, "  "));
		if (all.length > maxFiles) files.push(`  ... (+${all.length - maxFiles})`);
	}
	const statLines = st.ok && st.out ? st.out.split("\n").filter((l) => l.trim().length > 0) : [];
	return { files, stat: (statLines[statLines.length - 1] ?? "").trim() };
}

function formatWorkingTree(cwd: string, maxFiles = 12): { files: string[]; stat: string } {
	const ss = runGit(cwd, ["status", "--short", "--untracked-files=all"]);
	const st = runGit(cwd, ["diff", "HEAD", "--stat"]);
	const files: string[] = [];
	if (ss.ok && ss.out) {
		const all = ss.out.split("\n").filter((l) => l.trim().length > 0);
		for (const line of all.slice(0, maxFiles)) files.push("  " + line.trim());
		if (all.length > maxFiles) files.push(`  ... (+${all.length - maxFiles})`);
	}
	const statLines = st.ok && st.out ? st.out.split("\n").filter((l) => l.trim().length > 0) : [];
	return { files, stat: (statLines[statLines.length - 1] ?? "").trim() };
}

function commitDialogBody(cwd: string, message: string, chainStages: boolean, amend: boolean): string {
	const { files, stat } = chainStages ? formatWorkingTree(cwd) : formatChanges(cwd, ["--cached"]);
	const out: string[] = [];
	out.push(`Message:  ${message}`);
	out.push("");
	out.push(chainStages ? "Working-tree changes (after `git add`):" : "Staged files:");
	out.push(...(files.length > 0 ? files : ["  (none: the commit would be empty)"]));
	if (stat) {
		out.push("");
		out.push("  " + stat);
	}
	if (amend) out.push("", "--amend: rewrites the last commit (no new commit is created)");
	return out.join("\n");
}

/** Ask the user why they rejected, and return the reason for the agent. */
async function askRejectReason(ctx: ExtensionContext, what: string): Promise<string> {
	const reason = await ctx.ui.input(`Reason for rejecting ${what}? (sent to the agent)`, "e.g. wrong message, missing files, not ready");
	const trimmed = (reason ?? "").trim();
	return trimmed.length > 0 ? trimmed : "(no reason given)";
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "bash") return undefined;
		const command = String(event.input.command ?? "");
		if (!/(^|[\s;&|(])git\s/.test(command)) return undefined;

		const sessionCwd = ctx.cwd;
		const repoRoot = gitRoot(sessionCwd);

		const writes: Pending[] = [];
		let blockReason: string | null = null;

		const chainStages = splitSegments(command).some((s) => {
			const t = gitTokens(s);
			if (!t) return false;
			const sub = subcommandOf(t.slice(1));
			return sub === "add" || sub === "rm" || sub === "mv";
		});

		for (const seg of splitSegments(command)) {
			const tokens = tokenize(seg);
			if (tokens.length === 0) continue;
			let commitInfo: { message: string; amend: boolean } | null = null;
			const first = tokens[0].replace(/^["']|["']$/g, "");
			if (first !== "git") {
				if (/\bgit\b/.test(seg) && /^sudo\b/.test(first)) {
					blockReason = "Blocked: commands with `sudo` are not allowed.";
					break;
				}
				continue;
			}

			const args = tokens.slice(1);
			const op = classify(args);

			const dirFlag = dirOverride(args);
			const targetDir = dirFlag ? path.resolve(sessionCwd, dirFlag) : sessionCwd;
			if (op !== "read") {
				if (!repoRoot) {
					blockReason =
						"Blocked: the session directory is not a git repository. No git writes are allowed here.";
					break;
				}
				const targetRoot = dirFlag
					? (runGit(targetDir, ["rev-parse", "--show-toplevel"]).out || null)
					: repoRoot;
				if (targetRoot !== repoRoot) {
					blockReason = `Blocked: git operation outside your project (repo "${targetRoot ?? dirFlag}" != "${repoRoot}").`;
					break;
				}
			}

			if (op === "read") continue;

			if (op === "destructive") {
				blockReason = `Blocked: \`git ${args[0]}\` is destructive (rewrites or discards history). Run it yourself if truly needed.`;
				break;
			}

			if (op === "write" && subcommandOf(args) === "commit") {
				if (args.some((a) => /^--file/.test(a))) {
					blockReason = `Blocked: use \`git commit -m "<message>"\` with the <type>(<scope>): <subject> convention.`;
					break;
				}
				const msg = commitMessageFromSegment(seg);
				if (msg === null || msg.trim() === "") {
					blockReason = `Blocked: commit message is mandatory. Use \`git commit -m "<type>(<scope>): <subject>"\` (types: feat fix refactor docs test chore perf style build ci).`;
					break;
				}
				const subject = msg.split(/\r?\n/)[0].trim();
				if (!COMMIT_SUBJECT_RE.test(subject)) {
					blockReason =
						`Blocked: commit message does not conform.\n` +
						`   Found:  "${subject}"\n` +
						`   Expect: <type>(<scope>): <subject>\n` +
						`   Types: feat fix refactor docs test chore perf style build ci\n` +
						`   Subject: imperative, lowercase, no trailing period, max 72 chars.`;
					break;
				}
				commitInfo = { message: subject, amend: args.includes("--amend") };
			}

			writes.push({ op, seg, commit: commitInfo });
		}

		if (blockReason) return { block: true, reason: blockReason };
		if (writes.length === 0) return undefined;

		if (!ctx.hasUI) {
			return {
				block: true,
				reason: "Blocked: git write in a non-interactive session (cannot ask for approval). Repeat interactively.",
			};
		}

		const pendingCommit = writes.find((w) => w.commit !== null)?.commit ?? null;
		if (pendingCommit) {
			const branch = runGit(sessionCwd, ["rev-parse", "--abbrev-ref", "HEAD"]).out || "(unknown)";
			const repoName = repoRoot ? path.basename(repoRoot) : path.basename(sessionCwd);
			const body = commitDialogBody(sessionCwd, pendingCommit.message, chainStages, pendingCommit.amend);
			const choice = await ctx.ui.select(`Commit in ${repoName} (branch ${branch})\n\n${body}`, [
				"Conferma",
				"Rifiuta",
			]);
			if (choice !== "Conferma") {
				const reason = await askRejectReason(ctx, "the commit");
				return {
					block: true,
					reason:
						`Commit rejected by the user. Reason: "${reason}". DO NOT retry the same commit. ` +
						`Fix what the user asked (staged files, message, or content), then retry.`,
				};
			}
			return undefined;
		}

		const title =
			writes.some((w) => w.op === "push") ? "Confirm git push" : "Confirm git operation";
		const choice = await ctx.ui.select(
			`${title}\n\n${writes.map((w) => `$ ${describe(w.op, w.seg, sessionCwd)}`).join("\n")}`,
			["Conferma", "Rifiuta"],
		);
		if (choice !== "Conferma") {
			const what = writes.some((w) => w.op === "push") ? "the push" : "the git operation";
			const reason = await askRejectReason(ctx, what);
			return { block: true, reason: `${what} rejected by the user. Reason: "${reason}".` };
		}
		return undefined;
	});
}
