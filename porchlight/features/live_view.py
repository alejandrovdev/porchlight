"""Read-only live view of one session the Remote Control server started.

    view(project, session, mac)   what the command `view <project> <session id, cse_...>` runs

Prints the session's conversation and keeps following it: what the user wrote, what
Claude answered, and one line per tool call. Every control character in them but tabs and
line breaks is replaced first: what a model or a tool writes never reaches the terminal as
an escape sequence. Nothing typed here reaches the session; it
is driven from the phone. The view ends by itself a moment after the session's process
ends (the session was archived), which closes the terminal tab that runs it
(`view_tabs` opens that tab).
"""

import re
import shutil
import sys
import textwrap
from pathlib import Path

from .. import names
from ..atoms import processes, transcripts, worktrees
from ..atoms.text import printable

COMMAND = "view"  # the command of the tool that a tab runs
SESSION = re.compile(re.escape(names.SERVER_SESSION) + r"[A-Za-z0-9]+")
HISTORY = 30  # how many earlier items to show when the view opens
NOT_CONVERSATION = (
    "<task-notification>",
    "<system-reminder>",
    "<local-command-",
    "<command-name>",
    "<command-message>",
)
DETAIL_KEYS = ("description", "file_path", "path", "pattern", "query", "url", "skill", "prompt", "command")
STYLE = {"user": "\033[1;36m", "assistant": "", "tool": "\033[2m", "note": "\033[2;3m"}
RESET = "\033[0m"


def server_processes(ps_text):
    """The sessions some server is running on this Mac: {session: pid}.

    Main sessions only, never a run a session starts (`claude -p`, `--print` with a model,
    `--bg`, `daemon-worker`): those have no server address or no session id of the server.
    """
    found = {}
    for pid, program, arguments in processes.rows(ps_text):
        if Path(program).name != "claude":
            continue
        if "--print" not in arguments or "--sdk-url" not in arguments:
            continue
        if "--session-id" not in arguments[:-1]:
            continue
        session = arguments[arguments.index("--session-id") + 1]
        if SESSION.fullmatch(session):
            found[session] = pid
    return found


def live_sessions(ps_text, worktrees_folder):
    """The sessions the server is running, with a worktree in this folder: {session: pid}."""
    return {
        session: pid
        for session, pid in server_processes(ps_text).items()
        if (Path(worktrees_folder) / (worktrees.SERVER_PREFIX + session)).is_dir()
    }


def command(project, session, porchlight):
    """What the tab of a view runs. `porchlight` is the tool as a shell reads it; a
    project's name and a session's id are plain words."""
    return "exec %s %s %s %s" % (porchlight, COMMAND, project.name, session)


def transcript(project, session, mac):
    """The transcript of a server session, or None while it has none."""
    worktree = worktrees.of_server_session(names.repository(project), session)
    return transcripts.server_transcript(transcripts.folder(mac.transcripts, worktree))


def tool_line(name, tool_input):
    detail = ""
    if isinstance(tool_input, dict):
        candidates = [tool_input.get(key) for key in DETAIL_KEYS] + list(tool_input.values())
        for value in candidates:
            if isinstance(value, str) and value.strip():
                detail = " ".join(value.split())
                break
    line = "%s · %s" % (name, detail) if detail else str(name)
    return line if len(line) <= 120 else line[:119] + "…"


def shown(text):
    """Text as the view prints it: each control character but tabs and line breaks
    replaced, half characters dropped."""
    return printable(str(text).replace("\r\n", "\n"), keep="\t\n")


def render(entry):
    """The conversation items of one transcript line: (kind, text) pairs, printable."""
    if entry.get("isSidechain") or entry.get("isMeta"):
        return []
    content = (entry.get("message") or {}).get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
    if not isinstance(blocks, list):
        return []
    items = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = shown(block.get("text") or "").strip()
        if entry.get("type") == "user":
            if block.get("type") == "text" and text and not text.startswith(NOT_CONVERSATION):
                items.append(("user", text))
        elif entry.get("type") == "assistant":
            if block.get("type") == "text" and text:
                items.append(("assistant", text))
            elif block.get("type") == "tool_use":
                items.append(("tool", shown(tool_line(block.get("name"), block.get("input")))))
    return items


def items_of(lines):
    return [item for entry in transcripts.entries(lines) for item in render(entry)]


def plain(text):
    """A printed line without its colors."""
    return re.sub(r"\033\[[0-9;]*m", "", text).rstrip()


def terminal_columns():
    return shutil.get_terminal_size((100, 40)).columns


class Screen:
    def __init__(self, out=None, width=terminal_columns):
        self.out = out or self.write
        self.columns = width
        self.last_kind = None

    @staticmethod
    def write(line):
        print(line)
        sys.stdout.flush()

    def show(self, kind, text):
        width = max(40, min(self.columns() - 2, 118))
        prefix = {"user": "▌ ", "tool": "  · "}.get(kind, "")
        if kind != "tool" or self.last_kind != "tool":
            self.out("")
        for paragraph in text.splitlines() or [""]:
            wrapped = textwrap.wrap(paragraph, width - len(prefix)) or [""]
            for line in wrapped:
                self.out(STYLE[kind] + prefix + line + RESET)
        self.last_kind = kind


def running(pid, session, mac):
    """Whether a process is still that session's; True when ps cannot tell, to keep the view open."""
    shown = mac.command_of(pid)
    return True if shown is None else session in shown.split()


def follow(project, session, mac, screen=None):
    screen = screen or Screen()
    live = live_sessions(mac.processes(), worktrees.folder(names.repository(project)))
    if session not in live:
        screen.show("note", "Session %s is not running on this Mac." % session)
        mac.sleep(4)
        return 1
    pid = live[session]
    screen.show("note", "%s · read-only view · type from the phone · closes when archived" % session)

    path = transcript(project, session, mac)
    while path is None and running(pid, session, mac):
        mac.sleep(1)
        path = transcript(project, session, mac)
    if path is None:
        return 0

    with open(path, "rb") as handle:
        lines, rest = transcripts.finished_lines(handle.read())
        items = items_of(lines)
        if len(items) > HISTORY:
            screen.show("note", "… %d earlier items not shown" % (len(items) - HISTORY))
        for kind, text in items[-HISTORY:]:
            screen.show(kind, text)

        checked = mac.clock()
        while True:
            chunk = handle.read()
            if chunk:
                lines, rest = transcripts.finished_lines(rest + chunk)
                for kind, text in items_of(lines):
                    screen.show(kind, text)
                continue
            if mac.clock() - checked > 3:
                checked = mac.clock()
                if not running(pid, session, mac):
                    break
            mac.sleep(0.5)

        lines, rest = transcripts.finished_lines(rest + handle.read())
        for kind, text in items_of(lines):
            screen.show(kind, text)
    screen.show("note", "The session ended (archived). Closing this tab.")
    mac.sleep(3)
    return 0


def view(project, session, mac, out=print):
    """What the tab runs: the view of one session, until it ends or the user closes it.
    0 when the session ended or the view was closed, 1 when the session does not run here."""
    try:
        return follow(project, session, mac, Screen(None if out is print else out))
    except KeyboardInterrupt:
        return 0
